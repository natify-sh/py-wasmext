"""Make the directory that the program sees as /py: the standard library of a CPython checkout built for WASI, and wasi_pip.

    python tools/make_stdlib.py CHECKOUT OUT_DIR [wasm32-wasip2]

OUT_DIR/lib/python3.15/ gets CHECKOUT/Lib (without test, idlelib, tkinter), the build's `_sysconfigdata*` and an empty lib-dynload (CPython looks for it).
"""

import shutil
import sys
from pathlib import Path

checkout, out = Path(sys.argv[1]), Path(sys.argv[2])
target = sys.argv[3] if len(sys.argv) > 3 else "wasm32-wasip2"
lib = out / "lib" / "python3.15"
shutil.rmtree(lib, ignore_errors=True)
shutil.copytree(checkout / "Lib", lib, ignore=shutil.ignore_patterns("test", "idlelib", "tkinter", "__pycache__"))
for f in (checkout / "cross-build" / target / "build").glob("lib.*/*.py"):
    shutil.copy(f, lib)
(lib / "lib-dynload").mkdir()
shutil.copy(Path(__file__).resolve().parent.parent / "guest" / "wasi_pip.py", lib)
print(f"{lib}: {sum(1 for _ in lib.rglob('*.py'))} files")
