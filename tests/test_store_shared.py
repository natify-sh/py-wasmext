"""Two instances in one store (C2a): the host is shared, the memory is the instance's own.

The module of WASI 0.1 gets the memory of the instance that calls (the trampoline binds it before each call), so a host shared by several instances serves each. These tests are written
before the public `Store` existed (`WASI_TARGET_PLAN.md`, "The structure"). Both front ends have it: the extension, and the wrapper for ctypes over the `<name>_store_new` of the library.
"""

from __future__ import annotations

import functools
import gc
import weakref
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

DATA = Path(__file__).parent / "data"
Builder = Callable[..., ModuleType]


@pytest.fixture(params=["extension", "ctypes"])
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


def test_a_memory_that_grows_is_read_again_and_the_other_keeps_its_size(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_grow.wat", "wasi_grow")
    out: list[bytes] = []
    store = mod.Store(wasi={"stdout": out.append})
    a, b = mod.Instance(store), mod.Instance(store)
    assert write(a, 100, b"before") == 6
    assert a.grow(1) == 1  # one page, now two
    assert write(a, 70000, b"in the new page") == 15  # beyond the first page: only the grown memory has it
    assert write(b, 100, b"b") == 1
    mem = b.memory
    mem[0:8] = (70000).to_bytes(4, "little") + (4).to_bytes(4, "little")
    assert b.fd_write(1, 0, 1, 32) == 21  # EFAULT: b is still one page, whatever a has grown to
    del mem
    assert b.grow(3) == 1 and write(b, 200000, b"b grew") == 6
    assert write(a, 70000, b"a again") == 7
    assert out == [b"before", b"in the new page", b"b", b"b grew", b"a again"]


WASI = "wasi_snapshot_preview1"


def test_a_with_block_closes_the_store_and_nothing_is_called_in_it_any_more(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_probe.wat", "wasi_probe")
    out: list[bytes] = []
    with mod.Store(wasi={"stdout": out.append}) as store:
        inst = mod.Instance(store)
        assert not store.closed and write(inst, 100, b"inside") == 6
    assert store.closed and out == [b"inside"]
    with pytest.raises(ValueError, match="closed"):
        inst.fd_write(1, 0, 1, 32)  # a call into an instance of a closed store is an error, never a crash
    with pytest.raises(ValueError, match="closed"):
        mod.Instance(store)
    with pytest.raises(ValueError, match="closed"), store:
        pass
    store.close()  # closing twice is not an error, as for a file


def test_close_lets_go_the_objects_of_the_configuration(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_probe.wat", "wasi_probe")

    class Sink:
        def write(self, data: bytes) -> None:
            pass

    sink = Sink()
    ref = weakref.ref(sink)
    store = mod.Store(wasi={"stdout": sink})
    inst = mod.Instance(store)
    del sink
    gc.collect()
    assert ref() is not None  # the store holds it while it is open
    store.close()
    gc.collect()
    assert ref() is None  # the host is let go: the files of the program are closed, the objects of the caller are free
    assert inst is not None


def test_a_store_is_not_closed_from_inside_a_call_that_runs_in_it(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_probe.wat", "wasi_probe")
    holder: list[Any] = []

    def hook(data: bytes) -> None:
        holder[0].close()  # the call of fd_write is running in this store

    store = mod.Store(wasi={"stdout": hook})
    holder.append(store)
    inst = mod.Instance(store)
    with pytest.raises(RuntimeError, match="in use"):
        write(inst, 100, b"x")
    assert not store.closed  # nothing was done
    store.close()
    assert store.closed


def test_the_runtime_of_a_store_says_what_it_is(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_probe.wat", "wasi_probe")
    a, b = mod.Store(), mod.Store()
    assert a.runtime.name == "wasm2c" and isinstance(a.runtime.abi, int) and isinstance(a.runtime.fingerprint, int)
    assert (a.runtime.abi, a.runtime.fingerprint) == (b.runtime.abi, b.runtime.fingerprint)


def test_a_store_of_another_module_is_refused(build: Builder) -> None:
    mod_a: Any = build(DATA / "wasi_probe.wat", "wasi_probe")
    mod_b: Any = build(DATA / "wasi_grow.wat", "wasi_grow")
    with pytest.raises(TypeError, match="Store"):
        mod_b.Instance(
            mod_a.Store()
        )  # the layouts of two modules differ: a store shared by modules waits for the versioned record (C7)
    with pytest.raises(TypeError, match="Store"):
        mod_a.Instance(object())


def test_the_original_of_a_call_of_the_host_reads_the_memory_of_its_own_instance(build: Builder) -> None:
    mod: Any = build(DATA / "wasi_probe.wat", "wasi_probe")
    out: list[bytes] = []
    store = mod.Store(wasi={"stdout": out.append})
    a, b = mod.Instance(store), mod.Instance(store)
    original = a.__host__.__imports__[WASI]["fd_write"]
    write(b, 100, b"from b")  # b is the last instance that called
    mem = a.memory
    mem[100:106] = b"from a"
    mem[0:8] = (100).to_bytes(4, "little") + (6).to_bytes(4, "little")
    assert original(1, 0, 1, 32) == 0 and out == [b"from b", b"from a"]
    store.close()
    with pytest.raises(ValueError, match="closed"):
        original(1, 0, 1, 32)
