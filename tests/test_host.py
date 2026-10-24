"""The `host` of a module (docs/wasi_target.md): who stands on the other side of its imports. It is said, never guessed."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from wasmext import GenError, generate, parse
from wasmext._natify import generate_c  # pyright: ignore[reportPrivateUsage]
from wasmext._setuptools import pyproject_calls  # pyright: ignore[reportPrivateUsage]

from .conftest import DATA
from .test_wasm_parser import I32, functype, leb, module, name, section, vec

WASI = "wasi_snapshot_preview1"
Builder = Callable[..., ModuleType]


def _wasm(*imports: tuple[str, str]) -> bytes:
    """A module that imports the functions `(module, field)` as `(i32) -> ()` and exports a memory."""
    parts = [section(1, vec(functype([I32], [])))]
    if imports:
        parts.append(section(2, vec(*[name(m) + name(f) + b"\x00" + leb(0) for m, f in imports])))
    parts += [section(5, vec(b"\x00" + leb(1))), section(7, vec(name("memory") + b"\x02" + leb(0)))]
    return module(*parts)


def test_the_default_host_binds_nothing_and_says_so() -> None:
    glue = generate(parse(_wasm((WASI, "proc_exit"))), "m")
    assert "wasi_p1.h" not in glue.header and not glue.wasi_headers
    assert any("wasm32-wasip1" in note for note in glue.notes)  # a note, not a binding
    assert "__host__: Literal['wasm32']" in glue.stub.replace('"', "'")
    assert f"'{WASI}'" in glue.stub.replace('"', "'")  # the import is the caller's, so it is typed like any other


def test_wasip1_binds_wasi_and_is_told_by_the_module() -> None:
    glue = generate(parse(_wasm((WASI, "proc_exit"))), "m", host="wasm32-wasip1")
    assert glue.wasi_headers == ("wasi_p1.h",)
    assert not glue.notes
    assert "__host__: Literal['wasm32-wasip1']" in glue.stub.replace('"', "'")
    assert "__host__" in glue.source


def test_an_alias_is_the_same_host() -> None:
    a = generate(parse(_wasm((WASI, "proc_exit"))), "m", host="wasm32-unknown-unknown")
    assert "__host__: Literal['wasm32']" in a.stub.replace('"', "'")


@pytest.mark.parametrize("host", ["wasm32-wasip3", "auto", "", "x86_64"])
def test_a_host_that_is_not_known_is_refused(host: str) -> None:
    with pytest.raises(GenError, match="is not one of wasm32, wasm32-wasip1, wasm32-wasip2"):
        generate(parse(_wasm()), "m", host=host)


def test_wasip3_is_said_not_to_be_supported() -> None:
    with pytest.raises(GenError, match="WASI 0.3 is not supported"):
        generate(parse(_wasm()), "m", host="wasm32-wasip3")


def test_the_signature_check_is_of_what_was_said() -> None:
    wrong = _wasm((WASI, "no_such_call"))
    with pytest.raises(GenError, match="is not a function of"):
        generate(parse(wrong), "m", host="wasm32-wasip1")
    generate(parse(wrong), "m")  # with wasm32 the names prove nothing and nothing is checked


def test_imports_that_do_not_belong_to_the_host_are_plain_imports_with_a_note() -> None:
    both = _wasm((WASI, "proc_exit"), ("wasi:cli/environment@0.2.12", "get-arguments"))
    glue = generate(parse(both), "m", host="wasm32-wasip1")
    assert glue.wasi_headers == ("wasi_p1.h",)
    assert any("wasi:cli/environment@0.2.12" in note and "yours to give" in note for note in glue.notes)
    assert "wasi:cli/environment@0.2.12" in glue.stub  # typed as the caller's
    p2 = generate(parse(both), "m", host="wasm32-wasip2")
    assert not p2.wasi_headers and any("does not answer the imports of WASI 0.2" in n for n in p2.notes)


def test_a_module_built_with_the_default_host_asks_for_its_wasi_imports(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi_hello.wat", "host_default")
    assert mod.__host__ == "wasm32"
    with pytest.raises(mod.LinkError, match="has imports"):
        mod.Instance()  # the module does not get WASI by itself any more


def test_a_module_built_with_wasip1_gets_wasi_by_itself(build_extension: Builder) -> None:
    mod = build_extension(DATA / "wasi_hello.wat", "host_wasip1", host="wasm32-wasip1")
    assert mod.__host__ == "wasm32-wasip1"
    with pytest.raises(mod.WasiExit):
        mod.Instance()._start()  # pyright: ignore[reportPrivateUsage]


def test_a_program_needs_the_wasip1_host(tmp_path: Path, wabt: Path) -> None:
    wasm = tmp_path / "hello.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "wasi_hello.wat", "-o", wasm], check=True)
    made = generate_c(wasm, "hello", tmp_path / "out", force=True, quiet=True, stubs=False, parts=1)
    assert "exe" in made.targets and "wasm32-wasip1" in made.targets["exe"].reason
    ok = generate_c(
        wasm, "hello", tmp_path / "out1", force=True, quiet=True, stubs=False, parts=1, host="wasm32-wasip1"
    )
    assert not ok.targets["exe"].reason


def test_the_host_is_a_key_of_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.wasmext.ext-modules]\nmodule-list = "x"\nhost = "wasm32-wasip1"\n', encoding="utf-8"
    )
    assert pyproject_calls(tmp_path)[0]["host"] == "wasm32-wasip1"
    (tmp_path / "pyproject.toml").write_text(
        '[tool.wasmext.ext-modules]\nmodule-list = "x"\nhost = "auto"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="host must be one of"):
        pyproject_calls(tmp_path)


def test_a_call_of_wasi_is_replaced_through_imports_in_both_front_ends(
    build_front_end: Builder, front_end: str
) -> None:
    """The stub is one text for the extension and for the wrapper for ctypes (`Imports` keyed by the exact module, each call `NotRequired`), and
    both take the same dictionary: what the caller gives wins over the call that wasmext has."""
    mod = build_front_end(DATA / "wasi_hello.wat", f"host_replace_{front_end}", host="wasm32-wasip1")
    seen: list[tuple[int, ...]] = []

    def fd_write(*args: int) -> int:
        seen.append(args)
        return 0

    with pytest.raises(mod.WasiExit) as raised:
        mod.Instance({WASI: {"fd_write": fd_write}})._start()  # pyright: ignore[reportPrivateUsage]
    assert raised.value.code == 3 and len(seen) == 1 and seen[0][0] == 1  # fd 1; the real call did not write


def test_the_stub_types_every_module_of_the_imports_by_its_name() -> None:
    both = _wasm((WASI, "proc_exit"), ("env", "f"), ("wasi:cli/environment@0.2.12", "get-arguments"))
    stub = generate(parse(both), "m", host="wasm32-wasip1").stub
    assert (
        "_Imports_wasi_snapshot_preview1 = TypedDict('_Imports_wasi_snapshot_preview1', {'proc_exit': NotRequired["
        in stub
    )
    assert "_Imports_env = TypedDict('_Imports_env', {'f': Callable" in stub  # the caller's: required
    assert "_Imports_wasi_cli_environment_0_2_12 = TypedDict(" in stub
    assert "'wasi_snapshot_preview1': NotRequired[_Imports_wasi_snapshot_preview1]" in stub
    assert "'env': _Imports_env" in stub and "def __init__(self, imports: Imports, *, wasi" in stub  # env is asked for
    assert "_Imports0" not in stub
    compile(stub, "m.pyi", "exec")
    only = generate(parse(_wasm((WASI, "proc_exit"))), "m", host="wasm32-wasip1").stub
    assert "imports: Imports | None = None, *, wasi: Wasi | None = None" in only  # a WASI program asks for nothing
    twin = generate(parse(_wasm(("a-b", "f"), ("a_b", "g"))), "m").stub
    assert (
        "_Imports_a_b = " in twin and "_Imports_a_b_2 = " in twin
    )  # told apart by a number, in the order of the section
