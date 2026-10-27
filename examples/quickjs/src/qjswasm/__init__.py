"""QuickJS (quickjs-ng), a JavaScript engine and a WASI program (`_qjs.wasm`), built into the native extension `qjswasm._qjs` by wasmext.

>>> import qjswasm
>>> qjswasm.run(["-e", "console.log(2 ** 10)"]).stdout
b'1024\\n'
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import _qjs  # the extension made from _qjs.wasm; _qjs.pyi (written by wasmext) types it

__all__ = ["Result", "run"]


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
    """Run `qjs` with `args` (`["script.js"]`, `["-e", "console.log(1)"]`). The script and the files it opens are looked up in
    `root` (by default: nothing, the program sees no files); it can read, write and remove files there and nowhere else.
    An error of the script ends `qjs` with a code of 1 and a message on stderr, as on the command line."""
    out, err = _Sink(), _Sink()
    wasi: _qjs.Wasi = {"args": ["qjs", *args], "stdin": stdin, "stdout": out.write, "stderr": err.write}
    if root is not None:
        directory = os.fspath(root)
        wasi["preopens"] = {".": directory, "/": directory}  # an old libc finds a relative name only through "."
    instance = _qjs.Instance(_qjs.Store(wasi=wasi))
    try:
        instance._start()
        code = 0
    except _qjs.WasiExit as exit_:
        code = exit_.code
    return Result(code, out.value(), err.value())
