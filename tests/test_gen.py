"""The generator on its own (no compiler): names, skipped exports, what it refuses."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wasmext import GenError, generate, mangle, parse

from .test_wasm_parser import F64, I32, V128, code, functype, leb, module, name, section, vec

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


def test_a_v128_export_is_skipped_but_an_import_of_one_is_refused() -> None:
    skipped = module(
        section(1, vec(functype([V128], [V128]))),
        HEADER_FUNC,
        section(7, vec(name("vec") + b"\x00" + leb(0))),
        code(b"\x00\x20\x00\x0b"),
    )
    glue = generate(parse(skipped), "m")
    assert glue.skipped == ["function 'vec' uses v128"]
    assert "Instance_f" not in glue.source.replace("Instance_free", "")

    refused = module(
        section(1, vec(functype([V128], []))),
        section(2, vec(name("env") + name("f") + b"\x00" + leb(0))),
    )
    with pytest.raises(GenError, match=r"env\.f uses v128"):
        generate(parse(refused), "m")


def test_imported_memories_are_refused() -> None:
    data = module(section(2, vec(name("env") + name("mem") + b"\x02\x00" + leb(1))))
    with pytest.raises(GenError, match="imported memory"):
        generate(parse(data), "m")


def test_the_module_name_must_be_an_identifier() -> None:
    data = module(section(1, vec(functype([I32], [F64]))), HEADER_FUNC, code(b"\x00\x44" + bytes(8) + b"\x0b"))
    generate(parse(data), "pkg.sub.good")
    for bad in ("bad-name", "1abc", "pkg.", ""):
        with pytest.raises(GenError):
            generate(parse(data), bad)


def test_the_dotted_name_is_the_type_name_and_the_last_part_the_init_function() -> None:
    data = module(section(1, vec(functype([], []))), HEADER_FUNC, code(b"\x00\x0b"))
    source = generate(parse(data), "pkg.sub.fast").source
    assert "PyMODINIT_FUNC PyInit_fast(void)" in source
    assert '"pkg.sub.fast.Instance"' in source
    assert '#include "fast_w2c.h"' in source
