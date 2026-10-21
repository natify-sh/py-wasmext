"""A directory that `wasmext` takes for WABT (WASMEXT_WABT=DIR): `bin/wasm2c`, `wasm2c/` (the runtime of the C that it writes) and the
version, made of this package. `bin/wasm2c` is a script that runs `_wasm2c.wasm`, built into the extension `wabtwasm._wasm2c` by wasmext:
the translator of the next extension is an extension that wasmext built.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

RUNTIME = Path(__file__).parent / "runtime"


def make_toolchain(directory: str | os.PathLike[str]) -> Path:
    """Write the directory (POSIX: the program of `bin/wasm2c` is a shell script) and give its path."""
    if os.name == "nt":
        raise OSError("bin/wasm2c has to be a program that wasmext can run: a shell script, so not on Windows")
    root = Path(directory).resolve()
    (root / "bin").mkdir(parents=True, exist_ok=True)
    runtime = root / "wasm2c"
    runtime.mkdir(exist_ok=True)
    for file in RUNTIME.iterdir():
        if file.name != "WABT_VERSION":
            shutil.copyfile(file, runtime / file.name)
    version = (RUNTIME / "WABT_VERSION").read_text(encoding="utf-8").strip()
    (root / "_wabt_version.txt").write_text(f"{version}-wabtwasm\n", encoding="utf-8")
    script = root / "bin" / "wasm2c"
    script.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -m wabtwasm wasm2c "$@"\n', encoding="utf-8")
    script.chmod(0o755)
    return root
