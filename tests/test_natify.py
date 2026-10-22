"""natify(): a project with `.wasm` files, built by setuptools into extensions that import and run."""

from __future__ import annotations

import hashlib
import itertools
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from setuptools import Extension

from wasmext import GenError, natify

from .conftest import DATA, needs_abi3

SIMPLE = DATA / "simple.wasm"
SETUP = """\
from setuptools import setup
from wasmext import natify

setup(name="demo", version="0", packages=["pkg"], ext_modules=natify({arg}, quiet=True))
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wabt: Path) -> Path:
    """tmp/pkg/{__init__.py, add.wasm} as the working directory, and wabt-package reachable."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(SIMPLE, tmp_path / "pkg" / "add.wasm")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WASMEXT_WABT", str(wabt))
    return tmp_path


def run_python(cwd: Path, *args: str) -> str:
    return subprocess.run([sys.executable, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def test_the_extensions_get_their_names_from_the_packages(project: Path) -> None:
    (project / "top.wasm").write_bytes(SIMPLE.read_bytes())
    [pkg_add] = natify("pkg/*.wasm", quiet=True)
    [top] = natify("top.wasm", quiet=True)
    assert (pkg_add.name, top.name) == ("pkg.add", "top")
    assert Path(pkg_add.sources[0]).as_posix() == "build/wasmext/pkg.add/add_py.c"
    assert "build/wasmext/pkg.add" in [Path(d).as_posix() for d in pkg_add.include_dirs]
    assert sorted(Path(s).name for s in pkg_add.sources) == [
        "add_py.c",
        "add_rt_exceptions.c",
        "add_rt_impl.c",
        "add_rt_mem.c",
        "add_w2c.c",
    ]


def test_setup_py_builds_a_working_extension(project: Path) -> None:
    (project / "setup.py").write_text(SETUP.format(arg='"pkg/*.wasm"'), encoding="utf-8")
    run_python(project, "setup.py", "-q", "build_ext", "--inplace")
    out = run_python(project, "-c", "from pkg import add; print(add.Instance().add(40, 2))")
    assert out.strip() == "42"


def test_an_extension_object_keeps_its_settings_and_gives_the_name(project: Path) -> None:
    ext = Extension("pkg.fast", ["pkg/add.wasm"], define_macros=[("X", "1")], libraries=["m"])
    [made] = natify([ext], quiet=True)
    assert made.name == "pkg.fast"
    assert ("X", "1") in made.define_macros and made.libraries == ["m"]
    assert not any(s.endswith(".wasm") for s in made.sources)
    assert ext.sources == ["pkg/add.wasm"]  # the argument is not changed
    (project / "setup.py").write_text(
        SETUP.format(arg='[__import__("setuptools").Extension("pkg.fast", ["pkg/add.wasm"])]'), encoding="utf-8"
    )
    run_python(project, "setup.py", "-q", "build_ext", "--inplace")
    assert run_python(project, "-c", "from pkg import fast; print(fast.Instance().add(1, 2))").strip() == "3"


def test_an_ordinary_extension_passes_through(project: Path) -> None:
    plain = Extension("other", ["other.c"])
    assert natify([plain, "pkg/*.wasm"], quiet=True)[0] is plain


def _head(path: Path) -> str:
    """The macros WASMEXT_GENERATED_* at the head of a file of the C."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(itertools.takewhile(lambda line: line.startswith("#define WASMEXT_GENERATED_"), lines))


def test_the_head_of_the_c_says_who_made_it(project: Path) -> None:
    from wasmext._natify import _generated_info  # pyright: ignore[reportPrivateUsage]

    natify("pkg/*.wasm", quiet=True)
    out = project / "build" / "wasmext" / "pkg.add"
    for name in ("add_w2c.c", "add_py.c"):
        info = _generated_info(out / name)
        assert info is not None and {"VERSION", "INPUTS", "SOURCES", "WABT", "PARTS", "WASM"} <= set(info), name
        assert (
            (out / name).read_text(encoding="utf-8").startswith("#define WASMEXT_GENERATED_")
        )  # macros, not a comment


def test_other_sources_of_wasmext_generate_the_c_again(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    natify("pkg/*.wasm", quiet=True)
    out = project / "build" / "wasmext" / "pkg.add"
    (out / "add_py.c").write_text("old", encoding="utf-8")
    monkeypatch.setattr("wasmext._natify.sources_digest", lambda: "f" * 64)  # a wasmext with other sources
    natify("pkg/*.wasm", quiet=True)
    assert (out / "add_py.c").read_text(encoding="utf-8") != "old"
    assert f'#define WASMEXT_GENERATED_SOURCES "{"f" * 64}"' in (out / "add_w2c.c").read_text(encoding="utf-8")


def test_the_inputs_digest_covers_every_input() -> None:
    from wasmext._natify import inputs_digest  # pyright: ignore[reportPrivateUsage]

    def digest(sources: str = "s", wabt: str = "w", parts: int = 1, name: str = "pkg.add", wasm: str = "d") -> str:
        return inputs_digest(sources, wabt, parts, name, wasm)

    seen = {
        digest(),
        digest(sources="S"),
        digest(wabt="W"),
        digest(parts=2),
        digest(name="pkg.sub"),
        digest(wasm="D"),
    }
    assert len(seen) == 6  # each input alone changes the digest


def test_a_c_with_a_comment_for_a_head_is_made_again(project: Path) -> None:
    """The C of a wasmext that wrote a comment (or any file with no macros at its head) is not current."""
    natify("pkg/*.wasm", quiet=True)
    out = project / "build" / "wasmext" / "pkg.add"
    w2c = out / "add_w2c.c"
    good = w2c.read_text(encoding="utf-8")
    w2c.write_text(
        "/* Generated by wasmext 0.1 (WABT 1.0.42, parts 1) */\n" + "\n".join(good.split("\n")[5:]), encoding="utf-8"
    )
    natify("pkg/*.wasm", quiet=True)
    assert w2c.read_text(encoding="utf-8") == good


def test_the_version_of_the_package_does_not_decide_whether_the_c_is_current(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The digest of the sources of wasmext does: a development tree is not rebuilt by every commit."""
    natify("pkg/*.wasm", quiet=True)
    out = project / "build" / "wasmext" / "pkg.add"
    (out / "add_py.c").write_text("old", encoding="utf-8")
    monkeypatch.setattr("wasmext._natify._version", lambda: "9.9.9")
    natify("pkg/*.wasm", quiet=True)
    assert (out / "add_py.c").read_text(encoding="utf-8") == "old"  # not made again


def test_a_different_wasm_or_force_generates_the_c_again(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The C is stale by the content of the .wasm, not by its time: a cache, a copy or an archive does not keep the times."""
    natify("pkg/*.wasm", quiet=True)
    out = project / "build" / "wasmext" / "pkg.add"
    w2c = out / "add_w2c.c"
    marker = out / "add_py.c"
    marker.write_text("old", encoding="utf-8")
    natify("pkg/*.wasm", quiet=True)
    assert marker.read_text(encoding="utf-8") == "old"  # same wasm, same maker: nothing is written
    wasm = project / "pkg" / "add.wasm"
    os.utime(wasm, (w2c.stat().st_mtime + 10, w2c.stat().st_mtime + 10))  # touched, the same bytes
    natify("pkg/*.wasm", quiet=True)
    assert marker.read_text(encoding="utf-8") == "old"
    marker.write_text("old", encoding="utf-8")
    monkeypatch.setenv("WASMEXT_FORCE_REGEN", "1")
    natify("pkg/*.wasm", quiet=True)
    assert marker.read_text(encoding="utf-8") != "old"


def test_a_wasm_of_other_content_makes_the_c_again_whatever_its_time(project: Path) -> None:
    """A module put in place of another with an older time (a copy that keeps the times, a restored cache) must not leave the C of the old one."""
    natify("pkg/*.wasm", quiet=True)
    out = project / "build" / "wasmext" / "pkg.add"
    before = (out / "add_w2c.c").read_bytes()
    wasm = project / "pkg" / "add.wasm"
    other = DATA / "kitchen_sink.wasm"
    wasm.write_bytes(other.read_bytes())
    os.utime(wasm, (946684800, 946684800))  # the year 2000: older than the C that is there
    natify("pkg/*.wasm", quiet=True)
    after = (out / "add_w2c.c").read_bytes()
    assert after != before
    assert (
        hashlib.sha256(other.read_bytes()).hexdigest().encode() in after[:600]
    )  # the head names the .wasm it was made from
    assert _head(out / "add_py.c") == _head(out / "add_w2c.c")  # and the Python layer is of the same module


def test_a_changed_wasm_is_generated_again(project: Path) -> None:
    natify("pkg/*.wasm", quiet=True)
    w2c = project / "build" / "wasmext" / "pkg.add" / "add_w2c.c"
    first = w2c.read_text(encoding="utf-8")
    shutil.copy(DATA / "features.wasm", project / "pkg" / "add.wasm")
    later = w2c.stat().st_mtime + 10
    os.utime(project / "pkg" / "add.wasm", (later, later))
    natify("pkg/*.wasm", quiet=True)
    assert w2c.read_text(encoding="utf-8") != first


def test_build_dir_and_exclude(project: Path) -> None:
    shutil.copy(SIMPLE, project / "pkg" / "skipped.wasm")
    [ext] = natify("pkg/*.wasm", exclude=["pkg/skipped.wasm"], build_dir="gen", quiet=True)
    assert ext.name == "pkg.add"
    assert (project / "gen" / "pkg.add" / "add_py.c").is_file()
    assert not (project / "build" / "wasmext" / "pkg.add").exists()


def test_notes_about_what_is_not_exposed(project: Path, wabt: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copy(DATA / "features.wasm", project / "pkg" / "add.wasm")
    natify("pkg/*.wasm")
    assert "not exposed" not in capsys.readouterr().err  # its table is a funcref table: it is exposed (instance["tbl"])
    (project / "pkg" / "ref.wat").write_text(
        '(module (table (export "t") 1 externref) (func (export "f") (result i32) i32.const 1))', encoding="utf-8"
    )
    subprocess.run(
        [wabt / "bin" / "wat2wasm", project / "pkg" / "ref.wat", "-o", project / "pkg" / "ref.wasm"], check=True
    )
    natify("pkg/ref.wasm")
    assert "pkg/ref.wasm: not exposed: table 't' is an externref table" in capsys.readouterr().err.replace(os.sep, "/")


def test_errors_say_which_file(project: Path) -> None:
    with pytest.raises(ValueError, match="two modules are named"):
        natify(["pkg/add.wasm", "pkg/*.wasm"], quiet=True)
    shutil.copy(SIMPLE, project / "pkg" / "my-module.wasm")
    with pytest.raises(ValueError, match="my-module.wasm.*not a module name"):
        natify("pkg/my-module.wasm", quiet=True)
    (project / "pkg" / "bad.wasm").write_bytes(b"not wasm")
    with pytest.raises(ValueError, match=r"bad\.wasm: not a WebAssembly binary"):
        natify("pkg/bad.wasm", quiet=True)
    with pytest.raises(ValueError, match="one is wanted"):
        natify([Extension("x", ["pkg/*.wasm"])], quiet=True)
    assert issubclass(GenError, ValueError)


def test_a_pattern_without_files_is_reported(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert natify("nothing/*.wasm") == []
    assert "does not match any files" in capsys.readouterr().err


def test_the_msvc_only_intrinsic_is_kept_to_x64(project: Path) -> None:
    """wasm2c's `_addcarry_u64` branch is for x64 MSVC only: ARM64 and Win32 (x86) build the C but do not link (WABT #2885)."""
    natify("pkg/*.wasm", quiet=True)
    c = (project / "build" / "wasmext" / "pkg.add" / "add_w2c.c").read_text(encoding="utf-8")
    assert "#elif defined(_MSC_VER) && defined(_M_X64)" in c
    assert not re.search(r"#elif defined\(_MSC_VER\)\s+if \(_addcarry_u64", c)


def test_stubs_can_be_turned_off(project: Path) -> None:
    natify("pkg/*.wasm", quiet=True, stubs=False)
    assert not (project / "pkg" / "add.pyi").exists()


@needs_abi3
def test_abi3_is_the_default_where_the_interpreter_has_it(project: Path) -> None:
    [default] = natify("pkg/*.wasm", quiet=True)
    assert default.py_limited_api and ("Py_LIMITED_API", "0x030B0000") in default.define_macros


@needs_abi3
def test_native_on_request(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    [native] = natify("pkg/*.wasm", quiet=True, limited_api=False)
    assert not native.py_limited_api and all(m[0] != "Py_LIMITED_API" for m in native.define_macros)
    monkeypatch.setenv("WASMEXT_LIMITED_API", "0")
    [from_env] = natify("pkg/*.wasm", quiet=True)
    [code_wins] = natify("pkg/*.wasm", quiet=True, limited_api=True)
    assert not from_env.py_limited_api and code_wins.py_limited_api


@pytest.mark.parametrize("why", ["free-threaded", "android", "emscripten", "ios", "pypy"])
def test_where_there_is_no_stable_abi_the_extension_is_native(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], why: str
) -> None:
    from wasmext import _natify  # pyright: ignore[reportPrivateUsage]

    real_var: Callable[[str], Any] = _natify.sysconfig.get_config_var

    def config_var(name: str) -> Any:
        return 1 if why == "free-threaded" and name == "Py_GIL_DISABLED" else real_var(name)

    monkeypatch.setattr(_natify.sysconfig, "get_config_var", config_var)
    if why == "pypy":
        monkeypatch.setattr(_natify.sys.implementation, "name", "pypy", raising=False)
    elif why != "free-threaded":
        monkeypatch.setattr(_natify.sysconfig, "get_platform", lambda: f"{why}_4_0_arm64")
    [ext] = natify("pkg/*.wasm", limited_api=True)  # asked for, but impossible: native, and it says why
    assert not ext.py_limited_api and all(m[0] != "Py_LIMITED_API" for m in ext.define_macros)
    assert "building a native extension" in capsys.readouterr().err
    [default] = natify("pkg/*.wasm", quiet=True)  # the default does not insist
    assert not default.py_limited_api


_VERSION = f"cp{sys.version_info.major}{sys.version_info.minor}"
_NATIVE_TAG = f"-{_VERSION}-{_VERSION}{'t' if sysconfig.get_config_var('Py_GIL_DISABLED') else ''}-"
# where abi3 is possible the default is abi3 (cp311-abi3); a free-threaded build has none and keeps its own tag
_DEFAULT_TAG = _NATIVE_TAG if sysconfig.get_config_var("Py_GIL_DISABLED") else "-cp311-abi3-"


@pytest.mark.parametrize(
    ("arg", "tag"), [('"pkg/*.wasm"', _DEFAULT_TAG), ('"pkg/*.wasm", limited_api=False', _NATIVE_TAG)]
)
def test_the_wheel_is_tagged_for_what_was_built(project: Path, arg: str, tag: str) -> None:
    """Nothing but natify() decides: abi3 gets its tag from wasmext's setuptools hook, native keeps the interpreter's."""
    (project / "setup.py").write_text(SETUP.format(arg=arg), encoding="utf-8")
    run_python(project, "setup.py", "-q", "bdist_wheel", "--dist-dir", "dist")
    [wheel] = (project / "dist").glob("*.whl")
    assert tag in wheel.name, wheel.name


def test_a_project_setting_outranks_the_automatic_wheel_tag(project: Path) -> None:
    from setuptools import Distribution

    from wasmext._setuptools import finalize_distribution_options  # pyright: ignore[reportPrivateUsage]

    [ext] = natify("pkg/*.wasm", quiet=True)
    dist = Distribution({"name": "demo", "ext_modules": [ext]})
    dist.get_option_dict("bdist_wheel")["py_limited_api"] = ("setup.cfg", "cp312")
    finalize_distribution_options(dist)
    assert dist.get_option_dict("bdist_wheel")["py_limited_api"] == ("setup.cfg", "cp312")


def test_guard_pages_can_be_turned_off_for_the_runtime(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    [default] = natify("pkg/*.wasm", quiet=True)
    assert ("WASM_RT_USE_MMAP", "0") not in default.define_macros
    [off] = natify("pkg/*.wasm", quiet=True, guard_pages=False)
    assert ("WASM_RT_USE_MMAP", "0") in off.define_macros
    monkeypatch.setenv("WASMEXT_GUARD_PAGES", "0")
    [by_env] = natify("pkg/*.wasm", quiet=True)
    assert ("WASM_RT_USE_MMAP", "0") in by_env.define_macros
    [on_again] = natify("pkg/*.wasm", quiet=True, guard_pages=True)  # the argument wins over the environment
    assert ("WASM_RT_USE_MMAP", "0") not in on_again.define_macros


def test_a_module_with_simd_gets_the_include_directory_of_simde(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wasmext._natify import _simde_include  # pyright: ignore[reportPrivateUsage]

    c = tmp_path / "m_w2c.c"
    c.write_text('#include "simde/wasm/simd128.h"\nint x;\n', encoding="utf-8")
    root = tmp_path / "wabt"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / ("wasm2c.exe" if os.name == "nt" else "wasm2c")).write_text("", encoding="utf-8")
    (root / "wasm2c").mkdir()
    for name in RUNTIME_FILES:
        (root / "wasm2c" / name).write_text("", encoding="utf-8")
    monkeypatch.setenv("WASMEXT_WABT", str(root))
    with pytest.raises(RuntimeError, match="simde"):
        _simde_include([c])
    (root / "include" / "simde").mkdir(parents=True)
    assert _simde_include([c]) == (str(root / "include"),)
    c.write_text("int x;\n", encoding="utf-8")  # no SIMD: nothing is looked for
    assert _simde_include([c]) == ()


def test_a_big_endian_host_builds_with_wabt_big_endian(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The C of wasm2c lays the memory out reversed only when told (-DWABT_BIG_ENDIAN=1): without it a big-endian host
    (s390x) computed the wrong values, with no error."""
    (project / "top.wasm").write_bytes(SIMPLE.read_bytes())
    [little] = natify("top.wasm", quiet=True)
    assert ("WABT_BIG_ENDIAN", "1") not in little.define_macros
    monkeypatch.setattr(sys, "byteorder", "big")
    [big] = natify("top.wasm", quiet=True)
    assert ("WABT_BIG_ENDIAN", "1") in big.define_macros


def test_the_locals_that_wasm2c_cuts_in_two_are_put_together() -> None:
    from wasmext._natify import _tail_call_locals  # pyright: ignore[reportPrivateUsage]

    broken = b"  u32   u32 var_i0, var_i1;\n  u64 var_j1;\nvar_l3 = 0, var_l4 = 0,\n      var_l5 = 0;\n  u64 var_l6 = 0;\n  var_i0 = var_p0;\n"
    assert _tail_call_locals(broken) == (
        b"  u32 var_i0, var_i1;\n  u64 var_j1;\n  u32 var_l3 = 0, var_l4 = 0,\n      var_l5 = 0;\n  u64 var_l6 = 0;\n  var_i0 = var_p0;\n"
    )
    whole = b"  u32 var_l3 = 0;\n  u32 var_i0, var_i1;\n  var_i0 = var_p0;\n"  # what a wasm2c without the bug writes
    assert _tail_call_locals(whole) == whole


def test_the_result_of_a_return_call_indirect_that_wasm2c_drops_is_put_in_the_tail_call_stack() -> None:
    from wasmext._natify import _tail_call_result  # pyright: ignore[reportPrivateUsage]

    broken = (
        b"  if (!instance->w2c_T0.data[var_i0].func_tailcallee.fn) {\n"
        b"    var_i0 = CALL_INDIRECT(instance->w2c_T0, u32 (*)(void*), w2c_c_t0, var_i0, instance->w2c_T0.data[var_i0].module_instance);\n"
        b"    next->fn = NULL;\n"
        b"  } else {\n"
    )
    assert _tail_call_result(broken) == broken.replace(b"    next->fn = NULL;\n", b"    goto var_Bfunc;\n")
    whole = b"  {\n    var_i0 = CALL_INDIRECT(t, u32 (*)(void*), ft, var_i0, m);\n  }\n  next->fn = NULL;\n"  # no func_tailcallee test: not that shape
    assert _tail_call_result(whole) == whole


RUNTIME_FILES = (
    "wasm-rt.h",
    "wasm-rt-impl.c",
    "wasm-rt-mem-impl.c",
    "wasm-rt-mem-impl-helper.inc",
    "wasm-rt-exceptions-impl.c",
)


def _clean_toolchain_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("WASMEXT_WABT", "WASMEXT_WASM2C", "WASMEXT_WASM2C_RUNTIME", "WASMEXT_WASM2C_INCLUDE"):
        monkeypatch.delenv(name, raising=False)


def test_each_part_of_the_toolchain_has_its_own_variable(
    wabt: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The executable and the runtime can come from different places, and with both given the wabt-package is not needed."""
    from wasmext._toolchain import find_toolchain  # pyright: ignore[reportPrivateUsage]

    _clean_toolchain_env(monkeypatch)
    suffix = ".exe" if os.name == "nt" else ""
    exe = wabt / "bin" / ("wasm2c" + suffix)
    runtime = tmp_path / "rt"
    runtime.mkdir()
    for name in (
        "wasm-rt.h",
        "wasm-rt-impl.c",
        "wasm-rt-mem-impl.c",
        "wasm-rt-mem-impl-helper.inc",
        "wasm-rt-exceptions-impl.c",
    ):
        (runtime / name).write_text("", encoding="utf-8")
    simde = tmp_path / "inc"
    (simde / "simde").mkdir(parents=True)

    monkeypatch.setenv("WASMEXT_WASM2C", str(exe))
    monkeypatch.setenv("WASMEXT_WASM2C_RUNTIME", str(runtime))
    monkeypatch.setenv("WASMEXT_WASM2C_INCLUDE", str(simde))
    monkeypatch.setitem(sys.modules, "wabt_package", None)  # an import of it fails: it is not looked for
    found = find_toolchain()
    assert (found.wasm2c, found.runtime, found.include) == (exe, runtime, simde)
    assert found.version.split(".")[0].isdigit()  # what `wasm2c --version` says

    monkeypatch.delenv("WASMEXT_WASM2C_RUNTIME")  # the runtime then has to come from somewhere else
    with pytest.raises(RuntimeError, match="WASMEXT_WASM2C_RUNTIME"):
        find_toolchain()
    monkeypatch.setenv("WASMEXT_WABT", str(wabt))
    assert find_toolchain().wasm2c == exe and find_toolchain().runtime != runtime


def test_the_variables_of_the_toolchain_are_checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from wasmext._toolchain import find_toolchain  # pyright: ignore[reportPrivateUsage]

    _clean_toolchain_env(monkeypatch)
    monkeypatch.setenv("WASMEXT_WASM2C", str(tmp_path / "nope"))
    monkeypatch.setenv("WASMEXT_WASM2C_RUNTIME", str(tmp_path))
    with pytest.raises(RuntimeError, match="WASMEXT_WASM2C=.*not a file"):
        find_toolchain()
    (tmp_path / "wasm2c").write_text("", encoding="utf-8")
    monkeypatch.setenv("WASMEXT_WASM2C", str(tmp_path / "wasm2c"))
    with pytest.raises(RuntimeError, match=r"WASMEXT_WASM2C_RUNTIME=.*wasm-rt\.h"):
        find_toolchain()
    for name in RUNTIME_FILES:
        (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setenv("WASMEXT_WASM2C_INCLUDE", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="WASMEXT_WASM2C_INCLUDE=.*not a directory"):
        find_toolchain()
    monkeypatch.delenv("WASMEXT_WASM2C_INCLUDE")
    assert find_toolchain().version == "unknown"  # an empty file is not a program that says its version


def test_a_runtime_that_lacks_files_is_refused_with_what_is_missing(
    wabt: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runtime of an older WABT (1.0.34 of Debian has no wasm-rt-mem-impl*) used to fail later, on a file that is not there."""
    from wasmext._toolchain import find_toolchain  # pyright: ignore[reportPrivateUsage]

    _clean_toolchain_env(monkeypatch)
    runtime = tmp_path / "rt"
    runtime.mkdir()
    for name in ("wasm-rt.h", "wasm-rt-impl.c", "wasm-rt-exceptions-impl.c"):
        (runtime / name).write_text("", encoding="utf-8")
    monkeypatch.setenv("WASMEXT_WASM2C", str(wabt / "bin" / ("wasm2c.exe" if os.name == "nt" else "wasm2c")))
    monkeypatch.setenv("WASMEXT_WASM2C_RUNTIME", str(runtime))
    with pytest.raises(RuntimeError, match=r"has not wasm-rt-mem-impl\.c, wasm-rt-mem-impl-helper\.inc"):
        find_toolchain()


@needs_abi3
def test_the_extensions_of_one_wheel_are_all_abi3_or_all_native(project: Path) -> None:
    """A wheel has one tag: the modules of wasmext follow what the others in it can be, and settings that contradict each other are an error."""
    from setuptools import Distribution, Extension

    from wasmext._setuptools import finalize_distribution_options  # pyright: ignore[reportPrivateUsage]

    def finalize(*extensions: Extension) -> Distribution:
        dist = Distribution({"name": "demo", "ext_modules": list(extensions)})
        finalize_distribution_options(dist)
        return dist

    def tagged(dist: Distribution) -> bool:
        return "py_limited_api" in dist.get_option_dict("bdist_wheel") or "py_limited_api" in dist.get_option_dict(
            "bdist_wheel"
        )

    handwritten = Extension("pkg.other", ["other.c"])  # for one interpreter
    [auto] = natify("pkg/*.wasm", quiet=True)
    dist = finalize(
        auto, handwritten
    )  # the default follows the hand-written extension: native, with no abi3 mark and no macro
    assert not tagged(dist) and not auto.py_limited_api and ("Py_LIMITED_API", "0x030B0000") not in auto.define_macros
    [only] = natify("pkg/*.wasm", quiet=True)
    assert tagged(finalize(only)) and only.py_limited_api  # alone it stays abi3
    [forced] = natify("pkg/*.wasm", quiet=True, limited_api=True)
    with pytest.raises(ValueError, match="is not abi3"):
        finalize(forced, handwritten)
    [yes] = natify("pkg/*.wasm", quiet=True, limited_api=True)
    [no] = natify("pkg/*.wasm", quiet=True, limited_api=False)
    with pytest.raises(ValueError, match="one setting"):
        finalize(yes, no)
    [follow] = natify("pkg/*.wasm", quiet=True)
    [native] = natify("pkg/*.wasm", quiet=True, limited_api=False)
    assert not tagged(finalize(follow, native)) and not follow.py_limited_api  # the default follows the explicit False
    [abi3] = natify("pkg/*.wasm", quiet=True)
    [library] = natify(
        "pkg/*.wasm", quiet=True, product="shared"
    )  # (a program needs a WASI command, and is refused when natify() runs)
    assert tagged(finalize(abi3, library))  # a library or a program does not tie the wheel to a Python


@pytest.mark.parametrize(
    ("platform", "arch"),
    [
        ("linux-x86_64", "x86_64"),
        ("linux-i686", "x86"),
        ("win32", "x86"),
        ("win-amd64", "x86_64"),
        ("win-arm64", "arm64"),
        ("macosx-11.0-arm64", "arm64"),
        ("macosx-10.13-x86_64", "x86_64"),
        ("linux-aarch64", "arm64"),
        ("linux-armv7l", "armv7l"),
        ("android-24-arm64_v8a", "arm64"),
        ("ios-13.0-arm64-iphoneos", "arm64"),
        ("linux-ppc64le", "ppc64le"),
        ("emscripten-4.0.9-wasm32", "wasm32"),
    ],
)
def test_the_architecture_of_the_target_has_one_name(platform: str, arch: str) -> None:
    from wasmext._natify import target_arch  # pyright: ignore[reportPrivateUsage]

    assert target_arch(platform) == arch


def test_guard_pages_are_decided_for_the_architecture_of_the_target(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wasmext._natify import parse_guard_pages, target_arch  # pyright: ignore[reportPrivateUsage]

    assert parse_guard_pages("off") is False and parse_guard_pages("1") is True
    assert parse_guard_pages("x86=off, armv7l=0,default=on") == {"x86": False, "armv7l": False, "default": True}
    with pytest.raises(ValueError, match="guard pages"):
        parse_guard_pages("x86")
    here = target_arch()
    macro = ("WASM_RT_USE_MMAP", "0")
    [off_here] = natify("pkg/*.wasm", quiet=True, guard_pages={here: False, "default": True})
    [on_here] = natify("pkg/*.wasm", quiet=True, guard_pages={here: True, "default": False})
    [other] = natify("pkg/*.wasm", quiet=True, guard_pages={"no-such-arch": False})  # not this one: the default (on)
    [text] = natify("pkg/*.wasm", quiet=True, guard_pages=f"{here}=off")
    assert macro in off_here.define_macros and macro not in on_here.define_macros
    assert macro not in other.define_macros and macro in text.define_macros
    monkeypatch.setenv("WASMEXT_GUARD_PAGES", f"{here}=off")
    [by_env] = natify("pkg/*.wasm", quiet=True)
    assert macro in by_env.define_macros


@needs_abi3
def test_abi3_is_asked_of_the_interpreter_and_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the interpreter loads is read from its own extension suffixes (as setuptools reads them); the platforms that pin one CPython are a decision on top."""
    import importlib.machinery
    import sys
    import sysconfig

    from wasmext._natify import abi3_possible  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(
        importlib.machinery, "EXTENSION_SUFFIXES", [".cpython-311-x86_64-linux-gnu.so", ".abi3.so", ".so"]
    )
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sysconfig, "get_platform", lambda: "linux-x86_64")
    assert abi3_possible() is None
    # an interpreter that lists no .abi3 suffix cannot load such a file
    monkeypatch.setattr(importlib.machinery, "EXTENSION_SUFFIXES", [".cpython-311-x86_64-linux-gnu.so", ".so"])
    assert "does not load abi3" in str(abi3_possible())
    # an interpreter that names the file with the platform: .abi3-<platform>.so
    monkeypatch.setattr(
        importlib.machinery,
        "EXTENSION_SUFFIXES",
        [".cpython-315-x86_64-linux-gnu.so", ".abi3-x86_64-linux-gnu.so", ".so"],
    )
    assert abi3_possible() is None
    # 3.15 lists .abi3t.so too: it is the stable ABI of a free-threaded build, not abi3
    monkeypatch.setattr(
        importlib.machinery, "EXTENSION_SUFFIXES", [".cpython-315-x86_64-linux-gnu.so", ".abi3t.so", ".so"]
    )
    assert "does not load abi3" in str(abi3_possible())
    # Windows: the plain .pyd is the abi3 suffix
    monkeypatch.setattr(importlib.machinery, "EXTENSION_SUFFIXES", [".cp311-win_amd64.pyd", ".pyd"])
    monkeypatch.setattr(sys, "platform", "win32")
    assert abi3_possible() is None
    # a platform that pins one CPython, though it loads abi3 files
    monkeypatch.setattr(
        importlib.machinery, "EXTENSION_SUFFIXES", [".cpython-313-wasm32-emscripten.so", ".abi3.so", ".so"]
    )
    for target, platform in (
        ("emscripten", "emscripten-4.0.9-wasm32"),
        ("android", "android-24-arm64_v8a"),
        ("ios", "ios-13.0-arm64-iphoneos"),
    ):
        monkeypatch.setattr(sysconfig, "get_platform", lambda platform=platform: platform)
        assert target in str(abi3_possible())
    # free-threaded: even where .pyd is listed (Windows)
    monkeypatch.setattr(sysconfig, "get_platform", lambda: "win-amd64")
    real = sysconfig.get_config_var

    def free_threaded(name: str) -> Any:
        return 1 if name == "Py_GIL_DISABLED" else real(name)

    monkeypatch.setattr(sysconfig, "get_config_var", free_threaded)
    assert "free-threaded" in str(abi3_possible())
    # not CPython
    monkeypatch.setattr(sysconfig, "get_config_var", real)
    monkeypatch.setattr(sys, "implementation", type("I", (), {"name": "pypy"})())
    assert "pypy has no stable ABI" in str(abi3_possible())


def test_a_stub_is_made_with_the_c_and_not_written_beside_the_wasm(project: Path) -> None:
    [ext] = natify("pkg/*.wasm", quiet=True)
    stub = project / "build" / "wasmext" / "pkg.add" / "add.pyi"
    assert "def add(self, arg0: int, arg1: int, /) -> int: ..." in stub.read_text(encoding="utf-8")
    assert Path(ext._wasmext_stub) == stub.resolve()  # type: ignore[attr-defined]  # absolute: the build puts it beside the extension
    assert not (project / "pkg" / "add.pyi").exists()
    stub.unlink()  # deleted: made again
    natify("pkg/*.wasm", quiet=True)
    assert stub.is_file()


def test_share_tables_is_an_input_of_the_c_and_gives_the_module_the_stack_of_entries(project: Path) -> None:
    """The option is in the digest that decides whether the C is current: a change makes it again. A module with no table that has it shares tables
    (the define for the trap handler, the class Table in the stub); without it nothing of that is there."""
    [plain] = natify("pkg/*.wasm", quiet=True)
    out = project / "build" / "wasmext" / "pkg.add"
    assert "WASMEXT_GENERATED_SHARE 0" in (out / "add_py.c").read_text(encoding="utf-8")
    assert "WASMEXT_TRAP_HANDLER" not in [name for name, _ in plain.define_macros]
    assert "class Table" not in (out / "add.pyi").read_text(encoding="utf-8")

    [shared] = natify("pkg/*.wasm", quiet=True, share_tables=True)
    assert "WASMEXT_GENERATED_SHARE 1" in (out / "add_py.c").read_text(encoding="utf-8")  # made again
    assert ("WASMEXT_TRAP_HANDLER", "wasmext_trap_add") in shared.define_macros
    assert "class Table" in (out / "add.pyi").read_text(encoding="utf-8")
    assert "add_table_new" in (out / "add_api.h").read_text(
        encoding="utf-8"
    )  # and the C API of the library has the tables

    natify("pkg/*.wasm", quiet=True)  # and back
    assert "add_table_new" not in (out / "add_api.h").read_text(encoding="utf-8")
    assert "WASMEXT_GENERATED_SHARE 0" in (out / "add_py.c").read_text(encoding="utf-8")


_ELEM_TEMPLATE = (
    b"typedef enum { RefFunc, RefNull, GlobalGet } wasm_elem_segment_expr_type_t;\n"
    b"    switch (src_expr->expr_type) {\n"
    b"      case RefFunc:\n"
    b"        *dest_val = (wasm_rt_funcref_t){\n"
    b"            src_expr->type, src_expr->func, src_expr->func_tailcallee,\n"
    b"            (char*)module_instance + src_expr->module_offset};\n"
    b"        break;\n"
    b"      case RefNull:\n"
)
_ELEM_ENTRIES = (
    b"static const wasm_elem_segment_expr_t elem_segment_exprs_w2c_m_e0[] = {\n"
    b"  {RefFunc, w2c_m_t0, (wasm_rt_function_ptr_t)wrap_w2c_env_f, {wasm_tailcall_w2c_env_f}, offsetof(w2c_m, w2c_env_instance)},\n"
    b"  {RefFunc, w2c_m_t0, (wasm_rt_function_ptr_t)w2c_m_f1, {NULL}, 0},\n"
    b"};\n"
)


def test_an_imported_function_in_an_element_segment_gets_the_pointer_to_the_import() -> None:
    from wasmext._natify import _repair_imported_elements  # pyright: ignore[reportPrivateUsage]

    template, entries = _repair_imported_elements(
        [_ELEM_TEMPLATE, _ELEM_ENTRIES]
    )  # the template and the entries are in different files
    assert b"RefFunc, RefNull, GlobalGet, RefImportFunc }" in template
    assert b"*(void**)((char*)module_instance + src_expr->module_offset)" in template
    assert b"      case RefFunc:\n" in template  # the case of the defined functions stays
    assert b"{RefImportFunc, w2c_m_t0, (wasm_rt_function_ptr_t)wrap_w2c_env_f" in entries
    assert (
        b"{RefFunc, w2c_m_t0, (wasm_rt_function_ptr_t)w2c_m_f1, {NULL}, 0}" in entries
    )  # a defined function has the offset 0 and is as it was
    assert _repair_imported_elements([template, entries]) == [template, entries]  # again: nothing more


def test_a_wasm2c_that_writes_the_element_segments_another_way_is_left_alone() -> None:
    from wasmext._natify import _repair_imported_elements  # pyright: ignore[reportPrivateUsage]

    fixed = _ELEM_TEMPLATE.replace(
        b"(char*)module_instance + src_expr->module_offset};",
        b"*(void**)((char*)module_instance + src_expr->module_offset)};",
    )
    assert _repair_imported_elements([fixed, _ELEM_ENTRIES]) == [
        fixed,
        _ELEM_ENTRIES,
    ]  # no such template: the entries are not rewritten either
    assert _repair_imported_elements([b"int main(void) { return 0; }\n"]) == [b"int main(void) { return 0; }\n"]


_SIGNAL_MACROS = [
    ("WASMEXT_CHAIN", "1"),
    ("WASMEXT_STACK_LIMIT", "1"),
    ("WASM_RT_NONCONFORMING_UNCHECKED_STACK_EXHAUSTION", "1"),
]


@pytest.mark.parametrize(
    ("platform", "macros", "link"),
    [
        ("linux-x86_64", _SIGNAL_MACROS, ["-Wl,-z,now"]),
        ("macosx-14.0-arm64", _SIGNAL_MACROS, []),
        ("win-amd64", [], []),
        ("win-arm64", [], []),
        ("emscripten-4.0.9-wasm32", [], []),  # wasm-ld does not know `-z now`, and there are no such signals
    ],
)
def test_the_chain_of_signal_handlers_is_for_the_target_that_has_signals(
    platform: str, macros: list[tuple[str, str]], link: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sysconfig

    from wasmext._natify import signal_build_flags

    monkeypatch.setattr(sysconfig, "get_platform", lambda: platform)
    if os.name == "nt":  # a Windows host never has it, whatever it builds for
        assert signal_build_flags() == ([], [])
    else:
        assert signal_build_flags() == (macros, link)


def test_the_guard_page_can_be_asked_for_instead_of_the_check_of_the_stack_and_is_warned_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sysconfig

    from wasmext._natify import signal_build_flags

    if os.name == "nt":
        pytest.skip("Windows has neither")
    monkeypatch.setattr(sysconfig, "get_platform", lambda: "linux-x86_64")
    monkeypatch.setenv("WASMEXT_STACK_CHECK", "guard")
    with pytest.warns(UserWarning, match="WASMEXT_STACK_CHECK=guard"):
        macros, link = signal_build_flags()
    assert macros == [("WASMEXT_CHAIN", "1")] and link == ["-Wl,-z,now"]
    monkeypatch.setenv("WASMEXT_STACK_CHECK", "fast")
    with pytest.raises(ValueError, match="WASMEXT_STACK_CHECK"):
        signal_build_flags()
