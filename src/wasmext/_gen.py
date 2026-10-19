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
from dataclasses import dataclass, field

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
    stub: str = ""  # the .pyi of the extension module
    wasi_headers: tuple[
        str, ...
    ] = ()  # the headers of wasmext for WASI that the glue includes (and wasi_common.h): copied beside it


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
    w: list[str] = []
    add = w.append

    add(f"/* Generated by wasmext from the WebAssembly module of {last}: do not edit. */")
    add("#define PY_SSIZE_T_CLEAN")
    add("#include <Python.h>")
    add("#include <structmember.h>")
    add("#include <string.h>")
    add(f'#include "{last}_w2c.h"')
    add('#include "wasm-rt-impl.h"')
    add('#include "wasm-rt-exceptions.h"')
    for module_name in wasi_modules:
        add(f'#include "{_WASI_HEADERS[module_name]}"')
    add("#ifndef _WIN32")
    add("#include <signal.h>")
    add("#endif")
    add("")
    add("/* the trap code of a Python exception that unwinds the WebAssembly frames: the exception is already set */")
    add("#define PY_ERROR_TRAP ((wasm_rt_trap_t)0x7000)")
    add("")
    add("static PyObject *TrapError;")
    add("static PyObject *LinkError;")
    if uses_wasi:
        add("static PyObject *WasiExitError, *WasiSignalError, *WasiTerminatedError;")
    add("static PyTypeObject *InstanceType;")
    if memories:
        add("static PyTypeObject *MemoryType;")
    add("")
    add("/* the wasmext copy of the runtime traps with this when a memory cannot be allocated */")
    add("#define PY_NO_MEMORY_TRAP ((wasm_rt_trap_t)0x7001)")
    add("")
    add("static void set_trap_error(wasm_rt_trap_t code) {")
    add("    if (code == PY_NO_MEMORY_TRAP) PyErr_NoMemory();")
    add("    else if (code != PY_ERROR_TRAP) PyErr_SetString(TrapError, wasm_rt_strerror(code));")
    add("}")
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
    # what another extension reads of an export of this one: a capsule over this struct. The contract between the extensions
    # is private to wasmext and versioned; a reader checks `version` and `size` before it reads a field.
    add('#define WASMEXT_EXPORT "wasmext.export.v1"')
    add(
        "/* A fingerprint of the layout of the structs of the wasm2c runtime that are shared between extensions (a memory, a table): an"
    )
    add(
        "   extension built with another runtime reads another layout, and its exports must not be linked. (Overridable, for the tests.) */"
    )
    add("#ifndef WASMEXT_RUNTIME")
    add(
        "#define WASMEXT_RUNTIME ((uint32_t)(sizeof(wasm_rt_memory_t) * 1000003u ^ offsetof(wasm_rt_memory_t, data) * 8191u ^ \\"
    )
    add(
        "    offsetof(wasm_rt_memory_t, pages) * 131u ^ offsetof(wasm_rt_memory_t, size) * 17u ^ offsetof(wasm_rt_memory_t, is64) * 7u ^ \\"
    )
    add("    sizeof(wasm_rt_funcref_table_t) * 65537u))")
    add("#endif")
    add("enum { WASMEXT_FUNC = 0, WASMEXT_TABLE = 1, WASMEXT_MEMORY = 2, WASMEXT_GLOBAL = 3 };")
    add("typedef struct {")
    add("    uint32_t size;      /* sizeof of this struct for the extension that made it */")
    add("    uint32_t version;   /* 1 */")
    add("    uint32_t kind;      /* WASMEXT_FUNC, ... */")
    add(
        "    uint32_t type;      /* a global: its value type as numbered in the binary format (0x7F is i32); a memory: sizeof(wasm_rt_memory_t) */"
    )
    add(
        "    uint32_t flags;     /* bit 0: the global is mutable; bit 1: the memory is 64-bit; bit 2: it is checked with guard pages */"
    )
    add("    PyObject *owner;    /* the instance: a reader that keeps the address keeps a reference to it */")
    add(
        "    void *address;      /* a global: the pointer to its value; a memory: the wasm_rt_memory_t; a function: the function to call (see below) */"
    )
    add("    void *instance;     /* a function: the first argument of that call */")
    add("    const char *signature;  /* a function: the parameters, '>', the results (i j f d o) */")
    add(
        "    uint32_t runtime;   /* WASMEXT_RUNTIME of the extension that made it: the layout of the structs of the wasm2c runtime */"
    )
    add("} wasmext_export;")
    add(
        "/* a function is called as `result f(void *instance, parameters..., int *trapped)`: a trap is reported through `trapped`,"
    )
    add(
        "   with the exception set in Python, and the result is then undefined; it catches the traps of its own module. */"
    )
    add("")
    # what a call of WebAssembly code must do about the jump buffer
    add(
        "/* a trap from a signal handler (an access past the guard pages) leaves the signal blocked: sigsetjmp saves no mask, for speed */"
    )
    add("static void unblock_fault_signals(void) {")
    add("#ifndef _WIN32")
    add("    sigset_t set_;")
    add("    sigemptyset(&set_);")
    add("    sigaddset(&set_, SIGSEGV);")
    add("    sigaddset(&set_, SIGBUS);")
    add("    pthread_sigmask(SIG_UNBLOCK, &set_, NULL);")
    add("#endif")
    add("}")
    add("")
    add("/* the unwind target is where a `throw` that no `try` of the module catches goes: the trap of this call */")
    add("#define SET_UP_TRAP_() \\")
    add("    (WASM_RT_SAVE_STACK_DEPTH(), wasm_rt_set_unwind_target(&g_wasm_rt_jmp_buf), \\")
    add("     (wasm_rt_trap_t)wasm_rt_try(g_wasm_rt_jmp_buf))")
    if has_imports:
        add(
            "/* a Python callable can call back into the module: the buffer of the outer call is put back afterwards */"
        )
        add("#define ENTER_WASM(FAIL) \\")
        add("    wasm_rt_jmp_buf saved_jmp_; \\")
        add("    memcpy(&saved_jmp_, &g_wasm_rt_jmp_buf, sizeof saved_jmp_); \\")
        add("    wasm_rt_trap_t trap_ = SET_UP_TRAP_(); \\")
        add("    if (trap_) { \\")
        add("        unblock_fault_signals(); \\")
        add("        memcpy(&g_wasm_rt_jmp_buf, &saved_jmp_, sizeof saved_jmp_); \\")
        add("        set_trap_error(trap_); \\")
        add("        FAIL; \\")
        add("    }")
        add("#define LEAVE_WASM() memcpy(&g_wasm_rt_jmp_buf, &saved_jmp_, sizeof saved_jmp_)")
    else:
        add("#define ENTER_WASM(FAIL) \\")
        add("    wasm_rt_trap_t trap_ = SET_UP_TRAP_(); \\")
        add("    if (trap_) { unblock_fault_signals(); set_trap_error(trap_); FAIL; }")
        add("#define LEAVE_WASM() ((void)0)")
    add("")

    for i, host in enumerate(hosts):
        add(f"/* the callables and the values of the imports of module {_c_string(host)} */")
        # g: the value of a global the caller gave as a number; gp: where the runtime reads it (g, or the global of another
        # instance); go: that instance, kept alive
        values = "".join(
            f" {_CTYPE[g.type]} g{g.slot}; {_CTYPE[g.type]} *gp{g.slot}; PyObject *go{g.slot};"
            for g in global_imports
            if hosts[g.host] == host
        )
        n = max(slots.get(host, 0), 1)
        memory_fields = "".join(
            f" wasm_rt_memory_t *mp{m.slot}; PyObject *mo{m.slot};" for m in memory_imports if hosts[m.host] == host
        )
        # fn: the Python callables; lf, li, lo: the function of another instance to call instead, its instance, and the owner
        add(
            f"struct w2c_{mangle(host, module=True)} {{ PyObject *fn[{n}]; void *lf[{n}]; void *li[{n}]; PyObject *lo[{n}];{values}{memory_fields} }};"
        )
    add("")
    add("typedef struct {")
    add("    PyObject_HEAD")
    add(f"    w2c_{prefix} inst;")
    add("    int instantiated;")
    add("    PyObject *weakreflist;")
    if uses_wasi:
        add("    wasmext_wasi *wasi;")
    for i, host in enumerate(hosts):
        add(f"    struct w2c_{mangle(host, module=True)} host{i};")
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

    # the globals the module imports: the runtime asks for a pointer to the value
    for g in global_imports:
        mod_struct = f"struct w2c_{mangle(g.module, module=True)}"
        add(f"{_CTYPE[g.type]} *{g.symbol}({mod_struct} *h) {{ return h->gp{g.slot}; }}")
    if global_imports:
        add("")
    for m in memory_imports:
        mod_struct = f"struct w2c_{mangle(m.module, module=True)}"
        add(f"wasm_rt_memory_t *{m.symbol}({mod_struct} *h) {{ return h->mp{m.slot}; }}")
    if memory_imports:
        add("")

    # the functions the module imports, implemented over the callables
    for imp in imports:
        func = imp.func
        params = "".join(f", {_CTYPE[t]} a{i}" for i, t in enumerate(func.params))
        several = len(func.results) > 1
        codes = "".join(_MULTI_CODE[t] for t in func.results)
        ret = f"struct wasm_multi_{codes}" if several else _CTYPE[func.results[0]] if func.results else "void"
        mod_struct = f"struct w2c_{mangle(imp.module, module=True)}"
        add(f"{ret} {imp.symbol}({mod_struct} *h{params}) {{")
        fmt = "".join(_BUILD[t][0] for t in func.params)
        casts = "".join(f", {_BUILD[t][1].format(f'a{i}')}" for i, t in enumerate(func.params))
        arg_types = "".join(f", {_CTYPE[t]}" for t in func.params)
        arg_names = "".join(f", a{i}" for i in range(len(func.params)))
        add(f"    if (h->lf[{imp.slot}] != NULL) {{  /* a function of another instance: called directly */")
        add("        int trapped = 0;")
        call = f"(({ret} (*)(void *{arg_types}, int *))h->lf[{imp.slot}])(h->li[{imp.slot}]{arg_names}, &trapped)"
        if func.results:
            add(f"        {ret} r_ = {call};")
            add("        if (trapped) wasm_rt_trap(PY_ERROR_TRAP);")
            add("        return r_;")
        else:
            add(f"        {call};")
            add("        if (trapped) wasm_rt_trap(PY_ERROR_TRAP);")
            add("        return;")
        add("    }")
        add(f'    PyObject *r = PyObject_CallFunction(h->fn[{imp.slot}], "{fmt}"{casts});')
        add("    if (r == NULL) wasm_rt_trap(PY_ERROR_TRAP);")
        if several:
            n = len(func.results)
            what = _c_string(f"{imp.module}.{imp.field}() must return a tuple of {n} values")
            add(f"    {ret} v = {{0}};")
            add(f"    if (!PyTuple_Check(r) || PyTuple_Size(r) != {n}) {{")
            add("        Py_DECREF(r);")
            add(f"        PyErr_SetString(PyExc_TypeError, {what});")
            add("        wasm_rt_trap(PY_ERROR_TRAP);")
            add("    }")
            for k, rt in enumerate(func.results):
                add(f"    v.{_MULTI_CODE[rt]}{k} = {_TO_WASM[rt].format(f'PyTuple_GetItem(r, {k})')};")
            add("    Py_DECREF(r);")
            add("    if (PyErr_Occurred()) wasm_rt_trap(PY_ERROR_TRAP);")
            add("    return v;")
        elif func.results:
            rt = func.results[0]
            add(f"    {ret} v = {_TO_WASM[rt].format('r')};")
            add("    Py_DECREF(r);")
            add("    if (PyErr_Occurred()) wasm_rt_trap(PY_ERROR_TRAP);")
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
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_VISIT(self->host{i}.fn[k]);")
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_VISIT(self->host{i}.lo[k]);")
    if uses_wasi:
        add("    if (self->wasi != NULL) wasmext_wasi_traverse(self->wasi, visit, arg);")
    for g in global_imports:
        add(f"    Py_VISIT(self->host{g.host}.go{g.slot});")
    for m in memory_imports:
        add(f"    Py_VISIT(self->host{m.host}.mo{m.slot});")
    add("    return 0;")
    add("}")
    add("")
    add("static int Instance_clear(InstanceObject *self) {")
    for i, host in enumerate(hosts):
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_CLEAR(self->host{i}.fn[k]);")
        add(f"    for (int k = 0; k < {slots.get(host, 0)}; k++) Py_CLEAR(self->host{i}.lo[k]);")
    if uses_wasi:
        add("    if (self->wasi != NULL) wasmext_wasi_clear(self->wasi);")
    for g in global_imports:
        add(f"    Py_CLEAR(self->host{g.host}.go{g.slot});")
    for m in memory_imports:
        add(f"    Py_CLEAR(self->host{m.host}.mo{m.slot});")
    add("    return 0;")
    add("}")
    add("")
    add("static void Instance_dealloc(InstanceObject *self) {")
    add("    PyTypeObject *tp = Py_TYPE((PyObject *)self);")
    add("    PyObject_GC_UnTrack(self);")
    add("    if (self->weakreflist != NULL) PyObject_ClearWeakRefs((PyObject *)self);")
    add(f"    if (self->instantiated) wasm2c_{prefix}_free(&self->inst);")
    add("    Instance_clear(self);")
    if uses_wasi:
        add("    wasmext_wasi_free(self->wasi);")
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
            f"    self->wasi = wasmext_wasi_new(wasi, WasiExitError, WasiSignalError, WasiTerminatedError, {_c_string(last)});"
        )
        add("    if (self->wasi == NULL) { Py_DECREF(self); return NULL; }")
        add(f"    wasmext_wasi_bind(self->wasi, w2c_{prefix}_{mangle('memory')}(&self->inst));")
    if has_imports:
        if needs_imports:
            add("    if (imports == Py_None) {")
            add(
                '        PyErr_SetString(LinkError, "the module has imports: pass imports={module: {name: callable or value}}");'
            )
            add("        Py_DECREF(self);")
            add("        return NULL;")
            add("    }")
        for imp in imports:
            where = f"{imp.module}.{imp.field}"
            host = f"self->host{imp.host}"
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
                add(f"            {host}.lf[{imp.slot}] = (void *)wasi_{'unstable_' if own else ''}{imp.field};")
                add(f"            {host}.li[{imp.slot}] = self->wasi;")
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
            add(
                "            if (e->version != 1 || e->size < sizeof(wasmext_export) || e->runtime != WASMEXT_RUNTIME) {"
            )
            add(
                f"                PyErr_SetString(LinkError, {_c_string(f'import {where}: the export is from an incompatible version of wasmext or of the wasm2c runtime')});"
            )
            add("            } else if (e->kind != WASMEXT_FUNC) {")
            add(
                f"                PyErr_SetString(LinkError, {_c_string(f'import {where} is a function: the export given is not')});"
            )
            add(f"            }} else if (strcmp(e->signature, {_c_string(signature)}) != 0) {{")
            add(
                f'                PyErr_Format(LinkError, "import {where} is a function {_signature_code(imp.func)}: the export given is another one (%s)", e->signature);'
            )
            add("            } else {")
            add(f"                {host}.lf[{imp.slot}] = e->address;")
            add(f"                {host}.li[{imp.slot}] = e->instance;")
            add("                Py_INCREF(e->owner);")
            add(f"                {host}.lo[{imp.slot}] = e->owner;")
            add("            }")
            add("            Py_DECREF(ref);")
            add("            Py_DECREF(v);")
            add("            if (PyErr_Occurred()) { Py_DECREF(self); return NULL; }")
            add("        } else if (PyCallable_Check(v)) {")
            add("            Py_XDECREF(ref);")
            add(f"            {host}.fn[{imp.slot}] = v;")
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
        for g in global_imports:
            if g.type == "v128":
                number, what = "wasmext_is_v128(v)", "16 bytes"
            else:
                number = "PyLong_Check(v)" if g.type in ("i32", "i64") else "(PyLong_Check(v) || PyFloat_Check(v))"
                what = "an int" if g.type in ("i32", "i64") else "a number"
            where = f"{g.module}.{g.field}"
            host = f"self->host{g.host}"
            add("    {")
            add(f"        PyObject *v = lookup_import(imports, {_c_string(g.module)}, {_c_string(g.field)}, 0);")
            add("        if (v == NULL) { Py_DECREF(self); return NULL; }")
            add("        if (PyCapsule_IsValid(v, WASMEXT_EXPORT)) {  /* an export of another instance */")
            add("            wasmext_export *e = (wasmext_export *)PyCapsule_GetPointer(v, WASMEXT_EXPORT);")
            add(
                "            if (e->version != 1 || e->size < sizeof(wasmext_export) || e->runtime != WASMEXT_RUNTIME) {"
            )
            add(
                f"                PyErr_SetString(LinkError, {_c_string(f'import {where}: the export is from an incompatible version of wasmext or of the wasm2c runtime')});"
            )
            add("            } else if (e->kind != WASMEXT_GLOBAL) {")
            add(
                f"                PyErr_SetString(LinkError, {_c_string(f'import {where} is a global: the export given is not')});"
            )
            add(f"            }} else if (e->type != {_TYPE_CODE[g.type]} || (e->flags & 1) != {int(g.mutable)}) {{")
            expected = f"{'mutable ' if g.mutable else ''}{g.type}"
            add(
                f"                PyErr_SetString(LinkError, {_c_string(f'import {where} is a {expected} global: the export given has another type or the other mutability')});"
            )
            add("            } else {")
            add(f"                {host}.gp{g.slot} = ({_CTYPE[g.type]} *)e->address;")
            add("                Py_INCREF(e->owner);")
            add(f"                {host}.go{g.slot} = e->owner;")
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
                add(f"            {host}.g{g.slot} = {_TO_WASM[g.type].format('v')};")
                add(f"            {host}.gp{g.slot} = &{host}.g{g.slot};")
                add("            Py_DECREF(v);")
                add("        }")
            add("    }")
    for m in memory_imports:
        where = f"{m.module}.{m.field}"
        host = f"self->host{m.host}"
        lim = m.limits
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
        add("            wasm_rt_memory_t *mem = (wasm_rt_memory_t *)e->address;")
        add("            if (e->version != 1 || e->size < sizeof(wasmext_export) || e->runtime != WASMEXT_RUNTIME) {")
        add(
            f"                PyErr_SetString(LinkError, {_c_string(f'import {where}: the export is from an incompatible version of wasmext or of the wasm2c runtime')});"
        )
        add("            } else if (e->kind != WASMEXT_MEMORY) {")
        add(
            f"                PyErr_SetString(LinkError, {_c_string(f'import {where} is a memory: the export given is not')});"
        )
        add("            } else if (e->type != sizeof(wasm_rt_memory_t)) {")
        add(
            f"                PyErr_SetString(LinkError, {_c_string(f'import {where}: the memory is from an incompatible runtime of wasm2c')});"
        )
        add(f"            }} else if (((e->flags >> 1) & 1) != {int(lim.is64)}) {{")
        add(
            f"                PyErr_SetString(LinkError, {_c_string(f'import {where} is a {chr(54)}{chr(52)}-bit memory the other way: memory64 differs')});"
        )
        add("            } else if (((e->flags >> 2) & 1) != (WASM_RT_MEMCHECK_GUARD_PAGES ? 1 : 0)) {")
        add(
            f"                PyErr_SetString(LinkError, {_c_string(f'import {where}: one module is built with guard pages and the other without (--no-guard-pages)')});"
        )
        add(f"            }} else if (mem->pages < {lim.min}ULL) {{")
        add(
            f'                PyErr_Format(LinkError, "import {where}: the memory has %llu pages, the module needs at least {lim.min}", (unsigned long long)mem->pages);'
        )
        if lim.max is not None:
            add(f"            }} else if (mem->max_pages > {lim.max}ULL) {{")
            add(
                f'                PyErr_Format(LinkError, "import {where}: the memory may grow to %llu pages, the module allows {lim.max}", (unsigned long long)mem->max_pages);'
            )
        add("            } else {")
        add(f"                {host}.mp{m.slot} = mem;")
        add("                Py_INCREF(e->owner);")
        add(f"                {host}.mo{m.slot} = e->owner;")
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
    add("    ENTER_WASM({ Py_DECREF(self); return NULL; })")
    host_args = "".join(f", &self->host{i}" for i in range(len(hosts)))
    add(f"    wasm2c_{prefix}_instantiate(&self->inst{host_args});")
    add("    LEAVE_WASM();")
    add("    self->instantiated = 1;")
    add("    return (PyObject *)self;")
    add("}")
    add("")

    # A WASI program is over when it calls proc_exit or proc_raise; a command (it exports _start) is over after a trap too
    is_command = any(exp_name == "_start" for exp_name, _ in funcs)
    fail_trap = "return NULL"
    link_self = ""
    link_fail = ""
    if uses_wasi:
        if is_command:
            fail_trap = "{ wasmext_wasi_finish(self->wasi, WASI_END_TRAP, 0); return NULL; }"
            link_fail = "wasmext_wasi_finish(self->wasi, WASI_END_TRAP, 0);"
        link_self = "InstanceObject *self = (InstanceObject *)((char *)inst - offsetof(InstanceObject, inst));"

    # the exported functions
    for i, (exp_name, func) in enumerate(funcs):
        n = len(func.params)
        add(f"/* {exp_name}{_signature(func)} */")
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
        if uses_wasi:
            add("    if (wasmext_wasi_check(self->wasi) < 0) return NULL;")
        add(f"    ENTER_WASM({fail_trap})")
        call_args = "".join(f", a{j}" for j in range(n))
        call = f"w2c_{prefix}_{mangle(exp_name)}(&self->inst{call_args})"
        if len(func.results) > 1:
            codes = "".join(_MULTI_CODE[t] for t in func.results)
            add(f"    struct wasm_multi_{codes} r = {call};")
            add("    LEAVE_WASM();")
            fmt = "".join(_BUILD[t][0] for t in func.results)
            members = "".join(f", {_BUILD[t][1].format(f'r.{_MULTI_CODE[t]}{k}')}" for k, t in enumerate(func.results))
            add(f'    return Py_BuildValue("({fmt})"{members});')
        elif func.results:
            add(f"    {_CTYPE[func.results[0]]} r = {call};")
            add("    LEAVE_WASM();")
            add(f"    return {_FROM_WASM[func.results[0]].format('r')};")
        else:
            add(f"    {call};")
            add("    LEAVE_WASM();")
            add("    Py_RETURN_NONE;")
        add("}")
        add("")
    # instance['name'] and instance.__exports__: the references to the exports (capsules that another extension reads)
    # name, kind, type, flags, the getter of the address of a global, the function to call, its signature
    mapped: list[tuple[str, int, int | str, int | str, str, str, str]] = []
    for i, (exp_name, glob) in enumerate(globals_):
        accessor = f"w2c_{prefix}_{mangle(exp_name)}"
        add(f"static void *export_address{i}(InstanceObject *self) {{ return (void *){accessor}(&self->inst); }}")
        mapped.append((exp_name, 3, _TYPE_CODE[glob.type], int(glob.mutable), f"export_address{i}", "NULL", "NULL"))
    if globals_:
        add("")
    for i, (exp_name, func) in enumerate(funcs):
        # what another extension calls: it traps inside this extension (its own jump buffer), and says so through `trapped`
        params = "".join(f", {_CTYPE[t]} a{j}" for j, t in enumerate(func.params))
        several = len(func.results) > 1
        codes = "".join(_MULTI_CODE[t] for t in func.results)
        ret = f"struct wasm_multi_{codes}" if several else _CTYPE[func.results[0]] if func.results else "void"
        names = "".join(f", a{j}" for j in range(len(func.params)))
        add(f"static {ret} link_call{i}(void *inst{params}, int *trapped) {{")
        if func.results:
            add(f"    {ret} zero;")
            add("    memset(&zero, 0, sizeof zero);")
            add(f"    {link_self}")
            add("    if (wasmext_wasi_check(self->wasi) < 0) { *trapped = 1; return zero; }" if uses_wasi else "")
            add(f"    ENTER_WASM({{ {link_fail} *trapped = 1; return zero; }})")
            add(f"    {ret} r = w2c_{prefix}_{mangle(exp_name)}((w2c_{prefix} *)inst{names});")
            add("    LEAVE_WASM();")
            add("    return r;")
        else:
            add(f"    {link_self}")
            add("    if (wasmext_wasi_check(self->wasi) < 0) { *trapped = 1; return; }" if uses_wasi else "")
            add(f"    ENTER_WASM({{ {link_fail} *trapped = 1; return; }})")
            add(f"    w2c_{prefix}_{mangle(exp_name)}((w2c_{prefix} *)inst{names});")
            add("    LEAVE_WASM();")
        add("}")
        add("")
        mapped.append((exp_name, 0, 0, 0, "NULL", f"(void *)link_call{i}", _c_string(_signature_code(func))))
    memory_base = len(mapped)
    for i, (exp_name, lim) in enumerate(zip(memories, memory_limits, strict=True)):
        accessor = f"w2c_{prefix}_{mangle(exp_name)}"
        add(f"static void *export_memory{i}(InstanceObject *self) {{ return (void *){accessor}(&self->inst); }}")
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
    add("    if (e != NULL) { Py_DECREF(e->owner); PyMem_Free(e); }")
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
    add("    e->instance = &((InstanceObject *)self)->inst;")
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
        add("    wasm_rt_memory_t *mem = m->get(&m->owner->inst);")
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
        accessor = f"w2c_{prefix}_{mangle(exp_name)}(&self->inst)"
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
    add("    InstanceType = (PyTypeObject *)PyType_FromSpec(&instance_spec);")
    if memories:
        add("    MemoryType = (PyTypeObject *)PyType_FromSpec(&memory_spec);")
    add(
        "    if (!TrapError || !LinkError || !InstanceType"
        + (" || !WasiTerminatedError || !WasiExitError || !WasiSignalError" if uses_wasi else "")
        + (" || !MemoryType" if memories else "")
        + ") goto fail;"
    )
    if uses_wasi:
        add('    if (PyModule_AddObjectRef(m, "WasiTerminated", WasiTerminatedError) < 0) goto fail;')
        add('    if (PyModule_AddObjectRef(m, "WasiExit", WasiExitError) < 0) goto fail;')
        add('    if (PyModule_AddObjectRef(m, "WasiSignal", WasiSignalError) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "Trap", TrapError) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "LinkError", LinkError) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "Instance", (PyObject *)InstanceType) < 0) goto fail;')
    add("    return m;")
    add("fail:")
    add("    Py_DECREF(m);")
    add("    return NULL;")
    add("}")
    stub_imports = [imp for imp in module.imports if imp.module not in _WASI_HEADERS]
    return Glue(
        "\n".join(w) + "\n",
        skipped,
        _stub(last, funcs, memories, globals_, stub_imports, uses_wasi, version, param_names),
        tuple(_WASI_HEADERS[m] for m in wasi_modules),
    )


# the value types as the binary format of WebAssembly numbers them: what the link between two extensions says of a global
_TYPE_CODE: dict[ValType, int] = {"i32": 0x7F, "i64": 0x7E, "f32": 0x7D, "f64": 0x7C, "v128": 0x7B}
_PY_TYPE: dict[ValType, str] = {"i32": "int", "i64": "int", "f32": "float", "f64": "float", "v128": "bytes"}
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
