"""WASI, `wasi_snapshot_preview1`, compiled into the module (wasi_p1.h of fusedwasi): the module gets it by itself."""

from __future__ import annotations

import functools
import gc
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from wasmext._natify import shared_header

DATA = Path(__file__).parent / "data"
Builder = Callable[..., ModuleType]


@pytest.fixture(params=["extension", "ctypes"])
def build_extension(request: pytest.FixtureRequest) -> Builder:
    """The tests of WASI run on both front ends: the extension, and the shared library through ctypes (the name `build_extension` is kept for the tests)."""
    build: Builder = request.getfixturevalue("build_extension" if request.param == "extension" else "build_ctypes")
    return functools.partial(build, host="wasm32-wasip1")


def test_hello_writes_to_stdout_and_exits_with_a_code(
    build_extension: Builder, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = build_extension(DATA / "wasi_hello.wat", "wasi_hello")
    inst = mod.Instance()  # no imports: the module gets WASI by itself
    with pytest.raises(mod.WasiExit) as info:
        inst._start()
    assert info.value.code == 3
    assert capsys.readouterr().out == "hello, wasi\n"


def probe(build_extension: Builder, **config: object) -> tuple[Any, Any]:
    mod = build_extension(DATA / "wasi_probe.wat", "wasi_probe")
    return mod, mod.Instance(wasi=config) if config else mod.Instance()


def u32(mem: memoryview, at: int) -> int:
    return int.from_bytes(mem[at : at + 4], "little")


def strings(mem: memoryview, table: int, count: int) -> list[bytes]:
    out: list[bytes] = []
    for i in range(count):
        start = u32(mem, table + 4 * i)
        out.append(bytes(mem[start:]).split(b"\0", 1)[0])
    return out


def test_arguments_and_environment_are_what_the_caller_gave(build_extension: Builder) -> None:
    _, inst = probe(build_extension, args=["prog", "-v", "héllo"], env={"A": "1", "B": "two"})
    mem = inst.memory
    assert inst.args_sizes_get(0, 4) == 0
    assert (u32(mem, 0), u32(mem, 4)) == (3, len(b"prog\0-v\0h\xc3\xa9llo\0"))
    assert inst.args_get(0x100, 0x200) == 0
    assert strings(mem, 0x100, 3) == [b"prog", b"-v", "héllo".encode()]
    assert inst.environ_sizes_get(0, 4) == 0
    assert (u32(mem, 0), u32(mem, 4)) == (2, len(b"A=1\0B=two\0"))
    assert inst.environ_get(0x100, 0x200) == 0
    assert strings(mem, 0x100, 2) == [b"A=1", b"B=two"]


def test_defaults_are_the_name_of_the_module_and_an_empty_environment(build_extension: Builder) -> None:
    _, inst = probe(build_extension)
    mem = inst.memory
    inst.args_sizes_get(0, 4)
    assert (u32(mem, 0), u32(mem, 4)) == (1, len(b"wasi_probe\0"))
    inst.environ_sizes_get(0, 4)
    assert (u32(mem, 0), u32(mem, 4)) == (0, 0)


def test_clocks_random_and_yield(build_extension: Builder) -> None:
    import time

    _, inst = probe(build_extension)
    mem = inst.memory
    slack = (
        50_000_000  # the clock of the core is the precise one; time.time_ns() of Python on Windows ticks every 15 ms
    )
    before = time.time_ns()
    assert inst.clock_time_get(0, 16) == 0
    now = int.from_bytes(mem[16:24], "little")
    assert before - slack <= now <= time.time_ns() + slack
    assert inst.clock_time_get(1, 16) == 0
    first = int.from_bytes(mem[16:24], "little")
    assert inst.clock_time_get(1, 16) == 0
    assert int.from_bytes(mem[16:24], "little") >= first  # monotonic
    assert inst.clock_time_get(9, 16) == 28  # EINVAL: no such clock
    assert inst.clock_res_get(0, 16) == 0
    assert int.from_bytes(mem[16:24], "little") >= 1
    mem[64:96] = bytes(32)
    assert inst.random_get(64, 32) == 0
    assert bytes(mem[64:96]) != bytes(32)
    assert inst.random_get(65536, 1) == 21  # EFAULT: past the memory
    assert inst.sched_yield() == 0


def test_standard_streams_go_where_the_caller_says(build_extension: Builder) -> None:
    out: list[bytes] = []
    err: list[bytes] = []

    class Sink:
        def write(self, data: bytes) -> None:
            err.append(data)

    _, inst = probe(build_extension, stdin=b"abcdef", stdout=out.append, stderr=Sink())
    mem = inst.memory
    mem[100:105] = b"hello"
    mem[0:8] = (100).to_bytes(4, "little") + (5).to_bytes(4, "little")
    assert inst.fd_write(1, 0, 1, 32) == 0
    assert u32(mem, 32) == 5 and out == [b"hello"]
    assert inst.fd_write(2, 0, 1, 32) == 0
    assert err == [b"hello"]
    assert inst.fd_write(0, 0, 1, 32) == 8  # EBADF: stdin is not for writing
    assert inst.fd_write(7, 0, 1, 32) == 8
    mem[0:8] = (200).to_bytes(4, "little") + (4).to_bytes(4, "little")  # read 4 bytes to 200
    assert inst.fd_read(0, 0, 1, 32) == 0
    assert u32(mem, 32) == 4 and bytes(mem[200:204]) == b"abcd"
    assert inst.fd_read(0, 0, 1, 32) == 0
    assert u32(mem, 32) == 2 and bytes(mem[200:202]) == b"ef"
    assert inst.fd_read(0, 0, 1, 32) == 0 and u32(mem, 32) == 0  # the end
    assert inst.fd_read(1, 0, 1, 32) == 8


def test_default_streams_follow_sys_stdout(build_extension: Builder, capsys: pytest.CaptureFixture[str]) -> None:
    _, inst = probe(build_extension)
    mem = inst.memory
    mem[100:106] = b"wasm!\n"
    mem[0:8] = (100).to_bytes(4, "little") + (6).to_bytes(4, "little")
    print("before", end="")  # not flushed by itself: the order must be kept
    inst.fd_write(1, 0, 1, 32)
    print("after")
    inst.fd_write(2, 0, 1, 32)
    captured = capsys.readouterr()
    assert captured.out == "beforewasm!\nafter\n" and captured.err == "wasm!\n"


def test_descriptors_the_first_stage_has(build_extension: Builder) -> None:
    _, inst = probe(build_extension)
    mem = inst.memory
    assert inst.fd_fdstat_get(1, 40) == 0
    assert mem[40] == 2 and int.from_bytes(mem[48:56], "little") & (1 << 6)  # a character device that can be written
    assert inst.fd_fdstat_get(9, 40) == 8
    assert inst.fd_prestat_get(3, 40) == 8  # nothing preopened: the end of the walk
    assert inst.fd_seek(1, 40) == 70  # ESPIPE
    assert inst.fd_close(1) == 0 and inst.fd_close(9) == 8
    assert inst.path_open() == 8  # EBADF: there is no descriptor 3 without a preopen


def test_proc_exit_is_an_exception_of_the_call_and_the_instance_goes_on(build_extension: Builder) -> None:
    """As in Wasmtime, where proc_exit is the error `I32Exit` that the call returns: the end is what the call leaves, not a state of the instance."""
    mod, inst = probe(build_extension)
    with pytest.raises(mod.WasiExit) as info:
        inst.proc_exit(7)
    assert info.value.code == 7 and isinstance(info.value, mod.WasiTerminated)
    assert inst.sched_yield() == 0  # the instance can be called again
    with pytest.raises(mod.WasiExit) as again:
        inst.proc_exit(9)  # and it ends again, with its own code
    assert again.value.code == 9
    assert bytes(inst.memory[:1]) == b"\0"  # what it left in memory can be read


def test_proc_raise_ends_the_program_with_a_signal_unless_the_signal_is_ignored(build_extension: Builder) -> None:
    mod, inst = probe(build_extension)
    for ignored in (0, 16, 17, 18, 19, 20, 21, 22, 27):  # none, child, continue, the stops, urgent data, window size
        assert inst.proc_raise(ignored) == 0
    assert inst.proc_raise(31) == 28  # EINVAL: there is no such signal
    assert inst.sched_yield() == 0  # still alive
    with pytest.raises(mod.WasiSignal) as info:
        inst.proc_raise(6)
    assert (info.value.signal, info.value.name) == (6, "SIGABRT") and isinstance(info.value, mod.WasiTerminated)
    assert inst.sched_yield() == 0  # the instance can be called again
    with pytest.raises(mod.WasiSignal) as again:
        inst.proc_raise(15)
    assert again.value.name == "SIGTERM"  # the signal of the call, not the first one
    _, other = probe(build_extension)
    with pytest.raises(mod.WasiSignal) as term:
        other.proc_raise(15)
    assert term.value.name == "SIGTERM"


def test_the_end_of_a_call_leaves_what_the_program_opened(build_extension: Builder, tmp_path: Path) -> None:
    import os
    import sys

    if not sys.platform.startswith("linux"):
        pytest.skip("counts the descriptors of the process through /proc/self/fd")
    mod: Any = build_extension(DATA / "wasi_fs_probe.wat", "wasi_fs_probe_end")
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    before = len(os.listdir("/proc/self/fd"))
    inst = mod.Instance(wasi={"preopens": {"/": str(tmp_path)}})
    mem = inst.memory
    mem[1000:1005] = b"f.txt"
    assert inst.path_open(3, 0, 1000, 5, 0, 0xFFFFFFFF, 0, 0, 2000) == 0  # rights: all, no flags
    assert u32(mem, 2000) == 4  # a file is open
    assert len(os.listdir("/proc/self/fd")) >= before + 2  # the preopen and the file
    with pytest.raises(mod.WasiExit):
        inst.proc_exit(0)
    assert (
        len(os.listdir("/proc/self/fd")) >= before + 2
    )  # nothing is closed by the end of a call, as in Wasmtime: the file is still open
    assert inst.fd_close(4) == 0  # and it can be used
    del mem, inst
    gc.collect()
    assert len(os.listdir("/proc/self/fd")) == before  # the files go with the instance


def test_a_trap_does_not_end_the_instance_of_a_command_or_of_a_reactor(build_extension: Builder) -> None:
    command: Any = build_extension(DATA / "wasi_command_trap.wat", "wasi_command_trap")
    inst = command.Instance()
    with pytest.raises(command.Trap):
        inst._start()
    assert inst.ping() == 1  # a core module that trapped can be called again in Wasmtime, command or not
    reactor: Any = build_extension(DATA / "wasi_reactor_trap.wat", "wasi_reactor_trap")
    loose = reactor.Instance()
    with pytest.raises(reactor.Trap):
        loose.boom()
    assert loose.ping() == 1  # the instance stays usable


def test_the_caller_can_replace_a_call_and_the_rest_stays(build_extension: Builder) -> None:
    mod: Any = build_extension(DATA / "wasi_probe.wat", "wasi_probe")
    inst = mod.Instance({"wasi_snapshot_preview1": {"sched_yield": lambda: 99}})
    assert inst.sched_yield() == 99
    assert inst.random_get(64, 8) == 0  # still ours


def test_a_wrong_config_is_refused(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi_probe.wat", "wasi_probe")
    with pytest.raises(TypeError, match="unknown option 'colour'"):
        mod.Instance(wasi={"colour": 1})
    with pytest.raises(NotADirectoryError):
        mod.Instance(wasi={"preopens": {"/": __file__}})
    with pytest.raises(TypeError):
        mod.Instance(wasi=[1])


def test_the_header_has_a_function_for_each_call_of_the_specification() -> None:
    import re

    from wasmext._gen import _WASI_PREVIEW1_SIGNATURES  # pyright: ignore[reportPrivateUsage]

    header = shared_header("wasi_p1_core.h").read_text("utf-8")
    defined = set(re.findall(r"static inline (?:uint32_t|void) fusedwasi_p1_(\w+)\(", header))
    defined &= set(_WASI_PREVIEW1_SIGNATURES)  # the helpers that also begin with wasi_ are not calls
    defined |= set(re.findall(r"^FUSEDWASI_P1_(?:NOT_PROVIDED|SOCKET)\((\w+),", header, re.MULTILINE))
    assert defined == set(_WASI_PREVIEW1_SIGNATURES)
    assert len(_WASI_PREVIEW1_SIGNATURES) == 46


def test_a_call_that_wasi_does_not_have_or_has_with_another_signature_is_refused(wabt: Path, tmp_path: Path) -> None:
    import subprocess

    from wasmext import GenError, generate, parse

    def wasm(imports: str) -> bytes:
        wat = tmp_path / "m.wat"
        wat.write_text(f'(module {imports} (memory (export "memory") 1))', encoding="utf-8")
        subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", tmp_path / "m.wasm"], check=True)
        return (tmp_path / "m.wasm").read_bytes()

    unknown = wasm('(import "wasi_snapshot_preview1" "fd_teleport" (func (param i32)))')
    with pytest.raises(GenError, match="not a function of wasi_snapshot_preview1"):
        generate(parse(unknown), "m", host="wasm32-wasip1")
    wrong = wasm('(import "wasi_snapshot_preview1" "fd_write" (func (param i32 i32 i32) (result i32)))')
    with pytest.raises(GenError, match="fd_write is ii?i>i, wasi_snapshot_preview1 says iiii>i"):
        generate(parse(wrong), "m", host="wasm32-wasip1")
    no_memory = (
        b"\x00asm\x01\x00\x00\x00"  # a module that imports proc_exit and exports no memory
        b"\x01\x05\x01\x60\x01\x7f\x00"
        b"\x02\x24\x01\x16wasi_snapshot_preview1\x09proc_exit\x00\x00"
    )
    with pytest.raises(GenError, match="does not export its memory"):
        generate(parse(no_memory), "m", host="wasm32-wasip1")


def test_the_first_snapshot_wasi_unstable_is_served_too(build_extension: Builder, tmp_path: Path) -> None:
    wat = tmp_path / "unstable_probe.wat"
    wat.write_text(
        (DATA / "wasi_probe.wat").read_text("utf-8").replace("wasi_snapshot_preview1", "wasi_unstable"), "utf-8"
    )
    mod: Any = build_extension(wat, "wasi_unstable_probe")
    inst = mod.Instance(wasi={"args": ["prog", "x"], "env": {"A": "1"}})
    mem = inst.memory
    inst.args_sizes_get(0, 4)
    assert (u32(mem, 0), u32(mem, 4)) == (2, len(b"prog\0x\0"))
    assert inst.clock_time_get(0, 16) == 0
    assert inst.fd_fdstat_get(1, 40) == 0 and mem[40] == 2
    assert inst.fd_seek(1, 40) == 70
    with pytest.raises(mod.WasiExit) as info:
        inst.proc_exit(5)
    assert info.value.code == 5


def test_one_module_can_import_both_snapshots(
    build_extension: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wat = tmp_path / "both.wat"
    wat.write_text(
        """
(module
  (import "wasi_snapshot_preview1" "fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))
  (import "wasi_unstable" "proc_exit" (func $proc_exit (param i32)))
  (memory (export "memory") 1)
  (data (i32.const 8) "both\\n")
  (func (export "_start")
    (i32.store (i32.const 0) (i32.const 8))
    (i32.store (i32.const 4) (i32.const 5))
    (drop (call $fd_write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 24)))
    (call $proc_exit (i32.const 4))))
""",
        encoding="utf-8",
    )
    mod: Any = build_extension(wat, "wasi_both")
    with pytest.raises(mod.WasiExit) as info:
        mod.Instance()._start()
    assert info.value.code == 4 and capsys.readouterr().out == "both\n"


def test_sock_accept_is_not_a_call_of_the_first_snapshot(wabt: Path, tmp_path: Path) -> None:
    import subprocess

    from wasmext import GenError, generate, parse

    wat = tmp_path / "m.wat"
    wat.write_text(
        '(module (import "wasi_unstable" "sock_accept" (func (param i32 i32 i32) (result i32)))'
        ' (memory (export "memory") 1))',
        encoding="utf-8",
    )
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", tmp_path / "m.wasm"], check=True)
    with pytest.raises(GenError, match="sock_accept is not a function of wasi_unstable"):
        generate(parse((tmp_path / "m.wasm").read_bytes()), "m", host="wasm32-wasip1")


def test_a_function_imported_twice_is_one_function(build_extension: Builder) -> None:
    mod: Any = build_extension(DATA / "wasi_twice.wat", "wasi_twice")
    inst = mod.Instance()
    assert inst.first(99) == 8 and inst.second(99) == 8  # EBADF from both
    seen: list[int] = []

    def fd_write(fd: int, iovs: int, count: int, nwritten: int) -> int:
        seen.append(fd)
        return 0

    again = mod.Instance({"wasi_snapshot_preview1": {"fd_write": fd_write}})
    assert again.first(5) == 0 and again.second(6) == 0 and seen == [5, 6]


def test_none_is_nothing_and_an_absent_key_is_the_default(
    build_extension: Builder, capsys: pytest.CaptureFixture[str]
) -> None:
    _, inst = probe(build_extension, args=None, stdout=None, stdin=None, stderr=None, env=None)
    mem = inst.memory
    assert inst.args_sizes_get(0, 4) == 0
    assert (u32(mem, 0), u32(mem, 4)) == (0, 0)  # no arguments: not the name of the program
    assert inst.environ_sizes_get(0, 4) == 0 and u32(mem, 0) == 0
    mem[100:105] = b"lost!"
    mem[0:8] = (100).to_bytes(4, "little") + (5).to_bytes(4, "little")
    assert inst.fd_write(1, 0, 1, 32) == 0 and u32(mem, 32) == 5  # thrown away, as written
    assert inst.fd_write(2, 0, 1, 32) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    mem[0:8] = (200).to_bytes(4, "little") + (4).to_bytes(4, "little")
    assert inst.fd_read(0, 0, 1, 32) == 0 and u32(mem, 32) == 0  # an empty input
    _, absent = probe(build_extension, stdout=None)  # the other streams of this one are the default
    absent.memory[100:102] = b"ok"
    absent.memory[0:8] = (100).to_bytes(4, "little") + (2).to_bytes(4, "little")
    assert absent.fd_write(2, 0, 1, 32) == 0
    assert capsys.readouterr().err == "ok"


def test_the_system_streams_can_be_given_explicitly(
    build_extension: Builder, capsys: pytest.CaptureFixture[str]
) -> None:
    import io
    import sys

    _, inst = probe(build_extension, stdout=sys.stdout, stderr=io.StringIO(), stdin=io.StringIO("héllo"))
    mem = inst.memory
    mem[100:106] = b"wasm!\n"
    mem[0:8] = (100).to_bytes(4, "little") + (6).to_bytes(4, "little")
    print("before", end="")
    assert inst.fd_write(1, 0, 1, 32) == 0  # a text stream gets the bytes through its binary side, in order
    print("after")
    assert capsys.readouterr().out == "beforewasm!\nafter\n"
    assert inst.fd_write(2, 0, 1, 32) == 0  # a StringIO has none: it gets the text
    mem[0:8] = (200).to_bytes(4, "little") + (16).to_bytes(4, "little")
    assert inst.fd_read(0, 0, 1, 32) == 0
    assert bytes(mem[200 : 200 + u32(mem, 32)]) == "héllo".encode()


def test_the_clock_and_the_random_bytes_can_be_replaced(build_extension: Builder) -> None:
    asked: list[int] = []

    def clock(clock_id: int) -> int:
        asked.append(clock_id)
        return 1_234_567_890_123 + clock_id

    def sevens(count: int) -> bytes:
        return b"\x07" * count

    def one_byte(count: int) -> bytes:
        return b"x"

    _, inst = probe(build_extension, clock=clock, random=sevens)
    mem = inst.memory
    assert inst.clock_time_get(1, 16) == 0
    assert int.from_bytes(mem[16:24], "little") == 1_234_567_890_124 and asked == [1]
    assert inst.random_get(64, 5) == 0 and bytes(mem[64:69]) == b"\x07" * 5
    _, short = probe(build_extension, random=one_byte)
    with pytest.raises(ValueError, match="'random' gave 1 bytes, 4 were asked for"):
        short.random_get(64, 4)
    mod = build_extension(DATA / "wasi_probe.wat", "wasi_probe")
    with pytest.raises(TypeError, match="'clock' must be a function"):
        mod.Instance(wasi={"clock": None})
    with pytest.raises(TypeError, match="'random' must be a function"):
        mod.Instance(wasi={"random": 5})


def test_the_clocks_are_those_of_the_system(build_extension: Builder) -> None:
    import time

    _, inst = probe(build_extension)
    mem = inst.memory
    before = time.time_ns()
    assert inst.clock_time_get(0, 16) == 0
    real = int.from_bytes(mem[16:24], "little")
    after = time.time_ns()
    assert before - 1_000_000_000 <= real <= after + 1_000_000_000
    assert inst.clock_time_get(1, 16) == 0
    first = int.from_bytes(mem[16:24], "little")
    assert inst.clock_time_get(1, 16) == 0 and int.from_bytes(mem[16:24], "little") >= first > 0
    for clock_id in (2, 3):
        assert inst.clock_time_get(clock_id, 16) == 0
        assert inst.clock_res_get(clock_id, 24) == 0 and int.from_bytes(mem[24:32], "little") >= 1


@pytest.mark.parametrize("source", ["wasi_hello.wat", "simple.wasm", "kitchen_sink.wasm"])
def test_the_glue_of_a_module_compiles_with_no_python(source: str, wabt: Path, tmp_path: Path) -> None:
    """Check (a) of the plan for the glue of a module (<name>_glue.h): it is C that only the runtime of wasm2c is needed for, so that
    a host that is not Python can use it. The compiler is given no path to Python.h, and the header is not allowed to name it."""
    import os
    import platform
    import shutil
    import subprocess

    from wasmext import generate, parse

    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    if cc is None or platform.system() == "Windows":
        pytest.skip("no C compiler of the cc kind")
    wasm = tmp_path / "m.wasm"
    if source.endswith(".wat"):
        subprocess.run([wabt / "bin" / "wat2wasm", DATA / source, "-o", wasm], check=True)
    else:
        wasm.write_bytes((DATA / source).read_bytes())
    glue = generate(parse(wasm.read_bytes()), "m", host="wasm32-wasip1")
    (tmp_path / "m_glue.h").write_text(glue.header, encoding="utf-8")
    shared = [
        "wasmext_glue.h",
        *(("wasi_p1_core.h", "wasi_python.h", *glue.wasi_headers) if glue.wasi_headers else ()),
    ]
    for name in shared:
        (tmp_path / name).write_bytes(shared_header(name).read_bytes())
    subprocess.run([wabt / "bin" / "wasm2c", wasm, "-o", tmp_path / "m_w2c.c", "--module-name=m"], check=True)
    (tmp_path / "check.c").write_text('#include "m_glue.h"\nint main(void) { return 0; }\n', encoding="utf-8")
    compiled = subprocess.run(
        [
            cc,
            "-std=gnu11",
            "-Wall",
            "-Wno-unused-function",
            "-Wno-unused-parameter",
            "-fsyntax-only",
            f"-I{tmp_path}",
            f"-I{wabt / 'wasm2c'}",
            f"-I{wabt / 'include'}",  # simde, for a module that uses SIMD
            tmp_path / "check.c",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr[-1500:]
    assert "#include <Python.h>" not in glue.header


def _write_bytes(inst: Any, data: bytes, fd: int = 1) -> int:
    """fd_write of `data` to `fd` from the memory of the probe: the errno."""
    mem = inst.memory
    mem[100 : 100 + len(data)] = data
    mem[0:8] = (100).to_bytes(4, "little") + len(data).to_bytes(4, "little")
    return int(inst.fd_write(fd, 0, 1, 32))


def test_a_stream_that_takes_less_than_it_is_given_gets_all_of_it(build_extension: Builder) -> None:
    taken: list[bytes] = []

    class Chunky:
        """A raw stream: write() says how many bytes it took, and it takes three at a time."""

        def write(self, data: bytes) -> int:
            taken.append(bytes(data[:3]))
            return min(3, len(data))

    _, inst = probe(build_extension, stdout=Chunky())
    assert _write_bytes(inst, b"hello, wasi") == 0
    assert b"".join(taken) == b"hello, wasi"


def test_a_character_in_two_writes_is_one_character(build_extension: Builder) -> None:
    import io

    text = io.StringIO()  # a text stream with no binary side
    _, inst = probe(build_extension, stdout=text)
    assert _write_bytes(inst, b"\xc3") == 0 and _write_bytes(inst, b"\xa9!") == 0
    assert text.getvalue() == "é!"


def test_a_closed_stream_is_ebadf_not_a_trap(build_extension: Builder) -> None:
    import io

    text = io.StringIO()
    text.close()
    _, inst = probe(build_extension, stdout=text)
    assert _write_bytes(inst, b"x") == 8  # EBADF


def test_a_stand_in_for_stdout_that_has_only_write(build_extension: Builder, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    seen: list[str] = []

    class OnlyWrite:
        def write(self, text: str) -> int:
            seen.append(text)
            return len(text)

    monkeypatch.setattr(sys, "stdout", OnlyWrite())
    _, inst = probe(build_extension)
    assert _write_bytes(inst, "é".encode()) == 0
    assert "".join(seen) == "é"


def test_a_text_stdin_with_characters_of_several_bytes_is_read_in_pieces(build_extension: Builder) -> None:
    import io

    _, inst = probe(build_extension, stdin=io.StringIO("héllo wörld ✓"))
    mem = inst.memory
    got = b""
    for _ in range(20):
        mem[0:8] = (200).to_bytes(4, "little") + (4).to_bytes(4, "little")
        assert inst.fd_read(0, 0, 1, 32) == 0
        n = u32(mem, 32)
        if n == 0:
            break
        got += bytes(mem[200 : 200 + n])
    assert got == "héllo wörld ✓".encode()


def test_args_and_env_are_checked(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi_probe.wat", "wasi_probe")
    for bad, error in (
        ({"env": {b"a": b"c"}}, TypeError),
        ({"env": {"a": 1}}, TypeError),
        ({"env": {"a=b": "c"}}, ValueError),
        ({"env": {"": "c"}}, ValueError),
        ({"env": {"a": "c\0d"}}, ValueError),
        ({"args": "abc"}, TypeError),
        ({"args": ["a\0b"]}, ValueError),
        ({"args": [b"a"]}, TypeError),
    ):
        with pytest.raises(error):
            mod.Instance(wasi=bad)
