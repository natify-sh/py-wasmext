"""The programs of the test suite as native executables (wasmext._exe: the C of the module, the glue and the core of WASI, no Python), made
before the runner runs them, one process for each (a compiler of Windows changes the environment of the process it is started from).

    python exe_build.py --build /path/to/program.wasm     # makes it, prints the path of the executable
    python exe_build.py --path /path/to/program.wasm      # prints the path where it is (or would be)
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path


def cache() -> Path:
    return Path(os.environ.get("WASMEXT_TESTSUITE_CACHE", Path(tempfile.gettempdir()) / "wasmext-testsuite")) / "exe"


def digest(program: Path) -> str:
    return hashlib.sha256(program.read_bytes()).hexdigest()[:16]


def exe_path(program: Path) -> Path:
    return cache() / digest(program) / ("program.exe" if os.name == "nt" else "program")


def build(program: Path) -> Path:
    from wasmext._exe import build as build_exe

    where = exe_path(program)
    if not where.is_file():
        build_exe(
            program, where, name=f"t_{digest(program)}", work=where.parent / "c", optimize=False, host="wasm32-wasip1"
        )
    return where


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("--build", "--path"):
        target = Path(sys.argv[2])
        print(build(target) if sys.argv[1] == "--build" else exe_path(target))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
