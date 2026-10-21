"""The generator on its own (no compiler): names, skipped exports, what it refuses."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wasmext import GenError, generate, mangle, parse

from .conftest import DATA
from .test_wasm_parser import EXTERNREF, F64, I32, code, functype, leb, module, name, section, vec

HEADER_FUNC = section(3, vec(leb(0)))


# The right-hand sides are what `wasm2c` 1.0.42 itself wrote for these export names (see test_mangling_follows_wasm2c).
MANGLED = {
    "add": "add",
    "my_func": "my_func",
    "_lead": "0x5Flead",
    "trail_": "trail0x5F",
    "a__b": "a_0x5Fb",
    "a-b.c": "a0x2Db0x2Ec",
    "0xAB": "0x0x41B",
    "0xab": "0xab",  # only capitals are hex digits for the mangler
    "зв": "0xD00xB70xD00xB2",
    "x___y_": "x_0x5F_y0x5F",
    "A0x1": "A0x0x31",
    "0x0x4F": "0x0x30x4F",
}


@pytest.mark.parametrize(("text", "expected"), MANGLED.items())
def test_mangling_of_names(text: str, expected: str) -> None:
    assert mangle(text) == expected


def test_mangling_of_module_names_doubles_the_underscores() -> None:
    assert mangle("my_mod_", module=True) == "my__mod0x5F"
    assert mangle("fast", module=True) == "fast"


def test_mangling_follows_wasm2c(wabt: Path, tmp_path: Path) -> None:
    """Every name above through the real `wasm2c`: the exports of the C it writes are `w2c_<module>_<mangled>`."""
    funcs = "".join(f'(func (export "{n}"))' for n in MANGLED)
    (tmp_path / "n.wat").write_text(f"(module {funcs})", encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", tmp_path / "n.wat", "-o", tmp_path / "n.wasm"], check=True)
    subprocess.run(
        [wabt / "bin" / "wasm2c", tmp_path / "n.wasm", "-o", tmp_path / "n.c", "--module-name=my_mod_"], check=True
    )
    header = (tmp_path / "n.h").read_text(encoding="utf-8")
    prefix = f"w2c_{mangle('my_mod_', module=True)}_"
    for text in MANGLED:
        assert f"{prefix}{mangle(text)}(" in header, text


def test_an_externref_export_is_skipped_but_an_import_of_one_is_refused() -> None:
    skipped = module(
        section(1, vec(functype([EXTERNREF], [EXTERNREF]))),
        HEADER_FUNC,
        section(7, vec(name("vec") + b"\x00" + leb(0))),
        code(b"\x00\x20\x00\x0b"),
    )
    glue = generate(parse(skipped), "m")
    assert glue.skipped == ["function 'vec' uses externref"]
    assert "Instance_f" not in glue.source.replace("Instance_free", "")

    refused = module(
        section(1, vec(functype([EXTERNREF], []))),
        section(2, vec(name("env") + name("f") + b"\x00" + leb(0))),
    )
    with pytest.raises(GenError, match=r"env\.f uses externref"):
        generate(parse(refused), "m")


def test_an_imported_memory_is_taken_from_another_instance_but_not_a_shared_one() -> None:
    data = module(section(2, vec(name("env") + name("mem") + b"\x02\x00" + leb(1))))
    glue = generate(parse(data), "m")
    assert "wasm_rt_memory_t *w2c_env_mem(" in glue.header and "'mem': object" in glue.stub
    shared = module(section(2, vec(name("env") + name("mem") + b"\x02\x03" + leb(1) + leb(2))))
    with pytest.raises(GenError, match="imported shared memory"):
        generate(parse(shared), "m")


def test_the_module_name_must_be_an_identifier() -> None:
    data = module(section(1, vec(functype([I32], [F64]))), HEADER_FUNC, code(b"\x00\x44" + bytes(8) + b"\x0b"))
    generate(parse(data), "pkg.sub.good")
    for bad in ("bad-name", "1abc", "pkg.", ""):
        with pytest.raises(GenError):
            generate(parse(data), bad)


def test_the_dotted_name_is_the_type_name_and_the_last_part_the_init_function() -> None:
    data = module(section(1, vec(functype([], []))), HEADER_FUNC, code(b"\x00\x0b"))
    glue = generate(parse(data), "pkg.sub.fast")
    assert "PyMODINIT_FUNC PyInit_fast(void)" in glue.source
    assert '"pkg.sub.fast.Instance"' in glue.source
    assert '#include "fast_glue.h"' in glue.source  # the Python layer includes the glue of the module ...
    assert (
        '#include "fast_w2c.h"' in glue.header and "#include <Python.h>" not in glue.header
    )  # ... which has no Python in it


def test_the_stub_describes_the_extension() -> None:
    glue = generate(parse((DATA / "features.wasm").read_bytes()), "features_ext")
    stub = glue.stub
    compile(stub, "features_ext.pyi", "exec")  # it is Python
    assert "def add(self, arg0: int, arg1: int, /) -> int: ..." in stub
    assert "def fadd(self, arg0: float, arg1: float, /) -> float: ..." in stub
    assert "def nop(self) -> None: ..." in stub
    assert "def mem(self) -> memoryview: ..." in stub
    assert "'twice': Callable[[float], float]" in stub and "def __init__(self, imports: Imports) -> None: ..." in stub
    assert "def pair(self) -> tuple[int, int]: ..." in stub  # several results: a tuple
    assert "def answer(self) -> int: ..." in stub  # an immutable global: a read-only attribute
    assert "def tbl" not in stub and "tbl:" not in stub  # a table is not an attribute of the instance...
    assert "def __getitem__(self, name: Literal['tbl'], /) -> Table: ..." in stub  # ...instance['tbl'] is a Table
    header = stub.splitlines()[:5]
    assert (
        "# ruff: noqa" in header and "# ruff: noqa: PGH004" in header and "# fmt: off" in header
    )  # a formatter and a linter leave it alone


def test_the_stub_of_a_module_without_imports_needs_no_arguments_or_imports() -> None:
    data = module(
        section(1, vec(functype([I32], [I32]))),
        HEADER_FUNC,
        section(7, vec(name("f") + b"\x00" + leb(0))),
        code(b"\x00\x20\x00\x0b"),
    )
    stub = generate(parse(data), "m").stub
    assert "def __init__(self) -> None: ..." in stub and "Callable" not in stub and "TypedDict" not in stub


def test_the_stub_of_a_wasi_program_types_every_key_of_wasi_and_the_exit() -> None:
    data = module(
        section(1, vec(functype([], [I32]))),
        section(2, vec(name("wasi_snapshot_preview1") + name("sched_yield") + b"\x00" + leb(0))),
        section(5, vec(b"\x00" + leb(1))),
        section(7, vec(name("memory") + b"\x02" + leb(0))),
    )
    stub = generate(parse(data), "m").stub
    assert "class WasiExit(WasiTerminated):" in stub and "class WasiSignal(WasiTerminated):" in stub
    assert "class WasiTerminated(Exception)" in stub and "wasi: Wasi | None = None" in stub
    for key in ("args", "env", "stdin", "stdout", "stderr", "preopens", "readonly", "clock", "random"):
        assert f"    {key}: NotRequired[" in stub  # absent is the default, None is nothing
    assert "SupportsWrite[bytes]" in stub and "SupportsRead[bytes]" in stub
    compile(stub, "m.pyi", "exec")


def test_names_that_are_not_identifiers_are_left_out_of_the_stub_with_a_comment() -> None:
    data = module(
        section(1, vec(functype([], []))),
        HEADER_FUNC,
        section(7, vec(name("a-b") + b"\x00" + leb(0), name("class") + b"\x00" + leb(0))),
        code(b"\x00\x0b"),
    )
    stub = generate(parse(data), "m").stub
    assert "def a-b" not in stub and "def class" not in stub
    assert "'a-b' is not an identifier" in stub and "'class' is not an identifier" in stub
    compile(stub, "m.pyi", "exec")


def _named(*names: str | None, extra: bytes = b"") -> bytes:
    """A module exporting `add(i32, i32) -> i32` whose "name" section names the parameters `names` (None: not named)."""
    local_map = vec(*(leb(i) + name(n) for i, n in enumerate(names) if n is not None))
    sub = vec(leb(0) + local_map)
    custom = name("name") + b"\x02" + leb(len(sub)) + sub + extra
    return module(
        section(1, vec(functype([I32, I32], [I32]))),
        HEADER_FUNC,
        section(7, vec(name("add") + b"\x00" + leb(0))),
        code(b"\x00\x20\x00\x20\x01\x6a\x0b"),
        section(0, custom),
    )


def _add_line(wasm: bytes) -> str:
    [line] = [x for x in generate(parse(wasm), "m").stub.splitlines() if x.lstrip().startswith("def add(")]
    return line.strip()


def test_the_stub_names_the_parameters_the_name_section_names() -> None:
    assert _add_line(_named("left", "right")) == "def add(self, left: int, right: int, /) -> int: ..."


@pytest.mark.parametrize(
    "names",
    [
        ("a", None),  # one is not named
        ("a", "a"),  # twice
        ("a", "class"),  # a keyword
        ("self", "b"),
        ("a", "b-c"),  # not an identifier
        ("__a", "b"),
        ("a", "ж"),  # not ASCII
    ],
)
def test_the_stub_keeps_argn_when_the_names_cannot_all_be_used(names: tuple[str | None, ...]) -> None:
    assert _add_line(_named(*names)) == "def add(self, arg0: int, arg1: int, /) -> int: ..."


def test_a_module_without_names_or_with_a_broken_name_section_is_as_before() -> None:
    plain = module(
        section(1, vec(functype([I32, I32], [I32]))),
        HEADER_FUNC,
        section(7, vec(name("add") + b"\x00" + leb(0))),
        code(b"\x00\x20\x00\x20\x01\x6a\x0b"),
    )
    assert _add_line(plain) == "def add(self, arg0: int, arg1: int, /) -> int: ..."
    broken = plain + section(0, name("name") + b"\x02\x7f")  # a subsection longer than the section
    assert parse(broken).local_names == {}
    assert _add_line(broken) == "def add(self, arg0: int, arg1: int, /) -> int: ..."


def test_param_names_are_read_per_function() -> None:
    m = parse(_named("x", None))
    assert m.param_names(0) == ("x", None)
    assert m.local_names == {0: {0: "x"}}


def test_a_module_with_tags_has_the_uncaught_exception_in_its_glue_and_in_its_stub(wabt: Path, tmp_path: Path) -> None:
    wasm = tmp_path / "ex.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "exceptions.wat", "-o", wasm], check=True)
    glue = generate(parse(wasm.read_bytes()), "ex")
    assert "class UncaughtException(Trap):" in glue.stub and "tag: int | None" in glue.stub
    assert (
        "extern const wasm_rt_tag_t wasmext_tags_ex[3];" in glue.header
    )  # the table the repair of the C of wasm2c adds
    assert "UncaughtException" in glue.source
    plain = generate(parse((DATA / "simple.wasm").read_bytes()), "simple")
    assert "UncaughtException" not in plain.stub + plain.source + plain.header  # a module without tags has none
