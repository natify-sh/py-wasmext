"""The Caller (as in Wasmtime): a callable with `__wasm_caller__` true is called with the instance that called, its store and its memory first."""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

DATA = Path(__file__).parent / "data"
Builder = Callable[..., ModuleType]
WASI = "wasi_snapshot_preview1"


@pytest.fixture(params=["extension", "ctypes"])
def build(request: pytest.FixtureRequest) -> Builder:
    return request.getfixturevalue("build_extension" if request.param == "extension" else "build_ctypes")  # type: ignore[no-any-return]


def asks_for_the_caller(function: Any) -> Any:
    function.__wasm_caller__ = True
    return function


def test_the_caller_is_the_instance_that_called_and_its_memory(build: Builder) -> None:
    mod: Any = build(DATA / "caller_probe.wat", "caller_probe")
    seen: list[Any] = []

    @asks_for_the_caller
    def peek(caller: Any, address: int) -> int:
        seen.append(caller)
        return int(caller.memory[address])

    store = mod.Store()
    a = mod.Instance(store, imports={"env": {"peek": peek}})
    b = mod.Instance(store, imports={"env": {"peek": peek}})
    a.poke(100, 7)
    b.poke(100, 9)
    assert a.go(100) == 7 and b.go(100) == 9  # the memory of the one that called, whichever called last
    assert a.go(100) == 7
    assert seen[0].instance is a and seen[1].instance is b and seen[0].store is store
    assert seen[0] is seen[2]  # one Caller for an instance


def test_a_callable_that_does_not_ask_is_called_as_before(build: Builder) -> None:
    mod: Any = build(DATA / "caller_probe.wat", "caller_probe")

    def plus_one(address: int) -> int:
        return address + 1

    inst = mod.Instance(mod.Store(), imports={"env": {"peek": plus_one}})
    assert inst.go(41) == 42


def test_the_caller_of_a_module_without_a_memory_has_none(build: Builder) -> None:
    mod: Any = build(DATA / "caller_nomem.wat", "caller_nomem")
    got: list[Any] = []

    @asks_for_the_caller
    def who(caller: Any) -> int:
        got.append(caller.memory)
        return 5

    assert mod.Instance(mod.Store(), imports={"env": {"who": who}}).go() == 5
    assert got == [None]


def test_a_wrapper_of_a_call_of_wasi_gets_the_caller_and_calls_the_original_for_it(build: Builder) -> None:
    mod: Any = functools.partial(build, host="wasm32-wasip1")(DATA / "wasi_probe.wat", "wasi_probe")
    out: list[bytes] = []
    callers: list[Any] = []

    @asks_for_the_caller
    def fd_write(caller: Any, fd: int, iovs: int, count: int, written: int) -> int:
        callers.append(caller.instance)
        original = caller.instance.__host__.__imports__[WASI]["fd_write"]
        return original(fd, iovs, count, written)  # type: ignore[no-any-return]

    store = mod.Store(wasi={"stdout": out.append})
    a = mod.Instance(store, imports={WASI: {"fd_write": fd_write}})
    b = mod.Instance(store, imports={WASI: {"fd_write": fd_write}})
    for inst, text in ((a, b"from a"), (b, b"from b"), (a, b"again")):
        mem = inst.memory
        mem[100 : 100 + len(text)] = text
        mem[0:8] = (100).to_bytes(4, "little") + len(text).to_bytes(4, "little")
        assert inst.fd_write(1, 0, 1, 32) == 0
    assert out == [b"from a", b"from b", b"again"] and callers == [a, b, a]
