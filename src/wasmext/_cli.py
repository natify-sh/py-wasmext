"""The command line, in the manner of `cythonize`:

wasmext src/mypkg/*.wasm          write the C beside each .wasm (what setup.py's wasmize() does), build nothing
wasmext -i src/mypkg/*.wasm       ... and build the extensions in place, next to the .wasm files
wasmext -b ...                    ... and build them under build/ (as `setup.py build_ext`)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ._gen import GenError
from ._wasm import WasmError
from ._wasmize import _wasmize  # pyright: ignore[reportPrivateUsage]

__all__ = ["main"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wasmext",
        description="Turn WebAssembly modules into native CPython extensions: the C is written beside each .wasm "
        "(or under --build-dir); with -i or -b the extensions are built too.",
    )
    parser.add_argument(
        "files", nargs="+", metavar="FILE", help=".wasm file or glob pattern (quote it to let wasmext expand it)"
    )
    parser.add_argument(
        "-i", "--inplace", action="store_true", help="build the extensions in place, next to the .wasm files"
    )
    parser.add_argument(
        "-b", "--build", action="store_true", help="build the extensions (under build/, or in place with -i)"
    )
    parser.add_argument(
        "-f", "--force", action="store_true", help="write the C and build again even if nothing changed"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="say nothing about what is not exposed or built")
    parser.add_argument(
        "-X", "--exclude", action="append", default=[], metavar="GLOB", help="leave out files matching GLOB"
    )
    parser.add_argument(
        "--build-dir", metavar="DIR", help="write the C to DIR/<module name>/ instead of beside the .wasm"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        made = _wasmize(args.files, args.exclude, build_dir=args.build_dir, force=args.force, quiet=args.quiet)
    except (WasmError, GenError, ValueError, RuntimeError) as exc:
        print(f"wasmext: error: {exc}", file=sys.stderr)
        return 1
    if not made:
        print("wasmext: no .wasm files to process", file=sys.stderr)
        return 1
    if not args.quiet:
        for wasm, ext in made:
            print(f"wasmext: {wasm} -> {ext.name} ({ext.include_dirs[-1]}/)")
    if not (args.inplace or args.build):
        return 0

    from setuptools import setup

    # `--inplace` puts a module `a.b.c` in the directory of the package `a.b`: here, the one the .wasm is in.
    package_dir: dict[str, str] = {}
    for wasm, ext in made:
        if wasm is None:
            continue
        package = ext.name.rpartition(".")[0]
        folder = Path(wasm).parent.as_posix()
        if package_dir.setdefault(package, folder) != folder:
            print(f"wasmext: error: the modules of package {package!r} are in two directories", file=sys.stderr)
            return 1
    script_args = ["build_ext"]
    if args.inplace:
        script_args.append("--inplace")
    if args.force:
        script_args.append("--force")
    if args.quiet:
        script_args.insert(0, "-q")
    try:
        setup(
            name="wasmext-cli",
            ext_modules=[ext for _, ext in made],
            package_dir=package_dir,
            packages=[],
            py_modules=[],
            script_args=script_args,
        )
    except SystemExit as exc:
        return 1 if exc.code not in (None, 0) else 0
    return 0
