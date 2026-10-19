"""[tool.wasmext.wasmize] of pyproject.toml: the extensions of a project with no setup.py (src/wasmext/_setuptools.py)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from wasmext._setuptools import pyproject_calls  # pyright: ignore[reportPrivateUsage]

from .conftest import DATA

ROOT = Path(__file__).resolve().parent.parent


def _project(tmp_path: Path, pyproject: str, setup: str | None = None) -> Path:
    project = tmp_path / "proj"
    (project / "src" / "pk").mkdir(parents=True)
    (project / "src" / "pk" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(DATA / "pywasm3" / "coremark-minimal.wasm", project / "src" / "pk" / "cm.wasm")
    (project / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    if setup is not None:
        (project / "setup.py").write_text(setup, encoding="utf-8")
    return project


BUILD = """\
[build-system]
requires = ["setuptools>=77", "wasmext"]
build-backend = "setuptools.build_meta"

[project]
name = "pk"
version = "0.1.0"

[tool.setuptools]
package-dir = { "" = "src" }
packages = ["pk"]
"""


def _build(project: Path, wabt: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "WASMEXT_WABT": str(wabt), "PYTHONPATH": str(ROOT / "src")}
    script = ["setup.py"] if (project / "setup.py").is_file() else ["-c", "from setuptools import setup; setup()"]
    return subprocess.run(
        [sys.executable, *script, "-q", "build_ext", "--inplace", "--force"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_project_with_no_setup_py_gets_its_extensions_from_pyproject(tmp_path: Path, wabt: Path) -> None:
    project = _project(
        tmp_path, BUILD + '\n[tool.wasmext.wasmize]\nmodule-list = "src/pk/*.wasm"\nparts = 2\nstubs = false\n'
    )
    built = _build(project, wabt)
    assert built.returncode == 0, built.stderr[-800:]
    assert any(p.name.startswith("cm.") and p.suffix in (".so", ".pyd") for p in (project / "src" / "pk").iterdir())
    assert len(list((project / "src" / "pk" / "cm_wasmext").glob("cm_w2c_*.c"))) == 2  # parts = 2 was read
    assert not (project / "src" / "pk" / "cm.pyi").exists()  # stubs = false was read


def test_several_calls_as_an_array_of_tables(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[[tool.wasmext.wasmize]]\nmodule-list = ["a/*.wasm"]\nparts = 8\n[[tool.wasmext.wasmize]]\nmodule-list = "b/*.wasm"\nguard-pages = false\n',
        encoding="utf-8",
    )
    assert pyproject_calls(tmp_path) == [
        {"module_list": ["a/*.wasm"], "parts": 8},
        {"module_list": "b/*.wasm", "guard_pages": False},
    ]


def test_without_the_table_there_is_nothing_to_do(tmp_path: Path) -> None:
    assert pyproject_calls(tmp_path) == []  # no file
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert pyproject_calls(tmp_path) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[tool.wasmext.wasmize]\nparts = 2\n", "needs module-list"),
        ('[tool.wasmext.wasmize]\nmodule-list = "x"\npartz = 2\n', "no key 'partz'"),
        ("[tool.wasmext.other]\nx = 1\n", r"\[tool.wasmext.other\] is not something wasmext knows"),
        ("[tool.wasmext]\nwasmize = [1]\n", "must be a table, or an array of tables"),
    ],
)
def test_a_wrong_table_is_refused_with_a_message(tmp_path: Path, text: str, message: str) -> None:
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    with pytest.raises((ValueError, TypeError), match=message):
        pyproject_calls(tmp_path)


def test_a_setup_py_that_calls_wasmize_and_a_table_are_a_mistake(tmp_path: Path, wabt: Path) -> None:
    setup = "from setuptools import setup\nfrom wasmext import wasmize\nsetup(ext_modules=wasmize('src/pk/*.wasm'))\n"
    project = _project(tmp_path, BUILD + '\n[tool.wasmext.wasmize]\nmodule-list = "src/pk/*.wasm"\n', setup)
    built = _build(project, wabt)
    assert built.returncode != 0
    assert "use one of them" in built.stderr


def test_a_setup_py_with_an_extension_of_another_kind_goes_with_the_table(tmp_path: Path, wabt: Path) -> None:
    setup = "from setuptools import Extension, setup\nsetup(ext_modules=[Extension('pk.plain', ['src/pk/plain.c'])])\n"
    project = _project(tmp_path, BUILD + '\n[tool.wasmext.wasmize]\nmodule-list = "src/pk/*.wasm"\n', setup)
    (project / "src" / "pk" / "plain.c").write_text(
        "#include <Python.h>\n"
        'static struct PyModuleDef m = {PyModuleDef_HEAD_INIT, "plain", 0, -1, 0};\n'
        "PyMODINIT_FUNC PyInit_plain(void) { return PyModule_Create(&m); }\n",
        encoding="utf-8",
    )
    built = _build(project, wabt)
    assert built.returncode == 0, built.stderr[-800:]
    names = {p.name.split(".")[0] for p in (project / "src" / "pk").iterdir() if p.suffix in (".so", ".pyd")}
    assert names == {"plain", "cm"}
