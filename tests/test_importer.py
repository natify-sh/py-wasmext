"""`wasmimport`: `import mod` finds `mod.wasm`, makes an extension of it, keeps it in a cache and loads it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import DATA

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
    assert (tmp_path / "fast_wasmext" / "fast_w2c.c").is_file()


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
