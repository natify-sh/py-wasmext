"""`wasmimport`: `import mod` finds `mod.wasm`, makes an extension of it, keeps it in a cache and loads it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import DATA, is_abi3_file, needs_abi3

SIMPLE = DATA / "simple.wasm"


@pytest.fixture
def env(wabt: Path, tmp_path: Path) -> dict[str, str]:
    return {**os.environ, "WASMEXT_WABT": str(wabt), "WASMIMPORT_BUILD_DIR": str(tmp_path / "cache")}


def python(cwd: Path, env: dict[str, str], code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", "import wasmimport\nwasmimport.install()\n" + code],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def cached(tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "cache").rglob("*") if p.suffix in (".so", ".pyd")]


def test_a_wasm_file_is_imported_and_the_extension_is_kept(tmp_path: Path, env: dict[str, str]) -> None:
    shutil.copy(SIMPLE, tmp_path / "fast.wasm")
    first = python(tmp_path, env, "import fast\nprint(fast.Instance().add(2, 3), fast.__file__)")
    assert first.returncode == 0, first.stderr[-600:]
    assert first.stdout.split()[0] == "5"
    [so] = cached(tmp_path)
    assert not (tmp_path / "fast.pyi").exists()  # nothing is written beside the source
    stamp = so.stat().st_mtime_ns
    again = python(tmp_path, env, "import fast\nprint(fast.Instance().add(4, 5))")
    assert again.returncode == 0 and again.stdout.strip() == "9"
    assert so.stat().st_mtime_ns == stamp  # loaded, not made again


def test_a_module_in_a_package(tmp_path: Path, env: dict[str, str]) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(SIMPLE, package / "add.wasm")
    done = python(tmp_path, env, "import pkg.add\nprint(pkg.add.Instance().add(1, 1), pkg.add.__name__)")
    assert done.returncode == 0, done.stderr[-600:]
    assert done.stdout.split() == ["2", "pkg.add"]


def test_a_changed_wasm_is_made_again(tmp_path: Path, env: dict[str, str]) -> None:
    shutil.copy(SIMPLE, tmp_path / "m.wasm")
    assert python(tmp_path, env, "import m\nprint(hasattr(m.Instance(), 'mul64'))").stdout.strip() == "False"
    shutil.copy(DATA / "features.wasm", tmp_path / "m.wasm")
    later = (tmp_path / "m.wasm").stat().st_mtime + 10
    os.utime(tmp_path / "m.wasm", (later, later))
    done = python(
        tmp_path,
        env,
        "import m\nprint(hasattr(m, 'Instance'))\n"
        "i = m.Instance({'env': {'log': print, 'twice': float, 'cb': print}})\nprint(i.mul64(2, 3))",
    )
    assert done.returncode == 0, done.stderr[-600:]
    assert done.stdout.split() == ["True", "6"]


def test_an_ordinary_module_wins_over_the_wasm(tmp_path: Path, env: dict[str, str]) -> None:
    shutil.copy(SIMPLE, tmp_path / "same.wasm")
    (tmp_path / "same.py").write_text("WHO = 'python'\n", encoding="utf-8")
    done = python(tmp_path, env, "import same\nprint(same.WHO)")
    assert done.stdout.strip() == "python" and not cached(tmp_path)


def test_a_bad_file_is_an_import_error_and_uninstall_stops_the_hook(tmp_path: Path, env: dict[str, str]) -> None:
    (tmp_path / "junk.wasm").write_bytes(b"not wasm")
    shutil.copy(SIMPLE, tmp_path / "good.wasm")
    code = """
try:
    import junk
except ImportError as exc:
    print('ImportError', 'junk.wasm' in str(exc))
wasmimport.uninstall()
try:
    import good
except ImportError:
    print('not found')
"""
    done = python(tmp_path, env, code)
    assert done.returncode == 0, done.stderr[-600:]
    assert done.stdout.splitlines() == ["ImportError True", "not found"]


def test_inplace_puts_the_extension_next_to_the_wasm(tmp_path: Path, env: dict[str, str]) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(SIMPLE, package / "add.wasm")
    done = python(
        tmp_path, env, "wasmimport.install(inplace=True)\nimport pkg.add\nprint(pkg.add.Instance().add(1, 2))"
    )
    assert done.returncode == 0, done.stderr[-600:]
    assert done.stdout.strip() == "3"
    assert [p for p in package.iterdir() if p.suffix in (".so", ".pyd")]
    assert not cached(tmp_path)


def test_build_in_temp_false_writes_the_c_beside_the_wasm(tmp_path: Path, env: dict[str, str]) -> None:
    shutil.copy(SIMPLE, tmp_path / "fast.wasm")
    done = python(
        tmp_path, env, "wasmimport.install(build_in_temp=False)\nimport fast\nprint(fast.Instance().add(1, 2))"
    )
    assert done.returncode == 0, done.stderr[-600:]
    assert (tmp_path / "build" / "wasmext" / "fast" / "fast_w2c.c").is_file()


def test_a_wasmbld_file_says_how_the_extension_is_made(tmp_path: Path, env: dict[str, str]) -> None:
    shutil.copy(SIMPLE, tmp_path / "fast.wasm")
    (tmp_path / "fast.wasmbld").write_text(
        "def make_ext(modname, wasmfilename):\n"
        "    from setuptools import Extension\n"
        "    return Extension(modname, [wasmfilename], libraries=['no_such_library_for_wasmimport'])\n",
        encoding="utf-8",
    )
    done = python(
        tmp_path,
        env,
        "try:\n    import fast\nexcept ImportError as exc:\n    print('ImportError', 'Building module fast failed' in str(exc))",
    )
    assert done.stdout.strip() == "ImportError True"  # the library it asks for is not there: the hook was used


def test_uninstall_takes_the_finder_that_install_gave(tmp_path: Path, env: dict[str, str]) -> None:
    shutil.copy(SIMPLE, tmp_path / "fast.wasm")
    code = "finder = wasmimport.install()\nwasmimport.uninstall(finder)\ntry:\n    import fast\nexcept ImportError:\n    print('not found')"
    assert python(tmp_path, env, code).stdout.strip() == "not found"


def test_what_the_compiler_prints_does_not_reach_the_standard_output(tmp_path: Path) -> None:
    """MSVC prints the names of the files it compiles to stdout: the build runs with it on stderr."""
    code = (
        "import subprocess, sys\n"
        "from wasmext._importer import _compiler_output_to_stderr\n"
        "with _compiler_output_to_stderr():\n"
        "    subprocess.run([sys.executable, '-c', 'print(\"from the compiler\")'], check=True)\n"
        "print('after')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["after"] and "from the compiler" in done.stderr


def test_a_change_of_how_it_is_built_makes_the_extension_again(tmp_path: Path, env: dict[str, str]) -> None:
    shutil.copy(SIMPLE, tmp_path / "fast.wasm")
    use = "import fast\nprint(fast.Instance().add(2, 3), fast.__file__)"
    first = python(tmp_path, env, f"wasmimport.install(guard_pages=True)\n{use}")
    assert first.returncode == 0, first.stderr[-600:]
    [so] = cached(tmp_path)
    stamp = so.stat().st_mtime_ns
    same = python(tmp_path, env, f"wasmimport.install(guard_pages=True)\n{use}")
    assert same.returncode == 0 and so.stat().st_mtime_ns == stamp  # the same settings: loaded
    changed = python(tmp_path, env, f"wasmimport.install(guard_pages=False)\n{use}")
    assert changed.returncode == 0, changed.stderr[-600:]
    assert changed.stdout.split()[0] == "5"
    assert so.stat().st_mtime_ns != stamp  # other settings: made again


@needs_abi3
def test_native_after_abi3_gives_the_native_extension_and_not_the_abi3_one_left_in_the_cache(
    tmp_path: Path, env: dict[str, str]
) -> None:
    shutil.copy(SIMPLE, tmp_path / "fast.wasm")
    use = "import fast\nprint(fast.__file__)"

    def is_abi3(
        printed: str,
    ) -> bool:  # fast.abi3.so, or fast.pyd on Windows; a native one has the tag of the interpreter too
        name = Path(printed.strip()).name
        return is_abi3_file(name) or name.count(".") == 1

    abi3 = python(tmp_path, env, f"wasmimport.install(limited_api=True)\n{use}")
    assert abi3.returncode == 0, abi3.stderr[-600:]
    assert is_abi3(abi3.stdout)
    native = python(tmp_path, env, f"wasmimport.install(limited_api=False)\n{use}")
    assert native.returncode == 0, native.stderr[-600:]
    assert not is_abi3(native.stdout)
    assert len(cached(tmp_path)) == 1  # the stale one is gone, not left to shadow the new one


def test_the_working_directory_does_not_make_the_extension_again(tmp_path: Path, env: dict[str, str]) -> None:
    """natify() gives its include directories relative to the working directory: they must not be part of what makes a cached
    extension stale (every program of the WASI tests was made again when the runner started it from another directory)."""
    shutil.copy(SIMPLE, tmp_path / "fast.wasm")
    here = {**env, "PYTHONPATH": str(tmp_path)}
    elsewhere = tmp_path / "elsewhere" / "deeper"
    elsewhere.mkdir(parents=True)
    first = python(tmp_path, here, "import fast\nprint(fast.Instance().add(2, 3))")
    assert first.returncode == 0, first.stderr
    [so] = cached(tmp_path)
    stamp = so.stat().st_mtime_ns
    other = python(elsewhere, here, "import fast\nprint(fast.Instance().add(2, 3))")
    assert other.returncode == 0, other.stderr
    assert so.stat().st_mtime_ns == stamp  # loaded from another directory, not made again
