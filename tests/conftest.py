"""Builds extensions from WAT for the tests: `wat2wasm` and `wasm2c` from the wabt-package (or WASMEXT_WABT, a
directory with its `bin/` and `wasm2c/`) and the C compiler of the machine. Skipped where one of them is missing."""

from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from wasmext import generate, parse

DATA = Path(__file__).parent / "data"


def _wabt_dir() -> Path | None:
    env = os.environ.get("WASMEXT_WABT")
    if env:
        return Path(env)
    spec = importlib.util.find_spec("wabt_package")
    return Path(spec.origin).parent if spec and spec.origin else None


@pytest.fixture(scope="session")
def wabt() -> Path:
    path = _wabt_dir()
    if path is None or not (path / "bin").is_dir():
        pytest.skip("no wabt-package: set WASMEXT_WABT to a directory with bin/ and wasm2c/")
    return path


@pytest.fixture(scope="session")
def build_extension(wabt: Path, tmp_path_factory: pytest.TempPathFactory) -> Callable[[Path, str], ModuleType]:
    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    if cc is None or sys.platform == "win32":
        pytest.skip("no C compiler of the cc kind")
    out = tmp_path_factory.mktemp("ext")
    sys.path.insert(0, str(out))

    def build(source: Path, name: str) -> ModuleType:
        wasm = source
        if source.suffix == ".wat":
            wasm = out / f"{name}.wasm"
            subprocess.run([wabt / "bin" / "wat2wasm", source, "-o", wasm], check=True)
        glue = generate(parse(wasm.read_bytes()), name)
        (out / f"{name}_glue.c").write_text(glue.source, encoding="utf-8")
        subprocess.run(
            [wabt / "bin" / "wasm2c", wasm, "-o", out / f"{name}_w2c.c", f"--module-name={name}"], check=True
        )
        runtime = wabt / "wasm2c"
        so = out / (name + str(sysconfig.get_config_var("EXT_SUFFIX")))
        subprocess.run(
            [
                cc, "-O1", "-Wall", "-Wno-unused-value", "-shared", "-fPIC",
                f"-I{runtime}", f"-I{out}", f"-I{sysconfig.get_paths()['include']}",
                out / f"{name}_glue.c", out / f"{name}_w2c.c",
                runtime / "wasm-rt-impl.c", runtime / "wasm-rt-mem-impl.c",
                "-o", so,
            ],
            check=True,
        )  # fmt: skip
        return importlib.import_module(name)

    return build
