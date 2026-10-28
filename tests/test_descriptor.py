"""Step 1 of layer 1 (docs/step1_model_descriptor.md): the model and the descriptor. The descriptor is read by a plain C program
(tests/c/dump_descriptor.c, no Python, no wasm2c output) and by the model in Python; the two texts must be the same."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from wasmext import parse
from wasmext._descriptor import generate_descriptor
from wasmext._model import build_model

HERE = Path(__file__).parent
C_DIR = HERE / "c"
WASMEXT_C = HERE.parent / "src" / "wasmext" / "c"
DATA = HERE / "data"

# Every kind and corner of the format, as small modules in the text format.
MODULES: dict[str, str] = {
    "empty": "(module)",
    "add": '(module (func (export "add") (param $a i32) (param $b i32) (result i32) local.get $a local.get $b i32.add))',
    "unnamed": '(module (func (export "f") (param i32 i64) (result f32) f32.const 0))',
    "multi_value": '(module (func (export "swap") (param i32 i64) (result i64 i32) local.get 1 local.get 0))',
    "memory": '(module (memory (export "mem") 1 4) (global (export "g") (mut i64) (i64.const 7)) (global (export "c") i32 (i32.const 1)))',
    "memory64": '(module (memory (export "m") i64 2))',
    "shared_memory": '(module (memory (export "m") 1 2 shared))',
    "table": '(module (table (export "t") 3 10 funcref) (func $f) (elem (i32.const 0) $f))',
    "externref_table": '(module (table (export "t") 2 externref))',
    "imports": """(module
      (import "env" "f" (func (param i32) (result i32)))
      (import "env" "mem" (memory 1 5))
      (import "env" "tab" (table 2 funcref))
      (import "env" "g" (global i32))
      (import "env" "mg" (global (mut f64)))
      (func (export "run") (param i32) (result i32) local.get 0 call 0))""",
    "tag": '(module (tag (export "e") (param i32 f32)))',
    "start": "(module (func $s) (start $s))",
    "simd": '(module (func (export "v") (param v128) (result v128) local.get 0))',
    "odd_names": '(module (func (export "a\\22b\\5cc \\00d%s\\e2\\82\\ac") (result i32) i32.const 1))',
    "wasi": """(module
      (import "wasi_snapshot_preview1" "proc_exit" (func (param i32)))
      (import "wasi_unstable" "fd_close" (func (param i32) (result i32)))
      (import "wasi:cli/exit@0.2.0" "exit" (func (param i32)))
      (memory (export "memory") 1)
      (func (export "_start") i32.const 0 call 0))""",
}


def _compile(sources: list[Path], exe: Path, last: str) -> None:
    """Builds the C reader with `cc`, or with the compiler of Python (MSVC on Windows), the way the other tests build."""
    cc = (
        None
        if os.name == "nt"
        else shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    )
    if cc is not None:
        extra = shlex.split(os.environ.get("WASMEXT_TEST_CFLAGS", ""))
        subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", *extra, f"-DDESCRIBE={last}_describe", f"-I{WASMEXT_C}",
             *map(str, sources), "-o", str(exe)],
            check=True,
        )  # fmt: skip
        return
    from setuptools._distutils.errors import DistutilsPlatformError  # pyright: ignore[reportMissingTypeStubs]
    from setuptools._distutils.ccompiler import new_compiler  # pyright: ignore[reportMissingTypeStubs]

    compiler = new_compiler()
    initialize = getattr(compiler, "initialize", None)  # the MSVC compiler looks for Visual Studio here
    try:
        if initialize is not None:
            initialize()
    except DistutilsPlatformError:
        pytest.skip("no C compiler")
    objects = compiler.compile(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        [str(x) for x in sources],
        output_dir=str(exe.parent / (exe.stem + "_obj")),
        include_dirs=[str(WASMEXT_C)],
        macros=[("DESCRIBE", f"{last}_describe")],
    )
    compiler.link_executable(objects, exe.stem, output_dir=str(exe.parent))  # pyright: ignore[reportUnknownMemberType]


@pytest.fixture(scope="module")
def dump_c(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str, str, str], str]:
    out = tmp_path_factory.mktemp("descriptor")

    def run(descriptor_c: str, last: str, key: str) -> str:
        src = out / f"{key}_descriptor.c"
        src.write_text(descriptor_c, encoding="utf-8")
        exe = out / (f"{key}.exe" if os.name == "nt" else key)
        _compile([C_DIR / "dump_descriptor.c", src], exe, last)
        return subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout

    return run


def _binary(wabt: Path, text: str, tmp: Path, key: str) -> bytes:
    wat = tmp / f"{key}.wat"
    wat.write_text(text, encoding="utf-8")
    wasm = tmp / f"{key}.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", "--enable-threads", "--debug-names", wat, "-o", wasm], check=True)
    return wasm.read_bytes()


@pytest.mark.parametrize("key", sorted(MODULES))
@pytest.mark.parametrize("host", ["wasm32", "wasm32-wasip1", "wasm32-wasip2"])
def test_c_and_python_read_the_same_facts(
    key: str, host: str, wabt: Path, dump_c: Callable[[str, str, str], str], tmp_path: Path
) -> None:
    module = parse(_binary(wabt, MODULES[key], tmp_path, key))
    model = build_model(module, "pkg.mod", host=host, share_tables=key == "table")
    assert dump_c(generate_descriptor(model), model.last, f"{key}_{host}") == model.dump()


def test_the_model_says_who_answers_the_imports(wabt: Path, tmp_path: Path) -> None:
    module = parse(_binary(wabt, MODULES["wasi"], tmp_path, "wasi"))
    answered = {
        h: [i.name for i in build_model(module, "m", host=h).imports if i.core]
        for h in ("wasm32", "wasm32-wasip1", "wasm32-wasip2")
    }
    assert answered == {"wasm32": [], "wasm32-wasip1": ["proc_exit", "fd_close"], "wasm32-wasip2": ["exit"]}


def test_parameter_names_are_in_the_model(wabt: Path, tmp_path: Path) -> None:
    model = build_model(parse(_binary(wabt, MODULES["add"], tmp_path, "add")), "add")
    assert model.exports[0].param_names == ("a", "b")
    assert "names " in model.dump()


def test_a_reader_refuses_another_version(dump_c: Callable[[str, str, str], str], wabt: Path, tmp_path: Path) -> None:
    model = build_model(parse(_binary(wabt, MODULES["add"], tmp_path, "add")), "add")
    source = generate_descriptor(model).replace(
        "WASMEXT_DESCRIPTOR_VERSION, sizeof", "WASMEXT_DESCRIPTOR_VERSION + 1u, sizeof"
    )
    with pytest.raises(subprocess.CalledProcessError) as raised:
        dump_c(source, model.last, "other_version")
    assert raised.value.returncode == 2
    assert "descriptor version" in raised.value.stderr
