from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import wabtwasm

ADD = '(module (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add))'


def test_wat_becomes_a_binary_module() -> None:
    wasm = wabtwasm.wat2wasm(ADD)
    assert wasm[:8] == b"\0asm\x01\0\0\0"
    assert b"add" in wasm


def test_a_wrong_module_is_an_error_with_the_message_of_the_tool() -> None:
    with pytest.raises(wabtwasm.WabtError) as info:
        wabtwasm.wat2wasm("(module (func (result i32) i64.const 1))")
    assert info.value.code != 0 and b"type mismatch" in info.value.stderr


def test_a_binary_module_becomes_c() -> None:
    files = wabtwasm.wasm2c(wabtwasm.wat2wasm(ADD), name="adder")
    assert sorted(files) == ["adder.c", "adder.h"]
    assert b"w2c_adder_add" in files["adder.c"] and b"w2c_adder_add" in files["adder.h"]


def test_the_c_can_be_split_into_files() -> None:
    files = wabtwasm.wasm2c(wabtwasm.wat2wasm(ADD), "--num-outputs=2", name="adder")
    assert len([n for n in files if n.endswith(".c")]) == 2


def test_the_output_is_that_of_the_native_tools() -> None:
    """The tools of the wabt-package are the same WABT: what they write is the same bytes and the same C."""
    wabt_package = pytest.importorskip("wabt_package")
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "m.wat").write_text(ADD, encoding="utf-8")
        subprocess.run([wabt_package.get_executable("wat2wasm"), "m.wat", "-o", "native.wasm"], cwd=root, check=True)
        subprocess.run(
            [wabt_package.get_executable("wasm2c"), "native.wasm", "-o", "m.c", "--module-name=m"], cwd=root, check=True
        )
        native_wasm = (root / "native.wasm").read_bytes()
        native_c = (root / "m.c").read_bytes()
        native_h = (root / "m.h").read_bytes()
    wasm = wabtwasm.wat2wasm(ADD)
    assert wasm == native_wasm
    files = wabtwasm.wasm2c(native_wasm, name="m")
    assert files["m.c"] == native_c and files["m.h"] == native_h


def test_calls_are_independent() -> None:
    first = wabtwasm.wat2wasm(ADD)
    second = wabtwasm.wat2wasm('(module (func (export "x")))')
    assert first != second and wabtwasm.wat2wasm(ADD) == first


@pytest.mark.skipif(sys.platform == "win32", reason="bin/wasm2c is a shell script")
def test_a_directory_for_wasmext_is_made_and_its_wasm2c_runs(tmp_path: Path) -> None:
    from wabtwasm._toolchain import make_toolchain

    root = make_toolchain(tmp_path / "wabt")
    assert (root / "wasm2c" / "wasm-rt.h").is_file() and (root / "bin" / "wasm2c").is_file()
    assert (root / "_wabt_version.txt").read_text(encoding="utf-8").strip() == "1.0.42-wabtwasm"
    work = tmp_path / "work"
    work.mkdir()
    (work / "m.wasm").write_bytes(wabtwasm.wat2wasm(ADD))
    ran = subprocess.run(
        [
            root / "bin" / "wasm2c",
            work / "m.wasm",
            "-o",
            work / "m.c",
            "--module-name=m",
        ],  # absolute paths, as wasmext gives them
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    assert b"w2c_m_add" in (work / "m.c").read_bytes()
