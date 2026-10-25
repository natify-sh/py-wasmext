"""Programs of WASI 0.2 as a toolchain makes them, not written by hand: a C program (wasi-sdk, `tests/data/wasi2_real/prog_c.wasm`, the core module of the component:
`clang --target=wasm32-wasip2 -O1 prog.c`, then `wasm-tools component unbundle --threshold 0`) and a Rust program (`rustc --target wasm32-wasip2`, built here when the
toolchain is there). Each runs as a program, as an extension and through the wrapper for ctypes: arguments, environment, stdin, files, directories, the clock."""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from wasmext._exe import build  # pyright: ignore[reportPrivateUsage]

from .conftest import DATA

Builder = Callable[..., ModuleType]
P2 = "wasm32-wasip2"
RUN = "wasi:cli/run@0.2.12#run"  # the version of the world is the toolchain's: wasi-sdk 34 says 0.2.12
RUN_RUST = "wasi:cli/run@0.2.0#run"
C_MODULE = DATA / "wasi2_real" / "prog_c.wasm"
RUST_SOURCE = DATA / "wasi2_real" / "prog.rs"


def rust_module(tmp_path: Path) -> Path:
    """The core module of the Rust program, or a skip when the toolchain is not there."""
    rustc = shutil.which("rustc")
    wasm_tools = shutil.which("wasm-tools")
    if rustc is None or wasm_tools is None:
        pytest.skip("rustc and wasm-tools are needed")
    component = tmp_path / "prog_rs.component.wasm"
    done = subprocess.run(
        [rustc, "--target", "wasm32-wasip2", "-O", "-o", str(component), str(RUST_SOURCE)],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip(f"rustc cannot build for wasm32-wasip2: {done.stderr.strip().splitlines()[-1:]}")
    modules = tmp_path / "modules"
    modules.mkdir()
    subprocess.run(
        [
            wasm_tools,
            "component",
            "unbundle",
            str(component),
            "--module-dir",
            str(modules),
            "-o",
            str(tmp_path / "stub.wasm"),
            "--threshold",
            "0",
        ],
        check=True,
        capture_output=True,
    )
    return modules / "unbundled-module0.wasm"


def program(tmp_path: Path, wasm: Path) -> Path:
    return build(wasm, tmp_path / ("prog.exe" if sys.platform == "win32" else "prog"), optimize=False, host=P2)


def test_a_c_program_runs_as_a_program(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    ran = subprocess.run(
        [program(tmp_path, C_MODULE), "--env", "GREETING=hi", "--dir", f"{data}::/data", "prog", "extra"],
        input=b"hello stdin\n",
        capture_output=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    lines = ran.stdout.decode().splitlines()
    assert lines[0] == "argc=2 argv0=prog"
    assert "arg 1=extra" in lines
    assert "GREETING=hi" in lines
    assert "stdin line: hello stdin" in lines
    assert "read back: written by wasip2" in lines
    assert "entries=2" in lines and "clock ok=1" in lines
    assert ran.stderr.decode().strip() == "to stderr"
    assert (data / "out.txt").read_text(encoding="utf-8") == "written by wasip2\n"
    assert (data / "sub").is_dir()


def test_a_c_program_runs_in_python(build_front_end: Builder, tmp_path: Path) -> None:
    mod = build_front_end(C_MODULE, "wasi2_prog_c", host=P2)
    data = tmp_path / "data"
    data.mkdir()
    out: list[bytes] = []
    err: list[bytes] = []
    wasi: dict[str, Any] = {
        "args": ["prog", "extra"],
        "env": {"GREETING": "hi"},
        "stdin": io.BytesIO(b"hello stdin\n"),
        "stdout": out.append,
        "stderr": err.append,
        "preopens": {"/data": data},
    }
    assert getattr(mod.Instance(wasi=wasi), RUN)() == 0
    lines = b"".join(out).decode().splitlines()
    assert lines[0] == "argc=2 argv0=prog" and "GREETING=hi" in lines and "stdin line: hello stdin" in lines
    assert "read back: written by wasip2" in lines and "entries=2" in lines
    assert b"".join(err) == b"to stderr\n"
    assert (data / "out.txt").read_text(encoding="utf-8") == "written by wasip2\n"


def test_a_rust_program_runs_as_a_program(tmp_path: Path) -> None:
    wasm = rust_module(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    ran = subprocess.run(
        [program(tmp_path, wasm), "--env", "GREETING=hi", "--dir", f"{data}::/data", "prog", "b"],
        input=b"first\nsecond\nthird\n",
        capture_output=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    lines = ran.stdout.decode().splitlines()
    assert lines[0] == 'args=["prog", "b"]'
    assert lines[1] == 'GREETING=Ok("hi")'
    assert "stdin: first" in lines and "rest bytes=13" in lines
    assert "lines=1000" in lines and 'dir=["deep", "moved.txt"]' in lines
    assert "missing is err=true" in lines and "slept>=20ms=true" in lines
    assert ran.stderr.decode().strip() == "to stderr"


def test_a_rust_program_runs_in_python(build_front_end: Builder, tmp_path: Path) -> None:
    wasm = rust_module(tmp_path)
    mod = build_front_end(wasm, "wasi2_prog_rs", host=P2)
    data = tmp_path / "data"
    data.mkdir()
    out: list[bytes] = []
    wasi: dict[str, Any] = {
        "args": ["prog", "b"],
        "env": {"GREETING": "hi"},
        "stdin": io.BytesIO(b"first\nsecond\nthird\n"),
        "stdout": out.append,
        "stderr": None,
        "preopens": {"/data": data},
    }
    inst = mod.Instance(wasi=wasi)
    with pytest.raises(mod.WasiExit) as ended:  # a Rust program ends with process::exit
        getattr(inst, RUN_RUST)()
    assert ended.value.code == 0  # std::process::exit(0) is wasi:cli/exit(ok)
    lines = b"".join(out).decode().splitlines()
    assert "lines=1000" in lines and 'dir=["deep", "moved.txt"]' in lines and "stdin: first" in lines
