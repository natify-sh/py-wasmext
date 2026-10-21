# pyright: reportPrivateUsage=false
"""The C API of a module as a shared library (item 10 of DESIGN.md, stage 6a): a public header `<name>_api.h` for any host language and the C that
exports it, `<name>_shared.c`, on the typed functions of `<name>_glue.h`. No Python in either.

The life of an instance: `<name>_new(&config, &error)` (WASI is made and bound there), `<name>_set_import<k>(m, function, user)` for each import that is not WASI's
(a host function is `result f(void *user, parameters..., int *trapped)`: it answers through `trapped`, nonzero when it failed, and keeps its error itself, as the
protocol of errors says), `<name>_instantiate(m)` (0, or the code of a trap), then the exports as `int <name>_<export>(m, parameters..., results...)`, which answer 0 or the
code of the trap (`<name>_trap_message(code)` is its text); `<name>_free(m)`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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
    "export",
    "export_find",
    "trap_is_exception",
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
    global_imports: list[tuple[int, str, str, ValType, bool]] = field(
        default_factory=list[tuple[int, str, str, ValType, bool]]
    )  # j (the C functions are <last>_link_global_import<j> and, for an immutable one, <last>_set_global_import<j>), module, field, type, mutable
    memory_imports: list[tuple[int, str, str]] = field(
        default_factory=list[tuple[int, str, str]]
    )  # j (the C function is <last>_link_memory_import<j>), module, field
    tables: list[str] = field(
        default_factory=list[str]
    )  # the funcref tables the module exports (reached through <last>_export_find)
    table_imports: list[tuple[int, str, str]] = field(
        default_factory=list[tuple[int, str, str]]
    )  # j (the C function is <last>_link_table_import<j>), module, field
    shares_tables: bool = False  # the library has <last>_traps and <last>_traps_use (see the header)
    ref_types: list[tuple[int, str, FuncType]] = field(
        default_factory=list[tuple[int, str, FuncType]]
    )  # k, the C function <last>_funcref_call<k>, the type: what a Function of the wrapper can call
    skipped: list[str] = field(default_factory=list[str])


# The names that an export may not take: the functions of the glue and of the C API are named by these patterns.
_RESERVED_NAMES = re.compile(
    r"call\d+|set_import\d+|link_\w+|set_global_\w+|memory_\w+|global_\w+|wasi_\w+|glue_\w+|import\d+_fn|instance|traps|traps_use|unlink_tables|table_(?:new|free|size|maximum|grow|export|is_null|is|set|get_ref)|funcref_(?:type|copy|free|export|same|hash|call\d+)"
)


def _ident(name: str, taken: set[str]) -> str:
    """A C identifier for an export, different from those taken (and from the names of the API, and the `call<n>` of the glue).

    A clash with another export gets a suffix (`add_2`). A name that is reserved by a pattern (everything that starts with `wasi_`, `link_`, ...)
    cannot be freed by a suffix, since the suffix leaves the start as it is: it gets the prefix `x_` instead (`x_wasi_cli_run_0_2_12_run`, the
    name of the export `wasi:cli/run@0.2.12#run` of a component). Where no name is found, it is an error and not a loop."""

    from ._gen import GenError  # _gen imports this module inside its functions only

    def free(candidate: str) -> bool:
        return candidate not in taken and candidate not in _RESERVED and not _RESERVED_NAMES.fullmatch(candidate)

    def escaped(candidate: str) -> str:
        return f"x_{candidate}" if _RESERVED_NAMES.fullmatch(candidate) else candidate

    base = re.sub(r"[^0-9A-Za-z_]", "_", name) or "export"
    if base[0].isdigit():
        base = f"_{base}"
    base = escaped(base)
    out = base
    for n in range(2, 10_000):
        if free(out):
            taken.add(out)
            return out
        out = escaped(f"{base}_{n}")
    raise GenError(f"no C name is found for the export {name!r}")


def unsupported(
    imports: list[tuple[str, str, FuncType]], *, global_imports: bool, memory_imports: bool, table_imports: bool = False
) -> str | None:
    """Why the module has no shared library yet, or None."""
    del (
        imports,
        global_imports,
        memory_imports,
    )  # served: the numbers, a v128 (as 16 bytes behind a pointer) and the exports of other instances (see the link functions)
    del table_imports  # served: the table of another instance (see the link functions and <name>_traps)
    return None


def _in(t: ValType, name: str) -> str:
    """A parameter of the C API: a v128 is 16 bytes behind a pointer (in the order of WebAssembly memory, little-endian); a funcref is a pointer to one (NULL: the null funcref)."""
    if t == "funcref":
        return f"const void *{name}"
    return f"const uint8_t *{name}" if t == "v128" else f"{_API_TYPE[t]} {name}"


def _out(t: ValType, name: str) -> str:
    """A result of the C API, by pointer: for a v128, where its 16 bytes are written; for a funcref, a copy that the host frees with `funcref_free` (NULL: the null funcref)."""
    if t == "funcref":
        return f"void **{name}"
    return f"uint8_t *{name}" if t == "v128" else f"{_API_TYPE[t]} *{name}"


def _arg_expr(t: ValType, name: str, ctype: str) -> str:
    """The argument of the call of the glue for a parameter of the C API."""
    if t == "v128":
        return f"api_v128({name})"
    if t == "funcref":
        return f"api_funcref({name})"
    return f"({ctype}){name}"


def _store_result(t: ValType, name: str, value: str, api_type: str) -> str:
    """The statement that gives the result of a call to the host through the pointer `name`."""
    if t == "v128":
        return f"    if ({name} != NULL) api_bytes({name}, {value});"
    if t == "funcref":
        return f"    if ({name} != NULL) *{name} = api_funcref_new({value});"
    return f"    if ({name} != NULL) *{name} = ({api_type}){value};"


def _has_v128(func: FuncType) -> bool:
    return "v128" in (*func.params, *func.results)


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
    global_imports: list[Any] | None = None,
    memory_imports: list[Any] | None = None,
    memory_limits: list[Any] | None = None,
    tables: list[str] | None = None,
    table_imports: list[Any] | None = None,
    trap_handler: str = "",
    ref_types: list[FuncType] | None = None,
) -> tuple[str, str, ApiModel]:
    """The public header, the C of the library and the model of the API; `funcs` are the exports in the order of the glue (`<name>_call<i>`). A v128 in a signature is 16 bytes behind a pointer
    (`const uint8_t *` in, `uint8_t *` out, little-endian); a global of that type and the link of such a function to another instance are left out."""
    from ._gen import (
        _CTYPE,
        _MULTI_CODE,
        _TYPE_CODE,
        _c_string,
        _cc,
        _signature_code,
        mangle,
    )

    big = last.upper()
    model = ApiModel(
        last,
        uses_wasi=uses_wasi,
        has_tags=bool(tags),
        tables=list(tables or ()),
        shares_tables=bool(trap_handler),
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
        f"#define {big}_TRAP_LINKED 0x20000  /* a function that is the export of another instance answers a trap of that instance as this + its code: the caller traps with the code */"
    )
    A(
        "/* What an instance gives of an export for another to import (a function, a memory or a global): the record of wasmext, public and versioned by WASMEXT_ABI; it is passed by"
    )
    A(
        "   pointer from the exporter (`_export_find`) to the importer (`_link_*`). `owner` is whatever keeps the exporter alive (the host's own business). */"
    )
    A("typedef struct {")
    A("    uint32_t size, abi, kind, type, flags;")
    A("    void *owner, *address, *instance;")
    A("    const char *signature;")
    A("    uint32_t runtime;")
    A("    const void *funcref;")
    A("    uint32_t floor;")
    A(f"}} {last}_export;")
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
    if trap_handler:
        A(
            "/* A funcref table that one library exports and another imports holds functions of both, and a trap in a function of one that the other called must come back to the call that"
        )
        A(
            "   entered WebAssembly code, whichever library it happened in. So the libraries that share tables share one stack of entries (per thread): this library has one of its own,"
        )
        A(
            "   and `traps_use` makes it use the stack of another. Before the first instance of the second library is made: `lib2_traps_use(lib1_traps())`, for every library after the"
        )
        A(
            "   first. 0 when done, 1 when the stacks are not compatible (another layout of the runtime of wasm2c) or when too many libraries share one. */"
        )
        A(f"WASMEXT_API const void *{last}_traps(void);")
        A(f"WASMEXT_API int {last}_traps_use(const void *traps);")
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
            A(f"/* not here: {_cc(item)} */")
    A("")

    C(f"/* Generated by wasmext for {last}: the C API of the shared library. No Python in it. */")
    C("#define WASMEXT_BUILDING 1")
    C("#include <stdlib.h>")
    C("#include <string.h>")
    C(f'#include "{last}_glue.h"')
    C(f'#include "{last}_api.h"')
    C("")
    if trap_handler:
        C("#ifndef WASMEXT_TRAP_HANDLER")
        C(
            f'#error "wasmext: this module shares tables with other instances: build it with -DWASMEXT_TRAP_HANDLER={trap_handler} (build_shared and natify do)"'
        )
        C("#endif")
        C(
            "/* the function that the runtime of this library calls for a trap instead of `longjmp` (wasmext_glue.h): it goes to the innermost call into WebAssembly code */"
        )
        C(f"void {trap_handler}(wasm_rt_trap_t code) {{ wasmext_traps_->trap(code); }}")
        C(
            "static int api_joined;  /* this runtime is on the stack of entries (set by the first instance; make the instances of libraries that share tables from one thread first) */"
        )
        C(f"const void *{last}_traps(void) {{ return &wasmext_traps_own_; }}")
        C(f"int {last}_traps_use(const void *traps) {{")
        C("    int bad = wasmext_traps_use((const wasmext_traps *)traps);")
        C("    if (!bad) api_joined = 1;")
        C("    return bad;")
        C("}")
        C("")
    C(
        "/* the runtime of wasm2c must be set up for the thread before WebAssembly code runs on it (the handler of the signals of a trap, the stack for it) */"
    )
    C("static WASM_RT_THREAD_LOCAL int api_ready;")
    C("static void api_enter(void) {")
    if trap_handler:
        C("    if (!api_joined) {")
        C("        if (wasmext_traps_use(wasmext_traps_)) abort();  /* joins this runtime to the stack it uses */")
        C("        api_joined = 1;")
        C("    }")
    C("    if (!api_ready) {")
    C("        wasm_rt_init();")
    C("        api_ready = 1;")
    C("    }")
    C("}")
    if any(_has_v128(f) for _m, _f, f, _w, _h, _s in imports) or any(_has_v128(f) for _n, f in funcs):
        C("#if defined(__BYTE_ORDER__) && defined(__ORDER_BIG_ENDIAN__) && __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__")
        C('#error "wasmext: v128 in a signature is not supported on big-endian hosts"')
        C("#endif")
        C("/* a v128 crosses the API as 16 bytes in the order of WebAssembly memory (little-endian) */")
        C("static v128 api_v128(const uint8_t *bytes) {")
        C("    v128 v;")
        C("    memcpy(&v, bytes, 16);")
        C("    return v;")
        C("}")
        C("static void api_bytes(uint8_t *out, v128 v) {")
        C("    memcpy(out, &v, 16);")
        C("}")
    if any("funcref" in (*f.params, *f.results) for _n, f in funcs):
        C(
            "/* a funcref crosses the API as a pointer to the element (NULL: null); a result is a copy that the host frees with funcref_free */"
        )
        C("static wasm_rt_funcref_t api_funcref(const void *p) {")
        C("    wasm_rt_funcref_t f;")
        C("    memset(&f, 0, sizeof f);")
        C("    if (p != NULL) memcpy(&f, p, sizeof f);")
        C("    return f;")
        C("}")
        C("static void *api_funcref_new(wasm_rt_funcref_t f) {")
        C("    wasm_rt_funcref_t *c;")
        C("    if (f.func == NULL) return NULL;")
        C("    c = (wasm_rt_funcref_t *)malloc(sizeof *c);")
        C("    if (c != NULL) *c = f;")
        C("    return c;")
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
    C(
        f"    unsigned char gset[{max(len(global_imports or ()), 1)}], mset[{max(len(memory_imports or ()), 1)}];  /* the same for the globals and the memories */"
    )
    if table_imports:
        C(f"    unsigned char tset[{len(table_imports)}];  /* ... and the tables */")
    if any(len(func.results) > 1 or _has_v128(func) for _m, _f, func, _w, _h, _s in imports):
        C(
            f"    struct {{ void *fn; void *user; }} multi[{max(n_imports, 1)}];  /* the host function of an import with several results, and its user */"
        )
    if memories:
        C(f"    long mem_pins[{len(memories)}];  /* the pins of each exported memory (see <name>_memory_*_pin) */")
        C(f"    uint64_t mem_max_pages[{len(memories)}];")
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
            C(f"    if (!m->set[{k}]) return {big}_LINK_ERROR;  /* {_cc(module)}.{_cc(field_)} */")
    for j, g in enumerate(global_imports or ()):
        C(f"    if (!m->gset[{j}]) return {big}_LINK_ERROR;  /* {_cc(g.module)}.{_cc(g.field)} */")
    for j, mem in enumerate(memory_imports or ()):
        C(f"    if (!m->mset[{j}]) return {big}_LINK_ERROR;  /* {_cc(mem.module)}.{_cc(mem.field)} */")
    for j, tb in enumerate(table_imports or ()):
        C(f"    if (!m->tset[{j}]) return {big}_LINK_ERROR;  /* {_cc(tb.module)}.{_cc(tb.field)} */")
    reactor_init = next(
        (i for i, (name, func) in enumerate(funcs) if name == "_initialize" and not func.params and not func.results),
        None,
    )
    if any(name == "_start" for name, _ in funcs):
        reactor_init = None
    # a reactor: `_initialize` is run once, after the module is instantiated, before any other export (the convention of WASI for a library); the same
    # function does it in every front end, and a later call of the export `_initialize` does nothing
    C(f"    int rc = {last}_glue_instantiate(&m->core);")
    C("    if (rc) return rc;")
    C(f"    return {last}_glue_initialize(&m->core);")
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
        wrapped = several or _has_v128(func)  # the host function is called through a function of this file
        outs_style = several or "v128" in func.results  # the results go through pointers
        ret = "void" if outs_style else _API_TYPE[func.results[0]] if func.results else "void"
        params = "".join(f", {_in(t, f'a{j}')}" for j, t in enumerate(func.params))
        outs = "".join(f", {_out(t, f'r{j}')}" for j, t in enumerate(func.results)) if outs_style else ""
        if is_wasi:
            A(
                f"/* the call of WASI {_cc(module)}.{_cc(field_)}: the core has it; a function set here (not NULL) replaces it, as the host's own import does */"
            )
        else:
            A(
                f"/* the import {_cc(module)}.{_cc(field_)}: set it before {last}_instantiate; a failure of the function is `*trapped` nonzero (and its own error, kept by the host){'; the results go through the pointers' if outs_style else ''}{'; a v128 is 16 bytes' if _has_v128(func) else ''} */"
            )
        model.imports.append((k, module, field_, func, is_wasi))
        A(f"typedef {ret} (*{last}_import{k}_fn)(void *user{params}{outs}, int *trapped);")
        A(f"WASMEXT_API void {last}_set_import{k}({last}_t *m, {last}_import{k}_fn function, void *user);")
        if wrapped:
            glue_ret = (
                f"struct wasm_multi_{''.join(_MULTI_CODE[t] for t in func.results)}"
                if several
                else _CTYPE[func.results[0]]
                if func.results
                else "void"
            )
            glue_params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(func.params))
            C(f"static {glue_ret} api_import{k}(void *self{glue_params}, int *trapped) {{")
            C(f"    {last}_t *m = ({last}_t *)self;")
            if glue_ret != "void":
                C(f"    {glue_ret} r;")
                C("    memset(&r, 0, sizeof r);")
            for j, t in enumerate(func.params):
                if t == "v128":
                    C(f"    uint8_t b{j}[16];")
                    C(f"    api_bytes(b{j}, a{j});")
            if outs_style:
                for j, t in enumerate(func.results):
                    if t == "v128":
                        C(f"    uint8_t o{j}[16];")
                        C(f"    memset(o{j}, 0, 16);")
            C(f"    {last}_import{k}_fn function = ({last}_import{k}_fn)m->multi[{k}].fn;")
            args = "".join(f", b{j}" if t == "v128" else f", a{j}" for j, t in enumerate(func.params))
            if several:
                refs = "".join(
                    f", o{j}" if t == "v128" else f", ({_API_TYPE[t]} *)&r.{_MULTI_CODE[t]}{j}"
                    for j, t in enumerate(func.results)
                )
                C(f"    function(m->multi[{k}].user{args}{refs}, trapped);")
                for j, t in enumerate(func.results):
                    if t == "v128":
                        C(f"    memcpy(&r.{_MULTI_CODE[t]}{j}, o{j}, 16);")
            elif outs_style:  # a single v128 result
                C(f"    function(m->multi[{k}].user{args}, o0, trapped);")
                C("    memcpy(&r, o0, sizeof r);")
            elif func.results:
                C(f"    r = ({_CTYPE[func.results[0]]})function(m->multi[{k}].user{args}, trapped);")
            else:
                C(f"    function(m->multi[{k}].user{args}, trapped);")
            if glue_ret != "void":
                C("    return r;")
            C("}")
            C(f"void {last}_set_import{k}({last}_t *m, {last}_import{k}_fn function, void *user) {{")
            C(f"    m->multi[{k}].fn = (void *)function;")
            C(f"    m->multi[{k}].user = user;")
            C(f"    m->core.host{host}.fn[{slot}] = (void *){'api_import' + str(k)};")
            C(f"    m->core.host{host}.user[{slot}] = m;")
        else:
            C(f"void {last}_set_import{k}({last}_t *m, {last}_import{k}_fn function, void *user) {{")
            C(f"    m->core.host{host}.fn[{slot}] = (void *)function;")
            C(f"    m->core.host{host}.user[{slot}] = user;")
        C(f"    m->set[{k}] = function != NULL;")
        C("}")
        C("")
    # linking: the imports from the exports of another instance (the checks are those of the glue of the module, the same as the extension's)
    A("")
    for k, (module, field_, func, is_wasi, host, slot) in enumerate(imports):
        A(
            f"/* the import {_cc(module)}.{_cc(field_)}: the function of another instance (its record from `_export_find`); 0, or 1 with the message of the LinkError */"
        )
        A(
            f"WASMEXT_API int {last}_link_import{k}({last}_t *m, const {last}_export *e, char *message, size_t capacity);"
        )
        C(f"int {last}_link_import{k}({last}_t *m, const {last}_export *e, char *message, size_t capacity) {{")
        C(f"    int rc = {last}_link_func{k}(&m->core, (const wasmext_export *)e, message, capacity);")
        C(f"    if (rc == 0) m->set[{k}] = 1;")
        C("    return rc;")
        C("}")
        C("")
    for j, g in enumerate(global_imports or ()):
        ctype = _API_TYPE.get(g.type, "")
        model.global_imports.append((j, g.module, g.field, g.type, g.mutable))
        A(
            f"/* the import {_cc(g.module)}.{_cc(g.field)}: the {'mutable ' if g.mutable else ''}global {g.type} of another instance */"
        )
        A(
            f"WASMEXT_API int {last}_link_global_import{j}({last}_t *m, const {last}_export *e, char *message, size_t capacity);"
        )
        C(f"int {last}_link_global_import{j}({last}_t *m, const {last}_export *e, char *message, size_t capacity) {{")
        C(f"    int rc = {last}_link_global{j}(&m->core, (const wasmext_export *)e, message, capacity);")
        C(f"    if (rc == 0) m->gset[{j}] = 1;")
        C("    return rc;")
        C("}")
        C("")
        if not g.mutable and g.type in _API_TYPE:
            A("/* ... or, as it is not mutable, its value */")
            A(f"WASMEXT_API void {last}_set_global_import{j}({last}_t *m, {ctype} value);")
            C(f"void {last}_set_global_import{j}({last}_t *m, {ctype} value) {{")
            C(f"    {last}_set_global{j}(&m->core, ({_CTYPE[g.type]})value);")
            C(f"    m->gset[{j}] = 1;")
            C("}")
            C("")
    for j, mem in enumerate(memory_imports or ()):
        model.memory_imports.append((j, mem.module, mem.field))
        A(f"/* the import {_cc(mem.module)}.{_cc(mem.field)}: the memory of another instance */")
        A(
            f"WASMEXT_API int {last}_link_memory_import{j}({last}_t *m, const {last}_export *e, char *message, size_t capacity);"
        )
        C(f"int {last}_link_memory_import{j}({last}_t *m, const {last}_export *e, char *message, size_t capacity) {{")
        C(f"    int rc = {last}_link_memory{j}(&m->core, (const wasmext_export *)e, message, capacity);")
        C(f"    if (rc == 0) m->mset[{j}] = 1;")
        C("    return rc;")
        C("}")
        C("")
    for j, tb in enumerate(table_imports or ()):
        model.table_imports.append((j, tb.module, tb.field))
        A(
            f"/* the import {_cc(tb.module)}.{_cc(tb.field)}: the funcref table of another instance (see {last}_traps for what the libraries that share tables have to do) */"
        )
        A(
            f"WASMEXT_API int {last}_link_table_import{j}({last}_t *m, const {last}_export *e, char *message, size_t capacity);"
        )
        C(f"int {last}_link_table_import{j}({last}_t *m, const {last}_export *e, char *message, size_t capacity) {{")
        C(f"    int rc = {last}_link_table{j}(&m->core, (const wasmext_export *)e, message, capacity);")
        C(f"    if (rc == 0) m->tset[{j}] = 1;")
        C("    return rc;")
        C("}")
        C("")
    if table_imports:
        A(
            "/* Take the functions of this instance out of the tables it imports (they become empty slots). An instance that put functions in the table of another must be kept"
        )
        A(
            "   until the owner of the table is done being called, or unlinked with this before it is freed; `_free` does not do it, so that the owner can go first (the order of the"
        )
        A(
            "   destruction of objects that refer to each other is not the host's to choose). A failed `_instantiate` leaves what it wrote: call this after it. */"
        )
        A(f"WASMEXT_API void {last}_unlink_tables({last}_t *m);")
        C(f"void {last}_unlink_tables({last}_t *m) {{ {last}_scrub_tables(&m->core); }}")
        C("")
    if trap_handler:
        A(
            "/* A table of funcref that no module owns (the class Table of the extension and of the wrapper for ctypes is made of these). `table` is a pointer to the table, which is also"
        )
        A(
            "   what the record of an export of kind WASMEXT_TABLE has as `address`, so these work on the table of an instance as well (size, maximum, grow). `maximum` 0xFFFFFFFF is none. */"
        )
        A(f"WASMEXT_API void *{last}_table_new(uint32_t initial, uint32_t maximum);  /* NULL: not enough memory */")
        A(
            f"WASMEXT_API void {last}_table_free(void *table);  /* the modules that imported it are unlinked or freed first ({last}_unlink_tables); NULL is allowed */"
        )
        A(f"WASMEXT_API uint32_t {last}_table_size(const void *table);")
        A(f"WASMEXT_API uint32_t {last}_table_maximum(const void *table);")
        A(
            f"WASMEXT_API int64_t {last}_table_grow(void *table, uint32_t delta);  /* the size before, or -1 when it cannot grow that much */"
        )
        A(
            f"WASMEXT_API void {last}_table_export(void *table, void *owner, {last}_export *out);  /* the record to give a module as an import; `owner` is whatever keeps the table alive */"
        )
        A(
            "/* The elements. `funcref` is the field of the record of a function export (`<name>_export_find` of the module that has the function); the host keeps that instance alive as long"
        )
        A("   as the table may call it. */")
        A(
            f"WASMEXT_API int {last}_table_is_null(const void *table, uint32_t index);  /* 1 if the slot is empty, 0 if not, -1 if the index is out of range */"
        )
        A(
            f"WASMEXT_API int {last}_table_is(const void *table, uint32_t index, const void *funcref);  /* 1 if the slot holds that function of that instance */"
        )
        A(
            f"WASMEXT_API int {last}_table_set(void *table, uint32_t index, const void *funcref);  /* the function into the slot (NULL: empty it); 0, or -1 if the index is out of range */"
        )
        C(f"void *{last}_table_new(uint32_t initial, uint32_t maximum) {{")
        C("    wasm_rt_funcref_table_t *t = (wasm_rt_funcref_table_t *)malloc(sizeof *t);")
        C("    if (t == NULL) return NULL;")
        C("    if (wasmext_table_new(t, initial, maximum)) {")
        C("        free(t);")
        C("        return NULL;")
        C("    }")
        C("    return t;")
        C("}")
        C(f"void {last}_table_free(void *table) {{")
        C("    if (table == NULL) return;")
        C("    wasmext_table_free((wasm_rt_funcref_table_t *)table);")
        C("    free(table);")
        C("}")
        C(f"uint32_t {last}_table_size(const void *table) {{ return ((const wasm_rt_funcref_table_t *)table)->size; }}")
        C(
            f"uint32_t {last}_table_maximum(const void *table) {{ return ((const wasm_rt_funcref_table_t *)table)->max_size; }}"
        )
        C(
            f"int64_t {last}_table_grow(void *table, uint32_t delta) {{ return wasmext_table_grow((wasm_rt_funcref_table_t *)table, delta); }}"
        )
        C(f"void {last}_table_export(void *table, void *owner, {last}_export *out) {{")
        C("    wasmext_table_export((wasmext_export *)out, (wasm_rt_funcref_table_t *)table, owner);")
        C("}")
        C(f"int {last}_table_is_null(const void *table, uint32_t index) {{")
        C("    const wasm_rt_funcref_table_t *t = (const wasm_rt_funcref_table_t *)table;")
        C("    return index >= t->size ? -1 : t->data[index].func == NULL;")
        C("}")
        C(f"int {last}_table_is(const void *table, uint32_t index, const void *funcref) {{")
        C("    const wasm_rt_funcref_table_t *t = (const wasm_rt_funcref_table_t *)table;")
        C("    const wasm_rt_funcref_t *f = (const wasm_rt_funcref_t *)funcref;")
        C(
            "    return index < t->size && f != NULL && t->data[index].func == f->func && t->data[index].module_instance == f->module_instance;"
        )
        C("}")
        A(
            "/* A function of a table, as the Function of the wrapper has it: a copy of the element (`table_get_ref`; NULL if the slot is empty), or of the funcref of an export record;"
        )
        A(
            "   free it with `funcref_free`. `funcref_type` is the type k of this module that it has (-1: none), and `funcref_call<k>` calls it. */"
        )
        A(f"WASMEXT_API void *{last}_table_get_ref(const void *table, uint32_t index);")
        A(f"WASMEXT_API void *{last}_funcref_copy(const void *funcref);")
        A(f"WASMEXT_API void {last}_funcref_free(void *funcref);")
        A(
            f"WASMEXT_API int {last}_funcref_same(const void *a, const void *b);  /* the same function of the same instance */"
        )
        A(f"WASMEXT_API uint64_t {last}_funcref_hash(const void *funcref);")
        A(f"WASMEXT_API int {last}_funcref_type(const void *funcref);")
        A(
            f"WASMEXT_API void {last}_funcref_export(const void *funcref, void *owner, {last}_export *out);  /* the record of the function, to put it in a table */"
        )
        C(f"void *{last}_funcref_copy(const void *funcref) {{")
        C("    wasm_rt_funcref_t *c = (wasm_rt_funcref_t *)malloc(sizeof *c);")
        C("    if (c != NULL) memcpy(c, funcref, sizeof *c);")
        C("    return c;")
        C("}")
        C(f"void *{last}_table_get_ref(const void *table, uint32_t index) {{")
        C("    const wasm_rt_funcref_table_t *t = (const wasm_rt_funcref_table_t *)table;")
        C("    if (index >= t->size || t->data[index].func == NULL) return NULL;")
        C(f"    return {last}_funcref_copy(&t->data[index]);")
        C("}")
        C(f"void {last}_funcref_free(void *funcref) {{ free(funcref); }}")
        C(f"int {last}_funcref_same(const void *a, const void *b) {{")
        C("    const wasm_rt_funcref_t *x = (const wasm_rt_funcref_t *)a, *y = (const wasm_rt_funcref_t *)b;")
        C("    return x->func == y->func && x->module_instance == y->module_instance;")
        C("}")
        C(f"uint64_t {last}_funcref_hash(const void *funcref) {{")
        C("    const wasm_rt_funcref_t *x = (const wasm_rt_funcref_t *)funcref;")
        C("    return (uint64_t)((uintptr_t)x->func ^ ((uintptr_t)x->module_instance >> 4));")
        C("}")
        C(
            f"int {last}_funcref_type(const void *funcref) {{ return {last}_ref_type((const wasm_rt_funcref_t *)funcref); }}"
        )
        C(f"void {last}_funcref_export(const void *funcref, void *owner, {last}_export *out) {{")
        C("    wasmext_function_export((wasmext_export *)out, (const wasm_rt_funcref_t *)funcref, owner);")
        C("}")
        for k, ft in enumerate(ref_types or ()):
            params = "".join(f", {_in(t, f'a{j}')}" for j, t in enumerate(ft.params))
            results = "".join(f", {_out(t, f'r{j}')}" for j, t in enumerate(ft.results))
            model.ref_types.append((k, f"{last}_funcref_call{k}", ft))
            sig = f"({', '.join(ft.params)}) -> {', '.join(ft.results) or 'nothing'}"
            A(f"/* a function of the type {k}, {_cc(sig)}: 0, or the code of the trap */")
            A(f"WASMEXT_API int {last}_funcref_call{k}(const void *funcref{params}{results});")
            C(f"int {last}_funcref_call{k}(const void *funcref{params}{results}) {{")
            C("    api_enter();")
            C("    int trapped = 0;")
            args = "".join(f", {_arg_expr(t, f'a{j}', _CTYPE[t])}" for j, t in enumerate(ft.params))
            call = f"{last}_callref{k}((const wasm_rt_funcref_t *)funcref{args}, &trapped)"
            if len(ft.results) > 1:
                codes = "".join(_MULTI_CODE[t] for t in ft.results)
                C(f"    struct wasm_multi_{codes} r = {call};")
            elif ft.results:
                C(f"    {_CTYPE[ft.results[0]]} r = {call};")
            else:
                C(f"    {call};")
            C("    if (trapped) return trapped;")
            if len(ft.results) > 1:
                for i, t in enumerate(ft.results):
                    C(_store_result(t, f"r{i}", f"r.{_MULTI_CODE[t]}{i}", _API_TYPE.get(t, "")))
            elif ft.results:
                C(_store_result(ft.results[0], "r0", "r", _API_TYPE.get(ft.results[0], "")))
            C("    return 0;")
            C("}")
        C(f"int {last}_table_set(void *table, uint32_t index, const void *funcref) {{")
        C("    wasm_rt_funcref_table_t *t = (wasm_rt_funcref_table_t *)table;")
        C("    if (index >= t->size) return -1;")
        C("    if (funcref == NULL) memset(&t->data[index], 0, sizeof t->data[index]);")
        C("    else t->data[index] = *(const wasm_rt_funcref_t *)funcref;")
        C("    return 0;")
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
        ident = _ident(name, taken)
        params = "".join(f", {_in(t, f'a{j}')}" for j, t in enumerate(func.params))
        results = "".join(f", {_out(t, f'r{k}')}" for k, t in enumerate(func.results))
        sig = f"{name}({', '.join(func.params)}) -> {', '.join(func.results) or 'nothing'}"
        A(f"/* {_cc(sig)}: 0, or the code of the trap */")
        model.exports.append((name, f"{last}_{ident}", func))
        A(f"WASMEXT_API int {last}_{ident}({last}_t *m{params}{results});")
        C(f"int {last}_{ident}({last}_t *m{params}{results}) {{")
        C("    api_enter();")
        if i == reactor_init:
            C("    if (m->core.initialized) return 0;  /* the reactor was initialized when the instance was made */")
        C("    int trapped = 0;")
        args = "".join(f", {_arg_expr(t, f'a{j}', _CTYPE[t])}" for j, t in enumerate(func.params))
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
                C(_store_result(t, f"r{k}", f"r.{_MULTI_CODE[t]}{k}", _API_TYPE.get(t, "")))
        elif func.results:
            C(_store_result(func.results[0], "r0", "r", _API_TYPE.get(func.results[0], "")))
        C("    return 0;")
        C("}")
        C("")
    # the exported memories
    taken_memories: set[str] = set()
    for name in memories:
        ident = f"memory_{_ident(name, taken_memories)}"
        A(f"/* the memory {_cc(name)}: its bytes (valid until the module grows it) and their number */")
        model.memories.append((name, f"{last}_{ident}"))
        A(f"WASMEXT_API uint8_t *{last}_{ident}({last}_t *m, size_t *size);")
        C(f"uint8_t *{last}_{ident}({last}_t *m, size_t *size) {{")
        C(f"    wasm_rt_memory_t *memory = w2c_{prefix}_{mangle(name)}(&m->core.inst);")
        C("    if (size != NULL) *size = (size_t)memory->size;")
        C("    return memory->data;")
        C("}")
        C("")
        A(
            f"/* pin (1) or unpin (0) the memory {_cc(name)}: while it is pinned, `memory.grow` answers -1 where the runtime moves a memory that grows (no guard pages, memory64),"
            " so the bytes stay where they are; pins count. */"
        )
        A(f"WASMEXT_API void {last}_{ident}_pin({last}_t *m, int pin);")
        C(f"void {last}_{ident}_pin({last}_t *m, int pin) {{")
        C(f"    wasm_rt_memory_t *memory = w2c_{prefix}_{mangle(name)}(&m->core.inst);")
        C("#if WASM_RT_USE_MMAP")
        C("    int moves = memory->is64 || memory->page_size != WASM_DEFAULT_PAGE_SIZE;")
        C("#else")
        C("    int moves = 1;")
        C("#endif")
        C("    if (!moves) return;")
        C(f"    long *pins = &m->mem_pins[{len(model.memories) - 1}];")
        C(f"    uint64_t *saved = &m->mem_max_pages[{len(model.memories) - 1}];")
        C("    if (pin) {")
        C("        if ((*pins)++ == 0) {")
        C("            *saved = memory->max_pages;")
        C("            memory->max_pages = memory->pages;")
        C("        }")
        C("    } else if (*pins > 0 && --(*pins) == 0) {")
        C("        memory->max_pages = *saved;")
        C("    }")
        C("}")
        C("")
    # the exported globals
    taken_globals: set[str] = set()
    for name, glob in globals_ or ():
        if glob.type not in _API_TYPE:
            A(f"/* the global {_cc(name)}: not here, it is a {glob.type} */")
            continue
        ident = _ident(name, taken_globals)
        ctype = _API_TYPE[glob.type]
        kind = "mutable" if glob.mutable else "immutable"
        accessor = f"w2c_{prefix}_{mangle(name)}(&m->core.inst)"
        A(f"/* the {kind} global {_cc(name)} ({glob.type}) */")
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
    # the exports as records for another instance to import; a function's address is a shim that lets a trap through as LINKED + its code
    A("")
    A(
        f"/* The record of the export `name` for another instance to import (`{last}_link_*` of the other library): 0, or 1 when there is no such export. `owner` is kept in the"
    )
    A("   record, for whoever has to keep this instance alive. The record is valid as long as this instance is. */")
    A(f"WASMEXT_API int {last}_export_find({last}_t *m, const char *name, void *owner, {last}_export *out);")
    shims: dict[int, str] = {}
    for i, (name, func) in enumerate(funcs):
        if "v128" in (*func.params, *func.results):
            continue
        several = len(func.results) > 1
        codes = "".join(_MULTI_CODE[t] for t in func.results)
        ret = f"struct wasm_multi_{codes}" if several else _CTYPE[func.results[0]] if func.results else "void"
        params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(func.params))
        args = "".join(f", a{j}" for j in range(len(func.params)))
        C(f"static {ret} api_link{i}(void *inst{params}, int *trapped) {{")
        if func.results:
            C(f"    {ret} r = {last}_call{i}(inst{args}, trapped);")
            C("    if (*trapped) *trapped += WASMEXT_TRAP_LINKED;")
            C("    return r;")
        else:
            C(f"    {last}_call{i}(inst{args}, trapped);")
            C("    if (*trapped) *trapped += WASMEXT_TRAP_LINKED;")
        C("}")
        C("")
        shims[i] = f"api_link{i}"
    C(f"static wasmext_export *api_record({last}_t *m, void *owner, {last}_export *out) {{")
    C("    wasmext_export *e = (wasmext_export *)out;")
    C("    memset(e, 0, sizeof *e);")
    C("    e->size = sizeof *e;")
    C("    e->abi = WASMEXT_ABI;")
    C("    e->owner = owner;")
    C("    e->runtime = WASMEXT_RUNTIME;")
    C("    e->instance = &m->core.inst;")
    C("    return e;")
    C("}")
    C("")
    C(f"int {last}_export_find({last}_t *m, const char *name, void *owner, {last}_export *out) {{")
    C("    wasmext_export *e;  /* `out` is left as it was when there is no such export */")
    for i, shim in shims.items():
        name, func = funcs[i]
        C(f"    if (strcmp(name, {_c_string(name)}) == 0) {{")
        C("        e = api_record(m, owner, out);")
        C("        e->kind = WASMEXT_FUNC;")
        C(
            "        e->flags = 8u"
            + (" | 16u" if trap_handler else "")
            + ";  /* bit 3: the function can be called without Python, with no GIL; bit 4: the module shares tables, so the function may be put in one */"
        )
        C(f"        e->address = (void *){shim};")
        C(f"        e->signature = {_c_string(_signature_code(func))};")
        C(f"        e->funcref = (const void *){last}_glue_funcref(&m->core, {i});")
        C("        wasmext_export_seal(e);")
        C("        return 0;")
        C("    }")
    for mi, name in enumerate(memories):
        lim = (memory_limits or [None] * len(memories))[mi]
        is64 = int(bool(getattr(lim, "is64", False)))
        C(f"    if (strcmp(name, {_c_string(name)}) == 0) {{")
        C("        e = api_record(m, owner, out);")
        C("        e->kind = WASMEXT_MEMORY;")
        C(f"        e->address = (void *)w2c_{prefix}_{mangle(name)}(&m->core.inst);")
        C("        e->type = (uint32_t)sizeof(wasm_rt_memory_t);")
        C(f"        e->flags = {2 * is64}u | (WASM_RT_MEMCHECK_GUARD_PAGES ? 4u : 0u);")
        C("        wasmext_export_seal(e);")
        C("        return 0;")
        C("    }")
    for name in tables or ():
        C(f"    if (strcmp(name, {_c_string(name)}) == 0) {{")
        C("        e = api_record(m, owner, out);")
        C("        e->kind = WASMEXT_TABLE;")
        C(f"        e->address = (void *)w2c_{prefix}_{mangle(name)}(&m->core.inst);")
        C("        e->type = (uint32_t)sizeof(wasm_rt_funcref_table_t);")
        C("        wasmext_export_seal(e);")
        C("        return 0;")
        C("    }")
    for name, glob in globals_ or ():
        if glob.type not in _API_TYPE:
            continue
        C(f"    if (strcmp(name, {_c_string(name)}) == 0) {{")
        C("        e = api_record(m, owner, out);")
        C("        e->kind = WASMEXT_GLOBAL;")
        C(f"        e->address = (void *)w2c_{prefix}_{mangle(name)}(&m->core.inst);")
        C(f"        e->type = {_TYPE_CODE[glob.type]};")
        C(f"        e->flags = {int(glob.mutable)}u;")
        C("        wasmext_export_seal(e);")
        C("        return 0;")
        C("    }")
    C("    return 1;")
    C("}")
    C("")
    A("")
    A("#ifdef __cplusplus")
    A("}")
    A("#endif")
    A("#endif")
    return "\n".join(a) + "\n", "\n".join(c) + "\n", model
