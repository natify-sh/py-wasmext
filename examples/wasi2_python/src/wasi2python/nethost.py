"""wasi:sockets for the host of the experiment: name lookup (IPv4) and a TCP client with blocking connect, on top of fshost.FsHost.

Layouts (canonical ABI, WASI 0.2.12): `result<resolve-address-stream, error-code>` has its tag at 0 and the handle or the code at 4;
`result<option<ip-address>, error-code>` has the option tag at 2 and an `ip-address` at 4 (its tag at 4, the four bytes of IPv4 at 6);
`result<ip-socket-address, error-code>` has the address at 8 (tag at 8, port at 12... see _put_address). Not written: UDP, listening, IPv6.
"""

import errno
import socket

from wasi2demo.host import _In, _Out

from .fshost import FsHost

# error-code of wasi:sockets/network
_NET = {
    "unknown": 0,
    "access-denied": 1,
    "not-supported": 2,
    "invalid-argument": 3,
    "timeout": 5,
    "invalid-state": 9,
    "connection-refused": 14,
    "connection-reset": 15,
    "connection-aborted": 16,
    "name-unresolvable": 18,
    "temporary-resolver-failure": 19,
}


class _Names:
    def __init__(self, addresses):
        self.addresses = iter(addresses)


def _net_code(e):
    return {
        errno.ECONNREFUSED: 14,
        errno.ECONNRESET: 15,
        errno.ECONNABORTED: 16,
        errno.ETIMEDOUT: 5,
        errno.EACCES: 1,
    }.get(e.errno, 0)


class NetHost(FsHost):
    def table(self):
        t = super().table()
        for (m, n), f in {
            ("wasi:sockets/ip-name-lookup", "resolve-addresses"): "resolve_addresses",
            (
                "wasi:sockets/ip-name-lookup",
                "[method]resolve-address-stream.resolve-next-address",
            ): "resolve_next_address",
            ("wasi:sockets/ip-name-lookup", "[method]resolve-address-stream.subscribe"): "subscribe_ready",
            ("wasi:sockets/tcp", "[method]tcp-socket.finish-connect"): "finish_connect",
            ("wasi:sockets/tcp", "[method]tcp-socket.remote-address"): "remote_address",
            ("wasi:sockets/tcp", "[method]tcp-socket.local-address"): "local_address",
            ("wasi:sockets/tcp", "[method]tcp-socket.shutdown"): "shutdown",
            ("wasi:sockets/tcp", "[method]tcp-socket.set-keep-alive-enabled"): "ok1",
            ("wasi:sockets/tcp", "[method]tcp-socket.set-receive-buffer-size"): "ok1",
            ("wasi:sockets/tcp", "[method]tcp-socket.set-send-buffer-size"): "ok1",
            ("wasi:sockets/tcp", "[method]tcp-socket.set-hop-limit"): "ok1",
        }.items():
            t[(m, n)] = getattr(self, f)
        return t

    def resolve_addresses(self, network, ptr, n, result):
        name = self._string(ptr, n)
        try:
            found = sorted({a[4][0] for a in socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)})
        except socket.gaierror:
            self._byte(result, 1)
            self._byte(result + 4, _NET["name-unresolvable"])
            return
        self._byte(result, 0)
        self._u32(result + 4, self._new(_Names(found)))

    def resolve_next_address(self, stream, result):
        a = next(self._handles[stream].addresses, None)
        self._byte(result, 0)
        if a is None:
            self._byte(result + 2, 0)
            return
        self._byte(result + 2, 1)
        self._byte(result + 4, 0)  # some(ipv4)
        for k, part in enumerate(a.split(".")):
            self._byte(result + 6 + k, int(part))

    def finish_connect(self, socket_, result):
        tcp = self._handles[socket_]
        try:
            tcp.sock.connect(tcp.address)
        except OSError as e:
            self._byte(result, 1)
            self._byte(result + 4, _net_code(e))
            return
        tcp.sock.setblocking(False)
        self._byte(result, 0)
        self._u32(result + 4, self._new(_In(tcp.sock)))
        self._u32(result + 8, self._new(_Out(tcp.sock)))

    def _put_address(self, host, port, result):
        self._byte(result, 0)
        self._byte(result + 4, 0)  # ok, ipv4
        self._memory()[result + 8 : result + 10] = port.to_bytes(2, "little")
        for k, part in enumerate(host.split(".")):
            self._byte(result + 10 + k, int(part))

    def remote_address(self, socket_, result):
        self._put_address(*self._handles[socket_].sock.getpeername()[:2], result)

    def local_address(self, socket_, result):
        self._put_address(*self._handles[socket_].sock.getsockname()[:2], result)

    def shutdown(self, socket_, how, result):
        try:
            self._handles[socket_].sock.shutdown((socket.SHUT_RD, socket.SHUT_WR, socket.SHUT_RDWR)[how])
        except OSError:
            pass
        self._byte(result, 0)
