"""The C of the binding of a module to the static core (`<name>_binding.c`): what has to name the symbols that wasm2c made for this module, made from the model.

It holds no rule. The adapters turn an array of `wasmext_val` into a typed call of wasm2c (one adapter for each distinct signature, the typed function is a
field of the export); `instantiate`/`release` catch a trap of the start function; for each import there is the function that wasm2c declares, which looks at the
slot of the import and calls the host (the typed function when it was given, else the uniform one with the values packed). See docs/specs/S0003-instances.md."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

from ._gen import (
    _CTYPE as _GEN_CTYPE,
)
from ._gen import (
    _MULTI_CODE as _GEN_MULTI_CODE,
)
from ._gen import (
    _RT_TYPE as _GEN_RT_TYPE,
)
from ._gen import (
    GenError,
    _p2_headers,
    mangle,
    module_prefix,
)
from ._model import VALTYPE_BYTES, ImportFact, ModuleModel
from ._wasm import FuncType, GlobalType, Limits, TableType, ValType

__all__ = ["binding_headers", "generate_binding"]

_FIELD: dict[ValType, str] = {"i32": "i32", "i64": "i64", "f32": "f32", "f64": "f64"}
_REFS = ("funcref", "externref")
# the old glue refuses an externref (and so lacks it in these tables); the binding carries it: the pointer of a record of the store (docs/specs/S0006-externref.md)
_CTYPE: dict[ValType, str] = {**_GEN_CTYPE, "externref": "wasm_rt_externref_t"}
_MULTI_CODE: dict[ValType, str] = {**_GEN_MULTI_CODE, "externref": "e"}
_RT_TYPE: dict[ValType, str] = {**_GEN_RT_TYPE, "externref": "WASM_RT_EXTERNREF"}
# the letters of a signature in a record (wasmext_instance_signature_ of the core): F is a funcref and E an externref, so a link compares them as letters (docs/specs/S0008-shared-store.md)
_SIG_LETTER: dict[ValType, str] = {
    "i32": "i",
    "i64": "j",
    "f32": "f",
    "f64": "d",
    "v128": "o",
    "funcref": "F",
    "externref": "E",
}


def _ret(ft: FuncType) -> str:
    if len(ft.results) > 1:
        return "struct wasm_multi_" + "".join(_MULTI_CODE[t] for t in ft.results)
    return _CTYPE[ft.results[0]] if ft.results else "void"


def _pack(t: ValType, dst: str, src: str) -> str:
    """Statement that puts the C value `src` into the wasmext_val `dst`."""
    byte = VALTYPE_BYTES[t]
    if t == "funcref":
        # the caller points `as.ref` at a `wasmext_funcref` to be filled (the core checks it before the call and sets its store and owner after)
        return f"{dst}.type = {byte:#x}; ((wasmext_funcref *){dst}.as.ref)->ref = {src};"
    if t == "externref":
        return f"{dst}.type = {byte:#x}; {dst}.as.ref = {src};"
    if t == "v128":
        return f"{dst}.type = {byte:#x}; memcpy({dst}.as.v128, &{src}, 16);"
    cast = {"i32": "(int32_t)", "i64": "(int64_t)", "f32": "", "f64": ""}[t]
    return f"{dst}.type = {byte:#x}; {dst}.as.{_FIELD[t]} = {cast}{src};"


def _unpack(t: ValType, src: str, dst: str) -> str:
    """Statement that takes the wasmext_val `src`, whose type must be `t`, into the C lvalue `dst`; a wrong type is a trap of the host."""
    byte = VALTYPE_BYTES[t]
    check = f"if ({src}.type != {byte:#x}) wasm_rt_trap(WASMEXT_TRAP_HOST); "
    if t == "v128":
        return check + f"memcpy(&{dst}, {src}.as.v128, 16);"
    cast = {"i32": "(u32)", "i64": "(u64)", "f32": "", "f64": ""}[t]
    return check + f"{dst} = {cast}{src}.as.{_FIELD[t]};"


def _adapter(name: str, ft: FuncType, reentrant: bool) -> list[str]:
    several = len(ft.results) > 1
    ret = _ret(ft)
    ptypes = "".join(f", {_CTYPE[t]}" for t in ft.params)
    pre: list[str] = []
    args = ""
    for k, t in enumerate(ft.params):
        if t == "externref":
            args += f", a[{k}].as.ref"
        elif t == "funcref":
            pre.append(
                f"wasm_rt_funcref_t t{k}; if (a[{k}].as.ref) t{k} = ((const wasmext_funcref *)a[{k}].as.ref)->ref; else memset(&t{k}, 0, sizeof t{k});"
            )
            args += f", t{k}"
        elif t == "v128":
            pre.append(f"v128 t{k}; memcpy(&t{k}, a[{k}].as.v128, 16);")
            args += f", t{k}"
        else:
            cast = {"i32": "(u32)", "i64": "(u64)", "f32": "", "f64": ""}[t]
            args += f", {cast}a[{k}].as.{_FIELD[t]}"
    sig = (
        " ".join(str(VALTYPE_BYTES[t]) for t in ft.params)
        + " -> "
        + " ".join(str(VALTYPE_BYTES[t]) for t in ft.results)
    )
    out = [
        f"/* ({sig}) */",
        f"static int {name}(void *inst, void *fn, const wasmext_val *a, wasmext_val *r) {{",
        "    (void)a; (void)r;",
    ]
    out += [f"    {x}" for x in pre]
    if ft.results:
        out.append(f"    {ret} res;")
    out.append(
        "    WASMEXT_ENTER_REENTRANT(trap_, { return (int)trap_; })"
        if reentrant
        else "    WASMEXT_ENTER_PLAIN(trap_, { return (int)trap_; })"
    )
    call = f"(({ret} (*)(void *{ptypes}))fn)(inst{args})"
    out.append(f"    {'res = ' if ft.results else ''}{call};")
    out.append("    WASMEXT_LEAVE_REENTRANT();" if reentrant else "    WASMEXT_LEAVE_PLAIN();")
    for j, t in enumerate(ft.results):
        out.append("    " + _pack(t, f"r[{j}]", f"res.{_MULTI_CODE[t]}{j}" if several else "res"))
    out += ["    return 0;", "}", ""]
    return out


def _forwarder(c_module: str, c_name: str, slot: int, ft: FuncType) -> list[str]:
    """The function that wasm2c declares for an import: the slot decides between the typed host function and the uniform one."""
    params = "".join(f", {_CTYPE[t]} a{k}" for k, t in enumerate(ft.params))
    head = [
        f"{_ret(ft)} {c_name}(struct {c_module} *h{params}) {{",
        f"    wasmext_import_slot *s = &h->slot[{slot}];",
    ]
    # a typed function of a slot is a host function (without references: `bind_typed` refuses them) or the shim of a linked export, which takes a funcref by value and checks it as it comes in
    return _slot_call(head, ft, typed=True)


def _trampoline(name: str, ft: FuncType) -> list[str]:
    """The function of an element of a table that stands for a function of the host: `module_instance` is its slot (a `wasmext_import_slot` that starts the record of the function), and
    the call is made as the call of an import is, by the uniform shape."""
    params = "".join(f", {_CTYPE[t]} a{k}" for k, t in enumerate(ft.params))
    head = [
        f"static {_ret(ft)} {name}(void *h_{params}) {{",
        "    wasmext_import_slot *s = (wasmext_import_slot *)h_;",
    ]
    return _slot_call(head, ft, typed=False)


def _slot_call(head: list[str], ft: FuncType, *, typed: bool) -> list[str]:
    """The body that calls the host function of the slot `s`: the typed one when there is one (if `typed`), else the uniform one with the values packed."""
    several = len(ft.results) > 1
    ret = _ret(ft)
    ptypes = "".join(f", {_CTYPE[t]}" for t in ft.params)
    names = "".join(f", a{k}" for k in range(len(ft.params)))
    n_a, n_r = max(len(ft.params), 1), max(len(ft.results), 1)
    out = list(head)
    if ft.results:
        out.append(f"    {ret} res;")
    if typed:
        out += [
            "    if (s->typed) {",
            "        int trapped = 0;",
            f"        {'res = ' if ft.results else ''}(({ret} (*)(void *{ptypes}, int *))s->typed)(s->user{names}, &trapped);",
            "        if (trapped == WASMEXT_HOST_THROW) wasmext_throw_pending_();",
            "        if (trapped) wasm_rt_trap(WASMEXT_TRAP_OF(trapped));",
        ]
        # only the shim of a linked export has a reference in its signature (the callee's artifact and store checks are in the shim; the answer of the callee is checked for this one)
        out += [
            f"        if (wasmext_link_funcref_((wasmext_instance *)s->self, &{f'res.{_MULTI_CODE[t]}{j}' if several else 'res'})) wasm_rt_trap(WASMEXT_TRAP_HOST);"
            for j, t in enumerate(ft.results)
            if t == "funcref"
        ]
        out.append("    } else {")
    else:
        out.append("    {")
    out += [
        f"        wasmext_val a[{n_a}], r[{n_r}];",
        "        int rc;",
    ]
    out += [f"        wasmext_funcref f{k};" for k, t in enumerate(ft.params) if t == "funcref"]
    out.append("        memset(a, 0, sizeof a); memset(r, 0, sizeof r);")
    for k, t in enumerate(ft.params):
        if t == "funcref":
            out.append(
                f"        if (wasmext_funcref_from_(s->self, &a{k}, &f{k})) wasm_rt_trap(WASMEXT_TRAP_HOST); a[{k}].type = 0x70; a[{k}].as.ref = &f{k};"
            )
        elif t == "externref":
            out.append(f"        {_pack(t, f'a[{k}]', f'a{k}')}")
        else:
            out.append(f"        {_pack(t, f'a[{k}]', f'a{k}')}")
    out += [
        "        rc = s->host(s->user, a, r);",
        "        if (rc == WASMEXT_HOST_THROW) wasmext_throw_pending_();",
        "        if (rc) wasm_rt_trap(WASMEXT_TRAP_OF(rc));",
    ]
    for j, t in enumerate(ft.results):
        dst = f"res.{_MULTI_CODE[t]}{j}" if several else "res"
        if t == "funcref":
            out.append(
                f"        if (wasmext_funcref_result_(s->self, &r[{j}], &{dst})) wasm_rt_trap(WASMEXT_TRAP_HOST);"
            )
        elif t == "externref":
            out.append(
                f"        if (wasmext_extern_result_(s->self, &r[{j}], &{dst})) wasm_rt_trap(WASMEXT_TRAP_HOST);"
            )
        else:
            out.append(f"        {_unpack(t, f'r[{j}]', dst)}")
    out += ["    }"]
    out += ["    return res;" if ft.results else "    return;", "}", ""]
    return out


def generate_binding(model: ModuleModel) -> str:
    """The C source of `<last>_binding.c`: `extern const wasmext_binding <last>_binding`. The descriptor is `<last>_descriptor` (see _descriptor.py)."""
    for imp in model.imports:
        if isinstance(imp.type, TableType) and (imp.type.limits.is64 or imp.type.limits.shared):
            raise GenError(
                f"{model.name}: the import {imp.module}.{imp.name} is a 64-bit or a shared table; only the tables of 32 bits that are not shared are carried"
            )
    last = model.last
    prefix = module_prefix(model.name)
    inst_t = f"w2c_{prefix}"
    reentrant = bool(model.imports)
    core = [imp for imp in model.imports if imp.core]
    if core and not any(e.kind == "memory" and e.name == "memory" for e in model.exports):
        raise GenError(f"{model.name}: a module with WASI imports exports its memory as 'memory'; this one does not")
    if (
        core
        and model.host == "wasm32-wasip2"
        and not any(e.kind == "func" and e.name == "cabi_realloc" for e in model.exports)
    ):
        raise GenError(
            f"{model.name}: a module of WASI 0.2 exports cabi_realloc (the canonical ABI allocates in it); this one does not"
        )
    tag_names = {
        k: f"w2c_{mangle(imp.module, module=True)}_{mangle(imp.name)}"
        for k, imp in enumerate(model.imports)
        if imp.kind == "tag"
    }
    out = [
        "/* Generated by wasmext: the binding of the module to the core (wasmext_instance.h). */",
        "/* the header of wasm2c includes windows.h, and the sockets of fusedwasi winsock2.h, which does not go with the winsock.h that windows.h brings unless this is set first */",
        "#if defined(_WIN32) && !defined(WIN32_LEAN_AND_MEAN)",
        "#define WIN32_LEAN_AND_MEAN",
        "#endif",
        *[
            f"#define {c} wasmext_declared_{c}  /* the header declares the tag as const; it is defined below, writable (wasm2c has no slot for a tag: the import is a symbol) */"
            for c in tag_names.values()
        ],
        f'#include "{last}_w2c.h"',
        *[f"#undef {c}" for c in tag_names.values()],
        '#include "wasmext_instance.h"',
        *(['#include "wasmext_host.h"'] if core else []),
        *[f'#include "fusedwasi/{h}"' for h in binding_headers(model)],
        "#if defined(__BYTE_ORDER__) && defined(__ORDER_BIG_ENDIAN__) && __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__",
        '#error "wasmext: v128 is not supported on big-endian hosts"',
        "#endif",
        "",
        f"extern const wasmext_descriptor {last}_descriptor;",
        "",
    ]
    # the modules the imports come from, in the order wasm2c takes them (the first appearance), each with the slots of its functions
    # wasm2c takes the structures of the import modules in the order of their names (UTF-8 bytes), not of the first import
    by_module: dict[str, list[ImportFact]] = {}
    for imp in model.imports:
        by_module.setdefault(imp.module, []).append(imp)
    modules = sorted(by_module, key=lambda m: m.encode("utf-8"))
    c_mod = {m: f"w2c_{mangle(m, module=True)}" for m in modules}
    fslot, rslot = _layout(model)
    # the imported tags: a global of wasm2c's that the module reads whenever it throws or catches; the core writes the tag of the exporter into it when the import is linked (once for the process)
    out += [f"wasm_rt_tag_t {c};" for c in tag_names.values()]
    for m in modules:
        nf = sum(1 for imp in by_module[m] if imp.kind == "func")
        nr = len(by_module[m]) - nf
        out.append(f"struct {c_mod[m]} {{ wasmext_import_slot slot[{max(nf, 1)}]; void *ref[{max(nr, 1)}]; }};")
    out += [
        f"struct {last}_block {{",
        f"    {inst_t} inst;  /* first: the pointer to the instance of wasm2c is the pointer to the block */",
        *[f"    struct {c_mod[m]} m{n};" for n, m in enumerate(modules)],
        *(
            [
                "    wasmext_host *host;",
                "    fusedwasi_p2_guest guest;  /* the caller of fusedwasi: this instance's memory, trap and end of call */",
                "    uint32_t signalled;",
            ]
            if core
            else []
        ),
        "};",
        "",
    ]
    if core:
        out += _core_functions(model, last, prefix, modules, by_module)
    for k, imp in enumerate(model.imports):
        c_name = f"{c_mod[imp.module]}_{mangle(imp.name)}"
        if imp.kind == "tag":
            continue  # a symbol, defined above
        if imp.kind == "func":
            assert isinstance(imp.type, FuncType)
            out += _forwarder(c_mod[imp.module], c_name, fslot[k][1], imp.type)
        else:
            if isinstance(imp.type, GlobalType):
                ctype = _CTYPE[imp.type.type]
            elif isinstance(imp.type, TableType):
                ctype = "wasm_rt_externref_table_t" if imp.type.elem == "externref" else "wasm_rt_funcref_table_t"
            else:
                assert isinstance(imp.type, Limits)
                ctype = "wasm_rt_memory_t"
            out.append(
                f"{ctype} *{c_name}(struct {c_mod[imp.module]} *h) {{ return ({ctype} *)h->ref[{rslot[k][1]}]; }}"
            )
    out.append("")
    adapters: dict[tuple[tuple[ValType, ...], tuple[ValType, ...]], str] = {}
    for e in model.exports:
        if e.kind == "func":
            ft = e.type
            assert isinstance(ft, FuncType)
            key = (ft.params, ft.results)
            if key not in adapters:
                adapters[key] = f"{last}_adapt{len(adapters)}"
                out += _adapter(adapters[key], ft, reentrant)
    shims: dict[int, str] = {}
    for n, e in enumerate(model.exports):
        if e.kind == "func":
            ft = e.type
            assert isinstance(ft, FuncType)
            shims[n] = f"{last}_shim{n}"
            out += _shim(shims[n], last, prefix, e.name, ft)
    # the types of the type section that `call_ref` can call an element of: each with the type as wasm2c knows it (the hash that `call_indirect` compares), an adapter (always the reentrant
    # one: the function is of any instance of the store, and the call may be made from inside a host function), and the signature
    ref_rows: list[str] = []
    seen_types: list[tuple[tuple[ValType, ...], tuple[ValType, ...]]] = []
    for ft in model.module.types:
        if (ft.params, ft.results) in seen_types:
            continue
        k = len(seen_types)
        seen_types.append((ft.params, ft.results))
        types = "".join(f", {_RT_TYPE[t]}" for t in (*ft.params, *ft.results))
        out += _adapter(f"{last}_radapt{k}", ft, True)
        out += _trampoline(f"{last}_tramp{k}", ft)
        out += [
            f"static const uint8_t {last}_rtp{k}[] = {{{', '.join(str(VALTYPE_BYTES[t]) for t in ft.params) or '0'}}};",
            f"static const uint8_t {last}_rtr{k}[] = {{{', '.join(str(VALTYPE_BYTES[t]) for t in ft.results) or '0'}}};",
            f"static const char *{last}_rt{k}(void) {{ return wasm2c_{prefix}_get_func_type({len(ft.params)}, {len(ft.results)}{types}); }}",
            "",
        ]
        ref_rows.append(
            f"{{{last}_rt{k}, {last}_radapt{k}, {{{len(ft.params)}, {len(ft.results)}, {last}_rtp{k}, {last}_rtr{k}}}, (void *)(void (*)(void)){last}_tramp{k}}}"
        )
    if ref_rows:
        out.append(f"static const wasmext_ref_type {last}_ref_types[] = {{")
        out += [f"    {r}," for r in ref_rows]
        out += ["};", ""]
    # the tags the module can see: the ones it exports (their identity is the global of wasm2c) and the ones it imports (what was linked): how their payloads are read and made
    tag_rows: list[str] = []
    tag_sigs: dict[tuple[ValType, ...], int] = {}
    tag_entries: list[tuple[str, tuple[ValType, ...]]] = []  # (the C function of the identity, the types of the values)
    for n, e in enumerate(model.exports):
        if e.kind == "tag":
            assert isinstance(e.type, FuncType)
            # the tag of the module, as wasm2c exports it (a global of the type `const wasm_rt_tag_t`): the identity that `throw` and `catch` compare
            out += [
                f"static void *{last}_tag{n}(void *inst_) {{ (void)inst_; return (void *)w2c_{prefix}_{mangle(e.name)}; }}",
                "",
            ]
    # every tag of the module, in the order of its index space: the imported ones (what was linked), then the ones it defines, whether it exports them or keeps them to itself. The tags it defines
    # are read from the table `wasmext_tags_<prefix>` that the build puts in the C of wasm2c (`_export_tags` of _natify.py), since wasm2c makes them `static`.
    for k, imp in enumerate(model.imports):
        if imp.kind == "tag":
            assert isinstance(imp.type, FuncType)
            out += [f"static void *{last}_tagi{k}(void *inst_) {{ (void)inst_; return (void *){tag_names[k]}; }}", ""]
            tag_entries.append((f"{last}_tagi{k}", imp.type.params))
    if model.module.tags:
        out.append(f"extern const wasm_rt_tag_t wasmext_tags_{prefix}[{len(model.module.tags)}];")
    for j, tag_type in enumerate(model.module.tags):
        out += [
            f"static void *{last}_tagd{j}(void *inst_) {{ (void)inst_; return (void *)wasmext_tags_{prefix}[{j}]; }}",
            "",
        ]
        tag_entries.append((f"{last}_tagd{j}", tag_type.params))
    for ident, sig in tag_entries:
        if sig not in tag_sigs:
            tag_sigs[sig] = len(tag_sigs)
            out += _tag_payload(f"{last}_tp{tag_sigs[sig]}", sig)
        t = tag_sigs[sig]
        ref = any(v in _REFS for v in sig)
        params = f"{last}_tpv{t}"
        out_types = ", ".join(str(VALTYPE_BYTES[v]) for v in sig) or "0"
        out.append(f"static const uint8_t {params}_{len(tag_rows)}[] = {{{out_types}}};")
        size = f"sizeof(struct {last}_tp{t})" if sig else "0"
        dec = "0" if ref else f"{last}_tp{t}_dec"
        enc = "0" if ref else f"{last}_tp{t}_enc"
        tag_rows.append(
            f"{{(const void *(*)(void *)){ident}, {{{len(sig)}, 0, {params}_{len(tag_rows)}, 0}}, {size}, {dec}, {enc}}}"
        )
    if tag_rows:
        out.append(f"static const wasmext_tag_binding {last}_tags[] = {{")
        out += [f"    {r}," for r in tag_rows]
        out += ["};", ""]
    refs: dict[int, str] = {}
    for n, e in enumerate(model.exports):
        if e.kind == "func":
            assert isinstance(e.type, FuncType)
            refs[n] = f"{last}_ref{n}"
            out += _ref_filler(refs[n], last, prefix, e.name, e.type)
    enter = "WASMEXT_ENTER_REENTRANT" if reentrant else "WASMEXT_ENTER_PLAIN"
    leave = "WASMEXT_LEAVE_REENTRANT" if reentrant else "WASMEXT_LEAVE_PLAIN"
    wasm_args = "".join(f", &b->m{n}" for n in range(len(modules)))
    setup: list[str] = []
    if core:
        setup = [f"    {last}_core_setup(b, (wasmext_host *)host);"]
    out += [
        f"static int {last}_instantiate(void *block, void *host) {{",
        f"    struct {last}_block *b = (struct {last}_block *)block;",
        "    (void)host;",
        *setup,
        f"    {enter}(trap_, {{ if (trap_ != WASMEXT_TRAP_NO_MEMORY) wasm2c_{prefix}_free(&b->inst); memset(&b->inst, 0, sizeof b->inst); return (int)trap_; }})",
        f"    wasm2c_{prefix}_instantiate(&b->inst{wasm_args});",
        f"    {leave}();",
        "    return 0;",
        "}",
        f"static void {last}_release(void *block) {{ wasm2c_{prefix}_free(&((struct {last}_block *)block)->inst); }}",
        "",
    ]
    if fslot:
        out += [
            f"static wasmext_import_slot *{last}_import_slot(void *block, uint32_t k) {{",
            f"    struct {last}_block *b = (struct {last}_block *)block;",
            "    switch (k) {",
            *[f"    case {k}: return &b->m{n_mod}.slot[{slot}];" for k, (n_mod, slot) in sorted(fslot.items())],
            "    default: return 0;",
            "    }",
            "}",
            "",
        ]
    if rslot:
        out += [
            f"static void **{last}_ref_slot(void *block, uint32_t k) {{",
            f"    struct {last}_block *b = (struct {last}_block *)block;",
            "    switch (k) {",
            *[
                f"    case {k}: return (void **)&{tag_names[k]};"
                if k in tag_names
                else f"    case {k}: return &b->m{n_mod}.ref[{slot}];"
                for k, (n_mod, slot) in sorted(rslot.items())
            ],
            "    default: return 0;",
            "    }",
            "}",
            "",
        ]
    rows: list[str] = []
    for n, e in enumerate(model.exports):
        if e.kind == "func":
            ft = e.type
            assert isinstance(ft, FuncType)
            sig = "".join(_SIG_LETTER[t] for t in ft.params) + ">" + "".join(_SIG_LETTER[t] for t in ft.results)
            shim = f"(void *){shims[n]}"
            rows.append(
                f"{{{adapters[(ft.params, ft.results)]}, (void *)(void (*)(void))w2c_{prefix}_{mangle(e.name)}, 0, {shim}, {_c_lit(sig)}, {refs[n]}}}"
            )
            continue
        elif e.kind == "tag":
            assert isinstance(e.type, FuncType)
            sig = "".join(_SIG_LETTER[t] for t in e.type.params) + ">"
            rows.append(f"{{0, 0, {last}_tag{n}, 0, {_c_lit(sig)}, 0}}")
            continue
        elif e.kind in ("memory", "global", "table"):
            # wasm2c's accessor: `wasm_rt_memory_t *f(w2c_<p> *)` for a memory, `T *f(w2c_<p> *)` for a global (the pointer to its value), `wasm_rt_funcref_table_t *f(w2c_<p> *)` for a table
            rows.append(f"{{0, 0, (void *(*)(void *))w2c_{prefix}_{mangle(e.name)}, 0, 0, 0}}")
            continue
        rows.append("{0, 0, 0, 0, 0, 0}")
    out.append(f"static const wasmext_export_binding {last}_export_bindings[] = {{")
    out += [f"    {r}," for r in rows] or ["    {0, 0, 0, 0, 0, 0},"]
    out += [
        "};",
        "",
        f"const wasmext_binding {last}_binding = {{&{last}_descriptor, sizeof(struct {last}_block), {last}_instantiate, {last}_release, {last}_export_bindings, "
        + (f"{last}_import_slot" if fslot else "0")
        + (f", {last}_ref_slot" if rslot else ", 0")
        + (f", {last}_call_begin, {last}_wasi_end" if core else ", 0, 0")
        + (f", {last}_ref_types, {len(ref_rows)}" if ref_rows else ", 0, 0")
        + (f", {last}_tags, {len(tag_rows)}" if tag_rows else ", 0, 0")
        + (
            ", WASMEXT_HOST_LAYOUT_ID" if core else ", 0"
        )  # the layout of the host this binding reads (wasmext_host.h); checked against the one the host of the store was set with
        + "};",
        "",
    ]
    return "\n".join(out)


def _shim(name: str, last: str, prefix: str, export: str, ft: FuncType) -> list[str]:
    """The typed function that another instance calls through the record of this export: it enters the store of this instance, catches a trap of its own module and answers
    it as WASMEXT_TRAP_LINKED + its code, so the trap goes through the caller as one of its own (the buffer of the caller is put back: the entry is the reentrant one).
    A funcref or an externref comes in by value (`wasm_rt_funcref_t`, `void *`) and is checked here, as a call of the host is: a reference that no member of the store stands behind, or a funcref of
    another artifact (the temporary guard of S0008, removed by 8b), is answered in `*trapped` (not as a trap of the callee)."""
    ret = _ret(ft)
    params = "".join(f", {_CTYPE[t]} a{k}" for k, t in enumerate(ft.params))
    args = "".join(f", a{k}" for k in range(len(ft.params)))
    give = "return zero;" if ft.results else "return;"
    out = [
        f"static {ret} {name}(void *self_{params}, int *trapped) {{",
        "    wasmext_instance *self = (wasmext_instance *)self_;",
        f"    struct {last}_block *b = (struct {last}_block *)self->module;",
        "    int line, rc;",
        "    long level;",
    ]
    if ft.results:
        out += [f"    {ret} zero;", "    memset(&zero, 0, sizeof zero);"]
    for k, t in enumerate(ft.params):
        if t == "funcref":
            out.append(f"    rc = wasmext_link_funcref_(self, &a{k}); if (rc) {{ *trapped = rc; {give} }}")
        elif t == "externref":
            out.append(f"    rc = wasmext_link_extern_(self, a{k}); if (rc) {{ *trapped = rc; {give} }}")
    out += [
        "    rc = wasmext_instance_begin_(self, &line, &level);",
        f"    if (rc) {{ *trapped = (int)WASMEXT_TRAP_LINKED + rc; {give} }}",
        f"    WASMEXT_ENTER_REENTRANT(trap_, {{ wasmext_instance_end_(self, line, level); *trapped = (int)WASMEXT_TRAP_LINKED + (int)trap_; {give} }})",
    ]
    call = f"w2c_{prefix}_{mangle(export)}(&b->inst{args})"
    if ft.results:
        out += [
            f"    {ret} res = {call};",
            "    WASMEXT_LEAVE_REENTRANT();",
            "    wasmext_instance_end_(self, line, level);",
            "    return res;",
        ]
    else:
        out += [f"    {call};", "    WASMEXT_LEAVE_REENTRANT();", "    wasmext_instance_end_(self, line, level);"]
    out += ["}", ""]
    return out


def _tag_payload(name: str, sig: tuple[ValType, ...]) -> list[str]:
    """The payload of an exception of a tag with these value types, as the runtime of wasm2c keeps it (the values one after the other in a struct of the natural layout, which is what its
    `struct wasm_multi_...` is, or the value alone for one), with the function that reads it into values and the one that makes it of values. None with a reference among the values."""
    if any(v in _REFS for v in sig):
        return []
    members = "".join(f" {_CTYPE[v]} v{j};" for j, v in enumerate(sig))
    out = [f"struct {name} {{{members or ' char none;'} }};"]
    out.append(f"static void {name}_dec(const void *p, wasmext_val *out) {{")
    # the runtime keeps the payload in a byte buffer that is not aligned for the struct: copy it, as wasm2c does
    out.append(f"    struct {name} xv, *x = &xv;")
    out.append("    (void)x; (void)out;")
    out.append("    memcpy(&xv, p, sizeof xv);")
    for j, v in enumerate(sig):
        if v == "v128":
            out.append(f"    out[{j}].type = 0x7b; memcpy(out[{j}].as.v128, &x->v{j}, 16);")
        else:
            cast = {"i32": "(int32_t)", "i64": "(int64_t)", "f32": "", "f64": ""}[v]
            out.append(f"    out[{j}].type = {VALTYPE_BYTES[v]:#x}; out[{j}].as.{_FIELD[v]} = {cast}x->v{j};")
    out += [
        "}",
        f"static int {name}_enc(const wasmext_val *v, void *p) {{",
        f"    struct {name} xv, *x = &xv;",
        "    (void)x; (void)v; (void)p;",
        "    memset(&xv, 0, sizeof xv);",
    ]
    for j, v in enumerate(sig):
        if v == "v128":
            out.append(f"    memcpy(&x->v{j}, v[{j}].as.v128, 16);")
        else:
            cast = {"i32": "(u32)", "i64": "(u64)", "f32": "", "f64": ""}[v]
            out.append(f"    x->v{j} = {cast}v[{j}].as.{_FIELD[v]};")
    out += ["    memcpy(p, &xv, sizeof xv);", "    return 0;", "}", ""]
    return out


def _ref_filler(name: str, last: str, prefix: str, export: str, ft: FuncType) -> list[str]:
    """Fills the element of a table that stands for the export: its type (the one of this module, whose hash the elements of any module with the type share), the function itself (called as
    `result f(void *instance, parameters...)`) and the instance. No tail-call variant: a call that is a tail call goes through the plain one."""
    types = "".join(f", {_RT_TYPE[t]}" for t in (*ft.params, *ft.results))
    return [
        f"static void {name}(void *block, wasm_rt_funcref_t *r) {{",
        "    memset(r, 0, sizeof *r);",
        f"    r->module_instance = &((struct {last}_block *)block)->inst;",
        f"    r->func_type = wasm2c_{prefix}_get_func_type({len(ft.params)}, {len(ft.results)}{types});",
        f"    r->func = (wasm_rt_function_ptr_t)(void (*)(void))w2c_{prefix}_{mangle(export)};",
        "}",
        "",
    ]


def _c_lit(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _layout(model: ModuleModel) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    """Where each import is: by the index of the import in the descriptor, (the number of its module in the order wasm2c passes them in, its place among the
    function slots of the module) for a function and (..., its place among the pointers) for a memory or a global."""
    order: dict[str, list[int]] = {}
    for k, imp in enumerate(model.imports):
        order.setdefault(imp.module, []).append(k)
    fslot: dict[int, tuple[int, int]] = {}
    rslot: dict[int, tuple[int, int]] = {}
    for n_mod, module in enumerate(sorted(order, key=lambda m: m.encode("utf-8"))):
        nf = nr = 0
        for k in order[module]:
            if model.imports[k].kind == "func":
                fslot[k] = (n_mod, nf)
                nf += 1
            else:
                rslot[k] = (n_mod, nr)
                nr += 1
    return fslot, rslot


def binding_headers(model: ModuleModel) -> tuple[str, ...]:
    """The headers of fusedwasi (in its tree, below `fusedwasi/`) that the binding includes for the imports the core answers, dependencies first: `p1/wasi_p1.h` for WASI 0.1; for 0.2
    the core, the streams, `cli` and the files that the host needs, and the header of each function."""
    core = [imp for imp in model.imports if imp.core and imp.core_call]
    if not core:
        return ()
    if model.host == "wasm32-wasip2":
        calls = {(imp.module, imp.name): imp.core_call for imp in core if imp.core_call}
        return tuple("p2/" + h for h in _p2_headers(calls, include=True))
    return tuple(sorted({imp.core_header for imp in core if imp.core_header}))


def _core_functions(
    model: ModuleModel, last: str, prefix: str, modules: list[str], by_module: dict[str, list[ImportFact]]
) -> list[str]:
    """For WASI 0.1: the guest of an instance (its hooks), the typed function of each import the core answers, and the setup that binds them into the slots."""
    del modules, by_module
    out = [
        "/* the hooks of the guest of an instance of WASI 0.1 */",
        f"static void {last}_guest_trap(fusedwasi_p2_guest *g, const char *message) {{ wasmext_host_trap_(g->state, message); }}",
        f"static void {last}_guest_exit(fusedwasi_p2_guest *g, uint32_t code) {{ g->exited = 1; g->exit_code = code; wasm_rt_trap(WASMEXT_TRAP_HOST); }}",
    ]
    if model.host == "wasm32-wasip2":
        out += [
            f"static uint32_t {last}_guest_realloc(fusedwasi_p2_guest *g, uint32_t comp, uint32_t old_ptr, uint32_t old_size, uint32_t align, uint32_t new_size) {{",
            f"    struct {last}_block *b = (struct {last}_block *)g->user;",
            "    (void)comp;",
            f"    return w2c_{prefix}_{mangle('cabi_realloc')}(&b->inst, old_ptr, old_size, align, new_size);",
            "}",
            "",
        ]
    else:
        out += [
            f"static uint32_t {last}_guest_signal(fusedwasi_p2_guest *g, uint32_t number) {{",
            f"    struct {last}_block *b = (struct {last}_block *)g->user;",
            "    if (!wasmext_signal_ends(number)) return 0;",
            "    b->signalled = number;",
            "    wasm_rt_trap(WASMEXT_TRAP_HOST);",
            "}",
            "",
        ]
    for k, imp in enumerate(imp for imp in model.imports if imp.core):
        ft = imp.type
        assert isinstance(ft, FuncType)
        ret = _ret(ft)
        params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(ft.params))
        args = "".join(f", a{j}" for j in range(len(ft.params)))
        out += [
            f"/* {imp.module}.{imp.name}: fusedwasi on the guest of this instance, under the lock of the host */",
            f"static {ret} {last}_core{k}(void *user{params}, int *trapped) {{",
            f"    struct {last}_block *b = (struct {last}_block *)user;",
            "    (void)trapped;",
            *([f"    {ret} res;"] if ft.results else []),
            "    wasmext_rlock_lock(&b->host->lock);",
            f"    {'res = ' if ft.results else ''}{imp.core_call}(&b->guest{', 0' if imp.core_comp else ''}{args});",
            "    wasmext_rlock_unlock(&b->host->lock);  /* a trap does not come back here: the caller of the instance lets the lock go (wasmext_rlock_release_to) */",
            *(["    return res;"] if ft.results else []),
            "}",
            "",
        ]
    mem = f"w2c_{prefix}_{mangle('memory')}"
    out += [
        f"static void {last}_core_setup(struct {last}_block *b, wasmext_host *host) {{",
        f"    wasm_rt_memory_t *memory = {mem}(&b->inst);",
        "    b->host = host;",
        "    fusedwasi_p2_guest_init(&b->guest, &host->wasi);",
        "    b->guest.user = b;",
        f"    b->guest.trap = {last}_guest_trap;",
        f"    b->guest.exit = {last}_guest_exit;",
        f"    b->guest.{'realloc' if model.host == 'wasm32-wasip2' else 'signal'} = {last}_guest_{'realloc' if model.host == 'wasm32-wasip2' else 'signal'};",
        "    if (host->wait != NULL) b->guest.wait = host->wait;",
        "    fusedwasi_p2_bind_memory(&b->guest, 0, &memory->data, &memory->size);  /* read at each access, so a memory that grows needs nothing */",
    ]
    # the slots: found by the index of the import in the descriptor
    fslot, _ = _layout(model)
    core_k = 0
    for k, imp in enumerate(model.imports):
        if not imp.core:
            continue
        n_mod, slot = fslot[k]
        out.append(
            f"    b->m{n_mod}.slot[{slot}].typed = (void *){last}_core{core_k}; b->m{n_mod}.slot[{slot}].host = 0; b->m{n_mod}.slot[{slot}].user = b;"
        )
        core_k += 1
    out += [
        "}",
        f"static void {last}_call_begin(void *block) {{",
        f"    struct {last}_block *b = (struct {last}_block *)block;",
        "    b->guest.exited = 0;",
        "    b->signalled = 0;",
        "}",
        f"static int {last}_wasi_end(void *block, uint32_t *value) {{",
        f"    struct {last}_block *b = (struct {last}_block *)block;",
        "    if (b->guest.exited) { *value = b->guest.exit_code; return WASMEXT_END_EXIT; }",
        "    if (b->signalled) { *value = b->signalled; return WASMEXT_END_SIGNAL; }",
        "    return WASMEXT_END_NONE;",
        "}",
        "",
    ]
    return out
