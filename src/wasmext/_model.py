"""The model of a module: one analysis of a parsed module and the build options, read by every emitter.

It adds to `wasmext.Module` only facts about the build, decided once: who answers each import, the flags. `dump()` is the canonical text of
all of it, one fact per line; the C reader of the descriptor (`tests/c/dump_descriptor.c`) prints the same text, so the two readers of the
facts must agree."""

from __future__ import annotations

from dataclasses import dataclass

from ._gen import _ident, check_host  # pyright: ignore[reportPrivateUsage]
from ._wasm import ExternKind, FuncType, GlobalType, Limits, Module, TableType, ValType

__all__ = ["ExportFact", "ImportFact", "ModuleModel", "build_model"]

FLAG_SHARE_TABLES = 1
FLAG_USES_CORE = 2

KIND_CODES: dict[ExternKind, int] = {"func": 0, "table": 1, "memory": 2, "global": 3, "tag": 4}
VALTYPE_BYTES: dict[ValType, int] = {
    "i32": 0x7F,
    "i64": 0x7E,
    "f32": 0x7D,
    "f64": 0x7C,
    "v128": 0x7B,
    "funcref": 0x70,
    "externref": 0x6F,
}

_P1_MODULES = ("wasi_snapshot_preview1", "wasi_unstable")

Type = FuncType | TableType | Limits | GlobalType


@dataclass(frozen=True, slots=True)
class ImportFact:
    module: str
    name: str
    kind: ExternKind
    index: int  # among the imports of its kind
    type: Type
    core: bool  # the core answers it, the caller gives nothing


@dataclass(frozen=True, slots=True)
class ExportFact:
    name: str
    kind: ExternKind
    index: int  # in the index space of its kind
    type: Type
    param_names: tuple[str | None, ...] | None  # the names of the parameters of a function, if the module names any


@dataclass(frozen=True, slots=True)
class ModuleModel:
    name: str  # as it is imported (dotted)
    last: str  # the C identifier of the last part of the name: the prefix of the C API
    host: str
    share_tables: bool
    module: Module
    imports: tuple[ImportFact, ...]
    exports: tuple[ExportFact, ...]

    @property
    def flags(self) -> int:
        return (FLAG_SHARE_TABLES if self.share_tables else 0) | (
            FLAG_USES_CORE if any(i.core for i in self.imports) else 0
        )

    def dump(self) -> str:
        """The canonical text: see `tests/c/dump_descriptor.c`, which writes the same from the descriptor in C."""
        m = self.module
        out = [f"module {_q(self.name)}", f"flags {self.flags}", f"start {-1 if m.start is None else m.start}"]
        for i, mem in enumerate(m.all_memories):
            out.append(f"memory {i} {_limits(mem)}")
        for i, tab in enumerate(m.all_tables):
            out.append(f"table {i} {VALTYPE_BYTES[tab.elem]} {_limits(tab.limits)}")
        for i, glob in enumerate(m.all_globals):
            out.append(f"global {i} {VALTYPE_BYTES[glob.type]} {int(glob.mutable)}")
        for i, tag in enumerate(m.all_tags):
            out.append(f"tag {i} {_functype(tag)}")
        for imp in self.imports:
            out.append(
                f"import {imp.kind} {_q(imp.module)} {_q(imp.name)} {imp.index} {int(imp.core)} {_type(imp.type)}"
            )
        for exp in self.exports:
            names = ""
            if exp.param_names is not None:
                names = " names " + " ".join("-" if n is None else _q(n) for n in exp.param_names)
            out.append(f"export {exp.kind} {_q(exp.name)} {exp.index} {_type(exp.type)}{names}")
        return "\n".join(out) + "\n"


def build_model(module: Module, name: str, *, host: str = "wasm32", share_tables: bool = False) -> ModuleModel:
    """The model of `module`, imported as `name`, for `host` (see `wasmext._gen.HOSTS`)."""
    host = check_host(host)
    seen: dict[ExternKind, int] = {}
    imports: list[ImportFact] = []
    for imp in module.imports:
        index = seen.get(imp.kind, 0)
        seen[imp.kind] = index + 1
        imports.append(
            ImportFact(imp.module, imp.name, imp.kind, index, imp.type, _answered_by_core(host, imp.module, imp.kind))
        )
    spaces: dict[ExternKind, list[Type]] = {
        "func": list(module.all_functions),
        "table": list(module.all_tables),
        "memory": list(module.all_memories),
        "global": list(module.all_globals),
        "tag": list(module.all_tags),
    }
    exports: list[ExportFact] = []
    for exp in module.exports:
        names = None
        if exp.kind == "func":
            names = module.param_names(exp.index)
            if not any(n is not None for n in names):
                names = None
        exports.append(ExportFact(exp.name, exp.kind, exp.index, spaces[exp.kind][exp.index], names))
    return ModuleModel(name, _ident(name), host, share_tables, module, tuple(imports), tuple(exports))


def _answered_by_core(host: str, module: str, kind: ExternKind) -> bool:
    """Whether the core of wasmext answers an import (the one place that says it): WASI 0.1 for `wasm32-wasip1`, WASI 0.2 for `wasm32-wasip2`."""
    if kind != "func":
        return False
    if host == "wasm32-wasip1":
        return module in _P1_MODULES
    if host == "wasm32-wasip2":
        return module.startswith("wasi:") and "@0.2." in module
    return False


def _q(text: str) -> str:
    """A name as the dump writes it: in double quotes, the bytes outside printable ASCII, the quote and the backslash as `\\xHH`."""
    out = ['"']
    for b in text.encode("utf-8", "surrogatepass"):
        out.append(chr(b) if 0x20 < b < 0x7F and b not in (0x22, 0x5C) else f"\\x{b:02x}")
    out.append('"')
    return "".join(out)


def _limits(lim: Limits) -> str:
    return f"{lim.min} {-1 if lim.max is None else lim.max} {int(lim.shared)} {int(lim.is64)}"


def _functype(ft: FuncType) -> str:
    return f"({' '.join(str(VALTYPE_BYTES[t]) for t in ft.params)})->({' '.join(str(VALTYPE_BYTES[t]) for t in ft.results)})"


def _type(t: Type) -> str:
    if isinstance(t, FuncType):
        return _functype(t)
    if isinstance(t, TableType):
        return f"{VALTYPE_BYTES[t.elem]} {_limits(t.limits)}"
    if isinstance(t, GlobalType):
        return f"{VALTYPE_BYTES[t.type]} {int(t.mutable)}"
    return _limits(t)
