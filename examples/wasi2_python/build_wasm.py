"""Take the core module out of a CPython component built for WASI 0.2 and put it in src/wasi2python/_python.wasm.

    python build_wasm.py PYTHON.wasm        # the python.wasm of cross-build/wasm32-wasip2 (see README.md for how it is built)

Needs `wasm-tools` on the PATH (`uv tool install wasm-tools-package`). The result is about 36 MB and is not kept in the repository.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if shutil.which("wasm-tools") is None:
    raise SystemExit("wasm-tools is not on the PATH (uv tool install wasm-tools-package)")
with tempfile.TemporaryDirectory() as tmp:
    subprocess.run(
        [
            "wasm-tools",
            "component",
            "unbundle",
            sys.argv[1],
            "--threshold",
            "0",
            "--module-dir",
            tmp,
            "-o",
            f"{tmp}/rest.wasm",
        ],
        check=True,
    )  # --threshold 0: the default leaves small modules inside rest.wasm
    shutil.copyfile(
        f"{tmp}/unbundled-module0.wasm", Path(__file__).resolve().parent / "src" / "wasi2python" / "_python.wasm"
    )
