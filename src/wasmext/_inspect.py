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
    if kind == "global" and isinstance(thing, GlobalType):
        if thing.type not in ("i32", "i64", "f32", "f64"):
            return f"not supported yet: uses {thing.type}"
        return (
            "ok (an export of another instance)" if thing.mutable else "ok (a number, or an export of another instance)"
        )
    if kind == "memory" and isinstance(thing, Limits):
        return "not supported yet: a shared memory" if thing.shared else "ok (the memory of another instance)"
    if kind == "table" and isinstance(thing, TableType):
        if thing.elem != "funcref" or thing.limits.is64 or thing.limits.shared:
            what = "a 64-bit" if thing.limits.is64 else "a shared" if thing.limits.shared else f"an {thing.elem}"
            return f"not supported yet: {what} table"
        return "ok (the table of another instance)"
    if kind != "func" or not isinstance(thing, FuncType):
        return f"not supported yet: an imported {kind}"
    reason = _why_not(thing, several_results=True)
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
    # the generator decides what is exposed: its list of what it leaves out wins over the rules above (a name with a NUL, a name that
    # would hide a special name of Instance, ...), so that the report cannot say "method of Instance" for what is not one
    generator_error: str | None = None
    left_out: dict[tuple[str, str], str] = {}
    notes: list[str] = []
    try:
        glue = generate(module, "module")
    except GenError as exc:
        generator_error = str(exc)
        ok = False
    else:
        notes = glue.notes
        for item in glue.skipped:
            for exp in module.exports:
                for head in (f"{exp.kind} {exp.name!r}", f"function {exp.name!r}"):
                    if item.startswith(head):
                        left_out[(exp.kind, exp.name)] = item[len(head) :].strip() or f"a {exp.kind}"

    out.append(f"imports ({len(module.imports)}), which the host has to provide:")
    import_rows: list[tuple[str, str, str]] = []
    for imp in module.imports:
        verdict = _verdict_of_import(imp.kind, imp.type)
        ok = ok and verdict.startswith("ok")
        import_rows.append((f"{imp.module}.{imp.name}", f"{imp.kind} {_describe(imp.kind, imp.type)}", verdict))
    out += _rows(import_rows) or ["  (none)"]

    out.append(f"exports ({len(module.exports)}):")
    export_rows: list[tuple[str, str, str]] = []
    for exp in module.exports:
        thing = _export_type(module, exp.kind, exp.index)
        verdict = _export_verdict(exp.kind, thing)
        if (exp.kind, exp.name) in left_out and not verdict.startswith("not "):
            verdict = f"not exposed: {left_out[(exp.kind, exp.name)]}"
        export_rows.append(
            (
                repr(exp.name)[1:-1] if "\0" in exp.name else exp.name,
                f"{exp.kind} {_describe(exp.kind, thing)}",
                verdict,
            )
        )
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

    if generator_error is not None:
        out.append(f"result: cannot be wrapped: {generator_error}")
    else:
        out.append(
            "result: can be wrapped"
            + ("" if not any(r[2].startswith("not ") for r in export_rows) else ", but some exports are left out")
        )
        out += [f"note: {n}" for n in notes]
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
        return "Instance.memory"
    if kind == "global" and isinstance(thing, GlobalType):
        if thing.type not in ("i32", "i64", "f32", "f64"):
            return f"not exposed: uses {thing.type}"
        return "Instance attribute, read-write" if thing.mutable else "Instance attribute, read-only"
    if kind == "table" and isinstance(thing, TableType):
        if thing.elem != "funcref" or thing.limits.is64 or thing.limits.shared:
            return f"not exposed: a {thing.elem} table"
        return "instance[name], for another instance to import"
    return f"not exposed: a {kind}"


def read(path: Path) -> tuple[str, bool]:
    """The report on the file `path`."""
    return inspect(path.read_bytes(), path.as_posix())
