"""C glue for a core module made by `meld fuse` (several components fused into one module with one memory per component),
compiled by wasm2c. Imports of the fused module are of three kinds:

- WASI 0.2 functions: zwasm's host (zw_register / zw_call). meld keeps one copy of a WASI import per component that lowers
  it, suffixing the later copies with `$<component>`: the copy decides which memory and which cabi_realloc the call uses.
- resource intrinsics left by meld (`[resource-new]`, `[resource-rep]`, `[resource-drop]` of a resource defined inside the
  fused module): one handle table in C; a drop calls the resource's `[dtor]` export.

usage: python fused_glue.py MODULE.wasm NAME --mem DEFAULT=<memory export>:<realloc export> [--mem <suffix>=...]
                            [--dtor <resource>=<dtor export>]
Export names are given in wasm2c's mangled form (as in NAME.h). Writes NAME_glue.c with `int glue_init(w2c_NAME *)`.
"""

import re
import subprocess
import sys

WT = "/home/claude/tools/wasm-tools-1.262.0-x86_64-linux/wasm-tools"
CT = {"i32": "u32", "i64": "u64", "f32": "f32", "f64": "f64"}


def mangle(s):
    """wasm2c's name mangling: letters and digits kept; '_' kept unless it starts the name or follows an emitted '_'."""
    out = ""
    for c in s:
        if c.isalnum() or (c == "_" and out and out[-1] != "_"):
            out += c
        else:
            out += f"0x{ord(c):02X}"
    return out


def imports(wasm: str):
    out = subprocess.run([WT, "print", wasm], check=True, capture_output=True, text=True).stdout
    types = {}
    for m in re.finditer(r"\(type \(;(\d+);\) \(func((?: \(param[^)]*\))*)((?: \(result[^)]*\))*)\)\)", out):
        types[m[1]] = (" ".join(re.findall(r"\(param ([^)]*)\)", m[2])).split(),
                       " ".join(re.findall(r"\(result ([^)]*)\)", m[3])).split())
    for m in re.finditer(r'\(import "([^"]+)" "([^"]+)" \(func (?:\S+ )?\(;\d+;\) \(type (\d+)\)', out):
        yield m[1], m[2], *types[m[3]]


def main() -> None:
    wasm, name = sys.argv[1], sys.argv[2]
    mems, dtors = {}, {}
    for i, a in enumerate(sys.argv):
        if a == "--mem":
            k, v = sys.argv[i + 1].split("=", 1)
            mems[k] = v.split(":")
        if a == "--dtor":
            k, v = sys.argv[i + 1].split("=", 1)
            dtors[k] = v
    header = open(f"{name}.h").read()
    imps = list(imports(wasm))
    c = [f'#include "{name}.h"', "#include <stdio.h>", "#include <stdlib.h>", "",
         "int zw_init(void); void zw_set_realloc(u32 (*)(u32, u32)); int zw_register(const char *, const char *);",
         "int zw_call(int, u8 *, size_t, const u64 *, size_t, u64 *); const char *zw_last_error(void); int zw_exit_code(void);",
         "", f"static w2c_{name} *I;", ""]
    for key, (mem, rea) in mems.items():
        c.append(f"static u32 realloc_{mangle(key)}(u32 size, u32 align) {{ return w2c_{name}_{rea}(I, 0, 0, align, size); }}")
    c += ["", "/* resource intrinsics: one table, handle = index + 1 */",
          "static struct { u32 rep; int live; } RT[1024]; static u32 nrt;",
          "static u32 rt_new(u32 rep) { if (nrt == 1024) wasm_rt_trap(WASM_RT_TRAP_EXHAUSTION); RT[nrt].rep = rep; RT[nrt].live = 1; return ++nrt; }",
          "static u32 rt_rep(u32 h) { if (h == 0 || h > nrt || !RT[h - 1].live) wasm_rt_trap(WASM_RT_TRAP_UNREACHABLE); return RT[h - 1].rep; }",
          "static int n_new, n_rep, n_drop;", ""]
    wasi, mods = [], sorted({m for m, *_ in imps})
    for m in mods:
        c.append(f"struct w2c_{mangle(m)} {{ int unused; }}; struct w2c_{mangle(m)} E_{mangle(m)};")
    c.append("")
    for (m, n, params, results) in imps:
        fn = f"w2c_{mangle(m)}_{mangle(n)}"
        assert fn + "(" in header, fn
        ret = CT[results[0]] if results else "void"
        args = "".join(f", {CT[p]} a{j}" for j, p in enumerate(params))
        base, _, suffix = n.partition("$")
        res = re.match(r"\[resource-(new|rep|drop)\](.+)", base)
        if res and not m.startswith("wasi:"):
            kind, rname = res[1], res[2]
            if kind == "new":
                body = "n_new++; return rt_new(a0);"
            elif kind == "rep":
                body = "n_rep++; return rt_rep(a0);"
            else:
                body = f"n_drop++; u32 rep = rt_rep(a0); RT[a0 - 1].live = 0; w2c_{name}_{dtors[rname]}(I, rep);"
            c.append(f"{ret} {fn}(struct w2c_{mangle(m)} *e{args}) {{ (void)e; {body} }}")
            continue
        key = suffix or "DEFAULT"
        mem, _ = mems[key]
        idx = len(wasi)
        wasi.append((m, base))
        vals = ", ".join(f"(u64)a{j}" for j in range(len(params))) or "0"
        call = (f"u64 r = 0; wasm_rt_memory_t *mm = w2c_{name}_{mem}(I); zw_set_realloc(realloc_{mangle(key)}); "
                f"int rc = zw_call(W[{idx}], mm->data, (size_t)mm->size, (const u64[]){{{vals}}}, {len(params)}, &r); "
                f"if (rc == 2) {{ fflush(stdout); exit(zw_exit_code()); }} "
                f'if (rc) {{ fprintf(stderr, "[glue] {m} {n}: %s\\n", zw_last_error()); wasm_rt_trap(WASM_RT_TRAP_UNREACHABLE); }}')
        body = f"{call} return ({ret})r;" if results else call
        c.append(f"{ret} {fn}(struct w2c_{mangle(m)} *e{args}) {{ (void)e; {body} }}")
    c.insert(9, f"static int W[{max(len(wasi), 1)}];")
    c += ["", f"int glue_init(w2c_{name} *inst) {{",
          "  I = inst; int missing = 0;",
          *[f'  if ((W[{i}] = zw_register("{m}", "{b}")) < 0) {{ missing++; fprintf(stderr, "[glue] not in host: {m} {b}\\n"); }}'
            for i, (m, b) in enumerate(wasi)],
          f'  fprintf(stderr, "[glue] {name}: %d WASI imports bound to zwasm, %d missing; {len(imps) - len(wasi)} resource intrinsics in C\\n", {len(wasi)} - missing, missing);',
          "  return missing;", "}",
          'void glue_stats(void) { fprintf(stderr, "[glue] resource.new %d, rep %d, drop %d\\n", n_new, n_rep, n_drop); }',
          "#define GLUE_INST_ARGS " + ", ".join(f"&E_{mangle(m)}" for m in mods)]
    open(f"{name}_glue.c", "w").write("\n".join(c) + "\n")
    open(f"{name}_glue_args.h", "w").write(
        "".join(f"extern struct w2c_{mangle(m)} E_{mangle(m)};\n" for m in mods)
        + "#define GLUE_INST_ARGS " + ", ".join(f"&E_{mangle(m)}" for m in mods) + "\n"
        + f"int glue_init(w2c_{name} *); void glue_stats(void); int zw_init(void);\n")
    print(f"{name}_glue.c: {len(imps)} imports: {len(wasi)} WASI, {len(imps) - len(wasi)} resource intrinsics")


main()
