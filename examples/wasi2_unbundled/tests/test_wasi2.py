from __future__ import annotations

import socket
import threading
from io import BytesIO

import pytest
from wasi2demo import Host, _hello, _sock, run


def test_a_program_prints_through_the_streams_of_the_host() -> None:
    out = BytesIO()
    assert run(_hello, Host(stdout=out)) == 1  # main returned 3: the err of the result of run
    assert out.getvalue() == b"hello from wasip2\n"


def test_a_program_talks_to_a_tcp_server_through_the_host() -> None:
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]
    received: list[bytes] = []

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            received.append(connection.recv(64))
            connection.sendall(b"pong")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    out = BytesIO()
    # the program connects to 127.0.0.1:47123 (the port in sock.c): the host sends it to the port of the server
    host = Host(stdout=out, remap={("127.0.0.1", 47123): ("127.0.0.1", port)})
    try:
        assert run(_sock, host) == 0
    finally:
        thread.join(5)
        server.close()
    assert received == [b"ping"]
    assert out.getvalue() == b"reply: pong\n"


def test_an_import_that_is_not_written_raises_when_it_is_called() -> None:
    imports = Host().imports()
    assert set(imports["wasi:sockets/udp@0.2.12"]) >= {"[method]udp-socket.start-bind"}
    with pytest.raises(NotImplementedError, match="udp-socket.start-bind"):
        imports["wasi:sockets/udp@0.2.12"]["[method]udp-socket.start-bind"](*range(15))
