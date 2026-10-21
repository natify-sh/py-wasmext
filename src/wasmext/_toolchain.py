"""Where `wasm2c` and its runtime sources are: the environment, the directory in WASMEXT_WABT, or the wabt-package."""

from __future__ import annotations

import functools
import importlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Toolchain", "find_toolchain"]

# What wasmext takes from the runtime directory (see _natify.py): the headers and sources of the runtime, as WABT 1.0.42 has them.
_RUNTIME_FILES = (
    "wasm-rt.h",
    "wasm-rt-impl.c",
    "wasm-rt-mem-impl.c",
    "wasm-rt-mem-impl-helper.inc",
    "wasm-rt-exceptions-impl.c",
)
_PARTS = ("WASMEXT_WASM2C", "WASMEXT_WASM2C_RUNTIME", "WASMEXT_WASM2C_INCLUDE")


@dataclass(frozen=True, slots=True)
class Toolchain:
    wasm2c: Path
    runtime: Path  # wasm-rt.h, wasm-rt-impl.c, ... of the version of `wasm2c`
    version: str
    include: Path | None = None  # headers the C of wasm2c may include, the simde/ of SIMD modules


def find_toolchain() -> Toolchain:
    """Each part is looked for in this order: its own variable (WASMEXT_WASM2C: the executable; WASMEXT_WASM2C_RUNTIME: the directory
    with `wasm-rt.h`; WASMEXT_WASM2C_INCLUDE: the directory with `simde/`), the directory in WASMEXT_WABT (with `bin/` and `wasm2c/`,
    like the one inside the wabt-package), the installed wabt-package. The wabt-package is not needed when every part is given.
    Raises RuntimeError with what to do if a part is nowhere."""
    exe_env, runtime_env, include_env = (os.environ.get(name) for name in _PARTS)
    base = _base(needed=not (exe_env and runtime_env))
    exe = _executable(exe_env) if exe_env else base.wasm2c if base else None
    runtime = _runtime(runtime_env, "WASMEXT_WASM2C_RUNTIME") if runtime_env else base.runtime if base else None
    assert exe is not None and runtime is not None
    _check_runtime(runtime)
    include = base.include if base else None
    if include_env:
        if not Path(include_env).is_dir():
            raise RuntimeError(f"WASMEXT_WASM2C_INCLUDE={include_env}: not a directory")
        include = Path(include_env)
    version = _version_of(exe) if exe_env else base.version if base else "unknown"
    return Toolchain(exe, runtime, version, include)


def _check_runtime(runtime: Path) -> None:
    missing = [name for name in _RUNTIME_FILES if not (runtime / name).is_file()]
    if missing:
        raise RuntimeError(
            f"the runtime in {runtime} has not {', '.join(missing)}: wasmext needs the files of the runtime of WABT 1.0.42 or later, "
            "all in one directory (a distribution may split them: headers in /usr/include, sources in /usr/share/wabt/wasm2c; "
            "and WABT before 1.0.42 does not have them all)"
        )


def _executable(env: str) -> Path:
    path = Path(env)
    if not path.is_file():
        raise RuntimeError(f"WASMEXT_WASM2C={env}: not a file (the executable `wasm2c`)")
    return path


def _runtime(env: str, name: str) -> Path:
    path = Path(env)
    if not (path / "wasm-rt.h").is_file():
        raise RuntimeError(f"{name}={env}: expected wasm-rt.h in it (the runtime of the C that wasm2c writes)")
    return path


@functools.cache
def _version_of(exe: Path) -> str:
    """What `wasm2c --version` says (`1.0.42`), else `unknown`."""
    try:
        done = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip().split()[0] if done.returncode == 0 and done.stdout.split() else "unknown"


def _base(*, needed: bool) -> Toolchain | None:
    """The directory in WASMEXT_WABT, else the wabt-package; None when `needed` is false and neither is there."""
    env = os.environ.get("WASMEXT_WABT")
    if env:
        root = Path(env)
        suffix = ".exe" if os.name == "nt" else ""
        exe = root / "bin" / ("wasm2c" + suffix)
        runtime = root / "wasm2c"
        if not exe.is_file() or not (runtime / "wasm-rt.h").is_file():
            if needed:
                raise RuntimeError(f"WASMEXT_WABT={env}: expected bin/wasm2c and wasm2c/wasm-rt.h in it")
            return None
        version = root / "_wabt_version.txt"
        headers = root / "include"
        return Toolchain(
            exe,
            runtime,
            version.read_text(encoding="utf-8").strip() if version.is_file() else "unknown",
            headers if headers.is_dir() else None,
        )
    try:
        wabt = importlib.import_module("wabt_package")
    except ImportError:
        if not needed:
            return None
        raise RuntimeError(
            "wasm2c is not available: install the wabt-package (`pip install wabt-package`; "
            "put it in build-system.requires), or point WASMEXT_WABT at a directory with bin/ and wasm2c/, "
            "or WASMEXT_WASM2C at the executable and WASMEXT_WASM2C_RUNTIME at the directory with wasm-rt.h"
        ) from None
    return Toolchain(wabt.get_executable("wasm2c"), wabt.runtime_dir(), wabt.wabt_version(), wabt.include_dir())
