"""wasi:cli (13 imports): `environment`, `exit`, `stdin`, `stdout`, `stderr` and the terminals (the twin of `c/p2/wasi_p2_cli.h`).

- `environment`: `Host.args`, `Host.env`, `Host.initial_cwd`; lists and strings are written into the memory of the component (`cabi_realloc`), the list first, then the strings
  in order. `get-environment` is a `list<tuple<string, string>>` (16 bytes an element), `get-arguments` a `list<string>` (8 bytes), `initial-cwd` an `option<string>` (tag at 0,
  the string at 4).
- `exit`: raises `Exit(code)`; `exit(status: result)` is 0 for ok and 1 for error, `exit-with-code` takes the code (the low 8 bits).
- `stdin`, `stdout`, `stderr`: a new handle on every call, to the same stream: the one the caller gave the `Host`, or by default **the Python streams of the moment**
  (`sys.stdin.buffer` and so on, looked at when used, so that a capture of the output sees what the guest writes; as in the WASI 0.1 host of wasmext). `FdInput` and `FdOutput` write
  to a descriptor. A standard stream is not closed when a handle to it is dropped.
- the terminals: `get-terminal-*` is `some(handle)` for the names in `Host.terminals` and `none` otherwise (the default); the resources have no methods.
"""

from __future__ import annotations

import os
import select
import sys

from .wasi_p2_core import (
    KIND_INPUT_STREAM,
    KIND_OUTPUT_STREAM,
    KIND_TERMINAL_INPUT,
    KIND_TERMINAL_OUTPUT,
    Exit,
    Host,
    alloc,
    store_bytes,
    store_u8,
    store_u32,
    table_drop,
    table_new,
)
from .wasi_p2_io import InputStream, OutputStream, StreamClosed, StreamFailed

CHUNK = 4096  # what a standard output takes at a time (`check-write`)


class FdInput(InputStream):
    """Reads a file descriptor without blocking where the system can tell (select); an end of file is `StreamClosed`."""

    def __init__(self, fd: int = 0) -> None:
        self.fd = fd

    def ready(self) -> bool:
        if sys.platform == "win32":
            return True
        return bool(select.select([self.fd], [], [], 0)[0])

    def read(self, n: int) -> bytes:
        if n == 0 or not self.ready():
            return b""
        try:
            data = os.read(self.fd, n)
        except OSError as exc:
            raise StreamFailed(str(exc)) from exc
        if not data:
            raise StreamClosed
        return data


class FdOutput(OutputStream):
    def __init__(self, fd: int = 1) -> None:
        self.fd = fd

    def check_write(self) -> int:
        return CHUNK

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        try:
            while len(view):
                view = view[os.write(self.fd, view) :]
        except OSError as exc:
            raise StreamFailed(str(exc)) from exc


class SysInput(InputStream):
    """`sys.stdin.buffer` of the moment (blocking: a read waits for at least one byte or the end)."""

    def read(self, n: int) -> bytes:
        buffer = getattr(sys.stdin, "buffer", None)
        if buffer is None:
            return b""
        data = buffer.read1(n) if hasattr(buffer, "read1") else buffer.read(n)
        if not data and n:
            raise StreamClosed
        return data


class SysOutput(OutputStream):
    """`sys.stdout.buffer` or `sys.stderr.buffer` of the moment (the text layer is flushed first so that the order against `print` holds)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def _target(self):
        return getattr(sys, self.name)

    def check_write(self) -> int:
        return CHUNK

    def write(self, data: bytes) -> None:
        target = self._target()
        try:
            target.flush()
            buffer = getattr(target, "buffer", None)
            if buffer is not None:
                buffer.write(data)
            else:
                target.write(data.decode(errors="replace"))
        except (OSError, ValueError) as exc:
            raise StreamFailed(str(exc)) from exc

    def flush(self) -> None:
        try:
            self._target().flush()
        except (OSError, ValueError) as exc:
            raise StreamFailed(str(exc)) from exc


def _std(host: Host, name: str) -> object:
    if name not in host.std:
        host.std[name] = SysInput() if name == "stdin" else SysOutput(name)
    return host.std[name]


def _string(host: Host, comp: int, text: str) -> tuple[int, int]:
    data = text.encode()
    ptr = alloc(host, comp, 1, len(data))
    store_bytes(host, comp, ptr, data)
    return ptr, len(data)


# environment


def wasi_cli_environment_get_environment(host: Host, comp: int, retptr: int) -> None:
    items = host.env
    ptr = alloc(host, comp, 4, 16 * len(items))
    for i, (name, value) in enumerate(items):
        for k, text in enumerate((name, value)):
            sptr, slen = _string(host, comp, text)
            store_u32(host, comp, ptr + 16 * i + 8 * k, sptr)
            store_u32(host, comp, ptr + 16 * i + 8 * k + 4, slen)
    store_u32(host, comp, retptr, ptr)
    store_u32(host, comp, retptr + 4, len(items))


def wasi_cli_environment_get_arguments(host: Host, comp: int, retptr: int) -> None:
    ptr = alloc(host, comp, 4, 8 * len(host.args))
    for i, text in enumerate(host.args):
        sptr, slen = _string(host, comp, text)
        store_u32(host, comp, ptr + 8 * i, sptr)
        store_u32(host, comp, ptr + 8 * i + 4, slen)
    store_u32(host, comp, retptr, ptr)
    store_u32(host, comp, retptr + 4, len(host.args))


def wasi_cli_environment_initial_cwd(host: Host, comp: int, retptr: int) -> None:
    if host.initial_cwd is None:
        store_u8(host, comp, retptr, 0)
        return
    sptr, slen = _string(host, comp, host.initial_cwd)
    store_u8(host, comp, retptr, 1)
    store_u32(host, comp, retptr + 4, sptr)
    store_u32(host, comp, retptr + 8, slen)


# exit


def wasi_cli_exit_exit(host: Host, status: int) -> None:
    raise Exit(0 if status == 0 else 1)


def wasi_cli_exit_exit_with_code(host: Host, status_code: int) -> None:
    raise Exit(status_code & 0xFF)


# the standard streams


def wasi_cli_stdin_get_stdin(host: Host) -> int:
    return table_new(host, KIND_INPUT_STREAM, _std(host, "stdin"))


def wasi_cli_stdout_get_stdout(host: Host) -> int:
    return table_new(host, KIND_OUTPUT_STREAM, _std(host, "stdout"))


def wasi_cli_stderr_get_stderr(host: Host) -> int:
    return table_new(host, KIND_OUTPUT_STREAM, _std(host, "stderr"))


# the terminals


def _terminal(host: Host, comp: int, retptr: int, name: str, kind: int) -> None:
    if name in host.terminals:
        store_u8(host, comp, retptr, 1)
        store_u32(host, comp, retptr + 4, table_new(host, kind, name))
    else:
        store_u8(host, comp, retptr, 0)


def wasi_cli_terminal_stdin_get_terminal_stdin(host: Host, comp: int, retptr: int) -> None:
    _terminal(host, comp, retptr, "stdin", KIND_TERMINAL_INPUT)


def wasi_cli_terminal_stdout_get_terminal_stdout(host: Host, comp: int, retptr: int) -> None:
    _terminal(host, comp, retptr, "stdout", KIND_TERMINAL_OUTPUT)


def wasi_cli_terminal_stderr_get_terminal_stderr(host: Host, comp: int, retptr: int) -> None:
    _terminal(host, comp, retptr, "stderr", KIND_TERMINAL_OUTPUT)


def wasi_cli_terminal_input_terminal_input_drop(host: Host, handle: int) -> None:
    table_drop(host, handle, KIND_TERMINAL_INPUT)


def wasi_cli_terminal_output_terminal_output_drop(host: Host, handle: int) -> None:
    table_drop(host, handle, KIND_TERMINAL_OUTPUT)
