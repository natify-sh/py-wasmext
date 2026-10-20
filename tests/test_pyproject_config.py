"""[tool.wasmext.ext-modules] of pyproject.toml: the extensions of a project with no setup.py (src/wasmext/_setuptools.py)."""

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
        tmp_path, BUILD + '\n[tool.wasmext.ext-modules]\nmodule-list = "src/pk/*.wasm"\nparts = 2\nstubs = false\n'
    )
    built = _build(project, wabt)
    assert built.returncode == 0, built.stderr[-800:]
    assert any(p.name.startswith("cm.") and p.suffix in (".so", ".pyd") for p in (project / "src" / "pk").iterdir())
    assert len(list((project / "build" / "wasmext" / "pk.cm").glob("cm_w2c_*.c"))) == 2  # parts = 2 was read
    assert not (project / "src" / "pk" / "cm.pyi").exists()  # stubs = false was read


def test_several_calls_as_an_array_of_tables(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[[tool.wasmext.ext-modules]]\nmodule-list = ["a/*.wasm"]\nparts = 8\n[[tool.wasmext.ext-modules]]\nmodule-list = "b/*.wasm"\nguard-pages = false\n',
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
        ("[tool.wasmext.ext-modules]\nparts = 2\n", "needs module-list"),
        ('[tool.wasmext.ext-modules]\nmodule-list = "x"\npartz = 2\n', "no key 'partz'"),
        ("[tool.wasmext.other]\nx = 1\n", r"\[tool.wasmext.other\] is not something wasmext knows"),
        ("[tool.wasmext]\next-modules = [1]\n", "must be a table, or an array of tables"),
    ],
)
def test_a_wrong_table_is_refused_with_a_message(tmp_path: Path, text: str, message: str) -> None:
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    with pytest.raises((ValueError, TypeError), match=message):
        pyproject_calls(tmp_path)


def test_a_setup_py_that_calls_natify_and_a_table_are_a_mistake(tmp_path: Path, wabt: Path) -> None:
    setup = "from setuptools import setup\nfrom wasmext import natify\nsetup(ext_modules=natify('src/pk/*.wasm'))\n"
    project = _project(tmp_path, BUILD + '\n[tool.wasmext.ext-modules]\nmodule-list = "src/pk/*.wasm"\n', setup)
    built = _build(project, wabt)
    assert built.returncode != 0
    assert "use one of them" in built.stderr


def test_a_setup_py_with_an_extension_of_another_kind_goes_with_the_table(tmp_path: Path, wabt: Path) -> None:
    setup = "from setuptools import Extension, setup\nsetup(ext_modules=[Extension('pk.plain', ['src/pk/plain.c'])])\n"
    project = _project(tmp_path, BUILD + '\n[tool.wasmext.ext-modules]\nmodule-list = "src/pk/*.wasm"\n', setup)
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


def test_flags_macros_and_libraries_are_added_to_the_extensions(tmp_path: Path, wabt: Path) -> None:
    table = (
        '\n[tool.wasmext.ext-modules]\nmodule-list = "src/pk/*.wasm"\nstubs = false\n'
        'extra-compile-args = ["-O1"]\ndefine-macros = ["PLAIN", "VALUE=2", ["PAIR", "3"]]\nlibraries = ["m"]\n'
    )
    project = _project(tmp_path, BUILD + table)
    env = {**os.environ, "WASMEXT_WABT": str(wabt), "PYTHONPATH": str(ROOT / "src")}
    probe = (
        "from setuptools import Distribution\n"
        "dist = Distribution({'name': 'pk'})  # the hook of wasmext runs by itself\n"
        "[e] = dist.ext_modules\n"
        "print(e.extra_compile_args, e.libraries, [x for x in e.define_macros if x[0] in ('PLAIN', 'VALUE', 'PAIR')])\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], cwd=project, env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-600:]
    assert done.stdout.strip() == "['-O1'] ['m'] [('PLAIN', None), ('VALUE', '2'), ('PAIR', '3')]"


def test_a_macro_that_is_not_a_macro_is_refused(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.wasmext.ext-modules]\nmodule-list = "x"\ndefine-macros = [1]\n', encoding="utf-8"
    )
    with pytest.raises(TypeError, match="not NAME"):
        pyproject_calls(tmp_path)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ('quiet = "yes"', "quiet must be true or false"),
        ("parts = 0", "parts must be a whole number"),
        ("parts = true", "parts must be a whole number"),
        ("build-dir = 3", "build-dir must be a string"),
        ("module-list = 5", "module-list must be a string or a list"),
        ('libraries = "m"', "libraries must be a list of strings"),
        ("extra-compile-args = [1]", "extra-compile-args must be a list of strings"),
        ('define-macros = "A"', "define-macros must be a list"),
    ],
)
def test_a_value_of_the_wrong_type_is_refused_by_the_key(tmp_path: Path, line: str, message: str) -> None:
    body = "module-list = 'x'\n" if not line.startswith("module-list") else ""
    (tmp_path / "pyproject.toml").write_text(f"[tool.wasmext.ext-modules]\n{body}{line}\n", encoding="utf-8")
    with pytest.raises(TypeError, match=message):
        pyproject_calls(tmp_path)


def test_a_lone_exclude_pattern_is_one_pattern(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.wasmext.ext-modules]\nmodule-list = 'x'\nexclude = 'skip*'\n", encoding="utf-8"
    )
    assert pyproject_calls(tmp_path)[0]["exclude"] == ["skip*"]


def test_limited_api_is_one_setting_of_the_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.wasmext]\nlimited-api = false\n[[tool.wasmext.ext-modules]]\nmodule-list = 'a'\n[[tool.wasmext.ext-modules]]\nmodule-list = 'b'\n",
        encoding="utf-8",
    )
    assert [call["limited_api"] for call in pyproject_calls(tmp_path)] == [
        False,
        False,
    ]  # every entry is built the same way
    (tmp_path / "pyproject.toml").write_text(
        "[[tool.wasmext.ext-modules]]\nmodule-list = 'a'\nlimited-api = true\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="one setting for the whole project"):
        pyproject_calls(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.wasmext]\nlimited-api = 'yes'\n[[tool.wasmext.ext-modules]]\nmodule-list = 'a'\n", encoding="utf-8"
    )
    with pytest.raises(TypeError, match="limited-api must be true or false"):
        pyproject_calls(tmp_path)


def test_guard_pages_in_pyproject_are_a_bool_or_a_table_of_architectures(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[[tool.wasmext.ext-modules]]\nmodule-list = 'a'\nguard-pages = { x86 = false, default = true }\n",
        encoding="utf-8",
    )
    assert pyproject_calls(tmp_path)[0]["guard_pages"] == {"x86": False, "default": True}
    (tmp_path / "pyproject.toml").write_text(
        "[[tool.wasmext.ext-modules]]\nmodule-list = 'a'\nguard-pages = { x86 = 'no' }\n", encoding="utf-8"
    )
    with pytest.raises(TypeError, match="table of architectures"):
        pyproject_calls(tmp_path)
