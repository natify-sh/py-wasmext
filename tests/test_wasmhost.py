"""Examples of py-wasmhost (`examples/imports.py`), run as native extensions: the module of that example
(`tests/data/wasmhost/imports.wasm`, the bytes of the example written out as a file) imports four host functions, one of
them with several results."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

DATA = Path(__file__).parent / "data" / "wasmhost"
Builder = Callable[..., ModuleType]


def test_host_functions_with_several_results_and_an_exception(build_extension: Builder) -> None:
    mod = build_extension(DATA / "imports.wasm", "wh_imports")
    log: list[str] = []

    def plus(a: int, b: int) -> int:
        log.append(f"plus({a}, {b})")
        return a + b

    def note(x: int) -> None:
        log.append(f"note({x})")

    def half(x: float) -> float:
        return x / 2

    def pair(x: int) -> tuple[int, int]:
        return (x, x + 1)

    imports: dict[str, dict[str, Callable[..., object]]] = {
        "env": {"plus": plus, "note": note, "half": half, "pair": pair}
    }
    inst = mod.Instance(imports)
    assert inst.call_plus(2, 3) == 5
    assert inst.twice(10) == 12  # two calls of the host
    assert inst.call_half(5.0) == 2.5
    assert inst.call_pair(7) == (7, 8)  # several results: a tuple
    inst.call_note(2**62 + 1)  # an i64 arrives as an exact int
    assert log == ["plus(2, 3)", "plus(10, 1)", "plus(11, 1)", f"note({2**62 + 1})"]

    # an exception in a host function comes out of the call that led to it, and the instance is still good
    def broken(a: int, b: int) -> int:
        raise ValueError("no thanks")

    other = mod.Instance({"env": {**imports["env"], "plus": broken}})
    with pytest.raises(ValueError, match="no thanks"):
        other.call_plus(1, 2)
    assert other.call_half(1.0) == 0.5
