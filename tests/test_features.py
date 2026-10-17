"""Which WebAssembly features a module can use: one small module for each, through the whole path (`wat2wasm`, then
`wasmext -i`, then import and call). The cases marked `xfail` are the known gaps: they are strict, so that the day
one is closed the test says so and the mark goes."""

from __future__ import annotations

import platform
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


def test_an_exception_nobody_catches_is_a_trap(tmp_path: Path, wabt: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "m.wat").write_text(
        '(module (tag $e (param i32)) (func (export "boom") i32.const 1 throw $e)'
        ' (func (export "ok") (result i32) try (result i32) i32.const 7 throw $e catch $e end))',
        encoding="utf-8",
    )
    subprocess.run([wabt / "bin" / "wat2wasm", "m.wat", "-o", "m.wasm"], cwd=package, check=True)
    built = wasmext(tmp_path, wabt, "-i", "-q", "pkg/m.wasm")
    assert built.returncode == 0, built.stderr[-600:]
    code = (
        "import pkg.m\n"
        "instance = pkg.m.Instance()\n"
        "print(instance.ok())\n"  # the payload of the exception is what the handler gets: 7
        "try:\n"
        "    instance.boom()\n"
        "except pkg.m.Trap as exc:\n"
        "    print('trap:', exc)\n"
        "print(instance.ok())\n"  # and the instance is still usable
    )
    ran = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr[-400:]
    lines = ran.stdout.split("\n")
    assert lines[0] == "7" and lines[1].startswith("trap:") and lines[2] == "7"


def test_an_imported_function_returns_several_results_as_a_tuple(tmp_path: Path, wabt: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "m.wat").write_text(
        '(module (import "env" "pair" (func $pair (param i32) (result i32 f64 i64)))'
        ' (func (export "f") (param i32) (result i32 f64 i64) local.get 0 call $pair))',
        encoding="utf-8",
    )
    subprocess.run([wabt / "bin" / "wat2wasm", "m.wat", "-o", "m.wasm"], cwd=package, check=True)
    built = wasmext(tmp_path, wabt, "-i", "-q", "pkg/m.wasm")
    assert built.returncode == 0, built.stderr[-600:]
    code = """
import pkg.m
i = pkg.m.Instance({'env': {'pair': lambda n: (n + 1, 2.5, -3)}})
print(i.f(4))
for bad in (lambda n: (1, 2), lambda n: 7, lambda n: (1, 'x', 3)):
    try:
        pkg.m.Instance({'env': {'pair': bad}}).f(1)
    except TypeError:
        print('TypeError')
print(i.f(5))
"""
    ran = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr[-500:]
    assert ran.stdout.splitlines() == ["(5, 2.5, -3)", "TypeError", "TypeError", "TypeError", "(6, 2.5, -3)"]


def test_an_exported_memory64_is_a_memoryview_too(tmp_path: Path, wabt: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "m.wat").write_text(
        '(module (memory (export "mem") i64 1 4) (data (i64.const 0) "hi")'
        ' (func (export "peek") (param i64) (result i32) local.get 0 i32.load8_u)'
        ' (func (export "grow") (param i64) (result i64) local.get 0 memory.grow))',
        encoding="utf-8",
    )
    subprocess.run([wabt / "bin" / "wat2wasm", "m.wat", "-o", "m.wasm"], cwd=package, check=True)
    built = wasmext(tmp_path, wabt, "-i", "-q", "pkg/m.wasm")
    assert built.returncode == 0, built.stderr[-600:]
    code = """
import pkg.m
i = pkg.m.Instance()
print(bytes(i.mem[:2]), len(i.mem))
i.mem[5] = 42
print(i.peek(5))
print(i.grow(1), len(i.mem))
"""
    ran = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr[-500:]
    assert ran.stdout.splitlines() == ["b'hi' 65536", "42", "1 131072"]


def _build_pkg(tmp_path: Path, wabt: Path, wat: str) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "m.wat").write_text(wat, encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", "m.wat", "-o", "m.wasm"], cwd=package, check=True)
    built = wasmext(tmp_path, wabt, "-i", "-q", "pkg/m.wasm")
    assert built.returncode == 0, built.stderr[-600:]


# The memory is reserved, not touched: the test needs address space (Linux overcommits), not 4 GiB of RAM.
@pytest.mark.skipif(platform.system() != "Linux", reason="allocates a memory of more than 4 GiB")
def test_memory64_addresses_above_4_gib(tmp_path: Path, wabt: Path) -> None:
    _build_pkg(
        tmp_path,
        wabt,
        '(module (memory (export "mem") i64 65538 65600)'
        ' (func (export "put") (param i64 i32) local.get 0 local.get 1 i32.store)'
        ' (func (export "get") (param i64) (result i32) local.get 0 i32.load))',
    )
    code = """
import pkg.m
i = pkg.m.Instance()
a = 2**32 + 12
i.put(a, 0x12345678)
print(len(i.mem), i.get(a), bytes(i.mem[a:a + 4]).hex())
i.mem[a:a + 4] = bytes.fromhex('efbeadde')
print(i.get(a))
"""
    ran = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr[-500:]
    assert ran.stdout.splitlines() == [f"{65538 * 65536} 305419896 78563412", "-559038737"]  # 0xDEADBEEF as an i32


@pytest.mark.skipif(platform.system() != "Linux", reason="the memory of 64 TiB is refused by Linux")
@pytest.mark.xfail(
    strict=True,
    reason="wasm_rt_allocate_memory of wasm2c calls abort() when the initial memory cannot be allocated",
)
def test_a_memory_that_cannot_be_allocated_is_a_memory_error(tmp_path: Path, wabt: Path) -> None:
    _build_pkg(
        tmp_path, wabt, '(module (memory (export "mem") i64 1073741824) (func (export "f") (result i32) i32.const 1))'
    )
    code = """
import pkg.m
try:
    pkg.m.Instance()
except MemoryError:
    print('MemoryError')
"""
    ran = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ran.returncode == 0 and ran.stdout.strip() == "MemoryError"  # now the process dies with SIGABRT


def _limited_run(tmp_path: Path, code: str, limit_mib: int) -> subprocess.CompletedProcess[str]:
    import resource

    def limit() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (limit_mib << 20, limit_mib << 20))

    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        preexec_fn=limit,
    )


@pytest.mark.skipif(platform.system() != "Linux", reason="RLIMIT_AS and the 8 GiB reservation of the runtime")
@pytest.mark.parametrize("guard_pages", [True, False], ids=["guard pages", "no guard pages"])
def test_a_limit_on_address_space(guard_pages: bool, tmp_path: Path, wabt: Path) -> None:
    """With guard pages each memory reserves 8 GiB of address space, so a process limited to 2 GiB dies in abort();
    without them the module gets the 64 KiB it asks for."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "m.wat").write_text(
        '(module (memory (export "mem") 1) (func (export "f") (result i32) i32.const 7))', encoding="utf-8"
    )
    subprocess.run([wabt / "bin" / "wat2wasm", "m.wat", "-o", "m.wasm"], cwd=package, check=True)
    built = wasmext(tmp_path, wabt, "-i", "-q", "--guard-pages" if guard_pages else "--no-guard-pages", "pkg/m.wasm")
    assert built.returncode == 0, built.stderr[-600:]
    ran = _limited_run(tmp_path, "import pkg.m; i = pkg.m.Instance(); print(i.f(), len(i.mem))", 2048)
    if guard_pages:
        assert ran.returncode != 0 and "os_mmap failed" in ran.stderr  # the runtime aborts
    else:
        assert ran.returncode == 0, ran.stderr[-300:]
        assert ran.stdout.split() == ["7", "65536"]


def test_exported_globals_are_attributes(tmp_path: Path, wabt: Path) -> None:
    _build_pkg(
        tmp_path,
        wabt,
        '(module (global (export "mi") (mut i32) (i32.const 1)) (global (export "ci") i32 (i32.const 2))'
        ' (global (export "mj") (mut i64) (i64.const 3)) (global (export "mf") (mut f32) (f32.const 1.5))'
        ' (global (export "cd") f64 (f64.const 2.5))'
        ' (func (export "read") (result i32) global.get 0) (func (export "bump") global.get 0 i32.const 1 i32.add global.set 0))',
    )
    code = """
import pkg.m
i = pkg.m.Instance()
print(i.mi, i.ci, i.mj, i.mf, i.cd)
i.mi = 40
i.bump()
print(i.mi, i.read())            # what Python writes the module reads, and the other way round
i.mi = 2**32 + 5; print(i.mi)    # taken modulo 2**32, as an argument
i.mi = 0xFFFFFFFF; print(i.mi)   # and signed when read
i.mj = -(2**63); print(i.mj)
i.mf = 0.1; print(i.mf)          # an f32 keeps what an f32 keeps
for what in ('i.ci = 1', 'i.cd = 1.0', 'del i.mi', "i.mi = 'x'", 'i.mf = None'):
    try:
        exec(what)
    except (AttributeError, TypeError) as exc:
        print(type(exc).__name__)
print(i.mi, pkg.m.Instance().mi)  # a failed set changed nothing; instances do not share globals
"""
    ran = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr[-500:]
    assert ran.stdout.splitlines() == [
        "1 2 3 1.5 2.5",
        "41 41",
        "5",
        "-1",
        str(-(2**63)),
        "0.10000000149011612",
        "AttributeError",
        "AttributeError",
        "AttributeError",
        "TypeError",
        "TypeError",
        "-1 1",
    ]


def test_an_imported_immutable_global_is_a_number(tmp_path: Path, wabt: Path) -> None:
    _build_pkg(
        tmp_path,
        wabt,
        '(module (import "env" "limit" (global i32)) (import "env2" "scale" (global f64)) (import "env" "big" (global i64))'
        ' (func (export "limit") (result i32) global.get 0) (func (export "scale") (result f64) global.get 1)'
        ' (func (export "big") (result i64) global.get 2))',
    )
    code = """
import pkg.m
imports = {'env': {'limit': 100, 'big': -2**40}, 'env2': {'scale': 2.5}}
i = pkg.m.Instance(imports)
print(i.limit(), i.scale(), i.big())
imports['env']['limit'] = 7          # the value was taken when the instance was made
print(i.limit(), pkg.m.Instance(imports).limit())
print(pkg.m.Instance({'env': {'limit': 2**32 + 3, 'big': 1}, 'env2': {'scale': 1}}).limit())  # wraps, an int is a number
for bad in ({'env2': {'scale': 1}, 'env': {'big': 1}},                      # missing
            {'env': {'limit': 'x', 'big': 1}, 'env2': {'scale': 1}},        # not a number
            {'env': {'limit': 1.5, 'big': 1}, 'env2': {'scale': 1}},        # a float for an i32
            {'env': {'limit': 1, 'big': 1}, 'env2': {'scale': print}}):     # a function for a global
    try:
        pkg.m.Instance(bad)
    except pkg.m.LinkError as exc:
        print('LinkError')
"""
    ran = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr[-500:]
    assert ran.stdout.splitlines() == [
        "100 2.5 -1099511627776",
        "100 7",
        "3",
        "LinkError",
        "LinkError",
        "LinkError",
        "LinkError",
    ]


def test_an_imported_mutable_global_is_refused_when_the_extension_is_made(tmp_path: Path, wabt: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "m.wat").write_text(
        '(module (import "env" "counter" (global (mut i32))) (func (export "f") global.get 0 drop))', encoding="utf-8"
    )
    subprocess.run([wabt / "bin" / "wat2wasm", "m.wat", "-o", "m.wasm"], cwd=package, check=True)
    built = wasmext(tmp_path, wabt, "-i", "-q", "pkg/m.wasm")
    assert built.returncode == 1
    assert "an imported mutable global is not supported yet" in built.stderr
