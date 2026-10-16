"""The `wasmext` command: C only, build in place, and the exit codes."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import DATA

SIMPLE = DATA.parent.parent / "wasm" / "simple.wasm"


def wasmext(cwd: Path, wabt: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "WASMEXT_WABT"}
    if wabt is not None:
        env["WASMEXT_WABT"] = str(wabt)
    return subprocess.run(
        [sys.executable, "-m", "wasmext", *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


@pytest.fixture
def project(tmp_path: Path, wabt: Path) -> Path:
    """tmp/src/pkg/{__init__.py, add.wasm}"""
    package = tmp_path / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(SIMPLE, package / "add.wasm")
    return tmp_path


def test_without_flags_it_writes_the_c_and_builds_nothing(project: Path, wabt: Path) -> None:
    done = wasmext(project, wabt, "src/pkg/*.wasm")
    assert done.returncode == 0, done.stderr
    assert "src/pkg/add.wasm -> pkg.add" in done.stdout
    generated = project / "src" / "pkg" / "add_wasmext"
    assert (generated / "add_glue.c").is_file() and (generated / "add_w2c.c").is_file()
    assert not list((project / "src" / "pkg").glob("add.*.so")) and not (project / "build").exists()


def test_inplace_builds_next_to_the_wasm(project: Path, wabt: Path) -> None:
    done = wasmext(project, wabt, "-q", "-i", "src/pkg/*.wasm")
    assert done.returncode == 0, done.stderr
    [built] = [p for p in (project / "src" / "pkg").iterdir() if p.name.startswith("add.") and p.suffix == ".so"]
    out = subprocess.run(
        [sys.executable, "-c", "from pkg import add; print(add.Instance().add(40, 2))"],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip() == "42" and built.parent == project / "src" / "pkg"


def test_build_goes_under_build(project: Path, wabt: Path) -> None:
    done = wasmext(project, wabt, "-q", "-b", "src/pkg/*.wasm")
    assert done.returncode == 0, done.stderr
    assert list((project / "build").rglob("add.*.so"))
    assert not list((project / "src").rglob("add.*.so"))


def test_exclude_and_build_dir(project: Path, wabt: Path) -> None:
    shutil.copy(SIMPLE, project / "src" / "pkg" / "other.wasm")
    done = wasmext(project, wabt, "-X", "src/pkg/other.wasm", "--build-dir", "gen", "src/pkg/*.wasm")
    assert done.returncode == 0, done.stderr
    assert (project / "gen" / "pkg.add" / "add_glue.c").is_file()
    assert not (project / "gen" / "pkg.other").exists()


def test_errors_have_a_message_and_a_nonzero_exit(project: Path, wabt: Path) -> None:
    nothing = wasmext(project, wabt, "nope/*.wasm")
    assert nothing.returncode == 1 and "no .wasm files" in nothing.stderr
    (project / "src" / "pkg" / "bad.wasm").write_bytes(b"not wasm")
    bad = wasmext(project, wabt, "src/pkg/bad.wasm")
    assert bad.returncode == 1 and "bad.wasm: not a WebAssembly binary" in bad.stderr
    code = (
        "import sys; sys.modules['wabt_package'] = None\n"
        "from wasmext._cli import main\n"
        "sys.exit(main(['src/pkg/add.wasm', '--build-dir', 'elsewhere']))\n"
    )
    no_tools = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env={k: v for k, v in os.environ.items() if k != "WASMEXT_WABT"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert no_tools.returncode == 1 and "wabt-package" in no_tools.stderr


def test_a_failed_build_exits_nonzero(project: Path, wabt: Path) -> None:
    glue = project / "src" / "pkg" / "add_wasmext"
    assert wasmext(project, wabt, "src/pkg/add.wasm").returncode == 0
    (glue / "add_glue.c").write_text("this is not C;\n", encoding="utf-8")
    # the stamp says the files are current, so they are not written again: the compiler meets the broken one
    done = wasmext(project, None, "-q", "-b", "src/pkg/add.wasm")
    assert done.returncode == 1


def test_help_lists_the_flags(project: Path, wabt: Path) -> None:
    done = wasmext(project, wabt, "--help")
    assert done.returncode == 0
    for flag in ("--inplace", "--build", "--force", "--exclude", "--build-dir"):
        assert flag in done.stdout
