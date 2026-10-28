"""Linking instances: an import taken from the export of another instance (a function, a global, a memory), between modules of either front end —
two extensions, two wrappers for ctypes, and an extension with a wrapper (in both directions). The same scenarios as `test_features.py` has for
extensions, run on every pair, so that the front ends are proved to link with each other and the same way."""

from __future__ import annotations

import gc
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .test_features import (  # pyright: ignore[reportPrivateUsage]
    _COUNTER_A,  # pyright: ignore[reportPrivateUsage]
    _COUNTER_B,  # pyright: ignore[reportPrivateUsage]
    _FUNCS_A,  # pyright: ignore[reportPrivateUsage]
    _FUNCS_B,  # pyright: ignore[reportPrivateUsage]
    _MEMORY_A,  # pyright: ignore[reportPrivateUsage]
    _MEMORY_B,  # pyright: ignore[reportPrivateUsage]
)

Builder = Callable[..., ModuleType]
PAIRS = [("extension", "extension"), ("ctypes", "ctypes"), ("extension", "ctypes"), ("ctypes", "extension")]


@pytest.fixture(params=PAIRS, ids=["-".join(p) for p in PAIRS])
def modules(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Callable[..., tuple[ModuleType, ...]]:
    """`modules(a=wat, b=wat)`: the modules, the first of the pair in the front end of the exporter and the others in that of the importer."""
    exporter, importer = request.param
    builders = {
        "extension": request.getfixturevalue("build_extension"),
        "ctypes": request.getfixturevalue("build_ctypes"),
    }
    out = tmp_path_factory.mktemp("link")

    def make(**wats: str) -> tuple[ModuleType, ...]:
        built: list[ModuleType] = []
        for i, (name, wat) in enumerate(wats.items()):
            front = exporter if i == 0 else importer
            source = out / f"{name}_{front}.wat"
            source.write_text(wat, encoding="utf-8")
            built.append(builders[front](source, f"lk_{name}_{front}_{abs(hash(wat)) % 10**6}"))
        return tuple(built)

    return make


def test_instances_share_a_mutable_global_and_an_instance_is_a_mapping(modules: Callable[..., tuple[Any, ...]]) -> None:
    a_mod, b_mod = modules(a=_COUNTER_A, b=_COUNTER_B)
    a = a_mod.Instance(a_mod.Store())
    assert sorted(a.__exports__) == sorted(["counter", "fixed", "wide", "bump", "log"])
    said: list[int] = []
    shelf = {**a.__exports__, "log": said.append}  # everything of a, and log from Python (the later key wins)
    b = b_mod.Instance(b_mod.Store(), imports={"env": shelf})
    assert (b.read(), b.fixed()) == (10, 7)  # the global of a, seen from b
    assert (b.add(5), a.counter, a.bump(), b.read()) == (15, 15, 16, 16)  # one variable
    a.counter = 100
    assert b.read() == 100
    b.say(3)
    assert said == [3]  # log came from Python, not from a
    c = b_mod.Instance(
        b_mod.Store(), imports={"env": {"counter": a["counter"], "fixed": 5, "log": print}}
    )  # one export of a, the rest by hand
    assert (c.read(), c.fixed()) == (100, 5)
    del a, shelf
    gc.collect()
    assert b.add(1) == 101  # a is kept alive by b


def test_the_whole_instance_is_a_shelf(modules: Callable[..., tuple[Any, ...]]) -> None:
    a_mod, b_mod = modules(a=_FUNCS_A, b=_FUNCS_B)
    a = a_mod.Instance(a_mod.Store())
    b = b_mod.Instance(b_mod.Store(), imports={"env": a})
    assert b.sum(2, 3) == 5


def test_linking_a_global_checks_what_it_is(modules: Callable[..., tuple[Any, ...]]) -> None:
    a_mod, b_mod = modules(a=_COUNTER_A, b=_COUNTER_B)
    a = a_mod.Instance(a_mod.Store())

    def attempt(counter: Any, fixed: Any = 5) -> str:
        try:
            b_mod.Instance(b_mod.Store(), imports={"env": {"counter": counter, "fixed": fixed, "log": print}})
        except b_mod.LinkError as exc:
            return str(exc)
        return "linked"

    assert "mutable global" in attempt(3) and "export of another instance" in attempt(
        3
    )  # a mutable global is not given as a number
    assert "another type" in attempt(a["wide"])  # i64, the module wants i32
    assert "another type" in attempt(a["fixed"])  # immutable, the module wants mutable
    assert "global: the export given is not" in attempt(a["bump"])  # a function
    assert "another type" in attempt(a["counter"], a["wide"])  # an i64 for an i32
    assert attempt(a["counter"], a["fixed"]) == "linked"  # an immutable global of a for an immutable import
    with pytest.raises(KeyError, match="nothing"):
        a["nothing"]


def test_instances_call_each_others_functions(modules: Callable[..., tuple[Any, ...]]) -> None:
    a_mod, b_mod = modules(a=_FUNCS_A, b=_FUNCS_B)
    a = a_mod.Instance(a_mod.Store())
    b = b_mod.Instance(b_mod.Store(), imports={"env": a})  # the whole shelf from an instance
    assert b.sum(2, 3) == 5
    b.tell(42)
    assert a.seen() == 42  # a void function of a
    assert b.twin(7) == (7, 8)  # several results
    c = b_mod.Instance(b_mod.Store(), imports={"env": {**a.__exports__}})  # unpacked references
    assert c.sum(10, 20) == 30
    d = b_mod.Instance(
        b_mod.Store(), imports={"env": {"add": a.add, "note": a["note"], "pair": a.pair, "boom": a["boom"]}}
    )  # a bound method stands for its export
    assert d.sum(1, 1) == 2
    with pytest.raises(RuntimeError, match="(?i)unreachable") as raised:  # the trap of a, raised through b
        b.explode()
    assert isinstance(raised.value, (a_mod.Trap, b_mod.Trap))
    assert (b.sum(4, 4), a.add(1, 2)) == (8, 3)  # both are usable afterwards
    with pytest.raises(RuntimeError):
        b.explode()


def test_linking_a_function_checks_its_signature(modules: Callable[..., tuple[Any, ...]]) -> None:
    a_mod, b_mod = modules(a=_FUNCS_A, b=_FUNCS_B)
    refs = a_mod.Instance(a_mod.Store()).__exports__
    with pytest.raises(b_mod.LinkError) as raised:
        b_mod.Instance(
            b_mod.Store(), imports={"env": {**refs, "add": refs["note"]}}
        )  # note(i32), add wants (i32, i32) -> i32
    assert "import env.add is a function ii>i" in str(raised.value) and "(i>)" in str(raised.value)


def test_an_exception_of_a_function_of_another_instance_comes_out_of_the_call(
    modules: Callable[..., tuple[Any, ...]],
) -> None:
    """The Python function behind an import of `a` raises: `b` calls `a`, and the very object comes out of the call of `b`."""
    a_mod, b_mod = modules(
        a='(module (import "env" "fail" (func $f (result i32))) (func (export "boom") (result i32) call $f))',
        b='(module (import "env" "boom" (func $boom (result i32))) (func (export "explode") (result i32) call $boom))',
    )

    def fail() -> int:
        raise ValueError("from the function of a")

    a = a_mod.Instance(a_mod.Store(), imports={"env": {"fail": fail}})
    b = b_mod.Instance(b_mod.Store(), imports={"env": a})
    with pytest.raises(ValueError, match="from the function of a"):
        b.explode()


def test_instances_share_a_memory(modules: Callable[..., tuple[Any, ...]]) -> None:
    a_mod, b_mod = modules(a=_MEMORY_A, b=_MEMORY_B)
    a = a_mod.Instance(a_mod.Store())
    b = b_mod.Instance(b_mod.Store(), imports={"env": a})  # the shelf from an instance
    assert (chr(b.load(0)), len(a.memory)) == ("h", 65536)
    b.store(1, 65)
    assert bytes(a.memory[:5]) == b"hAllo"  # one memory
    a.memory[2] = 66
    assert b.load(2) == 66
    assert (b.grow(1), len(a.memory)) == (1, 131072)  # a grows with b
    c = b_mod.Instance(b_mod.Store(), imports={"env": {"memory": a.memory}})  # a memoryview of the memory stands for it
    d = b_mod.Instance(b_mod.Store(), imports={"env": {"memory": a["memory"]}})  # or the reference
    assert (c.load(1), d.load(1)) == (65, 65)


def test_linking_a_memory_checks_its_size_and_kind(modules: Callable[..., tuple[Any, ...]]) -> None:
    a_mod, big, small, wide, other = modules(
        a=_MEMORY_A,
        big='(module (import "env" "memory" (memory 2)))',
        small='(module (import "env" "memory" (memory 1 2)))',
        wide='(module (import "env" "memory" (memory i64 1)))',
        other='(module (import "env" "memory" (memory 1)) (global (export "g") i32 (i32.const 1)))',
    )
    a = a_mod.Instance(a_mod.Store())
    messages: list[str] = []
    for module, given in ((big, a.memory), (small, a.memory), (wide, a.memory), (other, 3)):
        with pytest.raises(module.LinkError) as raised:
            module.Instance(module.Store(), imports={"env": {"memory": given}})
        messages.append(str(raised.value))
    assert "1 pages" in messages[0] and "at least 2" in messages[0]
    assert "may grow to 4 pages" in messages[1] and "allows 2" in messages[1]
    assert "memory64" in messages[2]
    assert "is a memory" in messages[3]


def test_an_imported_immutable_global_is_a_number(modules: Callable[..., tuple[Any, ...]]) -> None:
    (mod,) = modules(
        m='(module (import "env" "limit" (global i32)) (import "env2" "scale" (global f64)) (import "env" "big" (global i64))'
        ' (func (export "limit") (result i32) global.get 0) (func (export "scale") (result f64) global.get 1)'
        ' (func (export "big") (result i64) global.get 2))'
    )
    imports: dict[str, dict[str, Any]] = {"env": {"limit": 100, "big": -(2**40)}, "env2": {"scale": 2.5}}
    i = mod.Instance(mod.Store(), imports=imports)
    assert (i.limit(), i.scale(), i.big()) == (100, 2.5, -1099511627776)
    imports["env"]["limit"] = 7  # the value was taken when the instance was made
    assert (i.limit(), mod.Instance(mod.Store(), imports=imports).limit()) == (100, 7)
    assert (
        mod.Instance(mod.Store(), imports={"env": {"limit": 2**32 + 3, "big": 1}, "env2": {"scale": 1}}).limit() == 3
    )  # wraps, an int is a number
    for bad in (
        {"env2": {"scale": 1}, "env": {"big": 1}},  # missing
        {"env": {"limit": "x", "big": 1}, "env2": {"scale": 1}},  # not a number
        {"env": {"limit": 1.5, "big": 1}, "env2": {"scale": 1}},  # a float for an i32
        {"env": {"limit": 1, "big": 1}, "env2": {"scale": print}},  # a function for a global
    ):
        with pytest.raises(mod.LinkError):
            mod.Instance(mod.Store(), imports=bad)


def test_exports_named_like_the_methods_of_instance_are_reached_by_name(
    modules: Callable[..., tuple[Any, ...]],
) -> None:
    (mod,) = modules(
        m='(module (func (export "keys") (result i32) i32.const 1) (func (export "__class__") (result i32) i32.const 2)'
        ' (func (export "__init__") (result i32) i32.const 3) (func (export "ok") (result i32) i32.const 4))'
    )
    i = mod.Instance(mod.Store())
    assert (i.__class__.__name__, i.ok(), i.keys(), sorted(i.__exports__)) == (
        "Instance",
        4,
        1,
        ["__class__", "__init__", "keys", "ok"],
    )
    # a reference to an export: a capsule from an extension, an object that gives one (`__wasmext_ref__`) from the wrapper for ctypes
    references = {"PyCapsule", "_Reference"}
    assert {type(i[name]).__name__ for name in ("__class__", "__init__")} <= references
    assert type(i.__exports__["keys"]).__name__ in references


def test_a_wrapper_keeps_the_instance_it_uses_alive(modules: Callable[..., tuple[Any, ...]], tmp_path: Path) -> None:
    del tmp_path
    a_mod, b_mod = modules(a=_MEMORY_A, b=_MEMORY_B)
    a = a_mod.Instance(a_mod.Store())
    b = b_mod.Instance(b_mod.Store(), imports={"env": a})
    del a
    gc.collect()
    assert chr(b.load(0)) == "h"  # the memory of a is still there


_NAMES = ("add", "note", "pair", "boom")  # what the module b imports from a


def _record_of(reference: Any) -> tuple[bytes, Any]:
    """The name of the capsule and the record that it holds, as a ctypes structure over the memory of the record."""
    import ctypes

    if type(reference).__name__ != "PyCapsule":
        pytest.skip("only the extension for CPython hands out a capsule; the wrapper for ctypes passes its own record")

    class Record(ctypes.Structure):
        _fields_ = [
            ("size", ctypes.c_uint32), ("abi", ctypes.c_uint32), ("kind", ctypes.c_uint32), ("type", ctypes.c_uint32), ("flags", ctypes.c_uint32),
            ("owner", ctypes.c_void_p), ("address", ctypes.c_void_p), ("instance", ctypes.c_void_p),
            ("signature", ctypes.c_char_p), ("runtime", ctypes.c_uint32), ("funcref", ctypes.c_void_p), ("floor", ctypes.c_uint32),
        ]  # fmt: skip

    api = ctypes.pythonapi
    api.PyCapsule_GetName.restype = ctypes.c_char_p
    api.PyCapsule_GetName.argtypes = [ctypes.py_object]
    api.PyCapsule_GetPointer.restype = ctypes.c_void_p
    api.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
    name = api.PyCapsule_GetName(reference)
    address = api.PyCapsule_GetPointer(reference, name)
    assert address is not None
    return name, Record.from_address(address)


def test_an_export_of_another_x_is_not_linked(modules: Callable[..., tuple[Any, ...]]) -> None:
    """The record carries the ABI of the wasmext that made it, and the capsule has its x in the name: an export of another x is refused with a reason."""
    from wasmext._abi import ABI, capsule_name  # pyright: ignore[reportPrivateUsage]

    a_mod, b_mod = modules(a=_FUNCS_A, b=_FUNCS_B)
    a = a_mod.Instance(a_mod.Store())
    imports = {"env": {name: a[name] for name in _NAMES}}
    name, record = _record_of(imports["env"]["add"])
    assert name == capsule_name().encode()  # x is in the name
    assert record.abi == ABI
    record.abi = ABI + (1 << 24)  # another x
    with pytest.raises(b_mod.LinkError, match="incompatible"):
        b_mod.Instance(b_mod.Store(), imports=imports)


@pytest.mark.parametrize("step", [1, 0x100, 0x10000])  # the serial, z, y: something that is not x
def test_an_export_of_another_y_z_or_serial_is_linked(modules: Callable[..., tuple[Any, ...]], step: int) -> None:
    from wasmext._abi import ABI  # pyright: ignore[reportPrivateUsage]

    a_mod, b_mod = modules(a=_FUNCS_A, b=_FUNCS_B)
    a = a_mod.Instance(a_mod.Store())
    imports = {"env": {name: a[name] for name in _NAMES}}
    _name, record = _record_of(imports["env"]["add"])
    record.abi = ABI + step
    assert b_mod.Instance(b_mod.Store(), imports=imports) is not None  # linked: the record is accepted


def test_a_record_is_refused_by_a_reader_below_its_floor(modules: Callable[..., tuple[Any, ...]]) -> None:
    """The floor is the lowest version of a reader that can use the record: a reader below it refuses, a reader at it or above it links."""
    from wasmext._abi import ABI  # pyright: ignore[reportPrivateUsage]

    a_mod, b_mod = modules(a=_FUNCS_A, b=_FUNCS_B)
    a = a_mod.Instance(a_mod.Store())
    imports = {"env": {name: a[name] for name in _NAMES}}
    _name, record = _record_of(imports["env"]["add"])
    assert record.floor <= ABI  # a record made by this wasmext can be read by it
    record.floor = ABI + 0x100  # a version of the reader that is not this one
    with pytest.raises(b_mod.LinkError, match="incompatible"):
        b_mod.Instance(b_mod.Store(), imports=imports)
    record.floor = ABI  # this one
    b_mod.Instance(b_mod.Store(), imports=imports)


def test_the_name_of_an_import_with_percent_quote_and_backslash_is_in_the_message_as_it_is(
    modules: Callable[..., tuple[Any, ...]],
) -> None:
    """The message of a link that fails is made by C from a format string: a name with `%`, `"` or `\\` must not change the format or break the C."""
    a_mod, b_mod = modules(
        a='(module (func (export "note") (param i32)))',
        b=r'(module (import "env" "we%s\22ird\5c%d" (func (param i32 i32) (result i32))) (func (export "go") (result i32) i32.const 0 i32.const 0 call 0))',
    )
    refs = a_mod.Instance(a_mod.Store()).__exports__
    name = 'we%s"ird\\%d'
    with pytest.raises(b_mod.LinkError) as raised:
        b_mod.Instance(b_mod.Store(), imports={"env": {name: refs["note"]}})
    assert f"import env.{name} is a function ii>i" in str(raised.value)
