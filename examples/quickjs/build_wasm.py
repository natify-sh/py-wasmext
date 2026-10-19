"""Build src/qjswasm/_qjs.wasm, the `qjs` command of QuickJS-ng, with `zig cc` (the `ziglang` package) as wasm32-wasi.

    uv run --group wasm python examples/quickjs/build_wasm.py                  # clones https://github.com/quickjs-ng/quickjs
    uv run --group wasm python examples/quickjs/build_wasm.py --quickjs DIR    # a checkout you already have

The sources are those of the tag below, as they are; the flags are those of the WASI build of its CMakeLists.txt (the process clocks and
the signals of wasi-libc are emulated, the stack is 2 MiB). The module is a command (`_start`) that needs `wasi_snapshot_preview1`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "src" / "qjswasm" / "_qjs.wasm"
REPO = "https://github.com/quickjs-ng/quickjs"
TAG = "v0.17.0"
SOURCES = ("dtoa.c", "libregexp.c", "libunicode.c", "quickjs.c", "quickjs-libc.c", "qjs.c", "gen/repl.c")
DEFINES = ("QJS_BUILD_LIBC", "_GNU_SOURCE", "_WASI_EMULATED_PROCESS_CLOCKS", "_WASI_EMULATED_SIGNAL")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quickjs", type=Path, help=f"a checkout of {REPO} at {TAG} (default: a fresh clone)")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        src = args.quickjs
        if src is None:
            src = Path(tmp) / "quickjs"
            subprocess.run(["git", "clone", "--depth", "1", "--branch", TAG, REPO, str(src)], check=True)
        command = [
            sys.executable, "-m", "ziglang", "cc", "-target", "wasm32-wasi", "-O2", "-s",
            *[f"-D{define}" for define in DEFINES],
            "-Wl,-z,stack-size=2097152",
            *SOURCES,
            "-lwasi-emulated-process-clocks", "-lwasi-emulated-signal",
            "-o", str(OUT),
        ]  # fmt: skip
        subprocess.run(command, cwd=src, check=True)
    print(f"{OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
