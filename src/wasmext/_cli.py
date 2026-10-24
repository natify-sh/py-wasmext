"""The command line, with a command for each thing it does:

wasmext natify src/mypkg/*.wasm     write the C beside each .wasm (what natify() of setup.py does), build nothing
wasmext natify -i src/mypkg/*.wasm  ... and build the extensions in place, next to the .wasm files
wasmext natify -b ...               ... and build them under build/ (as `setup.py build_ext`)
wasmext inspect src/mypkg/*.wasm    say what each module imports and exports, and what wasmext makes of it
"""

from __future__ import annotations

import argparse
import copy
import glob
import importlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ._gen import HOST_ALIASES, HOSTS, GenError
from ._inspect import read
from ._natify import Generated, _natify, _version, parse_guard_pages  # pyright: ignore[reportPrivateUsage]
from ._toolchain import find_toolchain
from ._wasm import WasmError

if TYPE_CHECKING:
    from setuptools import Extension

__all__ = ["main"]


def _version_text() -> str:
    """`wasmext 0.1.0a1 (WABT 1.0.42)`: the version of wasmext and of the WABT it would use, where there is one."""
    try:
        return f"wasmext {_version()} (WABT {find_toolchain().version})"
    except RuntimeError:
        return f"wasmext {_version()} (no WABT found)"


def _parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="wasmext",
        description="Turn WebAssembly modules into native CPython extensions.",
    )
    top.add_argument("--version", action="version", version=_version_text())
    commands = top.add_subparsers(dest="command", required=True, metavar="COMMAND")
    parser = commands.add_parser(
        "natify",
        help="make native extensions of .wasm files",
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
        "-b",
        "--build",
        action="store_true",
        help="build the extensions (in build/lib.*, or in place with -i; the objects are in build/temp.* either way)",
    )
    parser.add_argument(
        "-f", "--force", action="store_true", help="write the C and build again even if nothing changed"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="say nothing about what is not exposed or built")
    parser.add_argument(
        "--limited-api",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="force the stable ABI (abi3) or a native extension; default: abi3 where this Python has one",
    )
    parser.add_argument(
        "--guard-pages",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="reserve address space for the memories and check them with guard pages (fast, the default), or allocate "
        "what they need and check every access (--no-guard-pages: for processes with a limit on address space)",
    )
    parser.add_argument(
        "--guard-pages-for",
        metavar="ARCH=on|off,...",
        help="guard pages by architecture of the target (x86_64, x86, arm64, armv7l, ...), e.g. x86=off,armv7l=off; `default=` is for the others "
        "(or what --guard-pages says)",
    )
    parser.add_argument(
        "--parts",
        type=int,
        metavar="N",
        help="write the C of each module in N files, which are compiled at the same time (1: one file); default: WASMEXT_PARTS, "
        "else one file for a module under 1 MiB and one for each 128 KiB of a larger one",
    )
    parser.add_argument(
        "--share-tables",
        action="store_true",
        help="build the modules with the stack of entries for traps that modules with a funcref table share, whether or not they have one, so that "
        "a function of such a module can be put in a table (Table.set)",
    )
    parser.add_argument(
        "--host",
        default="wasm32",
        choices=[*HOSTS, *HOST_ALIASES],
        help="who stands on the other side of the imports: wasm32 (the default; every import is yours to give), wasm32-wasip1 (wasmext answers "
        "the imports of wasi_snapshot_preview1 and wasi_unstable; a program needs it) or wasm32-wasip2 (wasmext answers the imports of wasi:*@0.2 of the extension: wasi:cli, clocks, io, random, ...; wasi= configures them)",
    )
    what = parser.add_mutually_exclusive_group()
    what.add_argument(
        "--extension",
        dest="product",
        action="store_const",
        const="extension",
        help="make a Python extension (the default)",
    )
    what.add_argument(
        "--shared",
        dest="product",
        action="store_const",
        const="shared",
        help="make a shared library with a C API and a ctypes wrapper, instead of an extension (like an extension: the C is written, -i or -b builds it)",
    )
    what.add_argument(
        "--exe",
        dest="product",
        action="store_const",
        const="exe",
        help="make a program of a command (a module with _start), instead of an extension (like an extension: the C is written, -i or -b builds it)",
    )
    parser.set_defaults(product="extension")
    parser.add_argument("--no-stubs", action="store_true", help="do not make the .pyi of each extension")
    parser.add_argument(
        "-X", "--exclude", action="append", default=[], metavar="GLOB", help="leave out files matching GLOB"
    )
    parser.add_argument(
        "--build-dir", metavar="DIR", help="write the C to DIR/<module name>/ (default: build/wasmext/)"
    )
    inspect = commands.add_parser(
        "inspect",
        help="say what a module imports and exports and what wasmext makes of it",
        description="Say what a WebAssembly module imports and exports and what wasmext would make of it "
        "(nothing is written; wasm2c is not needed). Exit status 1 if some module cannot be wrapped.",
    )
    inspect.add_argument("files", nargs="+", metavar="FILE", help=".wasm file or glob pattern")
    return top


def _guard_pages_of(args: Any) -> Any:
    """What --guard-pages and --guard-pages-for ask together: a bool, a mapping of architectures, or None (not asked)."""
    if args.guard_pages_for is None:
        return args.guard_pages
    asked = parse_guard_pages(args.guard_pages_for)
    if isinstance(asked, bool):
        return asked
    if args.guard_pages is not None:
        asked.setdefault("default", args.guard_pages)
    return asked


def _inspect_main(files: Sequence[str]) -> int:
    paths = sorted({Path(p) for pattern in files for p in (glob.glob(pattern, recursive=True) or [pattern])})
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
    args = _parser().parse_args(given)
    if args.command == "inspect":
        return _inspect_main(args.files)
    try:
        made = _natify(
            args.files,
            args.exclude,
            build_dir=args.build_dir,
            force=args.force,
            quiet=args.quiet,
            stubs=not args.no_stubs,
            limited_api=args.limited_api,
            guard_pages=_guard_pages_of(args),
            parts=args.parts,
            share_tables=args.share_tables,
            host=args.host,
            product=args.product,
        )
    except (WasmError, GenError, ValueError, RuntimeError) as exc:
        print(f"wasmext: error: {exc}", file=sys.stderr)
        return 1
    if not made:
        print("wasmext: no .wasm files to process", file=sys.stderr)
        return 1
    if not args.quiet:
        for wasm, ext in made:
            shown = Path(wasm).as_posix() if wasm else wasm
            if args.product == "extension":
                print(f"wasmext: {shown} -> {ext.name} ({ext.include_dirs[-1]}/)")
                continue
            generated = cast("Generated", ext._wasmext_generated)  # type: ignore[attr-defined]
            print(
                f"wasmext: {shown} -> the C of the {args.product} {generated.last} ({Path(generated.out_dir).as_posix()}/)"
            )
            for item in generated.skipped:
                print(f"wasmext: {shown}: not in the library: {item}", file=sys.stderr)
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
    in place of the abi3 one just built (and the other way round after `--no-limited-api`: the `.abi3.so` is tried second)."""
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
        result: list[str] = []
        for p in paths:
            try:
                result.append(Path(os.path.relpath(os.path.abspath(p), base)).as_posix())
            except ValueError:  # another drive on Windows (the headers of simde are in the environment)
                result.append(Path(os.path.abspath(p)).as_posix())
        return result

    moved = copy.copy(ext)
    moved.sources = rel(ext.sources)
    moved.depends = rel(ext.depends)
    moved.include_dirs = rel(ext.include_dirs)
    return moved


def _build(base: Path, extensions: list[Extension], *, inplace: bool, force: bool, quiet: bool) -> int:
    from setuptools import setup

    moved = [_rebase(ext, base) for ext in extensions]
    if quiet:  # -q: the warnings of the C that wasm2c makes (an unused function, ...) are not the user's to read; their own flags come after and win
        from distutils.ccompiler import get_default_compiler  # pyright: ignore[reportMissingModuleSource]

        importlib.import_module(
            "setuptools"
        )  # puts the distutils of setuptools in place of the one of the standard library

        if get_default_compiler() != "msvc":  # cl says it is overriding /W3 with /w, which is a warning of its own
            for ext in moved:
                ext.extra_compile_args = ["-w", *(ext.extra_compile_args or [])]
    script_args = ["build_ext"]
    if inplace:
        script_args.append("--inplace")
    if force:
        script_args.append("--force")
    if quiet:
        script_args.insert(0, "-q")
    cwd = os.getcwd()
    os.environ["WASMEXT_NO_PYPROJECT"] = (
        "1"  # setuptools' hook of wasmext must not add the extensions of the table of a project to this build
    )
    try:
        os.chdir(base)
        cmdclass: dict[str, Any] = {}
        if any(getattr(e, "_wasmext_product", None) or getattr(e, "_wasmext_stub", None) for e in moved):
            from setuptools.command.build_ext import build_ext

            from ._setuptools import parallel_build_ext

            cmdclass["build_ext"] = parallel_build_ext(build_ext)
        setup(
            name="wasmext-cli",
            ext_modules=moved,
            packages=[],
            py_modules=[],
            script_args=script_args,
            cmdclass=cmdclass,
        )
    except SystemExit as exc:
        return 1 if exc.code not in (None, 0) else 0
    except (
        WasmError,
        GenError,
        ValueError,
        RuntimeError,
    ) as exc:  # a library or a program that cannot be made: said as the other errors are
        print(f"wasmext: error: {exc}", file=sys.stderr)
        return 1
    else:
        if inplace:
            for ext in moved:
                _prune_stale(base, ext.name)
    finally:
        os.environ.pop("WASMEXT_NO_PYPROJECT", None)
        os.chdir(cwd)
    return 0
