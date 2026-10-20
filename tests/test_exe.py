"""A native executable from a command (wasmext._exe): the C of the module, its glue and the core of WASI, with no Python in the program."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from wasmext._exe import build  # pyright: ignore[reportPrivateUsage]

from .conftest import DATA


def _program(wabt: Path, tmp_path: Path, source: str) -> Path:
    wasm = tmp_path / "m.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / source, "-o", wasm], check=True)
    return build(wasm, tmp_path / ("m.exe" if sys.platform == "win32" else "m"), optimize=False)


def test_a_command_runs_as_a_program_and_ends_with_its_code(wabt: Path, tmp_path: Path) -> None:
    program = _program(wabt, tmp_path, "wasi_hello.wat")
    ran = subprocess.run([program, "m.wasm"], capture_output=True, check=False)
    assert ran.stdout == b"hello, wasi\n"  # the bytes of the program, as they are
    assert ran.returncode == 3  # proc_exit(3)


def test_a_trap_of_a_command_is_134_and_is_told_on_stderr(wabt: Path, tmp_path: Path) -> None:
    program = _program(wabt, tmp_path, "wasi_command_trap.wat")
    ran = subprocess.run([program, "m.wasm"], capture_output=True, check=False)
    assert ran.returncode == 134
    assert ran.stderr.startswith(b"trap: ")


def test_a_module_with_other_imports_than_wasi_is_not_made_into_a_program(wabt: Path, tmp_path: Path) -> None:
    wat = tmp_path / "other.wat"
    wat.write_text('(module (import "env" "f" (func)) (func (export "_start") call 0))', encoding="utf-8")
    wasm = tmp_path / "other.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    with pytest.raises(Exception, match="serves the imports of WASI"):
        build(wasm, tmp_path / "other", optimize=False)


def test_a_module_that_imports_nothing_from_wasi_is_not_made_into_a_program_in_words(
    wabt: Path, tmp_path: Path
) -> None:
    wat = tmp_path / "plain.wat"
    wat.write_text('(module (func (export "_start")))', encoding="utf-8")
    wasm = tmp_path / "plain.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    with pytest.raises(Exception, match="imports nothing from WASI"):
        build(wasm, tmp_path / "plain", optimize=False)


def _run(program: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([program, *args], capture_output=True, check=False)


def test_the_options_give_the_program_its_name_environment_and_arguments(wabt: Path, tmp_path: Path) -> None:
    program = _program(wabt, tmp_path, "wasi_args.wat")
    ran = _run(program, "--env", "A=1", "--env", "B=two=2", "--argv0", "prog", "--", "-x", "ü")
    assert ran.stdout.split(b"\0")[:5] == [b"prog", b"-x", "ü".encode(), b"A=1", b"B=two=2"]
    assert ran.returncode == 3
    named = _run(program, "m.wasm", "x")  # the first thing that is not an option is the name, as before
    assert named.stdout.split(b"\0")[:2] == [b"m.wasm", b"x"] and named.returncode == 2
    bare = _run(program)  # no name given: the program's own
    assert bare.returncode == 1 and bare.stdout.split(b"\0")[0] == str(program).encode()


def test_wrong_options_are_told_with_exit_2_and_help_and_version_work(wabt: Path, tmp_path: Path) -> None:
    program = _program(wabt, tmp_path, "wasi_args.wat")
    for bad in (["--env", "NOEQUALS"], ["--env", "=x"], ["--env"], ["--dir"], ["--nonsense"], ["--dir", "/no/such/dir"]):
        ran = _run(program, *bad)
        assert ran.returncode == 2 and ran.stderr and not ran.stdout, bad
    helped = _run(program, "--help")
    assert helped.returncode == 0 and b"--env" in helped.stdout and b"--dir" in helped.stdout
    versioned = _run(program, "--version")
    assert versioned.returncode == 0 and b"wasmext" in versioned.stdout


def test_a_directory_can_be_given_read_only(wabt: Path, tmp_path: Path) -> None:
    wat = tmp_path / "create.wat"
    wat.write_text(
        '(module (import "wasi_snapshot_preview1" "path_open" (func $open (param i32 i32 i32 i32 i32 i64 i64 i32 i32) (result i32)))'
        ' (import "wasi_snapshot_preview1" "proc_exit" (func $exit (param i32))) (memory (export "memory") 1) (data (i32.const 0) "new")'
        ' (func (export "_start") (call $exit (call $open (i32.const 3) (i32.const 0) (i32.const 0) (i32.const 3)'
        " (i32.const 1) (i64.const 0x3fffffff) (i64.const 0) (i32.const 0) (i32.const 8)))))",
        encoding="utf-8",
    )
    wasm = tmp_path / "create.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    program = build(wasm, tmp_path / ("create.exe" if sys.platform == "win32" else "create"), optimize=False)
    writable, shared = tmp_path / "rw", tmp_path / "ro"
    writable.mkdir()
    shared.mkdir()
    assert _run(program, "--dir", f"{writable}::/").returncode == 0  # creates "new"
    assert (writable / "new").is_file()
    assert _run(program, "--dir", f"{shared}::/:ro").returncode != 0  # EROFS / ENOTCAPABLE
    assert not (shared / "new").exists()


def test_a_start_that_is_not_a_command_is_refused(wabt: Path, tmp_path: Path) -> None:
    wat = tmp_path / "typed.wat"
    wat.write_text(
        '(module (import "wasi_snapshot_preview1" "proc_exit" (func (param i32))) (func (export "_start") (param i32)))',
        encoding="utf-8",
    )
    wasm = tmp_path / "typed.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    with pytest.raises(Exception, match=r"_start is \(i32\)"):
        build(wasm, tmp_path / "typed", optimize=False)
