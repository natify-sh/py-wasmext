"""The C API of a module as a shared library (wasmext._shared, built by wasmext._exe.build_shared): checked with a host in C, with no Python anywhere in it —
the protocol of errors of host functions (stage 6a of the plan)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from wasmext._exe import build_shared  # pyright: ignore[reportPrivateUsage]

from .conftest import DATA


@pytest.mark.skipif(sys.platform == "win32", reason="the host is linked with cc; Windows is tried in CI")
def test_a_host_in_c_uses_the_library_and_a_failing_host_function_is_a_trap_of_the_call(
    wabt: Path, tmp_path: Path
) -> None:
    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler of the cc kind")
    wasm = tmp_path / "mod.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "shared_module.wat", "-o", wasm], check=True)
    suffix = ".dylib" if platform.system() == "Darwin" else ".so"
    library = build_shared(wasm, tmp_path / f"libmod{suffix}", name="mod", optimize=False)
    host = tmp_path / "host"
    subprocess.run(
        [cc, "-Wall", "-o", host, DATA / "shared_host.c", f"-I{tmp_path / 'libmod_wasmext'}", library],
        check=True,
    )
    env = {**os.environ, "LD_LIBRARY_PATH": str(tmp_path), "DYLD_LIBRARY_PATH": str(tmp_path)}
    ran = subprocess.run([host], capture_output=True, text=True, env=env, check=False)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        "instantiate without the import: LINK_ERROR",
        "instantiate: 0",
        "add: 0 5",
        "twice: 0 7 7",
        "call_log: 0 101",
        "call_log again: 0 102",
        "call_log failing: TRAP_HOST, host calls 3",
        "add after the failure: 0 42",
        "trap: 1 (Unreachable instruction executed)",
        "boom: exception 1 tag 0 count 1 value -9",
        "memory: 65536 hi",
    ]


def test_a_module_that_imports_a_global_has_no_shared_library_yet(wabt: Path, tmp_path: Path) -> None:
    from wasmext import GenError

    wat = tmp_path / "g.wat"
    wat.write_text(
        '(module (import "env" "g" (global i32)) (func (export "f") (result i32) global.get 0))', encoding="utf-8"
    )
    wasm = tmp_path / "g.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    with pytest.raises(GenError, match="imports a global"):
        build_shared(wasm, tmp_path / "libg.so", name="g", optimize=False)
