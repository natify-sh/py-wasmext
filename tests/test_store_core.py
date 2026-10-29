"""Step 2 of layer 1 (docs/step2_store.md): the store and the table of errors, tested as plain C (tests/c/), with no wasm module and no Python in the program."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from wasmext._toolchain import find_toolchain  # pyright: ignore[reportPrivateUsage]

from .c_build import compile_c, find_cc, supports_flag
from .conftest import SANITIZED

HERE = Path(__file__).parent
C_DIR = HERE / "c"
WASMEXT_C = HERE.parent / "src" / "wasmext" / "c"
EXE = ".exe" if os.name == "nt" else ""


def _run(exe: Path) -> None:
    result = subprocess.run([str(exe)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_the_store(tmp_path: Path) -> None:
    exe = tmp_path / f"test_store{EXE}"
    compile_c([C_DIR / "test_store.c"], exe, include_dirs=[WASMEXT_C], threads=True)
    _run(exe)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ThreadSanitizer is checked on Linux")
def test_the_store_under_threadsanitizer(tmp_path: Path) -> None:
    if SANITIZED:
        pytest.skip("another sanitizer is on for the whole run; the two cannot be combined")
    if find_cc() is None or not supports_flag("-fsanitize=thread"):
        pytest.skip("no ThreadSanitizer")
    exe = tmp_path / "test_store_tsan"
    compile_c(
        [C_DIR / "test_store.c"],
        exe,
        include_dirs=[WASMEXT_C],
        flags=["-fsanitize=thread", "-g"],
        defines=["ROUNDS=4"],
        threads=True,
    )
    _run(exe)


def test_the_table_of_errors(tmp_path: Path) -> None:
    runtime = find_toolchain().runtime
    exe = tmp_path / f"test_errors{EXE}"
    compile_c(
        [
            C_DIR / "test_errors.c",
            runtime / "wasm-rt-impl.c",
            runtime / "wasm-rt-mem-impl.c",
            runtime / "wasm-rt-exceptions-impl.c",
        ],
        exe,
        include_dirs=[WASMEXT_C, runtime],
        strict=False,
        std=None,
    )
    _run(exe)
