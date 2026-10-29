"""The guard of a duplicate (docs/layers.md, "the register of duplicates"): which function of fusedwasi answers a WASI 0.1 import is decided in the model and, until the
extension step replaces it, in `_gen.py`. For every function of both snapshots, the glue that `_gen` makes must call the function the model names."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wasmext import generate, parse
from wasmext._gen import _WASI_SIGNATURES  # pyright: ignore[reportPrivateUsage]
from wasmext._model import build_model

_TYPES = {"i": "i32", "j": "i64", "f": "f32", "d": "f64"}


def _wat(module: str, signatures: dict[str, str]) -> str:
    lines = ["(module"]
    for name, code in signatures.items():
        params, results = code.split(">")
        lines.append(
            f'  (import "{module}" "{name}" (func (param {" ".join(_TYPES[c] for c in params)}) (result {" ".join(_TYPES[c] for c in results)})))'.replace(
                "(param )", ""
            ).replace("(result )", "")
        )
    lines.append('  (memory (export "memory") 1))')
    return "\n".join(lines)


@pytest.mark.parametrize("module", sorted(_WASI_SIGNATURES))
def test_gen_and_the_model_name_the_same_function(wabt: Path, tmp_path: Path, module: str) -> None:
    (tmp_path / "m.wat").write_text(_wat(module, _WASI_SIGNATURES[module]), encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", tmp_path / "m.wat", "-o", tmp_path / "m.wasm"], check=True)
    parsed = parse((tmp_path / "m.wasm").read_bytes())
    glue = generate(parsed, "m", host="wasm32-wasip1").header
    model = build_model(parsed, "m", host="wasm32-wasip1")
    assert len(model.imports) == len(_WASI_SIGNATURES[module])
    for imp in model.imports:
        assert imp.core and imp.core_call is not None
        assert f"{imp.core_call}(&self->guest" in glue, f"{imp.module}.{imp.name}: the model says {imp.core_call}"
