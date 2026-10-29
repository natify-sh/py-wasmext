"""Builds a plain C program for the tests of the core in tests/c/: with `cc` where there is one, with the compiler of Python (MSVC on Windows) otherwise."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

__all__ = ["compile_c", "find_cc", "supports_flag"]


def find_cc() -> str | None:
    if os.name == "nt":
        return None
    return shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")


def supports_flag(flag: str) -> bool:
    """Whether the C compiler takes `flag` and links with it (a sanitizer may be missing from the machine)."""
    cc = find_cc()
    if cc is None:
        return False
    probe = subprocess.run(
        [cc, flag, "-x", "c", "-", "-o", os.devnull],
        input="int main(void){return 0;}",
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


def compile_c(
    sources: Sequence[Path],
    exe: Path,
    *,
    include_dirs: Sequence[Path] = (),
    defines: Sequence[str] = (),
    flags: Sequence[str] = (),
    strict: bool = True,
    threads: bool = False,
    math: bool = False,  # the C of wasm2c calls the library of mathematics (-lm off Windows)
    std: str | None = "c99",  # the runtime of wasm2c needs the defaults of the compiler (POSIX names)
) -> None:
    """Builds `exe` from `sources`; skips the test where there is no compiler. `flags` are for `cc` only (a sanitizer)."""
    cc = find_cc()
    if cc is not None:
        extra = shlex.split(os.environ.get("WASMEXT_TEST_CFLAGS", ""))
        warn = ["-Wall", "-Wextra", "-Werror"] if strict else ["-w"]
        subprocess.run(
            [cc, *([f"-std={std}"] if std else []), *warn, *extra, *flags, *(["-pthread"] if threads else []), *(f"-D{d}" for d in defines),
             *(f"-I{d}" for d in include_dirs), *map(str, sources), *(["-lm"] if math else []), "-o", str(exe)],
            check=True,
        )  # fmt: skip
        return
    from setuptools._distutils.ccompiler import new_compiler  # pyright: ignore[reportMissingTypeStubs]
    from setuptools._distutils.errors import DistutilsPlatformError  # pyright: ignore[reportMissingTypeStubs]

    compiler = new_compiler()
    initialize = getattr(compiler, "initialize", None)  # the MSVC compiler looks for Visual Studio here
    try:
        if initialize is not None:
            initialize()
    except DistutilsPlatformError:
        pytest.skip("no C compiler")
    macros: list[tuple[str, str | None]] = [
        (d.split("=", 1)[0], d.split("=", 1)[1] if "=" in d else None) for d in defines
    ]
    objects = compiler.compile(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        [str(x) for x in sources],
        output_dir=str(exe.parent / (exe.stem + "_obj")),
        include_dirs=[str(d) for d in include_dirs],
        macros=macros,  # pyright: ignore[reportArgumentType]
    )
    compiler.link_executable(objects, exe.stem, output_dir=str(exe.parent))  # pyright: ignore[reportUnknownMemberType]
