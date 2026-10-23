"""wasi:sockets of the host of WASI 0.2 (`wasmext.p2.wasi_p2_sockets`, `c/p2/wasi_p2_sockets.h`): the same scenario in Python and in C, on real sockets on the loopback.

The ports are those the system gives, so what is compared is whether they match, and the answers (states, errors, data). The permission is tested with a host that allows nothing.
"""

import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest

import wasmext
from wasmext.p2 import wasi_p2_io as io
from wasmext.p2 import wasi_p2_sockets as sk
from wasmext.p2.wasi_p2_core import (
    KIND_TCP_SOCKET,
    Host,
    Trap,
    load_u16,
    load_u32,
    store_u8,
    store_u16,
    store_u32,
    table_get,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the host of the sockets is POSIX only")

C_P2 = Path(wasmext.__file__).parent / "c" / "p2"
DRIVER = Path(__file__).parent / "data" / "wasi_p2_sockets_driver.c"
CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

SCENARIOS = ["main", "reset", "denied", "udp_trap", "bad_handle"]
R = 100


def a4(port: int, a: int, b: int, c: int, d: int) -> tuple[int, ...]:
    return (0, port, a, b, c, d, 0, 0, 0, 0, 0, 0)


def a6loop(port: int) -> tuple[int, ...]:
    return (1, port, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0)


def python_output(scenario: str) -> str:
    memory = bytearray(4096)
    next_free = [3000]

    def bump(comp: int, old_ptr: int, old_size: int, align: int, new_size: int) -> int:
        ptr = (next_free[0] + align - 1) // align * align
        next_free[0] = ptr + new_size
        return ptr

    allow = scenario != "denied"
    host = Host(
        [memory],
        realloc=bump,
        socket_addr_check=(lambda ip, port, use: True) if allow else None,
        allow_ip_name_lookup=allow,
    )
    out: list[str] = []

    def pr(text: str) -> None:
        out.append(text)

    def show(label: str, off: int, n: int) -> None:
        pr(f"{label}:{bytes(memory[off : off + n]).hex()}\n")

    def u32(off: int) -> int:
        return load_u32(host, 0, off)

    def u16(off: int) -> int:
        return load_u16(host, 0, off)

    def clear() -> None:
        memory[R : R + 64] = bytes(64)

    def tcp(name: str, *args: int) -> None:
        getattr(sk, "wasi_sockets_tcp_tcp_socket_" + name)(host, 0, *args)

    def udp(name: str, *args: int) -> None:
        getattr(sk, "wasi_sockets_udp_udp_socket_" + name)(host, 0, *args)

    def settle(fn: str, h: int) -> None:
        for _ in range(3000):
            clear()
            tcp(fn, h, R)
            if not (memory[R] == 1 and memory[R + 4] == sk._CODE["would-block"]):  # pyright: ignore[reportPrivateUsage]
                return
            time.sleep(0.001)

    def read_some(label: str, h: int) -> None:
        for _ in range(3000):
            clear()
            io.wasi_io_streams_input_stream_read(host, 0, h, 100, R)
            if memory[R] == 1 or u32(R + 8) > 0:
                break
            time.sleep(0.001)
        pr(f"{label} ")
        if memory[R] == 0:
            data = bytes(memory[u32(R + 4) : u32(R + 4) + u32(R + 8)])
            pr(f"data {data.hex()}\n")
        else:
            pr(f"stream-error tag {memory[R + 4]}\n")

    def put_dgram(idx: int, data: bytes, has_remote: bool, port: int) -> None:
        base, dptr = 2200 + 44 * idx, 2000 + 16 * idx
        memory[dptr : dptr + len(data)] = data
        memory[base : base + 44] = bytes(44)
        store_u32(host, 0, base, dptr)
        store_u32(host, 0, base + 4, len(data))
        store_u8(host, 0, base + 8, int(has_remote))
        if has_remote:
            store_u8(host, 0, base + 12, 0)
            store_u16(host, 0, base + 16, port)
            memory[base + 18] = 127
            memory[base + 21] = 1

    def receive_some(label: str, h: int, expect_port: int, tries: int = 3000) -> None:
        for _ in range(tries):
            clear()
            sk.wasi_sockets_udp_incoming_datagram_stream_receive(host, 0, h, 10, R)
            if memory[R] == 1 or u32(R + 8) > 0:
                break
            time.sleep(0.001)
        pr(f"{label} ")
        if memory[R] == 1:
            pr(f"error {memory[R + 4]}\n")
            return
        n, lst = u32(R + 8), u32(R + 4)
        pr(f"{n} datagrams")
        for i in range(n):
            d = lst + 40 * i
            data = bytes(memory[u32(d) : u32(d) + u32(d + 4)])
            match = int(u16(d + 12) == expect_port) if expect_port else -1
            pr(f" [{data.hex()} from tag {memory[d + 8]} port-match {match}]")
        pr("\n")

    net = sk.wasi_sockets_instance_network_instance_network(host)
    pr(f"network {net}\n")
    try:
        if scenario == "main":
            clear()
            sk.wasi_sockets_tcp_create_socket_create_tcp_socket(host, 0, 0, R)
            show("create tcp", R, 8)
            srv = u32(R + 4)
            pr(
                f"family {sk.wasi_sockets_tcp_tcp_socket_address_family(host, srv)} listening {sk.wasi_sockets_tcp_tcp_socket_is_listening(host, srv)}\n"
            )
            clear()
            tcp("local_address", srv, R)
            show("local address before bind", R, 8)
            clear()
            tcp("start_bind", srv, net, *a6loop(0), R)
            show("bind v6 on a v4 socket", R, 2)
            clear()
            tcp("start_bind", srv, net, *a4(0, 224, 0, 0, 1), R)
            show("bind multicast", R, 2)
            clear()
            tcp("start_bind", srv, net, *a4(0, 127, 0, 0, 1), R)
            show("start-bind", R, 2)
            clear()
            tcp("local_address", srv, R)
            show("local address while binding", R, 8)
            clear()
            tcp("finish_bind", srv, R)
            show("finish-bind", R, 2)
            clear()
            tcp("finish_bind", srv, R)
            show("finish-bind again", R, 2)
            clear()
            tcp("start_bind", srv, net, *a4(0, 127, 0, 0, 1), R)
            show("bind again", R, 2)
            clear()
            tcp("start_listen", srv, R)
            show("start-listen", R, 2)
            clear()
            tcp("finish_listen", srv, R)
            show("finish-listen", R, 2)
            clear()
            tcp("finish_listen", srv, R)
            show("finish-listen again", R, 2)
            pr(f"listening {sk.wasi_sockets_tcp_tcp_socket_is_listening(host, srv)}\n")
            clear()
            tcp("accept", srv, R)
            show("accept with nothing waiting", R, 8)
            clear()
            tcp("local_address", srv, R)
            show("listener", R, 1)
            show("  tag", R + 4, 1)
            show("  ip", R + 10, 4)
            port = u16(R + 8)
            # options
            clear()
            tcp("set_listen_backlog_size", srv, 0, R)
            show("backlog 0", R, 2)
            clear()
            tcp("set_listen_backlog_size", srv, 10, R)
            show("backlog 10", R, 2)
            clear()
            tcp("set_keep_alive_enabled", srv, 1, R)
            show("keep-alive on", R, 2)
            clear()
            tcp("keep_alive_enabled", srv, R)
            show("keep-alive?", R, 2)
            clear()
            tcp("set_keep_alive_idle_time", srv, 0, R)
            show("idle 0", R, 2)
            clear()
            tcp("set_keep_alive_idle_time", srv, 30_000_000_000, R)
            show("idle 30 s", R, 2)
            clear()
            tcp("keep_alive_idle_time", srv, R)
            show("idle?", R, 16)
            clear()
            tcp("set_keep_alive_interval", srv, 5_000_000_000, R)
            tcp("keep_alive_interval", srv, R + 24)
            show("interval", R, 2)
            show("  value", R + 24, 16)
            clear()
            tcp("set_keep_alive_count", srv, 3, R)
            tcp("keep_alive_count", srv, R + 24)
            show("count", R, 2)
            show("  value", R + 24, 8)
            clear()
            tcp("set_hop_limit", srv, 0, R)
            show("hop-limit 0", R, 2)
            clear()
            tcp("set_hop_limit", srv, 64, R)
            tcp("hop_limit", srv, R + 24)
            show("hop-limit 64", R, 2)
            show("  value", R + 24, 2)
            clear()
            tcp("set_receive_buffer_size", srv, 0, R)
            show("receive buffer 0", R, 2)
            clear()
            tcp("set_receive_buffer_size", srv, 65536, R)
            tcp("receive_buffer_size", srv, R + 24)
            show("receive buffer", R, 2)
            pr(f"  receive buffer > 0: {int(u32(R + 32) > 0)}\n")
            clear()
            tcp("set_send_buffer_size", srv, 65536, R)
            tcp("send_buffer_size", srv, R + 24)
            show("send buffer", R, 2)
            pr(f"  send buffer > 0: {int(u32(R + 32) > 0)}\n")
            listener_poll = sk.wasi_sockets_tcp_tcp_socket_subscribe(host, srv)
            pr(f"listener pollable {listener_poll} ready {io.wasi_io_poll_pollable_ready(host, listener_poll)}\n")
            # connect and accept
            clear()
            sk.wasi_sockets_tcp_create_socket_create_tcp_socket(host, 0, 0, R)
            cli = u32(R + 4)
            clear()
            tcp("remote_address", cli, R)
            show("remote address before connect", R, 8)
            clear()
            tcp("start_connect", cli, net, *a4(0, 0, 0, 0, 0), R)
            show("connect to 0.0.0.0", R, 2)
            clear()
            tcp("start_connect", cli, net, *a4(80, 224, 0, 0, 1), R)
            show("connect to multicast", R, 2)
            clear()
            tcp("start_connect", cli, net, *a6loop(80), R)
            show("connect v6 on a v4 socket", R, 2)
            clear()
            tcp("start_connect", cli, net, *a4(port, 127, 0, 0, 1), R)
            show("start-connect", R, 2)
            clear()
            tcp("start_connect", cli, net, *a4(port, 127, 0, 0, 1), R)
            show("connect twice", R, 2)
            settle("finish_connect", cli)
            show("finish-connect", R, 12)
            cin, cout = u32(R + 4), u32(R + 8)
            clear()
            tcp("finish_connect", cli, R)
            show("finish-connect again", R, 8)
            clear()
            tcp("remote_address", cli, R)
            show("client remote", R, 1)
            pr(f"  remote port is the listener's: {int(u16(R + 8) == port)}\n")
            pr(
                f"listener pollable ready with a connection waiting {io.wasi_io_poll_pollable_ready(host, listener_poll)}\n"
            )
            settle("accept", srv)
            show("accept", R, 16)
            conn, sin, sout = u32(R + 4), u32(R + 8), u32(R + 12)
            pr(f"listener pollable ready {io.wasi_io_poll_pollable_ready(host, listener_poll)}\n")
            # data both ways
            memory[2000:2004] = b"ping"
            clear()
            io.wasi_io_streams_output_stream_blocking_write_and_flush(host, 0, cout, 2000, 4, R)
            show("client writes", R, 8)
            read_some("server reads", sin)
            memory[2000:2005] = b"pong!"
            clear()
            io.wasi_io_streams_output_stream_blocking_write_and_flush(host, 0, sout, 2000, 5, R)
            show("server writes", R, 8)
            read_some("client reads", cin)
            clear()
            tcp("shutdown", cli, 1, R)
            show("client shutdown send", R, 2)
            read_some("server reads after the shutdown", sin)
            clear()
            tcp("shutdown", cli, 1, R)
            show("shutdown again", R, 2)
            clear()
            io.wasi_io_streams_output_stream_check_write(host, 0, cout, R)
            show("client can write?", R, 8)
            clear()
            tcp("shutdown", srv, 2, R)
            show("shutdown of a listener", R, 2)
            # connection refused
            sk.wasi_sockets_tcp_tcp_socket_drop(host, srv)
            sk.wasi_sockets_tcp_tcp_socket_drop(host, conn)
            sk.wasi_sockets_tcp_tcp_socket_drop(host, cli)
            clear()
            sk.wasi_sockets_tcp_create_socket_create_tcp_socket(host, 0, 0, R)
            cli2 = u32(R + 4)
            clear()
            tcp("start_connect", cli2, net, *a4(port, 127, 0, 0, 1), R)
            show("connect to a closed port", R, 2)
            if memory[R] == 0:
                settle("finish_connect", cli2)
            show("  finished", R, 8)
            clear()
            tcp("finish_connect", cli2, R)
            show("  and again", R, 8)
            sk.wasi_sockets_tcp_tcp_socket_drop(host, cli2)
            # UDP
            ids: list[int] = []
            for _ in range(3):
                clear()
                sk.wasi_sockets_udp_create_socket_create_udp_socket(host, 0, 0, R)
                ids.append(u32(R + 4))
            ua, ub, uc = ids
            clear()
            udp("stream", ua, 0, *a4(0, 0, 0, 0, 0), R)
            show("udp stream before bind", R, 8)
            ports: list[int] = []
            for h in ids:
                clear()
                udp("start_bind", h, net, *a4(0, 127, 0, 0, 1), R)
                clear()
                udp("finish_bind", h, R)
                clear()
                udp("local_address", h, R)
                ports.append(u16(R + 8))
            clear()
            udp("start_bind", ua, net, *a4(0, 127, 0, 0, 1), R)
            show("udp bind again", R, 2)
            clear()
            udp("finish_bind", ua, R)
            show("udp finish-bind again", R, 2)
            clear()
            udp("stream", ua, 0, *a4(0, 0, 0, 0, 0), R)
            show("stream a", R, 12)
            ain, aout = u32(R + 4), u32(R + 8)
            clear()
            udp("stream", ub, 1, *a4(ports[0], 127, 0, 0, 1), R)
            show("stream b to a", R, 12)
            bin_, bout = u32(R + 4), u32(R + 8)
            clear()
            udp("stream", uc, 0, *a4(0, 0, 0, 0, 0), R)
            cout_u = u32(R + 8)
            clear()
            udp("remote_address", ub, R)
            show("b remote", R, 1)
            pr(f"  is a: {int(u16(R + 8) == ports[0])}\n")
            clear()
            udp("remote_address", ua, R)
            show("a remote", R, 8)
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_check_send(host, 0, bout, R)
            show("check-send", R, 16)
            put_dgram(0, b"hello", False, 0)
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_send(host, 0, bout, 2200, 1, R)
            show("b sends to its peer", R, 16)
            receive_some("a receives", ain, ports[1])
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_check_send(host, 0, aout, R)
            put_dgram(0, b"back", True, ports[1])
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_send(host, 0, aout, 2200, 1, R)
            show("a sends to b", R, 16)
            receive_some("b receives", bin_, ports[0])
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_check_send(host, 0, bout, R)
            put_dgram(0, b"x", True, ports[0])
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_send(host, 0, bout, 2200, 1, R)
            show("b names its peer", R, 16)
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_check_send(host, 0, bout, R)
            put_dgram(0, b"x", True, ports[1])
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_send(host, 0, bout, 2200, 1, R)
            show("b names another peer", R, 16)
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_check_send(host, 0, aout, R)
            put_dgram(0, b"x", False, 0)
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_send(host, 0, aout, 2200, 1, R)
            show("a names no peer", R, 16)
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_check_send(host, 0, cout_u, R)
            put_dgram(0, b"stranger", True, ports[1])
            clear()
            sk.wasi_sockets_udp_outgoing_datagram_stream_send(host, 0, cout_u, 2200, 1, R)
            show("c sends to b", R, 16)
            for _ in range(20):
                time.sleep(0.001)
            receive_some("b receives from a stranger", bin_, 0, 3)
            clear()
            udp("set_unicast_hop_limit", ua, 0, R)
            show("udp hop-limit 0", R, 2)
            clear()
            udp("set_unicast_hop_limit", ua, 7, R)
            udp("unicast_hop_limit", ua, R + 24)
            show("udp hop-limit 7", R, 2)
            show("  value", R + 24, 2)
            clear()
            udp("set_send_buffer_size", ua, 0, R)
            show("udp send buffer 0", R, 2)
            sk.wasi_sockets_udp_incoming_datagram_stream_drop(host, ain)
            sk.wasi_sockets_udp_outgoing_datagram_stream_drop(host, aout)
            sk.wasi_sockets_udp_udp_socket_drop(host, ua)
            clear()
            udp("local_address", ub, R)
            show("b still bound", R, 1)
            # names
            for name in ("127.0.0.1", "::1", "", "bad name!", "localhost", "a%b"):
                raw = name.encode()
                memory[2000 : 2000 + len(raw)] = raw
                clear()
                sk.wasi_sockets_ip_name_lookup_resolve_addresses(host, 0, net, 2000, len(raw), R)
                pr(f"resolve [{name}] ")
                show("", R, 8)
                if memory[R] == 0:
                    rs = u32(R + 4)
                    pollable = sk.wasi_sockets_ip_name_lookup_resolve_address_stream_subscribe(host, rs)
                    pr(f"  stream pollable ready {io.wasi_io_poll_pollable_ready(host, pollable)}\n")
                    for k in range(8):
                        clear()
                        sk.wasi_sockets_ip_name_lookup_resolve_address_stream_resolve_next_address(host, 0, rs, R)
                        if not memory[R + 2]:
                            pr(f"  end after {k}\n")
                            break
                        show("  address", R + 4, 6 if memory[R + 4] == 0 else 18)
                    sk.wasi_sockets_ip_name_lookup_resolve_address_stream_drop(host, rs)
            e = io.error_new(host, "plain")
            clear()
            sk.wasi_sockets_network_network_error_code(host, 0, e, R)
            show("network-error-code of a plain error", R, 2)
            sk.wasi_sockets_network_network_drop(host, net)
        elif scenario == "reset":
            clear()
            sk.wasi_sockets_tcp_create_socket_create_tcp_socket(host, 0, 0, R)
            srv = u32(R + 4)
            clear()
            tcp("start_bind", srv, net, *a4(0, 127, 0, 0, 1), R)
            clear()
            tcp("finish_bind", srv, R)
            clear()
            tcp("start_listen", srv, R)
            clear()
            tcp("finish_listen", srv, R)
            clear()
            tcp("local_address", srv, R)
            port = u16(R + 8)
            clear()
            sk.wasi_sockets_tcp_create_socket_create_tcp_socket(host, 0, 0, R)
            cli = u32(R + 4)
            clear()
            tcp("start_connect", cli, net, *a4(port, 127, 0, 0, 1), R)
            settle("finish_connect", cli)
            cin = u32(R + 4)
            settle("accept", srv)
            conn = u32(R + 4)
            sock = cast(Any, table_get(host, conn, KIND_TCP_SOCKET)).sock
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            sk.wasi_sockets_tcp_tcp_socket_drop(host, conn)  # closing with linger 0 sends a reset
            read_some("read after a reset", cin)
            err = u32(R + 8)
            clear()
            sk.wasi_sockets_network_network_error_code(host, 0, err, R)
            show("network-error-code", R, 2)
            clear()
            io.wasi_io_error_error_to_debug_string(host, 0, err, R)
            pr(f"debug string is not empty: {int(u32(R + 4) > 0)}\n")
            read_some("and again", cin)
        elif scenario == "denied":
            clear()
            sk.wasi_sockets_tcp_create_socket_create_tcp_socket(host, 0, 0, R)
            t = u32(R + 4)
            clear()
            tcp("start_bind", t, net, *a4(0, 127, 0, 0, 1), R)
            show("tcp bind", R, 2)
            clear()
            tcp("start_connect", t, net, *a4(80, 127, 0, 0, 1), R)
            show("tcp connect", R, 2)
            clear()
            sk.wasi_sockets_udp_create_socket_create_udp_socket(host, 0, 0, R)
            u = u32(R + 4)
            clear()
            udp("start_bind", u, net, *a4(0, 127, 0, 0, 1), R)
            show("udp bind", R, 2)
            memory[2000:2009] = b"127.0.0.1"
            clear()
            sk.wasi_sockets_ip_name_lookup_resolve_addresses(host, 0, net, 2000, 9, R)
            show("resolve", R, 8)
        elif scenario == "udp_trap":
            clear()
            sk.wasi_sockets_udp_create_socket_create_udp_socket(host, 0, 0, R)
            u = u32(R + 4)
            clear()
            udp("start_bind", u, net, *a4(0, 127, 0, 0, 1), R)
            clear()
            udp("finish_bind", u, R)
            clear()
            udp("stream", u, 0, *a4(0, 0, 0, 0, 0), R)
            put_dgram(0, b"x", True, 9)
            sk.wasi_sockets_udp_outgoing_datagram_stream_send(host, 0, u32(R + 8), 2200, 1, R)
        elif scenario == "bad_handle":
            sk.wasi_sockets_tcp_tcp_socket_is_listening(host, 4242)
    except Trap:
        out.append("TRAP\n")
    return "".join(out)


def c_output(scenario: str, binary: Path) -> str:
    out = subprocess.run([str(binary), scenario], capture_output=True, text=True, check=True, timeout=120).stdout
    return "".join(("TRAP\n" if line.startswith("TRAP") else line + "\n") for line in out.splitlines())


@pytest.fixture(scope="module")
def driver(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if CC is None:
        pytest.skip("no C compiler")
    binary = tmp_path_factory.mktemp("p2sk") / "driver"
    subprocess.run(
        [CC, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-I", str(C_P2), str(DRIVER), "-o", str(binary)], check=True
    )
    return binary


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_c_and_python_agree(driver: Path, scenario: str) -> None:
    assert python_output(scenario) == c_output(scenario, driver)


def lines_of(scenario: str) -> list[str]:
    return python_output(scenario).splitlines()


def test_values() -> None:
    lines = lines_of("main")
    code = sk.NETWORK_ERRORS.index

    def err(label: str, at: int = 1) -> int:
        line = next(x for x in lines if x.startswith(f"{label}:"))
        data = bytes.fromhex(line.split(":", 1)[1])
        assert data[0] == 1, line
        return data[at]

    assert err("bind v6 on a v4 socket") == code("invalid-argument")
    assert err("bind multicast") == code("invalid-argument")
    assert err("local address before bind", 4) == code("invalid-state")
    assert err("finish-bind again") == code("not-in-progress")
    assert err("bind again") == code("invalid-state")
    assert err("accept with nothing waiting", 4) == code("would-block")
    assert err("idle 0") == code("invalid-argument")
    assert err("connect to 0.0.0.0") == code("invalid-argument")
    assert err("connect twice") == code("invalid-state")
    assert err("shutdown of a listener") == code("invalid-state")
    assert err("udp stream before bind", 4) == code("invalid-state")
    assert err("b names another peer", 8) == code("invalid-argument")
    assert "b names its peer:00000000000000000100000000000000" in lines  # the same peer is allowed
    assert err("a names no peer", 8) == code("invalid-argument")
    assert "listening 1" in lines and "listener:00" in lines and "  ip:7f000001" in lines
    assert "  remote port is the listener's: 1" in lines
    assert "listener pollable ready with a connection waiting 1" in lines
    assert "server reads data 70696e67" in lines and "client reads data 706f6e6721" in lines  # "ping", "pong!"
    assert "server reads after the shutdown stream-error tag 1" in lines  # closed
    assert err("  finished", 4) == code("connection-refused") or err("connect to a closed port") == code(
        "connection-refused"
    )
    assert "a receives 1 datagrams [68656c6c6f from tag 0 port-match 1]" in lines
    assert "b receives 1 datagrams [6261636b from tag 0 port-match 1]" in lines
    assert "b receives from a stranger 0 datagrams" in lines  # a datagram from another address is dropped
    assert "  address:00007f000001" in lines  # the name 127.0.0.1
    assert (
        sum(1 for x in lines if x.startswith("resolve [") and x.endswith(":0100000003000000")) == 3
    )  # "", "bad name!", "a%b"
    assert "  receive buffer > 0: 1" in lines and "  send buffer > 0: 1" in lines


def test_denied_by_default() -> None:
    lines = lines_of("denied")
    denied = f"{sk.NETWORK_ERRORS.index('access-denied'):02x}"
    for label in ("tcp bind", "tcp connect", "udp bind"):
        assert f"{label}:01{denied}" in lines, label
    assert next(x for x in lines if x.startswith("resolve:")).startswith(f"resolve:01000000{denied}")


def test_a_reset_is_a_network_error() -> None:
    lines = lines_of("reset")
    assert "read after a reset stream-error tag 0" in lines  # last-operation-failed
    assert f"network-error-code:01{sk.NETWORK_ERRORS.index('connection-reset'):02x}" in lines
    assert "debug string is not empty: 1" in lines
    assert "and again stream-error tag 1" in lines  # the stream is closed after the failure


def test_traps() -> None:
    assert lines_of("udp_trap")[-1] == "TRAP"  # send without check-send
    assert lines_of("bad_handle")[-1] == "TRAP"
