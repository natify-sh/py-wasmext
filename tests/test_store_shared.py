"""Two instances in one store (C2a): the host is shared, the memory is the instance's own.

The module of WASI 0.1 gets the memory of the instance that calls (the trampoline binds it before each call), so a host shared by several instances serves each. These tests are written
before the public `Store` existed (`WASI_TARGET_PLAN.md`, "The structure"). The extension has it; the wrapper for ctypes is expected to fail with `AttributeError` until its step, and `strict` makes the mark go with it.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

DATA = Path(__file__).parent / "data"
Builder = Callable[..., ModuleType]

ctypes_not_yet = pytest.mark.xfail(
    strict=True, raises=AttributeError, reason="C2a: the Store of the wrapper for ctypes is not made yet"
)


@pytest.fixture(params=["extension", pytest.param("ctypes", marks=ctypes_not_yet)])
def build(request: pytest.FixtureRequest) -> Builder:
    builder: Builder = request.getfixturevalue("build_extension" if request.param == "extension" else "build_ctypes")
    return functools.partial(builder, host="wasm32-wasip1")


def write(inst: Any, at: int, data: bytes) -> int:
    """Put `data` at `at` of the memory of `inst`, with an iovec at 0 for it, and write it to descriptor 1; the number of bytes the host says it wrote."""
    mem = inst.memory
    mem[at : at + len(data)] = data
    mem[0:8] = at.to_bytes(4, "little") + len(data).to_bytes(4, "little")
    assert inst.fd_write(1, 0, 1, 32) == 0
    return int.from_bytes(mem[32:36], "little")


def test_each_instance_of_a_store_is_served_from_its_own_memory(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_probe.wat", "wasi_probe")
    out: list[bytes] = []
    store = mod.Store(wasi={"stdout": out.append})
    a, b = mod.Instance(store), mod.Instance(store)
    # the same address holds different bytes in each memory: a host that read the wrong memory would write the other's
    assert write(a, 100, b"from a") == 6
    assert write(b, 100, b"from b!") == 7
    assert write(a, 100, b"again a") == 7
    assert out == [b"from a", b"from b!", b"again a"]
    assert bytes(a.memory[100:107]) == b"again a" and bytes(b.memory[100:107]) == b"from b!"


def test_the_table_of_descriptors_is_the_stores(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_probe.wat", "wasi_probe")
    out: list[bytes] = []
    store = mod.Store(wasi={"stdout": out.append})
    a, b = mod.Instance(store), mod.Instance(store)
    assert a.fd_close(1) == 0
    assert b.fd_close(1) == 8  # EBADF: closed by the other instance, as in Wasmtime where the table is the store's
    mem = b.memory
    mem[0:8] = (100).to_bytes(4, "little") + (1).to_bytes(4, "little")
    assert b.fd_write(1, 0, 1, 32) == 8 and out == []


def test_the_end_of_one_instance_does_not_touch_the_other(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_probe.wat", "wasi_probe")
    out: list[bytes] = []
    store = mod.Store(wasi={"stdout": out.append})
    a, b = mod.Instance(store), mod.Instance(store)
    with pytest.raises(mod.WasiExit) as info:
        a.proc_exit(7)
    assert info.value.code == 7
    assert write(b, 100, b"alive") == 5  # as in Wasmtime: the end is what the call leaves, not a state of the store
    assert write(a, 100, b"so is a") == 7
    assert out == [b"alive", b"so is a"]


def test_a_store_of_its_own_shares_nothing(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_probe.wat", "wasi_probe")
    out1: list[bytes] = []
    out2: list[bytes] = []
    a = mod.Instance(mod.Store(wasi={"stdout": out1.append}))
    b = mod.Instance(mod.Store(wasi={"stdout": out2.append}))
    assert a.fd_close(1) == 0
    assert write(b, 100, b"b") == 1 and out1 == [] and out2 == [b"b"]
