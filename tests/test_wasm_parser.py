"""The binary reader: the two modules of the proof of concept, and hand-assembled bytes for the corners of the format."""

from __future__ import annotations

from pathlib import Path

import pytest

from wasmext import FuncType, GlobalType, Limits, TableType, WasmError, parse

WASM_DIR = Path(__file__).resolve().parent.parent / "wasm"
HEADER = b"\0asm\x01\x00\x00\x00"

I32, I64, F32, F64, V128, FUNCREF, EXTERNREF = 0x7F, 0x7E, 0x7D, 0x7C, 0x7B, 0x70, 0x6F


def leb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def sleb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if (n == 0 and not b & 0x40) or (n == -1 and b & 0x40):
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


def vec(*items: bytes) -> bytes:
    return leb(len(items)) + b"".join(items)


def name(s: str) -> bytes:
    raw = s.encode()
    return leb(len(raw)) + raw


def section(section_id: int, payload: bytes) -> bytes:
    return bytes([section_id]) + leb(len(payload)) + payload


def functype(params: list[int], results: list[int]) -> bytes:
    return b"\x60" + vec(*(bytes([p]) for p in params)) + vec(*(bytes([r]) for r in results))


def module(*sections: bytes) -> bytes:
    return HEADER + b"".join(sections)


ADD_BODY = b"\x00\x20\x00\x20\x01\x6a\x0b"  # no locals; local.get 0; local.get 1; i32.add; end


def code(*bodies: bytes) -> bytes:
    return section(10, vec(*(leb(len(b)) + b for b in bodies)))


def test_simple_module() -> None:
    m = parse((WASM_DIR / "simple.wasm").read_bytes())
    assert m.func_exports() == [("add", FuncType(("i32", "i32"), ("i32",)))]
    assert m.imports == []


def test_coremark_module() -> None:
    m = parse((WASM_DIR / "coremark.wasm").read_bytes())
    assert [(i.module, i.name, i.type) for i in m.func_imports()] == [
        ("wiring", "millis", FuncType((), ("i32",))),
        ("wiring", "print", FuncType(("i32", "i32"), ())),
        ("wiring", "stopWdt", FuncType((), ())),
        ("wiring", "delay", FuncType(("i32",), ())),
    ]
    assert m.func_exports() == [("setup", FuncType((), ())), ("loop", FuncType((), ()))]
    assert m.memory_exports() == [("memory", Limits(1))]


def test_exported_imports_resolve_through_the_index_space() -> None:
    # (import "env" "f" (func (param i64))) re-exported as "g", and a function defined here exported as "h"
    data = module(
        section(1, vec(functype([I64], []), functype([], [F64]))),
        section(2, vec(name("env") + name("f") + b"\x00" + leb(0))),
        section(3, vec(leb(1))),
        section(7, vec(name("g") + b"\x00" + leb(0), name("h") + b"\x00" + leb(1))),
        code(b"\x00\x44" + bytes(8) + b"\x0b"),
    )
    m = parse(data)
    assert m.func_exports() == [("g", FuncType(("i64",), ())), ("h", FuncType((), ("f64",)))]
    assert len(m.all_functions) == 2 and len(m.functions) == 1


def test_leb128_of_more_than_one_byte() -> None:
    data = module(
        section(1, vec(functype([I32], [I32]))),
        section(3, vec(leb(0))),
        section(7, vec(name("a" * 200) + b"\x00" + leb(0))),  # the length of the name takes two bytes
        code(b"\x00\x20\x00\x0b"),
    )
    assert parse(data).func_exports()[0][0] == "a" * 200


def test_names_are_utf8() -> None:
    data = module(
        section(1, vec(functype([], []))),
        section(3, vec(leb(0))),
        section(7, vec(name("зв'язок") + b"\x00" + leb(0))),
        code(b"\x00\x0b"),
    )
    assert parse(data).func_exports()[0][0] == "зв'язок"


def test_invalid_utf8_name() -> None:
    data = module(
        section(1, vec(functype([], []))),
        section(3, vec(leb(0))),
        section(7, vec(leb(1) + b"\xff" + b"\x00" + leb(0))),
        code(b"\x00\x0b"),
    )
    with pytest.raises(WasmError, match="UTF-8"):
        parse(data)


def test_memory_table_and_global_types() -> None:
    data = module(
        section(
            4,
            vec(
                bytes([FUNCREF]) + b"\x01" + leb(2) + leb(10),
                b"\x40\x00" + bytes([EXTERNREF]) + b"\x00" + leb(1) + b"\xd0" + bytes([EXTERNREF]) + b"\x0b",
            ),
        ),
        section(5, vec(b"\x00" + leb(1), b"\x03" + leb(1) + leb(4), b"\x04" + leb(1 << 40))),
        section(
            6,
            vec(
                bytes([I32, 0]) + b"\x41" + sleb(-1) + b"\x0b",
                bytes([I64, 1]) + b"\x42" + sleb(-(1 << 40)) + b"\x0b",
                bytes([F32, 0]) + b"\x43" + bytes(4) + b"\x0b",
                bytes([V128, 0]) + b"\xfd\x0c" + bytes(16) + b"\x0b",
                bytes([I32, 0]) + b"\x41\x01\x41\x02\x6a\x0b",  # extended-const: i32.const 1, i32.const 2, i32.add
                bytes([EXTERNREF, 0]) + b"\xd0" + bytes([EXTERNREF]) + b"\x0b",
            ),
        ),
        section(
            7,
            vec(
                name("t") + b"\x01" + leb(0),
                name("m") + b"\x02" + leb(1),
                name("g") + b"\x03" + leb(1),
            ),
        ),
    )
    m = parse(data)
    assert m.tables == [TableType("funcref", Limits(2, 10)), TableType("externref", Limits(1))]
    assert m.memories == [Limits(1), Limits(1, 4, shared=True), Limits(1 << 40, is64=True)]
    assert m.globals[:2] == [GlobalType("i32", False), GlobalType("i64", True)]
    assert m.memory_exports() == [("m", Limits(1, 4, shared=True))]
    assert m.global_exports() == [("g", GlobalType("i64", True))]
    assert m.table_exports() == [("t", TableType("funcref", Limits(2, 10)))]
    assert m.globals[2:] == [
        GlobalType("f32", False),
        GlobalType("v128", False),
        GlobalType("i32", False),
        GlobalType("externref", False),
    ]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "magic"),
        (b"\x7fELF\x01\x00\x00\x00", "magic"),
        (b"\0asm\x02\x00\x00\x00", "version"),
        (HEADER + b"\x01", "unexpected end"),  # a section id and no size
        (HEADER + b"\x01\x05\x00", "bytes wanted"),  # a section larger than the data
        (HEADER + section(99, b""), "unknown section"),
        (HEADER + section(7, vec()) + section(1, vec()), "out of order"),
        (HEADER + section(1, vec()) + section(1, vec()), "out of order"),
        (HEADER + section(1, vec(b"\x61")), "type form"),
        (HEADER + section(1, vec(functype([0x40], []))), "value type"),
        (HEADER + section(1, vec(functype([0x63], []))), "value type"),  # a GC reference
        (HEADER + section(1, vec(functype([], [])) + b"\x00"), "unread"),
        (HEADER + section(1, leb(1000)), "vector"),  # a count that cannot be true
        (HEADER + section(3, vec(leb(0))), "type index"),
        (HEADER + section(1, vec(functype([], []))) + section(3, vec(leb(0))), "bodies"),  # no code section
        (HEADER + section(1, vec(functype([], []))) + code(b"\x00\x0b"), "bodies"),  # code for nothing
        (HEADER + section(5, vec(b"\x08" + leb(1))), "flags"),
        (HEADER + section(5, vec(b"\x00" + b"\xff\xff\xff\xff\x7f")), "32 bits"),
        (HEADER + section(7, vec(name("f") + b"\x00" + leb(0))), "out of range"),
        (HEADER + section(7, vec(name("f") + b"\x07" + leb(0))), "export kind"),
        (HEADER + section(8, leb(0)), "start"),
        (HEADER + section(6, vec(bytes([I32, 0]) + b"\x01")), "constant expression"),
        (HEADER + section(6, vec(bytes([I32, 2]) + b"\x41\x00\x0b")), "mutability"),
        (HEADER + b"\x00\x01", "bytes wanted"),  # a custom section without a name
    ],
)
def test_malformed_modules_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(WasmError, match=message):
        parse(data)


def test_custom_sections_and_unread_sections_are_skipped() -> None:
    data = module(
        section(0, name("producers") + b"anything"),
        section(1, vec(functype([], []))),
        section(3, vec(leb(0))),
        section(5, vec(b"\x00" + leb(1))),
        section(12, leb(1)),  # data count
        code(b"\x00\x0b"),
        section(11, vec(b"\x00\x41\x00\x0b" + vec(b"\x01"))),  # a data segment
        section(0, name("name") + b"\x00"),
    )
    m = parse(data)
    assert len(m.functions) == 1 and m.memories == [Limits(1)]


def test_a_module_assembled_by_wabt() -> None:
    """tests/data/kitchen_sink.wat through `wat2wasm` (WABT 1.0.42); the indices agree with `wasm-objdump -x`."""
    m = parse((Path(__file__).parent / "data" / "kitchen_sink.wasm").read_bytes())
    assert m.func_exports() == [
        ("f", FuncType(("f32", "f64"), ("i32", "i64"))),
        ("v", FuncType(("v128",), ("v128",))),
        ("log2", FuncType(("i32", "i64"), ())),  # an imported function exported again
    ]
    assert [(i.kind, i.module, i.name) for i in m.imports] == [
        ("func", "env", "log"),
        ("memory", "env", "mem"),
        ("global", "env", "g"),
    ]
    assert m.memory_exports() == [("mem2", Limits(1, 4))]  # the memory is the imported one
    assert m.global_exports() == [("k", GlobalType("f64", False))]
    assert m.table_exports() == [("tbl", TableType("funcref", Limits(3)))]
    assert m.start == 3
