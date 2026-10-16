"""The command line, in the manner of `cythonize`:

wasmext src/mypkg/*.wasm          write the C beside each .wasm (what setup.py's wasmize() does), build nothing
wasmext -i src/mypkg/*.wasm       ... and build the extensions in place, next to the .wasm files
wasmext -b ...                    ... and build them under build/ (as `setup.py build_ext`)
"""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from ._gen import GenError
from ._wasm import WasmError
from ._wasmize import _wasmize  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from setuptools import Extension

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
        "--abi3",
        action="store_true",
        help="build for the stable ABI (abi3, CPython 3.11 and later); also WASMEXT_LIMITED_API=1",
    )
    parser.add_argument("--no-stubs", action="store_true", help="do not write a .pyi beside each .wasm")
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
        made = _wasmize(
            args.files,
            args.exclude,
            build_dir=args.build_dir,
            force=args.force,
            quiet=args.quiet,
            stubs=not args.no_stubs,
            limited_api=True if args.abi3 else None,
        )
    except (WasmError, GenError, ValueError, RuntimeError) as exc:
        print(f"wasmext: error: {exc}", file=sys.stderr)
        return 1
    if not made:
        print("wasmext: no .wasm files to process", file=sys.stderr)
        return 1
    if not args.quiet:
        for wasm, ext in made:
            print(f"wasmext: {Path(wasm).as_posix() if wasm else wasm} -> {ext.name} ({ext.include_dirs[-1]}/)")
    if not (args.inplace or args.build):
        return 0

    # As cythonize does: the extensions are built by setuptools in the directory above the topmost package of each
    # module (`src/` for src/pkg/x.wasm), one group at a time, so that `--inplace` puts them next to the .wasm files.
    groups: dict[Path, list[Extension]] = {}
    for wasm, ext in made:
        if wasm is not None:
            groups.setdefault(_package_root(wasm), []).append(ext)
    status = 0
    for base, extensions in groups.items():
        status |= _build(base, extensions, inplace=args.inplace, force=args.force, quiet=args.quiet)
    return status


def _package_root(wasm: Path) -> Path:
    """The directory above the topmost package (directory with an `__init__.py`) the file is in."""
    folder = wasm.resolve().parent
    while (folder / "__init__.py").is_file():
        folder = folder.parent
    return folder


def _rebase(ext: Extension, base: Path) -> Extension:
    """`ext` with its paths relative to `base` instead of the working directory."""

    def rel(paths: list[str]) -> list[str]:
        return [Path(os.path.relpath(os.path.abspath(p), base)).as_posix() for p in paths]

    moved = copy.copy(ext)
    moved.sources = rel(ext.sources)
    moved.depends = rel(ext.depends)
    moved.include_dirs = rel(ext.include_dirs)
    return moved


def _build(base: Path, extensions: list[Extension], *, inplace: bool, force: bool, quiet: bool) -> int:
    from setuptools import setup

    moved = [_rebase(ext, base) for ext in extensions]
    script_args = ["build_ext"]
    if inplace:
        script_args.append("--inplace")
    if force:
        script_args.append("--force")
    if quiet:
        script_args.insert(0, "-q")
    cwd = os.getcwd()
    temp: str | None = None
    leave_build = (base / "build").exists()
    try:
        os.chdir(base)
        if inplace:  # nothing but the extensions is left behind (cythonize keeps its objects out of build/ too)
            temp = tempfile.mkdtemp(dir=base)
            script_args += ["--build-temp", temp]
        setup(name="wasmext-cli", ext_modules=moved, packages=[], py_modules=[], script_args=script_args)
    except SystemExit as exc:
        return 1 if exc.code not in (None, 0) else 0
    finally:
        os.chdir(cwd)
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
        if inplace and not leave_build:  # setuptools makes an empty build/ even when it builds in place
            shutil.rmtree(base / "build", ignore_errors=True)
    return 0
