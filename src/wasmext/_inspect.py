"""`wasmext inspect FILE...`: what a WebAssembly module imports and exports, and what wasmext would make of it.

It reads the module with the parser of wasmext and applies the rules of the generator, so that it names what the
extension would need from the host (the imports), what it would offer (the exports that become methods of
`Instance`) and what it would leave out, with the reason. Nothing is written and `wasm2c` is not needed.
"""

from __future__ import annotations

from pathlib import Path

from ._gen import GenError, _signature, _why_not, generate  # pyright: ignore[reportPrivateUsage]
from ._wasm import FuncType, GlobalType, Limits, Module, TableType, WasmError, parse

__all__ = ["inspect"]


def _limits(limits: Limits, unit: str) -> str:
    size = f"{limits.min}" if limits.max is None else f"{limits.min}..{limits.max}"
    if size == "1":
        unit = unit.removesuffix("s")
    flags = ", shared" if limits.shared else ""
    flags += ", memory64" if limits.is64 else ""
    return f"{size} {unit}{flags}"


def _describe(kind: str, thing: FuncType | TableType | Limits | GlobalType) -> str:
    if isinstance(thing, FuncType):
        return _signature(thing)
    if isinstance(thing, TableType):
        return f"{thing.elem}, {_limits(thing.limits, 'elements')}"
    if isinstance(thing, GlobalType):
        return f"{'mut ' if thing.mutable else ''}{thing.type}"
    return _limits(thing, "pages") if kind == "memory" else kind


def _verdict_of_import(kind: str, thing: FuncType | TableType | Limits | GlobalType) -> str:
    if kind != "func" or not isinstance(thing, FuncType):
        return f"not supported yet: an imported {kind}"
    reason = _why_not(thing)
    return f"not supported yet: {reason}" if reason else "ok"


def _rows(rows: list[tuple[str, str, str]]) -> list[str]:
    """Three columns, aligned; the last one is left out when it is empty."""
    first = max((len(a) for a, _, _ in rows), default=0)
    second = max((len(b) for _, b, _ in rows), default=0)
    return [f"  {a:<{first}}  {b:<{second}}  {c}".rstrip() for a, b, c in rows]


def inspect(data: bytes, label: str) -> tuple[str, bool]:
    """The report on the module `data` (`label` is how it is called) and whether wasmext can wrap it."""
    try:
        module = parse(data)
    except WasmError as exc:
        return f"{label}: not a module wasmext can read: {exc}\n", False

    out = [f"{label} ({len(data)} bytes)"]
    ok = True

    out.append(f"imports ({len(module.imports)}), which the host has to provide:")
    import_rows: list[tuple[str, str, str]] = []
    for imp in module.imports:
        verdict = _verdict_of_import(imp.kind, imp.type)
        ok = ok and verdict == "ok"
        import_rows.append((f"{imp.module}.{imp.name}", f"{imp.kind} {_describe(imp.kind, imp.type)}", verdict))
    out += _rows(import_rows) or ["  (none)"]

    out.append(f"exports ({len(module.exports)}):")
    export_rows: list[tuple[str, str, str]] = []
    for exp in module.exports:
        thing = _export_type(module, exp.kind, exp.index)
        export_rows.append((exp.name, f"{exp.kind} {_describe(exp.kind, thing)}", _export_verdict(exp.kind, thing)))
    out += _rows(export_rows) or ["  (none)"]

    extras = [
        f"{len(module.memories)} memory" if module.memories else "",
        f"{len(module.tables)} table" if module.tables else "",
        f"{len(module.globals)} global" if module.globals else "",
        f"start function {module.start}" if module.start is not None else "",
    ]
    defined = ", ".join(e for e in extras if e)
    out.append(
        f"defined here: {len(module.functions)} function{'s' if len(module.functions) != 1 else ''}"
        + (f", {defined}" if defined else "")
    )

    try:
        generate(module, "module")
    except GenError as exc:
        ok = False
        out.append(f"result: cannot be wrapped: {exc}")
    else:
        out.append(
            "result: can be wrapped"
            + ("" if not any(r[2].startswith("not ") for r in export_rows) else ", but some exports are left out")
        )
    return "\n".join(out) + "\n", ok


def _export_type(module: Module, kind: str, index: int) -> FuncType | TableType | Limits | GlobalType:
    if kind == "func":
        return module.all_functions[index]
    if kind == "table":
        return module.all_tables[index]
    if kind == "memory":
        return module.all_memories[index]
    if kind == "global":
        return module.all_globals[index]
    return FuncType((), ())  # a tag: only its place in the module is known here


def _export_verdict(kind: str, thing: FuncType | TableType | Limits | GlobalType) -> str:
    if kind == "func" and isinstance(thing, FuncType):
        reason = _why_not(thing, several_results=True)
        return f"not exposed: {reason}" if reason else "method of Instance"
    if kind == "memory" and isinstance(thing, Limits):
        return "not exposed: memory64" if thing.is64 else "Instance.memory"
    return f"not exposed: a {kind}"


def read(path: Path) -> tuple[str, bool]:
    """The report on the file `path`."""
    return inspect(path.read_bytes(), path.as_posix())
