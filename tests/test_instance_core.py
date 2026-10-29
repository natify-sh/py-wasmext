"""Step 3a of layer 1 (docs/step3_instances.md): the instance and the binding of a module, tested as plain C (tests/c/) over a real wasm2c module.
The C of the descriptor and of the binding is made by wasmext from the model; nothing of Python is in the program that runs."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from fusedwasi import get_include

from wasmext import parse
from wasmext._binding import generate_binding
from wasmext._descriptor import generate_descriptor
from wasmext._model import build_model
from wasmext._toolchain import find_toolchain  # pyright: ignore[reportPrivateUsage]

from .c_build import compile_c, supports_flag
from .conftest import SANITIZED

HERE = Path(__file__).parent
C_DIR = HERE / "c"
WASMEXT_C = HERE.parent / "src" / "wasmext" / "c"
EXE = ".exe" if os.name == "nt" else ""

OPS = """(module
  (memory (export "mem") 1)
  (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add)
  (func (export "div") (param i32 i32) (result i32) local.get 0 local.get 1 i32.div_s)
  (func (export "swap") (param i32 i64) (result i64 i32) local.get 1 local.get 0)
  (func (export "nothing"))
  (func (export "mix") (param f32 f64) (result f64) local.get 0 f64.promote_f32 local.get 1 f64.add)
  (global $g (mut i32) (i32.const 5))
  (func (export "g") (result i32) global.get $g)
  (func $s global.get $g i32.const 1 i32.add global.set $g)
  (start $s))"""
SIMD = """(module (func (export "double") (param v128) (result v128) local.get 0 local.get 0 i32x4.add))"""
START_TRAP = """(module (func $s unreachable) (start $s) (func (export "f") (result i32) i32.const 1))"""


@pytest.fixture(scope="module")
def build(wabt: Path, tmp_path_factory: pytest.TempPathFactory) -> Callable[..., Path]:
    """Builds a C test against a module: wat -> wasm -> wasm2c -> the descriptor and the binding of wasmext -> the test and the runtime."""
    out = tmp_path_factory.mktemp("instance")
    toolchain = find_toolchain()
    runtime = toolchain.runtime
    simde = [toolchain.include] if toolchain.include is not None and (toolchain.include / "simde").is_dir() else []

    def run(wat: str, name: str, test: str, flags: Sequence[str] = ()) -> Path:
        (out / f"{name}.wat").write_text(wat, encoding="utf-8")
        wasm = out / f"{name}.wasm"
        subprocess.run([wabt / "bin" / "wat2wasm", out / f"{name}.wat", "-o", wasm], check=True)
        subprocess.run(
            [wabt / "bin" / "wasm2c", wasm, "-o", out / f"{name}_w2c.c", f"--module-name={name}"], check=True
        )
        model = build_model(parse(wasm.read_bytes()), name)
        (out / f"{name}_descriptor.c").write_text(generate_descriptor(model), encoding="utf-8")
        (out / f"{name}_binding.c").write_text(generate_binding(model), encoding="utf-8")
        exe = (
            out
            / f"{name}_{Path(test).stem}{'_' + ''.join(c for c in ''.join(flags) if c.isalnum()) if flags else ''}{EXE}"
        )
        compile_c(
            [C_DIR / test, out / f"{name}_binding.c", out / f"{name}_descriptor.c", out / f"{name}_w2c.c",
             runtime / "wasm-rt-impl.c", runtime / "wasm-rt-mem-impl.c", runtime / "wasm-rt-exceptions-impl.c"],
            exe,
            include_dirs=[WASMEXT_C, Path(get_include()), runtime, out, *simde],
            flags=flags,
            defines=[f"MODULE={name}"],
            strict=False,
            std=None,
            threads=True,
            math=True,
        )  # fmt: skip
        return exe

    return run


def _run(exe: Path) -> None:
    result = subprocess.run([str(exe)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_calls_of_an_instance(build: Callable[..., Path]) -> None:
    _run(build(OPS, "ops", "test_instance.c"))


def test_a_trap_in_the_start_function(build: Callable[..., Path]) -> None:
    _run(build(START_TRAP, "starttrap", "test_instance_start_trap.c"))


def test_the_binding_is_refused_for_a_module_with_imports(wabt: Path, tmp_path: Path) -> None:
    from wasmext._gen import GenError

    wat = tmp_path / "i.wat"
    wat.write_text('(module (import "env" "f" (func)) (func (export "g") call 0))', encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", tmp_path / "i.wasm"], check=True)
    with pytest.raises(GenError, match="step 3b"):
        generate_binding(build_model(parse((tmp_path / "i.wasm").read_bytes()), "i"))


def test_a_v128_crosses_as_16_bytes(build: Callable[..., Path]) -> None:
    _run(build(SIMD, "simd", "test_instance_v128.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ThreadSanitizer is checked on Linux")
def test_the_instance_under_threadsanitizer(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=thread"):
        pytest.skip("no ThreadSanitizer, or another sanitizer is on for the whole run")
    _run(build(OPS, "ops", "test_instance.c", flags=["-fsanitize=thread", "-g"]))
