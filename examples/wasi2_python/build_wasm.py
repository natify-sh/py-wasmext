"""Take the core module out of a CPython component built for WASI 0.2 and put it in src/wasi2python/_python.wasm.

    python build_wasm.py PYTHON.wasm        # the python.wasm of cross-build/wasm32-wasip2 (see README.md for how it is built)

Needs `wasm-tools` on the PATH (`uv tool install wasm-tools-package`) and wasmext (it is a build requirement of this project, so it is there when `uv sync` builds it; here it
reads the imports of the module). The result is about 36 MB and is not kept in the repository, nor is `src/wasi2python/_imports.py`, the imports of the module by module name:
the package reads that file at run time, so it needs no wasmext then.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from wasmext import parse

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

# the imports of the module, for run(): by module (with its version), in the order of the module
PACKAGE = Path(__file__).resolve().parent / "src" / "wasi2python"
found: dict[str, list[str]] = {}
for item in parse((PACKAGE / "_python.wasm").read_bytes()).imports:
    found.setdefault(item.module, []).append(item.name)
lines = [
    '"""The imports of _python.wasm, by module: made by build_wasm.py, do not edit."""',
    "",
    "IMPORTS: dict[str, list[str]] = {",
]
for module, names in found.items():
    lines.append(f"    {json.dumps(module)}: [")
    lines.extend(f"        {json.dumps(name)}," for name in names)
    lines.append("    ],")
lines.append("}")
(PACKAGE / "_imports.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"_imports.py: {sum(len(v) for v in found.values())} imports of {len(found)} modules")
