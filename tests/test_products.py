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
    assert (package / "lib_ctypes.py").is_file() and (
        package / "lib_ctypes.pyi"
    ).is_file()  # the wrapper comes with the library
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
    assert (
        reactor.returncode == 1 and "serves the imports of WASI" in reactor.stderr and "Traceback" not in reactor.stderr
    )


def test_the_wheel_of_a_package_with_only_libraries_and_programs_is_not_tied_to_an_interpreter(
    tmp_path: Path, wabt: Path
) -> None:
    root = _project(
        tmp_path,
        wabt,
        '[[tool.wasmext.ext-modules]]\nmodule-list = "pkg/hello.wasm"\nproduct = "exe"\n',
    )
    env = {**os.environ, "WASMEXT_WABT": str(wabt)}
    done = subprocess.run(
        [sys.executable, "-c", "from setuptools import setup; setup()", "-q", "bdist_wheel", "-d", str(root / "dist")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-800:]
    (wheel,) = (root / "dist").glob("*.whl")
    assert wheel.name.startswith("prodtest-0-py3-none-"), wheel.name  # not cp311-cp311-...
    import zipfile

    with zipfile.ZipFile(wheel) as z:
        assert f"pkg/{product_filename('hello', 'exe')}" in z.namelist()  # the program is in the wheel


_LIBRARY_TABLE = '[[tool.wasmext.ext-modules]]\nmodule-list = "pkg/lib.wasm"\nproduct = "shared"\n'


def test_a_library_is_made_again_by_the_content_of_the_wasm_not_its_time(tmp_path: Path, wabt: Path) -> None:
    """Nothing is built twice for the same content; another module put in place with an older time is built, and its library is not the old one."""
    import ctypes

    root = _project(tmp_path, wabt, _LIBRARY_TABLE)
    assert _build_ext(root, wabt).returncode == 0
    library = root / "pkg" / product_filename("lib", "shared")
    built = library.stat().st_mtime_ns
    assert _build_ext(root, wabt).returncode == 0
    assert library.stat().st_mtime_ns == built  # the same .wasm, the same flags: left as it is
    wasm = root / "pkg" / "lib.wasm"
    os.utime(wasm, None)  # touched, the same bytes: still left as it is
    assert _build_ext(root, wabt).returncode == 0
    assert library.stat().st_mtime_ns == built
    (root / "other.wat").write_text('(module (func (export "other") (result i32) i32.const 7))', encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", root / "other.wat", "-o", wasm], check=True)
    os.utime(wasm, (946684800, 946684800))  # the year 2000: older than the library
    done = _build_ext(root, wabt)
    assert done.returncode == 0, done.stderr[-600:]
    assert library.stat().st_mtime_ns != built
    assert hasattr(ctypes.CDLL(str(library)), "lib_other")  # the library of the new module


def test_a_library_is_made_again_when_its_flags_change(tmp_path: Path, wabt: Path) -> None:
    root = _project(tmp_path, wabt, _LIBRARY_TABLE)
    assert _build_ext(root, wabt).returncode == 0
    library = root / "pkg" / product_filename("lib", "shared")
    built = library.stat().st_mtime_ns
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'product = "shared"\n', 'product = "shared"\ndefine-macros = [["WASMEXT_TEST_FLAG", "1"]]\n'
        ),
        encoding="utf-8",
    )
    assert _build_ext(root, wabt).returncode == 0
    assert library.stat().st_mtime_ns != built
