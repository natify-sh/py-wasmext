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
