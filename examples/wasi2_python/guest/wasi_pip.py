"""Runs the pip that ships with CPython inside WASI: `python -m wasi_pip install --index-url ... PACKAGE`.

ensurepip starts pip in a child process, and WASI has none, so the bundled wheel is put on the path and pip is called in this process.
The things pip needs of the platform that WASI does not have are given here: `os.getuid`, `os.umask`, the module `mmap`, and an `os.write` that writes it all.
"""

import glob
import os
import sys
import types


def _write_all(write):
    def os_write(fd, data):
        # wasi-libc's write(2) writes what the stream allows (65536 bytes on wasmtime, 4096 on a host that says so) and returns that; importlib.resources
        # (pip's certifi, taken out of the wheel) calls it once and so left a certificate bundle cut short
        view, done = memoryview(data), 0
        while done < len(view):
            done += write(fd, view[done:])
        return done

    return os_write


def main(argv: list[str]) -> int:
    os.write = _write_all(os.write)
    os.getuid = os.geteuid = lambda: 0  # platformdirs
    os.umask = lambda mask: 0o22  # pip: current_umask()
    module = types.ModuleType("mmap")  # cachecontrol only tests isinstance(..., mmap.mmap)
    module.mmap = type("mmap", (), {})
    sys.modules["mmap"] = module
    wheel = glob.glob(os.path.join(os.path.dirname(os.__file__), "ensurepip", "_bundled", "pip-*.whl"))[0]
    sys.path.insert(0, wheel)
    from pip._internal.cli.main import main as pip_main

    return pip_main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
