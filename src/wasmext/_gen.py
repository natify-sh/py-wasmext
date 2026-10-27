"""The C glue of an extension module: a parsed WebAssembly module in, the source of a CPython extension out.

    glue = generate(parse(wasm_bytes), "pkg.fast")
    glue.source        # C, to be compiled together with the C that `wasm2c --module-name=fast` writes
    glue.skipped       # exports that the extension does not expose, with the reason

The extension has a class `Instance`: `Instance(imports)` instantiates the module (`imports` is `{module: {name:
callable}}`, needed only if the module imports functions), the exported functions are its methods and an exported
memory is a read-write `memoryview` attribute. A trap is `Trap` (a `RuntimeError`), a missing import `LinkError`. Integers
are what WebAssembly has: arguments are taken modulo 2**32 / 2**64 and results are signed (as in the JavaScript API). An
exported function with several results gives them back as a tuple; an imported one returns one. An exported global is an
attribute (read-only if the global is immutable); an imported immutable global is a number in the imports.

The C uses only the limited API (PEP 384, 3.11+), so defining `Py_LIMITED_API` builds an abi3 extension.

Not yet: reference types, imported memories/tables and mutable globals, exported tables.
"""

from __future__ import annotations

import functools
import keyword
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._wasi_p2_table import FUNCS as _P2_FUNCS
from ._wasi_p2_table import INCLUDES as _P2_INCLUDES
from ._wasm import FuncType, GlobalType, Import, Limits, Module, TableType, ValType

__all__ = ["GenError", "Glue", "generate", "mangle"]

_CTYPE: dict[ValType, str] = {
    "i32": "u32",
    "i64": "u64",
    "f32": "f32",
    "f64": "f64",
    "v128": "v128",
    "funcref": "wasm_rt_funcref_t",  # in the signature of an export only (see _why_not)
}
# Python -> wasm value, wasm -> Python value, and the Py_BuildValue code with the cast it needs. An integer comes back
# signed, as the JavaScript API, wasmtime and wasm3 give it (and a negative or too big one is taken, wrapped).
_TO_WASM: dict[ValType, str] = {
    "i32": "(u32)PyLong_AsUnsignedLongMask({0})",
    "i64": "(u64)PyLong_AsUnsignedLongLongMask({0})",
    "f32": "(f32)PyFloat_AsDouble({0})",
    "f64": "PyFloat_AsDouble({0})",
    "v128": "wasmext_bytes_v128({0})",
    "funcref": "funcref_arg(self, {0})",
}
_FROM_WASM: dict[ValType, str] = {
    "i32": "PyLong_FromLong((long)(int32_t){0})",
    "i64": "PyLong_FromLongLong((long long)(int64_t){0})",
    "f32": "PyFloat_FromDouble((double){0})",
    "f64": "PyFloat_FromDouble({0})",
    "v128": "wasmext_v128_bytes({0})",
    "funcref": "funcref_result({0}, (PyObject *)self)",
}
_BUILD: dict[ValType, tuple[str, str]] = {
    "i32": ("l", "(long)(int32_t){0}"),
    "i64": ("L", "(long long)(int64_t){0}"),
    "f32": ("d", "(double){0}"),
    "f64": ("d", "(double){0}"),
    "v128": ("N", "wasmext_v128_bytes({0})"),
    "funcref": ("N", "funcref_result({0}, (PyObject *)self)"),
}


class GenError(ValueError):
    """The module cannot be turned into an extension (yet)."""


@dataclass(frozen=True, slots=True)
class Glue:
    source: str  # the C of the glue
    skipped: list[str] = field(default_factory=list[str])
    notes: list[str] = field(default_factory=list[str])  # things worth saying that do not lose anything
    stub: str = ""  # the .pyi of the extension module
    wasi_headers: tuple[
        str, ...
    ] = ()  # the headers of wasmext for WASI that the glue includes (and those they share: wasi_p1_core.h and wasi_python.h): copied beside it
    api_header: str = ""  # the public header of the C API of the shared library (<name>_api.h), no Python in it
    shared: str = ""  # the C of the shared library (<name>_shared.c); both are empty when `shared_unsupported` says why
    shared_unsupported: str = ""
    api_model: Any = (
        None  # the ApiModel of the C API (wasmext._shared), None when there is no shared library for the module
    )
    header: str = ""  # the C of the glue of the module (<name>_glue.h): typed functions, no Python; the Python layer (`source`, <name>_py.c) includes it
    trap_handler: str = ""  # a module that shares tables is built, as an extension, with WASMEXT_TRAP_HANDLER=<this> and WASM_RT_TRAP_HANDLER=<this> (see wasmext_glue.h); empty for the others


def module_prefix(name: str) -> str:
    """The `<prefix>` of `w2c_<prefix>_...`: what wasm2c makes of the name of the extension module (dotted, as it is imported)."""
    return mangle(_ident(name), module=True)


def mangle(name: str, *, module: bool = False) -> str:
    """The C identifier `wasm2c` makes of a WebAssembly name (CWriter::Mangle in WABT); `module` for module names.

    Letters and digits stay, anything else (and an underscore at either end or after another one, and a hex digit of
    capitals after "0x") becomes `0xHH` of its UTF-8 bytes; in a module name every underscore is doubled."""
    data = name.encode("utf-8")
    out: list[str] = []
    state = "any"  # any, zero ("0" seen), zerox ("0x" seen)
    last_underscore = False
    for i, ch in enumerate(data):
        c = chr(ch)
        if state == "zerox" and (c.isdigit() or "A" <= c <= "F") and ch < 0x80:
            out.append(f"0x{ch:02X}")  # rule 1
            last_underscore = False
            state = "any"
            continue
        state = {"any": "zero" if c == "0" else "any", "zero": "zerox" if c == "x" else "any", "zerox": "any"}[state]
        if c == "_" and (i == 0 or i == len(data) - 1 or last_underscore):  # rule 2
            out.append(f"0x{ch:02X}")
            last_underscore = False
        elif module and c == "_":  # rule 3
            out.append("__")
            last_underscore = True
        elif ch < 0x80 and (c.isalnum() or c == "_"):  # rule 4
            out.append(c)
            last_underscore = c == "_"
        else:
            out.append(f"0x{ch:02X}")
            last_underscore = False
    return "".join(out)


def _cc(text: str) -> str:
    """`text` made safe to stand in a C comment: a name in the module can be anything, even `*/` and a line end followed by code."""
    plain = "".join(c if c.isprintable() else "?" for c in text)
    return plain.replace("*/", "* /").replace("/*", "/ *")


def _c_string(text: str) -> str:
    """A C string literal (octal escapes: they cannot swallow the characters that follow, as hex ones would)."""
    out = ['"']
    for b in text.encode("utf-8"):
        if b in (0x22, 0x5C):
            out.append("\\" + chr(b))
        elif 0x20 <= b < 0x7F and chr(b) != "?":
            out.append(chr(b))
        else:
            out.append(f"\\{b:03o}")
    out.append('"')
    return "".join(out)


def _signature_code(func: FuncType) -> str:
    """The parameters, '>', the results as one letter each: what two extensions compare before one calls the other."""
    return "".join(_MULTI_CODE[t] for t in func.params) + ">" + "".join(_MULTI_CODE[t] for t in func.results)


def _signature(func: FuncType) -> str:
    return f"({', '.join(func.params)}) -> {', '.join(func.results) or 'None'}"


# the types that a global, an exception value or a function of the host can have: a funcref is only in the signature of an export (and an element of a table)
_PLAIN: frozenset[str] = frozenset({"i32", "i64", "f32", "f64", "v128"})


def _why_not(func: FuncType, *, several_results: bool = False, funcref: bool = False) -> str | None:
    """Why the glue cannot take a function of this type, or None. A function may have several results (an exported one
    gives them back as a tuple, an imported one is to return a tuple) when `several_results` is true. A `funcref` is taken in an exported function (`funcref`)."""
    bad = sorted({t for t in (*func.params, *func.results) if t not in _CTYPE or (t == "funcref" and not funcref)})
    if bad:
        return f"uses {', '.join(bad)}"
    if len(func.results) > 1 and not several_results:
        return "has several results"
    return None


def _ident(name: str) -> str:
    """The module name the C side uses: the last component of the dotted Python name."""
    last = name.rsplit(".", 1)[-1]
    if not last.isidentifier() or not last.isascii():
        raise GenError(f"{name!r} is not a valid extension module name")
    return last


# the modules a WASI program imports its system calls from; wasmext gives them (the headers of src/wasmext/c) unless the caller does
_WASI_PREVIEW1 = "wasi_snapshot_preview1"
_WASI_UNSTABLE = "wasi_unstable"  # the first snapshot
_WASI_HEADERS = {_WASI_PREVIEW1: "wasi_p1.h", _WASI_UNSTABLE: "wasi_p1_unstable.h"}

# who stands on the other side of the imports of a module (docs/wasi_target.md): `wasm32` binds nothing, `wasm32-wasip1` binds WASI 0.1
HOSTS = ("wasm32", "wasm32-wasip1", "wasm32-wasip2")
DEFAULT_HOST = "wasm32"
HOST_ALIASES = {"wasm32-unknown-unknown": "wasm32"}


def check_host(host: str) -> str:
    """The name of `host` that wasmext keeps (an alias such as `wasm32-unknown-unknown` is turned into `wasm32`), or a GenError for a host that is not known."""
    host = HOST_ALIASES.get(host, host)
    if host not in HOSTS:
        extra = " (WASI 0.3 is not supported)" if host == "wasm32-wasip3" else ""
        raise GenError(f"host {host!r} is not one of {', '.join(HOSTS)}{extra}")
    return host


def _p2_cname(module: str, name: str) -> str:
    """The name of the function of fusedwasi for an import of WASI 0.2: the module without its version and the name, every character that is not a letter or
    a digit turned into `_` (`wasi:io/streams@0.2.12` `[method]output-stream.write` is `fusedwasi_wasi_io_streams_output_stream_write`)."""
    base = module.split("@")[0].replace(":", "/")
    if name.startswith("[resource-drop]"):
        name = name[len("[resource-drop]") :] + "-drop"
    elif name.startswith("[constructor]"):
        name = name[len("[constructor]") :] + "-new"
    name = re.sub(r"^\[(method|static)\]", "", name).replace(".", "-")
    return "fusedwasi_" + re.sub(r"[^0-9A-Za-z]+", "_", f"{base}/{name}").strip("_")


def _p2_headers(calls: dict[tuple[str, str], str], include: bool = False) -> list[str]:
    """The headers of fusedwasi for the functions in `calls`, with the ones they include, the core and the streams that wasmext's own host needs (dependencies first).
    With `include`, only the ones the glue includes: the backends of the system (`..._fs_posix.h`, `..._fs_win32.h`) are included by the header of the files, one for each
    system, so they are copied (the build needs both) and not included."""
    wanted = ["wasi_p2_core.h", "wasi_p2_io.h", "wasi_p2_cli.h", "wasi_p2_filesystem.h"] + [
        _P2_FUNCS[c][0] for c in calls.values()
    ]
    order: list[str] = []

    def visit(header: str) -> None:
        if header in order:
            return
        for dep in _P2_INCLUDES.get(header, ()):
            visit(dep)
        order.append(header)

    for header in wanted:
        visit(header)
    return [h for h in order if not (include and h.endswith(("_fs_posix.h", "_fs_win32.h")))]


# the 46 calls of WASI 0.1 and their signatures (the witx files of the wasi-0.1 branch of WebAssembly/WASI): wasi_p1.h has a
# function for each, and a module that imports one with another signature is refused when the glue is made
_WASI_PREVIEW1_SIGNATURES = {
    "args_get": "ii>i",
    "args_sizes_get": "ii>i",
    "environ_get": "ii>i",
    "environ_sizes_get": "ii>i",
    "clock_res_get": "ii>i",
    "clock_time_get": "iji>i",
    "random_get": "ii>i",
    "sched_yield": ">i",
    "proc_exit": "i>",
    "proc_raise": "i>i",
    "poll_oneoff": "iiii>i",
    "fd_read": "iiii>i",
    "fd_pread": "iiiji>i",
    "fd_write": "iiii>i",
    "fd_pwrite": "iiiji>i",
    "fd_seek": "ijii>i",
    "fd_tell": "ii>i",
    "fd_advise": "ijji>i",
    "fd_allocate": "ijj>i",
    "fd_datasync": "i>i",
    "fd_sync": "i>i",
    "fd_close": "i>i",
    "fd_renumber": "ii>i",
    "fd_fdstat_get": "ii>i",
    "fd_fdstat_set_flags": "ii>i",
    "fd_fdstat_set_rights": "ijj>i",
    "fd_filestat_get": "ii>i",
    "fd_filestat_set_size": "ij>i",
    "fd_filestat_set_times": "ijji>i",
    "fd_prestat_get": "ii>i",
    "fd_prestat_dir_name": "iii>i",
    "fd_readdir": "iiiji>i",
    "path_create_directory": "iii>i",
    "path_filestat_get": "iiiii>i",
    "path_filestat_set_times": "iiiijji>i",
    "path_link": "iiiiiii>i",
    "path_open": "iiiiijjii>i",
    "path_readlink": "iiiiii>i",
    "path_remove_directory": "iii>i",
    "path_rename": "iiiiii>i",
    "path_symlink": "iiiii>i",
    "path_unlink_file": "iii>i",
    "sock_accept": "iii>i",
    "sock_recv": "iiiiii>i",
    "sock_send": "iiiii>i",
    "sock_shutdown": "ii>i",
}
# the first snapshot has the same calls but sock_accept
_WASI_SIGNATURES = {
    _WASI_PREVIEW1: _WASI_PREVIEW1_SIGNATURES,
    _WASI_UNSTABLE: {n: sig for n, sig in _WASI_PREVIEW1_SIGNATURES.items() if n != "sock_accept"},
}
# the calls of the first snapshot that have a function of their own, wasi_unstable_<name> (the others use wasi_<name>)
_WASI_UNSTABLE_OWN: frozenset[str] = frozenset(
    {"fd_seek", "fd_fdstat_get", "fd_filestat_get", "path_filestat_get", "poll_oneoff"}
)


@dataclass
class _Import:
    module: str
    field: str
    func: FuncType
    host: int  # index of the import module (the struct that holds its callables)
    slot: int  # the place among the callables of that module
    symbol: str


@dataclass
class _ImportMemory:
    module: str
    field: str
    limits: Limits
    host: int  # index of the import module (the struct that holds the pointer)
    slot: int  # the place among the memories of that module
    symbol: str


@dataclass
class _ImportTable:
    module: str
    field: str
    limits: Limits
    host: int  # index of the import module (the struct that holds the pointer)
    slot: int  # the place among the tables of that module
    symbol: str


@dataclass
class _ImportGlobal:
    module: str
    field: str
    type: ValType
    host: int  # index of the import module (the struct that holds the value)
    slot: int  # the place among the globals of that module
    symbol: str
    mutable: bool = False


def _emit_links(
    hadd: Callable[[str], None],
    last: str,
    imports: list[_Import],
    global_imports: list[_ImportGlobal],
    memory_imports: list[_ImportMemory],
    hosts: list[str],
    table_imports: list[_ImportTable],
) -> None:
    """The C that links an import to an export of another instance (a `wasmext_export`, see wasmext_glue.h), for every host that has Python or has
    not: it checks what the export is (kind, type, signature, size) and, if it fits, puts it where the module reads its import. 0 when linked;
    1 with the message in `msg` otherwise. Keeping the other instance alive is the host's business."""
    incompatible = "the export is from an incompatible version of wasmext"
    for k, imp in enumerate(imports):
        where = f"{imp.module}.{imp.field}"
        hadd(f"/* the import {_cc(where)}: a function of another instance */")
        hadd(
            f"static inline int {last}_link_func{k}({last}_instance *core, const wasmext_export *e, char *msg, size_t cap) {{"
        )
        hadd(
            f"    if (!wasmext_export_ok(e)) return wasmext_link_fail(msg, cap, {_c_string(f'import {where}: {incompatible}')});"
        )
        hadd(
            f"    if (e->kind != WASMEXT_FUNC) return wasmext_link_fail(msg, cap, {_c_string(f'import {where} is a function: the export given is not')});"
        )
        hadd(f"    if (strcmp(e->signature, {_c_string(_signature_code(imp.func))}) != 0) {{")
        hadd(
            f'        snprintf(msg, cap, "import {where} is a function {_signature_code(imp.func)}: the export given is another one (%s)", e->signature);'
        )
        hadd("        return 1;")
        hadd("    }")
        hadd(f"    core->host{imp.host}.fn[{imp.slot}] = e->address;")
        hadd(f"    core->host{imp.host}.user[{imp.slot}] = e->instance;")
        hadd("    return 0;")
        hadd("}")
        hadd("")
    for j, g in enumerate(global_imports):
        where = f"{g.module}.{g.field}"
        expected = f"{'mutable ' if g.mutable else ''}{g.type}"
        hadd(f"/* the import {_cc(where)}: a global of another instance, or (an immutable one) a value */")
        hadd(
            f"static inline int {last}_link_global{j}({last}_instance *core, const wasmext_export *e, char *msg, size_t cap) {{"
        )
        hadd(
            f"    if (!wasmext_export_ok(e)) return wasmext_link_fail(msg, cap, {_c_string(f'import {where}: {incompatible}')});"
        )
        hadd(
            f"    if (e->kind != WASMEXT_GLOBAL) return wasmext_link_fail(msg, cap, {_c_string(f'import {where} is a global: the export given is not')});"
        )
        hadd(f"    if (e->type != {_TYPE_CODE[g.type]} || (e->flags & 1) != {int(g.mutable)})")
        hadd(
            f"        return wasmext_link_fail(msg, cap, {_c_string(f'import {where} is a {expected} global: the export given has another type or the other mutability')});"
        )
        hadd(f"    core->host{g.host}.gp{g.slot} = ({_CTYPE[g.type]} *)e->address;")
        hadd("    return 0;")
        hadd("}")
        hadd("")
        if not g.mutable:
            hadd(f"static inline void {last}_set_global{j}({last}_instance *core, {_CTYPE[g.type]} value) {{")
            hadd(f"    core->host{g.host}.g{g.slot} = value;")
            hadd(f"    core->host{g.host}.gp{g.slot} = &core->host{g.host}.g{g.slot};")
            hadd("}")
            hadd("")
    for j, tb in enumerate(table_imports):
        where = f"{tb.module}.{tb.field}"
        lim = tb.limits
        hadd(f"/* the import {_cc(where)}: the table of another instance (a funcref table; see TABLES_PLAN.md) */")
        hadd(
            f"static inline int {last}_link_table{j}({last}_instance *core, const wasmext_export *e, char *msg, size_t cap) {{"
        )
        hadd(
            f"    if (!wasmext_export_ok(e)) return wasmext_link_fail(msg, cap, {_c_string(f'import {where}: {incompatible}')});"
        )
        hadd(
            f"    if (e->kind != WASMEXT_TABLE) return wasmext_link_fail(msg, cap, {_c_string(f'import {where} is a table: the export given is not')});"
        )
        hadd("    wasm_rt_funcref_table_t *tab = (wasm_rt_funcref_table_t *)e->address;")
        hadd(
            f"    if (e->type != sizeof(wasm_rt_funcref_table_t)) return wasmext_link_fail(msg, cap, {_c_string(f'import {where}: the table is from an incompatible runtime of wasm2c')});"
        )
        hadd(f"    if (tab->size < {lim.min}u) {{")
        hadd(
            f'        snprintf(msg, cap, "import {where}: the table has %lu elements, the module needs at least {lim.min}", (unsigned long)tab->size);'
        )
        hadd("        return 1;")
        hadd("    }")
        if lim.max is not None:
            hadd(f"    if (tab->max_size > {lim.max}u) {{")
            hadd(
                f'        snprintf(msg, cap, "import {where}: the table may grow to %lu elements, the module allows {lim.max}", (unsigned long)tab->max_size);'
            )
            hadd("        return 1;")
            hadd("    }")
        hadd(f"    core->host{tb.host}.tp{tb.slot} = tab;")
        hadd("    return 0;")
        hadd("}")
        hadd("")
    if table_imports:
        # An instance that put functions of its own in the table of another (an `elem` segment, `table.set`...) must not outlive them without that being known to
        # the owner of the table (the owner keeps it alive); one whose instantiation failed has to take back what it wrote before it is freed.
        hadd(
            "/* take back from the tables this instance imports the functions it put there (a failed instantiation leaves some) */"
        )
        hadd(f"static inline void {last}_scrub_tables({last}_instance *core) {{")
        for tb in table_imports:
            hadd("    {")
            hadd(f"        wasm_rt_funcref_table_t *tab = core->host{tb.host}.tp{tb.slot};")
            hadd("        for (uint32_t i = 0; tab != NULL && i < tab->size; i++) {")
            hadd("            const char *mi = (const char *)tab->data[i].module_instance;")
            hadd(
                "            if (mi >= (const char *)core && mi < (const char *)(core + 1)) memset(&tab->data[i], 0, sizeof tab->data[i]);"
            )
            hadd("        }")
            hadd("    }")
        hadd("}")
        hadd("")
    for j, m in enumerate(memory_imports):
        where = f"{m.module}.{m.field}"
        lim = m.limits
        hadd(f"/* the import {_cc(where)}: the memory of another instance */")
        hadd(
            f"static inline int {last}_link_memory{j}({last}_instance *core, const wasmext_export *e, char *msg, size_t cap) {{"
        )
        hadd(
            f"    if (!wasmext_export_ok(e)) return wasmext_link_fail(msg, cap, {_c_string(f'import {where}: {incompatible}')});"
        )
        hadd(
            f"    if (e->kind != WASMEXT_MEMORY) return wasmext_link_fail(msg, cap, {_c_string(f'import {where} is a memory: the export given is not')});"
        )
        hadd("    wasm_rt_memory_t *mem = (wasm_rt_memory_t *)e->address;")
        hadd(
            f"    if (e->type != sizeof(wasm_rt_memory_t)) return wasmext_link_fail(msg, cap, {_c_string(f'import {where}: the memory is from an incompatible runtime of wasm2c')});"
        )
        hadd(
            f"    if (((e->flags >> 1) & 1) != {int(lim.is64)}) return wasmext_link_fail(msg, cap, {_c_string(f'import {where} is a 64-bit memory the other way: memory64 differs')});"
        )
        hadd(
            f"    if (((e->flags >> 2) & 1) != (WASM_RT_MEMCHECK_GUARD_PAGES ? 1 : 0)) return wasmext_link_fail(msg, cap, {_c_string(f'import {where}: one module is built with guard pages and the other without (--no-guard-pages)')});"
        )
        hadd(f"    if (mem->pages < {lim.min}ULL) {{")
        hadd(
            f'        snprintf(msg, cap, "import {where}: the memory has %llu pages, the module needs at least {lim.min}", (unsigned long long)mem->pages);'
        )
        hadd("        return 1;")
        hadd("    }")
        if lim.max is not None:
            hadd(f"    if (mem->max_pages > {lim.max}ULL) {{")
            hadd(
                f'        snprintf(msg, cap, "import {where}: the memory may grow to %llu pages, the module allows {lim.max}", (unsigned long long)mem->max_pages);'
            )
            hadd("        return 1;")
            hadd("    }")
        hadd(f"    core->host{m.host}.mp{m.slot} = mem;")
        hadd("    return 0;")
        hadd("}")
        hadd("")


def generate(
    module: Module, name: str, *, version: str | None = None, share_tables: bool = False, host: str = DEFAULT_HOST
) -> Glue:
    """The C source of the extension module `name` (dotted, as it is imported) for the parsed `module`. `version`, the version of
    wasmext, goes into the header of the stub. `host` says who stands on the other side of the imports (see HOSTS): only with
    `wasm32-wasip1` are the imports of `wasi_snapshot_preview1` and `wasi_unstable` answered by wasmext; with `wasm32` all of them are the caller's."""
    host = check_host(host)
    wasi2 = host == "wasm32-wasip2"
    wasi_headers: dict[str, str] = dict(_WASI_HEADERS) if host == "wasm32-wasip1" else {}
    if wasi2:  # the imports of WASI 0.2 (any 0.2.x: the patch releases are compatible) are answered by the host
        wasi_headers = {
            imp.module: ""
            for imp in module.imports
            if imp.kind == "func" and imp.module.startswith("wasi:") and "@0.2." in imp.module
        }
    p2_calls: dict[tuple[str, str], str] = {}  # (module, field): the function of fusedwasi
    host_name = host
    last = _ident(name)
    prefix = mangle(last, module=True)
    skipped: list[str] = []

    # imports: functions (every signature must be one the glue can convert) and immutable globals (a number is given)
    hosts: list[str] = []
    imports: list[_Import] = []
    global_imports: list[_ImportGlobal] = []
    slots: dict[str, int] = {}
    global_slots: dict[str, int] = {}
    memory_imports: list[_ImportMemory] = []
    memory_slots: dict[str, int] = {}
    table_imports: list[_ImportTable] = []
    table_slots: dict[str, int] = {}
    for imp in module.imports:
        if "\0" in imp.module or "\0" in imp.name:  # a C string ends at the NUL: the name would be another one
            raise GenError(f"import {imp.module!r}.{imp.name!r}: a null character in a name is not supported")
        symbol = f"w2c_{mangle(imp.module, module=True)}_{mangle(imp.name)}"
        if imp.kind == "func" and isinstance(imp.type, FuncType):
            reason = _why_not(
                imp.type, several_results=True
            )  # a funcref in the signature of an import is not supported
            if reason:
                raise GenError(f"import {imp.module}.{imp.name} {reason}: not supported yet")
            if imp.module in wasi_headers and wasi2:
                cname = _p2_cname(imp.module, imp.name)
                entry = _P2_FUNCS.get(cname)
                if entry is None:
                    raise GenError(f"import {imp.module}.{imp.name} is not a function of WASI 0.2 that fusedwasi has")
                _, _, ptypes, rtype = entry
                if tuple(str(t) for t in imp.type.params) != ptypes or tuple(str(t) for t in imp.type.results) != (
                    (rtype,) if rtype else ()
                ):
                    raise GenError(
                        f"import {imp.module}.{imp.name} is {_signature_code(imp.type)}, fusedwasi says ({', '.join(ptypes)}) -> ({rtype})"
                    )
                p2_calls[(imp.module, imp.name)] = cname
            elif imp.module in wasi_headers:
                wanted = _WASI_SIGNATURES[imp.module].get(imp.name)
                if wanted is None:
                    raise GenError(f"import {imp.module}.{imp.name} is not a function of {imp.module}")
                if _signature_code(imp.type) != wanted:
                    raise GenError(
                        f"import {imp.module}.{imp.name} is {_signature_code(imp.type)}, {imp.module} says {wanted}"
                    )
            same = next((i for i in imports if i.module == imp.module and i.field == imp.name), None)
            if (
                same is not None
            ):  # the same function imported twice (AssemblyScript does): wasm2c names both alike, so one is made
                if same.func != imp.type:
                    raise GenError(f"import {imp.module}.{imp.name} is imported twice with different types")
                continue
            if imp.module not in hosts:
                hosts.append(imp.module)
            slot = slots.get(imp.module, 0)
            slots[imp.module] = slot + 1
            imports.append(_Import(imp.module, imp.name, imp.type, hosts.index(imp.module), slot, symbol))
        elif imp.kind == "global" and isinstance(imp.type, GlobalType):
            if imp.type.type not in _CTYPE or imp.type.type == "funcref":
                raise GenError(f"import {imp.module}.{imp.name} uses {imp.type.type}: not supported yet")
            if imp.module not in hosts:
                hosts.append(imp.module)
            slot = global_slots.get(imp.module, 0)
            global_slots[imp.module] = slot + 1
            global_imports.append(
                _ImportGlobal(
                    imp.module, imp.name, imp.type.type, hosts.index(imp.module), slot, symbol, imp.type.mutable
                )
            )
        elif imp.kind == "memory" and isinstance(imp.type, Limits):
            if imp.type.shared:
                raise GenError(f"import {imp.module}.{imp.name}: an imported shared memory is not supported yet")
            if imp.module not in hosts:
                hosts.append(imp.module)
            slot = memory_slots.get(imp.module, 0)
            memory_slots[imp.module] = slot + 1
            memory_imports.append(_ImportMemory(imp.module, imp.name, imp.type, hosts.index(imp.module), slot, symbol))
        elif imp.kind == "table" and isinstance(imp.type, TableType):
            if imp.type.elem != "funcref":
                raise GenError(
                    f"import {imp.module}.{imp.name}: an imported {imp.type.elem} table is not supported yet"
                )
            if imp.type.limits.is64 or imp.type.limits.shared:
                raise GenError(
                    f"import {imp.module}.{imp.name}: an imported {'64-bit' if imp.type.limits.is64 else 'shared'} table is not supported yet"
                )
            if imp.module not in hosts:
                hosts.append(imp.module)
            slot = table_slots.get(imp.module, 0)
            table_slots[imp.module] = slot + 1
            table_imports.append(
                _ImportTable(imp.module, imp.name, imp.type.limits, hosts.index(imp.module), slot, symbol)
            )
        else:
            raise GenError(f"import {imp.module}.{imp.name}: an imported {imp.kind} is not supported yet")

    # exports: functions and memories; the rest is left out, and reported
    funcs: list[tuple[str, FuncType]] = []
    param_names: dict[str, tuple[str | None, ...]] = {}
    memories: list[str] = []
    memory_limits: list[Limits] = []
    globals_: list[tuple[str, GlobalType]] = []
    tables: list[str] = []  # the funcref tables the module defines and exports: other instances can import them
    imported_tables = len(table_imports)
    no_attribute: set[str] = set()
    for exp in module.exports:
        if "\0" in exp.name:  # a C string ends at the NUL: the export would be another one
            skipped.append(f"{exp.kind} {exp.name!r} has a null character in its name")
            continue
        if _reserved(exp.name) and exp.kind in ("func", "memory", "global"):
            # not an attribute (it would replace a special name of Instance), but instance.__exports__[name] reaches it
            skipped.append(
                f"{exp.kind} {exp.name!r} is not an attribute (it would hide a special name of Instance): instance.__exports__[{exp.name!r}]"
            )
            no_attribute.add(exp.name)
        if exp.kind == "func":
            func = module.all_functions[exp.index]
            reason = _why_not(func, several_results=True, funcref=True)
            if reason:
                skipped.append(f"function {exp.name!r} {reason}")
            else:
                funcs.append((exp.name, func))
                param_names[exp.name] = module.param_names(exp.index)
        elif exp.kind == "memory":
            memories.append(exp.name)  # a memory64 is the same buffer: only its address type differs
            memory_limits.append(module.all_memories[exp.index])
        elif exp.kind == "global":
            glob = module.all_globals[exp.index]
            if glob.type in _PLAIN:
                globals_.append((exp.name, glob))
            else:
                skipped.append(f"global {exp.name!r} uses {glob.type}")
        elif exp.kind == "table":
            table = module.all_tables[exp.index]
            if exp.index < imported_tables:
                skipped.append(f"table {exp.name!r} is an imported table: exporting it again is not supported yet")
            elif table.elem != "funcref" or table.limits.is64 or table.limits.shared:
                what = (
                    "a 64-bit table"
                    if table.limits.is64
                    else "a shared table"
                    if table.limits.shared
                    else "an externref table"
                    if table.elem == "externref"
                    else f"a {table.elem} table"
                )
                skipped.append(f"table {exp.name!r} is {what}")
            else:
                tables.append(exp.name)
        else:
            skipped.append(f"{exp.kind} {exp.name!r}")

    uses_funcref = any(
        "funcref" in (*f.params, *f.results) for _, f in funcs
    )  # a Function comes out of (or goes into) a call: the module has the class
    funcref_args = any(
        "funcref" in f.params for _, f in funcs
    )  # and a function that is given must outlive the call: the instance keeps what it was given
    shares_tables = bool(
        tables or table_imports or share_tables or uses_funcref
    )  # a function of the module can be called by another instance (or the other way) with no step of the host between; `share_tables` asks for it
    trap_handler = f"wasmext_trap_{prefix}" if shares_tables else ""
    ref_types = (
        _ref_types(module) if shares_tables else []
    )  # the types of the elements of a table that a Function of this module can call
    has_imports = bool(imports or global_imports or memory_imports or table_imports)
    wasi_modules = sorted({imp.module for imp in imports if imp.module in wasi_headers})
    uses_wasi = bool(wasi_modules)
    # without other imports the caller need not give any: the module gets WASI by itself
    needs_imports = any(imp.module not in wasi_headers for imp in imports) or bool(
        global_imports or memory_imports or table_imports
    )
    if uses_wasi and "memory" not in memories:
        raise GenError(f"the module imports {wasi_modules[0]} but does not export its memory as 'memory'")
    if wasi2 and uses_wasi and "cabi_realloc" not in {n for n, _ in funcs}:
        raise GenError(
            f"the module imports {wasi_modules[0]} but does not export 'cabi_realloc' (a component's allocator: the host needs it for strings and lists)"
        )
    w: list[str] = []  # the Python layer (<name>_py.c)
    add = w.append
    h: list[str] = []  # the glue of the module (<name>_glue.h): typed C, no Python.h
    hadd = h.append
    guard = f"WASMEXT_GLUE_{prefix.upper()}_H"
    reentrant = "REENTRANT" if has_imports else "PLAIN"

    hadd(
        f"/* Generated by wasmext from the WebAssembly module of {last}: do not edit. The glue of the module: typed C functions, no Python.h. */"
    )
    hadd(f"#ifndef {guard}")
    hadd(f"#define {guard}")
    if (
        wasi2 and uses_wasi
    ):  # wasm-rt.h includes windows.h, whose winsock.h clashes with the winsock2.h of the sockets of WASI 0.2
        hadd("#if defined(_WIN32) && !defined(WIN32_LEAN_AND_MEAN)")
        hadd("#define WIN32_LEAN_AND_MEAN")
        hadd("#endif")
    hadd(f'#include "{last}_w2c.h"')
    hadd('#include "wasmext_glue.h"')
    if not wasi2:
        for module_name in wasi_modules:
            hadd(f'#include "{wasi_headers[module_name]}"')
    if uses_wasi:  # the state of the host is the one of 0.2, for a module of 0.1 too
        for header in _p2_headers(p2_calls, include=True):
            hadd(f'#include "{header}"')
    tags = module.tags
    notes: list[str] = []
    for tag_index, tag in enumerate(tags):
        size = sum({"i32": 4, "f32": 4, "i64": 8, "f64": 8, "v128": 16}.get(str(t), 8) for t in tag.params)
        if size > 256:
            notes.append(
                f"exception tag {tag_index} carries {size} bytes: the runtime keeps at most 256, "
                "so its values are not decoded when it is not caught"
            )
    wasi_names = sorted({imp.module for imp in module.imports if imp.kind == "func" and imp.module in _WASI_HEADERS})
    if wasi_names and host_name != "wasm32-wasip1":
        notes.append(
            f"the module imports {', '.join(wasi_names)}; with host {host_name!r} they are yours to give in imports "
            "(if this is a WASI program, say host 'wasm32-wasip1')"
        )
    wasi02 = sorted(
        {
            imp.module
            for imp in module.imports
            if imp.kind == "func" and imp.module.startswith("wasi:") and "@0.2." in imp.module
        }
    )
    if wasi02 and host_name == "wasm32":
        notes.append(
            f"the module imports {', '.join(wasi02)} (WASI 0.2); with host 'wasm32' they are yours to give in imports "
            "(if this is a WASI 0.2 program, say host 'wasm32-wasip2')"
        )
    other_wasi = sorted({imp.module for imp in module.imports if imp.kind == "func" and imp.module.startswith("wasi:")})
    if other_wasi and host_name == "wasm32-wasip1":
        notes.append(
            f"the module also imports {', '.join(other_wasi)}, which host 'wasm32-wasip1' does not answer: they are yours to give in imports"
        )
    other_wasi3 = sorted(
        {
            imp.module
            for imp in module.imports
            if imp.kind == "func" and imp.module.startswith("wasi:") and "@0.2." not in imp.module
        }
    )
    if other_wasi3 and host_name == "wasm32-wasip2":
        notes.append(
            f"the module also imports {', '.join(other_wasi3)}, which host 'wasm32-wasip2' does not answer (only WASI 0.2): they are yours to give in imports"
        )
    if tags:
        hadd(
            "/* The tags of the module: their identities (a table that wasmext adds to the C of wasm2c, in the order of the tags) and the"
        )
        hadd("   values of an exception that was thrown and not caught, decoded from what the runtime keeps of it. */")
        hadd(f"extern const wasm_rt_tag_t wasmext_tags_{prefix}[{len(tags)}];")
        hadd(f"#define {last.upper()}_TAG_COUNT {len(tags)}")
        hadd(f"#define {last.upper()}_TAG_MAX_VALUES {max(1, max(len(t.params) for t in tags))}")
        hadd("")
    hadd(
        "/* The extension (WASMEXT_PY_THREADS, defined by the Python layer before it includes this file) sets the runtime of wasm2c up for any thread that"
    )
    hadd(
        "   calls into WebAssembly code (see the Python layer); the library does it in its API functions and the program has one thread. */"
    )
    hadd("#ifdef WASMEXT_PY_THREADS")
    hadd("static WASM_RT_THREAD_LOCAL int wasmext_py_ready_;")
    hadd("static void wasmext_py_thread_setup_(void);")
    hadd("#define WASMEXT_THREAD_READY() ((void)(wasmext_py_ready_ ? 0 : (wasmext_py_thread_setup_(), 0)))")
    hadd("#else")
    hadd("#define WASMEXT_THREAD_READY() ((void)0)")
    hadd("#endif")
    if shares_tables:
        hadd(
            "#ifdef WASMEXT_TRAP_HANDLER  /* the extension: the calls into this module share the stack of entries (wasmext_glue.h) */"
        )
        hadd("#define WASMEXT_ENTER_INNER(CODE, FAIL) WASMEXT_ENTER_SHARED(CODE, FAIL)")
        hadd("#define WASMEXT_LEAVE_INNER() WASMEXT_LEAVE_SHARED()")
        hadd("#else")
    hadd(f"#define WASMEXT_ENTER_INNER(CODE, FAIL) WASMEXT_ENTER_{reentrant}(CODE, FAIL)")
    hadd(f"#define WASMEXT_LEAVE_INNER() WASMEXT_LEAVE_{reentrant}()")
    if shares_tables:
        hadd("#endif")
    hadd(
        "/* WASMEXT_CHAIN (the extension, not on Windows): the runtime of this module installs no handler of signals, the Python layer installs one that is a link of a chain"
    )
    hadd(
        "   (see there); it needs to know that a call into THIS module is running in the thread, which the entry marks (the mark of an outer call is put back). */"
    )
    hadd("#ifdef WASMEXT_CHAIN")
    hadd("static WASM_RT_THREAD_LOCAL int wasmext_chain_active_;")
    hadd(
        "#define WASMEXT_ENTER(CODE, FAIL) WASMEXT_THREAD_READY(); int chain_saved_ = wasmext_chain_active_; wasmext_chain_active_ = 1; \\"
    )
    hadd("    WASMEXT_ENTER_INNER(CODE, { wasmext_chain_active_ = chain_saved_; FAIL; })")
    hadd("#define WASMEXT_LEAVE() wasmext_chain_active_ = chain_saved_; WASMEXT_LEAVE_INNER()")
    hadd(
        "/* One handler of SIGSEGV/SIGBUS is in force for the process, so the runtimes of several modules would each replace the one before it, and the signal of a fault in a"
    )
    hadd(
        "   module would reach the runtime of the module imported last, which is not the one whose call is running. Here the runtime installs none (WASMEXT_CHAIN turns its"
    )
    hadd(
        "   `sigaction` into nothing, see _natify.py); this module installs one at its import and keeps the one that was there. A fault in a call of THIS module (the mark of"
    )
    hadd(
        "   the entry, wasmext_chain_active_) is turned into a trap of its own runtime; any other fault is given to the handler that was before, so that a real crash of the process"
    )
    hadd(
        "   (or of the code of some other module) is still a crash, with whatever handler (faulthandler) was meant for it. A fault in a call of another module that was made from"
    )
    hadd(
        "   inside a call of this one is not told apart: the module imported first would take it (known gap, docs/shared_runtime_concept.md). */"
    )
    hadd("#include <signal.h>")
    hadd("static struct sigaction wasmext_chain_old_segv_, wasmext_chain_old_bus_;")
    hadd("static int wasmext_chain_installed_;")
    hadd("static void wasmext_chain_handler_(int sig, siginfo_t *si, void *ctx) {")
    hadd(
        "#ifdef WASMEXT_STACK_LIMIT  /* the stack is checked in the prologue, so a fault in a call is the memory (macOS gives the guard page another si_code than ACCERR) */"
    )
    hadd("    if (wasmext_chain_active_) wasm_rt_trap(WASM_RT_TRAP_OOB);  /* does not return */")
    hadd("#else")
    hadd(
        "    if (wasmext_chain_active_) wasm_rt_trap(si->si_code == SEGV_ACCERR ? WASM_RT_TRAP_OOB : WASM_RT_TRAP_EXHAUSTION);  /* does not return */"
    )
    hadd("#endif")
    hadd("    const struct sigaction *old = sig == SIGSEGV ? &wasmext_chain_old_segv_ : &wasmext_chain_old_bus_;")
    hadd("    if (old->sa_flags & SA_SIGINFO) {")
    hadd("        old->sa_sigaction(sig, si, ctx);")
    hadd("    } else if (old->sa_handler == SIG_DFL || old->sa_handler == SIG_IGN) {")
    hadd(
        "        signal(sig, SIG_DFL);  /* the fault happens again when this returns, and the default action ends the process as if nobody had a handler */"
    )
    hadd("    } else {")
    hadd("        old->sa_handler(sig);")
    hadd("    }")
    hadd("}")
    hadd("static int wasmext_chain_install_(void) {")
    hadd("    struct sigaction sa;")
    hadd("    if (wasmext_chain_installed_) return 0;  /* the module initialised again: do not chain to itself */")
    hadd("    memset(&sa, 0, sizeof sa);")
    hadd("    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;")
    hadd("    sigemptyset(&sa.sa_mask);")
    hadd("    sa.sa_sigaction = wasmext_chain_handler_;")
    hadd(
        "    if (sigaction(SIGSEGV, &sa, &wasmext_chain_old_segv_) != 0 || sigaction(SIGBUS, &sa, &wasmext_chain_old_bus_) != 0) {"
    )
    hadd("        return -1;")
    hadd("    }")
    hadd(
        "    (void)*(volatile int *)&wasmext_chain_active_;  /* the thread-local block is made now: the first access may allocate (macOS, lazy TLS), which a handler must not do */"
    )
    hadd("    wasmext_chain_installed_ = 1;")
    hadd("    return 0;")
    hadd("}")
    hadd("#include <pthread.h>")
    hadd("static void wasmext_chain_install_once_(void) { (void)wasmext_chain_install_(); }")
    hadd("#ifdef WASMEXT_STACK_LIMIT")
    hadd(
        "/* The stack running out is seen by the prologue of each function (a patch of the C of wasm2c, _natify.py): the address of the frame against the lowest address of the stack of the thread"
    )
    hadd(
        "   that is still safe. A thread sets its limit once, at its first call (the capsule and the alternate stack of the thread are not needed). The margin is what a function of the host"
    )
    hadd(
        "   (an import that calls Python) can use when the limit is reached: a quarter of the stack, between 32 and 256 KiB. A thread whose stack cannot be measured gets 128 KiB below here. */"
    )
    hadd("#include <pthread.h>")
    hadd("#include <stdint.h>")
    hadd('extern __thread uintptr_t wasmext_stack_limit __attribute__((visibility("hidden")));')
    hadd("static void wasmext_stack_limit_init_(void) {")
    hadd("    uintptr_t low = 0, size = 0, margin;")
    hadd("#if defined(__APPLE__)")
    hadd("    pthread_t self = pthread_self();")
    hadd("    size = (uintptr_t)pthread_get_stacksize_np(self);")
    hadd("    low = (uintptr_t)pthread_get_stackaddr_np(self) - size;  /* the address it gives is the top */")
    hadd("#else")
    hadd("    extern int pthread_getattr_np(pthread_t, pthread_attr_t *);")
    hadd("    pthread_attr_t attr;")
    hadd("    if (pthread_getattr_np(pthread_self(), &attr) == 0) {")
    hadd("        void *addr = NULL;")
    hadd("        size_t length = 0;")
    hadd("        if (pthread_attr_getstack(&attr, &addr, &length) == 0) {")
    hadd("            low = (uintptr_t)addr;")
    hadd("            size = (uintptr_t)length;")
    hadd("        }")
    hadd("        pthread_attr_destroy(&attr);")
    hadd("    }")
    hadd("#endif")
    hadd("    if (size == 0) {")
    hadd("        wasmext_stack_limit = (uintptr_t)__builtin_frame_address(0) - 128 * 1024;")
    hadd("        return;")
    hadd("    }")
    hadd("    margin = size / 4;")
    hadd("    if (margin < 32 * 1024) margin = 32 * 1024;")
    hadd("    if (margin > 256 * 1024) margin = 256 * 1024;")
    hadd("    wasmext_stack_limit = low + margin;")
    hadd("}")
    hadd("#endif")
    hadd("#else")
    hadd("#define WASMEXT_ENTER(CODE, FAIL) WASMEXT_THREAD_READY(); WASMEXT_ENTER_INNER(CODE, FAIL)")
    hadd("#define WASMEXT_LEAVE() WASMEXT_LEAVE_INNER()")
    hadd("#endif")
    hadd("")

    add(
        f"/* Generated by wasmext from the WebAssembly module of {last}: do not edit. The Python layer: it uses {last}_glue.h. */"
    )
    add("#define PY_SSIZE_T_CLEAN")
    if (
        wasi2 and uses_wasi
    ):  # Python.h includes windows.h, whose winsock.h clashes with the winsock2.h of the sockets of WASI 0.2
        add("#if defined(_WIN32) && !defined(WIN32_LEAN_AND_MEAN)")
        add("#define WIN32_LEAN_AND_MEAN")
        add("#endif")
    add("#include <Python.h>")
    add("#include <structmember.h>")
    add("#include <string.h>")
    add("#define WASMEXT_PY_THREADS 1")
    add(f'#include "{last}_glue.h"')
    add("")
    add(
        "/* Every thread that runs WebAssembly code needs the runtime set up for it: the alternate stack for the handler of the signals, which turns a stack overflow"
    )
    add(
        "   into a trap (without it the process is killed by SIGSEGV). wasm_rt_init() did it for the thread that imported the module; any other thread does it at its"
    )
    add(
        "   first call (WASMEXT_THREAD_READY in the entry of a call) and gives it back when it ends: Python lets go of the capsule kept in the dict of the thread"
    )
    add(
        "   state when that is cleared, which happens in the thread that is ending. The thread that imports the module is not registered: at the end of the process"
    )
    add(
        '   the runtime of each module would free the one alternate stack of the thread, and only the last one\'s is in place (the runtime says "modified unexpectedly"'
    )
    add(
        "   in a debug build and leaves it, so a thread that runs several modules leaves a stack of each but one, as it did). */"
    )
    add(f'#define WASMEXT_PY_THREAD_KEY "wasmext.{last}.thread"')
    add("static void wasmext_py_thread_end_(PyObject *capsule) {")
    add("    unsigned long *owner = (unsigned long *)PyCapsule_GetPointer(capsule, WASMEXT_PY_THREAD_KEY);")
    add("    if (owner == NULL) {")
    add("        PyErr_Clear();")
    add("        return;")
    add("    }")
    add(
        "    if (*owner == PyThread_get_thread_ident()) {  /* not when the interpreter clears the state of another thread as it finalizes: the stack is that thread's */"
    )
    add("        wasm_rt_free_thread();")
    add("        wasmext_py_ready_ = 0;")
    add("    }")
    add("    free(owner);")
    add("}")
    add("static void wasmext_py_thread_setup_(void) {")
    add("#ifdef WASMEXT_STACK_LIMIT")
    add("    wasmext_stack_limit_init_();  /* nothing is given back at the end of the thread: no alternate stack */")
    add("    wasmext_py_ready_ = 1;")
    add("    return;")
    add("#endif")
    add("    PyObject *dict = PyThreadState_GetDict();")
    add("    unsigned long *owner = (unsigned long *)malloc(sizeof *owner);")
    add("    PyObject *capsule;")
    add("    wasm_rt_init_thread();")
    add("    wasmext_py_ready_ = 1;")
    add("#ifdef WASMEXT_CHAIN")
    add("    (void)*(volatile int *)&wasmext_chain_active_;  /* see wasmext_chain_install_ */")
    add("#endif")
    add(
        "    if (dict == NULL || owner == NULL) {  /* nowhere to keep it: the stack of this thread is not given back (as it was not before) */"
    )
    add("        free(owner);")
    add("        return;")
    add("    }")
    add("    *owner = PyThread_get_thread_ident();")
    add("    capsule = PyCapsule_New(owner, WASMEXT_PY_THREAD_KEY, wasmext_py_thread_end_);")
    add("    if (capsule == NULL) {")
    add("        free(owner);")
    add("        PyErr_Clear();")
    add("        return;")
    add("    }")
    add("    if (PyDict_SetItemString(dict, WASMEXT_PY_THREAD_KEY, capsule) < 0) PyErr_Clear();")
    add("    Py_DECREF(capsule);")
    add("}")
    if wasi_modules:
        add('#include "wasi2_python.h"')  # the host of the core of WASI: after the glue, whose WASI headers it needs
    add("")
    if shares_tables:
        add("#ifndef WASMEXT_TRAP_HANDLER")
        add(
            f'#error "wasmext: this module shares tables with other instances: build it with -DWASMEXT_TRAP_HANDLER={trap_handler} -DWASM_RT_TRAP_HANDLER={trap_handler} (natify does)"'
        )
        add("#endif")
        add(
            "/* the function that the runtime of this module calls for a trap instead of `longjmp` (wasmext_glue.h): it goes to the innermost call into WebAssembly code */"
        )
        add(f"void {trap_handler}(wasm_rt_trap_t code) {{ wasmext_traps_->trap(code); }}")
        add("")
        add(
            "/* The stack of entries is shared by every module of the interpreter that shares tables: the first to be loaded publishes its own, the others take it. */"
        )
        add("static int attach_traps(void) {")
        add("    PyObject *state = PyInterpreterState_GetDict(PyInterpreterState_Get());")
        add("    if (state == NULL) return -1;")
        add("    PyObject *found = PyDict_GetItemString(state, WASMEXT_TRAPS);")
        add("    if (found != NULL) {")
        add("        const wasmext_traps *shared = (const wasmext_traps *)PyCapsule_GetPointer(found, WASMEXT_TRAPS);")
        add("        if (shared == NULL) return -1;")
        add("        if (wasmext_traps_use(shared)) {")
        add(
            '            PyErr_SetString(PyExc_ImportError, "wasmext: another module that shares tables was built with another runtime of wasm2c, or too many are loaded");'
        )
        add("            return -1;")
        add("        }")
        add("        return 0;")
        add("    }")
        add("    PyErr_Clear();")
        add("    PyObject *capsule = PyCapsule_New((void *)&wasmext_traps_own_, WASMEXT_TRAPS, NULL);")
        add("    if (capsule == NULL) return -1;")
        add(
            "    int bad = wasmext_traps_use(&wasmext_traps_own_) || PyDict_SetItemString(state, WASMEXT_TRAPS, capsule) < 0;"
        )
        add("    Py_DECREF(capsule);")
        add(
            '    if (bad && !PyErr_Occurred()) PyErr_SetString(PyExc_ImportError, "wasmext: the runtime of wasm2c cannot join the stack of traps");'
        )
        add("    return bad ? -1 : 0;")
        add("}")
        add("")
    add("static PyObject *TrapError;")
    add("static PyObject *LinkError;")
    if tags:
        add("static PyObject *UncaughtExceptionError;")
    if uses_wasi:
        add("static PyObject *WasiExitError, *WasiSignalError, *WasiTerminatedError;")
    if uses_wasi and not wasi2:
        add("static PyTypeObject *HostType;")
    if uses_wasi:
        add(
            "/* A call of WASI that the caller gave as None: nothing is given. A call that answers with an errno answers ENOSYS (52), the other is a trap. */"
        )
        add(
            "static PyObject *wasmext_nothing_errno(PyObject *name, PyObject *args) { (void)name; (void)args; return PyLong_FromLong(52); }"
        )
        add("static PyObject *wasmext_nothing_trap(PyObject *name, PyObject *args) {")
        add("    (void)args;")
        add('    PyErr_Format(TrapError, "%U was given as None: nothing to call", name);')
        add("    return NULL;")
        add("}")
        add('static PyMethodDef wasmext_nothing_errno_def = {"nothing", wasmext_nothing_errno, METH_VARARGS, NULL};')
        add('static PyMethodDef wasmext_nothing_trap_def = {"nothing", wasmext_nothing_trap, METH_VARARGS, NULL};')
    add("static PyTypeObject *InstanceType;")
    if memories:
        add("static PyTypeObject *MemoryType;")
    if shares_tables:
        add("static PyTypeObject *TableType, *FunctionType;")
    add("")
    uses_v128 = any("v128" in (*imp.func.params, *imp.func.results) for imp in imports) or any(
        "v128" in (*f.params, *f.results) for _, f in funcs
    )
    uses_v128 = uses_v128 or any(g.type == "v128" for g in global_imports) or any(g.type == "v128" for _, g in globals_)
    if uses_v128:
        # a v128 is 16 bytes, in the order of WebAssembly memory (little-endian), as bytes or any bytes-like object of 16 bytes
        add("#if defined(__BYTE_ORDER__) && defined(__ORDER_BIG_ENDIAN__) && __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__")
        add('#error "wasmext: v128 in a signature is not supported on big-endian hosts"')
        add("#endif")
        add("static int wasmext_is_v128(PyObject *o) {")
        add("    Py_buffer view;")
        add("    if (PyObject_GetBuffer(o, &view, PyBUF_SIMPLE) != 0) { PyErr_Clear(); return 0; }")
        add("    int ok = view.len == 16;")
        add("    PyBuffer_Release(&view);")
        add("    return ok;")
        add("}")
        add("static v128 wasmext_bytes_v128(PyObject *o) {")
        add("    v128 out;")
        add("    memset(&out, 0, sizeof out);")
        add("    Py_buffer view;")
        add("    if (PyObject_GetBuffer(o, &view, PyBUF_SIMPLE) != 0) return out;")
        add("    if (view.len != 16) {")
        add('        PyErr_Format(PyExc_ValueError, "a v128 is 16 bytes, got %zd", (Py_ssize_t)view.len);')
        add("    } else {")
        add("        memcpy(&out, view.buf, 16);")
        add("    }")
        add("    PyBuffer_Release(&view);")
        add("    return out;")
        add("}")
        add("static PyObject *wasmext_v128_bytes(v128 v) {")
        add("    return PyBytes_FromStringAndSize((const char *)&v, 16);")
        add("}")
        add("")
    # ---- the glue of the module (no Python): what each import module holds, the instance, the imports as the module calls them ----
    for i, host in enumerate(hosts):
        hadd(f"/* the functions and the values of the imports of module {_c_string(host)} */")
        # g: the value of a global the caller gave as a number; gp: where the runtime reads it (g, or the global of another instance)
        values = "".join(
            f" {_CTYPE[g.type]} g{g.slot}; {_CTYPE[g.type]} *gp{g.slot};"
            for g in global_imports
            if hosts[g.host] == host
        )
        n = max(slots.get(host, 0), 1)
        memory_fields = "".join(f" wasm_rt_memory_t *mp{m.slot};" for m in memory_imports if hosts[m.host] == host)
        memory_fields += "".join(
            f" wasm_rt_funcref_table_t *tp{tb.slot};" for tb in table_imports if hosts[tb.host] == host
        )
        # fn, user: the function to call for an import, `result f(void *user, parameters..., int *trapped)`, and its first argument
        hadd(f"struct w2c_{mangle(host, module=True)} {{ void *fn[{n}]; void *user[{n}];{values}{memory_fields} }};")
    hadd("")
    hadd(
        "/* The store of an instance (a `Store`, as Wasmtime has one): it owns the host (who answers the imports of WASI) and, in time, the runtime. An instance has one of its own (`own`, private) and uses it"
    )
    hadd(
        "   through `store`; a store made for several instances is the same structure (see docs/context_concept.md, which says 'context' for what is now the store). */"
    )
    hadd("typedef struct {")
    if uses_wasi:
        hadd(
            "    fusedwasi_p2_state wasi2;  /* the state of the host (fusedwasi, p2/): made by the glue, its Python side is `wasi2_py`. A module of WASI 0.1 has it too: `wasi` is over it */"
        )
        hadd("    void *wasi2_py;")
        hadd("    char p2_message[160];  /* why the host trapped, when it did not say with an exception */")
    if uses_wasi and not wasi2:
        hadd("    fusedwasi_p1_state *wasi;")
    else:
        hadd("    char unused_;  /* a module with no WASI has no host yet */")
    hadd("    int closed;  /* the store was closed: a call is refused, the host was let go */")
    hadd(
        "    unsigned active;  /* the calls in progress (any thread holds the GIL when it changes this, or the host serialises) */"
    )
    hadd(f"}} {last}_store;")
    hadd("")
    hadd("typedef struct {")
    hadd(f"    w2c_{prefix} inst;")
    hadd("    int instantiated;")
    hadd("    int initialized;  /* the `_initialize` of a reactor has run */")
    hadd(
        f"    {last}_store *store;  /* the store the instance lives in: its host; set by whoever makes the instance */"
    )
    for i, host in enumerate(hosts):
        hadd(f"    struct w2c_{mangle(host, module=True)} host{i};")
    hadd(
        f"    wasm_rt_funcref_t exp_ref[{max(len(funcs), 1)}];  /* the exported functions as a table holds them: see {last}_glue_funcref */"
    )
    hadd(f"}} {last}_instance;")
    hadd("")
    _emit_funcrefs(hadd, last, prefix, funcs)
    _emit_links(hadd, last, imports, global_imports, memory_imports, hosts, table_imports)
    add("typedef struct {")
    add("    PyObject_HEAD")
    add(f"    {last}_store st;  /* the host: who answers the imports of WASI */")
    add("    PyObject *weakreflist;")
    add("} StoreObject;")
    add("static PyTypeObject *StoreType;")
    add("")
    add("typedef struct {")
    add("    PyObject_HEAD")
    add(f"    {last}_instance core;")
    add("    StoreObject *store_obj;  /* the store this instance lives in (a reference) */")
    add("    PyObject *caller;  /* the Caller that the callables which ask for one are given (made on the first) */")
    add("    PyObject *weakreflist;")
    if tables:
        add(
            "    PyObject *writers;  /* the instances that imported an exported table and may have put functions of their own in it: they live as long as this one */"
        )
    if funcref_args:
        add(
            "    PyObject *refs;  /* the owners of the functions this instance was given as parameters: the module may keep one (in a table, a global), so they live as long as this one */"
        )
    if memories:
        add(
            f"    long mem_pins[{len(memories)}];  /* the live buffers of each exported memory that can move (see Memory_getbuffer) */"
        )
        add(
            f"    uint64_t mem_max_pages[{len(memories)}];  /* its own maximum, put back when the last buffer is gone */"
        )
    for i, host in enumerate(hosts):
        # what the Python layer holds for the imports of a module: the callables, the owners of the exports of other instances
        k = max(slots.get(host, 0), 1)
        gos = "".join(f" PyObject *go{g.slot};" for g in global_imports if hosts[g.host] == host)
        mos = "".join(f" PyObject *mo{m.slot};" for m in memory_imports if hosts[m.host] == host)
        mos += "".join(f" PyObject *to{tb.slot};" for tb in table_imports if hosts[tb.host] == host)
        add(f"    struct {{ PyObject *fn[{k}]; PyObject *lo[{k}];{gos}{mos} }} hold{i};")
    add("} InstanceObject;")
    add("")
    if memories:
        add("typedef struct {")
        add("    PyObject_HEAD")
        add("    InstanceObject *owner;")
        add(f"    wasm_rt_memory_t *(*get)(w2c_{prefix} *);")
        add("    int export_index;  /* its place in export_table: the reference to it is made from that */")
        add("    size_t which;  /* which of the exported memories */")
        add("} MemoryObject;")
        add("")
    if shares_tables:
        add("typedef struct {")
        add("    PyObject_HEAD")
        add("    wasm_rt_funcref_table_t own;  /* the table of a Table that no module owns */")
        add("    wasm_rt_funcref_table_t *table;  /* &own, or a table of the module of `owner` */")
        add("    InstanceObject *owner;  /* the instance whose table this is; NULL for a table of its own */")
        add("    int export_index;  /* a table of an instance: its place in export_table */")
        add(
            "    PyObject *writers;  /* a table of its own: the instances that imported it and may have put functions of their own in it: they live as long as it does */"
        )
        add("} TableObject;")
        add("")
    if tags:
        add(
            "/* an exception of WebAssembly that no `try` caught: UncaughtException, with .tag (its index in the module, or None for the tag of"
        )
        add(
            "   another module) and .values (a tuple); what the runtime keeps of it is read now, before any other code of WebAssembly runs */"
        )
        add("static void raise_uncaught(void) {")
        add(f"    wasmext_value v[{last.upper()}_TAG_MAX_VALUES];")
        add(f"    int tag = {last}_tag_of(wasm_rt_exception_tag());")
        add(f"    int n = tag >= 0 ? {last}_tag_values(tag, wasm_rt_exception(), wasm_rt_exception_size(), v) : -1;")
        add("    PyObject *values = PyTuple_New(n > 0 ? n : 0);")
        add("    for (int i = 0; values != NULL && i < n; i++) {")
        add("        PyObject *item = NULL;")
        add("        switch (v[i].type) {")
        add("        case 0x7F: item = PyLong_FromLong((long)(int32_t)v[i].as.i); break;")
        add("        case 0x7E: item = PyLong_FromLongLong((long long)(int64_t)v[i].as.j); break;")
        add("        case 0x7D: item = PyFloat_FromDouble((double)v[i].as.f); break;")
        add("        case 0x7C: item = PyFloat_FromDouble(v[i].as.d); break;")
        add("        default: item = PyBytes_FromStringAndSize((const char *)v[i].as.o, 16); break;")
        add("        }")
        add("        if (item == NULL) { Py_CLEAR(values); break; }")
        add("        if (PyTuple_SetItem(values, i, item) < 0) { Py_CLEAR(values); break; }")
        add("    }")
        add("    PyObject *index = NULL;")
        add(
            "    if (values != NULL) { if (tag >= 0) index = PyLong_FromLong(tag); else { Py_INCREF(Py_None); index = Py_None; } }"
        )
        add(
            '    PyObject *exc = index != NULL ? PyObject_CallFunction(UncaughtExceptionError, "s", wasm_rt_strerror(WASM_RT_TRAP_UNCAUGHT_EXCEPTION)) : NULL;'
        )
        add(
            '    if (exc != NULL && (PyObject_SetAttrString(exc, "tag", index) < 0 || PyObject_SetAttrString(exc, "values", values) < 0)) Py_CLEAR(exc);'
        )
        add("    if (exc != NULL) PyErr_SetObject(UncaughtExceptionError, exc);")
        add("    Py_XDECREF(exc);")
        add("    Py_XDECREF(index);")
        add("    Py_XDECREF(values);")
        add("}")
        add("")
    add(
        "/* what a code of a trap becomes in Python (the code of a host function that failed means its exception is set already) */"
    )
    add("static void raise_trap_code(InstanceObject *self, int code) {")
    add("    (void)self;")
    add("    if (code == (int)WASMEXT_TRAP_HOST) {")
    add("        if (PyErr_Occurred()) return;")
    if uses_wasi:
        add(
            "        if (self->core.store->wasi2.exited) { wasmext_wasi2_raise_exit((wasmext_wasi2_py *)self->core.store->wasi2_py, self->core.store->wasi2.exit_code); return; }"
        )
    if uses_wasi and not wasi2:
        add(
            "        if (self->core.store->wasi != NULL && self->core.store->wasi->finished == FUSEDWASI_P1_END_SIGNAL) { wasmext_wasi_raise_signal(self->core.store->wasi); return; }"
        )
    if uses_wasi and wasi2:
        add(
            "        if (self->core.store->p2_message[0]) { PyErr_SetString(TrapError, self->core.store->p2_message); self->core.store->p2_message[0] = 0; return; }"
        )
    add(
        "        /* a function of another instance that this one calls through a link failed in its own host function: if that instance keeps the exception"
    )
    add("           (the wrapper for ctypes does, in `_pending`), it is the one to raise */")
    for i, host in enumerate(hosts):
        add(f"        for (int k = 0; k < {max(slots.get(host, 0), 1)}; k++) {{")
        add(f"            PyObject *owner = self->hold{i}.lo[k];")
        add('            PyObject *kept = owner != NULL ? PyObject_GetAttrString(owner, "_pending") : NULL;')
        add("            if (kept != NULL && kept != Py_None && PyExceptionInstance_Check(kept)) {")
        add(
            "                /* the attribute is cleared first and the exception is set last: a call of Python with an exception set may run a finalizer or the collector, and lose it */"
        )
        add('                if (PyObject_SetAttrString(owner, "_pending", Py_None) < 0) PyErr_Clear();')
        add("                PyErr_SetObject((PyObject *)Py_TYPE(kept), kept);")
        add("                Py_DECREF(kept);")
        add("                return;")
        add("            }")
        add("            Py_XDECREF(kept);")
        add("            PyErr_Clear();")
        add("        }")
    add('        PyErr_SetString(TrapError, "a host function of the WebAssembly module failed");')
    add("        return;")
    add("    }")
    if tags:
        add("    if (code == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION) { raise_uncaught(); return; }")
    add('    if (code == (int)WASMEXT_TRAP_CLOSED) PyErr_SetString(PyExc_ValueError, "the store is closed");')
    add("    else if (code == (int)WASMEXT_TRAP_NO_MEMORY) PyErr_NoMemory();")
    add("    else PyErr_SetString(TrapError, wasm_rt_strerror((wasm_rt_trap_t)code));")
    add("}")
    add(
        "/* a call that trapped always leaves an exception: a function that returns NULL without one is a SystemError, which says nothing of the trap */"
    )
    add("static void raise_trap(InstanceObject *self, int code) {")
    add("    raise_trap_code(self, code);")
    add('    if (!PyErr_Occurred()) PyErr_SetString(TrapError, "the WebAssembly call trapped and left no error");')
    add("}")
    add("")

    # the globals the module imports: the runtime asks for a pointer to the value
    for g in global_imports:
        mod_struct = f"struct w2c_{mangle(g.module, module=True)}"
        hadd(f"{_CTYPE[g.type]} *{g.symbol}({mod_struct} *h) {{ return h->gp{g.slot}; }}")
    if global_imports:
        hadd("")
    for m in memory_imports:
        mod_struct = f"struct w2c_{mangle(m.module, module=True)}"
        hadd(f"wasm_rt_memory_t *{m.symbol}({mod_struct} *h) {{ return h->mp{m.slot}; }}")
    if memory_imports:
        hadd("")
    for tb in table_imports:
        mod_struct = f"struct w2c_{mangle(tb.module, module=True)}"
        hadd(f"wasm_rt_funcref_table_t *{tb.symbol}({mod_struct} *h) {{ return h->tp{tb.slot}; }}")
    if table_imports:
        hadd("")

    # the functions the module imports, over the functions of the host: a trap of the host (nonzero; it keeps the error) unwinds the frames of the module
    for imp in imports:
        func = imp.func
        params = "".join(f", {_CTYPE[t]} a{i}" for i, t in enumerate(func.params))
        several = len(func.results) > 1
        codes = "".join(_MULTI_CODE[t] for t in func.results)
        ret = f"struct wasm_multi_{codes}" if several else _CTYPE[func.results[0]] if func.results else "void"
        mod_struct = f"struct w2c_{mangle(imp.module, module=True)}"
        arg_types = "".join(f", {_CTYPE[t]}" for t in func.params)
        arg_names = "".join(f", a{i}" for i in range(len(func.params)))
        hadd(f"{ret} {imp.symbol}({mod_struct} *h{params}) {{")
        hadd("    int trapped = 0;")
        host_call = (
            f"(({ret} (*)(void *{arg_types}, int *))h->fn[{imp.slot}])(h->user[{imp.slot}]{arg_names}, &trapped)"
        )
        if func.results:
            hadd(f"    {ret} r_ = {host_call};")
            hadd("    if (trapped) wasm_rt_trap(WASMEXT_TRAP_OF(trapped));")
            hadd("    return r_;")
        else:
            hadd(f"    {host_call};")
            hadd("    if (trapped) wasm_rt_trap(WASMEXT_TRAP_OF(trapped));")
        hadd("}")
        hadd("")

    # the same functions in Python: a callable of the caller, as a function of the host (its `user` is the callable)
    for k, imp in enumerate(imports):
        func = imp.func
        params = "".join(f", {_CTYPE[t]} a{i}" for i, t in enumerate(func.params))
        several = len(func.results) > 1
        codes = "".join(_MULTI_CODE[t] for t in func.results)
        ret = f"struct wasm_multi_{codes}" if several else _CTYPE[func.results[0]] if func.results else "void"
        fmt = "".join(_BUILD[t][0] for t in func.params)
        casts = "".join(f", {_BUILD[t][1].format(f'a{i}')}" for i, t in enumerate(func.params))
        give = "return zero_;" if func.results else "return;"
        add(f"static {ret} py_import{k}(void *user{params}, int *trapped) {{")
        if func.results:
            add(f"    {ret} zero_;")
            add("    memset(&zero_, 0, sizeof zero_);")
        add(f'    PyObject *r = PyObject_CallFunction((PyObject *)user, "{fmt}"{casts});')
        add(f"    if (r == NULL) {{ *trapped = (int)WASMEXT_TRAP_HOST; {give} }}")
        if several:
            n = len(func.results)
            what = _c_string(f"{imp.module}.{imp.field}() must return a tuple of {n} values")
            add(f"    {ret} v = {{0}};")
            add(f"    if (!PyTuple_Check(r) || PyTuple_Size(r) != {n}) {{")
            add("        Py_DECREF(r);")
            add(f"        PyErr_SetString(PyExc_TypeError, {what});")
            add("        *trapped = (int)WASMEXT_TRAP_HOST;")
            add(f"        {give}")
            add("    }")
            for j, rt in enumerate(func.results):
                add(f"    v.{_MULTI_CODE[rt]}{j} = {_TO_WASM[rt].format(f'PyTuple_GetItem(r, {j})')};")
            add("    Py_DECREF(r);")
            add(f"    if (PyErr_Occurred()) {{ *trapped = (int)WASMEXT_TRAP_HOST; {give} }}")
            add("    return v;")
        elif func.results:
            rt = func.results[0]
            add(f"    {ret} v = {_TO_WASM[rt].format('r')};")
            add("    Py_DECREF(r);")
            add(f"    if (PyErr_Occurred()) {{ *trapped = (int)WASMEXT_TRAP_HOST; {give} }}")
            add("    return v;")
        else:
            add("    Py_DECREF(r);")
        add("}")
        add("")

    # Instance: creation, destruction, the GC protocol
    if has_imports:
        add("static PyObject *lookup_import(PyObject *imports, const char *module, const char *field, int callable) {")
        add("    PyObject *key = PyUnicode_FromString(module), *m, *f;")
        add("    if (key == NULL) return NULL;")
        add("    m = PyObject_GetItem(imports, key);")
        add("    Py_DECREF(key);")
        add("    if (m == NULL) {")
        add("        PyErr_Clear();")
        add("        PyErr_Format(LinkError, \"missing import module '%s'\", module);")
        add("        return NULL;")
        add("    }")
        add(
            "    {   /* a shelf that is an instance of a wasmext extension (anything with __exports__) gives its exports */"
        )
        add('        PyObject *exports = PyObject_GetAttrString(m, "__exports__");')
        add("        if (exports != NULL) { Py_DECREF(m); m = exports; } else { PyErr_Clear(); }")
        add("    }")
        add("    key = PyUnicode_FromString(field);")
        add("    if (key == NULL) { Py_DECREF(m); return NULL; }")
        add("    f = PyObject_GetItem(m, key);")
        add("    Py_DECREF(key);")
        add("    Py_DECREF(m);")
        add("    if (f == NULL) {")
        add("        PyErr_Clear();")
        add("        PyErr_Format(LinkError, \"missing import '%s.%s'\", module, field);")
        add("        return NULL;")
        add("    }")
        add("    if (callable && !PyCallable_Check(f)) {")
        add("        Py_DECREF(f);")
        add("        PyErr_Format(LinkError, \"import '%s.%s' is not callable\", module, field);")
        add("        return NULL;")
        add("    }")
        add("    return f;")
        add("}")
        add("")
    add(
        "/* The store: the host (who answers the imports of WASI) with its state, shared by the instances made in it. The instance that the host serves is the one in call: the trampolines say so before each call. */"
    )
    add("static StoreObject *store_make(PyTypeObject *type, PyObject *wasi) {")
    add("    StoreObject *self = (StoreObject *)PyType_GenericAlloc(type, 0);")
    add("    if (self == NULL) return NULL;")
    if uses_wasi:
        add(f"    {last}_p2_store_init(&self->st);")
        add(
            f"    self->st.wasi2_py = wasmext_wasi2_new(&self->st.wasi2, NULL, wasi, WasiExitError, WasiSignalError, {_c_string(last)});"
        )
        add("    if (self->st.wasi2_py == NULL) { Py_DECREF((PyObject *)self); return NULL; }")
        if not wasi2:
            add("    self->st.wasi = wasmext_wasi_over((wasmext_wasi2_py *)self->st.wasi2_py, &self->st.wasi2);")
            add("    if (self->st.wasi == NULL) { Py_DECREF((PyObject *)self); return NULL; }")
    else:
        add("    (void)wasi;")
    add("    return self;")
    add("}")
    add("")
    add("static PyObject *Store_new(PyTypeObject *type, PyObject *args, PyObject *kwds) {")
    if uses_wasi:
        add('    static char *kwlist[] = {"wasi", NULL};')
        add("    PyObject *wasi = Py_None;")
        add('    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|O:Store", kwlist, &wasi)) return NULL;')
    else:
        add("    static char *kwlist[] = {NULL};")
        add('    if (!PyArg_ParseTupleAndKeywords(args, kwds, ":Store", kwlist)) return NULL;')
        add("    PyObject *wasi = Py_None;")
    add("    return (PyObject *)store_make(type, wasi);")
    add("}")
    add("")
    add("static int Store_traverse(StoreObject *self, visitproc visit, void *arg) {")
    add("    Py_VISIT(Py_TYPE((PyObject *)self));")
    if uses_wasi:
        add("    wasmext_wasi2_traverse((wasmext_wasi2_py *)self->st.wasi2_py, visit, arg);")
    add("    return 0;")
    add("}")
    add("")
    add("static int Store_clear(StoreObject *self) {")
    if uses_wasi:
        add("    wasmext_wasi2_clear((wasmext_wasi2_py *)self->st.wasi2_py);")
    else:
        add("    (void)self;")
    add("    return 0;")
    add("}")
    add("")
    add(
        "/* the host is let go: the files the program opened are closed, the Python objects of the configuration are dropped; once */"
    )
    add("static void store_release(StoreObject *self) {")
    if uses_wasi and not wasi2:
        add("    fusedwasi_p1_destroy(self->st.wasi);")
        add("    self->st.wasi = NULL;")
    if uses_wasi:
        add("    fusedwasi_p2_free(&self->st.wasi2);")
        add("    wasmext_wasi2_free((wasmext_wasi2_py *)self->st.wasi2_py);")
        add("    self->st.wasi2_py = NULL;")
    else:
        add("    (void)self;")
    add("}")
    add("")
    add("static PyObject *Store_close(StoreObject *self, PyObject *Py_UNUSED(ignored)) {")
    add("    if (self->st.closed) Py_RETURN_NONE;  /* closing twice is not an error, as for a file */")
    add("    if (self->st.active) {")
    add(
        '        PyErr_SetString(PyExc_RuntimeError, "the store is in use: a call into one of its instances is running");'
    )
    add("        return NULL;")
    add("    }")
    add("    self->st.closed = 1;")
    add("    store_release(self);")
    add("    Py_RETURN_NONE;")
    add("}")
    add("")
    add("static PyObject *Store_enter(StoreObject *self, PyObject *Py_UNUSED(ignored)) {")
    add('    if (self->st.closed) { PyErr_SetString(PyExc_ValueError, "the store is closed"); return NULL; }')
    add("    Py_INCREF((PyObject *)self);")
    add("    return (PyObject *)self;")
    add("}")
    add("")
    add("static PyObject *Store_exit(StoreObject *self, PyObject *Py_UNUSED(args)) {")
    add("    return Store_close(self, NULL);  /* an exception that leaves the block goes on */")
    add("}")
    add("")
    add(
        "static PyObject *Store_closed(StoreObject *self, void *Py_UNUSED(closure)) { return PyBool_FromLong(self->st.closed); }"
    )
    add("")
    add(
        "/* the identity of the runtime that the store lives in: no operations (the shared runtime is for the later steps) */"
    )
    add("static PyObject *Store_runtime(StoreObject *self, void *Py_UNUSED(closure)) {")
    add("    (void)self;")
    add('    PyObject *types = PyImport_ImportModule("types");')
    add("    if (types == NULL) return NULL;")
    add('    PyObject *ns = PyObject_GetAttrString(types, "SimpleNamespace");')
    add("    Py_DECREF(types);")
    add("    if (ns == NULL) return NULL;")
    add(
        '    PyObject *kw = Py_BuildValue("{s:s,s:I,s:I}", "name", "wasm2c", "abi", (unsigned)WASMEXT_ABI, "fingerprint", (unsigned)WASMEXT_RUNTIME);'
    )
    add("    PyObject *none = PyTuple_New(0);")
    add("    PyObject *r = kw != NULL && none != NULL ? PyObject_Call(ns, none, kw) : NULL;")
    add("    Py_XDECREF(kw);")
    add("    Py_XDECREF(none);")
    add("    Py_DECREF(ns);")
    add("    return r;")
    add("}")
    add("")
    add("static void Store_dealloc(StoreObject *self) {")
    add("    PyTypeObject *tp = Py_TYPE((PyObject *)self);")
    add("    PyObject_GC_UnTrack(self);")
    add("    if (self->weakreflist != NULL) PyObject_ClearWeakRefs((PyObject *)self);")
    add("    Store_clear(self);")
    add("    if (!self->st.closed) store_release(self);")
    add("    ((freefunc)PyType_GetSlot(tp, Py_tp_free))((PyObject *)self);")
    add("    Py_DECREF(tp);")
    add("}")
    add("")
    add("static int Instance_traverse(InstanceObject *self, visitproc visit, void *arg) {")
    add("    Py_VISIT(Py_TYPE((PyObject *)self));")
    add("    Py_VISIT((PyObject *)self->store_obj);")
    add("    Py_VISIT(self->caller);")
    for i, host in enumerate(hosts):
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_VISIT(self->hold{i}.fn[k]);")
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_VISIT(self->hold{i}.lo[k]);")
    for g in global_imports:
        add(f"    Py_VISIT(self->hold{g.host}.go{g.slot});")
    for m in memory_imports:
        add(f"    Py_VISIT(self->hold{m.host}.mo{m.slot});")
    for tb in table_imports:
        add(f"    Py_VISIT(self->hold{tb.host}.to{tb.slot});")
    if tables:
        add("    Py_VISIT(self->writers);")
    if funcref_args:
        add("    Py_VISIT(self->refs);")
    add("    return 0;")
    add("}")
    add("")
    add("static int Instance_clear(InstanceObject *self) {")
    add("    Py_CLEAR(self->caller);")
    for i, host in enumerate(hosts):
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_CLEAR(self->hold{i}.fn[k]);")
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_CLEAR(self->hold{i}.lo[k]);")
    for g in global_imports:
        add(f"    Py_CLEAR(self->hold{g.host}.go{g.slot});")
    for m in memory_imports:
        add(f"    Py_CLEAR(self->hold{m.host}.mo{m.slot});")
    for tb in table_imports:
        add(f"    Py_CLEAR(self->hold{tb.host}.to{tb.slot});")
    if tables:
        add("    Py_CLEAR(self->writers);")
    if funcref_args:
        add("    Py_CLEAR(self->refs);")
    add("    return 0;")
    add("}")
    add("")
    add("static void Instance_dealloc(InstanceObject *self) {")
    add("    PyTypeObject *tp = Py_TYPE((PyObject *)self);")
    add("    PyObject_GC_UnTrack(self);")
    add("    if (self->weakreflist != NULL) PyObject_ClearWeakRefs((PyObject *)self);")
    add(f"    {last}_glue_free(&self->core);")
    add("    Instance_clear(self);")
    add("    Py_XDECREF((PyObject *)self->store_obj);  /* the last one to leave frees the host */")
    add("    ((freefunc)PyType_GetSlot(tp, Py_tp_free))((PyObject *)self);")
    add("    Py_DECREF(tp);")
    add("}")
    add("")
    if has_imports or shares_tables:
        add(
            "/* The reference to an export of another instance that `v` stands for, as a capsule (a new reference), or NULL with no error: `v` is one, or has one as its"
        )
        add(
            "   `__wasmext_ref__` (itself an object that has it, perhaps: the wrapper for ctypes gives objects, because a capsule of its would have a destructor that cannot run"
        )
        add("   while an exception is raised). */")
        add("static PyObject *as_export_ref(PyObject *v) {")
        add("    PyObject *cur = v;")
        add("    Py_INCREF(cur);")
        add("    for (int depth = 0; depth < 3; depth++) {")
        add("        if (PyCapsule_IsValid(cur, WASMEXT_EXPORT)) return cur;")
        add('        PyObject *next = PyObject_GetAttrString(cur, "__wasmext_ref__");')
        add("        Py_DECREF(cur);")
        add("        if (next == NULL) { PyErr_Clear(); return NULL; }")
        add("        cur = next;")
        add("    }")
        add("    Py_DECREF(cur);")
        add("    return NULL;")
        add("}")
        add("")
        add(_FUNCTION_HOLDER)
        if uses_funcref:
            add(_funcref_values_c(funcref_args))
    if table_imports:
        add(
            "/* the owner of a table keeps alive the instances that may have put functions in it: 1 if it does (it is the instance of any extension) */"
        )
        add("static int keep_alive(PyObject *owner, PyObject *writer) {")
        add('    PyObject *r = PyObject_CallMethod(owner, "__wasmext_keep__", "O", writer);')
        add("    if (r == NULL) return 0;")
        add("    Py_DECREF(r);")
        add("    return 1;")
        add("}")
        add("")
    if has_imports:
        add(
            "/* ---- Caller: what a callable that asks for it (`fn.__wasm_caller__ = True`) is given first, as Wasmtime gives a Caller: the instance that called, its store and its memory ---- */"
        )
        add("typedef struct { PyObject_HEAD InstanceObject *instance; } CallerObject;")
        add("static PyTypeObject *CallerType;")
        add("static int Caller_traverse(CallerObject *self, visitproc visit, void *arg) {")
        add("    Py_VISIT(Py_TYPE((PyObject *)self));")
        add("    Py_VISIT((PyObject *)self->instance);")
        add("    return 0;")
        add("}")
        add("static int Caller_clear(CallerObject *self) {")
        add("    Py_CLEAR(self->instance);")
        add("    return 0;")
        add("}")
        add("static void Caller_dealloc(CallerObject *self) {")
        add("    PyTypeObject *tp = Py_TYPE((PyObject *)self);")
        add("    PyObject_GC_UnTrack(self);")
        add("    Caller_clear(self);")
        add("    ((freefunc)PyType_GetSlot(tp, Py_tp_free))((PyObject *)self);")
        add("    Py_DECREF(tp);")
        add("}")
        add("static PyObject *Caller_get_instance(CallerObject *self, void *Py_UNUSED(closure)) {")
        add("    Py_INCREF((PyObject *)self->instance);")
        add("    return (PyObject *)self->instance;")
        add("}")
        add("static PyObject *Caller_get_store(CallerObject *self, void *Py_UNUSED(closure)) {")
        add("    Py_INCREF((PyObject *)self->instance->store_obj);")
        add("    return (PyObject *)self->instance->store_obj;")
        add("}")
        add(
            '/* the memory of the instance that called, or None when the module has none (as `caller.get("memory")` of Wasmtime) */'
        )
        add("static PyObject *Caller_get_memory(CallerObject *self, void *Py_UNUSED(closure)) {")
        add('    PyObject *m = PyObject_GetAttrString((PyObject *)self->instance, "memory");')
        add("    if (m == NULL && PyErr_ExceptionMatches(PyExc_AttributeError)) {")
        add("        PyErr_Clear();")
        add("        Py_RETURN_NONE;")
        add("    }")
        add("    return m;")
        add("}")
        add("static PyGetSetDef Caller_getset[] = {")
        add('    {"instance", (getter)Caller_get_instance, NULL, "the instance that called", NULL},')
        add('    {"store", (getter)Caller_get_store, NULL, "the store of that instance", NULL},')
        add(
            '    {"memory", (getter)Caller_get_memory, NULL, "the memory of that instance (a memoryview), or None", NULL},'
        )
        add("    {NULL, NULL, NULL, NULL, NULL}")
        add("};")
        add(
            "/* A callable that has `__wasm_caller__` true is called with the Caller first. Done once, when the instance is made: the callable becomes partial(fn, caller), and the call is the same as for any callable. Steals `v`. */"
        )
        add("static PyObject *with_caller(InstanceObject *self, PyObject *v) {")
        add('    PyObject *mark = PyObject_GetAttrString(v, "__wasm_caller__");')
        add("    if (mark == NULL) { PyErr_Clear(); return v; }")
        add("    int yes = PyObject_IsTrue(mark);")
        add("    Py_DECREF(mark);")
        add("    if (yes <= 0) {")
        add("        if (yes < 0) { Py_DECREF(v); return NULL; }")
        add("        return v;")
        add("    }")
        add("    if (self->caller == NULL) {")
        add("        CallerObject *c = (CallerObject *)PyType_GenericAlloc(CallerType, 0);")
        add("        if (c == NULL) { Py_DECREF(v); return NULL; }")
        add("        Py_INCREF((PyObject *)self);")
        add("        c->instance = self;")
        add("        self->caller = (PyObject *)c;")
        add("    }")
        add('    PyObject *functools = PyImport_ImportModule("functools");')
        add('    PyObject *partial = functools != NULL ? PyObject_GetAttrString(functools, "partial") : NULL;')
        add("    Py_XDECREF(functools);")
        add("    PyObject *r = partial != NULL ? PyObject_CallFunctionObjArgs(partial, v, self->caller, NULL) : NULL;")
        add("    Py_XDECREF(partial);")
        add("    Py_DECREF(v);")
        add("    return r;")
        add("}")
        add("")
    add("static PyObject *Instance_new(PyTypeObject *type, PyObject *args, PyObject *kwds) {")
    # `Instance(store, imports=None)`: the store is required (there is no implicit store); `wasi=` is the configuration of the Store
    if has_imports:
        add('    static char *kwlist[] = {"store", "imports", NULL};')
        add("    PyObject *store, *imports = Py_None;")
        add('    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|O:Instance", kwlist, &store, &imports)) return NULL;')
    else:
        add('    static char *kwlist[] = {"store", NULL};')
        add("    PyObject *store;")
        add('    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O:Instance", kwlist, &store)) return NULL;')
    add("    if (!PyObject_TypeCheck(store, StoreType)) {")
    add(
        f"        PyErr_SetString(PyExc_TypeError, \"Instance() argument 'store' must be a Store made by this module ({_c_string(name)[1:-1]}.Store); a Store of another module is a different host\");"
    )
    add("        return NULL;")
    add("    }")
    add("    StoreObject *store_obj = (StoreObject *)store;")
    add('    if (store_obj->st.closed) { PyErr_SetString(PyExc_ValueError, "the store is closed"); return NULL; }')
    add("    Py_INCREF((PyObject *)store_obj);")
    add("    InstanceObject *self = (InstanceObject *)PyType_GenericAlloc(type, 0);")
    add("    if (self == NULL) {")
    add("        Py_DECREF((PyObject *)store_obj);")
    add("        return NULL;")
    add("    }")
    add("    self->store_obj = store_obj;")
    add("    self->core.store = &store_obj->st;")
    if tables:
        add("    self->writers = PyList_New(0);")
        add("    if (self->writers == NULL) { Py_DECREF(self); return NULL; }")
    if funcref_args:
        add("    self->refs = PyList_New(0);")
        add("    if (self->refs == NULL) { Py_DECREF(self); return NULL; }")
    if uses_wasi and not wasi2:
        add(
            f"    {{ wasm_rt_memory_t *m_ = w2c_{prefix}_{mangle('memory')}(&self->core.inst); fusedwasi_p1_bind(self->core.store->wasi, &m_->data, &m_->size); }}"
        )
    if has_imports:
        if needs_imports:
            add("    if (imports == Py_None) {")
            add(
                '        PyErr_SetString(LinkError, "the module has imports: pass imports={module: {name: callable or value}}");'
            )
            add("        Py_DECREF(self);")
            add("        return NULL;")
            add("    }")
        for k, imp in enumerate(imports):
            where = f"{imp.module}.{imp.field}"
            host = f"self->core.host{imp.host}"
            hold = f"self->hold{imp.host}"
            signature = _signature_code(imp.func)
            add("    {")
            if imp.module in wasi_headers:
                # what the caller gives wins; otherwise wasmext gives the call (a function of the WASI headers), called directly
                add("        PyObject *v = NULL;")
                add("        if (imports != Py_None) {")
                add(f"            v = lookup_import(imports, {_c_string(imp.module)}, {_c_string(imp.field)}, 0);")
                add(
                    "            if (v == NULL && !PyErr_ExceptionMatches(LinkError)) { Py_DECREF(self); return NULL; }"
                )
                add("            if (v == NULL) PyErr_Clear();")
                add("        }")
                nothing = (
                    "errno" if not wasi2 and [str(t) for t in imp.func.results] == ["i32"] else "trap"
                )  # 0.2 has no errno to answer with
                add(
                    "        if (v == Py_None) {  /* given as None: nothing is given, which is not the call of wasmext */"
                )
                add("            Py_DECREF(v);")
                add(f"            PyObject *label = PyUnicode_FromString({_c_string(where)});")
                add(f"            v = label != NULL ? PyCFunction_New(&wasmext_nothing_{nothing}_def, label) : NULL;")
                add("            Py_XDECREF(label);")
                add("            if (v == NULL) { Py_DECREF(self); return NULL; }")
                add("        }")
                add("        if (v == NULL) {")
                if wasi2:
                    add(f"            {host}.fn[{imp.slot}] = (void *){last}_p2_import{k};")
                    add(f"            {host}.user[{imp.slot}] = &self->core;")
                else:
                    add(f"            {host}.fn[{imp.slot}] = (void *){last}_p1_import{k};")
                    add(f"            {host}.user[{imp.slot}] = &self->core;")
                add("        } else {")
            else:
                add(
                    f"        PyObject *v = lookup_import(imports, {_c_string(imp.module)}, {_c_string(imp.field)}, 0);"
                )
                add("        if (v == NULL) { Py_DECREF(self); return NULL; }")
            add("        PyObject *ref = as_export_ref(v);  /* the reference to an export of another instance */")
            add(
                "        if (ref == NULL) {  /* a method of an instance of a wasmext extension stands for its export */"
            )
            add('            PyObject *owner = PyObject_GetAttrString(v, "__self__");')
            add('            PyObject *name = owner != NULL ? PyObject_GetAttrString(v, "__name__") : NULL;')
            add('            PyObject *exports = name != NULL ? PyObject_GetAttrString(owner, "__exports__") : NULL;')
            add("            if (exports != NULL && PyDict_Check(exports)) {")
            add("                ref = PyDict_GetItemWithError(exports, name);")
            add("                Py_XINCREF(ref);")
            add("            }")
            add("            Py_XDECREF(exports);")
            add("            Py_XDECREF(name);")
            add("            Py_XDECREF(owner);")
            add("            PyErr_Clear();")
            add("        }")
            add("        if (ref != NULL && PyCapsule_IsValid(ref, WASMEXT_EXPORT)) {")
            add("            wasmext_export *e = (wasmext_export *)PyCapsule_GetPointer(ref, WASMEXT_EXPORT);")
            add("            char message[512];")
            add(f"            if ({last}_link_func{k}(&self->core, e, message, sizeof message)) {{")
            add("                PyErr_SetString(LinkError, message);")
            add("            } else {")
            add("                Py_INCREF((PyObject *)e->owner);")
            add(f"                {hold}.lo[{imp.slot}] = (PyObject *)e->owner;")
            add("            }")
            add("            Py_DECREF(ref);")
            add("            Py_DECREF(v);")
            add("            if (PyErr_Occurred()) { Py_DECREF(self); return NULL; }")
            add("        } else if (PyCallable_Check(v)) {")
            add("            Py_XDECREF(ref);")
            add("            v = with_caller(self, v);")
            add("            if (v == NULL) { Py_DECREF(self); return NULL; }")
            add(f"            {host}.fn[{imp.slot}] = (void *)py_import{k};")
            add(f"            {host}.user[{imp.slot}] = v;")
            add(f"            {hold}.fn[{imp.slot}] = v;")
            add("        } else {")
            add("            Py_XDECREF(ref);")
            add("            Py_DECREF(v);")
            not_callable = f"import '{where}' is not callable"
            add(f"            PyErr_SetString(LinkError, {_c_string(not_callable)});")
            add("            Py_DECREF(self);")
            add("            return NULL;")
            add("        }")
            if imp.module in wasi_headers:
                add("        }")
            add("    }")
        for j, g in enumerate(global_imports):
            if g.type == "v128":
                number, what = "wasmext_is_v128(v)", "16 bytes"
            else:
                number = "PyLong_Check(v)" if g.type in ("i32", "i64") else "(PyLong_Check(v) || PyFloat_Check(v))"
                what = "an int" if g.type in ("i32", "i64") else "a number"
            where = f"{g.module}.{g.field}"
            hold = f"self->hold{g.host}"
            add("    {")
            add(f"        PyObject *v = lookup_import(imports, {_c_string(g.module)}, {_c_string(g.field)}, 0);")
            add("        if (v == NULL) { Py_DECREF(self); return NULL; }")
            add("        PyObject *ref = as_export_ref(v);  /* an export of another instance */")
            add("        if (ref != NULL) {")
            add("            wasmext_export *e = (wasmext_export *)PyCapsule_GetPointer(ref, WASMEXT_EXPORT);")
            add("            char message[512];")
            add(f"            if ({last}_link_global{j}(&self->core, e, message, sizeof message)) {{")
            add("                PyErr_SetString(LinkError, message);")
            add("            } else {")
            add("                Py_INCREF((PyObject *)e->owner);")
            add(f"                {hold}.go{g.slot} = (PyObject *)e->owner;")
            add("            }")
            add("            Py_DECREF(ref);")
            add("            Py_DECREF(v);")
            add("            if (PyErr_Occurred()) { Py_DECREF(self); return NULL; }")
            if g.mutable:
                add("        } else {")
                add("            Py_DECREF(v);")
                add(
                    f"            PyErr_SetString(LinkError, {_c_string(f'import {where} is a mutable global: pass an export of another instance: instance[{chr(39)}name{chr(39)}] (or the instance for the whole shelf)')});"
                )
                add("            Py_DECREF(self);")
                add("            return NULL;")
                add("        }")
            else:
                add(f"        }} else if (!{number}) {{")
                add("            Py_DECREF(v);")
                add(
                    f"            PyErr_SetString(LinkError, {_c_string(f'import {where} is a global of type {g.type}: pass {what} or an export of another instance')});"
                )
                add("            Py_DECREF(self);")
                add("            return NULL;")
                add("        } else {")
                add(f"            {last}_set_global{j}(&self->core, {_TO_WASM[g.type].format('v')});")
                add("            Py_DECREF(v);")
                add("        }")
            add("    }")
    for j, m in enumerate(memory_imports):
        where = f"{m.module}.{m.field}"
        hold = f"self->hold{m.host}"
        add("    {")
        add(f"        PyObject *v = lookup_import(imports, {_c_string(m.module)}, {_c_string(m.field)}, 0);")
        add("        if (v == NULL) { Py_DECREF(self); return NULL; }")
        add("        PyObject *ref = as_export_ref(v);  /* the reference to an export of another instance */")
        add(
            "        if (ref == NULL) {  /* the memoryview of a memory of an instance: the object behind it gives the reference */"
        )
        add('            PyObject *obj = PyObject_GetAttrString(v, "obj");')
        add("            if (obj != NULL) ref = as_export_ref(obj);")
        add("            Py_XDECREF(obj);")
        add("            PyErr_Clear();")
        add("        }")
        add("        if (ref != NULL && PyCapsule_IsValid(ref, WASMEXT_EXPORT)) {")
        add("            wasmext_export *e = (wasmext_export *)PyCapsule_GetPointer(ref, WASMEXT_EXPORT);")
        add("            char message[512];")
        add(f"            if ({last}_link_memory{j}(&self->core, e, message, sizeof message)) {{")
        add("                PyErr_SetString(LinkError, message);")
        add("            } else {")
        add("                Py_INCREF((PyObject *)e->owner);")
        add(f"                {hold}.mo{m.slot} = (PyObject *)e->owner;")
        add("            }")
        add("            Py_DECREF(ref);")
        add("            Py_DECREF(v);")
        add("            if (PyErr_Occurred()) { Py_DECREF(self); return NULL; }")
        add("        } else {")
        add("            Py_XDECREF(ref);")
        add("            Py_DECREF(v);")
        add(
            f"            PyErr_SetString(LinkError, {_c_string(f'import {where} is a memory: pass the memory of another instance (instance.memory or instance[{chr(39)}memory{chr(39)}])')});"
        )
        add("            Py_DECREF(self);")
        add("            return NULL;")
        add("        }")
        add("    }")
    for j, tb in enumerate(table_imports):
        where = f"{tb.module}.{tb.field}"
        hold = f"self->hold{tb.host}"
        add("    {")
        add(f"        PyObject *v = lookup_import(imports, {_c_string(tb.module)}, {_c_string(tb.field)}, 0);")
        add("        if (v == NULL) { Py_DECREF(self); return NULL; }")
        add("        PyObject *ref = as_export_ref(v);  /* the reference to an export of another instance */")
        add("        if (ref != NULL) {")
        add("            wasmext_export *e = (wasmext_export *)PyCapsule_GetPointer(ref, WASMEXT_EXPORT);")
        add("            char message[512];")
        add(f"            if ({last}_link_table{j}(&self->core, e, message, sizeof message)) {{")
        add("                PyErr_SetString(LinkError, message);")
        add("            } else {")
        add("                Py_INCREF((PyObject *)e->owner);")
        add(f"                {hold}.to{tb.slot} = (PyObject *)e->owner;")
        add("            }")
        add("            Py_DECREF(ref);")
        add("            Py_DECREF(v);")
        add("            if (PyErr_Occurred()) { Py_DECREF(self); return NULL; }")
        add("        } else {")
        add("            Py_DECREF(v);")
        add(
            f"            PyErr_SetString(LinkError, {_c_string(f'import {where} is a table: pass a Table, or the table of another instance (instance[{chr(39)}name{chr(39)}])')});"
        )
        add("            Py_DECREF(self);")
        add("            return NULL;")
        add("        }")
        add("    }")
    add(f"    int trapped = {last}_glue_instantiate(&self->core);")
    add(f"    if (!trapped) trapped = {last}_glue_initialize(&self->core);")
    if table_imports:
        # what the instantiation wrote into the tables of others dies with a failed instance; a good one is kept by each owner of a table it imports
        add(f"    if (trapped) {last}_scrub_tables(&self->core);")
    add("    if (trapped) { raise_trap(self, trapped); Py_DECREF(self); return NULL; }")
    for tb in table_imports:
        add(f"    if (!keep_alive(self->hold{tb.host}.to{tb.slot}, (PyObject *)self)) {{")
        add(f"        {last}_scrub_tables(&self->core);")
        add("        Py_DECREF(self);")
        add("        return NULL;")
        add("    }")
    add("    return (PyObject *)self;")
    add("}")
    add("")

    if tags:
        hadd("/* the index of the tag of an exception in this module, or -1 (the tag of another module) */")
        hadd(f"static inline int {last}_tag_of(wasm_rt_tag_t tag) {{")
        hadd(f"    for (int i = 0; i < {last.upper()}_TAG_COUNT; i++)")
        hadd(f"        if (wasmext_tags_{prefix}[i] == tag) return i;")
        hadd("    return -1;")
        hadd("}")
        hadd("")
        hadd(
            "/* The values of an exception of the tag `tag`, from the bytes the runtime keeps (`size` of them): how many, or -1 when the bytes are not"
        )
        hadd("   the values of that tag, or -2 when a type of the tag has no decoding here (a reference). */")
        hadd(f"static inline int {last}_tag_values(int tag, const void *payload, uint32_t size, wasmext_value *out) {{")
        hadd("    switch (tag) {")
        for k, tag in enumerate(tags):
            types = tag.params
            hadd(f"    case {k}: {{")
            if any(t not in _PLAIN for t in types):
                hadd("        (void)payload; (void)size; (void)out;")
                hadd("        return -2;")
            elif not types:
                hadd("        (void)payload; (void)out;")
                hadd("        return size == 0 ? 0 : -1;")
            elif len(types) == 1:
                t = types[0]
                hadd(f"        {_CTYPE[t]} v;")
                hadd("        if (size != sizeof v) return -1;")
                hadd("        memcpy(&v, payload, sizeof v);")
                hadd(f"        out[0].type = {_TYPE_CODE[t]};")
                hadd(f"        {_VALUE_STORE[t].format(dst='out[0]', src='v')}")
                hadd("        return 1;")
            else:
                # the values are a struct of them in the order of the tag, as wasm2c puts them (its `struct wasm_multi_<codes>` is not in the header)
                members = " ".join(f"{_CTYPE[t]} m{j};" for j, t in enumerate(types))
                hadd(f"        struct {{ {members} }} p;")
                hadd("        if (size != sizeof p) return -1;")
                hadd("        memcpy(&p, payload, sizeof p);")
                for j, t in enumerate(types):
                    hadd(f"        out[{j}].type = {_TYPE_CODE[t]};")
                    hadd(f"        {_VALUE_STORE[t].format(dst=f'out[{j}]', src=f'p.m{j}')}")
                hadd(f"        return {len(types)};")
            hadd("    }")
        hadd("    default: return -1;")
        hadd("    }")
        hadd("}")
        hadd("")

    # ---- the exports, as typed C functions of the glue (no Python): `result f(void *instance, parameters..., int *trapped)` ----
    # the end of a WASI program (proc_exit, proc_raise) is what the call leaves, as the error I32Exit of Wasmtime is the result of its call: nothing is kept in the instance
    hadd("/* instantiation: 0, or the code of the trap of the start function */")
    hadd(f"static inline int {last}_glue_instantiate({last}_instance *self) {{")
    # The runtime of wasm2c does not check the allocation of a table (1.0.42: a NULL that the first use trips over; later releases: abort()). The same
    # allocation is tried first, here (through a volatile pointer: clang at -O2 drops an allocation that is only freed), so that a table that cannot be had is the error of memory it is, and no part of the runtime is patched for it.
    for t in module.tables:
        if t.limits.min > 0:
            element = "wasm_rt_externref_t" if t.elem == "externref" else "wasm_rt_funcref_t"
            hadd(
                f"    {{ void *volatile probe_ = calloc((size_t){t.limits.min}ULL, sizeof({element})); if (probe_ == NULL) return (int)WASMEXT_TRAP_NO_MEMORY; free(probe_); }}"
            )
    # a trap while the instance is made (a start function that traps, a data segment out of range) leaves what was allocated: it is freed
    # here. Not after NO_MEMORY: the memory that could not be had has size but no data, and the runtime frees it with munmap(NULL, size),
    # which unmaps whatever lives at the bottom of the address space (the interpreter itself); only a further memory of the module leaks then.
    hadd(
        f"    WASMEXT_ENTER(trap_, {{ if (trap_ != WASMEXT_TRAP_NO_MEMORY) wasm2c_{prefix}_free(&self->inst); memset(&self->inst, 0, sizeof self->inst); return (int)trap_; }})"
    )
    # wasm2c orders the import modules by name in the parameters of its `instantiate`, whatever the order of the imports of the module is
    by_name = sorted(range(len(hosts)), key=lambda i: hosts[i].encode("utf-8"))
    host_args = "".join(f", &self->host{i}" for i in by_name)
    hadd(f"    wasm2c_{prefix}_instantiate(&self->inst{host_args});")
    hadd("    WASMEXT_LEAVE();")
    hadd("    self->instantiated = 1;")
    hadd("    return 0;")
    hadd("}")
    hadd("")
    # what a host that is not Python needs to run a command: WASI by itself (the functions of the core for the imports of WASI) and `_start`
    hadd(f"#define {last.upper()}_WASI {1 if uses_wasi else 0}")
    hadd(f"#define {last.upper()}_ONLY_WASI {0 if needs_imports else 1}  /* every import is a function of WASI */")
    start = next((i for i, (n_, f_) in enumerate(funcs) if n_ == "_start" and not f_.params and not f_.results), None)
    if start is not None:
        hadd(f"#define {last.upper()}_START {last}_call{start}")
    run = next(
        (
            i
            for i, (n_, f_) in enumerate(funcs)
            if re.fullmatch(r"wasi:cli/run@0\.2\.\d+#run", n_)
            and not f_.params
            and [str(r) for r in f_.results] == ["i32"]
        ),
        None,
    )
    if wasi2 and run is not None:
        hadd(f"#define {last.upper()}_RUN {last}_call{run}  /* wasi:cli/run#run: 0 for ok, 1 for err */")
    if uses_wasi:
        hadd(
            "/* The state of the host (fusedwasi, p2/) is `self->store->wasi2`, for a module of WASI 0.1 too; a trap of the core comes back to the caller of the module as a trap of the host. */"
        )
        hadd(f"static void {last}_p2_trap(fusedwasi_p2_state *s, const char *message) {{")
        hadd(
            f"    {last}_instance *self = *({last}_instance **)s->user;  /* the instance in call: the first member of what `user` points to */"
        )
        hadd('    snprintf(self->store->p2_message, sizeof self->store->p2_message, "%s", message);')
        hadd("    wasm_rt_trap(WASMEXT_TRAP_HOST);")
        hadd("}")
    if uses_wasi and wasi2:
        hadd(
            "/* WASI 0.2: the host of fusedwasi over the imports. Its state is `self->store->wasi2`; the memory of the instance in call is bound before each call by the pointers to its base and size (they are the instance's own, so a memory that grows is followed). */"
        )
        hadd(f"static inline void {last}_p2_refresh({last}_instance *self) {{")
        hadd(f"    wasm_rt_memory_t *m_ = w2c_{prefix}_{mangle('memory')}(&self->inst);")
        hadd("    fusedwasi_p2_bind_memory(&self->store->wasi2, 0, &m_->data, &m_->size);")
        hadd(
            f"    if (self->store->wasi2.user != NULL) *({last}_instance **)self->store->wasi2.user = self;  /* the instance in call: a store shared by several instances serves each */"
        )
        hadd("}")
        hadd(
            f"static uint32_t {last}_p2_realloc(fusedwasi_p2_state *s, uint32_t comp, uint32_t old_ptr, uint32_t old_size, uint32_t align, uint32_t new_size) {{"
        )
        hadd("    (void)comp;")
        hadd(
            f"    {last}_instance *self = *({last}_instance **)s->user;  /* the first member of what `user` points to */"
        )
        hadd(
            f"    uint32_t r = w2c_{prefix}_{mangle('cabi_realloc')}(&self->inst, old_ptr, old_size, align, new_size);"
        )
        hadd("    return r;  /* the memory may have grown: the binding is of the pointers, nothing to set again */")
        hadd("}")
        hadd(f"static inline void {last}_p2_store_init({last}_store *st) {{")
        hadd("    fusedwasi_p2_init(&st->wasi2);")
        hadd(f"    st->wasi2.trap = {last}_p2_trap;")
        hadd(f"    st->wasi2.realloc = {last}_p2_realloc;")
        hadd("}")
        hadd(f"static inline void {last}_p2_init({last}_instance *self) {{ {last}_p2_store_init(self->store); }}")
        for k, imp in enumerate(imports):
            if imp.module not in wasi_headers:
                continue
            cname = p2_calls[(imp.module, imp.field)]
            has_comp = _P2_FUNCS[cname][1]
            params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(imp.func.params))
            ret = _CTYPE[imp.func.results[0]] if imp.func.results else "void"
            args = "".join(f", a{j}" for j in range(len(imp.func.params)))
            hadd(f"/* {_cc(imp.module)}.{_cc(imp.field)}{_signature(imp.func)} */")
            hadd(f"static {ret} {last}_p2_import{k}(void *user{params}, int *trapped) {{")
            hadd(f"    {last}_instance *self = ({last}_instance *)user;")
            hadd("    (void)trapped;")
            hadd(f"    {last}_p2_refresh(self);")
            hadd(
                f"    {'return ' if imp.func.results else ''}{cname}(&self->store->wasi2{', 0' if has_comp else ''}{args});"
            )
            hadd("}")
        hadd(
            "/* only the imports of an instance over the trampolines, for an instance made in a store that is made already (`wasi_bind` is this and the init of the store) */"
        )
        hadd(f"static inline int {last}_wasi_bind_imports({last}_instance *self) {{")
        for k, imp in enumerate(imports):
            if imp.module in wasi_headers:
                hadd(f"    self->host{imp.host}.fn[{imp.slot}] = (void *){last}_p2_import{k};")
                hadd(f"    self->host{imp.host}.user[{imp.slot}] = self;")
        hadd("    return 0;")
        hadd("}")
        hadd(f"static inline int {last}_wasi_bind({last}_instance *self) {{")
        hadd(f"    {last}_p2_init(self);")
        hadd(f"    return {last}_wasi_bind_imports(self);")
        hadd("}")
        hadd("")
    elif uses_wasi:
        hadd(
            "/* WASI 0.1: a trampoline for each import, as for 0.2: the slot is (function, instance), and the function calls the one of fusedwasi with the state `self->store->wasi` (made first). */"
        )
        hadd(f"static inline void {last}_p2_store_init({last}_store *st) {{")
        hadd("    fusedwasi_p2_init(&st->wasi2);")
        hadd(f"    st->wasi2.trap = {last}_p2_trap;")
        hadd("}")
        hadd(f"static inline void {last}_p2_init({last}_instance *self) {{ {last}_p2_store_init(self->store); }}")
        hadd(
            f"static inline void {last}_p1_bind({last}_instance *self) {{ wasm_rt_memory_t *m_ = w2c_{prefix}_{mangle('memory')}(&self->inst); fusedwasi_p1_bind(self->store->wasi, &m_->data, &m_->size); if (self->store->wasi2.user != NULL) *({last}_instance **)self->store->wasi2.user = self; }}  /* the memory of the instance that calls: a store shared by several serves each */"
        )
        for k, imp in enumerate(imports):
            if imp.module not in wasi_headers:
                continue
            own = imp.module == _WASI_UNSTABLE and imp.field in _WASI_UNSTABLE_OWN
            params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(imp.func.params))
            ret = _CTYPE[imp.func.results[0]] if imp.func.results else "void"
            args = "".join(f", a{j}" for j in range(len(imp.func.params)))
            hadd(f"/* {_cc(imp.module)}.{_cc(imp.field)}{_signature(imp.func)} */")
            hadd(f"static {ret} {last}_p1_import{k}(void *user{params}, int *trapped) {{")
            hadd(f"    {last}_instance *self = ({last}_instance *)user;")
            hadd(f"    {last}_p1_bind(self);")
            hadd(
                f"    {'return ' if imp.func.results else ''}fusedwasi_p1_{'unstable_' if own else ''}{imp.field}(self->store->wasi{args}, trapped);"
            )
            hadd("}")
        hadd("/* the imports of WASI over the trampolines: 0 */")
        hadd(
            "/* only the imports of an instance over the trampolines, for an instance made in a store that is made already (`wasi_bind` is this and the init of the store) */"
        )
        hadd(f"static inline int {last}_wasi_bind_imports({last}_instance *self) {{")
        for k, imp in enumerate(imports):
            if imp.module in wasi_headers:
                hadd(f"    self->host{imp.host}.fn[{imp.slot}] = (void *){last}_p1_import{k};")
                hadd(f"    self->host{imp.host}.user[{imp.slot}] = self;")
        hadd("    return 0;")
        hadd("}")
        hadd(f"static inline int {last}_wasi_bind({last}_instance *self) {{")
        hadd(f"    {last}_p2_init(self);")
        hadd(f"    return {last}_wasi_bind_imports(self);")
        hadd("}")
        hadd("")
    hadd(f"static inline void {last}_glue_free({last}_instance *self) {{")
    hadd(f"    if (self->instantiated) wasm2c_{prefix}_free(&self->inst);")
    hadd("    self->instantiated = 0;")
    hadd("}")
    hadd("")
    reactor_init = next(
        (i for i, (n_, f_) in enumerate(funcs) if n_ == "_initialize" and not f_.params and not f_.results), None
    )
    if any(n_ == "_start" for n_, _ in funcs):
        reactor_init = None  # a command: nothing is run before the program starts
    for i, (exp_name, func) in enumerate(funcs):
        params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(func.params))
        several = len(func.results) > 1
        codes = "".join(_MULTI_CODE[t] for t in func.results)
        ret = f"struct wasm_multi_{codes}" if several else _CTYPE[func.results[0]] if func.results else "void"
        names = "".join(f", a{j}" for j in range(len(func.params)))
        give = "return zero;" if func.results else "return;"
        hadd(f"/* {_cc(exp_name)}{_signature(func)} */")
        hadd(f"static inline {ret} {last}_call{i}(void *inst{params}, int *trapped) {{")
        if func.results:
            hadd(f"    {ret} zero;")
            hadd("    memset(&zero, 0, sizeof zero);")
        hadd(f"    {last}_instance *self = ({last}_instance *)((char *)inst - offsetof({last}_instance, inst));")
        hadd(f"    if (self->store->closed) {{ *trapped = (int)WASMEXT_TRAP_CLOSED; {give} }}")
        hadd("    self->store->active++;")
        if uses_wasi:
            hadd("    self->store->wasi2.exited = 0;  /* the end of the last call is not the end of this one */")
            if not wasi2:
                hadd("    if (self->store->wasi != NULL) self->store->wasi->finished = 0;")
        hadd(f"    WASMEXT_ENTER(trap_, {{ self->store->active--; *trapped = (int)trap_; {give} }})")
        call = f"w2c_{prefix}_{mangle(exp_name)}((w2c_{prefix} *)inst{names})"
        if func.results:
            hadd(f"    {ret} r = {call};")
            hadd("    WASMEXT_LEAVE();")
            hadd("    self->store->active--;")
            hadd("    return r;")
        else:
            hadd(f"    {call};")
            hadd("    WASMEXT_LEAVE();")
            hadd("    self->store->active--;")
        hadd("}")
        hadd("")
    if shares_tables:
        _emit_refcalls(hadd, last, prefix, ref_types)
    hadd("#endif")

    # ---- the exported functions in Python: the arguments to C, the call, the result (or the trap) to Python ----
    for i, (exp_name, func) in enumerate(funcs):
        n = len(func.params)
        add(f"/* {_cc(exp_name)}{_signature(func)} */")
        add(f"static PyObject *Instance_f{i}(InstanceObject *self, PyObject *const *args, Py_ssize_t nargs) {{")
        add(f"    if (nargs != {n}) {{")
        add(
            f'        PyErr_Format(PyExc_TypeError, "%s() takes exactly {n} argument{"" if n == 1 else "s"} (%zd given)", '
            f"{_c_string(exp_name)}, nargs);"
        )
        add("        return NULL;")
        add("    }")
        for j, t in enumerate(func.params):
            add(f"    {_CTYPE[t]} a{j} = {_TO_WASM[t].format(f'args[{j}]')};")
        if n:
            add("    if (PyErr_Occurred()) return NULL;")
        if i == reactor_init:
            add(
                "    if (self->core.initialized) Py_RETURN_NONE;  /* the reactor was initialized when the instance was made */"
            )
        add("    int trapped = 0;")
        call_args = "".join(f", a{j}" for j in range(n))
        call = f"{last}_call{i}(&self->core.inst{call_args}, &trapped)"
        if len(func.results) > 1:
            codes = "".join(_MULTI_CODE[t] for t in func.results)
            add(f"    struct wasm_multi_{codes} r = {call};")
            add("    if (trapped) { raise_trap(self, trapped); return NULL; }")
            fmt = "".join(_BUILD[t][0] for t in func.results)
            members = "".join(f", {_BUILD[t][1].format(f'r.{_MULTI_CODE[t]}{k}')}" for k, t in enumerate(func.results))
            add(f'    return Py_BuildValue("({fmt})"{members});')
        elif func.results:
            add(f"    {_CTYPE[func.results[0]]} r = {call};")
            add("    if (trapped) { raise_trap(self, trapped); return NULL; }")
            add(f"    return {_FROM_WASM[func.results[0]].format('r')};")
        else:
            add(f"    {call};")
            add("    if (trapped) { raise_trap(self, trapped); return NULL; }")
            add("    Py_RETURN_NONE;")
        add("}")
        add("")
    # instance['name'] and instance.__exports__: the references to the exports (capsules that another extension reads)
    # name, kind, type, flags, the getter of the address of a global, the function to call, its signature
    mapped: list[tuple[str, int, int | str, int | str, str, str, str, int]] = []
    for i, (exp_name, glob) in enumerate(globals_):
        accessor = f"w2c_{prefix}_{mangle(exp_name)}"
        add(f"static void *export_address{i}(InstanceObject *self) {{ return (void *){accessor}(&self->core.inst); }}")
        mapped.append((exp_name, 3, _TYPE_CODE[glob.type], int(glob.mutable), f"export_address{i}", "NULL", "NULL", -1))
    if globals_:
        add("")
    for i, (exp_name, func) in enumerate(funcs):
        # what another Python extension calls: the typed function of the glue, and a trap becomes an exception of THIS extension (its
        # Trap, its WASI program that is over) before it is answered through `trapped`, as the contract of the link says
        params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(func.params))
        several = len(func.results) > 1
        codes = "".join(_MULTI_CODE[t] for t in func.results)
        ret = f"struct wasm_multi_{codes}" if several else _CTYPE[func.results[0]] if func.results else "void"
        names = "".join(f", a{j}" for j in range(len(func.params)))
        add(f"static {ret} py_link{i}(void *inst{params}, int *trapped) {{")
        add("    InstanceObject *self = (InstanceObject *)((char *)inst - offsetof(InstanceObject, core.inst));")
        if func.results:
            add(f"    {ret} r = {last}_call{i}(inst{names}, trapped);")
            add("    if (*trapped) { raise_trap(self, *trapped); *trapped = (int)WASMEXT_TRAP_HOST; }")
            add("    return r;")
        else:
            add(f"    {last}_call{i}(inst{names}, trapped);")
            add("    if (*trapped) { raise_trap(self, *trapped); *trapped = (int)WASMEXT_TRAP_HOST; }")
        add("}")
        add("")
        mapped.append(
            (
                exp_name,
                0,
                0,
                16 if shares_tables else 0,
                "NULL",
                f"(void *)py_link{i}",
                _c_string(_signature_code(func)),
                i,
            )
        )
    # a reactor (`_initialize` and no `_start`) is initialized once, after it is instantiated and before any other export, as WASI says a host must; every front end
    # does it through this, so that they agree, and an explicit call of `_initialize` afterwards does nothing (a second run of the constructors would break the module)
    hadd(
        "/* runs `_initialize` of a reactor once, after the instance is made: 0, or the code of a trap; nothing for any other module */"
    )
    hadd(f"static inline int {last}_glue_initialize({last}_instance *self) {{")
    if reactor_init is None:
        hadd("    (void)self;")
        hadd("    return 0;")
    else:
        hadd("    if (self->initialized) return 0;")
        hadd("    self->initialized = 1;")
        hadd("    int trapped = 0;")
        hadd(f"    {last}_call{reactor_init}(&self->inst, &trapped);")
        hadd("    return trapped;")
    hadd("}")
    hadd("")
    memory_base = len(mapped)
    for i, (exp_name, lim) in enumerate(zip(memories, memory_limits, strict=True)):
        accessor = f"w2c_{prefix}_{mangle(exp_name)}"
        add(f"static void *export_memory{i}(InstanceObject *self) {{ return (void *){accessor}(&self->core.inst); }}")
        flags = f"({2 * int(lim.is64)}u | (WASM_RT_MEMCHECK_GUARD_PAGES ? 4u : 0u))"
        mapped.append(
            (exp_name, 2, "(uint32_t)sizeof(wasm_rt_memory_t)", flags, f"export_memory{i}", "NULL", "NULL", -1)
        )
    if memories:
        add("")
    tables_base = len(mapped)
    for i, exp_name in enumerate(tables):
        accessor = f"w2c_{prefix}_{mangle(exp_name)}"
        add(f"static void *export_table{i}(InstanceObject *self) {{ return (void *){accessor}(&self->core.inst); }}")
        mapped.append(
            (exp_name, 1, "(uint32_t)sizeof(wasm_rt_funcref_table_t)", 0, f"export_table{i}", "NULL", "NULL", -1)
        )
    if tables:
        add("")
        add(
            "/* instance.__wasmext_keep__(other): `other` imported a table of this instance, so it may have put functions of its own in it: this instance keeps it alive */"
        )
        add("static PyObject *Instance_keep(PyObject *self, PyObject *other) {")
        add("    InstanceObject *me = (InstanceObject *)self;")
        add("    if (me->writers == NULL || PyList_Append(me->writers, other) < 0) return NULL;")
        add("    Py_RETURN_NONE;")
        add("}")
        add("")
    add(
        "static const struct { const char *name; uint32_t kind, type, flags; void *(*address)(InstanceObject *); "
        "void *function; const char *signature; int fn; } export_table[] = {"
    )
    for exp_name, kind, type_code, flags, address, function, signature, fn in mapped:
        add(f"    {{{_c_string(exp_name)}, {kind}, {type_code}, {flags}, {address}, {function}, {signature}, {fn}}},")
    add("    {NULL, 0, 0, 0, NULL, NULL, NULL, -1}")
    add("};")
    add("")
    add("static void export_free(PyObject *capsule) {")
    add("    wasmext_export *e = (wasmext_export *)PyCapsule_GetPointer(capsule, WASMEXT_EXPORT);")
    add("    if (e != NULL) { Py_DECREF((PyObject *)e->owner); PyMem_Free(e); }")
    add("}")
    add("")
    add("static PyObject *export_ref(PyObject *self, int k) {")
    add("    wasmext_export *e = (wasmext_export *)PyMem_Malloc(sizeof(wasmext_export));")
    add("    if (e == NULL) return PyErr_NoMemory();")
    add("    e->size = sizeof(wasmext_export);")
    add("    e->abi = WASMEXT_ABI;")
    add("    e->kind = export_table[k].kind;")
    add("    e->type = export_table[k].type;")
    add("    e->flags = export_table[k].flags;")
    add(
        "    e->address = export_table[k].address != NULL ? export_table[k].address((InstanceObject *)self) : export_table[k].function;"
    )
    add("    e->instance = &((InstanceObject *)self)->core.inst;")
    add("    e->signature = export_table[k].signature;")
    add("    e->runtime = WASMEXT_RUNTIME;")
    add(
        f"    e->funcref = export_table[k].fn >= 0 ? (const void *){last}_glue_funcref(&((InstanceObject *)self)->core, export_table[k].fn) : NULL;"
    )
    add("    Py_INCREF(self);")
    add("    e->owner = self;")
    add("    wasmext_export_seal(e);")
    add("    PyObject *capsule = PyCapsule_New(e, WASMEXT_EXPORT, export_free);")
    add("    if (capsule == NULL) { Py_DECREF(self); PyMem_Free(e); }")
    add("    return capsule;")
    add("}")
    add("")
    if shares_tables:
        add(_function_type_c(last, ref_types))
        add(_table_type_c(prefix, tables, tables_base))
    add("/* instance['name'] and instance.__exports__ give the reference to an export; a table is given as a Table */")
    add("static PyObject *export_value(PyObject *self, int k) {")
    if tables:
        add("    if (export_table[k].kind == WASMEXT_TABLE) return Table_of(self, k);")
    add("    return export_ref(self, k);")
    add("}")
    add("")
    add("/* instance['name']: the reference to one export (KeyError if there is none) */")
    add("static PyObject *Instance_subscript(PyObject *self, PyObject *key) {")
    add("    const char *name = PyUnicode_Check(key) ? PyUnicode_AsUTF8AndSize(key, NULL) : NULL;")
    add("    if (name == NULL) {")
    add("        if (PyErr_Occurred() && !PyErr_ExceptionMatches(PyExc_TypeError)) return NULL;")
    add("        PyErr_Clear();")
    add("        PyErr_SetObject(PyExc_KeyError, key);")
    add("        return NULL;")
    add("    }")
    add("    for (int k = 0; export_table[k].name != NULL; k++) {")
    add("        if (strcmp(name, export_table[k].name) == 0) return export_value(self, k);")
    add("    }")
    add("    PyErr_SetObject(PyExc_KeyError, key);")
    add("    return NULL;")
    add("}")
    add("")
    add("/* instance.__exports__: {name: a reference to the export}, to be given as an import of another instance */")
    add("static PyObject *Instance_exports(PyObject *self, void *closure) {")
    add("    (void)closure;")
    add("    PyObject *result = PyDict_New();")
    add("    if (result == NULL) return NULL;")
    add("    for (int k = 0; export_table[k].name != NULL; k++) {")
    add("        PyObject *name = PyUnicode_FromString(export_table[k].name);")
    add("        PyObject *ref = name != NULL ? export_value(self, k) : NULL;")
    add("        int bad = ref == NULL || PyDict_SetItem(result, name, ref) != 0;")
    add("        Py_XDECREF(name);")
    add("        Py_XDECREF(ref);")
    add("        if (bad) { Py_DECREF(result); return NULL; }")
    add("    }")
    add("    return result;")
    add("}")
    add("")
    add("static PyMethodDef Instance_methods[] = {")
    for i, (exp_name, func) in enumerate(funcs):
        if exp_name in no_attribute:
            continue
        doc = f"{exp_name}{_signature(func)}"
        add(
            f"    {{{_c_string(exp_name)}, (PyCFunction)(void (*)(void))Instance_f{i}, METH_FASTCALL, {_c_string(doc)}}},"
        )
    if tables:
        add(
            '    {"__wasmext_keep__", (PyCFunction)Instance_keep, METH_O, "keep an instance that imported a table of this one alive (not for you to call)"},'
        )
    add("    {NULL, NULL, 0, NULL}")
    add("};")
    add("")

    # the exported memories: an attribute that is a memoryview, held by an object that keeps the instance alive
    if memories:
        add(
            "/* A memory that the runtime allocates with calloc (no guard pages, or memory64, or another page size) is moved by realloc when it grows, and a"
        )
        add(
            "   buffer would then point to freed memory. While a buffer of such a memory is alive, `memory.grow` fails (-1, which WebAssembly allows at any time):"
        )
        add(
            "   the maximum is made the present size, as bytearray refuses to be resized while it is exported. With guard pages the memory does not move. */"
        )
        add("static int memory_can_move(const wasm_rt_memory_t *mem) {")
        add("#if WASM_RT_USE_MMAP")
        add("    return mem->is64 || mem->page_size != WASM_DEFAULT_PAGE_SIZE;")
        add("#else")
        add("    (void)mem;")
        add("    return 1;")
        add("#endif")
        add("}")
        add("")
        add("static int Memory_getbuffer(PyObject *self, Py_buffer *view, int flags) {")
        add("    MemoryObject *m = (MemoryObject *)self;")
        add("    wasm_rt_memory_t *mem = m->get(&m->owner->core.inst);")
        add("    if (mem->size > (uint64_t)PY_SSIZE_T_MAX) {")
        add('        PyErr_SetString(PyExc_MemoryError, "the memory is too big for a buffer");')
        add("        return -1;")
        add("    }")
        add("    if (PyBuffer_FillInfo(view, self, mem->data, (Py_ssize_t)mem->size, 0, flags) < 0) return -1;")
        add("    if (memory_can_move(mem)) {")
        add("        if (m->owner->mem_pins[m->which]++ == 0) {")
        add("            m->owner->mem_max_pages[m->which] = mem->max_pages;")
        add("            mem->max_pages = mem->pages;")
        add("        }")
        add("        view->internal = (void *)1;  /* this buffer holds the memory still */")
        add("    }")
        add("    return 0;")
        add("}")
        add("")
        add("static void Memory_releasebuffer(PyObject *self, Py_buffer *view) {")
        add("    MemoryObject *m = (MemoryObject *)self;")
        add("    if (view->internal == NULL) return;")
        add(
            "    if (--m->owner->mem_pins[m->which] == 0) m->get(&m->owner->core.inst)->max_pages = m->owner->mem_max_pages[m->which];"
        )
        add("}")
        add("")
        add(
            "/* memory.__wasmext_ref__: the reference to this memory, for the instance that imports it (see Instance_new) */"
        )
        add("static PyObject *Memory_ref(PyObject *self, void *closure) {")
        add("    (void)closure;")
        add("    return export_ref((PyObject *)((MemoryObject *)self)->owner, ((MemoryObject *)self)->export_index);")
        add("}")
        add("")
        add("static PyGetSetDef Memory_getset[] = {")
        add(
            '    {"__wasmext_ref__", (getter)Memory_ref, NULL, "the reference to the memory, to be given as an import", NULL},'
        )
        add("    {NULL, NULL, NULL, NULL, NULL}")
        add("};")
        add("")
        add("static void Memory_dealloc(MemoryObject *self) {")
        add("    PyTypeObject *tp = Py_TYPE((PyObject *)self);")
        add("    Py_XDECREF((PyObject *)self->owner);")
        add("    ((freefunc)PyType_GetSlot(tp, Py_tp_free))((PyObject *)self);")
        add("    Py_DECREF(tp);")
        add("}")
        add("")
        add(f"static wasm_rt_memory_t *(*const memory_getters[])(w2c_{prefix} *) = {{")
        for exp_name in memories:
            add(f"    w2c_{prefix}_{mangle(exp_name)},")
        add("    NULL")
        add("};")
        add("")
        add("static PyObject *Instance_memory(InstanceObject *self, void *closure) {")
        add("#if WABT_BIG_ENDIAN")
        add("    /* wasm2c keeps the memory reversed on a big-endian host: there is no plain buffer to give */")
        add("    (void)self; (void)closure;")
        add(
            '    PyErr_SetString(PyExc_NotImplementedError, "the memory of a module is not available as a memoryview on a big-endian host");'
        )
        add("    return NULL;")
        add("#else")
        add("    MemoryObject *m = PyObject_New(MemoryObject, MemoryType);")
        add("    PyObject *view;")
        add("    if (m == NULL) return NULL;")
        add("    Py_INCREF((PyObject *)self);")
        add("    m->owner = self;")
        add("    m->get = memory_getters[(size_t)closure];")
        add("    m->which = (size_t)closure;")
        add(f"    m->export_index = {memory_base} + (int)(size_t)closure;")
        add("    view = PyMemoryView_FromObject((PyObject *)m);")
        add("    Py_DECREF(m);")
        add("    return view;")
        add("#endif")
        add("}")
        add("")
    # the exported globals: attributes of the instance (read-only if the global is immutable)
    for i, (exp_name, glob) in enumerate(globals_):
        accessor = f"w2c_{prefix}_{mangle(exp_name)}(&self->core.inst)"
        add(f"static PyObject *Instance_global_get{i}(InstanceObject *self, void *closure) {{")
        add("    (void)closure;")
        add(f"    return {_FROM_WASM[glob.type].format(f'*{accessor}')};")
        add("}")
        if glob.mutable:
            add(f"static int Instance_global_set{i}(InstanceObject *self, PyObject *value, void *closure) {{")
            add("    (void)closure;")
            add("    if (value == NULL) {")
            add(
                f"        PyErr_SetString(PyExc_AttributeError, {_c_string(f'cannot delete the global {exp_name!r}')});"
            )
            add("        return -1;")
            add("    }")
            add(f"    {_CTYPE[glob.type]} v = {_TO_WASM[glob.type].format('value')};")
            add("    if (PyErr_Occurred()) return -1;")
            add(f"    *{accessor} = v;")
            add("    return 0;")
            add("}")
        add("")
    host_calls = [(k, imp) for k, imp in enumerate(imports) if imp.module in wasi_headers]
    if uses_wasi and not wasi2:
        add(
            "/* ---- the Host: what answers the imports of WASI (wasm32-wasip1) and the originals of its calls, for Python ---- */"
        )
        add("typedef struct { PyObject_HEAD InstanceObject *inst; } HostObject;")
        for k, imp in host_calls:
            n = len(imp.func.params)
            own = imp.module == _WASI_UNSTABLE and imp.field in _WASI_UNSTABLE_OWN
            core = f"fusedwasi_p1_{'unstable_' if own else ''}{imp.field}"
            add(f"/* the call of wasmext for {_cc(imp.module)}.{_cc(imp.field)}{_signature(imp.func)}, from Python */")
            add(f"static PyObject *host_call{k}(PyObject *selfobj, PyObject *const *args, Py_ssize_t nargs) {{")
            add("    InstanceObject *self = (InstanceObject *)selfobj;")
            add(f"    if (nargs != {n}) {{")
            add(
                f'        PyErr_Format(PyExc_TypeError, "%s() takes exactly {n} argument{"" if n == 1 else "s"} (%zd given)", '
                f"{_c_string(imp.field)}, nargs);"
            )
            add("        return NULL;")
            add("    }")
            for j, t in enumerate(imp.func.params):
                add(f"    {_CTYPE[t]} a{j} = {_TO_WASM[t].format(f'args[{j}]')};")
            if n:
                add("    if (PyErr_Occurred()) return NULL;")
            add(
                '    if (self->core.store->closed) { PyErr_SetString(PyExc_ValueError, "the store is closed"); return NULL; }'
            )
            add(f"    {last}_p1_bind(&self->core);  /* the memory of this instance: a store is shared by several */")
            add("    int trapped = 0;")
            call_args = "".join(f", a{j}" for j in range(n))
            call = f"{core}(self->core.store->wasi{call_args}, &trapped)"
            if imp.func.results:
                add(f"    {_CTYPE[imp.func.results[0]]} r = {call};")
                add("    if (trapped) { raise_trap(self, (int)WASMEXT_TRAP_HOST); return NULL; }")
                add(f"    return {_FROM_WASM[imp.func.results[0]].format('r')};")
            else:
                add(f"    {call};")
                add("    if (trapped) { raise_trap(self, (int)WASMEXT_TRAP_HOST); return NULL; }")
                add("    Py_RETURN_NONE;")
            add("}")
            add(
                f"static PyMethodDef host_def{k} = {{{_c_string(imp.field)}, (PyCFunction)(void (*)(void))host_call{k}, METH_FASTCALL, NULL}};"
            )
        add(
            "static int host_put(PyObject *all, const char *module, const char *field, PyMethodDef *def, PyObject *inst) {"
        )
        add("    PyObject *sub = PyDict_GetItemString(all, module);")
        add("    if (sub == NULL) {")
        add("        sub = PyDict_New();")
        add("        if (sub == NULL) return -1;")
        add("        int made = PyDict_SetItemString(all, module, sub);")
        add("        Py_DECREF(sub);")
        add("        if (made < 0) return -1;")
        add("        sub = PyDict_GetItemString(all, module);")
        add("    }")
        add("    PyObject *fn = PyCFunction_New(def, inst);")
        add("    if (fn == NULL) return -1;")
        add("    int r = PyDict_SetItemString(sub, field, fn);")
        add("    Py_DECREF(fn);")
        add("    return r;")
        add("}")
        add("static PyObject *Host_imports(HostObject *self, void *closure) {")
        add("    (void)closure;")
        add("    PyObject *all = PyDict_New();")
        add("    if (all == NULL) return NULL;")
        for k, imp in host_calls:
            add(
                f"    if (host_put(all, {_c_string(imp.module)}, {_c_string(imp.field)}, &host_def{k}, (PyObject *)self->inst) < 0) {{ Py_DECREF(all); return NULL; }}"
            )
        add("    return all;")
        add("}")
        add("static PyObject *Host_name(HostObject *self, void *closure) {")
        add("    (void)self; (void)closure;")
        add(f"    return PyUnicode_FromString({_c_string(host_name)});")
        add("}")
        add("static void Host_dealloc(HostObject *self) {")
        add("    PyTypeObject *tp = Py_TYPE((PyObject *)self);")
        add("    Py_XDECREF((PyObject *)self->inst);")
        add("    ((freefunc)PyType_GetSlot(tp, Py_tp_free))((PyObject *)self);")
        add("    Py_DECREF(tp);")
        add("}")
        add("static PyGetSetDef Host_getset[] = {")
        add(
            '    {"__imports__", (getter)Host_imports, NULL, "{module: {name: the call}}: the calls the host answers, as wasmext has them, whatever the caller gave in place of them", NULL},'
        )
        add('    {"name", (getter)Host_name, NULL, "the name of the host", NULL},')
        add("    {NULL, NULL, NULL, NULL, NULL}")
        add("};")
        add("static PyType_Slot host_slots[] = {")
        add("    {Py_tp_dealloc, Host_dealloc},")
        add("    {Py_tp_getset, Host_getset},")
        add("    {0, NULL}")
        add("};")
        add(
            f"static PyType_Spec host_spec = {{{_c_string(name + '.Host')}, sizeof(HostObject), 0, "
            "Py_TPFLAGS_DEFAULT | Py_TPFLAGS_DISALLOW_INSTANTIATION, host_slots};"
        )
        add("static PyObject *Instance_host(InstanceObject *self, void *closure) {")
        add("    (void)closure;")
        add("    HostObject *h = PyObject_New(HostObject, HostType);")
        add("    if (h == NULL) return NULL;")
        add("    Py_INCREF((PyObject *)self);")
        add("    h->inst = self;")
        add("    return (PyObject *)h;")
        add("}")
        add("")
    add("static PyGetSetDef Instance_getset[] = {")
    add(
        '    {"__exports__", (getter)Instance_exports, NULL, "{name: a reference to the export}: what another instance can take as an import", NULL},'
    )
    if uses_wasi and not wasi2:
        add(
            '    {"__host__", (getter)Instance_host, NULL, "the Host: what answers the imports of WASI, and the originals of its calls", NULL},'
        )
    for i, (exp_name, glob) in enumerate(globals_):
        if exp_name in no_attribute:
            continue
        setter = f"(setter)Instance_global_set{i}" if glob.mutable else "NULL"
        kind = "mutable" if glob.mutable else "immutable"
        add(
            f"    {{{_c_string(exp_name)}, (getter)Instance_global_get{i}, {setter}, "
            f'"the {kind} global of type {glob.type}", NULL}},'
        )
    for i, exp_name in enumerate(memories):
        if exp_name in no_attribute:
            continue
        add(
            f"    {{{_c_string(exp_name)}, (getter)Instance_memory, NULL, "
            f'"a memoryview of the linear memory (a new one after the memory grows)", (void *)(size_t){i}}},'
        )
    add("    {NULL, NULL, NULL, NULL, NULL}")
    add("};")
    add("")

    add("static PyMemberDef Instance_members[] = {")
    add('    {"__weaklistoffset__", T_PYSSIZET, offsetof(InstanceObject, weakreflist), READONLY, NULL},')
    add("    {NULL, 0, 0, 0, NULL}")
    add("};")
    add("")
    add("static PyMemberDef Store_members[] = {")
    add('    {"__weaklistoffset__", T_PYSSIZET, offsetof(StoreObject, weakreflist), READONLY, NULL},')
    add("    {NULL, 0, 0, 0, NULL}")
    add("};")
    add("")
    add("static PyMethodDef Store_methods[] = {")
    add(
        '    {"close", (PyCFunction)Store_close, METH_NOARGS, "close the store: its host is let go, its instances can not be called any more"},'
    )
    add('    {"__enter__", (PyCFunction)Store_enter, METH_NOARGS, NULL},')
    add('    {"__exit__", (PyCFunction)Store_exit, METH_VARARGS, NULL},')
    add("    {NULL, NULL, 0, NULL}")
    add("};")
    add("")
    add("static PyGetSetDef Store_getset[] = {")
    add('    {"closed", (getter)Store_closed, NULL, "whether the store was closed", NULL},')
    add('    {"runtime", (getter)Store_runtime, NULL, "the identity of the runtime: name, abi, fingerprint", NULL},')
    add("    {NULL, NULL, NULL, NULL, NULL}")
    add("};")
    add("")
    add("static PyType_Slot store_slots[] = {")
    add("    {Py_tp_new, Store_new},")
    add("    {Py_tp_methods, Store_methods},")
    add("    {Py_tp_getset, Store_getset},")
    add("    {Py_tp_dealloc, Store_dealloc},")
    add("    {Py_tp_traverse, Store_traverse},")
    add("    {Py_tp_clear, Store_clear},")
    add("    {Py_tp_members, Store_members},")
    add(
        f"    {{Py_tp_doc, (void *){_c_string('The host of the instances made in it (who answers the imports of WASI), with its configuration `wasi=`')}}},"
    )
    add("    {0, NULL}")
    add("};")
    add(
        f"static PyType_Spec store_spec = {{{_c_string(name + '.Store')}, sizeof(StoreObject), 0, "
        "Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC, store_slots};"
    )
    add("")
    if has_imports:
        add("static PyType_Slot caller_slots[] = {")
        add("    {Py_tp_dealloc, Caller_dealloc},")
        add("    {Py_tp_traverse, Caller_traverse},")
        add("    {Py_tp_clear, Caller_clear},")
        add("    {Py_tp_getset, Caller_getset},")
        add(
            f"    {{Py_tp_doc, (void *){_c_string('What a callable that asks for it is given first: the instance that called, its store and its memory')}}},"
        )
        add("    {0, NULL}")
        add("};")
        add(
            f"static PyType_Spec caller_spec = {{{_c_string(name + '.Caller')}, sizeof(CallerObject), 0, "
            "Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_DISALLOW_INSTANTIATION, caller_slots};"
        )
        add("")
    add("static PyType_Slot instance_slots[] = {")
    add("    {Py_tp_new, Instance_new},")
    add("    {Py_tp_dealloc, Instance_dealloc},")
    add("    {Py_tp_traverse, Instance_traverse},")
    add("    {Py_tp_clear, Instance_clear},")
    add("    {Py_tp_methods, Instance_methods},")
    add("    {Py_mp_subscript, Instance_subscript},")
    add("    {Py_tp_getset, Instance_getset},")
    add("    {Py_tp_members, Instance_members},")
    add(f"    {{Py_tp_doc, (void *){_c_string('An instance of the WebAssembly module')}}},")
    add("    {0, NULL}")
    add("};")
    add(
        f"static PyType_Spec instance_spec = {{{_c_string(name + '.Instance')}, sizeof(InstanceObject), 0, "
        "Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_BASETYPE, instance_slots};"
    )
    add("")
    if memories:
        add("static PyType_Slot memory_slots[] = {")
        add("    {Py_bf_getbuffer, Memory_getbuffer},")
        add("    {Py_bf_releasebuffer, Memory_releasebuffer},")
        add("    {Py_tp_dealloc, Memory_dealloc},")
        add("    {Py_tp_getset, Memory_getset},")
        add("    {0, NULL}")
        add("};")
        add(
            f"static PyType_Spec memory_spec = {{{_c_string(name + '.Memory')}, sizeof(MemoryObject), 0, "
            "Py_TPFLAGS_DEFAULT, memory_slots};"
        )
        add("")
    if shares_tables:
        add(
            f"static PyType_Spec function_spec = {{{_c_string(name + '.Function')}, sizeof(FunctionObject), 0, "
            "Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC | Py_TPFLAGS_DISALLOW_INSTANTIATION, function_slots};"
        )
        add(
            f"static PyType_Spec table_spec = {{{_c_string(name + '.Table')}, sizeof(TableObject), 0, "
            "Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC, table_slots};"
        )
        add("")
    add(
        f"static struct PyModuleDef module_def = {{PyModuleDef_HEAD_INIT, {_c_string(name)}, "
        f"{_c_string('A WebAssembly module as a native extension (wasmext, wasm2c)')}, -1, NULL}};"
    )
    add("")
    add(f"PyMODINIT_FUNC PyInit_{last}(void) {{")
    add("    PyObject *m;")
    add(
        "    wasm_rt_init();  /* sets up this thread too; not given back, as before (see the comment above wasmext_py_thread_end_) */"
    )
    add("    wasmext_py_ready_ = 1;")
    add("#ifdef WASMEXT_STACK_LIMIT")
    add("    wasmext_stack_limit_init_();")
    add("#endif")
    add("#ifdef WASMEXT_CHAIN")
    add(
        '    if (wasmext_chain_install_() < 0) { PyErr_SetString(PyExc_ImportError, "wasmext: sigaction failed"); return NULL; }'
    )
    add("#endif")
    if shares_tables:
        add("    if (attach_traps() < 0) return NULL;")
    add("    m = PyModule_Create(&module_def);")
    add("    if (m == NULL) return NULL;")
    add(
        f'    TrapError = PyErr_NewExceptionWithDoc({_c_string(name + ".Trap")}, "The WebAssembly code trapped", PyExc_RuntimeError, NULL);'
    )
    add(
        f'    LinkError = PyErr_NewExceptionWithDoc({_c_string(name + ".LinkError")}, "An import is missing", PyExc_Exception, NULL);'
    )
    if uses_wasi:
        add(
            f'    WasiTerminatedError = PyErr_NewExceptionWithDoc({_c_string(name + ".WasiTerminated")}, "The call ended the WebAssembly program (proc_exit, proc_raise); the base of WasiExit and WasiSignal. The instance can be called again, as in Wasmtime", PyExc_Exception, NULL);'
        )
        add(
            f'    WasiExitError = PyErr_NewExceptionWithDoc({_c_string(name + ".WasiExit")}, "The WebAssembly program called proc_exit (its code is .code)", WasiTerminatedError, NULL);'
        )
        add(
            f'    WasiSignalError = PyErr_NewExceptionWithDoc({_c_string(name + ".WasiSignal")}, "The WebAssembly program called proc_raise (the number of the signal is .signal, its name .name)", WasiTerminatedError, NULL);'
        )
    if tags:
        add(
            f'    UncaughtExceptionError = PyErr_NewExceptionWithDoc({_c_string(name + ".UncaughtException")}, "An exception of WebAssembly that nothing caught (.tag, .values)", TrapError, NULL);'
        )
    add("    StoreType = (PyTypeObject *)PyType_FromSpec(&store_spec);")
    if has_imports:
        add("    CallerType = (PyTypeObject *)PyType_FromSpec(&caller_spec);")
    add("    InstanceType = (PyTypeObject *)PyType_FromSpec(&instance_spec);")
    if uses_wasi and not wasi2:
        add("    HostType = (PyTypeObject *)PyType_FromSpec(&host_spec);")
    if memories:
        add("    MemoryType = (PyTypeObject *)PyType_FromSpec(&memory_spec);")
    if shares_tables:
        add("    TableType = (PyTypeObject *)PyType_FromSpec(&table_spec);")
        add("    FunctionType = (PyTypeObject *)PyType_FromSpec(&function_spec);")
    add(
        "    if (!TrapError || !LinkError || !StoreType || !InstanceType"
        + (" || !CallerType" if has_imports else "")
        + (" || !WasiTerminatedError || !WasiExitError || !WasiSignalError" if uses_wasi else "")
        + (" || !HostType" if uses_wasi and not wasi2 else "")
        + (" || !MemoryType" if memories else "")
        + (" || !TableType || !FunctionType" if shares_tables else "")
        + (" || !UncaughtExceptionError" if tags else "")
        + ") goto fail;"
    )
    if uses_wasi:
        add('    if (PyModule_AddObjectRef(m, "WasiTerminated", WasiTerminatedError) < 0) goto fail;')
        add('    if (PyModule_AddObjectRef(m, "WasiExit", WasiExitError) < 0) goto fail;')
        add('    if (PyModule_AddObjectRef(m, "WasiSignal", WasiSignalError) < 0) goto fail;')
    if uses_wasi and not wasi2:
        add('    if (PyModule_AddObjectRef(m, "Host", (PyObject *)HostType) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "Trap", TrapError) < 0) goto fail;')
    if tags:
        add('    if (PyModule_AddObjectRef(m, "UncaughtException", UncaughtExceptionError) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "LinkError", LinkError) < 0) goto fail;')
    add(f'    if (PyModule_AddStringConstant(m, "__host__", {_c_string(host_name)}) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "Store", (PyObject *)StoreType) < 0) goto fail;')
    if has_imports:
        add('    if (PyModule_AddObjectRef(m, "Caller", (PyObject *)CallerType) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "Instance", (PyObject *)InstanceType) < 0) goto fail;')
    if shares_tables:
        add('    if (PyModule_AddObjectRef(m, "Table", (PyObject *)TableType) < 0) goto fail;')
        add('    if (PyModule_AddObjectRef(m, "Function", (PyObject *)FunctionType) < 0) goto fail;')
    add("    return m;")
    add("fail:")
    add("    Py_DECREF(m);")
    add("    return NULL;")
    add("}")
    stub_imports = list(module.imports)  # those of a bound module are replacements the stub still shows (NotRequired)
    from ._shared import generate_shared, unsupported

    reason = unsupported(
        [(i.module, i.field, i.func) for i in imports],
        global_imports=bool(global_imports),
        memory_imports=bool(memory_imports),
        table_imports=bool(table_imports),
    )
    api_header = shared = ""
    api_model = None
    if reason is None:
        api_header, shared, api_model = generate_shared(
            last,
            prefix,
            funcs,
            memories,
            [(i.module, i.field, i.func, i.module in wasi_headers, i.host, i.slot) for i in imports],
            uses_wasi,
            len(tags),
            skipped,
            globals_,
            global_imports,
            memory_imports,
            memory_limits,
            tables,
            table_imports,
            trap_handler,
            ref_types,
            host_name,
            wasi2 and uses_wasi,
        )
    return Glue(
        "\n".join(w) + "\n",
        skipped,
        notes,
        _stub(
            last,
            funcs,
            memories,
            globals_,
            stub_imports,
            uses_wasi,
            version,
            param_names,
            bool(tags),
            shares_tables,
            tables,
            host_name,
            frozenset(wasi_modules),
            wasi2,
        ),
        (
            ("wasi2_python.h", *_p2_headers(p2_calls))
            if wasi2 and uses_wasi
            else (
                ("wasi2_python.h", *_p2_headers(p2_calls), *(wasi_headers[m] for m in wasi_modules))
                if uses_wasi
                else ()
            )
        ),
        api_header=api_header,
        shared=shared,
        shared_unsupported=reason or "",
        api_model=api_model,
        header="\n".join(h) + "\n",
        trap_handler=trap_handler,
    )


# the value types as the binary format of WebAssembly numbers them: what the link between two extensions says of a global
_TYPE_CODE: dict[ValType, int] = {"i32": 0x7F, "i64": 0x7E, "f32": 0x7D, "f64": 0x7C, "v128": 0x7B}
_PY_TYPE: dict[ValType, str] = {
    "i32": "int",
    "i64": "int",
    "f32": "float",
    "f64": "float",
    "v128": "bytes",
    "funcref": "Function | None",
}
# ... and what a parameter takes where that is more than what a result gives
_PY_PARAM: dict[ValType, str] = {"funcref": "Function | Callable[..., object] | None"}
# how a value of a type is put in a `wasmext_value` (the member of the union: i j f d, o for 16 bytes)
_VALUE_STORE: dict[ValType, str] = {
    "i32": "{dst}.as.i = {src};",
    "i64": "{dst}.as.j = {src};",
    "f32": "{dst}.as.f = {src};",
    "f64": "{dst}.as.d = {src};",
    "v128": "memcpy({dst}.as.o, &{src}, 16);",
}
# wasm2c returns several results in a `struct wasm_multi_<codes>` whose members are `<code><position>`.
_MULTI_CODE: dict[ValType, str] = {"i32": "i", "i64": "j", "f32": "f", "f64": "d", "v128": "o", "funcref": "r"}


def _ref_types(module: Module) -> list[FuncType]:
    """The function types of the module that a `Function` can call: the distinct types of its type section whose values the glue can convert."""
    seen: list[FuncType] = []
    for t in module.types:
        if _why_not(t, several_results=True, funcref=True) is None and "funcref" not in t.params and t not in seen:
            seen.append(t)
    return seen


def _emit_refcalls(hadd: Callable[[str], None], last: str, prefix: str, ref_types: list[FuncType]) -> None:
    """In the glue (no Python): the type of an element of a table among the types of this module (by the hash that `call_indirect` compares), and for each type
    `<name>_callref<k>`, the call of an element of that type as the call of an export is made: through the stack of entries, with a trap answered in `*trapped`."""
    hadd(
        "/* the type k of this module that the element of a table has (-1: none): by the hash of the type, the pointer first, as call_indirect compares them */"
    )
    hadd(f"static inline int {last}_ref_type(const wasm_rt_funcref_t *f) {{")
    hadd("    if (f == NULL || f->func == NULL || f->func_type == NULL) return -1;")
    if ref_types:
        hadd("    const char *t;")
    for k, ft in enumerate(ref_types):
        types = "".join(f", {_RT_TYPE[t]}" for t in (*ft.params, *ft.results))
        hadd(f"    t = wasm2c_{prefix}_get_func_type({len(ft.params)}, {len(ft.results)}{types});")
        hadd(f"    if (t != NULL && (t == f->func_type || memcmp(t, f->func_type, 32) == 0)) return {k};")
    hadd("    return -1;")
    hadd("}")
    hadd("")
    for k, ft in enumerate(ref_types):
        params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(ft.params))
        several = len(ft.results) > 1
        codes = "".join(_MULTI_CODE[t] for t in ft.results)
        ret = f"struct wasm_multi_{codes}" if several else _CTYPE[ft.results[0]] if ft.results else "void"
        arg_types = "".join(f", {_CTYPE[t]}" for t in ft.params)
        names = "".join(f", a{j}" for j in range(len(ft.params)))
        give = "return zero;" if ft.results else "return;"
        hadd(f"/* an element of the type {k}, {_cc(_signature(ft))} */")
        hadd(f"static inline {ret} {last}_callref{k}(const wasm_rt_funcref_t *f{params}, int *trapped) {{")
        if ft.results:
            hadd(f"    {ret} zero;")
            hadd("    memset(&zero, 0, sizeof zero);")
        hadd(f"    WASMEXT_ENTER(trap_, {{ *trapped = (int)trap_; {give} }})")
        call = f"(({ret} (*)(void *{arg_types}))f->func)(f->module_instance{names})"
        if ft.results:
            hadd(f"    {ret} r = {call};")
            hadd("    WASMEXT_LEAVE();")
            hadd("    return r;")
        else:
            hadd(f"    {call};")
            hadd("    WASMEXT_LEAVE();")
        hadd("}")
        hadd("")


def _function_type_c(last: str, ref_types: list[FuncType]) -> str:
    """The C of the type `Function` of an extension: a function in a slot of a table, which is called if its type is one of the types this module declares."""
    out: list[str] = []
    add = out.append
    add(
        "/* ---- Function: a function that a table holds (a copy of the element, and what keeps its instance alive) ---- */"
    )
    add("typedef struct {")
    add("    PyObject_HEAD")
    add("    wasm_rt_funcref_t ref;")
    add("    int type;  /* the type of this module that the function has, or -1 */")
    add("    PyObject *keeper;  /* what keeps the instance of the function alive: the table it was read from */")
    add("    PyObject *name;  /* the name of the export it is, or None */")
    add("} FunctionObject;")
    add("")
    add(
        "/* a trap of a function of another module that was called from here: its exception is this module's Trap (the tags and the program of that module are not ours) */"
    )
    add("static void raise_foreign_trap(int code) {")
    add("    if (code == (int)WASMEXT_TRAP_HOST) {")
    add(
        '        if (!PyErr_Occurred()) PyErr_SetString(TrapError, "a host function of the WebAssembly module failed");'
    )
    add("        return;")
    add("    }")
    add('    if (code == (int)WASMEXT_TRAP_CLOSED) PyErr_SetString(PyExc_ValueError, "the store is closed");')
    add("    else if (code == (int)WASMEXT_TRAP_NO_MEMORY) PyErr_NoMemory();")
    add(
        '    else if (code == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION) PyErr_SetString(TrapError, "an exception of WebAssembly that nothing caught");'
    )
    add("    else PyErr_SetString(TrapError, wasm_rt_strerror((wasm_rt_trap_t)code));")
    add("}")
    add("")
    add("static PyObject *Function_make(const wasm_rt_funcref_t *ref, PyObject *keeper) {")
    add("    FunctionObject *f = (FunctionObject *)PyType_GenericAlloc(FunctionType, 0);")
    add("    if (f == NULL) return NULL;")
    add("    f->ref = *ref;")
    add(f"    f->type = {last}_ref_type(ref);")
    add("    Py_INCREF(keeper);")
    add("    f->keeper = keeper;")
    add("    Py_INCREF(Py_None);")
    add("    f->name = Py_None;")
    add("    return (PyObject *)f;")
    add("}")
    add("")
    add("static int Function_traverse(FunctionObject *self, visitproc visit, void *arg) {")
    add("    Py_VISIT(Py_TYPE((PyObject *)self));")
    add("    Py_VISIT(self->keeper);")
    add("    Py_VISIT(self->name);")
    add("    return 0;")
    add("}")
    add("")
    add("static int Function_clear(FunctionObject *self) {")
    add("    Py_CLEAR(self->keeper);")
    add("    Py_CLEAR(self->name);")
    add("    return 0;")
    add("}")
    add("")
    add("static void Function_dealloc(FunctionObject *self) {")
    add("    PyTypeObject *tp = Py_TYPE((PyObject *)self);")
    add("    PyObject_GC_UnTrack(self);")
    add("    Function_clear(self);")
    add("    ((freefunc)PyType_GetSlot(tp, Py_tp_free))((PyObject *)self);")
    add("    Py_DECREF(tp);")
    add("}")
    add("")
    add("static PyObject *Function_call(PyObject *self, PyObject *args, PyObject *kwds) {")
    add("    FunctionObject *fn = (FunctionObject *)self;")
    add("    if (kwds != NULL && PyDict_Size(kwds) > 0) {")
    add('        PyErr_SetString(PyExc_TypeError, "a Function takes no keyword arguments");')
    add("        return NULL;")
    add("    }")
    add("    if (fn->type < 0) {")
    add(
        '        PyErr_SetString(PyExc_TypeError, "this module does not declare the type of this function, so the function cannot be called from here");'
    )
    add("        return NULL;")
    add("    }")
    add("    Py_ssize_t nargs = PyTuple_Size(args);")
    add("    switch (fn->type) {")
    for k, ft in enumerate(ref_types):
        n = len(ft.params)
        add(f"    case {k}: {{")
        add(f"        if (nargs != {n}) {{")
        add(
            f'            PyErr_Format(PyExc_TypeError, "the function takes exactly {n} argument{"" if n == 1 else "s"} (%zd given)", nargs);'
        )
        add("            return NULL;")
        add("        }")
        for j, t in enumerate(ft.params):
            add(f"        {_CTYPE[t]} a{j} = {_TO_WASM[t].format(f'PyTuple_GetItem(args, {j})')};")
        if n:
            add("        if (PyErr_Occurred()) return NULL;")
        add("        int trapped = 0;")
        call_args = "".join(f", a{j}" for j in range(n))
        call = f"{last}_callref{k}(&fn->ref{call_args}, &trapped)"
        if len(ft.results) > 1:
            codes = "".join(_MULTI_CODE[t] for t in ft.results)
            add(f"        struct wasm_multi_{codes} r = {call};")
            add("        if (trapped) { raise_foreign_trap(trapped); return NULL; }")
            fmt = "".join(_BUILD[t][0] for t in ft.results)
            members = "".join(f", {_BUILD[t][1].format(f'r.{_MULTI_CODE[t]}{i}')}" for i, t in enumerate(ft.results))
            add(f'        return Py_BuildValue("({fmt})"{members});')
        elif ft.results:
            add(f"        {_CTYPE[ft.results[0]]} r = {call};")
            add("        if (trapped) { raise_foreign_trap(trapped); return NULL; }")
            add(f"        return {_FROM_WASM[ft.results[0]].format('r')};")
        else:
            add(f"        {call};")
            add("        if (trapped) { raise_foreign_trap(trapped); return NULL; }")
            add("        Py_RETURN_NONE;")
        add("    }")
    add("    default:")
    add("        break;")
    add("    }")
    add('    PyErr_SetString(PyExc_TypeError, "this function cannot be called from here");')
    add("    return NULL;")
    add("}")
    add("")
    add("static PyObject *Function_signature(FunctionObject *self, void *closure) {")
    add("    (void)closure;")
    add("    switch (self->type) {")
    for k, ft in enumerate(ref_types):
        params = ", ".join(_c_string(t) for t in ft.params)
        results = ", ".join(_c_string(t) for t in ft.results)
        pf = "(" + "s" * len(ft.params) + ")"  # Py_BuildValue: parentheses make a tuple, also of one item
        rf = "(" + "s" * len(ft.results) + ")"
        sep = ", " if params and results else ""
        add(
            f'    case {k}: return Py_BuildValue("({pf}{rf})", {params}{sep}{results});'
            if (params or results)
            else f'    case {k}: return Py_BuildValue("((), ())");'
        )
    add("    default: Py_RETURN_NONE;")
    add("    }")
    add("}")
    add("")
    add("static PyObject *Function_name(FunctionObject *self, void *closure) {")
    add("    (void)closure;")
    add("    Py_INCREF(self->name);")
    add("    return self->name;")
    add("}")
    add("")
    add(
        "/* function.__wasmext_ref__: the record of the function with its funcref, for Table.set (and the parameters of a funcref) */"
    )
    add("static PyObject *Function_ref(PyObject *self, void *closure) {")
    add("    (void)closure;")
    add("    wasmext_export *e = (wasmext_export *)PyMem_Malloc(sizeof(wasmext_export));")
    add("    if (e == NULL) return PyErr_NoMemory();")
    add("    wasmext_function_export(e, &((FunctionObject *)self)->ref, self);")
    add("    Py_INCREF(self);")
    add("    PyObject *capsule = PyCapsule_New(e, WASMEXT_EXPORT, export_free);")
    add("    if (capsule == NULL) {")
    add("        Py_DECREF(self);")
    add("        PyMem_Free(e);")
    add("    }")
    add("    return capsule;")
    add("}")
    add("")
    add("static PyObject *Function_richcompare(PyObject *a, PyObject *b, int op) {")
    add("    if ((op != Py_EQ && op != Py_NE) || Py_TYPE(a) != Py_TYPE(b)) Py_RETURN_NOTIMPLEMENTED;")
    add("    const wasm_rt_funcref_t *x = &((FunctionObject *)a)->ref, *y = &((FunctionObject *)b)->ref;")
    add("    int same = x->func == y->func && x->module_instance == y->module_instance;")
    add("    if (same == (op == Py_EQ)) Py_RETURN_TRUE;")
    add("    Py_RETURN_FALSE;")
    add("}")
    add("")
    add("static Py_hash_t Function_hash(PyObject *self) {")
    add("    const wasm_rt_funcref_t *x = &((FunctionObject *)self)->ref;")
    add("    Py_hash_t h = (Py_hash_t)((uintptr_t)x->func ^ ((uintptr_t)x->module_instance >> 4));")
    add("    return h == -1 ? -2 : h;")
    add("}")
    add("")
    add("static PyObject *Function_repr(PyObject *self) {")
    add("    FunctionObject *f = (FunctionObject *)self;")
    add("    PyObject *signature = Function_signature(f, NULL);")
    add("    if (signature == NULL) return NULL;")
    add('    PyObject *r = PyUnicode_FromFormat("<Function %S %S>", f->name, signature);')
    add("    Py_DECREF(signature);")
    add("    return r;")
    add("}")
    add("")
    add("static PyGetSetDef Function_getset[] = {")
    add(
        '    {"signature", (getter)Function_signature, NULL, "(parameters, results) as the names of the types, or None if the type is not one of this module\'s", NULL},'
    )
    add('    {"name", (getter)Function_name, NULL, "the name of the export this function is, or None", NULL},')
    add(
        '    {"__wasmext_ref__", (getter)Function_ref, NULL, "the reference to the function, to put it in a table", NULL},'
    )
    add("    {NULL, NULL, NULL, NULL, NULL}")
    add("};")
    add("")
    add("static PyType_Slot function_slots[] = {")
    add("    {Py_tp_dealloc, Function_dealloc},")
    add("    {Py_tp_traverse, Function_traverse},")
    add("    {Py_tp_clear, Function_clear},")
    add("    {Py_tp_call, Function_call},")
    add("    {Py_tp_getset, Function_getset},")
    add("    {Py_tp_richcompare, Function_richcompare},")
    add("    {Py_tp_hash, Function_hash},")
    add("    {Py_tp_repr, Function_repr},")
    add('    {Py_tp_doc, (void *)"A function in a slot of a Table"},')
    add("    {0, NULL}")
    add("};")
    add("")
    return "\n".join(out) + "\n"


_RT_TYPE: dict[ValType, str] = {
    "i32": "WASM_RT_I32",
    "i64": "WASM_RT_I64",
    "f32": "WASM_RT_F32",
    "f64": "WASM_RT_F64",
    "v128": "WASM_RT_V128",
    "funcref": "WASM_RT_FUNCREF",
}


def _emit_funcrefs(hadd: Callable[[str], None], last: str, prefix: str, funcs: list[tuple[str, FuncType]]) -> None:
    """`<name>_glue_funcref(core, i)`: the exported function `i` as the element of a table holds it (its type, the function, the instance); what `Table.set` puts in a table."""
    hadd(
        "/* the exported function i as an element of a funcref table: its type (the one of this module, whose hash the elements of any module that has the type share), the function"
    )
    hadd(
        "   itself (called as `result f(void *instance, parameters...)`) and the instance; no tail-call variant (a call that is a tail call goes through the plain one) */"
    )
    hadd(f"static inline const wasm_rt_funcref_t *{last}_glue_funcref({last}_instance *self, int i) {{")
    hadd("    wasm_rt_funcref_t *r = &self->exp_ref[i];")
    hadd("    memset(r, 0, sizeof *r);")
    hadd("    r->module_instance = &self->inst;")
    hadd("    switch (i) {")
    for i, (exp_name, func) in enumerate(funcs):
        types = "".join(f", {_RT_TYPE[t]}" for t in (*func.params, *func.results))
        hadd(f"    case {i}:")
        hadd(f"        r->func_type = wasm2c_{prefix}_get_func_type({len(func.params)}, {len(func.results)}{types});")
        hadd(f"        r->func = (wasm_rt_function_ptr_t)(void (*)(void))w2c_{prefix}_{mangle(exp_name)};")
        hadd("        break;")
    hadd("    default:")
    hadd("        break;")
    hadd("    }")
    hadd("    return r;")
    hadd("}")
    hadd("")


_FUNCTION_HOLDER = r"""/* What stands for the export that `v` is (a new reference): `v` itself if it is one or gives one as its `__wasmext_ref__`, or, for a method of an instance of a wasmext
   module, the reference that the instance gives for its export of that name; NULL with no error if there is none. The reference of a wrapper for ctypes is an object that
   owns its record, so the caller keeps this until it is done with the capsule that as_export_ref makes of it. */
static PyObject *function_holder(PyObject *v) {
    PyObject *cap = as_export_ref(v);
    if (cap != NULL) {
        Py_DECREF(cap);
        Py_INCREF(v);
        return v;
    }
    PyObject *holder = NULL;
    PyObject *owner = PyObject_GetAttrString(v, "__self__");
    PyObject *name = owner != NULL ? PyObject_GetAttrString(v, "__name__") : NULL;
    PyObject *exports = name != NULL ? PyObject_GetAttrString(owner, "__exports__") : NULL;
    if (exports != NULL && PyDict_Check(exports)) {
        holder = PyDict_GetItemWithError(exports, name);
        Py_XINCREF(holder);
    }
    Py_XDECREF(exports);
    Py_XDECREF(name);
    Py_XDECREF(owner);
    PyErr_Clear();
    return holder;
}
"""


_TABLE_SET_GET = r"""
static int table_index(TableObject *t, PyObject *index_o, uint32_t *index) {
    if (table_u32(index_o, "index", index) < 0) return -1;
    if (*index >= t->table->size) {
        PyErr_Format(PyExc_IndexError, "table index %u is out of range: the table has %u elements", (unsigned)*index, (unsigned)t->table->size);
        return -1;
    }
    return 0;
}

static int writers_have(PyObject *writers, PyObject *who) {
    Py_ssize_t n = writers != NULL ? PyList_Size(writers) : 0;
    for (Py_ssize_t i = 0; i < n; i++)
        if (PyList_GetItem(writers, i) == who) return 1;
    return 0;
}

/* table.set(index, function): the function of an instance (instance.name, instance['name'], or None for an empty slot) goes into the slot; the table keeps the instance alive */
static PyObject *Table_set(PyObject *self, PyObject *args) {
    TableObject *t = (TableObject *)self;
    PyObject *index_o, *function;
    uint32_t index;
    if (!PyArg_ParseTuple(args, "OO:set", &index_o, &function)) return NULL;
    if (table_index(t, index_o, &index) < 0) return NULL;
    if (function == Py_None) {
        memset(&t->table->data[index], 0, sizeof(wasm_rt_funcref_t));
        Py_RETURN_NONE;
    }
    PyObject *holder = function_holder(function);
    PyObject *ref = holder != NULL ? as_export_ref(holder) : NULL;
    if (ref == NULL) {
        Py_XDECREF(holder);
        PyErr_SetString(PyExc_TypeError, "set() takes a function of an instance of a wasmext module (instance.name or instance['name']) or None");
        return NULL;
    }
    wasmext_export *e = (wasmext_export *)PyCapsule_GetPointer(ref, WASMEXT_EXPORT);
    if (e == NULL || !wasmext_export_ok(e)) {
        Py_DECREF(ref);
        Py_DECREF(holder);
        PyErr_SetString(LinkError, "the function is from an incompatible version of wasmext");
        return NULL;
    }
    const wasm_rt_funcref_t *fr = (const wasm_rt_funcref_t *)e->funcref;
    if (e->kind != WASMEXT_FUNC || fr == NULL || fr->func == NULL || fr->func_type == NULL) {
        Py_DECREF(ref);
        Py_DECREF(holder);
        PyErr_SetString(PyExc_TypeError, "set() takes a function: this export is not one, or its module does not give it for a table");
        return NULL;
    }
    if (!(e->flags & 16u)) {
        Py_DECREF(ref);
        Py_DECREF(holder);
        PyErr_SetString(PyExc_TypeError, "the module of this function does not share tables, so a trap in it could not come back to the caller through a table: only a module that shares tables (has a funcref table, or is built with share_tables) can put functions in a table");
        return NULL;
    }
    PyObject *keeper = (PyObject *)e->owner;
    if (!writers_have(table_writers(t), keeper)) {
        PyObject *r = Table_keep(self, keeper);
        if (r == NULL) {
            Py_DECREF(ref);
            Py_DECREF(holder);
            return NULL;
        }
        Py_DECREF(r);
    }
    t->table->data[index] = *fr;
    Py_DECREF(ref);
    Py_DECREF(holder);
    Py_RETURN_NONE;
}

/* the export of the instance `x` that is the function of the element `elem` (a new reference to its method), or NULL with no error */
static PyObject *table_find_function(PyObject *x, const wasm_rt_funcref_t *elem) {
    PyObject *exports = PyObject_GetAttrString(x, "__exports__");
    if (exports == NULL) {
        PyErr_Clear();
        return NULL;
    }
    PyObject *found = NULL, *key, *value;
    Py_ssize_t pos = 0;
    while (PyDict_Check(exports) && found == NULL && PyDict_Next(exports, &pos, &key, &value)) {
        PyObject *ref = as_export_ref(value);
        if (ref == NULL) continue;
        const wasmext_export *e = (const wasmext_export *)PyCapsule_GetPointer(ref, WASMEXT_EXPORT);
        const wasm_rt_funcref_t *fr = e != NULL ? (const wasm_rt_funcref_t *)e->funcref : NULL;
        int same = fr != NULL && e->kind == WASMEXT_FUNC && fr->func == elem->func && fr->module_instance == elem->module_instance;
        Py_DECREF(ref);
        if (same) {
            found = PyObject_GetAttr(x, key);
            if (found == NULL) PyErr_Clear();
        }
    }
    Py_DECREF(exports);
    return found;
}

/* table.get(index): None for an empty slot, else a Function (callable if its type is one this module declares); its name is that of the export it is, if an instance that uses the table exports it */
static PyObject *Table_get(PyObject *self, PyObject *index_o) {
    TableObject *t = (TableObject *)self;
    uint32_t index;
    if (table_index(t, index_o, &index) < 0) return NULL;
    const wasm_rt_funcref_t *elem = &t->table->data[index];
    if (elem->func == NULL) Py_RETURN_NONE;
    PyObject *function = Function_make(elem, self);
    if (function == NULL) return NULL;
    PyObject *writers = table_writers(t);
    Py_ssize_t n = writers != NULL ? PyList_Size(writers) : 0;
    for (Py_ssize_t c = t->owner != NULL ? -1 : 0; c < n; c++) {
        PyObject *x = c < 0 ? (PyObject *)t->owner : PyList_GetItem(writers, c);
        PyObject *found = table_find_function(x, elem);
        if (found == NULL) continue;
        PyObject *name = PyObject_GetAttrString(found, "__name__");
        Py_DECREF(found);
        if (name != NULL) {
            Py_DECREF(((FunctionObject *)function)->name);
            ((FunctionObject *)function)->name = name;
        } else {
            PyErr_Clear();
        }
        break;
    }
    return function;
}

"""


def _funcref_values_c(with_refs: bool) -> str:
    """The C that turns a Python value into a funcref (a parameter of an export) and a funcref into a Python value (a result): None is the null funcref, anything else is a Function."""
    keep = ""
    if with_refs:
        keep = (
            "        /* the module may keep the function (in a table, a global): its instance lives as long as this one */\n"
            "        if (!PySequence_Contains(self->refs, owner) && PyList_Append(self->refs, owner) < 0) out = null_;\n"
        )
    head = r"""static PyObject *Function_make(const wasm_rt_funcref_t *ref, PyObject *keeper);

/* a parameter of type funcref: None, a Function, or a function of an instance of a wasmext module (instance.name, instance['name']); the null funcref with an error set if it is none */
static wasm_rt_funcref_t funcref_arg(InstanceObject *self, PyObject *v) {
    wasm_rt_funcref_t null_;
    memset(&null_, 0, sizeof null_);
    (void)self;
    if (v == Py_None) return null_;
    PyObject *holder = function_holder(v);
    PyObject *ref = holder != NULL ? as_export_ref(holder) : NULL;
    if (ref == NULL) {
        Py_XDECREF(holder);
        PyErr_SetString(PyExc_TypeError, "a funcref is None, a Function, or a function of an instance of a wasmext module (instance.name or instance['name'])");
        return null_;
    }
    const wasmext_export *e = (const wasmext_export *)PyCapsule_GetPointer(ref, WASMEXT_EXPORT);
    const wasm_rt_funcref_t *fr = e != NULL ? (const wasm_rt_funcref_t *)e->funcref : NULL;
    wasm_rt_funcref_t out = null_;
    PyObject *owner = e != NULL ? (PyObject *)e->owner : NULL;
    (void)owner;
    if (e == NULL || !wasmext_export_ok(e)) {
        PyErr_SetString(LinkError, "the function is from an incompatible version of wasmext");
    } else if (e->kind != WASMEXT_FUNC || fr == NULL || fr->func == NULL || !(e->flags & 16u)) {
        PyErr_SetString(PyExc_TypeError, "a funcref takes a function of a module that shares tables (it has a funcref table, or is built with share_tables)");
    } else {
        out = *fr;
"""
    tail = r"""    }
    Py_DECREF(ref);
    Py_DECREF(holder);
    return PyErr_Occurred() ? null_ : out;
}

/* a result of type funcref: None for the null funcref, else a Function that keeps `keeper` (the instance that was called) alive */
static PyObject *funcref_result(wasm_rt_funcref_t f, PyObject *keeper) {
    if (f.func == NULL) Py_RETURN_NONE;
    return Function_make(&f, keeper);
}

"""
    return head + keep + tail


def _table_type_c(prefix: str, tables: list[str], tables_base: int) -> str:
    """The C of the type `Table` of an extension: a table of `funcref` that no module owns (`Table(initial, maximum=None)`), and the handle that `instance['name']`
    gives for a table the module exports. Both are the same object to Python and to another module: they give the capsule of the record (`__wasmext_ref__`)."""
    getters = "".join(f"    w2c_{prefix}_{mangle(n)},\n" for n in tables)
    keep = (
        "    if (t->owner != NULL) return Instance_keep((PyObject *)t->owner, other);  /* the instance keeps its importers */\n"
        if tables
        else ""
    )
    getters_c = (
        f"static wasm_rt_funcref_table_t *(*const table_getters[])(w2c_{prefix} *) = {{\n{getters}    NULL\n}};\n\n"
        "/* the handle of the table k of export_table, a table of the module of `self` */\n"
        "static PyObject *Table_of(PyObject *self, int k) {\n"
        "    TableObject *t = (TableObject *)PyType_GenericAlloc(TableType, 0);\n"
        "    if (t == NULL) return NULL;\n"
        "    Py_INCREF(self);\n"
        "    t->owner = (InstanceObject *)self;\n"
        f"    t->table = table_getters[k - {tables_base}](&t->owner->core.inst);\n"
        "    t->export_index = k;\n"
        "    return (PyObject *)t;\n"
        "}\n\n"
        if tables
        else ""
    )
    return (
        r"""/* ---- Table: a table of funcref that no module owns, or the handle of one that a module exports ---- */
static int table_u32(PyObject *v, const char *what, uint32_t *out) {
    if (!PyLong_Check(v)) {
        PyErr_Format(PyExc_TypeError, "%s must be an int", what);
        return -1;
    }
    unsigned long long n = PyLong_AsUnsignedLongLong(v);
    if (n == (unsigned long long)-1 && PyErr_Occurred()) {
        if (!PyErr_ExceptionMatches(PyExc_OverflowError)) return -1;
        PyErr_Clear();
        n = 0x100000000ull;
    }
    if (n > 0xFFFFFFFFull) {
        PyErr_Format(PyExc_ValueError, "%s must be between 0 and 4294967295", what);
        return -1;
    }
    *out = (uint32_t)n;
    return 0;
}

static PyObject *Table_new(PyTypeObject *type, PyObject *args, PyObject *kwds) {
    PyObject *initial_o, *maximum_o = Py_None;
    if (kwds != NULL && PyDict_Size(kwds) > 0) {
        PyErr_SetString(PyExc_TypeError, "Table() takes no keyword arguments");
        return NULL;
    }
    if (!PyArg_ParseTuple(args, "O|O:Table", &initial_o, &maximum_o)) return NULL;
    uint32_t initial, maximum = WASMEXT_TABLE_NO_MAXIMUM;
    if (table_u32(initial_o, "initial", &initial) < 0) return NULL;
    if (maximum_o != Py_None && table_u32(maximum_o, "maximum", &maximum) < 0) return NULL;
    if (initial > maximum) {
        PyErr_Format(PyExc_ValueError, "initial (%u) is more than maximum (%u)", (unsigned)initial, (unsigned)maximum);
        return NULL;
    }
    TableObject *self = (TableObject *)PyType_GenericAlloc(type, 0);
    if (self == NULL) return NULL;
    self->table = &self->own;
    if (wasmext_table_new(&self->own, initial, maximum)) {
        Py_DECREF(self);
        return PyErr_NoMemory();
    }
    self->writers = PyList_New(0);
    if (self->writers == NULL) {
        Py_DECREF(self);
        return NULL;
    }
    return (PyObject *)self;
}

static int Table_traverse(TableObject *self, visitproc visit, void *arg) {
    Py_VISIT(Py_TYPE((PyObject *)self));
    Py_VISIT((PyObject *)self->owner);
    Py_VISIT(self->writers);
    return 0;
}

static int Table_clear(TableObject *self) {
    Py_CLEAR(self->owner);
    Py_CLEAR(self->writers);
    return 0;
}

static void Table_dealloc(TableObject *self) {
    PyTypeObject *tp = Py_TYPE((PyObject *)self);
    PyObject_GC_UnTrack(self);
    Table_clear(self);
    if (self->table == &self->own) wasmext_table_free(&self->own);
    ((freefunc)PyType_GetSlot(tp, Py_tp_free))((PyObject *)self);
    Py_DECREF(tp);
}

static PyObject *Table_size(TableObject *self, void *closure) {
    (void)closure;
    return PyLong_FromUnsignedLong(self->table->size);
}

static PyObject *Table_maximum(TableObject *self, void *closure) {
    (void)closure;
    if (self->table->max_size == WASMEXT_TABLE_NO_MAXIMUM) Py_RETURN_NONE;
    return PyLong_FromUnsignedLong(self->table->max_size);
}

static Py_ssize_t Table_length(PyObject *self) {
    return (Py_ssize_t)((TableObject *)self)->table->size;
}

static PyObject *Table_grow(PyObject *self, PyObject *delta_o) {
    wasm_rt_funcref_table_t *table = ((TableObject *)self)->table;
    uint32_t delta;
    if (table_u32(delta_o, "delta", &delta) < 0) return NULL;
    int64_t before = wasmext_table_grow(table, delta);
    if (before < 0) {
        if (table->max_size == WASMEXT_TABLE_NO_MAXIMUM)
            PyErr_Format(PyExc_ValueError, "the table cannot grow by %u elements (it has %u): out of memory", (unsigned)delta, (unsigned)table->size);
        else
            PyErr_Format(PyExc_ValueError, "the table cannot grow by %u elements (it has %u, and its maximum is %u)", (unsigned)delta, (unsigned)table->size, (unsigned)table->max_size);
        return NULL;
    }
    return PyLong_FromLongLong(before);
}

/* table.__wasmext_ref__: the reference to this table, for the instance that imports it (see Instance_new) */
static PyObject *Table_ref(PyObject *self, void *closure) {
    (void)closure;
    TableObject *t = (TableObject *)self;
    if (t->owner != NULL) return export_ref((PyObject *)t->owner, t->export_index);
    wasmext_export *e = (wasmext_export *)PyMem_Malloc(sizeof(wasmext_export));
    if (e == NULL) return PyErr_NoMemory();
    wasmext_table_export(e, t->table, self);
    Py_INCREF(self);
    PyObject *capsule = PyCapsule_New(e, WASMEXT_EXPORT, export_free);
    if (capsule == NULL) {
        Py_DECREF(self);
        PyMem_Free(e);
    }
    return capsule;
}

/* table.__wasmext_keep__(other): `other` imported this table, so it may have put functions of its own in it: the table keeps it alive */
static PyObject *Table_keep(PyObject *self, PyObject *other) {
    TableObject *t = (TableObject *)self;
"""
        + keep
        + r"""    if (t->writers == NULL || PyList_Append(t->writers, other) < 0) return NULL;
    Py_RETURN_NONE;
}
"""
        + (
            "/* the list of the instances that may have put functions in this table: the owner of a table of a module keeps them, a table of its own does */\n"
            "static PyObject *table_writers(TableObject *t) {\n"
            + (
                "    return t->owner != NULL ? t->owner->writers : t->writers;\n"
                if tables
                else "    return t->writers;\n"
            )
            + "}\n"
        )
        + _TABLE_SET_GET
        + getters_c
        + r"""static PyMethodDef Table_methods[] = {
    {"get", (PyCFunction)Table_get, METH_O, "get(index): the Function in the slot, or None if it is empty"},
    {"set", (PyCFunction)Table_set, METH_VARARGS, "set(index, function): put the function of an instance in the slot, or None to empty it"},
    {"grow", (PyCFunction)Table_grow, METH_O, "grow(delta): add delta empty elements; the size before. ValueError if it cannot"},
    {"__wasmext_keep__", (PyCFunction)Table_keep, METH_O, "keep an instance that imported this table alive (not for you to call)"},
    {NULL, NULL, 0, NULL}
};

static PyGetSetDef Table_getset[] = {
    {"size", (getter)Table_size, NULL, "the number of elements", NULL},
    {"maximum", (getter)Table_maximum, NULL, "the most elements it can have, or None", NULL},
    {"__wasmext_ref__", (getter)Table_ref, NULL, "the reference to the table, to be given as an import", NULL},
    {NULL, NULL, NULL, NULL, NULL}
};

static PyType_Slot table_slots[] = {
    {Py_tp_new, Table_new},
    {Py_tp_dealloc, Table_dealloc},
    {Py_tp_traverse, Table_traverse},
    {Py_tp_clear, Table_clear},
    {Py_tp_methods, Table_methods},
    {Py_tp_getset, Table_getset},
    {Py_sq_length, Table_length},
    {Py_tp_doc, (void *)"Table(initial, maximum=None): a table of funcref that modules can import"},
    {0, NULL}
};

"""
    )


def _result_type(func: FuncType) -> str:
    """The annotation of what a function gives back in Python: None, a number, or a tuple of numbers."""
    if not func.results:
        return "None"
    if len(func.results) == 1:
        return _PY_TYPE[func.results[0]]
    return f"tuple[{', '.join(_PY_TYPE[t] for t in func.results)}]"


def _reserved(name: str) -> bool:
    """A name of an export that cannot be an attribute of Instance: between double underscores it would replace a special
    method or attribute of the object (`__class__`, `__init__`, `__exports__`). Such an export is still in `__exports__`."""
    return name.startswith("__") and name.endswith("__")


def _not_a_name(kind: str, name: str) -> str:
    """The comment of the stub for an export that is not written as an attribute."""
    if _reserved(name):
        return f"    # {kind}{_py_string(name)} is not an attribute (a special name of Instance): instance.__exports__[{_py_string(name)}]"
    return f"    # {kind}{_py_string(name)} is not an identifier: getattr(instance, {_py_string(name)})"


def _usable(name: str) -> bool:
    """A name that can be written as a method or an attribute in a stub."""
    return name.isidentifier() and not keyword.iskeyword(name) and not _reserved(name)


# `wasi=` as the stub shows it: the same for every module that uses WASI. A key that is absent has its default (worked out by the
# extension when it is used); None is nothing.
_WASI_STUB = [
    "class WasiP1(TypedDict):",
    "    args: NotRequired[Sequence[str] | None]",
    '    """absent: [the name of the program]. None: no arguments."""',
    "    env: NotRequired[Mapping[str, str] | None]",
    '    """absent: empty. None: empty (os.environ only if you give it)."""',
    "    stdin: NotRequired[SupportsRead[bytes] | bytes | None]",
    '    """absent: sys.stdin, when the program reads. None: an empty input."""',
    "    stdout: NotRequired[SupportsWrite[bytes] | Callable[[bytes], object] | None]",
    '    """absent: sys.stdout, when the program writes (so that a capture sees it). None: thrown away."""',
    "    stderr: NotRequired[SupportsWrite[bytes] | Callable[[bytes], object] | None]",
    '    """absent: sys.stderr, when the program writes. None: thrown away."""',
    "    preopens: NotRequired[Mapping[str, str | PathLike[str]] | None]",
    '    """absent: no files. None: no files."""',
    "    readonly: NotRequired[bool | str | Sequence[str]]",
    '    """True, a name or a list of names of the preopens that cannot be changed."""',
    "    clock: NotRequired[Callable[[int], int]]",
    '    """absent: the clocks of the system. A function (id of the clock: 0 real time, 1 monotonic, 2 process, 3 thread) -> nanoseconds."""',
    "    random: NotRequired[Callable[[int], bytes]]",
    '    """absent: the random bytes of the system. A function (how many) -> that many bytes."""',
    "",
    "Wasi = WasiP1  # the configuration of the host of this module (wasm32-wasip1)",
    "",
]


# what WASI 0.2 adds to the configuration: the network is refused unless the caller allows it (as in Wasmtime)
_WASI_P2_NETWORK_STUB = [
    "    sockets: NotRequired[bool | Callable[[str, int, str], bool] | None]",
    '    """absent or None: every bind and connect is refused. True: all are allowed. A function (ip, port, use) -> bool decides each; use is "tcp-bind", "tcp-connect", "udp-bind", "udp-connect" or "udp-outgoing"."""',
    "    tcp: NotRequired[bool | None]",
    '    """False: TCP is refused whatever sockets says. absent: sockets decides."""',
    "    udp: NotRequired[bool | None]",
    '    """False: UDP is refused whatever sockets says. absent: sockets decides."""',
    "    dns: NotRequired[bool | None]",
    '    """True: names may be resolved (wasi:sockets/ip-name-lookup). absent or None: refused."""',
    "    http: NotRequired[bool | Callable[[str, str], bool] | None]",
    '    """absent or None: every outgoing request is refused. True: all are allowed. A function (scheme, authority) -> bool decides each."""',
]


# `Table`, as the stub shows it: the same in the extension and in the wrapper for ctypes (a module that imports or exports a funcref table has it)
_TABLE_STUB = [
    "class Function:",
    '    """A function that a table holds. It is called if its type is one this module declares (signature is not None); equal to another of the same function and instance."""',
    "    @property",
    "    def name(self) -> str | None: ...",
    "    @property",
    "    def signature(self) -> tuple[tuple[str, ...], tuple[str, ...]] | None: ...",
    "    def __call__(self, *args: int | float | bytes) -> object: ...",
    "",
    "class Table:",
    '    """A table of funcref that modules import: Table(initial, maximum=None), or the table that instance[\'name\'] gives for one a module exports."""',
    "    def __init__(self, initial: int, maximum: int | None = None, /) -> None: ...",
    "    @property",
    "    def size(self) -> int: ...",
    "    @property",
    "    def maximum(self) -> int | None: ...",
    "    def __len__(self) -> int: ...",
    "    def grow(self, delta: int, /) -> int: ...",
    "    def get(self, index: int, /) -> Function | None: ...",
    "    def set(self, index: int, function: Callable[..., object] | None, /) -> None: ...",
    "",
]


def _stub(
    last: str,
    funcs: list[tuple[str, FuncType]],
    memories: list[str],
    globals_: list[tuple[str, GlobalType]],
    imports: list[Import],
    wasi: bool = False,
    version: str | None = None,
    param_names: dict[str, tuple[str | None, ...]] | None = None,
    tags: bool = False,
    table: bool = False,
    tables: list[str] | None = None,
    host: str = "wasm32",
    bound: frozenset[str] = frozenset(),
    wasi2: bool = False,
) -> str:
    """The `.pyi` for the extension module: what a type checker and an editor can know of an extension."""
    # The formatter and the linter of the project the stub lands in leave a generated file alone (the second noqa is
    # for a project that selects every rule, PGH004 among them: it objects to the first).
    lines = [
        f"# Generated by wasmext{f' {version}' if version else ''} from the WebAssembly module of {last}: do not edit.",
        "# ruff: noqa",
        "# ruff: noqa: PGH004",
        "# fmt: off",
    ]
    if wasi:
        lines += [
            "from _typeshed import SupportsRead, SupportsWrite",
            "from collections.abc import Callable, Mapping, Sequence",
            "from os import PathLike",
            "from typing import NotRequired, TypedDict",
        ]
    elif imports or table:
        lines += ["from collections.abc import Callable"] + (["from typing import TypedDict"] if imports else [])
    names = [t for t in (tables or ()) if _usable(t)]
    lines.append("from types import SimpleNamespace")
    lines.append("from typing import Literal, Protocol, overload" if names else "from typing import Literal, Protocol")
    lines += [
        "",
        f"__host__: Literal[{_py_string(host)}]",
        "",
        "class Trap(RuntimeError): ...",
        "class LinkError(Exception): ...",
    ]
    if tags:
        lines += [
            "class UncaughtException(Trap):",
            "    tag: int | None  # the index of the tag in the module; None for the tag of another module",
            "    values: tuple[int | float | bytes, ...]",
        ]
    if wasi:
        lines += [
            "class WasiTerminated(Exception): ...",
            "class WasiExit(WasiTerminated):",
            "    code: int",
            "class WasiSignal(WasiTerminated):",
            "    signal: int",
            "    name: str",
            "",
        ]
        if wasi2:
            stub = [line.replace("WasiP1", "WasiP2").replace("wasm32-wasip1", "wasm32-wasip2") for line in _WASI_STUB]
            at = stub.index("")
            stub[at:at] = _WASI_P2_NETWORK_STUB
            lines += stub
        else:
            lines += _WASI_STUB
    lines.append("")
    by_module: dict[str, list[Import]] = {}
    for imp in imports:
        by_module.setdefault(imp.module, []).append(imp)
    type_names = _imports_type_names(list(by_module))
    used: set[str] = set()  # the Protocols of fusedwasi that the types below use
    anchor = len(lines)

    def kind(module_name: str, m: Import, with_caller: bool = True) -> str:
        return _import_type(m.type, _protocol_name(module_name, m.name), used, with_caller)

    for module_name, members in by_module.items():
        type_name = type_names[module_name]
        if module_name in bound:  # the host answers these: each is a replacement, none is asked for
            items = ", ".join(f"{_py_string(m.name)}: NotRequired[{kind(module_name, m)} | None]" for m in members)
            lines.append(f"{type_name} = TypedDict('{type_name}', {{{items}}})")
        else:
            items = ", ".join(f"{_py_string(m.name)}: {kind(module_name, m)}" for m in members)
            lines.append(f"{type_name} = TypedDict('{type_name}', {{{items}}})")
    asked = any(m not in bound for m in by_module)  # a module of the caller's makes `imports` required
    if by_module:
        fields = ", ".join(
            f"{_py_string(m)}: {f'NotRequired[{type_names[m]}]' if m in bound else type_names[m]}" for m in by_module
        )
        lines += [f"Imports = TypedDict('Imports', {{{fields}}})", ""]
    if wasi and not wasi2:  # the host answers some imports: its originals, as the calls of wasmext have them
        host_names = {m: f"_Host{type_names[m]}" for m in by_module if m in bound}
        for module_name, type_name in host_names.items():
            items = ", ".join(f"{_py_string(m.name)}: {kind(module_name, m, False)}" for m in by_module[module_name])
            lines.append(f"{type_name} = TypedDict('{type_name}', {{{items}}})")
        fields = ", ".join(f"{_py_string(m)}: {t}" for m, t in host_names.items())
        lines += [
            f"_HostImports = TypedDict('_HostImports', {{{fields}}})",
            "",
            "class Host:",
            "    @property",
            "    def name(self) -> str: ...",
            "    @property",
            "    def __imports__(self) -> _HostImports: ...",
            "",
        ]
    if used:
        classes: list[str] = []
        for protocol in sorted(used):
            classes += [_protocol_text(protocol, False), _protocol_text(protocol, True)]
        lines[anchor:anchor] = [
            "# The functions that the host of WASI answers, with the names of the parameters (from fusedwasi)",
            *classes,
        ]
    if table:
        lines += _TABLE_STUB
    if imports:
        lines += [
            "class Caller:",
            "    @property",
            "    def instance(self) -> Instance: ...",
            "    @property",
            "    def store(self) -> Store: ...",
            "    @property",
            "    def memory(self) -> memoryview | None: ...",
            "",
        ]
    lines.append("class Store:")
    lines.append(
        "    def __init__(self, *, wasi: Wasi | None = None) -> None: ..."
        if wasi
        else "    def __init__(self) -> None: ..."
    )
    lines += [
        "    def close(self) -> None: ...",
        "    def __enter__(self) -> Store: ...",
        "    def __exit__(self, *exc: object) -> None: ...",
        "    @property",
        "    def closed(self) -> bool: ...",
        "    @property",
        "    def runtime(self) -> SimpleNamespace: ...",
    ]
    lines.append("")
    lines.append("class Instance:")
    lines.append(
        "    def __init__(self, store: Store, imports: Imports) -> None: ..."
        if asked
        else "    def __init__(self, store: Store, imports: Imports | None = None) -> None: ..."
        if by_module
        else "    def __init__(self, store: Store) -> None: ..."
    )
    lines += ["    @property", "    def __exports__(self) -> dict[str, object]: ..."]
    if wasi and not wasi2:
        lines += ["    @property", "    def __host__(self) -> Host: ..."]
    if names:  # the table that instance['name'] gives is a Table
        for n in names:
            lines += ["    @overload", f"    def __getitem__(self, name: Literal[{_py_string(n)}], /) -> Table: ..."]
        lines += ["    @overload", "    def __getitem__(self, name: str, /) -> object: ..."]
    else:
        lines.append("    def __getitem__(self, name: str, /) -> object: ...")
    for name, func in funcs:
        given = _param_names(func, (param_names or {}).get(name, ()))
        params = "".join(f"{given[i]}: {_PY_PARAM.get(t, _PY_TYPE[t])}, " for i, t in enumerate(func.params))
        params = f", {params}/" if func.params else ""
        result = _result_type(func)
        if _usable(name):
            lines.append(f"    def {name}(self{params}) -> {result}: ...")
        else:
            lines.append(_not_a_name("", name))
    for name, glob in globals_:
        if not _usable(name):
            lines.append(_not_a_name("global ", name))
        elif glob.mutable:
            lines.append(f"    {name}: {_PY_TYPE[glob.type]}")
        else:
            lines += ["    @property", f"    def {name}(self) -> {_PY_TYPE[glob.type]}: ..."]
    for name in memories:
        if _usable(name):
            lines += ["    @property", f"    def {name}(self) -> memoryview: ..."]
        else:
            lines.append(_not_a_name("memory ", name))
    return "\n".join(lines) + "\n"


def _imports_type_names(modules: list[str]) -> dict[str, str]:
    """The name of the `TypedDict` of each module of the imports: `_Imports_` and the name of the module with every character that is not a
    letter or a digit turned into `_` (`_Imports_wasi_snapshot_preview1`, `_Imports_wasi_io_streams_0_2_12`). It follows from the module, not from its place in
    the import section, so a stub does not change all over when a module is added. Two modules that give one name (`a-b`, `a_b`) are told apart by a
    number on the second, in the order of the section."""
    names: dict[str, str] = {}
    taken: set[str] = set()
    for module in modules:
        base = "_Imports_" + re.sub(r"[^0-9A-Za-z]+", "_", module).strip("_")
        name, n = base, 2
        while name in taken:
            name, n = f"{base}_{n}", n + 1
        taken.add(name)
        names[module] = name
    return names


def _param_names(func: FuncType, wanted: tuple[str | None, ...]) -> list[str]:
    """The names for the parameters of a method in the stub: those of the "name" section where each can be one (an identifier, not a
    keyword, not `self`, not twice), else `argN` for all of them: a stub that names some and not others reads worse than either."""
    fallback = [f"arg{i}" for i in range(len(func.params))]
    if len(wanted) != len(fallback):
        return fallback
    seen: set[str] = set()
    for n in wanted:
        if (
            n is None
            or not n.isidentifier()
            or not n.isascii()
            or keyword.iskeyword(n)
            or n == "self"
            or n.startswith("__")
            or n in seen
        ):
            return fallback
        seen.add(n)
    return [n for n in wanted if n is not None]


_P1_MODULES = (
    "wasi_snapshot_preview1",
    "wasi_unstable",
)  # the first snapshot has the names and the parameters of the second


@functools.cache
def _wasi_protocols() -> tuple[Any, Any, dict[str, str]] | None:
    """(the table of WASI 0.1, the table of WASI 0.2, the text of each Protocol by its name), all from fusedwasi; None when the fusedwasi at hand has no table of signatures."""
    try:
        from fusedwasi import get_signatures_path
        from fusedwasi.signatures import load
    except ImportError:
        return None
    blocks: dict[str, str] = {}
    for snapshot in ("p1", "p2"):
        text = (Path(get_signatures_path()) / f"wasi_{snapshot}_protocols.pyi").read_text(encoding="utf-8")
        blocks |= {
            m.group(1): m.group(0).rstrip() + "\n"
            for m in re.finditer(r"^class (\w+)\(Protocol\):\n.*?(?=^class |\Z)", text, re.DOTALL | re.MULTILINE)
        }
    return load("p1"), load("p2"), blocks


def _protocol_name(module: str, name: str) -> str | None:
    """The Protocol that fusedwasi has for an import of WASI 0.1 or 0.2, or None (another module, or no table)."""
    found = _wasi_protocols()
    if found is None:
        return None
    if module in _P1_MODULES:
        function = found[0].get("wasi_snapshot_preview1", name)
    else:  # `wasi:cli/exit@0.2.N`: the patch releases agree, the table is of the one it was made from
        function = found[1].get(re.sub(r"@0\.2\.\d+$", f"@{found[1].api.rsplit('@', 1)[-1]}", module), name)
    return function.protocol if function is not None and function.protocol in found[2] else None


def _protocol_text(protocol: str, with_caller: bool) -> str:
    """The text of a Protocol of fusedwasi; with the Caller first when asked (the class gets `WithCaller`)."""
    found = _wasi_protocols()
    assert found is not None
    text = found[2][protocol]
    if not with_caller:
        return text
    text = text.replace(f"class {protocol}(Protocol):", f"class {protocol}WithCaller(Protocol):", 1)
    if "def __call__(self)" in text:
        return text.replace("def __call__(self)", "def __call__(self, caller: Caller, /)", 1)
    return text.replace("def __call__(self, ", "def __call__(self, caller: Caller, ", 1)


def _import_type(
    thing: FuncType | GlobalType | Limits | TableType,
    protocol: str | None = None,
    used: set[str] | None = None,
    with_caller: bool = True,
) -> str:
    """The type of an import. `protocol` is the Protocol that fusedwasi has for it (named parameters), added to `used` to be written into the stub."""
    if isinstance(thing, FuncType) and protocol is not None and used is not None:
        used.add(protocol)
        return f"{protocol} | {protocol}WithCaller" if with_caller else protocol
    if isinstance(thing, FuncType):
        params = ", ".join(_PY_TYPE[t] for t in thing.params)
        result = _result_type(thing)
        # a callable may ask for the Caller first (`fn.__wasm_caller__ = True`)
        return (
            f"Callable[[{params}], {result}] | Callable[[Caller, {params}], {result}]"
            if params
            else f"Callable[[], {result}] | Callable[[Caller], {result}]"
        )
    if isinstance(
        thing, (Limits, TableType)
    ):  # a memory or a table: the export of another instance (a table: a Table of any module)
        return "object"
    return _global_import_type(thing)


def _global_import_type(glob: GlobalType) -> str:
    """What the imports may hold for a global: its value, or (the only way for a mutable one) an export of another instance."""
    return "object" if glob.mutable else f"{_PY_TYPE[glob.type]} | object"


def _py_string(text: str) -> str:
    return repr(text)
