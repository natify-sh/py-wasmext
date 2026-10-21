"""A host of WASI 0.2 in Python, for the core module of a component (what `wasm-tools component unbundle` gives).

The imports of such a module are plain functions with the arguments of the canonical ABI flattened to numbers: a `result` comes back through a
pointer that is the last argument, a string or a list is a pointer and a length, a resource is a number. `Host.imports()` is the dictionary of
Python callables that `Instance(...)` takes. The numbers that stand for resources (a stream, a socket, a pollable) are handles into a table of the
host; `[resource-drop]*` removes an entry.

Written: the standard streams (out and err only), the clocks, `poll`, and a TCP client socket (`create-tcp-socket`, `start-connect`,
`finish-connect` and the streams of the connection). Every other import is there, because the module needs all of them to be given, and raises
`NotImplementedError` when it is called. Errors of the network are not turned into the `error-code` of WASI: an `OSError` comes out of the call.
"""

from __future__ import annotations

import select
import socket
import struct
import sys
import time
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO, Protocol

from ._imports import IMPORTS


class Instance(Protocol):
    """What the host needs from the instance of the module."""

    @property
    def memory(self) -> memoryview: ...

    def cabi_realloc(self, old: int, old_size: int, align: int, size: int, /) -> int: ...


class _Pollable:
    def __init__(self, ready: Callable[[], bool]) -> None:
        self.ready = ready


class _Std:
    def __init__(self, file: BinaryIO | None) -> None:
        self.file = file


class _Network:
    pass


class _Tcp:
    def __init__(self) -> None:
        self.sock = socket.socket()
        self.address: tuple[str, int] = ("", 0)


class _In:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock


class _Out:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock


# (module without its version, name of the import) -> the method of Host that is it
_METHODS = {
    ("wasi:cli/stdin", "get-stdin"): "get_stdin",
    ("wasi:cli/stdout", "get-stdout"): "get_stdout",
    ("wasi:cli/stderr", "get-stderr"): "get_stderr",
    ("wasi:cli/terminal-stdin", "get-terminal-stdin"): "no_terminal",
    ("wasi:cli/terminal-stdout", "get-terminal-stdout"): "no_terminal",
    ("wasi:cli/terminal-stderr", "get-terminal-stderr"): "no_terminal",
    ("wasi:io/streams", "[method]output-stream.check-write"): "check_write",
    ("wasi:io/streams", "[method]output-stream.write"): "write",
    ("wasi:io/streams", "[method]output-stream.blocking-flush"): "flush",
    ("wasi:io/streams", "[method]output-stream.subscribe"): "subscribe_ready",
    ("wasi:io/streams", "[method]input-stream.subscribe"): "subscribe_input",
    ("wasi:io/streams", "[method]input-stream.read"): "read",
    ("wasi:io/poll", "poll"): "poll",
    ("wasi:io/poll", "[method]pollable.block"): "block",
    ("wasi:clocks/monotonic-clock", "now"): "monotonic_now",
    ("wasi:clocks/monotonic-clock", "subscribe-duration"): "subscribe_duration",
    ("wasi:clocks/wall-clock", "now"): "wall_now",
    ("wasi:sockets/instance-network", "instance-network"): "instance_network",
    ("wasi:sockets/tcp-create-socket", "create-tcp-socket"): "create_tcp_socket",
    ("wasi:sockets/tcp", "[method]tcp-socket.start-connect"): "start_connect",
    ("wasi:sockets/tcp", "[method]tcp-socket.finish-connect"): "finish_connect",
    ("wasi:sockets/tcp", "[method]tcp-socket.subscribe"): "subscribe_ready",
}


def _not_written(name: str) -> Callable[..., Any]:
    def call(*_args: int) -> Any:
        raise NotImplementedError(name)

    return call


class Host:
    """The imports of one instance. Make it, give `imports()` to `Instance`, then `bind` the instance (the imports need its memory).

    `stdout` and `stderr` are binary files (the standard ones by default). `remap` makes a connection to an address go to another one: a
    program built with a port of its own can then be served on the port the host has.
    """

    def __init__(
        self,
        *,
        stdout: BinaryIO | None = None,
        stderr: BinaryIO | None = None,
        remap: Mapping[tuple[str, int], tuple[str, int]] | None = None,
    ) -> None:
        self._stdout = stdout if stdout is not None else sys.stdout.buffer
        self._stderr = stderr if stderr is not None else sys.stderr.buffer
        self._remap = dict(remap or {})
        self._handles: dict[int, object] = {}
        self._last = 0
        self._instance: Instance | None = None

    def bind(self, instance: Instance) -> None:
        self._instance = instance

    def imports(self) -> dict[str, dict[str, Callable[..., Any]]]:
        """Every import of the modules of this package, by module and name: the ones written, and for the others a function that raises."""
        given: dict[str, dict[str, Callable[..., Any]]] = {}
        for module, names in IMPORTS.items():
            bare = module.split("@")[0]
            table = given[module] = {}
            for name in names:
                method = _METHODS.get((bare, name))
                if method is not None:
                    table[name] = getattr(self, method)
                elif name.startswith("[resource-drop]"):
                    table[name] = self.drop
                else:
                    table[name] = _not_written(f"{bare}.{name}")
        return given

    # ---- the memory of the instance, and the table of handles

    def _memory(self) -> memoryview:
        if self._instance is None:
            raise RuntimeError("Host.bind(instance) was not called")
        return self._instance.memory

    def _byte(self, pointer: int, value: int) -> None:
        self._memory()[pointer] = value

    def _u32(self, pointer: int, value: int) -> None:
        struct.pack_into("<I", self._memory(), pointer, value)

    def _u64(self, pointer: int, value: int) -> None:
        struct.pack_into("<Q", self._memory(), pointer, value)

    def _new(self, resource: object) -> int:
        self._last += 1
        self._handles[self._last] = resource
        return self._last

    def drop(self, handle: int) -> None:
        self._handles.pop(handle, None)

    # ---- wasi:cli

    def get_stdin(self) -> int:
        return self._new(_Std(None))

    def get_stdout(self) -> int:
        return self._new(_Std(self._stdout))

    def get_stderr(self) -> int:
        return self._new(_Std(self._stderr))

    def no_terminal(self, result: int) -> None:
        self._byte(result, 0)  # an option that is none

    # ---- wasi:io

    def check_write(self, stream: int, result: int) -> None:
        self._byte(result, 0)  # ok
        self._u64(result + 8, 4096)  # the bytes that may be written now

    def write(self, stream: int, pointer: int, length: int, result: int) -> None:
        out = self._handles[stream]
        data = bytes(self._memory()[pointer : pointer + length])
        if isinstance(out, _Out):
            out.sock.sendall(data)
        elif isinstance(out, _Std) and out.file is not None:
            out.file.write(data)
            out.file.flush()
        else:
            raise NotImplementedError("a write to this stream")
        self._byte(result, 0)

    def flush(self, stream: int, result: int) -> None:
        self._byte(result, 0)

    def subscribe_ready(self, resource: int) -> int:
        return self._new(_Pollable(lambda: True))

    def subscribe_input(self, stream: int) -> int:
        source = self._handles[stream]
        if not isinstance(source, _In):
            raise NotImplementedError("a wait on this stream")
        sock = source.sock
        return self._new(_Pollable(lambda: bool(select.select([sock], [], [], 0)[0])))

    def read(self, stream: int, length: int, result: int) -> None:
        source = self._handles[stream]
        if not isinstance(source, _In):
            raise NotImplementedError("a read from this stream (standard input is not written)")
        if select.select([source.sock], [], [], 0)[0]:
            data = source.sock.recv(min(length, 65536))
            if data == b"":
                self._byte(result, 1)  # err(stream-error)
                self._byte(result + 4, 1)  # closed
                return
        else:
            data = b""  # nothing yet: an empty list, not a wait
        assert self._instance is not None
        pointer = self._instance.cabi_realloc(0, 0, 1, max(len(data), 1))
        self._memory()[pointer : pointer + len(data)] = data
        self._byte(result, 0)
        self._u32(result + 4, pointer)
        self._u32(result + 8, len(data))

    def poll(self, pointer: int, count: int, result: int) -> None:
        handles = struct.unpack_from(f"<{count}I", self._memory(), pointer)
        while True:
            ready = [i for i, handle in enumerate(handles) if self._pollable(handle).ready()]
            if ready:
                break
            time.sleep(0.001)
        assert self._instance is not None
        out = self._instance.cabi_realloc(0, 0, 4, 4 * len(ready))
        for k, index in enumerate(ready):
            self._u32(out + 4 * k, index)
        self._u32(result, out)
        self._u32(result + 4, len(ready))

    def block(self, pollable: int) -> None:
        while not self._pollable(pollable).ready():
            time.sleep(0.001)

    def _pollable(self, handle: int) -> _Pollable:
        pollable = self._handles[handle]
        assert isinstance(pollable, _Pollable)
        return pollable

    # ---- wasi:clocks

    def monotonic_now(self) -> int:
        return time.monotonic_ns()

    def subscribe_duration(self, nanoseconds: int) -> int:
        end = time.monotonic_ns() + nanoseconds
        return self._new(_Pollable(lambda: time.monotonic_ns() >= end))

    def wall_now(self, result: int) -> None:
        now = time.time_ns()
        self._u64(result, now // 10**9)  # seconds
        self._u32(result + 8, now % 10**9)  # nanoseconds

    # ---- wasi:sockets (a TCP client)

    def instance_network(self) -> int:
        return self._new(_Network())

    def create_tcp_socket(self, family: int, result: int) -> None:
        self._byte(result, 0)
        self._u32(result + 4, self._new(_Tcp()))

    def start_connect(
        self, socket_: int, network: int, tag: int, port: int, a: int, b: int, c: int, d: int, *rest: int
    ) -> None:
        # the ip-socket-address arrives flattened: its tag, then the port and the four bytes of an IPv4 address (an IPv6 one has more numbers,
        # which are `rest` without its last item); the last argument is the pointer of the result
        if tag != 0:
            raise NotImplementedError("an IPv6 address")
        tcp = self._handles[socket_]
        assert isinstance(tcp, _Tcp)
        address = (f"{a}.{b}.{c}.{d}", port)
        tcp.address = self._remap.get(address, address)
        self._byte(rest[-1], 0)

    def finish_connect(self, socket_: int, result: int) -> None:
        tcp = self._handles[socket_]
        assert isinstance(tcp, _Tcp)
        tcp.sock.connect(tcp.address)
        tcp.sock.setblocking(False)
        self._byte(result, 0)
        self._u32(result + 4, self._new(_In(tcp.sock)))  # the input stream
        self._u32(result + 8, self._new(_Out(tcp.sock)))  # the output stream
