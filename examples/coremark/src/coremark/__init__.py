"""CoreMark, built from `_core.wasm` into the native extension `coremark._core` by wasmext.

>>> import coremark
>>> print(coremark.run())          # ~20 s
...
Correct operation validated. See README.md for run and reporting rules.
CoreMark 1.0 : 23726.199656 / zig cc (clang), wasm32 -O3 / STATIC
"""

from __future__ import annotations

import time
from collections.abc import Callable

from . import _core  # the extension made from _core.wasm; _core.pyi (written by wasmext) types it

__all__ = ["run"]


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


def run(millis: Callable[[], int] = _monotonic_ms) -> str:
    """Run the benchmark and return what it printed. `millis` is the clock the module times itself with."""
    printed: list[bytes] = []
    box: dict[str, memoryview] = {}

    def print_(offset: int, length: int) -> None:
        printed.append(bytes(box["memory"][offset : offset + length]))

    instance = _core.Instance(
        _core.Store(),
        imports={
            "wiring": {
                "millis": millis,
                "print": print_,
            }
        },
    )
    box["memory"] = instance.memory
    instance.setup()
    return b"".join(printed).decode()
