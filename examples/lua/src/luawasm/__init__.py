"""Lua 5.4, a WASI program (`_lua.wasm`), built into the native extension `luawasm._lua` by wasmext.

>>> import luawasm
>>> luawasm.run(["-e", "print(2^10)"]).stdout
b'1024.0\\n'
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import _lua  # the extension made from _lua.wasm; _lua.pyi (written by wasmext) types it

__all__ = ["ABORTED", "Result", "run"]

# What a shell reports for a program that was aborted: this Lua is built without longjmp, so an error of the script (a syntax
# error, error(), a failed pcall) ends the interpreter with a trap, with no message.
ABORTED = 134


@dataclass(frozen=True)
class Result:
    code: int
    stdout: bytes
    stderr: bytes


class _Sink:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.chunks.append(bytes(data))
        return len(data)

    def value(self) -> bytes:
        return b"".join(self.chunks)


def run(args: list[str], *, stdin: bytes = b"", root: str | os.PathLike[str] | None = None) -> Result:
    """Run `lua` with `args` (`["script.lua"]`, `["-e", "print(1)"]`). The script and the files it opens are looked up in
    `root` (by default: nothing, the program sees no files); it can read, write and remove files there and nowhere else."""
    out, err = _Sink(), _Sink()
    wasi: dict[str, object] = {"args": ["lua", *args], "stdin": stdin, "stdout": out.write, "stderr": err.write}
    if root is not None:
        directory = os.fspath(root)
        wasi["preopens"] = {".": directory, "/": directory}  # an old libc finds a relative name only through "."
    instance = _lua.Instance(_lua.Store(wasi=wasi))  # pyright: ignore[reportArgumentType]
    try:
        instance._start()
        code = 0
    except _lua.WasiExit as exit_:
        code = exit_.code
    except _lua.Trap:
        code = ABORTED
    return Result(code, out.value(), err.value())
