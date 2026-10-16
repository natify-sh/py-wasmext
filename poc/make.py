"""Build the wasm2c proof of concept: .wasm -> C (wasm2c) -> a CPython extension module.

    python poc/make.py [simple|coremark ...]        (default: both)

Needs a C compiler (CC, default `cc`), the Python headers, and WABT 1.0.x:
  WASM2C     the wasm2c executable (default: `wasm2c` on PATH)
  WABT_SRC   the directory with wasm2c's runtime sources (wasm-rt.h, wasm-rt-impl.c, wasm-rt-mem-impl.c, ...),
             i.e. `<wabt checkout>/wasm2c` or `<wabt release>/share/wabt/wasm2c` plus `<release>/include`
Linux only for now (see README).
"""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "out"
MODULES = ("simple", "coremark")


def run(cmd: list[str]) -> None:
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def build(name: str) -> Path:
    if not sys.platform.startswith("linux"):
        raise SystemExit("only Linux is done so far: the link flags of macOS and the compiler of Windows are not written")
    wabt_src = os.environ.get("WABT_SRC")
    if not wabt_src or not (Path(wabt_src) / "wasm-rt-impl.c").is_file():
        raise SystemExit("set WABT_SRC to the directory holding wasm-rt.h and wasm-rt-impl.c (wabt/wasm2c)")
    BUILD.mkdir(exist_ok=True)
    c_file = BUILD / f"{name}.c"
    run([os.environ.get("WASM2C", "wasm2c"), "-o", str(c_file), f"--module-name={name}", str(HERE / "wasm" / f"{name}.wasm")])
    out = BUILD / f"{name}_ext{sysconfig.get_config_var('EXT_SUFFIX')}"
    run(
        [
            os.environ.get("CC", "cc"), "-O2", "-shared", "-fPIC",
            f"-I{wabt_src}", f"-I{BUILD}", f"-I{sysconfig.get_paths()['include']}",
            str(HERE / "glue" / f"{name}.c"), str(c_file),
            str(Path(wabt_src) / "wasm-rt-impl.c"), str(Path(wabt_src) / "wasm-rt-mem-impl.c"),
            "-o", str(out),
        ]
    )  # fmt: skip
    return out


if __name__ == "__main__":
    names = sys.argv[1:] or list(MODULES)
    for n in names:
        if n not in MODULES:
            raise SystemExit(f"unknown module {n!r}; one of {MODULES}")
        print("built", build(n))
