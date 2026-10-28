"""A function of one instance that makes a call of WASI, called from another instance (a table that one module exports and another imports, or an imported function).

The call runs in the instance it belongs to: the memory it reads is that instance's, the stream it writes to is that instance's store's, and the end of the other store does not touch it.
This is what `fusedwasi_p2_bind_memory` per guest (one guest for each instance) has to give with no help from a registry of owners (C2b/C2c), and these tests say so before that registry is built.
On every pair of front ends (an extension or the wrapper for ctypes, for the owner and for the user).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest

Builder = Callable[..., ModuleType]
PAIRS = [("extension", "extension"), ("ctypes", "ctypes"), ("extension", "ctypes"), ("ctypes", "extension")]

# both write 7 bytes found at the same address of their own memory (100) to descriptor 1, through an iovec at 0 of that memory; the bytes differ
_WRITER = """
(module
  (import "wasi_snapshot_preview1" "fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_close" (func $fd_close (param i32) (result i32)))
  (memory (export "memory") 1)
  (data (i32.const 100) "{who}")
  {imports}
  (table (export "tab") {size} funcref)
  (func $say (export "say") (result i32)
    (i32.store (i32.const 0) (i32.const 100))
    (i32.store (i32.const 4) (i32.const 7))
    (call $fd_write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 32)))
  (func (export "close_1") (result i32) (call $fd_close (i32.const 1)))
  (func $peek (export "peek") (result i32) (i32.load8_u (i32.const 100)))
  (elem (i32.const 0) func $say $peek)
  {extra})
"""

_OWNER = _WRITER.format(who="from A!", imports="", size=2, extra="")

# the user: its own writer, the table of the owner (slot 0 is the owner's `say`) and a function of the owner imported by name
_USER = """
(module
  (type $t (func (result i32)))
  (import "wasi_snapshot_preview1" "fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))
  (import "env" "tab" (table 2 funcref))
  (import "env" "say" (func $owner_say (result i32)))
  (memory (export "memory") 1)
  (data (i32.const 100) "from B!")
  (func (export "own") (result i32)
    (i32.store (i32.const 0) (i32.const 100))
    (i32.store (i32.const 4) (i32.const 7))
    (call $fd_write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 32)))
  (func (export "through_table") (param i32) (result i32) local.get 0 call_indirect (type $t))
  (func (export "through_import") (result i32) call $owner_say))
"""


@pytest.fixture(params=PAIRS, ids=["-".join(p) for p in PAIRS])
def modules(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Any]:
    owner_front, user_front = request.param
    out = tmp_path_factory.mktemp("across")
    built: list[Any] = []
    for name, front, text in (("wa_owner", owner_front, _OWNER), ("wa_user", user_front, _USER)):
        source = out / f"{name}_{front}.wat"
        source.write_text(text, encoding="utf-8")
        builder: Builder = request.getfixturevalue("build_extension" if front == "extension" else "build_ctypes")
        built.append(functools.partial(builder, host="wasm32-wasip1")(source, f"{name}_{front}"))
    return built[0], built[1]


@pytest.fixture(autouse=True)
def _known_gap(request: pytest.FixtureRequest) -> None:
    """An extension that owns the function and a wrapper for ctypes that calls it through a table: a Python callback inside the function (the stream of the store is one) traps.
    It does not need WASI: `test_a_python_callback_in_a_table_function` has the same with no call of WASI in it. It is a gap of the front ends, not of fusedwasi."""
    writes = (
        "a_function_in_the_table_of_another_instance",
        "end_of_the_store_of_the_user",
    )  # the tests in which the function reaches the stream (a Python function) through the table
    name: str = getattr(request.node, "name", "")  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType, reportUnknownMemberType]
    if "extension-ctypes" in name and any(w in name for w in writes):
        request.applymarker(
            pytest.mark.xfail(
                strict=False,
                reason="a Python callback in a table function of an extension called from a wrapper for ctypes traps",
            )
        )


def _pair(modules: tuple[Any, Any]) -> tuple[Any, Any, list[bytes], list[bytes], Any, Any]:
    owner_mod, user_mod = modules
    from_a: list[bytes] = []
    from_b: list[bytes] = []
    store_a = owner_mod.Store(wasi={"stdout": from_a.append})
    store_b = user_mod.Store(wasi={"stdout": from_b.append})
    a = owner_mod.Instance(store_a)
    b = user_mod.Instance(store_b, imports={"env": {"tab": a["tab"], "say": a["say"]}})
    return a, b, from_a, from_b, store_a, store_b


def test_a_function_in_the_table_of_another_instance_writes_its_own_memory_to_its_own_store(
    modules: tuple[Any, Any],
) -> None:
    a, b, from_a, from_b, _, _ = _pair(modules)
    assert b.through_table(0) == 0  # the `say` of a, called from b
    assert from_a == [b"from A!"] and from_b == []
    assert b.own() == 0
    assert from_a == [b"from A!"] and from_b == [b"from B!"]
    assert bytes(a.memory[100:107]) == b"from A!" and bytes(b.memory[100:107]) == b"from B!"


def test_an_imported_function_of_another_instance_writes_its_own_memory_to_its_own_store(
    modules: tuple[Any, Any],
) -> None:
    a, b, from_a, from_b, _, _ = _pair(modules)
    assert b.through_import() == 0
    assert from_a == [b"from A!"] and from_b == []
    assert b.own() == 0 and from_b == [b"from B!"]
    assert a.say() == 0 and from_a == [b"from A!", b"from A!"]


def test_the_end_of_the_store_of_the_user_does_not_touch_the_owner(modules: tuple[Any, Any]) -> None:
    a, b, from_a, from_b, _, store_b = _pair(modules)
    assert b.through_table(0) == 0
    store_b.close()
    assert a.say() == 0
    assert from_a == [b"from A!", b"from A!"] and from_b == []


def test_the_descriptors_are_the_owners_when_the_owner_runs_the_function(modules: tuple[Any, Any]) -> None:
    """A descriptor closed by the owner is closed for its function even when another instance calls it: the table of descriptors is that of the store the function belongs to."""
    a, b, from_a, from_b, _, _ = _pair(modules)
    assert b.own() == 0 and from_b == [b"from B!"]  # b has its descriptor 1 ...
    assert a.close_1() == 0  # ... and a closes the descriptor 1 of its store
    assert b.through_table(0) == 8  # EBADF in the function of a, called from b
    assert b.own() == 0 and from_b == [b"from B!", b"from B!"]  # the descriptor 1 of b is open
    assert from_a == []


def test_the_store_of_the_owner_closed_gives_ebadf_to_the_function_called_from_another_instance(
    modules: tuple[Any, Any],
) -> None:
    _, b, from_a, from_b, store_a, _ = _pair(modules)
    store_a.close()
    assert b.through_table(0) == 8  # EBADF: the state is closed (it stays closed), nothing is written
    assert from_a == [] and b.own() == 0 and from_b == [b"from B!"]


# The same gap with no WASI in it: a function of the owner that calls a Python function, called through the table of the owner by another instance.
_OWNER_CALLBACK = """
(module
  (import "env" "log" (func $log (param i32)))
  (memory (export "memory") 1)
  (table (export "tab") 2 funcref)
  (func $f (export "f") (result i32) (call $log (i32.const 42)) (i32.const 1))
  (elem (i32.const 0) func $f))
"""
_USER_CALLBACK = """
(module
  (type $t (func (result i32)))
  (import "env" "tab" (table 2 funcref))
  (memory (export "memory") 1)
  (func (export "through_table") (param i32) (result i32) local.get 0 call_indirect (type $t)))
"""


@pytest.fixture(params=PAIRS, ids=["-".join(p) for p in PAIRS])
def callback_modules(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Any]:
    owner_front, user_front = request.param
    out = tmp_path_factory.mktemp("callback")
    built: list[Any] = []
    for name, front, text in (
        ("cb_owner", owner_front, _OWNER_CALLBACK),
        ("cb_user", user_front, _USER_CALLBACK),
    ):
        source = out / f"{name}_{front}.wat"
        source.write_text(text, encoding="utf-8")
        builder: Builder = request.getfixturevalue("build_extension" if front == "extension" else "build_ctypes")
        built.append(builder(source, f"{name}_{front}"))
    return built[0], built[1]


def test_a_python_callback_in_a_table_function(
    callback_modules: tuple[Any, Any], request: pytest.FixtureRequest
) -> None:
    name: str = getattr(request.node, "name", "")  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType, reportUnknownMemberType]
    if "extension-ctypes" in name:
        request.applymarker(
            pytest.mark.xfail(
                strict=False,
                reason="a Python callback in a table function of an extension called from a wrapper for ctypes traps",
            )
        )
    owner_mod, user_mod = callback_modules
    seen: list[int] = []
    a = owner_mod.Instance(owner_mod.Store(), imports={"env": {"log": seen.append}})
    b = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": a["tab"]}})
    assert a.f() == 1 and seen == [42]
    assert b.through_table(0) == 1 and seen == [42, 42]
