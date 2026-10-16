"""Where `wasm2c` and its runtime sources are: the wabt-package, or the directory in WASMEXT_WABT."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Toolchain", "find_toolchain"]


@dataclass(frozen=True, slots=True)
class Toolchain:
    wasm2c: Path
    runtime: Path  # wasm-rt.h, wasm-rt-impl.c, ... of the version of `wasm2c`
    version: str


def find_toolchain() -> Toolchain:
    """WASMEXT_WABT (a directory with `bin/` and `wasm2c/`, like the one inside the wabt-package) first, then the
    installed wabt-package. Raises RuntimeError with what to do if neither is there."""
    env = os.environ.get("WASMEXT_WABT")
    if env:
        root = Path(env)
        suffix = ".exe" if os.name == "nt" else ""
        exe = root / "bin" / ("wasm2c" + suffix)
        runtime = root / "wasm2c"
        if not exe.is_file() or not (runtime / "wasm-rt.h").is_file():
            raise RuntimeError(f"WASMEXT_WABT={env}: expected bin/wasm2c and wasm2c/wasm-rt.h in it")
        version = root / "_wabt_version.txt"
        return Toolchain(exe, runtime, version.read_text(encoding="utf-8").strip() if version.is_file() else "unknown")
    try:
        wabt = importlib.import_module("wabt_package")
    except ImportError:
        raise RuntimeError(
            "wasm2c is not available: install the wabt-package (`pip install wabt-package`; "
            "put it in build-system.requires), or point WASMEXT_WABT at a directory with bin/ and wasm2c/"
        ) from None
    return Toolchain(wabt.get_executable("wasm2c"), wabt.runtime_dir(), wabt.wabt_version())
