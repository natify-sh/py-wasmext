"""WABT (`wat2wasm` and `wasm2c`), WASI programs (`_wat2wasm.wasm`, `_wasm2c.wasm`), built into native extensions by wasmext.

>>> import wabtwasm
>>> wabtwasm.wat2wasm('(module (func (export "f") (result i32) i32.const 42))')[:4]
b'\\x00asm'
>>> sorted(wabtwasm.wasm2c(wasm, name="m"))
['m.c', 'm.h']
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

from . import _wasm2c, _wat2wasm

__all__ = ["WabtError", "wasm2c", "wat2wasm"]


class WabtError(Exception):
    """A tool of WABT ended with a code other than 0; `.code` is it, `.stderr` and `.stdout` are what the tool said."""

    def __init__(self, tool: str, code: int, stdout: bytes, stderr: bytes) -> None:
        super().__init__(f"{tool} exited with {code}: {stderr.decode('utf-8', 'replace').strip()}")
        self.tool, self.code, self.stdout, self.stderr = tool, code, stdout, stderr


class _Sink:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.chunks.append(bytes(data))
        return len(data)

    def value(self) -> bytes:
        return b"".join(self.chunks)


def run(
    module: ModuleType, tool: str, args: list[str], files: dict[str, bytes]
) -> tuple[int, bytes, bytes, dict[str, bytes]]:
    """Run the tool in a directory that holds `files` and is the whole world of the program; its exit code, what it printed, and the
    files it left there (all of them, the ones it was given too)."""
    out, err = _Sink(), _Sink()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, data in files.items():
            (root / name).write_bytes(data)
        wasi: Any = {
            "args": [tool, *args],
            "stdout": out.write,
            "stderr": err.write,
            "preopens": {".": str(root), "/": str(root)},
        }
        instance = module.Instance(wasi=wasi)
        try:
            instance._start()
            code = 0
        except module.WasiExit as exit_:
            code = exit_.code
        produced = {p.name: p.read_bytes() for p in sorted(root.iterdir()) if p.is_file()}
    return code, out.value(), err.value(), produced


def wat2wasm(wat: str | bytes, *options: str) -> bytes:
    """The binary of a module in the text format. `options` are those of `wat2wasm` (`--enable-all`, `--no-check`, ...)."""
    source = wat.encode("utf-8") if isinstance(wat, str) else wat
    code, out, err, files = run(
        _wat2wasm, "wat2wasm", ["module.wat", "-o", "module.wasm", *options], {"module.wat": source}
    )
    if code:
        raise WabtError("wat2wasm", code, out, err)
    return files["module.wasm"]


def wasm2c(wasm: bytes, *options: str, name: str = "module") -> dict[str, bytes]:
    """The C of a module in the binary format: `{"<name>.c": ..., "<name>.h": ...}` (more files with `--num-outputs=N`). `options` are
    those of `wasm2c`."""
    code, out, err, files = run(
        _wasm2c, "wasm2c", ["module.wasm", "-o", f"{name}.c", f"--module-name={name}", *options], {"module.wasm": wasm}
    )
    if code:
        raise WabtError("wasm2c", code, out, err)
    files.pop("module.wasm", None)
    return files
