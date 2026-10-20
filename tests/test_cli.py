"""The `wasmext` command: C only, build in place, and the exit codes."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import DATA, is_abi3_file, needs_abi3

SIMPLE = DATA / "simple.wasm"


def built(folder: Path, stem: str, *, recursive: bool = False) -> list[Path]:
    """The built extensions named `stem` in `folder`: .so on Linux and macOS, .pyd on Windows."""
    found = folder.rglob(f"{stem}.*") if recursive else folder.glob(f"{stem}.*")
    return [p for p in found if p.suffix in (".so", ".pyd")]


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
    done = wasmext(project, wabt, "natify", "src/pkg/*.wasm")
    assert done.returncode == 0, done.stderr
    assert "src/pkg/add.wasm -> pkg.add" in done.stdout
    generated = project / "src" / "pkg" / "add_wasmext"
    assert (generated / "add_py.c").is_file() and (generated / "add_w2c.c").is_file()
    assert not built(project / "src", "add", recursive=True) and not (project / "src" / "build").exists()


def test_inplace_builds_next_to_the_wasm(project: Path, wabt: Path) -> None:
    done = wasmext(project, wabt, "natify", "-q", "-i", "src/pkg/*.wasm")
    assert done.returncode == 0, done.stderr
    [extension] = built(project / "src" / "pkg", "add")
    out = subprocess.run(
        [sys.executable, "-c", "from pkg import add; print(add.Instance().add(40, 2))"],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip() == "42" and extension.parent == project / "src" / "pkg"


def test_build_goes_under_build(project: Path, wabt: Path) -> None:
    done = wasmext(project, wabt, "natify", "-q", "-b", "src/pkg/*.wasm")
    assert done.returncode == 0, done.stderr
    assert built(project / "src" / "build", "add", recursive=True)  # under build/ of the directory above the package
    assert not built(project / "src" / "pkg", "add")


def test_exclude_and_build_dir(project: Path, wabt: Path) -> None:
    shutil.copy(SIMPLE, project / "src" / "pkg" / "other.wasm")
    done = wasmext(project, wabt, "natify", "-X", "src/pkg/other.wasm", "--build-dir", "gen", "src/pkg/*.wasm")
    assert done.returncode == 0, done.stderr
    assert (project / "gen" / "pkg.add" / "add_py.c").is_file()
    assert not (project / "gen" / "pkg.other").exists()


def test_errors_have_a_message_and_a_nonzero_exit(project: Path, wabt: Path) -> None:
    nothing = wasmext(project, wabt, "natify", "nope/*.wasm")
    assert nothing.returncode == 1 and "no .wasm files" in nothing.stderr
    (project / "src" / "pkg" / "bad.wasm").write_bytes(b"not wasm")
    bad = wasmext(project, wabt, "natify", "src/pkg/bad.wasm")
    assert bad.returncode == 1 and "bad.wasm: not a WebAssembly binary" in bad.stderr
    code = (
        "import sys; sys.modules['wabt_package'] = None\n"
        "from wasmext._cli import main\n"
        "sys.exit(main(['natify', 'src/pkg/add.wasm', '--build-dir', 'elsewhere']))\n"
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
    assert wasmext(project, wabt, "natify", "src/pkg/add.wasm").returncode == 0
    (glue / "add_py.c").write_text("this is not C;\n", encoding="utf-8")
    # the first line says the C is current, so they are not written again: the compiler meets the broken one
    done = wasmext(project, None, "natify", "-q", "-b", "src/pkg/add.wasm")
    assert done.returncode == 1


def test_help_lists_the_flags(project: Path, wabt: Path) -> None:
    done = wasmext(project, wabt, "natify", "--help")
    assert done.returncode == 0
    for flag in ("--inplace", "--build", "--force", "--exclude", "--build-dir"):
        assert flag in done.stdout


def test_inplace_leaves_no_build_directory_and_handles_several_places(project: Path, wabt: Path) -> None:
    other = project / "tools"
    other.mkdir()
    shutil.copy(SIMPLE, other / "calc.wasm")
    done = wasmext(project, wabt, "natify", "-q", "-i", "src/pkg/add.wasm", "tools/calc.wasm")
    assert done.returncode == 0, done.stderr
    assert built(project / "src" / "pkg", "add") and built(other, "calc")
    assert not list(project.rglob("build")) and not list(project.rglob("tmp*"))


def test_stubs_are_written_unless_asked_not_to(project: Path, wabt: Path) -> None:
    assert wasmext(project, wabt, "natify", "-q", "src/pkg/add.wasm").returncode == 0
    assert (project / "src" / "pkg" / "add.pyi").is_file()
    (project / "src" / "pkg" / "add.pyi").unlink()
    assert wasmext(project, wabt, "natify", "-q", "--no-stubs", "src/pkg/add.wasm").returncode == 0
    assert not (project / "src" / "pkg" / "add.pyi").exists()


@needs_abi3
def test_abi3_builds_an_extension_that_runs(project: Path, wabt: Path) -> None:
    done = wasmext(project, wabt, "natify", "-q", "-i", "--limited-api", "src/pkg/add.wasm")
    assert done.returncode == 0, done.stderr
    [extension] = built(project / "src" / "pkg", "add")
    assert is_abi3_file(extension.name) or extension.suffix == ".pyd"
    out = subprocess.run(
        [sys.executable, "-c", "from pkg import add; print(add.Instance().add(40, 2))"],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip() == "42"


@needs_abi3
def test_inplace_removes_the_stale_variant_that_would_shadow_the_new_one(project: Path, wabt: Path) -> None:
    """Python tries `.cpython-3xx-<platform>.so` before `.abi3.so`: a native file left by an earlier build wins."""
    folder = project / "src" / "pkg"
    assert wasmext(project, wabt, "natify", "-q", "-i", "--no-limited-api", "src/pkg/add.wasm").returncode == 0
    [native] = built(folder, "add")
    assert not is_abi3_file(native.name)
    done = wasmext(project, wabt, "natify", "-q", "-i", "--limited-api", "src/pkg/add.wasm")
    assert done.returncode == 0, done.stderr
    [only] = built(folder, "add")
    assert only != native and not native.exists()
    assert "removed the stale" in done.stderr
    out = subprocess.run(
        [sys.executable, "-c", "from pkg import add; print(add.__file__.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1])"],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == only.name


def test_inspect_says_what_a_module_has_and_what_is_left_out(tmp_path: Path) -> None:
    shutil.copy(DATA / "features.wasm", tmp_path / "f.wasm")
    done = wasmext(tmp_path, None, "inspect", "f.wasm")
    assert done.returncode == 0, done.stderr
    text = " ".join(done.stdout.split())  # the columns are aligned with spaces: compare the words
    assert "env.twice func (f64) -> f64 ok" in text
    assert "add func (i32, i32) -> i32 method of Instance" in text
    assert "pair func () -> i32, i32 method of Instance" in text
    assert "tbl table funcref, 1 element not exposed: a table" in text
    assert "result: can be wrapped, but some exports are left out" in text
    assert not (tmp_path / "f_wasmext").exists()  # nothing is written


def test_inspect_exits_nonzero_for_what_cannot_be_wrapped(tmp_path: Path) -> None:
    # (type (func (param externref))) (import "e" "f" (func (type 0)))
    module = b"\0asm\1\0\0\0" + bytes([1, 5, 1, 0x60, 1, 0x6F, 0]) + bytes([2, 7, 1, 1, 0x65, 1, 0x66, 0, 0])
    (tmp_path / "v.wasm").write_bytes(module)
    (tmp_path / "junk.wasm").write_bytes(b"not wasm")
    bad = wasmext(tmp_path, None, "inspect", "v.wasm")
    assert bad.returncode == 1 and "e.f" in bad.stdout and "uses externref" in bad.stdout
    assert "result: cannot be wrapped" in bad.stdout
    junk = wasmext(tmp_path, None, "inspect", "junk.wasm", "missing.wasm")
    assert junk.returncode == 1 and "not a module wasmext can read" in junk.stdout and "missing.wasm" in junk.stdout


def test_version_is_printed_and_a_release_is_named_in_the_stub(capsys: pytest.CaptureFixture[str]) -> None:
    from wasmext import __version__
    from wasmext._cli import main  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.startswith(f"wasmext {__version__} (")


def test_the_stub_names_the_version_of_a_release_only() -> None:
    from wasmext import generate, parse
    from wasmext._natify import _RELEASE_VERSION  # pyright: ignore[reportPrivateUsage]

    wasm = b"\x00asm\x01\x00\x00\x00"
    assert (
        "# Generated by wasmext 0.1.0a1 from the WebAssembly module of m"
        in generate(parse(wasm), "m", version="0.1.0a1").stub
    )
    assert "# Generated by wasmext from the WebAssembly module of m" in generate(parse(wasm), "m").stub
    for release in ("1.0", "0.1.0a1", "2.3.4rc2", "1"):
        assert _RELEASE_VERSION.fullmatch(release)
    for development in ("0.0.0.dev142+g192c448.d20261019", "0.1.0a1.dev3", "0.1.0+local", "0+unknown", "1.0.post1"):
        assert not _RELEASE_VERSION.fullmatch(development)


def test_a_command_is_needed_and_a_file_is_not_one(tmp_path: Path) -> None:
    bare = wasmext(tmp_path, None, "f.wasm")
    assert bare.returncode == 2 and "invalid choice: 'f.wasm'" in bare.stderr and "natify" in bare.stderr
    nothing = wasmext(tmp_path, None)
    assert nothing.returncode == 2 and "COMMAND" in nothing.stderr
    help_ = wasmext(tmp_path, None, "--help")
    assert help_.returncode == 0 and "natify" in help_.stdout and "inspect" in help_.stdout


def test_inspect_agrees_with_the_generator_about_a_name_that_is_not_an_attribute(tmp_path: Path) -> None:
    name = b"__exports__"  # would hide a special name of Instance: the generator leaves it out of the attributes
    module = (
        b"\0asm\1\0\0\0"
        + bytes([1, 4, 1, 0x60, 0, 0])
        + bytes([3, 2, 1, 0])
        + bytes([7, 3 + len(name) + 1, 1, len(name)])
        + name
        + bytes([0, 0])
        + bytes([10, 4, 1, 2, 0, 0x0B])
    )
    (tmp_path / "r.wasm").write_bytes(module)
    done = wasmext(tmp_path, None, "inspect", "r.wasm")
    assert done.returncode == 0, done.stderr
    assert "not exposed: is not an attribute" in done.stdout and "method of Instance" not in done.stdout


def test_the_proposals_that_wasm2c_lacks_are_named_in_words(tmp_path: Path) -> None:
    gc = b"\0asm\1\0\0\0" + bytes([1, 5, 1, 0x5E, 0x7F, 0, 0])  # a struct type
    pages = b"\0asm\1\0\0\0" + bytes([5, 4, 1, 0x08, 1, 0x10])  # a memory with a custom page size
    (tmp_path / "gc.wasm").write_bytes(gc)
    (tmp_path / "pages.wasm").write_bytes(pages)
    said = wasmext(tmp_path, None, "inspect", "gc.wasm", "pages.wasm").stdout
    assert "GC proposal" in said and "custom page size" in said


def test_quiet_inplace_prints_nothing_not_even_warnings_of_the_compiler(project: Path, wabt: Path) -> None:
    done = wasmext(project, wabt, "natify", "-q", "-i", "--build-dir", "gen", "src/pkg/add.wasm")
    assert done.returncode == 0, done.stderr[-600:]
    if sys.platform != "win32":  # cl and link say what they compile and link whatever -q says
        assert done.stdout == "" and done.stderr == ""
    built = [p for p in (project / "src" / "pkg").glob("add.*") if p.suffix in (".so", ".pyd")]
    assert (project / "gen").is_dir() and built  # --build-dir is honoured with -i


def test_guard_pages_by_architecture_on_the_command_line(project: Path, wabt: Path) -> None:
    from wasmext._natify import target_arch  # pyright: ignore[reportPrivateUsage]

    here = target_arch()
    shutil_target = project / "src" / "pkg" / "add.wasm"
    assert shutil_target.is_file()
    for spec in (f"{here}=off", f"{here}=off,default=on", "off"):
        done = wasmext(project, wabt, "natify", "-q", "--guard-pages-for", spec, "src/pkg/add.wasm")
        assert done.returncode == 0, (spec, done.stderr[-400:])
    bad = wasmext(project, wabt, "natify", "-q", "--guard-pages-for", "x86", "src/pkg/add.wasm")
    assert bad.returncode == 1 and "guard pages" in bad.stderr
