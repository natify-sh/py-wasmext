"""Runs a script of requests (script_http.txt) on the Python host of wasmext, and returns the lines that the guest of Wasmtime prints for the same script."""

from __future__ import annotations

from pathlib import Path

from wasmext.p2 import wasi_p2_http as H
from wasmext.p2 import wasi_p2_io as io
from wasmext.p2.wasi_p2_core import Host, load_u32, store_u32

R = 256
STD = ("GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH")


class Ours:
    def __init__(self) -> None:
        self.memory = bytearray(1 << 20)
        self.free, self.inp = 0x80000, 0x1000

        def bump(comp: int, old_ptr: int, old_size: int, align: int, new_size: int) -> int:
            ptr = (self.free + align - 1) // align * align
            self.free = ptr + new_size
            return ptr

        self.host = Host([self.memory], realloc=bump, http=True)

    def u32(self, off: int) -> int:
        return load_u32(self.host, 0, off)

    def put(self, data: bytes) -> int:
        ptr = self.inp
        self.memory[ptr : ptr + len(data)] = data
        self.inp = (ptr + len(data) + 8) // 8 * 8
        return ptr

    def clear(self) -> None:
        self.memory[R : R + 128] = bytes(128)

    def fields(self, items: list[tuple[str, bytes]]) -> int:
        spans = [(self.put(n.encode()), len(n), self.put(v), len(v)) for n, v in items]
        arr = self.put(bytes(16 * len(items)))
        for i, span in enumerate(spans):
            for k, x in enumerate(span):
                store_u32(self.host, 0, arr + 16 * i + 4 * k, x)
        self.clear()
        H.wasi_http_types_fields_from_list(self.host, 0, arr, len(items), R)
        assert self.memory[R] == 0
        return self.u32(R + 4)

    def entries(self, handle: int) -> str:
        self.clear()
        H.wasi_http_types_fields_entries(self.host, 0, handle, R)
        ptr, n = self.u32(R), self.u32(R + 4)
        out = []
        for i in range(n):
            e = ptr + 16 * i
            name = bytes(self.memory[self.u32(e) : self.u32(e) + self.u32(e + 4)]).decode()
            value = bytes(self.memory[self.u32(e + 8) : self.u32(e + 8) + self.u32(e + 12)]).decode("utf-8", "replace")
            if name not in ("date", "server"):
                out.append(f"{name}:{value}")
        return ",".join(sorted(out))

    def error(self, off: int) -> str:
        return "err=" + H.CASES[self.memory[off]][0].lower().replace("-", "")

    def request(self, t: list[str]) -> str:
        host = self.host
        headers: list[tuple[str, bytes]] = []
        trailers: list[tuple[str, bytes]] | None = None
        body = first = None
        for opt in t[4:]:
            if opt.startswith("body="):
                body = opt[5:].replace("\\n", "\n").encode()
            elif opt.startswith("h:"):
                k, _, v = opt[2:].partition("=")
                headers.append((k, v.encode()))
            elif opt.startswith("tr:"):
                k, _, v = opt[3:].partition("=")
                trailers = (trailers or []) + [(k, v.encode())]
            elif opt.startswith("first="):
                first = int(opt[6:])
        req = H.wasi_http_types_outgoing_request_new(host, self.fields(headers))
        method = t[1]
        if method in STD:
            args = (STD.index(method), 0, 0)
        else:
            args = (9, self.put(method.encode()), len(method))
        H.wasi_http_types_outgoing_request_set_method(host, 0, req, *args)
        H.wasi_http_types_outgoing_request_set_scheme(host, 0, req, 1, 0, 0, 0)
        H.wasi_http_types_outgoing_request_set_authority(host, 0, req, 1, self.put(t[2].encode()), len(t[2]))
        H.wasi_http_types_outgoing_request_set_path_with_query(host, 0, req, 1, self.put(t[3].encode()), len(t[3]))
        if body is not None or trailers is not None:
            self.clear()
            H.wasi_http_types_outgoing_request_body(host, 0, req, R)
            ob = self.u32(R + 4)
            if body is not None:
                self.clear()
                H.wasi_http_types_outgoing_body_write(host, 0, ob, R)
                stream = self.u32(R + 4)
                self.clear()
                io.wasi_io_streams_output_stream_blocking_write_and_flush(host, 0, stream, self.put(body), len(body), R)
                io.wasi_io_streams_output_stream_drop(host, stream)
            tf = self.fields(trailers) if trailers is not None else 0
            self.clear()
            H.wasi_http_types_outgoing_body_finish(host, 0, ob, int(trailers is not None), tf, R)
        opts = 0
        if first is not None:
            opts = H.wasi_http_types_request_options_new(host)
            H.wasi_http_types_request_options_set_first_byte_timeout(host, opts, 1, first * 1_000_000)
        self.clear()
        H.wasi_http_outgoing_handler_handle(host, 0, req, 1 if opts else 0, opts, R)
        if self.memory[R] == 1:
            return self.error(R + 8)
        fut = self.u32(R + 8)
        pol = H.wasi_http_types_future_incoming_response_subscribe(host, fut)
        io.wasi_io_poll_pollable_block(host, pol)
        self.clear()
        H.wasi_http_types_future_incoming_response_get(host, 0, fut, R)
        if self.memory[R + 16] == 1:
            return self.error(R + 24)
        resp = self.u32(R + 24)
        status = H.wasi_http_types_incoming_response_status(host, resp)
        h = self.entries(H.wasi_http_types_incoming_response_headers(host, resp))
        self.clear()
        H.wasi_http_types_incoming_response_consume(host, 0, resp, R)
        ib = self.u32(R + 4)
        self.clear()
        H.wasi_http_types_incoming_body_stream(host, 0, ib, R)
        stream = self.u32(R + 4)
        data = b""
        while True:
            self.clear()
            io.wasi_io_streams_input_stream_blocking_read(host, 0, stream, 4096, R)
            if self.memory[R] == 1:
                break
            data += bytes(self.memory[self.u32(R + 4) : self.u32(R + 4) + self.u32(R + 8)])
        io.wasi_io_streams_input_stream_drop(host, stream)
        ft = H.wasi_http_types_incoming_body_finish(host, ib)
        self.clear()
        H.wasi_http_types_future_trailers_get(host, 0, ft, R)
        tr = self.entries(self.u32(R + 28)) if self.memory[R + 24] == 1 else "none"
        return f"status={status} h=[{h}] body={data.hex()} trailers={tr}"


def run(script: Path) -> list[str]:
    ours = Ours()
    lines = []
    n = 0
    for line in script.read_text().splitlines():
        line = line.split("#~")[0].strip()
        if not line or line.startswith("#"):
            continue
        n += 1
        lines.append(f"{n} req: {ours.request(line.split())}")
    return lines
