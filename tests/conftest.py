"""Builds extensions from WAT for the tests: `wat2wasm` and `wasm2c` from the wabt-package (or WASMEXT_WABT, a
directory with its `bin/` and `wasm2c/`) and the C compiler of the machine. Skipped where one of them is missing."""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from wasmext import generate, parse
from wasmext._gen import module_prefix
from wasmext._natify import _export_tags, _tail_call_locals  # pyright: ignore[reportPrivateUsage]

DATA = Path(__file__).parent / "data"
WASMEXT_C = Path(__file__).parent.parent / "src" / "wasmext" / "c"


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
def build_extension(wabt: Path, tmp_path_factory: pytest.TempPathFactory) -> Callable[..., ModuleType]:
    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    # platform.system(), not sys.platform: pyright takes a comparison with sys.platform as fixed and then does not
    # type-check what follows the skip when it runs on that platform.
    if cc is None or platform.system() == "Windows":
        pytest.skip("no C compiler of the cc kind")
    # a macOS extension finds the Python symbols in the interpreter that imports it
    link_flags: list[str] = ["-undefined", "dynamic_lookup"] if platform.system() == "Darwin" else []
    out = tmp_path_factory.mktemp("ext")
    sys.path.insert(0, str(out))

    def build(source: Path, name: str, *, abi3: bool = False, defines: tuple[str, ...] = ()) -> ModuleType:
        wasm = source
        if source.suffix == ".wat":
            wasm = out / f"{name}.wasm"
            subprocess.run([wabt / "bin" / "wat2wasm", source, "-o", wasm], check=True)
        glue = generate(parse(wasm.read_bytes()), name)
        (out / f"{name}_py.c").write_text(glue.source, encoding="utf-8")
        (out / f"{name}_glue.h").write_text(glue.header, encoding="utf-8")
        for c_name in (
            "wasmext_glue.h",
            *(("wasi_core.h", "wasi_files_win32.h", "wasi_python.h", *glue.wasi_headers) if glue.wasi_headers else ()),
        ):  # beside the glue, which includes them
            (out / c_name).write_bytes((WASMEXT_C / c_name).read_bytes())
        subprocess.run(
            [wabt / "bin" / "wasm2c", wasm, "-o", out / f"{name}_w2c.c", f"--module-name={name}"], check=True
        )
        w2c = out / f"{name}_w2c.c"
        w2c.write_bytes(
            _export_tags(_tail_call_locals(w2c.read_bytes()), module_prefix(name))
        )  # the repairs that natify() makes
        runtime = wabt / "wasm2c"
        limited = ["-DPy_LIMITED_API=0x030B0000"] if abi3 else []
        so = out / (name + str(sysconfig.get_config_var("EXT_SUFFIX")))
        include = [f"-I{runtime}", f"-I{out}", f"-I{sysconfig.get_paths()['include']}"]
        glue_object = out / f"{name}_py.o"
        # The glue is ours, so it is built strictly: GCC 14 makes these errors (older ones warn), and the manylinux and
        # user machines have it. The C of wasm2c and its runtime are not ours to police.
        strict = [
            "-Wall",
            "-Werror=incompatible-pointer-types",
            "-Werror=implicit-function-declaration",
            "-Werror=int-conversion",
        ]
        subprocess.run(
            [
                cc,
                "-O1",
                "-fPIC",
                *strict,
                *limited,
                *(f"-D{d}" for d in defines),
                *include,
                "-c",
                out / f"{name}_py.c",
                "-o",
                glue_object,
            ],
            check=True,
        )
        subprocess.run(
            [
                cc, "-O1", "-w", "-shared", "-fPIC", *link_flags, *limited, *include,
                glue_object, out / f"{name}_w2c.c", runtime / "wasm-rt-impl.c", runtime / "wasm-rt-mem-impl.c",
                runtime / "wasm-rt-exceptions-impl.c",
                "-o", so,
            ],
            check=True,
        )  # fmt: skip
        return importlib.import_module(name)

    return build
