"""The examples are real projects: built by setuptools through natify(), then imported and run."""

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
    # The benchmark decides how long to run from the clock it is given and wants a last run of 10 s or more: with a real clock
    # the length of the last run depends on how the machine behaves between the calibration and the run. This clock does not:
    # the first timed run lasts 1.5 s, the next one 15 s, whatever they really took.
    code = (
        "import coremark\n"
        "calls = []\n"
        "now = 1_000_000\n"
        "def clock():\n"
        "    global now\n"
        "    calls.append(now)\n"
        "    if len(calls) % 2 == 0:\n"
        "        now += 1500 if len(calls) <= 2 else 15000\n"
        "    return now\n"
        "print(coremark.run(clock))\n"
    )
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
def test_link_example_modules_use_each_other(tmp_path: Path, wabt: Path) -> None:
    project = build_example("link", tmp_path, wabt)
    out = subprocess.run(
        [sys.executable, "-m", "linkdemo"],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "the variable of counter: 2" in out and "starts with: Hello" in out, out
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(project / "tests")],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        check=True,
        capture_output=True,
    )
