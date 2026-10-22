"""Compact imports (the import section in the forms 0x7F and 0x7E): read by wasmext, translated by `wasm2c --enable-compact-imports`, in every product and by `wasmimport`.

The module is a WASI command written byte by byte, because `wat2wasm` does not read the text form of the proposal yet. The forms are those that
WABT reads (`src/binary-reader.cc`, `ReadImportSection`): 0x7F is a count and then a name and a kind with its type for each import; 0x7E is one kind, a
count and then a name and a type for each.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from wasmext import Import, WasmError, parse
from wasmext._setuptools import product_filename  # pyright: ignore[reportPrivateUsage]

WASI = "wasi_snapshot_preview1"
FD_WRITE = ([("i32", "i32", "i32", "i32")], ["i32"])


def _name(text: str) -> bytes:
    return bytes([len(text)]) + text.encode()


def _section(section_id: int, body: bytes) -> bytes:
    return bytes([section_id, len(body)]) + body


def _imports(form: str) -> bytes:
    """The import section of the command in the given form; `fd_write` has type 0, `proc_exit` type 1."""
    plain_fd = _name(WASI) + _name("fd_write") + bytes([0, 0])
    plain_exit = _name(WASI) + _name("proc_exit") + bytes([0, 1])
    if form == "plain":
        return bytes([2]) + plain_fd + plain_exit
    if form == "f7f":  # one module for both, each with its name, kind and type
        return (
            bytes([1])
            + _name(WASI)
            + _name("")
            + bytes([0x7F, 2])
            + _name("fd_write")
            + bytes([0, 0])
            + _name("proc_exit")
            + bytes([0, 1])
        )
    if form == "f7e":  # one module and one kind for both, each with its name and type
        return (
            bytes([1])
            + _name(WASI)
            + _name("")
            + bytes([0x7E, 0, 2])
            + _name("fd_write")
            + bytes([0])
            + _name("proc_exit")
            + bytes([1])
        )
    if form == "mixed":  # an ordinary import, then a group of the form 0x7E
        return bytes([2]) + plain_fd + _name(WASI) + _name("") + bytes([0x7E, 0, 1]) + _name("proc_exit") + bytes([1])
    raise AssertionError(form)


def _command(form: str) -> bytes:
    """A WASI command that writes `hello, wasi` and ends with `proc_exit(3)`, its imports in the given form."""
    types = bytes([3, 0x60, 4, 0x7F, 0x7F, 0x7F, 0x7F, 1, 0x7F, 0x60, 1, 0x7F, 0, 0x60, 0, 0])
    start = (
        bytes([0])
        + bytes([0x41, 0, 0x41, 8, 0x36, 2, 0, 0x41, 4, 0x41, 12, 0x36, 2, 0, 0x41, 1, 0x41, 0, 0x41, 1, 0x41, 24])
        + bytes([0x10, 0, 0x1A, 0x41, 3, 0x10, 1, 0x0B])
    )
    exports = (
        bytes([2]) + _name("memory") + bytes([2, 0]) + _name("_start") + bytes([0, 2])
    )  # after the two imported functions
    return (
        b"\0asm\1\0\0\0"
        + _section(1, types)
        + _section(2, _imports(form))
        + _section(3, bytes([1, 2]))
        + _section(5, bytes([1, 0, 1]))
        + _section(7, exports)
        + _section(10, bytes([1, len(start)]) + start)
        + _section(11, bytes([1, 0, 0x41, 8, 0x0B, 12]) + b"hello, wasi\n")
    )


def test_the_imports_of_every_form_are_read_in_order() -> None:
    plain = parse(_command("plain")).imports
    assert [(i.module, i.name, i.kind) for i in plain] == [(WASI, "fd_write", "func"), (WASI, "proc_exit", "func")]
    for form in ("f7f", "f7e"):
        assert parse(_command(form)).imports == plain, form


def test_ordinary_and_compact_imports_mix_and_keep_their_order() -> None:
    imports: list[Import] = parse(_command("mixed")).imports
    assert imports == parse(_command("plain")).imports


def test_a_count_that_fits_neither_the_groups_nor_the_imports_is_refused() -> None:
    good = _command("f7f")
    imports = _section(2, _imports("f7f"))
    wrong = _section(2, bytes([7]) + _imports("f7f")[1:])  # seven imports announced
    assert imports in good
    with pytest.raises(WasmError, match="announces 7 imports"):
        parse(good.replace(imports, wrong))


def _wasmext(cwd: Path, wabt: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "WASMEXT_WABT": str(wabt)}
    return subprocess.run(
        [sys.executable, "-m", "wasmext", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


def _module(tmp_path: Path, form: str) -> None:
    (tmp_path / "m.wasm").write_bytes(_command(form))


def _run_start(cwd: Path, wabt: Path, code: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "WASMEXT_WABT": str(wabt), "WASMIMPORT_BUILD_DIR": str(cwd / "cache")}
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=600
    )


START = "try:\n    m.Instance()._start()\nexcept m.WasiExit as exc:\n    print('exit', exc.code)\n"


@pytest.mark.parametrize("form", ["f7f", "f7e", "mixed"])
def test_a_python_extension_runs(tmp_path: Path, wabt: Path, form: str) -> None:
    _module(tmp_path, form)
    done = _wasmext(tmp_path, wabt, "natify", "-i", "-q", "m.wasm")
    assert done.returncode == 0, done.stderr[-800:]
    ran = _run_start(tmp_path, wabt, "import m\n" + START)
    assert ran.returncode == 0, ran.stderr[-800:]
    assert ran.stdout == "hello, wasi\nexit 3\n"


@pytest.mark.parametrize("form", ["f7f", "f7e"])
def test_a_shared_library_is_built(tmp_path: Path, wabt: Path, form: str) -> None:
    _module(tmp_path, form)
    done = _wasmext(tmp_path, wabt, "natify", "-i", "-q", "--shared", "m.wasm")
    assert done.returncode == 0, done.stderr[-800:]
    assert (tmp_path / product_filename("m", "shared")).is_file()
    assert (tmp_path / "m_ctypes.py").is_file()


@pytest.mark.parametrize("form", ["f7f", "f7e"])
def test_a_program_runs(tmp_path: Path, wabt: Path, form: str) -> None:
    _module(tmp_path, form)
    done = _wasmext(tmp_path, wabt, "natify", "-i", "-q", "--exe", "m.wasm")
    assert done.returncode == 0, done.stderr[-800:]
    ran = subprocess.run([tmp_path / product_filename("m", "exe")], capture_output=True, check=False)
    assert ran.stdout == b"hello, wasi\n" and ran.returncode == 3


@pytest.mark.parametrize("form", ["f7f", "f7e"])
def test_wasmimport_imports_it(tmp_path: Path, wabt: Path, form: str) -> None:
    _module(tmp_path, form)
    ran = _run_start(tmp_path, wabt, "import wasmimport\nwasmimport.install()\nimport m\n" + START)
    assert ran.returncode == 0, ran.stderr[-800:]
    assert ran.stdout == "hello, wasi\nexit 3\n"
