"""The examples are real projects: built by setuptools through wasmize(), then imported and run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def build_example(name: str, tmp_path: Path, wabt: Path) -> Path:
    project = tmp_path / name
    shutil.copytree(ROOT / "examples" / name, project, ignore=shutil.ignore_patterns("*_wasmext", "*.so", "build"))
    env = {**os.environ, "WASMEXT_WABT": str(wabt), "PYTHONPATH": str(ROOT / "src")}
    subprocess.run(
        [sys.executable, "setup.py", "-q", "build_ext", "--inplace"],
        cwd=project,
        env=env,
        check=True,
        capture_output=True,
    )
    return project


def test_coremark(tmp_path: Path, wabt: Path) -> None:
    project = build_example("coremark", tmp_path, wabt)
    # The benchmark times itself for 10 s with the clock it is given: this one runs 600 times too fast.
    code = "import time, coremark\nout = coremark.run(lambda: int(time.perf_counter() * 600_000) & 0xFFFFFFFF)\nprint(out)\n"
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    score = [line for line in out.splitlines() if line.startswith("CoreMark 1.0 :")]
    assert "Correct operation validated" in out and score and float(score[0].split()[3]) > 0, out
    assert any(
        p.name.startswith("_core.") and p.suffix in (".so", ".pyd") for p in (project / "src" / "coremark").iterdir()
    )


@pytest.mark.skipif(sys.platform == "win32", reason="the build line of the tests is for gcc/clang")
def test_the_coremark_sdist_directory_builds_without_wasm2c(tmp_path: Path, wabt: Path) -> None:
    """With the generated C beside the .wasm (as in an sdist) the build needs no wabt-package."""
    first = build_example("coremark", tmp_path, wabt)
    copy = tmp_path / "from_sdist"
    shutil.copytree(first, copy, ignore=shutil.ignore_patterns("*.so", "build"))
    env = {k: v for k, v in os.environ.items() if k != "WASMEXT_WABT"}
    env["PYTHONPATH"] = f"{ROOT / 'src'}"
    # `import wabt_package` must fail: a path entry that shadows it with nothing
    shadow = tmp_path / "shadow"
    (shadow / "wabt_package").mkdir(parents=True)
    (shadow / "wabt_package" / "__init__.py").write_text("raise ImportError('hidden')\n", encoding="utf-8")
    env["PYTHONPATH"] = os.pathsep.join([str(shadow), env["PYTHONPATH"]])
    subprocess.run(
        [sys.executable, "setup.py", "-q", "build_ext", "--inplace", "--force"],
        cwd=copy,
        env=env,
        check=True,
        capture_output=True,
    )
    assert any(p.name.startswith("_core.") for p in (copy / "src" / "coremark").iterdir())
