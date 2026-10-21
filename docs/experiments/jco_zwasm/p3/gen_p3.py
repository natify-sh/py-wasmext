"""Glue for a WASI 0.3 core module (unbundled from a wasm32-wasip3 C component) compiled by wasm2c: every import is mapped
to a function of p3host.c by its (interface without version, name); stream/future builtins are matched by kind.
usage: python gen_p3.py MODULE.wasm NAME -> NAME_imports.c"""

import re
import subprocess
import sys

WT = "/home/claude/tools/wasm-tools-1.262.0-x86_64-linux/wasm-tools"
CT = {"i32": "u32", "i64": "u64"}


def mangle(s):
    """wasm2c's name mangling: letters and digits kept; '_' kept unless it starts the name or follows an emitted '_'."""
    out = ""
    for c in s:
        if c.isalnum() or (c == "_" and out and out[-1] != "_"):
            out += c
        else:
            out += f"0x{ord(c):02X}"
    return out


def target(mod, name):
    iface = mod.split("@")[0]
    rules = [
        (r"\[stream-new-\d+\]", "p3_stream_new"), (r"\[stream-drop-readable-\d+\]", "p3_stream_drop_readable"),
        (r"\[stream-drop-writable-\d+\]", "p3_stream_drop_writable"), (r"\[async-lower\]\[stream-write-\d+\]", "p3_stream_write"),
        (r"\[async-lower\]\[stream-read-\d+\]", "p3_stream_read"), (r"\[stream-cancel-(read|write)-\d+\]", "p3_stream_cancel"),
        (r"\[async-lower\]\[future-read-\d+\]", "p3_future_read"), (r"\[future-drop-readable-\d+\]", "p3_future_drop_readable"),
        (r"\[resource-drop\]", "p3_noop1"),
    ]
    for pat, fn in rules:
        if re.match(pat, name):
            return fn
    table = {
        ("$root", "[waitable-set-new]"): "p3_ws_new", ("$root", "[waitable-join]"): "p3_ws_join",
        ("$root", "[waitable-set-drop]"): "p3_ws_drop", ("$root", "[waitable-set-wait]"): "p3_ws_wait",
        ("$root", "[waitable-set-poll]"): "p3_ws_poll", ("$root", "[subtask-cancel]"): "p3_subtask_cancel",
        ("$root", "[subtask-drop]"): "p3_noop1",
        ("env", "__wasm_get_stack_pointer"): "p3_get_sp", ("env", "__wasm_set_stack_pointer"): "p3_set_sp",
        ("env", "__wasm_get_tls_base"): "p3_get_tls", ("env", "__wasm_set_tls_base"): "p3_set_tls",
        ("wasi:cli/stdin", "read-via-stream"): "p3_stdin_read_via_stream",
        ("wasi:cli/stdout", "write-via-stream"): "p3_stdout_write_via_stream",
        ("wasi:cli/stderr", "write-via-stream"): "p3_stderr_write_via_stream",
        ("wasi:cli/terminal-stdin", "get-terminal-stdin"): "p3_option_none",
        ("wasi:cli/terminal-stdout", "get-terminal-stdout"): "p3_option_none",
        ("wasi:cli/terminal-stderr", "get-terminal-stderr"): "p3_option_none",
        ("wasi:clocks/monotonic-clock", "now"): "p3_monotonic_now",
        ("wasi:clocks/monotonic-clock", "[async-lower]wait-for"): "p3_wait_for",
        ("wasi:clocks/monotonic-clock", "[async-lower]wait-until"): "p3_wait_until",
        ("wasi:clocks/system-clock", "now"): "p3_system_now",
    }
    return table.get((iface, name))


def main():
    wasm, name = sys.argv[1], sys.argv[2]
    out = subprocess.run([WT, "print", wasm], check=True, capture_output=True, text=True).stdout
    types = {m[1]: (" ".join(re.findall(r"\(param ([^)]*)\)", m[2])).split(), " ".join(re.findall(r"\(result ([^)]*)\)", m[3])).split())
             for m in re.finditer(r"\(type \(;(\d+);\) \(func((?: \(param[^)]*\))*)((?: \(result[^)]*\))*)\)\)", out)}
    imps = [(m[1], m[2], *types[m[3]]) for m in re.finditer(r'\(import "([^"]+)" "([^"]+)" \(func (?:\S+ )?\(;\d+;\) \(type (\d+)\)', out)]
    c = [f'#include "{name}.h"', '#include "p3host.h"', ""]
    for m in sorted({m for m, *_ in imps}):
        c.append(f"struct w2c_{mangle(m)} {{ int u; }}; struct w2c_{mangle(m)} E_{mangle(m)};")
    missing = []
    for m, n, params, results in imps:
        fn = target(m, n)
        if not fn:
            missing.append((m, n))
            continue
        ret = CT[results[0]] if results else "void"
        args = "".join(f", {CT[p]} a{j}" for j, p in enumerate(params))
        call = f"{fn}({', '.join(f'a{j}' for j in range(len(params)))})"
        c.append(f"{ret} w2c_{mangle(m)}_{mangle(n)}(struct w2c_{mangle(m)} *e{args}) {{ (void)e; {'return ' if results else ''}{call}; }}")
    open(f"{name}_imports.c", "w").write("\n".join(c) + "\n")
    with open(f"{name}_args.h", "w") as f:
        mods = sorted({m for m, *_ in imps})
        f.write("".join(f"extern struct w2c_{mangle(m)} E_{mangle(m)};\n" for m in mods))
        f.write("#define INST_ARGS " + ", ".join(f"&E_{mangle(m)}" for m in mods) + "\n")
    print(f"{name}_imports.c: {len(imps)} imports, unmapped: {missing}")


main()
