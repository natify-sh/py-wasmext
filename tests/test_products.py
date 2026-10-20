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


def test_the_command_line_makes_one_product_in_place_with_i(tmp_path: Path, wabt: Path) -> None:
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

    assert run("-i", "--exe", "pkg/hello.wasm").returncode == 0
    ran = subprocess.run([root / "pkg" / product_filename("hello", "exe")], capture_output=True, check=False)
    assert ran.stdout == b"hello, wasi\n"
    assert run("-i", "--shared", "pkg/lib.wasm").returncode == 0
    assert (root / "pkg" / product_filename("lib", "shared")).is_file()
    both = run("--shared", "--exe", "pkg/lib.wasm")
    assert both.returncode == 2 and "not allowed with" in both.stderr  # one product for each run
    reactor = run(
        "--exe", "pkg/lib.wasm"
    )  # a library module is not a command (refused when the C is made, before any build)
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


def test_without_i_or_b_the_command_line_only_writes_the_c_of_a_product(tmp_path: Path, wabt: Path) -> None:
    """As `cythonize` without -b: the C is made (so it can be shipped, or named in package-data), nothing is compiled."""
    root = _project(tmp_path, wabt, "")
    env = {**os.environ, "WASMEXT_WABT": str(wabt)}

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "wasmext", "natify", *args],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    done = run("--shared", "pkg/lib.wasm")
    assert done.returncode == 0, done.stderr[-600:]
    work = root / "build" / "wasmext" / "pkg.lib"
    assert (work / "lib_api.h").is_file() and (work / "lib_shared.c").is_file() and (work / "lib_w2c.c").is_file()
    assert "the C of the shared lib" in done.stdout
    assert not (root / "pkg" / product_filename("lib", "shared")).exists()  # nothing was compiled
    done = run("--exe", "pkg/hello.wasm")
    assert done.returncode == 0, done.stderr[-600:]
    assert (root / "build" / "wasmext" / "pkg.hello" / "hello_main.c").is_file()
    assert not (root / "pkg" / product_filename("hello", "exe")).exists()


def test_the_c_of_a_product_is_made_when_natify_is_called_and_is_in_the_depends(
    tmp_path: Path, wabt: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So a source distribution carries it and a file of it can be named in package-data on the first build."""
    root = _project(tmp_path, wabt, "")
    monkeypatch.setenv("WASMEXT_WABT", str(wabt))
    monkeypatch.chdir(root)
    [ext] = natify("pkg/lib.wasm", product="shared", quiet=True)
    assert (root / "build" / "wasmext" / "pkg.lib" / "lib_api.h").is_file()  # made now, not at the build
    depends = [str(p) for p in ext.depends]
    for name in ("lib_api.h", "lib_shared.c", "lib_w2c.c", "lib_glue.h", "lib_rt_impl.c", "lib_py.c"):
        assert any(d.endswith(name) for d in depends), name  # the C of every target, the extension's too
    assert not any(d.endswith("lib_main.c") for d in depends)  # lib.wasm is not a command: it has no program


def test_a_source_distribution_has_no_generated_c_and_a_wheel_can_be_built_from_it(tmp_path: Path, wabt: Path) -> None:
    """The C is a step of the build, in build/wasmext/: not a source, so not in the sdist (distutils leaves build/ out), and the sdist builds, because wasm2c is a build requirement."""
    import tarfile
    import zipfile

    root = _project(tmp_path, wabt, _LIBRARY_TABLE)
    env = {**os.environ, "WASMEXT_WABT": str(wabt)}

    def setup(cwd: Path, *args: str) -> None:
        done = subprocess.run(
            [sys.executable, "-c", "from setuptools import setup; setup()", "-q", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr[-800:]

    setup(root, "sdist", "-d", str(root / "dist"))
    (sdist,) = (root / "dist").glob("*.tar.gz")
    with tarfile.open(sdist) as t:
        names = t.getnames()
        assert (root / "build" / "wasmext" / "pkg.lib" / "lib_w2c.c").is_file()  # made when the project was read
        assert any(n.endswith("pkg/lib.wasm") for n in names)
        assert not any(n.endswith((".c", "_api.h", "_glue.h")) for n in names), names
        unpacked = tmp_path / "from_sdist"
        t.extractall(unpacked, filter="data")
    (project,) = unpacked.iterdir()
    setup(project, "bdist_wheel", "-d", str(tmp_path / "whl"))
    (wheel,) = (tmp_path / "whl").glob("*.whl")
    with zipfile.ZipFile(wheel) as z:
        listed = z.namelist()
    assert any(n.startswith("pkg/") and n.endswith(product_filename("lib", "shared")) for n in listed)
    assert "pkg/lib_ctypes.py" in listed and not any(n.endswith("_api.h") for n in listed)


def test_the_c_of_every_target_the_module_can_have_is_generated_at_once(
    tmp_path: Path, wabt: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever product is asked for, the C of all of them is made, so the build of another product, or of another kind in a later step, never needs it made again."""
    root = _project(tmp_path, wabt, "")
    monkeypatch.setenv("WASMEXT_WABT", str(wabt))
    monkeypatch.chdir(root)
    work = root / "build" / "wasmext" / "pkg.hello"
    natify("pkg/hello.wasm", quiet=True)  # an extension was asked for
    wanted = ("hello_py.c", "hello_shared.c", "hello_api.h", "hello_main.c", "hello_w2c.c", "hello_glue.h")
    for name in wanted:
        assert (work / name).is_file(), name  # a WASI command can be all three
    before = {name: (work / name).stat().st_mtime_ns for name in wanted}
    natify("pkg/hello.wasm", product="exe", quiet=True)
    natify("pkg/hello.wasm", product="shared", quiet=True)
    assert {
        name: (work / name).stat().st_mtime_ns for name in wanted
    } == before  # nothing is made again for another product
    natify("pkg/lib.wasm", quiet=True)  # not a command: no program, and no error for the other targets
    lib = root / "build" / "wasmext" / "pkg.lib"
    assert (lib / "lib_py.c").is_file() and (lib / "lib_shared.c").is_file() and not (lib / "lib_main.c").exists()
    with pytest.raises(Exception, match="serves the imports of WASI"):
        natify("pkg/lib.wasm", product="exe", quiet=True)  # only when the program itself is asked for
