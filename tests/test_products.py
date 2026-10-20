"""The products a module can be made into besides a Python extension: `natify(product=...)`, the `product` key of pyproject.toml and `--shared`/`--exe`."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from wasmext import natify
from wasmext._setuptools import product_filename, pyproject_calls  # pyright: ignore[reportPrivateUsage]

from .conftest import DATA


def _project(tmp_path: Path, wabt: Path, table: str) -> Path:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "wasi_hello.wat", "-o", package / "hello.wasm"], check=True)
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "shared_module.wat", "-o", package / "lib.wasm"], check=True)
    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'
        '[project]\nname = "prodtest"\nversion = "0"\n[tool.setuptools]\npackages = ["pkg"]\n' + table,
        encoding="utf-8",
    )
    return tmp_path


def _build_ext(root: Path, wabt: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "WASMEXT_WABT": str(wabt)}
    code = "from setuptools import setup; setup()"
    return subprocess.run(
        [sys.executable, "-c", code, "build_ext", "--inplace", "-q", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pyproject_asks_for_a_library_and_a_program(tmp_path: Path, wabt: Path) -> None:
    root = _project(
        tmp_path,
        wabt,
        '[[tool.wasmext.ext-modules]]\nmodule-list = "pkg/lib.wasm"\nproduct = "shared"\n'
        '[[tool.wasmext.ext-modules]]\nmodule-list = "pkg/hello.wasm"\nproduct = "exe"\n',
    )
    assert pyproject_calls(root)[1]["product"] == "exe"
    done = _build_ext(root, wabt)
    assert done.returncode == 0, done.stderr[-800:]
    package = root / "pkg"
    assert (package / product_filename("lib", "shared")).is_file()
    assert (package / "lib_ctypes.py").is_file() and (package / "lib_ctypes.pyi").is_file()  # the wrapper comes with the library
    ran = subprocess.run([package / product_filename("hello", "exe")], capture_output=True, check=False)
    assert ran.stdout == b"hello, wasi\n" and ran.returncode == 3


def test_natify_returns_extensions_marked_for_the_other_products(tmp_path: Path, wabt: Path) -> None:
    root = _project(tmp_path, wabt, "")
    made = natify(str(root / "pkg" / "hello.wasm"), product="exe")
    assert len(made) == 1 and made[0].sources == [(root / "pkg" / "hello.wasm").as_posix()]
    assert made[0]._wasmext_product == "exe"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="product must be one of"):
        natify(str(root / "pkg" / "hello.wasm"), product="dll")


def test_a_product_that_is_not_known_is_refused_in_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.wasmext.ext-modules]\nmodule-list = "x"\nproduct = "dll"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="product must be one of"):
        pyproject_calls(tmp_path)


def test_the_command_line_makes_one_product_in_place(tmp_path: Path, wabt: Path) -> None:
    root = _project(tmp_path, wabt, "")
    env = {**os.environ, "WASMEXT_WABT": str(wabt)}

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "wasmext", "natify", "-q", *args],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    assert run("--exe", "pkg/hello.wasm").returncode == 0
    ran = subprocess.run([root / "pkg" / product_filename("hello", "exe")], capture_output=True, check=False)
    assert ran.stdout == b"hello, wasi\n"
    assert run("--shared", "pkg/lib.wasm").returncode == 0
    assert (root / "pkg" / product_filename("lib", "shared")).is_file()
    both = run("--shared", "--exe", "pkg/lib.wasm")
    assert both.returncode == 2 and "not allowed with" in both.stderr  # one product for each run
    reactor = run("--exe", "pkg/lib.wasm")  # a library module is not a command
    assert reactor.returncode == 1 and "serves the imports of WASI" in reactor.stderr and "Traceback" not in reactor.stderr
