"""WASI, `wasi_snapshot_preview1`, compiled into the module (src/wasmext/c/wasi_preview1.h): the module gets it by itself."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

DATA = Path(__file__).parent / "data"
Builder = Callable[..., ModuleType]


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
    before = time.time_ns()
    assert inst.clock_time_get(0, 16) == 0
    now = int.from_bytes(mem[16:24], "little")
    assert before <= now <= time.time_ns()
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


def test_proc_exit_is_an_exception_and_the_instance_stays_usable(build_extension: Builder) -> None:
    mod, inst = probe(build_extension)
    with pytest.raises(mod.WasiExit) as info:
        inst.proc_exit(7)
    assert info.value.code == 7
    assert inst.sched_yield() == 0


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

    header = (Path(__file__).parent.parent / "src" / "wasmext" / "c" / "wasi_common.h").read_text("utf-8")
    defined = set(re.findall(r"static inline (?:uint32_t|void) wasi_(\w+)\(", header))
    defined &= set(_WASI_PREVIEW1_SIGNATURES)  # the helpers that also begin with wasi_ are not calls
    defined |= set(re.findall(r"^WASI_(?:NOT_PROVIDED|SOCKET)\((\w+),", header, re.MULTILINE))
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
        generate(parse(unknown), "m")
    wrong = wasm('(import "wasi_snapshot_preview1" "fd_write" (func (param i32 i32 i32) (result i32)))')
    with pytest.raises(GenError, match="fd_write is ii?i>i, wasi_snapshot_preview1 says iiii>i"):
        generate(parse(wrong), "m")
    no_memory = (
        b"\x00asm\x01\x00\x00\x00"  # a module that imports proc_exit and exports no memory
        b"\x01\x05\x01\x60\x01\x7f\x00"
        b"\x02\x24\x01\x16wasi_snapshot_preview1\x09proc_exit\x00\x00"
    )
    with pytest.raises(GenError, match="does not export its memory"):
        generate(parse(no_memory), "m")


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
        generate(parse((tmp_path / "m.wasm").read_bytes()), "m")
