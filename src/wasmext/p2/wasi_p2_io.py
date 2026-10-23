"""wasi:io (23 imports): `error`, `poll` and `streams` (the twin of `c/p2/wasi_p2_io.h`).

Names carry the interface and the resource: `wasi_io_streams_input_stream_read`. A result that does not fit in one flat value is written through the pointer that is
the last argument (the canonical ABI). The layouts used here:

- `result<list<u8>, stream-error>`: 12 bytes, tag at 0, the list (pointer, length) at 4; `result<_, stream-error>`: 12 bytes; `result<u64, stream-error>`: 16 bytes, the u64 at 8.
- `stream-error`: a variant {last-operation-failed(own<error>), closed} of 8 bytes: tag at 0, the handle at 4; it is at 4 in the results of 12 bytes and at 8 in the one of 16.

A stream of the host is an `InputStream` or an `OutputStream` (any object with these methods; `MemoryInput` and `BufferOutput` are here, files and sockets come with their
packages). `read` returns at most `n` bytes (`b""` if none is ready), raises `StreamClosed` at the end and `StreamFailed(message)` when the operation failed; a write is
limited by `check_write`, and a write of more than that is a trap.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .wasi_p2_core import (
    KIND_ERROR,
    KIND_INPUT_STREAM,
    KIND_OUTPUT_STREAM,
    KIND_POLLABLE,
    Host,
    Pollable,
    Trap,
    alloc,
    load_bytes,
    load_u32,
    store_bytes,
    store_u8,
    store_u32,
    store_u64,
    table_drop,
    table_get,
    table_new,
)

READ_CAP = 1 << 16  # the most a call of `read` gives back


class StreamClosed(Exception):
    """The stream has ended, or was closed: the `closed` case of `stream-error`."""


class StreamFailed(Exception):
    """The operation failed: the case `last-operation-failed`, with an `error` resource that carries the message (and, from a file, the `error-code` of wasi:filesystem)."""

    def __init__(self, message: str = "", code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def _call(stream: object, fn: Callable[..., Any], *args: Any) -> Any:
    """Calls a method of a stream under the rule of `stream-error`: after `last-operation-failed` the stream is closed, and every later call is `closed`."""
    if getattr(stream, "dead", False):
        raise StreamClosed
    try:
        return fn(*args)
    except StreamFailed:
        stream.dead = True  # type: ignore[attr-defined]
        raise


class InputStream:
    dead = False

    def read(self, n: int) -> bytes:
        raise NotImplementedError

    def ready(self) -> bool:
        return True

    def close(self) -> None:
        pass


class OutputStream:
    dead = False

    def check_write(self) -> int:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def flush(self) -> None:
        pass

    def ready(self) -> bool:
        return self.check_write() > 0

    def close(self) -> None:
        pass


class MemoryInput(InputStream):
    """Reads from bytes it was given; closed when they are all read."""

    def __init__(self, data: bytes) -> None:
        self.data, self.pos = bytes(data), 0

    def read(self, n: int) -> bytes:
        if self.pos >= len(self.data) and n:
            raise StreamClosed
        chunk = self.data[self.pos : self.pos + n]
        self.pos += len(chunk)
        return chunk


class BufferOutput(OutputStream):
    """Collects what is written in `data`; takes at most `limit` bytes in all."""

    def __init__(self, limit: int = 65536) -> None:
        self.data, self.limit = bytearray(), limit

    def check_write(self) -> int:
        return self.limit - len(self.data)

    def write(self, data: bytes) -> None:
        self.data += data


class StreamPollable(Pollable):
    def __init__(self, stream: InputStream | OutputStream) -> None:
        self.stream = stream

    def ready(self, host: Host) -> bool:
        return bool(getattr(self.stream, "dead", False)) or self.stream.ready()  # a closed stream is always ready


class Error:
    """The `error` resource: a message, and the `error-code` of wasi:filesystem if the error came from a file (`filesystem-error-code` reads it)."""

    __slots__ = ("code", "message")

    def __init__(self, message: str, code: int | None = None) -> None:
        self.message = message
        self.code = code


# making resources for the guest


def error_new(host: Host, message: str, code: int | None = None) -> int:
    return table_new(host, KIND_ERROR, Error(message, code))


def input_stream_new(host: Host, stream: InputStream) -> int:
    return table_new(host, KIND_INPUT_STREAM, stream)


def output_stream_new(host: Host, stream: OutputStream) -> int:
    return table_new(host, KIND_OUTPUT_STREAM, stream)


# error


def wasi_io_error_error_to_debug_string(host: Host, comp: int, self: int, retptr: int) -> None:
    error: Error = table_get(host, self, KIND_ERROR)  # type: ignore[assignment]
    data = error.message.encode()
    ptr = alloc(host, comp, 1, len(data))
    store_bytes(host, comp, ptr, data)
    store_u32(host, comp, retptr, ptr)
    store_u32(host, comp, retptr + 4, len(data))


def wasi_io_error_error_drop(host: Host, handle: int) -> None:
    table_drop(host, handle, KIND_ERROR)


# poll


def _pollable(host: Host, handle: int) -> Pollable:
    return table_get(host, handle, KIND_POLLABLE)  # type: ignore[return-value]


def wasi_io_poll_pollable_ready(host: Host, self: int) -> int:
    return int(_pollable(host, self).ready(host))


def wasi_io_poll_pollable_block(host: Host, self: int) -> None:
    pollable = _pollable(host, self)
    while not pollable.ready(host):
        host.wait()


def wasi_io_poll_pollable_drop(host: Host, handle: int) -> None:
    table_drop(host, handle, KIND_POLLABLE)


def wasi_io_poll_poll(host: Host, comp: int, in_ptr: int, in_len: int, retptr: int) -> None:
    """Waits until one of the pollables is ready and gives the indexes of all that are (a list of u32). An empty list is a trap."""
    if in_len == 0:
        raise Trap("poll of an empty list")
    pollables = [_pollable(host, load_u32(host, comp, in_ptr + 4 * i)) for i in range(in_len)]
    while not (ready := [i for i, p in enumerate(pollables) if p.ready(host)]):
        host.wait()
    ptr = alloc(host, comp, 4, 4 * len(ready))
    for k, i in enumerate(ready):
        store_u32(host, comp, ptr + 4 * k, i)
    store_u32(host, comp, retptr, ptr)
    store_u32(host, comp, retptr + 4, len(ready))


# streams


def _input(host: Host, handle: int) -> InputStream:
    return table_get(host, handle, KIND_INPUT_STREAM)  # type: ignore[return-value]


def _output(host: Host, handle: int) -> OutputStream:
    return table_get(host, handle, KIND_OUTPUT_STREAM)  # type: ignore[return-value]


def _ok(host: Host, comp: int, retptr: int) -> None:
    store_u8(host, comp, retptr, 0)


def _err(host: Host, comp: int, retptr: int, error_at: int, exc: Exception) -> None:
    """Writes `err(stream-error)`: the tag of the result at `retptr`, the variant at `error_at`."""
    store_u8(host, comp, retptr, 1)
    if isinstance(exc, StreamFailed):
        store_u8(host, comp, error_at, 0)
        store_u32(host, comp, error_at + 4, error_new(host, str(exc), exc.code))
    else:
        store_u8(host, comp, error_at, 1)


def _read(host: Host, stream: InputStream, n: int, block: bool) -> bytes:
    """Up to `n` bytes; when `block`, waits for at least one (a read of 0 bytes is empty at once)."""
    while True:
        data = _call(stream, stream.read, min(n, READ_CAP))
        if data or not block or n == 0:
            return data
        host.wait()


def wasi_io_streams_input_stream_read(host: Host, comp: int, self: int, len: int, retptr: int) -> None:
    _read_list(host, comp, self, len, retptr, False)


def wasi_io_streams_input_stream_blocking_read(host: Host, comp: int, self: int, len: int, retptr: int) -> None:
    _read_list(host, comp, self, len, retptr, True)


def _read_list(host: Host, comp: int, self: int, n: int, retptr: int, block: bool) -> None:
    stream = _input(host, self)
    try:
        data = _read(host, stream, n, block)
    except (StreamClosed, StreamFailed) as exc:
        _err(host, comp, retptr, retptr + 4, exc)
        return
    ptr = alloc(host, comp, 1, len(data))
    store_bytes(host, comp, ptr, data)
    _ok(host, comp, retptr)
    store_u32(host, comp, retptr + 4, ptr)
    store_u32(host, comp, retptr + 8, len(data))


def _skip(host: Host, comp: int, self: int, n: int, retptr: int, block: bool) -> None:
    stream = _input(host, self)
    try:
        done = len(_read(host, stream, n, block))
    except (StreamClosed, StreamFailed) as exc:
        _err(host, comp, retptr, retptr + 8, exc)
        return
    _ok(host, comp, retptr)
    store_u64(host, comp, retptr + 8, done)


def wasi_io_streams_input_stream_skip(host: Host, comp: int, self: int, len: int, retptr: int) -> None:
    _skip(host, comp, self, len, retptr, False)


def wasi_io_streams_input_stream_blocking_skip(host: Host, comp: int, self: int, len: int, retptr: int) -> None:
    _skip(host, comp, self, len, retptr, True)


def wasi_io_streams_input_stream_subscribe(host: Host, self: int) -> int:
    return table_new(host, KIND_POLLABLE, StreamPollable(_input(host, self)))


def wasi_io_streams_input_stream_drop(host: Host, handle: int) -> None:
    stream = _input(host, handle)
    table_drop(host, handle, KIND_INPUT_STREAM)
    if not any(stream is std for std in host.std.values()):  # a standard stream outlives the handles to it
        stream.close()


def wasi_io_streams_output_stream_check_write(host: Host, comp: int, self: int, retptr: int) -> None:
    stream = _output(host, self)
    try:
        budget = _call(stream, stream.check_write)
    except (StreamClosed, StreamFailed) as exc:
        _err(host, comp, retptr, retptr + 8, exc)
        return
    _ok(host, comp, retptr)
    store_u64(host, comp, retptr + 8, budget)


def _write(host: Host, comp: int, stream: OutputStream, data: bytes, retptr: int) -> bool:
    """One write, limited by the budget (a bigger one traps); False if it wrote an error."""
    try:
        if len(data) > _call(stream, stream.check_write):
            raise Trap("write of more than check-write allows")
        _call(stream, stream.write, data)
    except (StreamClosed, StreamFailed) as exc:
        _err(host, comp, retptr, retptr + 4, exc)
        return False
    return True


def wasi_io_streams_output_stream_write(host: Host, comp: int, self: int, ptr: int, len: int, retptr: int) -> None:
    stream = _output(host, self)
    if _write(host, comp, stream, load_bytes(host, comp, ptr, len), retptr):
        _ok(host, comp, retptr)


def _write_all_and_flush(host: Host, comp: int, stream: OutputStream, data: bytes, retptr: int) -> None:
    """Writes it all in pieces as the budget allows, waiting when it is 0, then flushes."""
    try:
        view = memoryview(data)
        while len(view):
            budget = _call(stream, stream.check_write)
            if budget == 0:
                host.wait()
                continue
            _call(stream, stream.write, bytes(view[:budget]))
            view = view[budget:]
        _call(stream, stream.flush)
    except (StreamClosed, StreamFailed) as exc:
        _err(host, comp, retptr, retptr + 4, exc)
        return
    _ok(host, comp, retptr)


def wasi_io_streams_output_stream_blocking_write_and_flush(
    host: Host, comp: int, self: int, ptr: int, len: int, retptr: int
) -> None:
    _write_all_and_flush(host, comp, _output(host, self), load_bytes(host, comp, ptr, len), retptr)


def wasi_io_streams_output_stream_write_zeroes(host: Host, comp: int, self: int, len: int, retptr: int) -> None:
    stream = _output(host, self)
    if _write(host, comp, stream, bytes(len), retptr):
        _ok(host, comp, retptr)


def wasi_io_streams_output_stream_blocking_write_zeroes_and_flush(
    host: Host, comp: int, self: int, len: int, retptr: int
) -> None:
    _write_all_and_flush(host, comp, _output(host, self), bytes(len), retptr)


def wasi_io_streams_output_stream_flush(host: Host, comp: int, self: int, retptr: int) -> None:
    stream = _output(host, self)
    try:
        _call(stream, stream.flush)
    except (StreamClosed, StreamFailed) as exc:
        _err(host, comp, retptr, retptr + 4, exc)
        return
    _ok(host, comp, retptr)


def wasi_io_streams_output_stream_blocking_flush(host: Host, comp: int, self: int, retptr: int) -> None:
    wasi_io_streams_output_stream_flush(host, comp, self, retptr)


def _splice(host: Host, comp: int, self: int, src: int, n: int, retptr: int, block: bool) -> None:
    out, source = _output(host, self), _input(host, src)
    try:
        while True:
            budget = _call(out, out.check_write)
            if budget == 0:
                if not block:
                    data = b""
                    break
                host.wait()
                continue
            data = _read(host, source, min(n, budget), block)
            break
        _call(out, out.write, data)
    except (StreamClosed, StreamFailed) as exc:
        _err(host, comp, retptr, retptr + 8, exc)
        return
    _ok(host, comp, retptr)
    store_u64(host, comp, retptr + 8, len(data))


def wasi_io_streams_output_stream_splice(host: Host, comp: int, self: int, src: int, len: int, retptr: int) -> None:
    _splice(host, comp, self, src, len, retptr, False)


def wasi_io_streams_output_stream_blocking_splice(
    host: Host, comp: int, self: int, src: int, len: int, retptr: int
) -> None:
    _splice(host, comp, self, src, len, retptr, True)


def wasi_io_streams_output_stream_subscribe(host: Host, self: int) -> int:
    return table_new(host, KIND_POLLABLE, StreamPollable(_output(host, self)))


def wasi_io_streams_output_stream_drop(host: Host, handle: int) -> None:
    stream = _output(host, handle)
    table_drop(host, handle, KIND_OUTPUT_STREAM)
    if not any(stream is std for std in host.std.values()):
        stream.close()
