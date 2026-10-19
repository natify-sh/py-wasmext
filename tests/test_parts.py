# pyright: reportPrivateUsage=false
"""The C of a module in several files (`parts`), compiled at the same time."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from setuptools import Distribution

from wasmext import wasmize
from wasmext._wasmize import (
    AUTO_PART_SIZE,
    AUTO_SPLIT_FROM,
    MAX_AUTO_PARTS,
    _choose_parts,
    _existing_parts,
    _parts_warning,
    _prepare,
)

from .conftest import DATA

ROOT = Path(__file__).resolve().parent.parent


def test_the_number_of_parts_follows_the_size_unless_it_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WASMEXT_PARTS", raising=False)
    assert _choose_parts(1000, None) == 1
    assert _choose_parts(AUTO_SPLIT_FROM - 1, None) == 1  # a small module stays whole: the code is faster
    assert _choose_parts(AUTO_SPLIT_FROM, None) == -(-AUTO_SPLIT_FROM // AUTO_PART_SIZE)
    assert _choose_parts(10_785_625, None) == 83  # coreutils.wasm
    assert _choose_parts(10**9, None) == MAX_AUTO_PARTS
    assert _choose_parts(10_785_625, 1) == 1  # asked for: whole
    assert _choose_parts(10, 5) == 5  # asked for: even a small one
    assert _choose_parts(10, 10_000) == 10_000  # asked for: no limit (the warning says if it is unwise)
    monkeypatch.setenv("WASMEXT_PARTS", "4")
    assert _choose_parts(10, None) == 4
    assert _choose_parts(10, 2) == 2  # the argument wins over the environment
    monkeypatch.setenv("WASMEXT_PARTS", "many")
    with pytest.raises(ValueError, match="WASMEXT_PARTS must be a number"):
        _choose_parts(10, None)
    monkeypatch.delenv("WASMEXT_PARTS")
    with pytest.raises(ValueError, match="parts must be 1 or more"):
        _choose_parts(10, 0)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    (project / "src" / "pk").mkdir(parents=True)
    (project / "src" / "pk" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(DATA / "pywasm3" / "coremark-minimal.wasm", project / "src" / "pk" / "cm.wasm")
    return project


def _build(project: Path, wabt: Path, parts: int | None, **env: str) -> subprocess.CompletedProcess[str]:
    (project / "setup.py").write_text(
        f"from setuptools import setup\nfrom wasmext import wasmize\nsetup(package_dir={{'': 'src'}}, packages=['pk'], ext_modules=wasmize('src/pk/*.wasm', parts={parts!r}))\n",
        encoding="utf-8",
    )
    merged = {**os.environ, "WASMEXT_WABT": str(wabt), "PYTHONPATH": str(ROOT / "src"), **env}
    return subprocess.run(
        [sys.executable, "setup.py", "-q", "build_ext", "--inplace", "--force"],
        cwd=project,
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )


def _run(project: Path) -> str:
    code = (
        "import pk.cm\n"
        "now = 0\n"
        "def clock():\n"
        "    global now\n"
        "    now += 15000\n"
        "    return now\n"
        "print(round(pk.cm.Instance({'env': {'clock_ms': clock}}).run(), 4))\n"
    )
    ran = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr[-500:]
    return ran.stdout.strip()


def test_a_module_in_three_files_is_built_and_runs_the_same(tmp_path: Path, wabt: Path) -> None:
    project = _project(tmp_path)
    c_dir = project / "src" / "pk" / "cm_wasmext"
    built = _build(project, wabt, 3, WASMEXT_JOBS="2")
    assert built.returncode == 0, built.stderr[-800:]
    assert sorted(p.name for p in c_dir.glob("cm_w2c*")) == [
        "cm_w2c-impl.h",
        "cm_w2c.h",
        "cm_w2c_0.c",
        "cm_w2c_1.c",
        "cm_w2c_2.c",
    ]
    assert not (c_dir / "cm_w2c.c").exists()
    shared = (c_dir / "cm_w2c-impl.h").read_text(
        "utf-8"
    )  # the code the files share is made portable too (no _addcarry_u64 on x86)
    assert "_addcarry_u64" in shared and "defined(_MSC_VER)\n  if (_addcarry_u64(" not in shared
    assert "defined(_MSC_VER) && defined(_M_X64)" in shared
    assert _existing_parts(c_dir, "cm") == 3
    assert _run(project) == "0.6667"  # the same as the module in one file (tests/test_pywasm3.py)
    # another number of files: the old ones are gone, and it still runs
    again = _build(project, wabt, 1)
    assert again.returncode == 0, again.stderr[-800:]
    assert sorted(p.name for p in c_dir.glob("cm_w2c*")) == ["cm_w2c.c", "cm_w2c.h"]
    assert _run(project) == "0.6667"
    five = _build(project, wabt, 5)
    assert five.returncode == 0, five.stderr[-800:]
    assert _existing_parts(c_dir, "cm") == 5 and not (c_dir / "cm_w2c.c").exists()
    assert _run(project) == "0.6667"


def test_the_cli_takes_the_number_of_parts(tmp_path: Path, wabt: Path) -> None:
    project = _project(tmp_path)
    env = {**os.environ, "WASMEXT_WABT": str(wabt), "PYTHONPATH": str(ROOT / "src")}
    ran = subprocess.run(
        [sys.executable, "-m", "wasmext", "-q", "--parts", "2", "src/pk/cm.wasm"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    assert _existing_parts(project / "src" / "pk" / "cm_wasmext", "cm") == 2


def test_a_tree_with_its_c_in_files_is_used_where_there_is_no_wasm2c(
    tmp_path: Path, wabt: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    assert _build(project, wabt, 2).returncode == 0
    wasm = project / "src" / "pk" / "cm.wasm"
    out_dir = project / "src" / "pk" / "cm_wasmext"

    def no_toolchain() -> None:
        raise RuntimeError("no wabt")

    # the marker has the version of wasmext that the build process saw: a stale src/wasmext.egg-info (PYTHONPATH=src puts it first) can
    # make that another one than this process sees, so this process takes the one that is written
    marker = (out_dir / "cm_w2c_0.c").read_text("utf-8").splitlines()[0]
    version = re.match(r"/\* Generated by wasmext (\S+) ", marker)
    assert version is not None
    monkeypatch.setattr("wasmext._wasmize._version", lambda: version.group(1))
    monkeypatch.setattr("wasmext._wasmize.find_toolchain", no_toolchain)
    prepared = _prepare(wasm, "pk.cm", out_dir, force=False, quiet=True, stubs=False, parts=1)
    assert (
        prepared.parts == 2 and sum("cm_w2c_" in s for s in prepared.sources) == 2
    )  # what is there, not what was asked


def test_setuptools_gets_a_build_ext_that_compiles_at_once(
    tmp_path: Path, wabt: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    monkeypatch.setenv("WASMEXT_WABT", str(wabt))
    split = wasmize("src/pk/cm.wasm", parts=3, quiet=True)
    dist = Distribution({"name": "x", "ext_modules": split})
    dist.finalize_options()
    assert dist.cmdclass["build_ext"].__name__ == "WasmextBuildExt"
    whole = wasmize("src/pk/cm.wasm", parts=1, quiet=True)
    plain = Distribution({"name": "y", "ext_modules": whole})
    plain.finalize_options()
    assert "build_ext" not in plain.cmdclass  # one file: setuptools as it is


def test_a_number_of_files_that_is_unwise_is_warned_about_not_refused(
    tmp_path: Path, wabt: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("WASMEXT_WABT", str(wabt))
    wasm = _project(tmp_path) / "src" / "pk" / "cm.wasm"  # 11 KB, 11 functions
    out_dir = tmp_path / "c"
    assert _parts_warning(2, 11349, 11) is None
    assert "some of the files stay empty" in (_parts_warning(20, 11349, 11) or "")
    assert "bytes each" in (_parts_warning(5, 11349, 11) or "")
    assert _parts_warning(1, 100, 1) is None

    prepared = _prepare(wasm, "pk.cm", out_dir, force=True, quiet=False, stubs=False, parts=20)
    assert prepared.parts == 20  # done, not refused
    assert "20 files for 11 functions" in capsys.readouterr().err
    _prepare(wasm, "pk.cm", out_dir, force=True, quiet=True, stubs=False, parts=20)
    assert capsys.readouterr().err == ""  # quiet is quiet
    _prepare(wasm, "pk.cm", out_dir, force=True, quiet=False, stubs=False, parts=2)
    assert capsys.readouterr().err == ""  # a sensible number: nothing to say
