"""WASI 0.2 built into the extension: `host = "wasm32-wasip2"` answers the imports of `wasi:*@0.2.x` with the C host of fusedwasi (p2/), configured by `wasi=`."""

from __future__ import annotations

import struct
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from wasmext import GenError, generate, parse

from .conftest import DATA

Builder = Callable[..., ModuleType]
HELLO = Path(__file__).parent.parent / "examples" / "wasi2_unbundled" / "src" / "wasi2demo" / "_hello.wasm"
RUN = "wasi:cli/run@0.2.12#run"
P2 = "wasm32-wasip2"


def strings(inst: Any, at: int) -> list[str]:
    """A `list<string>` that the host wrote at `at` (pointer and length; each element a pointer and a length)."""
    mem = inst.memory
    ptr, count = struct.unpack("<II", bytes(mem[at : at + 8]))
    out: list[str] = []
    for i in range(count):
        p, n = struct.unpack("<II", bytes(mem[ptr + 8 * i : ptr + 8 * i + 8]))
        out.append(bytes(mem[p : p + n]).decode())
    return out


def test_a_command_of_wasi_p2_runs_with_no_host_of_python(build_extension: Builder) -> None:
    mod = build_extension(HELLO, "wasi2_hello", host=P2)
    assert mod.__host__ == P2
    out: list[bytes] = []
    inst = mod.Instance(wasi={"stdout": out.append})
    assert getattr(inst, RUN)() == 1  # the program returned 3, which is the err of the result of wasi:cli/run
    assert b"".join(out) == b"hello from wasip2\n"


def test_the_standard_output_goes_to_sys_stdout_when_it_is_not_given(
    build_extension: Builder, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = build_extension(HELLO, "wasi2_hello_sys", host=P2)
    getattr(mod.Instance(), RUN)()
    assert capsys.readouterr().out == "hello from wasip2\n"


def test_arguments_and_environment(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi2_probe.wat", "wasi2_probe_args", host=P2)
    assert strings_of(mod.Instance(), "args") == ["wasi2_probe_args"]  # the name of the program, when there are none
    assert strings_of(mod.Instance(wasi={"args": ["prog", "-x", "é"]}), "args") == ["prog", "-x", "é"]
    assert strings_of(mod.Instance(wasi={"args": None}), "args") == []
    inst = mod.Instance(wasi={"env": {"A": "1", "B": "two words"}})
    inst.env(1000)
    mem = inst.memory
    ptr, count = struct.unpack("<II", bytes(mem[1000:1008]))
    pairs: list[tuple[str, str]] = []
    for i in range(count):
        a, an, b, bn = struct.unpack("<IIII", bytes(mem[ptr + 16 * i : ptr + 16 * i + 16]))
        pairs.append((bytes(mem[a : a + an]).decode(), bytes(mem[b : b + bn]).decode()))
    assert pairs == [("A", "1"), ("B", "two words")]


def strings_of(inst: Any, export: str) -> list[str]:
    getattr(inst, export)(1000)
    return strings(inst, 1000)


def test_exit_raises_the_exception_with_the_code(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi2_probe.wat", "wasi2_probe_exit", host=P2)
    inst = mod.Instance()
    with pytest.raises(mod.WasiExit) as raised:
        inst.exit(1)  # the result of wasi:cli/exit is err (1)
    assert raised.value.code == 1
    with pytest.raises(mod.WasiTerminated, match="has ended"):  # the program is over
        inst.args(1000)


def test_the_clock_and_the_random_bytes_can_be_replaced(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi2_probe.wat", "wasi2_probe_hooks", host=P2)
    seen: list[int] = []

    def clock(clock_id: int) -> int:
        seen.append(clock_id)
        return 123456789

    def random(n: int) -> bytes:
        return b"\x01" * n

    inst = mod.Instance(wasi={"clock": clock, "random": random})
    assert inst.now() == 123456789 and seen == [1]  # the monotonic clock is 1
    assert inst.rand() == 0x0101010101010101
    real = mod.Instance()
    assert real.now() > 0  # the clock of the system


def test_an_exception_of_a_hook_comes_out_of_the_call(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi2_probe.wat", "wasi2_probe_raise", host=P2)

    def clock(clock_id: int) -> int:
        raise KeyError("no clock")

    with pytest.raises(KeyError, match="no clock"):
        mod.Instance(wasi={"clock": clock}).now()


def test_a_wrong_configuration_is_refused(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi2_probe.wat", "wasi2_probe_config", host=P2)
    with pytest.raises(TypeError, match="unknown option"):
        mod.Instance(wasi={"nope": 1})
    with pytest.raises(TypeError, match="lists of strings"):
        mod.Instance(wasi={"args": "abc"})


def test_the_imports_of_wasi_p2_are_replaced_one_by_one(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi2_probe.wat", "wasi2_probe_replace", host=P2)
    inst = mod.Instance({"wasi:clocks/monotonic-clock@0.2.12": {"now": lambda: 7}})
    assert inst.now() == 7
    nothing = mod.Instance(
        {"wasi:clocks/monotonic-clock@0.2.12": {"now": None}}
    )  # None is nothing given: a call with no errno traps
    with pytest.raises(mod.Trap, match="given as None"):
        nothing.now()


def test_the_stub_of_a_module_of_wasi_p2() -> None:
    module = parse((HELLO).read_bytes())
    stub = generate(module, "m", host=P2).stub
    assert "class WasiP2(TypedDict):" in stub and "Wasi = WasiP2" in stub and "wasi: Wasi | None = None" in stub
    assert (
        "_Imports_wasi_io_streams_0_2_12 = TypedDict(" in stub
        and "def __init__(self, imports: Imports | None = None" in stub
    )
    assert "class Host" not in stub  # the originals of the calls of 0.2 are not made yet
    compile(stub, "m.pyi", "exec")


def test_what_the_generator_refuses() -> None:
    wasm = DATA / "wasi2_probe.wat"
    assert wasm.is_file()
    with pytest.raises(GenError, match="does not export 'cabi_realloc'"):
        # the module of hello has it; one that does not is refused (a component's allocator)
        from .test_wasm_parser import I32, functype, leb, module, name, section, vec

        no_realloc = module(
            section(1, vec(functype([I32], []))),
            section(2, vec(name("wasi:cli/exit@0.2.12") + name("exit") + b"\x00" + leb(0))),
            section(5, vec(b"\x00" + leb(1))),
            section(7, vec(name("memory") + b"\x02" + leb(0))),
        )
        generate(parse(no_realloc), "m", host=P2)
