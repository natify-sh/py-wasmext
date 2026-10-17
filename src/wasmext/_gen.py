"""The C glue of an extension module: a parsed WebAssembly module in, the source of a CPython extension out.

    glue = generate(parse(wasm_bytes), "pkg.fast")
    glue.source        # C, to be compiled together with the C that `wasm2c --module-name=fast` writes
    glue.skipped       # exports that the extension does not expose, with the reason

The extension has a class `Instance`: `Instance(imports)` instantiates the module (`imports` is `{module: {name:
callable}}`, needed only if the module imports functions), the exported functions are its methods and an exported
memory is a read-write `memoryview` attribute. A trap is `Trap` (a `RuntimeError`), a missing import `LinkError`. Integers
are what WebAssembly has: arguments are taken modulo 2**32 / 2**64 and results are unsigned.

The C uses only the limited API (PEP 384, 3.11+), so defining `Py_LIMITED_API` builds an abi3 extension.

Not yet: v128, reference types and multiple results in a signature, memory64, imported memories/tables/globals.
"""

from __future__ import annotations

import keyword
from dataclasses import dataclass, field

from ._wasm import FuncType, Import, Module, ValType

__all__ = ["GenError", "Glue", "generate", "mangle"]

_CTYPE: dict[ValType, str] = {"i32": "u32", "i64": "u64", "f32": "f32", "f64": "f64"}
# Python -> wasm value, wasm -> Python value, and the Py_BuildValue code with the cast it needs.
_TO_WASM: dict[ValType, str] = {
    "i32": "(u32)PyLong_AsUnsignedLongMask({0})",
    "i64": "(u64)PyLong_AsUnsignedLongLongMask({0})",
    "f32": "(f32)PyFloat_AsDouble({0})",
    "f64": "PyFloat_AsDouble({0})",
}
_FROM_WASM: dict[ValType, str] = {
    "i32": "PyLong_FromUnsignedLong((unsigned long){0})",
    "i64": "PyLong_FromUnsignedLongLong((unsigned long long){0})",
    "f32": "PyFloat_FromDouble((double){0})",
    "f64": "PyFloat_FromDouble({0})",
}
_BUILD: dict[ValType, tuple[str, str]] = {
    "i32": ("k", "(unsigned long){0}"),
    "i64": ("K", "(unsigned long long){0}"),
    "f32": ("d", "(double){0}"),
    "f64": ("d", "(double){0}"),
}


class GenError(ValueError):
    """The module cannot be turned into an extension (yet)."""


@dataclass(frozen=True, slots=True)
class Glue:
    source: str  # the C of the glue
    skipped: list[str] = field(default_factory=list[str])
    stub: str = ""  # the .pyi of the extension module


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


def _signature(func: FuncType) -> str:
    return f"({', '.join(func.params)}) -> {', '.join(func.results) or 'None'}"


def _why_not(func: FuncType) -> str | None:
    bad = sorted({t for t in (*func.params, *func.results) if t not in _CTYPE})
    if bad:
        return f"uses {', '.join(bad)}"
    if len(func.results) > 1:
        return "has several results"
    return None


def _ident(name: str) -> str:
    """The module name the C side uses: the last component of the dotted Python name."""
    last = name.rsplit(".", 1)[-1]
    if not last.isidentifier() or not last.isascii():
        raise GenError(f"{name!r} is not a valid extension module name")
    return last


@dataclass
class _Import:
    module: str
    field: str
    func: FuncType
    host: int  # index of the import module (the struct that holds its callables)
    slot: int  # the place among the callables of that module
    symbol: str


def generate(module: Module, name: str) -> Glue:
    """The C source of the extension module `name` (dotted, as it is imported) for the parsed `module`."""
    last = _ident(name)
    prefix = mangle(last, module=True)
    skipped: list[str] = []

    # imports: functions only, and every signature must be one the glue can convert
    hosts: list[str] = []
    imports: list[_Import] = []
    slots: dict[str, int] = {}
    for imp in module.imports:
        if imp.kind != "func" or not isinstance(imp.type, FuncType):
            raise GenError(f"import {imp.module}.{imp.name}: an imported {imp.kind} is not supported yet")
        reason = _why_not(imp.type)
        if reason:
            raise GenError(f"import {imp.module}.{imp.name} {reason}: not supported yet")
        if imp.module not in hosts:
            hosts.append(imp.module)
        slot = slots.get(imp.module, 0)
        slots[imp.module] = slot + 1
        symbol = f"w2c_{mangle(imp.module, module=True)}_{mangle(imp.name)}"
        imports.append(_Import(imp.module, imp.name, imp.type, hosts.index(imp.module), slot, symbol))

    # exports: functions and memories; the rest is left out, and reported
    funcs: list[tuple[str, FuncType]] = []
    memories: list[str] = []
    memory_defs = module.all_memories
    for exp in module.exports:
        if exp.kind == "func":
            func = module.all_functions[exp.index]
            reason = _why_not(func)
            if reason:
                skipped.append(f"function {exp.name!r} {reason}")
            else:
                funcs.append((exp.name, func))
        elif exp.kind == "memory":
            if memory_defs[exp.index].is64:
                skipped.append(f"memory {exp.name!r} is memory64")
            else:
                memories.append(exp.name)
        else:
            skipped.append(f"{exp.kind} {exp.name!r}")

    has_imports = bool(imports)
    w: list[str] = []
    add = w.append

    add(f"/* Generated by wasmext from the WebAssembly module of {last}: do not edit. */")
    add("#define PY_SSIZE_T_CLEAN")
    add("#include <Python.h>")
    add("#include <structmember.h>")
    add("#include <string.h>")
    add(f'#include "{last}_w2c.h"')
    add('#include "wasm-rt-impl.h"')
    add("")
    add("/* the trap code of a Python exception that unwinds the WebAssembly frames: the exception is already set */")
    add("#define PY_ERROR_TRAP ((wasm_rt_trap_t)0x7000)")
    add("")
    add("static PyObject *TrapError;")
    add("static PyObject *LinkError;")
    add("static PyTypeObject *InstanceType;")
    if memories:
        add("static PyTypeObject *MemoryType;")
    add("")
    add("static void set_trap_error(wasm_rt_trap_t code) {")
    add("    if (code != PY_ERROR_TRAP) PyErr_SetString(TrapError, wasm_rt_strerror(code));")
    add("}")
    add("")
    # what a call of WebAssembly code must do about the jump buffer
    if has_imports:
        add(
            "/* a Python callable can call back into the module: the buffer of the outer call is put back afterwards */"
        )
        add("#define ENTER_WASM(FAIL) \\")
        add("    wasm_rt_jmp_buf saved_jmp_; \\")
        add("    memcpy(&saved_jmp_, &g_wasm_rt_jmp_buf, sizeof saved_jmp_); \\")
        add("    wasm_rt_trap_t trap_ = (wasm_rt_trap_t)wasm_rt_try(g_wasm_rt_jmp_buf); \\")
        add("    if (trap_) { \\")
        add("        memcpy(&g_wasm_rt_jmp_buf, &saved_jmp_, sizeof saved_jmp_); \\")
        add("        set_trap_error(trap_); \\")
        add("        FAIL; \\")
        add("    }")
        add("#define LEAVE_WASM() memcpy(&g_wasm_rt_jmp_buf, &saved_jmp_, sizeof saved_jmp_)")
    else:
        add("#define ENTER_WASM(FAIL) \\")
        add("    wasm_rt_trap_t trap_ = (wasm_rt_trap_t)wasm_rt_try(g_wasm_rt_jmp_buf); \\")
        add("    if (trap_) { set_trap_error(trap_); FAIL; }")
        add("#define LEAVE_WASM() ((void)0)")
    add("")

    for i, host in enumerate(hosts):
        add(f"/* the callables of the imports of module {_c_string(host)} */")
        add(f"struct w2c_{mangle(host, module=True)} {{ PyObject *fn[{slots[host]}]; }};")
    add("")
    add("typedef struct {")
    add("    PyObject_HEAD")
    add(f"    w2c_{prefix} inst;")
    add("    int instantiated;")
    add("    PyObject *weakreflist;")
    for i, host in enumerate(hosts):
        add(f"    struct w2c_{mangle(host, module=True)} host{i};")
    add("} InstanceObject;")
    add("")
    if memories:
        add("typedef struct {")
        add("    PyObject_HEAD")
        add("    InstanceObject *owner;")
        add(f"    wasm_rt_memory_t *(*get)(w2c_{prefix} *);")
        add("} MemoryObject;")
        add("")

    # the functions the module imports, implemented over the callables
    for imp in imports:
        func = imp.func
        params = "".join(f", {_CTYPE[t]} a{i}" for i, t in enumerate(func.params))
        ret = _CTYPE[func.results[0]] if func.results else "void"
        mod_struct = f"struct w2c_{mangle(imp.module, module=True)}"
        add(f"{ret} {imp.symbol}({mod_struct} *h{params}) {{")
        fmt = "".join(_BUILD[t][0] for t in func.params)
        casts = "".join(f", {_BUILD[t][1].format(f'a{i}')}" for i, t in enumerate(func.params))
        add(f'    PyObject *r = PyObject_CallFunction(h->fn[{imp.slot}], "{fmt}"{casts});')
        add("    if (r == NULL) wasm_rt_trap(PY_ERROR_TRAP);")
        if func.results:
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
        add("static PyObject *lookup_import(PyObject *imports, const char *module, const char *field) {")
        add("    PyObject *key = PyUnicode_FromString(module), *m, *f;")
        add("    if (key == NULL) return NULL;")
        add("    m = PyObject_GetItem(imports, key);")
        add("    Py_DECREF(key);")
        add("    if (m == NULL) {")
        add("        PyErr_Clear();")
        add("        PyErr_Format(LinkError, \"missing import module '%s'\", module);")
        add("        return NULL;")
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
        add("    if (!PyCallable_Check(f)) {")
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
        add(f"    for (int k = 0; k < {slots[host]}; k++) Py_VISIT(self->host{i}.fn[k]);")
    add("    return 0;")
    add("}")
    add("")
    add("static int Instance_clear(InstanceObject *self) {")
    for i, host in enumerate(hosts):
        add(f"    for (int k = 0; k < {slots[host]}; k++) Py_CLEAR(self->host{i}.fn[k]);")
    add("    return 0;")
    add("}")
    add("")
    add("static void Instance_dealloc(InstanceObject *self) {")
    add("    PyTypeObject *tp = Py_TYPE((PyObject *)self);")
    add("    PyObject_GC_UnTrack(self);")
    add("    if (self->weakreflist != NULL) PyObject_ClearWeakRefs((PyObject *)self);")
    add(f"    if (self->instantiated) wasm2c_{prefix}_free(&self->inst);")
    add("    Instance_clear(self);")
    add("    ((freefunc)PyType_GetSlot(tp, Py_tp_free))((PyObject *)self);")
    add("    Py_DECREF(tp);")
    add("}")
    add("")
    add("static PyObject *Instance_new(PyTypeObject *type, PyObject *args, PyObject *kwds) {")
    if has_imports:
        add('    static char *kwlist[] = {"imports", NULL};')
        add("    PyObject *imports = Py_None;")
        add('    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|O:Instance", kwlist, &imports)) return NULL;')
    else:
        add("    static char *kwlist[] = {NULL};")
        add('    if (!PyArg_ParseTupleAndKeywords(args, kwds, ":Instance", kwlist)) return NULL;')
    add("    InstanceObject *self = (InstanceObject *)PyType_GenericAlloc(type, 0);")
    add("    if (self == NULL) return NULL;")
    if has_imports:
        add("    if (imports == Py_None) {")
        add(
            '        PyErr_SetString(LinkError, "the module imports functions: pass imports={module: {name: callable}}");'
        )
        add("        Py_DECREF(self);")
        add("        return NULL;")
        add("    }")
        for imp in imports:
            add(
                f"    self->host{imp.host}.fn[{imp.slot}] = lookup_import(imports, {_c_string(imp.module)}, {_c_string(imp.field)});"
            )
            add(f"    if (self->host{imp.host}.fn[{imp.slot}] == NULL) {{ Py_DECREF(self); return NULL; }}")
    add("    ENTER_WASM({ Py_DECREF(self); return NULL; })")
    host_args = "".join(f", &self->host{i}" for i in range(len(hosts)))
    add(f"    wasm2c_{prefix}_instantiate(&self->inst{host_args});")
    add("    LEAVE_WASM();")
    add("    self->instantiated = 1;")
    add("    return (PyObject *)self;")
    add("}")
    add("")

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
        add("    ENTER_WASM(return NULL)")
        call_args = "".join(f", a{j}" for j in range(n))
        call = f"w2c_{prefix}_{mangle(exp_name)}(&self->inst{call_args})"
        if func.results:
            add(f"    {_CTYPE[func.results[0]]} r = {call};")
            add("    LEAVE_WASM();")
            add(f"    return {_FROM_WASM[func.results[0]].format('r')};")
        else:
            add(f"    {call};")
            add("    LEAVE_WASM();")
            add("    Py_RETURN_NONE;")
        add("}")
        add("")
    add("static PyMethodDef Instance_methods[] = {")
    for i, (exp_name, func) in enumerate(funcs):
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
        add("    return PyBuffer_FillInfo(view, self, mem->data, (Py_ssize_t)mem->size, 0, flags);")
        add("}")
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
        add("    MemoryObject *m = PyObject_New(MemoryObject, MemoryType);")
        add("    PyObject *view;")
        add("    if (m == NULL) return NULL;")
        add("    Py_INCREF((PyObject *)self);")
        add("    m->owner = self;")
        add("    m->get = memory_getters[(size_t)closure];")
        add("    view = PyMemoryView_FromObject((PyObject *)m);")
        add("    Py_DECREF(m);")
        add("    return view;")
        add("}")
        add("")
    add("static PyGetSetDef Instance_getset[] = {")
    for i, exp_name in enumerate(memories):
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
    add("    InstanceType = (PyTypeObject *)PyType_FromSpec(&instance_spec);")
    if memories:
        add("    MemoryType = (PyTypeObject *)PyType_FromSpec(&memory_spec);")
    add("    if (!TrapError || !LinkError || !InstanceType" + (" || !MemoryType" if memories else "") + ") goto fail;")
    add('    if (PyModule_AddObjectRef(m, "Trap", TrapError) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "LinkError", LinkError) < 0) goto fail;')
    add('    if (PyModule_AddObjectRef(m, "Instance", (PyObject *)InstanceType) < 0) goto fail;')
    add("    return m;")
    add("fail:")
    add("    Py_DECREF(m);")
    add("    return NULL;")
    add("}")
    return Glue("\n".join(w) + "\n", skipped, _stub(last, funcs, memories, module.imports))


_PY_TYPE: dict[ValType, str] = {"i32": "int", "i64": "int", "f32": "float", "f64": "float"}


def _usable(name: str) -> bool:
    """A name that can be written as a method or an attribute in a stub."""
    return name.isidentifier() and not keyword.iskeyword(name)


def _callable_type(func: FuncType) -> str:
    params = ", ".join(_PY_TYPE[t] for t in func.params)
    result = _PY_TYPE[func.results[0]] if func.results else "None"
    return f"Callable[[{params}], {result}]"


def _stub(last: str, funcs: list[tuple[str, FuncType]], memories: list[str], imports: list[Import]) -> str:
    """The `.pyi` for the extension module: what a type checker and an editor can know of an extension."""
    # The formatter and the linter of the project the stub lands in leave a generated file alone (the second noqa is
    # for a project that selects every rule, PGH004 among them: it objects to the first).
    lines = [
        f"# Generated by wasmext from the WebAssembly module of {last}: do not edit.",
        "# ruff: noqa",
        "# ruff: noqa: PGH004",
        "# fmt: off",
    ]
    if imports:
        lines += ["from collections.abc import Callable", "from typing import TypedDict"]
    lines += ["", "class Trap(RuntimeError): ...", "class LinkError(Exception): ...", ""]
    by_module: dict[str, list[Import]] = {}
    for imp in imports:
        by_module.setdefault(imp.module, []).append(imp)
    for i, (_module, members) in enumerate(by_module.items()):
        items = ", ".join(
            f"{_py_string(m.name)}: {_callable_type(m.type)}" for m in members if isinstance(m.type, FuncType)
        )
        lines.append(f"_Imports{i} = TypedDict('_Imports{i}', {{{items}}})")
    if by_module:
        fields = ", ".join(f"{_py_string(m)}: _Imports{i}" for i, m in enumerate(by_module))
        lines += [f"Imports = TypedDict('Imports', {{{fields}}})", ""]
    lines.append("class Instance:")
    lines.append(
        "    def __init__(self, imports: Imports) -> None: ..." if by_module else "    def __init__(self) -> None: ..."
    )
    for name, func in funcs:
        params = "".join(f"arg{i}: {_PY_TYPE[t]}, " for i, t in enumerate(func.params))
        params = f", {params}/" if func.params else ""
        result = _PY_TYPE[func.results[0]] if func.results else "None"
        if _usable(name):
            lines.append(f"    def {name}(self{params}) -> {result}: ...")
        else:
            lines.append(f"    # {_py_string(name)} is not an identifier: getattr(instance, {_py_string(name)})")
    for name in memories:
        if _usable(name):
            lines += ["    @property", f"    def {name}(self) -> memoryview: ..."]
        else:
            lines.append(f"    # memory {_py_string(name)} is not an identifier: getattr(instance, {_py_string(name)})")
    return "\n".join(lines) + "\n"


def _py_string(text: str) -> str:
    return repr(text)
