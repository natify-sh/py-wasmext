"""The glue uses only the limited API: with Py_LIMITED_API defined it builds, and the extension behaves the same."""

from __future__ import annotations

import gc
import weakref
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest

from .conftest import DATA

Builder = Callable[..., ModuleType]


@pytest.fixture(scope="module")
def ext(build_extension: Builder) -> Any:
    return build_extension(DATA / "features.wasm", "features_abi3", abi3=True)


def make(ext: Any, **overrides: Callable[..., Any]) -> Any:
    env: dict[str, Callable[..., Any]] = {"log": lambda _x: None, "twice": lambda x: x * 2, "cb": lambda: None}  # pyright: ignore[reportUnknownLambdaType]
    env.update(overrides)
    return ext.Instance({"env": env})


def test_calls_imports_and_traps(ext: Any) -> None:
    seen: list[int] = []
    inst = make(ext, log=seen.append)
    assert inst.add(0xFFFFFFFF, 2) == 1
    assert inst.dbl(1.25) == 2.5
    inst.say(7)
    assert seen == [7]
    with pytest.raises(ext.Trap, match="divide by zero"):
        inst.div(1, 0)
    assert inst.add(1, 1) == 2


def test_memory_and_lifetime(ext: Any) -> None:
    inst = make(ext)
    mem = inst.mem
    assert bytes(mem[:2]) == b"hi"
    ref = weakref.ref(inst)
    del inst
    gc.collect()
    assert bytes(mem[:2]) == b"hi"  # the view keeps the instance alive
    del mem
    gc.collect()
    assert ref() is None


def test_a_subclass_works(ext: Any) -> None:
    class Mine(ext.Instance):
        pass

    inst = Mine({"env": {"log": print, "twice": float, "cb": print}})
    assert inst.add(1, 2) == 3
    del inst
    gc.collect()
