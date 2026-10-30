"""The C of the binding of a module to the static core (`<name>_binding.c`): what has to name the symbols that wasm2c made for this module, made from the model.

It holds no rule. The adapters turn an array of `wasmext_val` into a typed call of wasm2c (one adapter for each distinct signature, the typed function is a
field of the export); `instantiate`/`release` catch a trap of the start function; for each import there is the function that wasm2c declares, which looks at the
slot of the import and calls the host (the typed function when it was given, else the uniform one with the values packed). See docs/step3_instances.md."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

from ._gen import (
    _CTYPE,
    _MULTI_CODE,
    _RT_TYPE,
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


def _supported(ft: FuncType) -> bool:
    """A signature the binding carries: a funcref is (a `wasmext_funcref` by pointer), an externref is not yet (step 6)."""
    return "externref" not in (*ft.params, *ft.results)


def _has_funcref(ft: FuncType) -> bool:
    return "funcref" in (*ft.params, *ft.results)


def _linkable(ft: FuncType) -> bool:
    """A function that another instance can import by the typed shape (`result f(void *instance, parameters..., int *trapped)`): a funcref is a struct, which that shape does not carry."""
    return _supported(ft) and not _has_funcref(ft)


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
        if t == "funcref":
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
    return _slot_call(head, ft, typed=not _has_funcref(ft))  # a funcref is a struct: only the uniform shape carries it


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
            "        if (trapped) wasm_rt_trap(WASMEXT_TRAP_OF(trapped));",
            "    } else {",
        ]
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
        else:
            out.append(f"        {_pack(t, f'a[{k}]', f'a{k}')}")
    out += [
        "        rc = s->host(s->user, a, r);",
        "        if (rc) wasm_rt_trap(WASMEXT_TRAP_OF(rc));",
    ]
    for j, t in enumerate(ft.results):
        dst = f"res.{_MULTI_CODE[t]}{j}" if several else "res"
        if t == "funcref":
            out.append(
                f"        if (wasmext_funcref_result_(s->self, &r[{j}], &{dst})) wasm_rt_trap(WASMEXT_TRAP_HOST);"
            )
        else:
            out.append(f"        {_unpack(t, f'r[{j}]', dst)}")
    out += ["    }"]
    out += ["    return res;" if ft.results else "    return;", "}", ""]
    return out


def generate_binding(model: ModuleModel) -> str:
    """The C source of `<last>_binding.c`: `extern const wasmext_binding <last>_binding`. The descriptor is `<last>_descriptor` (see _descriptor.py)."""
    for imp in model.imports:
        if imp.kind == "tag":
            raise GenError(
                f"{model.name}: the import {imp.module}.{imp.name} is a tag; that is step 7 of docs/step3_instances.md"
            )
        if isinstance(imp.type, TableType) and (
            imp.type.elem != "funcref" or imp.type.limits.is64 or imp.type.limits.shared
        ):
            raise GenError(
                f"{model.name}: the import {imp.module}.{imp.name} is a table of {imp.type.elem} (or 64-bit, or shared); only funcref tables are carried (externref is step 6 of docs/layers.md)"
            )
        if isinstance(imp.type, FuncType) and not _supported(imp.type):
            raise GenError(
                f"{model.name}: the import {imp.module}.{imp.name} has an externref in its signature; that is step 6 of docs/layers.md"
            )
        if isinstance(imp.type, GlobalType) and imp.type.type in _REFS:
            raise GenError(
                f"{model.name}: the import {imp.module}.{imp.name} is a global of {imp.type.type}; that is step 5 or 6 of docs/step3_instances.md"
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
    out = [
        "/* Generated by wasmext: the binding of the module to the core (wasmext_instance.h). */",
        "/* the header of wasm2c includes windows.h, and the sockets of fusedwasi winsock2.h, which does not go with the winsock.h that windows.h brings unless this is set first */",
        "#if defined(_WIN32) && !defined(WIN32_LEAN_AND_MEAN)",
        "#define WIN32_LEAN_AND_MEAN",
        "#endif",
        f'#include "{last}_w2c.h"',
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
        if imp.kind == "func":
            assert isinstance(imp.type, FuncType)
            out += _forwarder(c_mod[imp.module], c_name, fslot[k][1], imp.type)
        else:
            if isinstance(imp.type, GlobalType):
                ctype = _CTYPE[imp.type.type]
            elif isinstance(imp.type, TableType):
                ctype = "wasm_rt_funcref_table_t"
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
            if _supported(ft) and key not in adapters:
                adapters[key] = f"{last}_adapt{len(adapters)}"
                out += _adapter(adapters[key], ft, reentrant)
    shims: dict[int, str] = {}
    for n, e in enumerate(model.exports):
        if e.kind == "func":
            ft = e.type
            assert isinstance(ft, FuncType)
            if _linkable(ft):
                shims[n] = f"{last}_shim{n}"
                out += _shim(shims[n], last, prefix, e.name, ft)
    # the types of the type section that `call_ref` can call an element of: each with the type as wasm2c knows it (the hash that `call_indirect` compares), an adapter (always the reentrant
    # one: the function is of any instance of the store, and the call may be made from inside a host function), and the signature
    ref_rows: list[str] = []
    seen_types: list[tuple[tuple[ValType, ...], tuple[ValType, ...]]] = []
    for ft in model.module.types:
        if not _supported(ft) or (ft.params, ft.results) in seen_types:
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
    refs: dict[int, str] = {}
    for n, e in enumerate(model.exports):
        if e.kind == "func":
            assert isinstance(e.type, FuncType)
            if _supported(e.type):
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
            *[f"    case {k}: return &b->m{n_mod}.ref[{slot}];" for k, (n_mod, slot) in sorted(rslot.items())],
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
            if _supported(ft):
                sig = "".join(_MULTI_CODE[t] for t in ft.params) + ">" + "".join(_MULTI_CODE[t] for t in ft.results)
                shim = f"(void *){shims[n]}" if n in shims else "0"
                rows.append(
                    f"{{{adapters[(ft.params, ft.results)]}, (void *)(void (*)(void))w2c_{prefix}_{mangle(e.name)}, 0, {shim}, {_c_lit(sig)}, {refs[n]}}}"
                )
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
        + "};",
        "",
    ]
    return "\n".join(out)


def _shim(name: str, last: str, prefix: str, export: str, ft: FuncType) -> list[str]:
    """The typed function that another instance calls through the record of this export: it enters the store of this instance, catches a trap of its own module and answers
    it as WASMEXT_TRAP_LINKED + its code, so the trap goes through the caller as one of its own (the buffer of the caller is put back: the entry is the reentrant one)."""
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
