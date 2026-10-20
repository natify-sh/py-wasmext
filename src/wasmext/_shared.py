"""The C API of a module as a shared library (item 10 of FEATURES.md, stage 6a): a public header `<name>_api.h` for any host language and the C that
exports it, `<name>_shared.c`, on the typed functions of `<name>_glue.h`. No Python in either.

The life of an instance: `<name>_new(&config, &error)` (WASI is made and bound there), `<name>_set_import<k>(m, function, user)` for each import that is not WASI's
(a host function is `result f(void *user, parameters..., int *trapped)`: it answers through `trapped`, nonzero when it failed, and keeps its error itself, as the
protocol of errors says), `<name>_instantiate(m)` (0, or the code of a trap), then the exports as `int <name>_<export>(m, parameters..., results...)`, which answer 0 or the
code of the trap (`<name>_trap_message(code)` is its text); `<name>_free(m)`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ._wasm import FuncType, GlobalType, ValType

# the C types of the public header (no wasm2c types in it)
_API_TYPE: dict[ValType, str] = {"i32": "int32_t", "i64": "int64_t", "f32": "float", "f64": "double"}
_RESERVED = {
    "new",
    "free",
    "instantiate",
    "trap_message",
    "wasi_end",
    "exception",
    "config",
    "t",
    "value",
    "thread_free",
}


@dataclass
class ApiModel:
    """What the C API of a module has, by the names of the module: the header and the wrapper for ctypes are both made from it."""

    last: str
    uses_wasi: bool = False
    has_tags: bool = False
    exports: list[tuple[str, str, FuncType]] = field(
        default_factory=list[tuple[str, str, FuncType]]
    )  # name, C function, type
    memories: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])  # name, C function
    globals: list[tuple[str, str, str | None, ValType]] = field(
        default_factory=list[tuple[str, str, str | None, ValType]]
    )  # name, C getter, C setter (None: immutable), type
    imports: list[tuple[int, str, str, FuncType, bool]] = field(
        default_factory=list[tuple[int, str, str, FuncType, bool]]
    )  # k (the C function is <last>_set_import<k>), module, field, type, whether it is a call of WASI (that the core has)
    skipped: list[str] = field(default_factory=list[str])


def _ident(name: str, taken: set[str]) -> str:
    """A C identifier for an export, different from those taken (and from the names of the API, and the `call<n>` of the glue)."""
    base = re.sub(r"[^0-9A-Za-z_]", "_", name) or "export"
    if base[0].isdigit():
        base = f"_{base}"
    out, n = base, 1
    while (
        out in taken
        or out in _RESERVED
        or re.fullmatch(r"call\d+|set_import\d+|memory_\w+|global_\w+|set_global_\w+|wasi_\w+|glue_\w+|instance", out)
    ):
        n += 1
        out = f"{base}_{n}"
    taken.add(out)
    return out


def unsupported(imports: list[tuple[str, str, FuncType]], *, global_imports: bool, memory_imports: bool) -> str | None:
    """Why the module has no shared library yet, or None."""
    if global_imports or memory_imports:
        return "it imports a global or a memory"
    for module, field_, func in imports:
        if "v128" in (*func.params, *func.results):
            return f"the import {module}.{field_} uses v128"
    return None


def generate_shared(
    last: str,
    prefix: str,
    funcs: list[tuple[str, FuncType]],
    memories: list[str],
    imports: list[
        tuple[str, str, FuncType, bool, int, int]
    ],  # module, field, type, whether it is WASI's, the host, the slot (in the glue)
    uses_wasi: bool,
    tags: int,
    skipped: list[str] | None = None,
    globals_: list[tuple[str, GlobalType]] | None = None,
) -> tuple[str, str, ApiModel]:
    """The public header, the C of the library and the model of the API; `funcs` are the exports in the order of the glue (`<name>_call<i>`). An export with a v128 is left out
    of the header (and said there)."""
    from ._gen import _CTYPE, _MULTI_CODE, _c_string, mangle  # pyright: ignore[reportPrivateUsage]

    big = last.upper()
    model = ApiModel(
        last,
        uses_wasi=uses_wasi,
        has_tags=bool(tags),
        skipped=[x for x in skipped or () if "is not an attribute" not in x],
    )
    taken: set[str] = set()
    a: list[str] = []  # the header
    c: list[str] = []  # the C
    A, C = a.append, c.append
    A(
        f"/* The C API of the WebAssembly module {last}, made by wasmext: do not edit. No Python in it; any host language that can call C can use the library. */"
    )
    A(f"#ifndef WASMEXT_API_{big}_H")
    A(f"#define WASMEXT_API_{big}_H")
    A("#include <stddef.h>")
    A("#include <stdint.h>")
    A("#ifdef __cplusplus")
    A('extern "C" {')
    A("#endif")
    A("#ifndef WASMEXT_API")
    A("#if defined(_WIN32) && defined(WASMEXT_BUILDING)")
    A("#define WASMEXT_API __declspec(dllexport)")
    A("#elif defined(_WIN32)")
    A("#define WASMEXT_API __declspec(dllimport)")
    A("#else")
    A('#define WASMEXT_API __attribute__((visibility("default")))')
    A("#endif")
    A("#endif")
    A("")
    A(
        "/* The codes that a call answers (0 is success): those of the runtime of wasm2c (see the _trap_message of the module) and these. */"
    )
    A(f"#define {big}_TRAP_HOST 0x7000  /* a host function answered with a failure; its error is the host's */")
    A(f"#define {big}_TRAP_NO_MEMORY 0x7001")
    A(f"#define {big}_TRAP_ENDED 0x7002  /* the WASI program is over: {last}_wasi_end says how */")
    A(f"#define {big}_LINK_ERROR 0x7003  /* an import was not set before {last}_instantiate */")
    A(
        f"#define {big}_HOOK_TRAP 0x10000  /* what a hook of WASI answers for a failure of its own (a positive number below it is an errno of WASI) */"
    )
    A("")
    A(f"typedef struct {last}_t {last}_t;")
    A("")
    A(
        "/* The configuration of WASI (every field may be 0): arguments, `NAME=value` strings, directories as `host::guest` (the guest name is `/` when it is left out),"
    )
    A(
        "   and hooks for the standard streams, the clocks, the random bytes and sleeping: a hook answers 0, an errno of WASI, or HOOK_TRAP; without one the core uses descriptors 0, 1 and 2 and the system. */"
    )
    A("typedef struct {")
    A(
        "    const char *const *args; size_t nargs;  /* NULL: the name of the module; not NULL with nargs 0: no arguments */"
    )
    A("    const char *const *env; size_t nenv;")
    A("    const char *const *dirs; size_t ndirs;")
    A(
        "    const int *dirs_readonly;  /* NULL, or a flag for each dir: 1 for a directory that the program cannot change */"
    )
    A("    int (*stdin_read)(void *user, uint8_t *buf, size_t cap, size_t *got);")
    A("    int (*stdout_write)(void *user, int fd, const uint8_t *buf, size_t n);  /* fd 1 or 2 */")
    A(
        "    int (*clock)(void *user, uint32_t id, uint64_t *ns);  /* id: the clock of WASI (0 realtime, 1 monotonic, 2 and 3 of the process and the thread); without it the system's */"
    )
    A("    int (*random)(void *user, uint8_t *buf, size_t n);  /* without it the system's source */")
    A("    int (*sleep)(void *user, uint64_t ns);  /* without it the core sleeps in slices of 100 ms */")
    A("    void *user;")
    A(f"}} {last}_config;")
    A("")
    A("/* A new instance (imports not set, not instantiated); NULL with `*error` (an errno) when it cannot be made. */")
    A(f"WASMEXT_API {last}_t *{last}_new(const {last}_config *config, int *error);")
    A(f"WASMEXT_API void {last}_free({last}_t *m);")
    A(
        "/* The first call into the library from a thread sets that thread up for traps (the runtime of wasm2c does it for the thread that made the instance); a host thread that is going away may call this to give that back. */"
    )
    A(f"WASMEXT_API void {last}_thread_free(void);")
    A(f"WASMEXT_API int {last}_instantiate({last}_t *m);  /* 0, or the code of a trap (or {big}_LINK_ERROR) */")
    A(f"WASMEXT_API const char *{last}_trap_message(int code);")
    A(
        f"WASMEXT_API int {last}_trap_is_exception(int code);  /* whether a code is that of an exception of WebAssembly that nothing caught */"
    )
    A(
        "/* How the WASI program ended: 0 not yet, 1 proc_exit (`*value` is the code), 2 proc_raise (the signal), 3 a trap of a command. */"
    )
    A(f"WASMEXT_API int {last}_wasi_end({last}_t *m, uint32_t *value);")
    for item in skipped or ():
        if "is not an attribute" not in item:  # that is about the names of Instance
            A(f"/* not here: {item} */")
    A("")

    C(f"/* Generated by wasmext for {last}: the C API of the shared library. No Python in it. */")
    C("#define WASMEXT_BUILDING 1")
    C("#include <stdlib.h>")
    C("#include <string.h>")
    C(f'#include "{last}_glue.h"')
    C(f'#include "{last}_api.h"')
    C("")
    C(
        "/* the runtime of wasm2c must be set up for the thread before WebAssembly code runs on it (the handler of the signals of a trap, the stack for it) */"
    )
    C("static WASM_RT_THREAD_LOCAL int api_ready;")
    C("static void api_enter(void) {")
    C("    if (!api_ready) {")
    C("        wasm_rt_init();")
    C("        api_ready = 1;")
    C("    }")
    C("}")
    C(f"void {last}_thread_free(void) {{")
    C("    if (api_ready) {")
    C("        wasm_rt_free_thread();")
    C("        api_ready = 0;")
    C("    }")
    C("}")
    C("")
    n_imports = len(imports)
    C(f"struct {last}_t {{")
    C(f"    {last}_instance core;")
    C(f"    unsigned char set[{max(n_imports, 1)}];  /* an import that the host has set (those of WASI are) */")
    if any(len(func.results) > 1 for _m, _f, func, _w, _h, _s in imports):
        C(
            f"    struct {{ void *fn; void *user; }} multi[{max(n_imports, 1)}];  /* the host function of an import with several results, and its user */"
        )
    C("    int how; uint32_t value;  /* how the WASI program ended */")
    C("    int (*stdin_read)(void *user, uint8_t *buf, size_t cap, size_t *got);")
    C("    int (*stdout_write)(void *user, int fd, const uint8_t *buf, size_t n);")
    C("    int (*clock)(void *user, uint32_t id, uint64_t *ns);")
    C("    int (*random)(void *user, uint8_t *buf, size_t n);")
    C("    int (*sleep)(void *user, uint64_t ns);")
    C("    void *user;")
    if tags:
        C(
            "    int tag; int nvalues; wasmext_value values["
            + f"{big}_TAG_MAX_VALUES];  /* the exception of the last call that nothing caught */"
        )
    C("};")
    C("")
    if uses_wasi:
        C("static void api_ended(void *user, int how, uint32_t value) {")
        C(f"    {last}_t *m = ({last}_t *)user;")
        C("    m->how = how;")
        C("    m->value = value;")
        C("}")
        C("static int api_stdin(void *user, uint8_t *buf, size_t cap, size_t *got) {")
        C(f"    {last}_t *m = ({last}_t *)user;")
        C("    return m->stdin_read(m->user, buf, cap, got);")
        C("}")
        C("static int api_stdout(void *user, int fd, const uint8_t *buf, size_t n) {")
        C(f"    {last}_t *m = ({last}_t *)user;")
        C("    return m->stdout_write(m->user, fd, buf, n);")
        C("}")
        C("static int api_clock(void *user, uint32_t id, uint64_t *ns) {")
        C(f"    {last}_t *m = ({last}_t *)user;")
        C("    return m->clock(m->user, id, ns);")
        C("}")
        C("static int api_random(void *user, uint8_t *buf, size_t n) {")
        C(f"    {last}_t *m = ({last}_t *)user;")
        C("    return m->random(m->user, buf, n);")
        C("}")
        C("static int api_sleep(void *user, uint64_t ns) {")
        C(f"    {last}_t *m = ({last}_t *)user;")
        C("    return m->sleep(m->user, ns);")
        C("}")
        C("static char *api_pack(const char *const *items, size_t count, size_t *size) {")
        C("    size_t total = 0;")
        C("    for (size_t i = 0; i < count; i++) total += strlen(items[i]) + 1;")
        C("    char *buffer = (char *)malloc(total ? total : 1), *at = buffer;")
        C("    for (size_t i = 0; buffer != NULL && i < count; i++) {")
        C("        size_t n = strlen(items[i]) + 1;")
        C("        memcpy(at, items[i], n);")
        C("        at += n;")
        C("    }")
        C("    *size = total;")
        C("    return buffer;")
        C("}")
        C("")
    C(f"{last}_t *{last}_new(const {last}_config *config, int *error) {{")
    C("    int ignored;")
    C("    api_enter();")
    C("    if (error == NULL) error = &ignored;")
    C(f"    {last}_t *m = ({last}_t *)calloc(1, sizeof *m);")
    C("    if (m == NULL) { *error = 12; return NULL; }")
    if uses_wasi:
        C("    wasmext_wasi_config wasi;")
        C("    memset(&wasi, 0, sizeof wasi);")
        C("    char *args = NULL, *env = NULL;")
        C("    char **hosts = NULL;")
        C("    wasmext_wasi_preopen *preopens = NULL;")
        C(f"    wasi.program = {_c_string(last)};")
        C("    size_t ndirs = config != NULL ? config->ndirs : 0;")
        C("    if (config != NULL) {")
        C("        size_t size;")
        C("        if (config->args != NULL) {")
        C("            args = api_pack(config->args, config->nargs, &size);")
        C("            wasi.args = args; wasi.args_size = size; wasi.argc = (uint32_t)config->nargs;")
        C("        }")
        C("        if (config->nenv > 0) {")
        C("            env = api_pack(config->env, config->nenv, &size);")
        C("            wasi.env = env; wasi.env_size = size; wasi.envc = (uint32_t)config->nenv;")
        C("        }")
        C("        if (ndirs > 0) {")
        C("            preopens = (wasmext_wasi_preopen *)calloc(ndirs, sizeof *preopens);")
        C("            hosts = (char **)calloc(ndirs, sizeof(char *));")
        C("            for (size_t i = 0; preopens != NULL && hosts != NULL && i < ndirs; i++) {")
        C('                const char *item = config->dirs[i], *sep = strstr(item, "::");')
        C("                size_t host_len = sep != NULL ? (size_t)(sep - item) : strlen(item);")
        C("                hosts[i] = (char *)malloc(host_len + 1);")
        C("                if (hosts[i] == NULL) continue;")
        C("                memcpy(hosts[i], item, host_len);")
        C("                hosts[i][host_len] = '\\0';")
        C("                preopens[i].host = hosts[i];")
        C("                preopens[i].name = sep != NULL && sep[2] != '\\0' ? sep + 2 : \"/\";")
        C("                preopens[i].name_len = strlen(preopens[i].name);")
        C("                preopens[i].readonly = config->dirs_readonly != NULL && config->dirs_readonly[i] != 0;")
        C("            }")
        C("            wasi.preopens = preopens; wasi.npreopens = ndirs;")
        C("        }")
        C("        m->stdin_read = config->stdin_read;")
        C("        m->stdout_write = config->stdout_write;")
        C("        m->clock = config->clock;")
        C("        m->random = config->random;")
        C("        m->sleep = config->sleep;")
        C("        m->user = config->user;")
        C("    }")
        C("    if (m->stdin_read != NULL) wasi.hooks.stdin_read = api_stdin;")
        C("    if (m->stdout_write != NULL) wasi.hooks.stdout_write = api_stdout;")
        C("    if (m->clock != NULL) wasi.hooks.clock = api_clock;")
        C("    if (m->random != NULL) wasi.hooks.random = api_random;")
        C("    if (m->sleep != NULL) wasi.hooks.sleep = api_sleep;")
        C("    wasi.hooks.end = api_ended;")
        C("    wasi.user = m;")
        C("    size_t bad;")
        C("    int err = 0;")
        C("    m->core.wasi = wasmext_wasi_create(&wasi, &err, &bad);")
        C("    free(args); free(env); free(preopens);")
        C("    if (hosts != NULL) { for (size_t i = 0; i < ndirs; i++) free(hosts[i]); free(hosts); }")
        C("    if (m->core.wasi == NULL) { *error = err; free(m); return NULL; }")
        C(f"    wasmext_wasi_bind(m->core.wasi, w2c_{prefix}_memory(&m->core.inst));")
        C(f"    {last}_wasi_bind(&m->core);")
        for k, (_module, _field, _func, is_wasi, _host, _slot) in enumerate(imports):
            if is_wasi:
                C(f"    m->set[{k}] = 1;")
    else:
        C("    (void)config;")
    C("    *error = 0;")
    C("    return m;")
    C("}")
    C("")
    C(f"void {last}_free({last}_t *m) {{")
    C("    if (m == NULL) return;")
    C(f"    {last}_glue_free(&m->core);")
    if uses_wasi:
        C("    wasmext_wasi_destroy(m->core.wasi);")
    C("    free(m);")
    C("}")
    C("")
    C(f"int {last}_instantiate({last}_t *m) {{")
    C("    api_enter();")
    for k, (module, field_, _func, is_wasi, _host, _slot) in enumerate(imports):
        if not is_wasi:
            C(f"    if (!m->set[{k}]) return {big}_LINK_ERROR;  /* {module}.{field_} */")
    init = next(
        (i for i, (name, func) in enumerate(funcs) if name == "_initialize" and not func.params and not func.results),
        None,
    )
    if init is not None and not any(name == "_start" for name, _ in funcs):
        # a reactor: `_initialize` is run once, after the module is instantiated, before any other export (the convention of WASI for a library)
        C(f"    int rc = {last}_glue_instantiate(&m->core);")
        C("    if (rc) return rc;")
        C("    int trapped = 0;")
        C(f"    {last}_call{init}(&m->core.inst, &trapped);")
        C("    return trapped;")
    else:
        C(f"    return {last}_glue_instantiate(&m->core);")
    C("}")
    C("")
    C(f"const char *{last}_trap_message(int code) {{")
    C(f'    if (code == {big}_TRAP_HOST) return "a host function failed";')
    C(f'    if (code == {big}_TRAP_NO_MEMORY) return "out of memory";')
    C(f'    if (code == {big}_TRAP_ENDED) return "the WASI program is over";')
    C(f'    if (code == {big}_LINK_ERROR) return "an import was not set";')
    C("    return wasm_rt_strerror((wasm_rt_trap_t)code);")
    C("}")
    C("")
    C(f"int {last}_trap_is_exception(int code) {{")
    C("    return code == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION;")
    C("}")
    C("")
    C(f"int {last}_wasi_end({last}_t *m, uint32_t *value) {{")
    if uses_wasi:
        C("    if (value != NULL) *value = m->core.wasi->end_value;")
        C("    return m->core.wasi->finished;")
    else:
        C("    (void)m; (void)value;")
        C("    return 0;")
    C("}")
    C("")

    # the imports: the types of the functions and where to set them (a call of WASI may be replaced too: what the host gives wins)
    for k, (module, field_, func, is_wasi, host, slot) in enumerate(imports):
        several = len(func.results) > 1
        ret = "void" if several else _API_TYPE[func.results[0]] if func.results else "void"
        params = "".join(f", {_API_TYPE[t]} a{j}" for j, t in enumerate(func.params))
        outs = "".join(f", {_API_TYPE[t]} *r{j}" for j, t in enumerate(func.results)) if several else ""
        if is_wasi:
            A(
                f"/* the call of WASI {module}.{field_}: the core has it; a function set here (not NULL) replaces it, as the host's own import does */"
            )
        else:
            A(
                f"/* the import {module}.{field_}: set it before {last}_instantiate; a failure of the function is `*trapped` nonzero (and its own error, kept by the host){'; the results go through the pointers' if several else ''} */"
            )
        model.imports.append((k, module, field_, func, is_wasi))
        A(f"typedef {ret} (*{last}_import{k}_fn)(void *user{params}{outs}, int *trapped);")
        A(f"WASMEXT_API void {last}_set_import{k}({last}_t *m, {last}_import{k}_fn function, void *user);")
        if several:
            codes = "".join(_MULTI_CODE[t] for t in func.results)
            C(f"static struct wasm_multi_{codes} api_import{k}(void *self{params}, int *trapped) {{")
            C(f"    {last}_t *m = ({last}_t *)self;")
            C(f"    struct wasm_multi_{codes} r;")
            C("    memset(&r, 0, sizeof r);")
            C(f"    {last}_import{k}_fn function = ({last}_import{k}_fn)m->multi[{k}].fn;")
            args = "".join(f", a{j}" for j in range(len(func.params)))
            refs = "".join(f", ({_API_TYPE[t]} *)&r.{_MULTI_CODE[t]}{j}" for j, t in enumerate(func.results))
            C(f"    function(m->multi[{k}].user{args}{refs}, trapped);")
            C("    return r;")
            C("}")
            C(f"void {last}_set_import{k}({last}_t *m, {last}_import{k}_fn function, void *user) {{")
            C(f"    m->multi[{k}].fn = (void *)function;")
            C(f"    m->multi[{k}].user = user;")
            C(f"    m->core.host{host}.fn[{slot}] = (void *)api_import{k};")
            C(f"    m->core.host{host}.user[{slot}] = m;")
        else:
            C(f"void {last}_set_import{k}({last}_t *m, {last}_import{k}_fn function, void *user) {{")
            C(f"    m->core.host{host}.fn[{slot}] = (void *)function;")
            C(f"    m->core.host{host}.user[{slot}] = user;")
        C(f"    m->set[{k}] = function != NULL;")
        C("}")
        C("")
    A("")
    if tags:
        A(
            f"/* An exception of WebAssembly that nothing caught ends a call with the trap code of the runtime for it (see {last}_trap_message); then the tag (its index in the module)"
        )
        A("   and the values, as the last call left them. */")
        A(
            f"typedef struct {{ int type; union {{ int32_t i32; int64_t i64; float f32; double f64; }} as; }} {last}_value;  /* type: 0x7F i32, 0x7E i64, 0x7D f32, 0x7C f64 */"
        )
        A(
            f"WASMEXT_API int {last}_exception({last}_t *m, int *tag, {last}_value *values, size_t capacity, size_t *count);"
        )
        C(f"int {last}_exception({last}_t *m, int *tag, {last}_value *values, size_t capacity, size_t *count) {{")
        C("    if (tag != NULL) *tag = m->tag;")
        C("    size_t n = m->nvalues > 0 ? (size_t)m->nvalues : 0;")
        C("    if (count != NULL) *count = n;")
        C("    for (size_t i = 0; values != NULL && i < n && i < capacity; i++) {")
        C("        values[i].type = m->values[i].type;")
        C("        switch (m->values[i].type) {")
        C("        case 0x7F: values[i].as.i32 = (int32_t)m->values[i].as.i; break;")
        C("        case 0x7E: values[i].as.i64 = (int64_t)m->values[i].as.j; break;")
        C("        case 0x7D: values[i].as.f32 = m->values[i].as.f; break;")
        C("        default: values[i].as.f64 = m->values[i].as.d; break;")
        C("        }")
        C("    }")
        C("    return 0;")
        C("}")
        C("")

    # the exports
    for i, (name, func) in enumerate(funcs):
        if "v128" in (*func.params, *func.results):
            A(f"/* {name}: not here, it has a v128 */")
            continue
        ident = _ident(name, taken)
        params = "".join(f", {_API_TYPE[t]} a{j}" for j, t in enumerate(func.params))
        results = "".join(f", {_API_TYPE[t]} *r{k}" for k, t in enumerate(func.results))
        sig = f"{name}({', '.join(func.params)}) -> {', '.join(func.results) or 'nothing'}"
        A(f"/* {sig}: 0, or the code of the trap */")
        model.exports.append((name, f"{last}_{ident}", func))
        A(f"WASMEXT_API int {last}_{ident}({last}_t *m{params}{results});")
        C(f"int {last}_{ident}({last}_t *m{params}{results}) {{")
        C("    api_enter();")
        C("    int trapped = 0;")
        args = "".join(f", ({_CTYPE[t]})a{j}" for j, t in enumerate(func.params))
        call = f"{last}_call{i}(&m->core.inst{args}, &trapped)"
        if len(func.results) > 1:
            codes = "".join(_MULTI_CODE[t] for t in func.results)
            C(f"    struct wasm_multi_{codes} r = {call};")
        elif func.results:
            C(f"    {_CTYPE[func.results[0]]} r = {call};")
        else:
            C(f"    {call};")
        if tags:
            C("    if (trapped == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION) {")
            C(f"        m->tag = {last}_tag_of(wasm_rt_exception_tag());")
            C(
                f"        m->nvalues = m->tag >= 0 ? {last}_tag_values(m->tag, wasm_rt_exception(), wasm_rt_exception_size(), m->values) : -1;"
            )
            C("    }")
        if uses_wasi:
            C(
                "    /* the call in which the program ends (proc_exit, proc_raise) unwound with the code of a host function; it is the end that it answers */"
            )
            C(
                "    if (trapped == (int)WASMEXT_TRAP_HOST && m->core.wasi != NULL && (m->core.wasi->finished == WASI_END_EXIT || m->core.wasi->finished == WASI_END_SIGNAL))"
            )
            C("        trapped = (int)WASMEXT_TRAP_ENDED;")
        C("    if (trapped) return trapped;")
        if len(func.results) > 1:
            for k, t in enumerate(func.results):
                C(f"    if (r{k} != NULL) *r{k} = ({_API_TYPE[t]})r.{_MULTI_CODE[t]}{k};")
        elif func.results:
            C(f"    if (r0 != NULL) *r0 = ({_API_TYPE[func.results[0]]})r;")
        C("    return 0;")
        C("}")
        C("")
    # the exported memories
    taken_memories: set[str] = set()
    for name in memories:
        ident = f"memory_{_ident(name, taken_memories)}"
        A(f"/* the memory {name}: its bytes (valid until the module grows it) and their number */")
        model.memories.append((name, f"{last}_{ident}"))
        A(f"WASMEXT_API uint8_t *{last}_{ident}({last}_t *m, size_t *size);")
        C(f"uint8_t *{last}_{ident}({last}_t *m, size_t *size) {{")
        C(f"    wasm_rt_memory_t *memory = w2c_{prefix}_{mangle(name)}(&m->core.inst);")
        C("    if (size != NULL) *size = (size_t)memory->size;")
        C("    return memory->data;")
        C("}")
        C("")
    # the exported globals
    taken_globals: set[str] = set()
    for name, glob in globals_ or ():
        if glob.type not in _API_TYPE:
            A(f"/* the global {name}: not here, it is a {glob.type} */")
            continue
        ident = _ident(name, taken_globals)
        ctype = _API_TYPE[glob.type]
        kind = "mutable" if glob.mutable else "immutable"
        accessor = f"w2c_{prefix}_{mangle(name)}(&m->core.inst)"
        A(f"/* the {kind} global {name} ({glob.type}) */")
        model.globals.append(
            (name, f"{last}_global_{ident}", f"{last}_set_global_{ident}" if glob.mutable else None, glob.type)
        )
        A(f"WASMEXT_API {ctype} {last}_global_{ident}({last}_t *m);")
        C(f"{ctype} {last}_global_{ident}({last}_t *m) {{")
        C(f"    return ({ctype})*{accessor};")
        C("}")
        C("")
        if glob.mutable:
            A(f"WASMEXT_API void {last}_set_global_{ident}({last}_t *m, {ctype} value);")
            C(f"void {last}_set_global_{ident}({last}_t *m, {ctype} value) {{")
            C(f"    *{accessor} = value;")
            C("}")
            C("")
    A("")
    A("#ifdef __cplusplus")
    A("}")
    A("#endif")
    A("#endif")
    return "\n".join(a) + "\n", "\n".join(c) + "\n", model
