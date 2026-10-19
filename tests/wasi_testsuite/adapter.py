"""An adapter for the test runner of the WASI test suite: runs a program as wasmext builds it (see run_wasmext.py).

./run-tests --runtime /path/to/wasmext/tests/wasi_testsuite/adapter.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RUN = Path(__file__).parent / "run_wasmext.py"


# The tests expect other errors on other systems, and the suite asks for the system to be said with the environment of the
# program (tests/rust/wasm32-wasip1/src/config.rs): without it any of the errors the systems give is taken.
if sys.platform == "win32":
    # The files through Python cannot rename a directory over an empty one, as POSIX does (the native files of Windows can)
    # (no ERRNO_MODE_WINDOWS: it asks for the errors that a system gives that is not POSIX, where wasmext gives the errors of POSIX,
    # and without it the tests take any of the errors of the systems)
    PLATFORM = (
        {"NO_RENAME_DIR_TO_EMPTY_DIR": "1"}
        if "WASMEXT_WASI_PYTHON_FS=1" in os.environ.get("WASMEXT_TESTSUITE_CFLAGS", "")
        else {}
    )
elif sys.platform == "darwin":
    PLATFORM = {"ERRNO_MODE_MACOS": "1"}
else:
    PLATFORM = {"ERRNO_MODE_UNIX": "1"}


def get_name() -> str:
    return "wasmext"


def get_version() -> str:
    return "0"


def get_timeout_seconds() -> float:
    # the programs are built before (prebuild.py), but a machine can be slow and a build can be missing; the runner kills a program
    # at this time, and on Windows what it started goes on
    return 120.0


def get_wasi_versions() -> list[str]:
    return ["wasm32-wasip1"]


def get_wasi_worlds() -> list[str]:
    return ["wasi:cli/command"]


def compute_argv(
    test_path: str,
    args_env_root: tuple[list[str], dict[str, str], str | None],
    proposals: list[str],
    wasi_world: str,
    wasi_version: str,
) -> list[str]:
    args, env, root = args_env_root
    argv = [os.environ.get("WASMEXT_PYTHON", sys.executable), str(RUN)]
    if root:  # a test of files: the tests of the environment look at all of it
        env = {**PLATFORM, **env}
    for key, value in env.items():
        argv += ["--env", f"{key}={value}"]
    if root:
        argv += ["--dir", f"{root}::/"]
    return [*argv, test_path, *args]
