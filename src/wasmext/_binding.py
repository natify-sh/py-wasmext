"""The C of the binding of a module to the static core (`<name>_binding.c`): what has to name the symbols that wasm2c made for this module, made from the model.

It holds no rule. The adapters turn an array of `wasmext_val` into a typed call of wasm2c (one adapter for each distinct signature, the typed function is a
field of the export); `instantiate`/`release` catch a trap of the start function; for each import there is the function that wasm2c declares, which looks at the
slot of the import and calls the host (the typed function when it was given, else the uniform one with the values packed). See docs/step3_instances.md."""

from __future__ import annotations

from ._gen import _CTYPE, _MULTI_CODE, GenError, _p2_headers, mangle, module_prefix  # pyright: ignore[reportPrivateUsage]
from ._model import VALTYPE_BYTES, ImportFact, ModuleModel
from ._wasm import FuncType, ValType

__all__ = ["binding_headers", "generate_binding"]

_FIELD: dict[ValType, str] = {"i32": "i32", "i64": "i64", "f32": "f32", "f64": "f64"}
_REFS = ("funcref", "externref")


def _supported(ft: FuncType) -> bool:
    return not any(t in _REFS for t in (*ft.params, *ft.results))


def _ret(ft: FuncType) -> str:
    if len(ft.results) > 1:
        return "struct wasm_multi_" + "".join(_MULTI_CODE[t] for t in ft.results)
    return _CTYPE[ft.results[0]] if ft.results else "void"


def _pack(t: ValType, dst: str, src: str) -> str:
    """Statement that puts the C value `src` into the wasmext_val `dst`."""
    byte = VALTYPE_BYTES[t]
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
        if t == "v128":
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
    several = len(ft.results) > 1
    ret = _ret(ft)
    params = "".join(f", {_CTYPE[t]} a{k}" for k, t in enumerate(ft.params))
    ptypes = "".join(f", {_CTYPE[t]}" for t in ft.params)
    names = "".join(f", a{k}" for k in range(len(ft.params)))
    n_a, n_r = max(len(ft.params), 1), max(len(ft.results), 1)
    out = [
        f"{ret} {c_name}(struct {c_module} *h{params}) {{",
        f"    wasmext_import_slot *s = &h->slot[{slot}];",
    ]
    if ft.results:
        out.append(f"    {ret} res;")
    out += [
        "    if (s->typed) {",
        "        int trapped = 0;",
        f"        {'res = ' if ft.results else ''}(({ret} (*)(void *{ptypes}, int *))s->typed)(s->user{names}, &trapped);",
        "        if (trapped) wasm_rt_trap(WASMEXT_TRAP_OF(trapped));",
        "    } else {",
        f"        wasmext_val a[{n_a}], r[{n_r}];",
        "        int rc;",
        "        memset(a, 0, sizeof a); memset(r, 0, sizeof r);",
    ]
    out += [f"        {_pack(t, f'a[{k}]', f'a{k}')}" for k, t in enumerate(ft.params)]
    out += [
        "        rc = s->host(s->user, a, r);",
        "        if (rc) wasm_rt_trap(WASMEXT_TRAP_OF(rc));",
    ]
    out += [
        f"        {_unpack(t, f'r[{j}]', f'res.{_MULTI_CODE[t]}{j}' if several else 'res')}"
        for j, t in enumerate(ft.results)
    ]
    out += ["    }"]
    out += ["    return res;" if ft.results else "    return;", "}", ""]
    return out


def generate_binding(model: ModuleModel) -> str:
    """The C source of `<last>_binding.c`: `extern const wasmext_binding <last>_binding`. The descriptor is `<last>_descriptor` (see _descriptor.py)."""
    for imp in model.imports:
        if imp.kind != "func":
            raise GenError(
                f"{model.name}: the import {imp.module}.{imp.name} is a {imp.kind}; those are linked in step 3d of docs/step3_instances.md"
            )
        assert isinstance(imp.type, FuncType)
        if not _supported(imp.type):
            raise GenError(
                f"{model.name}: the import {imp.module}.{imp.name} has a reference type in its signature; that is step 5 or 6 of docs/step3_instances.md"
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
    for m in modules:
        out.append(f"struct {c_mod[m]} {{ wasmext_import_slot slot[{len(by_module[m])}]; }};")
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
    for m in modules:
        for slot, imp in enumerate(by_module[m]):
            assert isinstance(imp.type, FuncType)
            out += _forwarder(c_mod[m], f"{c_mod[m]}_{mangle(imp.name)}", slot, imp.type)
    adapters: dict[tuple[tuple[ValType, ...], tuple[ValType, ...]], str] = {}
    for e in model.exports:
        if e.kind == "func":
            ft = e.type
            assert isinstance(ft, FuncType)
            key = (ft.params, ft.results)
            if _supported(ft) and key not in adapters:
                adapters[key] = f"{last}_adapt{len(adapters)}"
                out += _adapter(adapters[key], ft, reentrant)
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
    if model.imports:
        out += [
            f"static wasmext_import_slot *{last}_import_slot(void *block, uint32_t k) {{",
            f"    struct {last}_block *b = (struct {last}_block *)block;",
            "    switch (k) {",
        ]
        for k, imp in enumerate(model.imports):
            out.append(
                f"    case {k}: return &b->m{modules.index(imp.module)}.slot[{by_module[imp.module].index(imp)}];"
            )
        out += ["    default: return 0;", "    }", "}", ""]
    rows: list[str] = []
    for e in model.exports:
        if e.kind == "func":
            ft = e.type
            assert isinstance(ft, FuncType)
            if _supported(ft):
                rows.append(
                    f"{{{adapters[(ft.params, ft.results)]}, (void *)(void (*)(void))w2c_{prefix}_{mangle(e.name)}}}"
                )
                continue
        rows.append("{0, 0}")
    out.append(f"static const wasmext_export_binding {last}_export_bindings[] = {{")
    out += [f"    {r}," for r in rows] or ["    {0, 0},"]
    out += [
        "};",
        "",
        f"const wasmext_binding {last}_binding = {{&{last}_descriptor, sizeof(struct {last}_block), {last}_instantiate, {last}_release, {last}_export_bindings, "
        + (f"{last}_import_slot" if model.imports else "0")
        + (f", {last}_call_begin, {last}_wasi_end" if core else ", 0, 0")
        + "};",
        "",
    ]
    return "\n".join(out)


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
    # the slots: found by the index of the import in its module
    index = {
        id(imp): (n_mod, slot) for n_mod, (_, imports) in enumerate(_group(model)) for slot, imp in enumerate(imports)
    }
    for k, imp in enumerate(imp for imp in model.imports if imp.core):
        n_mod, slot = index[id(imp)]
        out.append(
            f"    b->m{n_mod}.slot[{slot}].typed = (void *){last}_core{k}; b->m{n_mod}.slot[{slot}].host = 0; b->m{n_mod}.slot[{slot}].user = b;"
        )
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


def _group(model: ModuleModel) -> list[tuple[str, list[ImportFact]]]:
    """The imports by the module they come from, in the order wasm2c passes the structures in: the names of the modules, as UTF-8 bytes."""
    order: dict[str, list[ImportFact]] = {}
    for imp in model.imports:
        order.setdefault(imp.module, []).append(imp)
    return sorted(order.items(), key=lambda item: item[0].encode("utf-8"))
