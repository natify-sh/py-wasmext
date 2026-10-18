"""Run one WASI program of the official test suite (https://github.com/WebAssembly/wasi-testsuite) as wasmext builds it.

    python run_wasmext.py [--env NAME=value]... [--dir host_directory::/] program.wasm [arguments...]

The program is turned into a native extension (the build is kept, by the contents of the file, so a second run is quick), then
`_start` is run: the exit code is the code the program gave `proc_exit`. This is the command that `adapter.py` hands to the
test runner of the suite; it is not a part of wasmext.
"""

from __future__ import annotations

import argparse
import faulthandler
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path


def main(argv: list[str]) -> int:
    faulthandler.dump_traceback_later(
        int(os.environ.get("WASMEXT_TESTSUITE_TIMEOUT", "600")), exit=True
    )  # a hang shows where
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--dir", action="append", default=[])
    parser.add_argument("--version", action="store_true")
    parser.add_argument("program", nargs="?")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    if options.version:
        from wasmext._wasmize import _version  # pyright: ignore[reportPrivateUsage]

        print(f"wasmext {_version()}")
        return 0
    program = Path(options.program)
    digest = hashlib.sha256(program.read_bytes()).hexdigest()[:16]
    cache = Path(os.environ.get("WASMEXT_TESTSUITE_CACHE", Path(tempfile.gettempdir()) / "wasmext-testsuite"))
    module = f"t_{digest}"
    home = cache / "modules"
    home.mkdir(parents=True, exist_ok=True)
    wasm = home / f"{module}.wasm"
    if not wasm.exists():
        shutil.copyfile(program, wasm)
    # -O0: the programs are tests of what a call does, not of how fast it is, and gcc is much quicker without optimizing
    os.environ.setdefault("CFLAGS", "-O0" if os.name != "nt" else "/Od")
    from wasmext import _importer  # pyright: ignore[reportPrivateUsage]

    _importer.install(build_dir=cache / "build", parts=int(os.environ.get("WASMEXT_TESTSUITE_PARTS", "8")))
    sys.path.insert(0, str(home))
    sys.stdout.flush()
    imported = __import__(module)
    env = dict(item.split("=", 1) for item in options.env)
    preopens = {}
    for item in options.dir:
        host, _, guest = item.partition("::")
        preopens[guest or "/"] = host
    instance = imported.Instance(
        wasi={
            "args": [str(program), *options.arguments],
            "env": env,
            "preopens": preopens,
            "stdin": sys.stdin.buffer,
            "stdout": sys.stdout.buffer,
            "stderr": sys.stderr.buffer,
        }
    )
    try:
        instance._start()  # pyright: ignore[reportPrivateUsage]
    except imported.WasiExit as exit_:
        code = exit_.code
    except imported.Trap as trap:
        print(f"trap: {trap}", file=sys.stderr)
        code = 134
    else:
        code = 0
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
