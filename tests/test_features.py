"""Which WebAssembly features a module can use: one small module for each, through the whole path (`wat2wasm`, then
`wasmext -i`, then import and call). The cases marked `xfail` are the known gaps: they are strict, so that the day
one is closed the test says so and the mark goes."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from .test_cli import wasmext


@dataclass(frozen=True)
class Case:
    name: str
    wat: str
    call: str = "f"
    args: tuple[float, ...] = ()
    expect: object = None
    gap: str | None = None  # why it does not work yet


CASES = [
    # WebAssembly 1.0 (the MVP)
    Case(
        "1.0 mvp",
        '(module (func (export "f") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add))',
        args=(2, 3),
        expect=5,
    ),
    # 2.0: sign extension, saturating float-to-int, multi-value, bulk memory, reference types, SIMD, mutable globals
    Case(
        "2.0 sign-extension",
        '(module (func (export "f") (param i32) (result i32) local.get 0 i32.extend8_s))',
        args=(0xFF,),
        expect=-1,  # an i32 comes back signed, as the JavaScript API, wasmtime and wasm3 give it
    ),
    Case(
        "2.0 saturating float-to-int",
        '(module (func (export "f") (param f32) (result i32) local.get 0 i32.trunc_sat_f32_s))',
        args=(1e20,),
        expect=2147483647,
    ),
    Case(
        "2.0 multi-value, inside the module",
        '(module (func $p (result i32 i32) i32.const 3 i32.const 4) (func (export "f") (result i32) call $p i32.add))',
        expect=7,
    ),
    Case(
        "2.0 multi-value, an exported function",
        '(module (func (export "f") (result i32 i32) i32.const 3 i32.const 4))',
        expect=(3, 4),
    ),
    Case(
        "2.0 multi-value, all number types and a parameter",
        '(module (func (export "f") (param i32) (result f64 i32 i64 f32)'
        " f64.const 1.5 local.get 0 i64.const -2 f32.const 0.5))",
        args=(-7,),
        expect=(1.5, -7, -2, 0.5),
    ),
    Case(
        "2.0 bulk memory",
        '(module (memory 1) (data (i32.const 0) "\\07")'
        ' (func (export "f") (result i32) i32.const 8 i32.const 0 i32.const 1 memory.copy i32.const 8 i32.load8_u))',
        expect=7,
    ),
    Case(
        "2.0 reference types, inside the module",
        "(module (table $t 2 funcref) (func $g (result i32) i32.const 9) (elem (i32.const 0) $g)"
        ' (func (export "f") (result i32) i32.const 0 table.get $t ref.is_null))',
        expect=0,
    ),
    Case(
        "2.0 mutable global",
        '(module (global (export "g") (mut i32) (i32.const 1)) (func (export "f") (result i32) global.get 0))',
        expect=1,
    ),
    Case(
        "2.0 SIMD, inside the module",
        '(module (func (export "f") (result i32)'
        " v128.const i32x4 1 2 3 4 v128.const i32x4 1 1 1 1 i32x4.add i32x4.extract_lane 3))",
        expect=5,
        gap="the C of wasm2c includes simde, which nothing provides yet",
    ),
    # 3.0: tail calls, extended constants, memory64, multi-memory, exceptions, relaxed SIMD
    Case(
        "3.0 tail calls",
        "(module (func $a (param i32) (result i32) local.get 0)"
        ' (func (export "f") (param i32) (result i32) local.get 0 return_call $a))',
        args=(5,),
        expect=5,
    ),
    Case(
        "3.0 extended constants",
        '(module (global i32 (i32.add (i32.const 1) (i32.const 2))) (func (export "f") (result i32) global.get 0))',
        expect=3,
    ),
    Case(
        "3.0 memory64",
        '(module (memory i64 1) (func (export "f") (result i32) i64.const 0 i32.load))',
        expect=0,
    ),
    Case(
        "3.0 multi-memory",
        '(module (memory $a 1) (memory $b 1) (func (export "f") (result i32) i32.const 0 i32.load $b))',
        expect=0,
    ),
    Case(
        "3.0 exceptions",
        '(module (tag $e) (func (export "f") (result i32) try (result i32) throw $e catch $e i32.const 1 end))',
        expect=1,
        gap="the module builds but does not load: wasm-rt-exceptions-impl.c is not compiled in",
    ),
    Case(
        "3.0 relaxed SIMD, inside the module",
        '(module (func (export "f") (result i32)'
        " v128.const f32x4 1 2 3 4 i32x4.relaxed_trunc_f32x4_s i32x4.extract_lane 0))",
        expect=1,
        gap="the C of wasm2c includes simde, which nothing provides yet",
    ),
    # not 1.0, 2.0 or 3.0 proper
    Case(
        "threads",
        '(module (memory 1 1 shared) (func (export "f") (result i32) i32.const 0 i32.const 5 i32.atomic.rmw.add))',
        expect=0,
        gap="wasm2c is run without the threads feature",
    ),
]


def _params() -> list[object]:
    return [
        pytest.param(c, id=c.name, marks=pytest.mark.xfail(reason=c.gap, strict=True) if c.gap else ()) for c in CASES
    ]


@pytest.mark.parametrize("case", _params())
def test_feature(case: Case, tmp_path: Path, wabt: Path) -> None:
    assert isinstance(case, Case)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "m.wat").write_text(case.wat, encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", "m.wat", "-o", "m.wasm"], cwd=package, check=True)

    built = wasmext(tmp_path, wabt, "-i", "-q", "pkg/m.wasm")
    assert built.returncode == 0, built.stderr[-600:]

    code = f"import pkg.m\ninstance = pkg.m.Instance()\nprint(repr(instance.{case.call}(*{case.args!r})))\n"
    ran = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr[-400:]
    assert ran.stdout.strip() == repr(case.expect)
