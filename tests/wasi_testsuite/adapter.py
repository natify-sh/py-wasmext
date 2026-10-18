"""An adapter for the test runner of the WASI test suite: runs a program as wasmext builds it (see run_wasmext.py).

./run-tests --runtime /path/to/wasmext/tests/wasi_testsuite/adapter.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RUN = Path(__file__).parent / "run_wasmext.py"


def get_name() -> str:
    return "wasmext"


def get_version() -> str:
    return "0"


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
    for key, value in env.items():
        argv += ["--env", f"{key}={value}"]
    if root:
        argv += ["--dir", f"{root}::/"]
    return [*argv, test_path, *args]
