"""The command line, in the manner of `cythonize`:

wasmext src/mypkg/*.wasm          write the C beside each .wasm (what setup.py's wasmize() does), build nothing
wasmext -i src/mypkg/*.wasm       ... and build the extensions in place, next to the .wasm files
wasmext -b ...                    ... and build them under build/ (as `setup.py build_ext`)
wasmext inspect src/mypkg/*.wasm  say what each module imports and exports, and what wasmext makes of it
"""

from __future__ import annotations

import argparse
import copy
import glob
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from ._gen import GenError
from ._inspect import read
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
        action=argparse.BooleanOptionalAction,
        default=None,
        help="force the stable ABI (abi3) or a native extension; default: abi3 where this Python has one",
    )
    parser.add_argument("--no-stubs", action="store_true", help="do not write a .pyi beside each .wasm")
    parser.add_argument(
        "-X", "--exclude", action="append", default=[], metavar="GLOB", help="leave out files matching GLOB"
    )
    parser.add_argument(
        "--build-dir", metavar="DIR", help="write the C to DIR/<module name>/ instead of beside the .wasm"
    )
    return parser


def _inspect_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="wasmext inspect",
        description="Say what a WebAssembly module imports and exports and what wasmext would make of it "
        "(nothing is written; wasm2c is not needed). Exit status 1 if some module cannot be wrapped.",
    )
    parser.add_argument("files", nargs="+", metavar="FILE", help=".wasm file or glob pattern")
    args = parser.parse_args(argv)
    paths = sorted({Path(p) for pattern in args.files for p in (glob.glob(pattern, recursive=True) or [pattern])})
    status = 0
    for i, path in enumerate(paths):
        try:
            report, ok = read(path)
        except OSError as exc:
            report, ok = f"{path.as_posix()}: {exc.strerror or exc}\n", False
        print(("\n" if i else "") + report, end="")
        status |= 0 if ok else 1
    return status


def main(argv: Sequence[str] | None = None) -> int:
    given = list(sys.argv[1:] if argv is None else argv)
    if given[:1] == ["inspect"]:  # a file called `inspect` can still be given as ./inspect
        return _inspect_main(given[1:])
    args = _parser().parse_args(given)
    try:
        made = _wasmize(
            args.files,
            args.exclude,
            build_dir=args.build_dir,
            force=args.force,
            quiet=args.quiet,
            stubs=not args.no_stubs,
            limited_api=args.abi3,
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


def _prune_stale(base: Path, module: str) -> None:
    """After an in-place build, leave one extension file for `module`: the newest.

    Python tries `.cpython-311-<platform>.so` before `.abi3.so`, so a native file left by an earlier build would be imported
    in place of the abi3 one just built (and the other way round after `--no-abi3`: the `.abi3.so` is tried second)."""
    *package, stem = module.split(".")
    folder = base.joinpath(*package)
    files = [p for p in folder.glob(f"{stem}.*") if p.suffix in (".so", ".pyd") and p.name.split(".")[0] == stem]
    if len(files) > 1:
        newest = max(files, key=lambda p: p.stat().st_mtime_ns)
        for old in files:
            if old != newest:
                old.unlink()
                print(
                    f"wasmext: removed the stale {old.name} (the {newest.name} just built would be shadowed)",
                    file=sys.stderr,
                )


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
    else:
        if inplace:
            for ext in moved:
                _prune_stale(base, ext.name)
    finally:
        os.chdir(cwd)
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
        if inplace and not leave_build:  # setuptools makes an empty build/ even when it builds in place
            shutil.rmtree(base / "build", ignore_errors=True)
    return 0
