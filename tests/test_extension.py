"""The generated extension, built and imported: calls, number types, imports, traps, memory, re-entry, lifetime."""

from __future__ import annotations

import gc
import subprocess
import weakref
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from wasmext import generate, parse

from .conftest import DATA

Builder = Callable[..., ModuleType]


@pytest.fixture(scope="module")
def ext(build_front_end: Builder, front_end: str) -> Any:
    """The module `features.wasm` in each front end: the tests below are the proof that they have one interface."""
    return build_front_end(DATA / "features.wasm", f"features_{front_end}")


def _ignore(_x: int) -> None:
    pass


def _twice(x: float) -> float:
    return x * 2


def _nothing() -> None:
    pass


def _text(_x: float) -> str:
    return "text"


def make(ext: Any, **overrides: Callable[..., Any]) -> Any:
    env: dict[str, Callable[..., Any]] = {
        "log": _ignore,
        "twice": _twice,
        "cb": _nothing,
    }
    env.update(overrides)
    return ext.Instance({"env": env})


def test_the_committed_wasm_is_the_wat(wabt: Path, tmp_path: Path) -> None:
    out = tmp_path / "features.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "features.wat", "-o", out], check=True)
    assert out.read_bytes() == (DATA / "features.wasm").read_bytes()


def test_the_glue_skips_what_it_cannot_expose() -> None:
    glue = generate(parse((DATA / "features.wasm").read_bytes()), "features_ext")
    assert glue.skipped == []  # the table is a funcref table: another instance can import it


def test_integers_wrap_as_webassembly_does(ext: Any) -> None:
    inst = make(ext)
    assert inst.add(3, 4) == 7
    assert inst.add(0xFFFFFFFF, 2) == 1
    assert inst.add(-1, 2) == 1  # a negative number is its two's complement
    assert inst.add(2**32 + 5, 0) == 5
    assert inst.add(2**31 - 1, 1) == -(2**31)  # the result is signed, as in the JavaScript API
    assert inst.add(0xFFFFFFFF, 0) == -1
    assert inst.mul64(2**40, 2**30) == 0  # 2**70 wraps
    assert inst.mul64(-1, 3) == -3


def test_several_results_come_back_as_a_tuple(ext: Any) -> None:
    assert make(ext).pair() == (1, 2)


def test_floats(ext: Any) -> None:
    inst = make(ext)
    assert inst.fadd(1.5, 2.25) == 3.75
    assert inst.fadd(0.1, 0.2) != pytest.approx(0.30000000000000004, abs=1e-12)  # f32: rounded to single precision
    assert inst.dbl(1.25) == 2.5
    assert inst.dbl(2) == 4.0  # an int is accepted where a float is wanted


def test_wrong_arguments_are_type_errors(ext: Any) -> None:
    inst = make(ext)
    with pytest.raises(TypeError, match=r"add\(\) takes exactly 2 arguments \(1 given\)"):
        inst.add(1)
    with pytest.raises(TypeError):
        inst.add("x", 1)
    with pytest.raises(TypeError):
        inst.add(1.5, 1)
    with pytest.raises(TypeError, match=r"nop\(\) takes exactly 0 arguments"):
        inst.nop(1)
    assert inst.nop() is None


def test_methods_have_their_signature_in_the_docstring(ext: Any) -> None:
    assert ext.Instance.add.__doc__ == "add(i32, i32) -> i32"
    assert ext.Instance.nop.__doc__ == "nop() -> None"


def test_imports_are_called(ext: Any) -> None:
    log: list[int] = []
    inst = make(ext, log=log.append)
    inst.say(5)
    inst.say(0xFFFFFFFF + 3)
    assert log == [5, 2]


def test_missing_imports_are_link_errors(ext: Any) -> None:
    with pytest.raises(ext.LinkError, match="pass imports"):
        ext.Instance()
    with pytest.raises(ext.LinkError, match="missing import module 'env'"):
        ext.Instance({})
    with pytest.raises(ext.LinkError, match=r"missing import 'env.twice'"):
        ext.Instance({"env": {"log": print, "cb": print}})
    with pytest.raises(ext.LinkError, match=r"import 'env.log' is not callable"):
        ext.Instance({"env": {"log": 1, "twice": print, "cb": print}})


def test_a_trap_is_an_exception_and_the_instance_goes_on(ext: Any) -> None:
    inst = make(ext)
    with pytest.raises(ext.Trap, match="divide by zero"):
        inst.div(1, 0)
    assert issubclass(ext.Trap, RuntimeError)
    with pytest.raises(ext.Trap, match="(?i)unreachable"):
        inst.boom()
    assert inst.div(7, 2) == 3  # still usable
    assert inst.add(1, 1) == 2


def test_an_exception_of_an_import_comes_out_of_the_call(ext: Any) -> None:
    def fail(_x: int) -> None:
        raise ValueError("from the import")

    inst = make(ext, log=fail)
    with pytest.raises(ValueError, match="from the import"):
        inst.say(1)
    assert inst.add(1, 2) == 3


def test_an_import_that_returns_the_wrong_thing(ext: Any) -> None:
    inst = make(ext, twice=_text)
    with pytest.raises(TypeError):
        inst.dbl(1.0)
    assert inst.add(1, 2) == 3


def test_an_import_may_call_back_into_the_module(ext: Any) -> None:
    seen: list[int] = []
    box: dict[str, Any] = {}

    def cb() -> None:
        seen.append(box["inst"].add(20, 22))  # a nested call of the same instance; it leaves the outer one intact

    inst = make(ext, cb=cb)
    box["inst"] = inst
    with pytest.raises(
        ext.Trap, match="(?i)unreachable"
    ):  # the outer call traps after the callback: its jump buffer was kept
        inst.reenter()
    assert seen == [42]


def test_memory_is_a_writable_memoryview(ext: Any) -> None:
    inst = make(ext)
    mem: memoryview[int] = inst.mem
    assert isinstance(mem, memoryview) and not mem.readonly
    assert len(mem) == 65536
    assert bytes(mem[:2]) == b"hi"
    mem[2:4] = b"!?"
    assert bytes(inst.mem[:4]) == b"hi!?"
    other = make(ext)
    assert bytes(other.mem[:4]) == b"hi\0\0"  # instances do not share memory


def test_memory_grows_and_a_new_view_sees_it(ext: Any) -> None:
    inst = make(ext)
    assert inst.grow(1) == 1
    assert len(inst.mem) == 2 * 65536
    assert inst.grow(5) == -1  # beyond the maximum of 3 pages
    assert len(inst.mem) == 2 * 65536


def test_a_memoryview_keeps_its_instance_alive(ext: Any) -> None:
    inst = make(ext)
    mem = inst.mem
    ref = weakref.ref(inst)
    del inst
    gc.collect()
    assert bytes(mem[:2]) == b"hi"  # the memory is still there
    del mem
    gc.collect()
    assert ref() is None


def test_a_cycle_through_an_import_is_collected(ext: Any) -> None:
    def build_cycle() -> weakref.ref[Any]:
        box: dict[str, Any] = {}
        inst = make(ext, cb=lambda: box["inst"])  # the callable reaches the instance, which holds the callable
        box["inst"] = inst
        return weakref.ref(inst)

    gc.disable()
    try:
        ref = build_cycle()
        assert ref() is not None  # nothing but the collector can free it
        gc.collect()
        assert ref() is None
    finally:
        gc.enable()


def test_the_module_without_imports_takes_no_arguments(build_front_end: Builder, front_end: str) -> None:
    simple = build_front_end(DATA / "simple.wasm", f"simple_{front_end}")
    assert simple.Instance().add(3, 4) == 7
    with pytest.raises(TypeError):
        simple.Instance({"env": {}})
    if front_end == "extension":
        assert simple.Instance.__module__ == "simple_extension"


def test_an_exception_that_nothing_catches_is_an_uncaught_exception_with_its_tag_and_values(
    build_front_end: Callable[..., ModuleType],
    front_end: str,
) -> None:
    mod: Any = build_front_end(DATA / "exceptions.wat", f"exceptions_{front_end}")
    inst = mod.Instance()
    assert inst.caught() == 8 and inst.ok() == 5  # an exception that a `try` of the module catches is not seen
    with pytest.raises(mod.UncaughtException) as one:
        inst.throw_one(-9)
    assert one.value.tag == 0 and one.value.values == (-9,)
    with pytest.raises(mod.UncaughtException) as many:
        inst.throw_many()
    assert many.value.tag == 1 and many.value.values == (-5, 1.5, 2.25, -1)
    with pytest.raises(mod.UncaughtException) as bare:
        inst.throw_bare()
    assert bare.value.tag == 2 and bare.value.values == ()
    assert isinstance(bare.value, mod.Trap) and "ncaught" in str(bare.value)  # code that catches Trap goes on working
    assert inst.ok() == 5  # the instance is usable afterwards


def test_imports_of_several_modules_are_bound_by_the_name_of_the_module_not_by_the_order(
    build_front_end: Builder, front_end: str, tmp_path: Path
) -> None:
    """wasm2c takes the import modules in the order of their names; a module that imports "z" before "a" must still call each import of its own."""
    wat = tmp_path / "order.wat"
    wat.write_text(
        '(module (import "z" "f" (func $f (result i32))) (import "a" "g" (func $g (result i32)))'
        ' (func (export "callf") (result i32) call $f) (func (export "callg") (result i32) call $g))',
        encoding="utf-8",
    )
    mod = build_front_end(wat, f"order_{front_end}")
    inst = mod.Instance({"z": {"f": lambda: 1}, "a": {"g": lambda: 2}})
    assert (inst.callf(), inst.callg()) == (1, 2)


def test_a_wasi_module_with_imports_of_its_own_still_reaches_wasi(
    build_front_end: Builder, front_end: str, tmp_path: Path
) -> None:
    """The usual layout of a WASI program that has host imports: proc_exit of WASI first, then "env": the exit code must come from the call of env."""
    wat = tmp_path / "wasienv.wat"
    wat.write_text(
        '(module (import "wasi_snapshot_preview1" "proc_exit" (func $exit (param i32)))'
        ' (import "env" "get" (func $get (result i32))) (memory (export "memory") 1)'
        ' (func (export "_start") (call $exit (call $get))))',
        encoding="utf-8",
    )
    mod = build_front_end(wat, f"wasienv_{front_end}")
    inst = mod.Instance({"env": {"get": lambda: 5}})
    with pytest.raises(mod.WasiExit) as raised:
        inst._start()  # pyright: ignore[reportPrivateUsage]
    assert raised.value.code == 5


def test_a_table_that_cannot_be_allocated_is_a_memory_error(
    build_front_end: Builder, front_end: str, tmp_path: Path
) -> None:
    """The runtime of wasm2c does not check the allocation of a table; wasmext tries the same allocation first, so that it is an error of memory and not a NULL."""
    wat = tmp_path / "bigtable.wat"
    wat.write_text(
        '(module (table i64 1152921504606846976 funcref) (func (export "f") (result i32) i32.const 1))',
        encoding="utf-8",
    )
    mod = build_front_end(wat, f"bigtable_{front_end}")
    with pytest.raises(MemoryError):
        mod.Instance()


def test_odd_names_of_exports_and_imports_cannot_break_the_generated_c(
    build_front_end: Builder, front_end: str, tmp_path: Path
) -> None:
    """A name of the module is data, never C: `*/` and a line end in a name, a name with a null character, and the names `export` and ``."""
    wat = tmp_path / "odd.wat"
    wat.write_text(
        r"""(module
  (func (export "a*/ static int injected_by_name(void){return 77;} /*") (result i32) i32.const 1)
  (func (export "line\n*/ int x;") (result i32) i32.const 2)
  (func (export "export") (result i32) i32.const 3)
  (func (export "") (result i32) i32.const 4)
  (func (export "a\00b") (result i32) i32.const 5)
  (func (export "a") (result i32) i32.const 6))""",
        encoding="utf-8",
    )
    mod = build_front_end(wat, f"odd_{front_end}")
    inst = mod.Instance()
    assert inst.a() == 6  # not the function behind "a\0b", which is left out
    assert getattr(inst, "a*/ static int injected_by_name(void){return 77;} /*")() == 1
    assert getattr(inst, "line\n*/ int x;")() == 2
    assert (inst.export(), getattr(inst, "")()) == (3, 4)
    assert "a\x00b" not in inst.__exports__


def test_a_null_character_in_the_name_of_an_import_is_refused(tmp_path: Path, wabt: Path) -> None:
    from wasmext import GenError, generate, parse

    wat = tmp_path / "nul.wat"
    wat.write_text(r'(module (import "env" "f\00g" (func)))', encoding="utf-8")
    wasm = tmp_path / "nul.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    with pytest.raises(GenError, match="null character"):
        generate(parse(wasm.read_bytes()), "nul")


@pytest.mark.skipif(not Path("/proc/self/status").is_file(), reason="the size of the address space is read from /proc")
@pytest.mark.parametrize(
    "wat",
    [
        '(module (memory 1) (start $s) (func $s unreachable) (func (export "f")))',
        '(module (memory 1) (data (i32.const 70000) "x") (func (export "f")))',
    ],
    ids=["start", "data"],
)
def test_an_instance_that_could_not_be_made_gives_its_memory_back(
    build_front_end: Builder, front_end: str, tmp_path: Path, wat: str
) -> None:
    """Every failed `Instance()` used to leave the mapping of its memory (8 GiB of address space with guard pages)."""

    def megabytes() -> int:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmSize"):
                return int(line.split()[1]) // 1024
        return 0

    source = tmp_path / "fail.wat"
    source.write_text(wat, encoding="utf-8")
    mod = build_front_end(source, f"fail{abs(hash(wat)) % 10**6}_{front_end}")
    before = megabytes()
    for _ in range(50):
        with pytest.raises(RuntimeError):  # Trap
            mod.Instance()
    assert megabytes() - before < 1000, "the address space grew by the memories of the failed instances"


def test_a_tag_with_a_payload_larger_than_the_runtime_keeps_is_reported(wabt: Path, tmp_path: Path) -> None:
    params = " ".join(["i64"] * 40)  # 320 bytes; the runtime keeps 256
    wat = tmp_path / "bigtag.wat"
    wat.write_text(f'(module (tag $t (param {params})) (func (export "f") (result i32) i32.const 1))', encoding="utf-8")
    wasm = tmp_path / "bigtag.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    glue = generate(parse(wasm.read_bytes()), "bigtag")
    assert any("320 bytes" in note for note in glue.notes)


@pytest.mark.parametrize("guard_pages", [False, True], ids=["no guard pages", "guard pages"])
def test_a_memory_that_can_move_does_not_grow_while_a_memoryview_of_it_is_alive(
    build_front_end: Callable[..., ModuleType], front_end: str, tmp_path: Path, guard_pages: bool
) -> None:
    """Without guard pages the runtime reallocates the memory when it grows, and a memoryview would point to freed memory: while a view is
    alive memory.grow answers -1 (as bytearray refuses to be resized while it is exported); when the views are gone it grows."""
    wat = tmp_path / "grower.wat"
    wat.write_text(
        '(module (memory (export "mem") 1) (func (export "grow") (param i32) (result i32) local.get 0 memory.grow))',
        encoding="utf-8",
    )
    defines = () if guard_pages else ("WASM_RT_USE_MMAP=0",)
    mod: Any = build_front_end(wat, f"grower_{front_end}_{'guard' if guard_pages else 'noguard'}", defines=defines)
    inst = mod.Instance()
    view = inst.mem
    again = inst.mem
    if (
        guard_pages
    ):  # the memory does not move: growing is fine with a view alive (the view keeps its length; a new one is longer)
        assert inst.grow(1) == 1 and len(view) == 65536 and len(inst.mem) == 2 * 65536
        return
    assert inst.grow(1) == -1 and len(view) == 65536  # refused, and the view is still good
    view[0] = 7
    del view
    gc.collect()
    assert inst.grow(1) == -1  # a second view is still alive
    del again
    gc.collect()
    assert inst.grow(1) == 1 and len(inst.mem) == 2 * 65536  # none left: it grows
    gc.collect()
    held = inst.mem
    assert inst.grow(1) == -1
    held.release()
    del held
    gc.collect()
    assert inst.grow(1) == 2


_REACTOR = """(module
  (memory (export "mem") 1)
  (global $runs (mut i32) (i32.const 0))
  (func (export "_initialize")
    (global.set $runs (i32.add (global.get $runs) (i32.const 1)))
    (i32.store (i32.const 0) (i32.const 1234)))
  (func (export "runs") (result i32) global.get $runs)
  (func (export "peek") (result i32) (i32.load (i32.const 0))))"""


def test_a_reactor_is_initialized_once_when_the_instance_is_made(
    build_front_end: Builder, front_end: str, tmp_path: Path
) -> None:
    """WASI: a host runs `_initialize` of a reactor once, before any other export. Every front end does it, and an explicit call afterwards does nothing."""
    wat = tmp_path / "reactor.wat"
    wat.write_text(_REACTOR, encoding="utf-8")
    mod: Any = build_front_end(wat, f"reactor_{front_end}")
    inst = mod.Instance()
    assert (inst.runs(), inst.peek()) == (1, 1234)  # run by the instance, before the first export
    inst._initialize()  # a program written before it was automatic: it must not run the constructors again
    assert inst.runs() == 1
    other = mod.Instance()
    assert other.runs() == 1  # each instance is initialized, once


def test_a_trap_in_initialize_is_the_error_of_making_the_instance(
    build_front_end: Builder, front_end: str, tmp_path: Path
) -> None:
    wat = tmp_path / "reactor_trap.wat"
    wat.write_text(
        '(module (func (export "_initialize") unreachable) (func (export "f") (result i32) i32.const 1))',
        encoding="utf-8",
    )
    mod: Any = build_front_end(wat, f"reactor_trap_{front_end}")
    with pytest.raises(mod.Trap):
        mod.Instance()


def test_a_command_with_initialize_is_not_initialized_for_it(
    build_front_end: Builder, front_end: str, tmp_path: Path
) -> None:
    """A module with a `_start` is a command: nothing is run for it when it is made."""
    wat = tmp_path / "command.wat"
    wat.write_text(
        '(module (global $runs (mut i32) (i32.const 0)) (func (export "_initialize") (global.set $runs (i32.const 9)))'
        ' (func (export "_start")) (func (export "runs") (result i32) global.get $runs))',
        encoding="utf-8",
    )
    mod: Any = build_front_end(wat, f"command_{front_end}")
    inst = mod.Instance()
    assert inst.runs() == 0


def test_v128_in_signatures_is_16_bytes_in_each_front_end(build_front_end: Builder, front_end: str) -> None:
    """A v128 in an export or an import: 16 bytes in the order of WebAssembly memory, as `bytes` (the library takes them behind a pointer)."""
    import struct

    def lanes(*v: int) -> bytes:
        return struct.pack("<4i", *v)

    seen: list[type] = []

    def twice(b: bytes) -> bytes:
        seen.append(type(b))
        return lanes(*(2 * x for x in struct.unpack("<4i", b)))

    def split(b: bytes, n: int) -> tuple[int, bytes]:
        return n + 1, b[::-1]

    module = build_front_end(DATA / "v128_signatures.wat", f"v128_signatures_{front_end}")
    i = module.Instance({"env": {"twice": twice, "split": split}})
    assert i.double(lanes(1, 2, 3, 4)) == lanes(2, 4, 6, 8)
    assert i.double(bytearray(lanes(5, 5, 5, 5))) == lanes(10, 10, 10, 10)  # any bytes-like object
    assert i.pair(7, lanes(1, 1, 1, 1)) == (lanes(1, 1, 1, 1), 7)
    assert i.via_import(lanes(1, 2, 3, 4)) == lanes(2, 4, 6, 8) and seen == [bytes]
    assert i.via_split(lanes(1, 2, 3, 4), 9) == (10, lanes(1, 2, 3, 4)[::-1])
    assert i.lane(lanes(0, 0, 0, 42)) == 42
    for bad, exc in ((b"short", ValueError), (7, TypeError), ("0123456789abcdef", TypeError)):
        with pytest.raises(exc):
            i.double(bad)
    assert i.double(lanes(1, 1, 1, 1)) == lanes(2, 2, 2, 2)  # the instance goes on after a wrong argument


def test_an_imported_function_put_in_a_table_by_an_element_segment_is_called_with_its_own_instance(
    build_extension: Builder,
) -> None:
    """wasm2c 1.0.42 gave such an entry the address of a field of the module instance, and the call crashed (the output of `meld fuse` is built so)."""
    mod = build_extension(DATA / "imported_in_table.wat", "imported_in_table")

    def host(x: int) -> int:
        return x + 100

    inst = mod.Instance({"env": {"f": host}})
    assert inst.via_import(5) == 105
    assert inst.via_defined(5) == 10
