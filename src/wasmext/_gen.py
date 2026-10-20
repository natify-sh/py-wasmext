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

import keyword
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ._wasm import FuncType, GlobalType, Import, Limits, Module, ValType

__all__ = ["GenError", "Glue", "generate", "mangle"]

_CTYPE: dict[ValType, str] = {"i32": "u32", "i64": "u64", "f32": "f32", "f64": "f64", "v128": "v128"}
# Python -> wasm value, wasm -> Python value, and the Py_BuildValue code with the cast it needs. An integer comes back
# signed, as the JavaScript API, wasmtime and wasm3 give it (and a negative or too big one is taken, wrapped).
_TO_WASM: dict[ValType, str] = {
    "i32": "(u32)PyLong_AsUnsignedLongMask({0})",
    "i64": "(u64)PyLong_AsUnsignedLongLongMask({0})",
    "f32": "(f32)PyFloat_AsDouble({0})",
    "f64": "PyFloat_AsDouble({0})",
    "v128": "wasmext_bytes_v128({0})",
}
_FROM_WASM: dict[ValType, str] = {
    "i32": "PyLong_FromLong((long)(int32_t){0})",
    "i64": "PyLong_FromLongLong((long long)(int64_t){0})",
    "f32": "PyFloat_FromDouble((double){0})",
    "f64": "PyFloat_FromDouble({0})",
    "v128": "wasmext_v128_bytes({0})",
}
_BUILD: dict[ValType, tuple[str, str]] = {
    "i32": ("l", "(long)(int32_t){0}"),
    "i64": ("L", "(long long)(int64_t){0}"),
    "f32": ("d", "(double){0}"),
    "f64": ("d", "(double){0}"),
    "v128": ("N", "wasmext_v128_bytes({0})"),
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
    ] = ()  # the headers of wasmext for WASI that the glue includes (and those they share: wasi_core.h, wasi_files_win32.h and wasi_python.h): copied beside it
    api_header: str = ""  # the public header of the C API of the shared library (<name>_api.h), no Python in it
    shared: str = ""  # the C of the shared library (<name>_shared.c); both are empty when `shared_unsupported` says why
    shared_unsupported: str = ""
    api_model: Any = (
        None  # the ApiModel of the C API (wasmext._shared), None when there is no shared library for the module
    )
    header: str = ""  # the C of the glue of the module (<name>_glue.h): typed functions, no Python; the Python layer (`source`, <name>_py.c) includes it


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


def _why_not(func: FuncType, *, several_results: bool = False) -> str | None:
    """Why the glue cannot take a function of this type, or None. A function may have several results (an exported one
    gives them back as a tuple, an imported one is to return a tuple) when `several_results` is true."""
    bad = sorted({t for t in (*func.params, *func.results) if t not in _CTYPE})
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
_WASI_HEADERS = {_WASI_PREVIEW1: "wasi_preview1.h", _WASI_UNSTABLE: "wasi_unstable.h"}
# the 46 calls of WASI 0.1 and their signatures (the witx files of the wasi-0.1 branch of WebAssembly/WASI): wasi_preview1.h has a
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
_WASI_UNSTABLE_OWN: frozenset[str] = frozenset({"fd_seek", "fd_filestat_get", "path_filestat_get", "poll_oneoff"})


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
) -> None:
    """The C that links an import to an export of another instance (a `wasmext_export`, see wasmext_glue.h), for every host that has Python or has
    not: it checks what the export is (kind, type, signature, size) and, if it fits, puts it where the module reads its import. 0 when linked;
    1 with the message in `msg` otherwise. Keeping the other instance alive is the host's business."""
    incompatible = "the export is from an incompatible version of wasmext or of the wasm2c runtime"
    for k, imp in enumerate(imports):
        where = f"{imp.module}.{imp.field}"
        hadd(f"/* the import {_cc(where)}: a function of another instance */")
        hadd(
            f"static int {last}_link_func{k}({last}_instance *core, const wasmext_export *e, char *msg, size_t cap) {{"
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
            f"static int {last}_link_global{j}({last}_instance *core, const wasmext_export *e, char *msg, size_t cap) {{"
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
            hadd(f"static void {last}_set_global{j}({last}_instance *core, {_CTYPE[g.type]} value) {{")
            hadd(f"    core->host{g.host}.g{g.slot} = value;")
            hadd(f"    core->host{g.host}.gp{g.slot} = &core->host{g.host}.g{g.slot};")
            hadd("}")
            hadd("")
    for j, m in enumerate(memory_imports):
        where = f"{m.module}.{m.field}"
        lim = m.limits
        hadd(f"/* the import {_cc(where)}: the memory of another instance */")
        hadd(
            f"static int {last}_link_memory{j}({last}_instance *core, const wasmext_export *e, char *msg, size_t cap) {{"
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


def generate(module: Module, name: str, *, version: str | None = None) -> Glue:
    """The C source of the extension module `name` (dotted, as it is imported) for the parsed `module`. `version`, the version of
    wasmext, goes into the header of the stub."""
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
    for imp in module.imports:
        if "\0" in imp.module or "\0" in imp.name:  # a C string ends at the NUL: the name would be another one
            raise GenError(f"import {imp.module!r}.{imp.name!r}: a null character in a name is not supported")
        symbol = f"w2c_{mangle(imp.module, module=True)}_{mangle(imp.name)}"
        if imp.kind == "func" and isinstance(imp.type, FuncType):
            reason = _why_not(imp.type, several_results=True)
            if reason:
                raise GenError(f"import {imp.module}.{imp.name} {reason}: not supported yet")
            if imp.module in _WASI_HEADERS:
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
            if imp.type.type not in _CTYPE:
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
        else:
            raise GenError(f"import {imp.module}.{imp.name}: an imported {imp.kind} is not supported yet")

    # exports: functions and memories; the rest is left out, and reported
    funcs: list[tuple[str, FuncType]] = []
    param_names: dict[str, tuple[str | None, ...]] = {}
    memories: list[str] = []
    memory_limits: list[Limits] = []
    globals_: list[tuple[str, GlobalType]] = []
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
            reason = _why_not(func, several_results=True)
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
            if glob.type in _CTYPE:
                globals_.append((exp.name, glob))
            else:
                skipped.append(f"global {exp.name!r} uses {glob.type}")
        else:
            skipped.append(f"{exp.kind} {exp.name!r}")

    has_imports = bool(imports or global_imports or memory_imports)
    wasi_modules = sorted({imp.module for imp in imports if imp.module in _WASI_HEADERS})
    uses_wasi = bool(wasi_modules)
    # without other imports the caller need not give any: the module gets WASI by itself
    needs_imports = any(imp.module not in _WASI_HEADERS for imp in imports) or bool(global_imports or memory_imports)
    if uses_wasi and "memory" not in memories:
        raise GenError(f"the module imports {wasi_modules[0]} but does not export its memory as 'memory'")
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
    hadd(f'#include "{last}_w2c.h"')
    hadd('#include "wasmext_glue.h"')
    for module_name in wasi_modules:
        hadd(f'#include "{_WASI_HEADERS[module_name]}"')
    tags = module.tags
    notes: list[str] = []
    for tag_index, tag in enumerate(tags):
        size = sum({"i32": 4, "f32": 4, "i64": 8, "f64": 8, "v128": 16}.get(str(t), 8) for t in tag.params)
        if size > 256:
            notes.append(
                f"exception tag {tag_index} carries {size} bytes: the runtime keeps at most 256, "
                "so its values are not decoded when it is not caught"
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
    hadd(f"#define WASMEXT_ENTER(CODE, FAIL) WASMEXT_ENTER_{reentrant}(CODE, FAIL)")
    hadd(f"#define WASMEXT_LEAVE() WASMEXT_LEAVE_{reentrant}()")
    hadd("")

    add(
        f"/* Generated by wasmext from the WebAssembly module of {last}: do not edit. The Python layer: it uses {last}_glue.h. */"
    )
    add("#define PY_SSIZE_T_CLEAN")
    add("#include <Python.h>")
    add("#include <structmember.h>")
    add("#include <string.h>")
    add(f'#include "{last}_glue.h"')
    if wasi_modules:
        add('#include "wasi_python.h"')  # the host of the core of WASI: after the glue, whose WASI headers it needs
    add("")
    add("static PyObject *TrapError;")
    add("static PyObject *LinkError;")
    if tags:
        add("static PyObject *UncaughtExceptionError;")
    if uses_wasi:
        add("static PyObject *WasiExitError, *WasiSignalError, *WasiTerminatedError;")
    add("static PyTypeObject *InstanceType;")
    if memories:
        add("static PyTypeObject *MemoryType;")
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
        # fn, user: the function to call for an import, `result f(void *user, parameters..., int *trapped)`, and its first argument
        hadd(f"struct w2c_{mangle(host, module=True)} {{ void *fn[{n}]; void *user[{n}];{values}{memory_fields} }};")
    hadd("")
    hadd("typedef struct {")
    hadd(f"    w2c_{prefix} inst;")
    hadd("    int instantiated;")
    if uses_wasi:
        hadd("    wasmext_wasi *wasi;")
    for i, host in enumerate(hosts):
        hadd(f"    struct w2c_{mangle(host, module=True)} host{i};")
    hadd(f"}} {last}_instance;")
    hadd("")
    _emit_links(hadd, last, imports, global_imports, memory_imports, hosts)
    add("typedef struct {")
    add("    PyObject_HEAD")
    add(f"    {last}_instance core;")
    add("    PyObject *weakreflist;")
    for i, host in enumerate(hosts):
        # what the Python layer holds for the imports of a module: the callables, the owners of the exports of other instances
        k = max(slots.get(host, 0), 1)
        gos = "".join(f" PyObject *go{g.slot};" for g in global_imports if hosts[g.host] == host)
        mos = "".join(f" PyObject *mo{m.slot};" for m in memory_imports if hosts[m.host] == host)
        add(f"    struct {{ PyObject *fn[{k}]; PyObject *lo[{k}];{gos}{mos} }} hold{i};")
    add("} InstanceObject;")
    add("")
    if memories:
        add("typedef struct {")
        add("    PyObject_HEAD")
        add("    InstanceObject *owner;")
        add(f"    wasm_rt_memory_t *(*get)(w2c_{prefix} *);")
        add("    int export_index;  /* its place in export_table: the reference to it is made from that */")
        add("} MemoryObject;")
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
    add("static void raise_trap(InstanceObject *self, int code) {")
    add("    (void)self;")
    add("    if (code == (int)WASMEXT_TRAP_HOST) {")
    add("        if (PyErr_Occurred()) return;")
    add(
        "        /* a function of another instance that this one calls through a link failed in its own host function: if that instance keeps the exception"
    )
    add("           (the wrapper for ctypes does, in `_pending`), it is the one to raise */")
    for i, host in enumerate(hosts):
        add(f"        for (int k = 0; k < {max(slots.get(host, 0), 1)}; k++) {{")
        add(f"            PyObject *owner = self->hold{i}.lo[k];")
        add('            PyObject *kept = owner != NULL ? PyObject_GetAttrString(owner, "_pending") : NULL;')
        add("            if (kept != NULL && kept != Py_None && PyExceptionInstance_Check(kept)) {")
        add("                PyErr_SetObject((PyObject *)Py_TYPE(kept), kept);")
        add('                PyObject_SetAttrString(owner, "_pending", Py_None);')
        add("                Py_DECREF(kept);")
        add("                return;")
        add("            }")
        add("            Py_XDECREF(kept);")
        add("            PyErr_Clear();")
        add("        }")
    add('        PyErr_SetString(TrapError, "a host function of the WebAssembly module failed");')
    add("        return;")
    add("    }")
    if uses_wasi:
        add("    if (code == (int)WASMEXT_TRAP_ENDED) {")
        add("        if (self->core.wasi != NULL && self->core.wasi->finished) wasmext_wasi_check(self->core.wasi);")
        add('        else PyErr_SetString(TrapError, "the WebAssembly program of a linked instance has ended");')
        add("        return;")
        add("    }")
    if tags:
        add("    if (code == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION) { raise_uncaught(); return; }")
    add("    if (code == (int)WASMEXT_TRAP_NO_MEMORY) PyErr_NoMemory();")
    add("    else PyErr_SetString(TrapError, wasm_rt_strerror((wasm_rt_trap_t)code));")
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
    add("static int Instance_traverse(InstanceObject *self, visitproc visit, void *arg) {")
    add("    Py_VISIT(Py_TYPE((PyObject *)self));")
    for i, host in enumerate(hosts):
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_VISIT(self->hold{i}.fn[k]);")
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_VISIT(self->hold{i}.lo[k]);")
    if uses_wasi:
        add("    if (self->core.wasi != NULL) wasmext_wasi_traverse(self->core.wasi, visit, arg);")
    for g in global_imports:
        add(f"    Py_VISIT(self->hold{g.host}.go{g.slot});")
    for m in memory_imports:
        add(f"    Py_VISIT(self->hold{m.host}.mo{m.slot});")
    add("    return 0;")
    add("}")
    add("")
    add("static int Instance_clear(InstanceObject *self) {")
    for i, host in enumerate(hosts):
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_CLEAR(self->hold{i}.fn[k]);")
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_CLEAR(self->hold{i}.lo[k]);")
    if uses_wasi:
        add("    if (self->core.wasi != NULL) wasmext_wasi_clear(self->core.wasi);")
    for g in global_imports:
        add(f"    Py_CLEAR(self->hold{g.host}.go{g.slot});")
    for m in memory_imports:
        add(f"    Py_CLEAR(self->hold{m.host}.mo{m.slot});")
    add("    return 0;")
    add("}")
    add("")
    add("static void Instance_dealloc(InstanceObject *self) {")
    add("    PyTypeObject *tp = Py_TYPE((PyObject *)self);")
    add("    PyObject_GC_UnTrack(self);")
    add("    if (self->weakreflist != NULL) PyObject_ClearWeakRefs((PyObject *)self);")
    add(f"    {last}_glue_free(&self->core);")
    add("    Instance_clear(self);")
    if uses_wasi:
        add("    wasmext_wasi_free(self->core.wasi);")
    add("    ((freefunc)PyType_GetSlot(tp, Py_tp_free))((PyObject *)self);")
    add("    Py_DECREF(tp);")
    add("}")
    add("")
    add("static PyObject *Instance_new(PyTypeObject *type, PyObject *args, PyObject *kwds) {")
    if uses_wasi:
        add('    static char *kwlist[] = {"imports", "wasi", NULL};')
        add("    PyObject *imports = Py_None, *wasi = Py_None;")
        add('    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|O$O:Instance", kwlist, &imports, &wasi)) return NULL;')
    elif has_imports:
        add('    static char *kwlist[] = {"imports", NULL};')
        add("    PyObject *imports = Py_None;")
        add('    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|O:Instance", kwlist, &imports)) return NULL;')
    else:
        add("    static char *kwlist[] = {NULL};")
        add('    if (!PyArg_ParseTupleAndKeywords(args, kwds, ":Instance", kwlist)) return NULL;')
    add("    InstanceObject *self = (InstanceObject *)PyType_GenericAlloc(type, 0);")
    add("    if (self == NULL) return NULL;")
    if uses_wasi:
        add(
            f"    self->core.wasi = wasmext_wasi_new(wasi, WasiExitError, WasiSignalError, WasiTerminatedError, {_c_string(last)});"
        )
        add("    if (self->core.wasi == NULL) { Py_DECREF(self); return NULL; }")
        add(f"    wasmext_wasi_bind(self->core.wasi, w2c_{prefix}_{mangle('memory')}(&self->core.inst));")
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
            if imp.module in _WASI_HEADERS:
                # what the caller gives wins; otherwise wasmext gives the call (a function of the WASI headers), called directly
                add("        PyObject *v = NULL;")
                add("        if (imports != Py_None) {")
                add(f"            v = lookup_import(imports, {_c_string(imp.module)}, {_c_string(imp.field)}, 0);")
                add(
                    "            if (v == NULL && !PyErr_ExceptionMatches(LinkError)) { Py_DECREF(self); return NULL; }"
                )
                add("            if (v == NULL) PyErr_Clear();")
                add("        }")
                add("        if (v == NULL) {")
                own = imp.module == _WASI_UNSTABLE and imp.field in _WASI_UNSTABLE_OWN
                add(f"            {host}.fn[{imp.slot}] = (void *)wasi_{'unstable_' if own else ''}{imp.field};")
                add(f"            {host}.user[{imp.slot}] = self->core.wasi;")
                add("        } else {")
            else:
                add(
                    f"        PyObject *v = lookup_import(imports, {_c_string(imp.module)}, {_c_string(imp.field)}, 0);"
                )
                add("        if (v == NULL) { Py_DECREF(self); return NULL; }")
            add("        PyObject *ref = NULL;")
            add(
                "        if (PyCapsule_IsValid(v, WASMEXT_EXPORT)) {  /* the reference to an export of another instance */"
            )
            add("            Py_INCREF(v);")
            add("            ref = v;")
            add("        } else {  /* a method of an instance of a wasmext extension stands for its export */")
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
            if imp.module in _WASI_HEADERS:
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
            add("        if (PyCapsule_IsValid(v, WASMEXT_EXPORT)) {  /* an export of another instance */")
            add("            wasmext_export *e = (wasmext_export *)PyCapsule_GetPointer(v, WASMEXT_EXPORT);")
            add("            char message[512];")
            add(f"            if ({last}_link_global{j}(&self->core, e, message, sizeof message)) {{")
            add("                PyErr_SetString(LinkError, message);")
            add("            } else {")
            add("                Py_INCREF((PyObject *)e->owner);")
            add(f"                {hold}.go{g.slot} = (PyObject *)e->owner;")
            add("            }")
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
        add("        PyObject *ref = NULL;")
        add("        if (PyCapsule_IsValid(v, WASMEXT_EXPORT)) {  /* the reference to an export of another instance */")
        add("            Py_INCREF(v);")
        add("            ref = v;")
        add(
            "        } else {  /* the memoryview of a memory of an instance: the object behind it gives the reference */"
        )
        add('            PyObject *obj = PyObject_GetAttrString(v, "obj");')
        add('            if (obj != NULL) ref = PyObject_GetAttrString(obj, "__wasmext_ref__");')
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
    add(f"    int trapped = {last}_glue_instantiate(&self->core);")
    add("    if (trapped) { raise_trap(self, trapped); Py_DECREF(self); return NULL; }")
    add("    return (PyObject *)self;")
    add("}")
    add("")

    if tags:
        hadd("/* the index of the tag of an exception in this module, or -1 (the tag of another module) */")
        hadd(f"static int {last}_tag_of(wasm_rt_tag_t tag) {{")
        hadd(f"    for (int i = 0; i < {last.upper()}_TAG_COUNT; i++)")
        hadd(f"        if (wasmext_tags_{prefix}[i] == tag) return i;")
        hadd("    return -1;")
        hadd("}")
        hadd("")
        hadd(
            "/* The values of an exception of the tag `tag`, from the bytes the runtime keeps (`size` of them): how many, or -1 when the bytes are not"
        )
        hadd("   the values of that tag, or -2 when a type of the tag has no decoding here (a reference). */")
        hadd(f"static int {last}_tag_values(int tag, const void *payload, uint32_t size, wasmext_value *out) {{")
        hadd("    switch (tag) {")
        for k, tag in enumerate(tags):
            types = tag.params
            hadd(f"    case {k}: {{")
            if any(t not in _CTYPE for t in types):
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
    # A WASI program is over when it calls proc_exit or proc_raise; a command (it exports _start) is over after a trap too
    is_command = any(exp_name == "_start" for exp_name, _ in funcs)
    finish_on_trap = "wasmext_wasi_finish(self->wasi, WASI_END_TRAP, 0); " if uses_wasi and is_command else ""
    hadd("/* instantiation: 0, or the code of the trap of the start function */")
    hadd(f"static int {last}_glue_instantiate({last}_instance *self) {{")
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
    if uses_wasi:
        hadd("/* the imports of WASI over the functions of the core, with the state `self->wasi` (made first): 0 */")
        hadd(f"static int {last}_wasi_bind({last}_instance *self) {{")
        for imp in imports:
            if imp.module in _WASI_HEADERS:
                own = imp.module == _WASI_UNSTABLE and imp.field in _WASI_UNSTABLE_OWN
                hadd(f"    self->host{imp.host}.fn[{imp.slot}] = (void *)wasi_{'unstable_' if own else ''}{imp.field};")
                hadd(f"    self->host{imp.host}.user[{imp.slot}] = self->wasi;")
        hadd("    return 0;")
        hadd("}")
        hadd("")
    hadd(f"static void {last}_glue_free({last}_instance *self) {{")
    hadd(f"    if (self->instantiated) wasm2c_{prefix}_free(&self->inst);")
    hadd("    self->instantiated = 0;")
    hadd("}")
    hadd("")
    for i, (exp_name, func) in enumerate(funcs):
        params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(func.params))
        several = len(func.results) > 1
        codes = "".join(_MULTI_CODE[t] for t in func.results)
        ret = f"struct wasm_multi_{codes}" if several else _CTYPE[func.results[0]] if func.results else "void"
        names = "".join(f", a{j}" for j in range(len(func.params)))
        give = "return zero;" if func.results else "return;"
        hadd(f"/* {_cc(exp_name)}{_signature(func)} */")
        hadd(f"static {ret} {last}_call{i}(void *inst{params}, int *trapped) {{")
        if func.results:
            hadd(f"    {ret} zero;")
            hadd("    memset(&zero, 0, sizeof zero);")
        hadd(f"    {last}_instance *self = ({last}_instance *)((char *)inst - offsetof({last}_instance, inst));")
        if uses_wasi:
            hadd(
                f"    if (self->wasi != NULL && self->wasi->finished) {{ *trapped = (int)WASMEXT_TRAP_ENDED; {give} }}"
            )
        else:
            hadd("    (void)self;")
        hadd(f"    WASMEXT_ENTER(trap_, {{ {finish_on_trap}*trapped = (int)trap_; {give} }})")
        call = f"w2c_{prefix}_{mangle(exp_name)}((w2c_{prefix} *)inst{names})"
        if func.results:
            hadd(f"    {ret} r = {call};")
            hadd("    WASMEXT_LEAVE();")
            hadd("    return r;")
        else:
            hadd(f"    {call};")
            hadd("    WASMEXT_LEAVE();")
        hadd("}")
        hadd("")
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
    mapped: list[tuple[str, int, int | str, int | str, str, str, str]] = []
    for i, (exp_name, glob) in enumerate(globals_):
        accessor = f"w2c_{prefix}_{mangle(exp_name)}"
        add(f"static void *export_address{i}(InstanceObject *self) {{ return (void *){accessor}(&self->core.inst); }}")
        mapped.append((exp_name, 3, _TYPE_CODE[glob.type], int(glob.mutable), f"export_address{i}", "NULL", "NULL"))
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
        mapped.append((exp_name, 0, 0, 0, "NULL", f"(void *)py_link{i}", _c_string(_signature_code(func))))
    memory_base = len(mapped)
    for i, (exp_name, lim) in enumerate(zip(memories, memory_limits, strict=True)):
        accessor = f"w2c_{prefix}_{mangle(exp_name)}"
        add(f"static void *export_memory{i}(InstanceObject *self) {{ return (void *){accessor}(&self->core.inst); }}")
        flags = f"({2 * int(lim.is64)}u | (WASM_RT_MEMCHECK_GUARD_PAGES ? 4u : 0u))"
        mapped.append((exp_name, 2, "(uint32_t)sizeof(wasm_rt_memory_t)", flags, f"export_memory{i}", "NULL", "NULL"))
    if memories:
        add("")
    add(
        "static const struct { const char *name; uint32_t kind, type, flags; void *(*address)(InstanceObject *); "
        "void *function; const char *signature; } export_table[] = {"
    )
    for exp_name, kind, type_code, flags, address, function, signature in mapped:
        add(f"    {{{_c_string(exp_name)}, {kind}, {type_code}, {flags}, {address}, {function}, {signature}}},")
    add("    {NULL, 0, 0, 0, NULL, NULL, NULL}")
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
    add("    e->version = 1;")
    add("    e->kind = export_table[k].kind;")
    add("    e->type = export_table[k].type;")
    add("    e->flags = export_table[k].flags;")
    add(
        "    e->address = export_table[k].address != NULL ? export_table[k].address((InstanceObject *)self) : export_table[k].function;"
    )
    add("    e->instance = &((InstanceObject *)self)->core.inst;")
    add("    e->signature = export_table[k].signature;")
    add("    e->runtime = WASMEXT_RUNTIME;")
    add("    Py_INCREF(self);")
    add("    e->owner = self;")
    add("    PyObject *capsule = PyCapsule_New(e, WASMEXT_EXPORT, export_free);")
    add("    if (capsule == NULL) { Py_DECREF(self); PyMem_Free(e); }")
    add("    return capsule;")
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
    add("        if (strcmp(name, export_table[k].name) == 0) return export_ref(self, k);")
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
    add("        PyObject *ref = name != NULL ? export_ref(self, k) : NULL;")
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
    add("    {NULL, NULL, 0, NULL}")
    add("};")
    add("")

    # the exported memories: an attribute that is a memoryview, held by an object that keeps the instance alive
    if memories:
        add("static int Memory_getbuffer(PyObject *self, Py_buffer *view, int flags) {")
        add("    MemoryObject *m = (MemoryObject *)self;")
        add("    wasm_rt_memory_t *mem = m->get(&m->owner->core.inst);")
        add("    if (mem->size > (uint64_t)PY_SSIZE_T_MAX) {")
        add('        PyErr_SetString(PyExc_MemoryError, "the memory is too big for a buffer");')
        add("        return -1;")
        add("    }")
        add("    return PyBuffer_FillInfo(view, self, mem->data, (Py_ssize_t)mem->size, 0, flags);")
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
    add("static PyGetSetDef Instance_getset[] = {")
    add(
        '    {"__exports__", (getter)Instance_exports, NULL, "{name: a reference to the export}: what another instance can take as an import", NULL},'
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
        add("    {Py_tp_dealloc, Memory_dealloc},")
        add("    {Py_tp_getset, Memory_getset},")
        add("    {0, NULL}")
        add("};")
        add(
            f"static PyType_Spec memory_spec = {{{_c_string(name + '.Memory')}, sizeof(MemoryObject), 0, "
            "Py_TPFLAGS_DEFAULT, memory_slots};"
        )
        add("")
    add(
        f"static struct PyModuleDef module_def = {{PyModuleDef_HEAD_INIT, {_c_string(name)}, "
        f"{_c_string('A WebAssembly module as a native extension (wasmext, wasm2c)')}, -1, NULL}};"
    )
    add("")
    add(f"PyMODINIT_FUNC PyInit_{last}(void) {{")
    add("    PyObject *m;")
    add("    wasm_rt_init();")
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
            f'    WasiTerminatedError = PyErr_NewExceptionWithDoc({_c_string(name + ".WasiTerminated")}, "The WebAssembly program is over (proc_exit, proc_raise)", PyExc_Exception, NULL);'
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
    add("    InstanceType = (PyTypeObject *)PyType_FromSpec(&instance_spec);")
    if memories:
        add("    MemoryType = (PyTypeObject *)PyType_FromSpec(&memory_spec);")
    add(
        "    if (!TrapError || !LinkError || !InstanceType"
        + (" || !WasiTerminatedError || !WasiExitError || !WasiSignalError" if uses_wasi else "")
        + (" || !MemoryType" if memories else "")
        + (" || !UncaughtExceptionError" if tags else "")
        + ") goto fail;"
    )
    if uses_wasi:
        add('    if (PyModule_AddObjectRef(m, "WasiTerminated", WasiTerminatedError) < 0) goto fail;')
        add('    if (PyModule_AddObjectRef(m, "WasiExit", WasiExitError) < 0) goto fail;')
        add('    if (PyModule_AddObjectRef(m, "WasiSignal", WasiSignalError) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "Trap", TrapError) < 0) goto fail;')
    if tags:
        add('    if (PyModule_AddObjectRef(m, "UncaughtException", UncaughtExceptionError) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "LinkError", LinkError) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "Instance", (PyObject *)InstanceType) < 0) goto fail;')
    add("    return m;")
    add("fail:")
    add("    Py_DECREF(m);")
    add("    return NULL;")
    add("}")
    stub_imports = [imp for imp in module.imports if imp.module not in _WASI_HEADERS]
    from ._shared import generate_shared, unsupported

    reason = unsupported(
        [(i.module, i.field, i.func) for i in imports],
        global_imports=bool(global_imports),
        memory_imports=bool(memory_imports),
    )
    api_header = shared = ""
    api_model = None
    if reason is None:
        api_header, shared, api_model = generate_shared(
            last,
            prefix,
            funcs,
            memories,
            [(i.module, i.field, i.func, i.module in _WASI_HEADERS, i.host, i.slot) for i in imports],
            uses_wasi,
            len(tags),
            skipped,
            globals_,
            global_imports,
            memory_imports,
            memory_limits,
        )
    return Glue(
        "\n".join(w) + "\n",
        skipped,
        notes,
        _stub(last, funcs, memories, globals_, stub_imports, uses_wasi, version, param_names, bool(tags)),
        tuple(_WASI_HEADERS[m] for m in wasi_modules),
        api_header=api_header,
        shared=shared,
        shared_unsupported=reason or "",
        api_model=api_model,
        header="\n".join(h) + "\n",
    )


# the value types as the binary format of WebAssembly numbers them: what the link between two extensions says of a global
_TYPE_CODE: dict[ValType, int] = {"i32": 0x7F, "i64": 0x7E, "f32": 0x7D, "f64": 0x7C, "v128": 0x7B}
_PY_TYPE: dict[ValType, str] = {"i32": "int", "i64": "int", "f32": "float", "f64": "float", "v128": "bytes"}
# how a value of a type is put in a `wasmext_value` (the member of the union: i j f d, o for 16 bytes)
_VALUE_STORE: dict[ValType, str] = {
    "i32": "{dst}.as.i = {src};",
    "i64": "{dst}.as.j = {src};",
    "f32": "{dst}.as.f = {src};",
    "f64": "{dst}.as.d = {src};",
    "v128": "memcpy({dst}.as.o, &{src}, 16);",
}
# wasm2c returns several results in a `struct wasm_multi_<codes>` whose members are `<code><position>`.
_MULTI_CODE: dict[ValType, str] = {"i32": "i", "i64": "j", "f32": "f", "f64": "d", "v128": "o"}


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


def _callable_type(func: FuncType) -> str:
    params = ", ".join(_PY_TYPE[t] for t in func.params)
    result = _result_type(func)
    return f"Callable[[{params}], {result}]"


# `wasi=` as the stub shows it: the same for every module that uses WASI. A key that is absent has its default (worked out by the
# extension when it is used); None is nothing.
_WASI_STUB = [
    "class Wasi(TypedDict):",
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
    elif imports:
        lines += ["from collections.abc import Callable", "from typing import TypedDict"]
    lines += ["", "class Trap(RuntimeError): ...", "class LinkError(Exception): ..."]
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
        lines += _WASI_STUB
    lines.append("")
    by_module: dict[str, list[Import]] = {}
    for imp in imports:
        by_module.setdefault(imp.module, []).append(imp)
    for i, (_module, members) in enumerate(by_module.items()):
        items = ", ".join(
            f"{_py_string(m.name)}: {_import_type(m.type)}"
            for m in members
            if isinstance(m.type, (FuncType, GlobalType, Limits))
        )
        lines.append(f"_Imports{i} = TypedDict('_Imports{i}', {{{items}}})")
    if by_module:
        fields = ", ".join(f"{_py_string(m)}: _Imports{i}" for i, m in enumerate(by_module))
        lines += [f"Imports = TypedDict('Imports', {{{fields}}})", ""]
    lines.append("class Instance:")
    if wasi:
        required = "imports: Imports, " if by_module else "imports: None = None, "
        lines.append(f"    def __init__(self, {required}*, wasi: Wasi | None = None) -> None: ...")
    else:
        lines.append(
            "    def __init__(self, imports: Imports) -> None: ..."
            if by_module
            else "    def __init__(self) -> None: ..."
        )
    lines += [
        "    @property",
        "    def __exports__(self) -> dict[str, object]: ...",
        "    def __getitem__(self, name: str, /) -> object: ...",
    ]
    for name, func in funcs:
        given = _param_names(func, (param_names or {}).get(name, ()))
        params = "".join(f"{given[i]}: {_PY_TYPE[t]}, " for i, t in enumerate(func.params))
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


def _import_type(thing: FuncType | GlobalType | Limits) -> str:
    if isinstance(thing, FuncType):
        return _callable_type(thing)
    if isinstance(thing, Limits):  # a memory: the memory of another instance
        return "object"
    return _global_import_type(thing)


def _global_import_type(glob: GlobalType) -> str:
    """What the imports may hold for a global: its value, or (the only way for a mutable one) an export of another instance."""
    return "object" if glob.mutable else f"{_PY_TYPE[glob.type]} | object"


def _py_string(text: str) -> str:
    return repr(text)
