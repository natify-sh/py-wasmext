"""The imports of the core modules of this package, by module: made by build_wasm.py, do not edit."""

IMPORTS: dict[str, list[str]] = {
    "wasi:cli/stderr@0.2.12": [
        "get-stderr",
    ],
    "wasi:cli/stdin@0.2.12": [
        "get-stdin",
    ],
    "wasi:cli/stdout@0.2.12": [
        "get-stdout",
    ],
    "wasi:cli/terminal-input@0.2.12": [
        "[resource-drop]terminal-input",
    ],
    "wasi:cli/terminal-output@0.2.12": [
        "[resource-drop]terminal-output",
    ],
    "wasi:cli/terminal-stderr@0.2.12": [
        "get-terminal-stderr",
    ],
    "wasi:cli/terminal-stdin@0.2.12": [
        "get-terminal-stdin",
    ],
    "wasi:cli/terminal-stdout@0.2.12": [
        "get-terminal-stdout",
    ],
    "wasi:clocks/monotonic-clock@0.2.12": [
        "now",
        "subscribe-duration",
    ],
    "wasi:clocks/wall-clock@0.2.12": [
        "now",
    ],
    "wasi:io/error@0.2.12": [
        "[resource-drop]error",
    ],
    "wasi:io/poll@0.2.12": [
        "[resource-drop]pollable",
        "[method]pollable.block",
        "poll",
    ],
    "wasi:io/streams@0.2.12": [
        "[resource-drop]input-stream",
        "[resource-drop]output-stream",
        "[method]output-stream.check-write",
        "[method]output-stream.write",
        "[method]output-stream.blocking-flush",
        "[method]output-stream.subscribe",
        "[method]input-stream.read",
        "[method]input-stream.subscribe",
    ],
    "wasi:sockets/instance-network@0.2.12": [
        "instance-network",
    ],
    "wasi:sockets/tcp-create-socket@0.2.12": [
        "create-tcp-socket",
    ],
    "wasi:sockets/tcp@0.2.12": [
        "[resource-drop]tcp-socket",
        "[method]tcp-socket.start-bind",
        "[method]tcp-socket.finish-bind",
        "[method]tcp-socket.start-connect",
        "[method]tcp-socket.finish-connect",
        "[method]tcp-socket.start-listen",
        "[method]tcp-socket.finish-listen",
        "[method]tcp-socket.accept",
        "[method]tcp-socket.local-address",
        "[method]tcp-socket.remote-address",
        "[method]tcp-socket.is-listening",
        "[method]tcp-socket.set-listen-backlog-size",
        "[method]tcp-socket.keep-alive-enabled",
        "[method]tcp-socket.set-keep-alive-enabled",
        "[method]tcp-socket.keep-alive-idle-time",
        "[method]tcp-socket.set-keep-alive-idle-time",
        "[method]tcp-socket.keep-alive-interval",
        "[method]tcp-socket.set-keep-alive-interval",
        "[method]tcp-socket.keep-alive-count",
        "[method]tcp-socket.set-keep-alive-count",
        "[method]tcp-socket.hop-limit",
        "[method]tcp-socket.set-hop-limit",
        "[method]tcp-socket.receive-buffer-size",
        "[method]tcp-socket.set-receive-buffer-size",
        "[method]tcp-socket.send-buffer-size",
        "[method]tcp-socket.set-send-buffer-size",
        "[method]tcp-socket.subscribe",
        "[method]tcp-socket.shutdown",
    ],
    "wasi:sockets/udp-create-socket@0.2.12": [
        "create-udp-socket",
    ],
    "wasi:sockets/udp@0.2.12": [
        "[resource-drop]udp-socket",
        "[resource-drop]incoming-datagram-stream",
        "[resource-drop]outgoing-datagram-stream",
        "[method]udp-socket.start-bind",
        "[method]udp-socket.finish-bind",
        "[method]udp-socket.stream",
        "[method]udp-socket.local-address",
        "[method]udp-socket.remote-address",
        "[method]udp-socket.unicast-hop-limit",
        "[method]udp-socket.set-unicast-hop-limit",
        "[method]udp-socket.receive-buffer-size",
        "[method]udp-socket.set-receive-buffer-size",
        "[method]udp-socket.send-buffer-size",
        "[method]udp-socket.set-send-buffer-size",
        "[method]udp-socket.subscribe",
        "[method]incoming-datagram-stream.receive",
        "[method]incoming-datagram-stream.subscribe",
        "[method]outgoing-datagram-stream.check-send",
        "[method]outgoing-datagram-stream.send",
        "[method]outgoing-datagram-stream.subscribe",
    ],
}
