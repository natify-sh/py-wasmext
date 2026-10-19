"""python -m wabtwasm wat2wasm|wasm2c [options of the tool] FILE: the tool, as the command line program;
python -m wabtwasm toolchain DIR: a directory for `WASMEXT_WABT=DIR` (see _toolchain.py).

The program sees the current directory, and the directory of each argument that is an absolute path to a file or to where a file will be
(under the name that the path has, so that the path works in the program): this is what lets another program, `wasmext` for one, call it
in place of the `wasm2c` that is a file of the system.
"""

from __future__ import annotations

import os
import sys

from . import _wasm2c, _wat2wasm
from ._toolchain import make_toolchain


def preopens(arguments: list[str]) -> dict[str, str]:
    """The directories the program may use: the current one, and the one of each argument that is an absolute path (also after `-o`)."""
    folders = {".": "."}
    for argument in arguments:
        value = argument.split("=", 1)[1] if argument.startswith("--") and "=" in argument else argument
        if os.path.isabs(value):
            folder = value if os.path.isdir(value) else os.path.dirname(value)
            if folder and os.path.isdir(folder):
                folders[folder] = folder
    return folders


def main() -> int:
    tools = {"wat2wasm": _wat2wasm, "wasm2c": _wasm2c}
    if sys.argv[1:2] == ["toolchain"] and len(sys.argv) == 3:
        print(make_toolchain(sys.argv[2]))
        return 0
    if len(sys.argv) < 2 or sys.argv[1] not in tools:
        print(f"usage: python -m wabtwasm {'|'.join(tools)} [options] FILE | toolchain DIR", file=sys.stderr)
        return 2
    tool, module = sys.argv[1], tools[sys.argv[1]]
    wasi = {"args": [tool, *sys.argv[2:]], "preopens": preopens(sys.argv[2:])}
    instance = module.Instance(wasi=wasi)
    try:
        instance._start()
    except module.WasiExit as exit_:
        return exit_.code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
