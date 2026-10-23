"""wasi:http (63 imports): `types` (62) and `outgoing-handler` (1) (the twin of `c/p2/wasi_p2_http.h`). `incoming-handler` is an export of a component, not an import.

**An outgoing request is refused (`HTTP-request-denied`) unless the caller says so**: `Host(http=True)` allows all, `Host(http_check=f)` decides for each one (`f("https", "example.com:443")`),
`Host(http_send=g)` replaces the transport (`g(HttpRequest) -> HttpResponse`, a failure is a raised `ErrorCode`). The transport of the host is a small HTTP/1.1 client over a socket
(`Connection: close`), the same in the C twin, except that only Python has TLS (`ssl`); in C `https` is `internal-error` unless `http_send` is set. What a guest sees is shaped by these choices:

* the answer is read whole before the guest sees it (a body is a stream over bytes in memory, at most `MAX_BODY`; the end is `closed`, and `http-error-code` is `none`: a stream of a body never fails);
* a request is sent when the guest first asks for the answer (`get`, `ready` or `block` of the future), after the body is finished; a future dropped before that sends nothing;
* the body of a request is collected and sent with `Content-Length` (with `Transfer-Encoding: chunked` if trailers are given); if the guest set `content-length`, a body of another size is `HTTP-request-body-size`;
* names of fields are kept in lower case; `connection`, `keep-alive`, `proxy-connection`, `transfer-encoding`, `upgrade`, `host`, `http2-settings` and `te` are `forbidden`; the headers of a request, a response or an incoming
  message are `immutable`; the order of checks is immutable, invalid-syntax, forbidden;
* the timeouts of `request-options` default to 600 s (as in Wasmtime): connect → `connection-timeout`, first byte and between bytes → `connection-read-timeout`;
* an unset `scheme` is `https`; an unset `path-with-query` is `/`; an unset `authority` is `HTTP-request-URI-invalid`.

The server side (a component that exports `incoming-handler`) is made of the embedder: `incoming_request_new` gives the guest a request and `response_outparam_new` the place where it puts its answer.

Layouts (Canonical ABI): `method` 12 bytes (tag at 0, string at 4), `scheme` the same, `option<scheme>` 16 bytes (tag 0, scheme at 4), `option<string>` 12 bytes. `error-code` is 32 bytes aligned to 8:
the tag at 0 and the payload at 8 (see `CASES`: each payload is one or two options of a number or a string, and `HTTP-request-header-size` has them in an option of a record). `result<T, error-code>` is 8 + 32
(the tag at 0, T or the error at 8); `result<_, header-error>`: tag 0, error 1; `result<own T>`: tag 0, handle 4. The answer of `future-incoming-response.get` (`option<result<result<T, error-code>>>`)
is 56 bytes: option tag 0, tag of the outer result 8, tag of the inner 16, handle 24 or error-code 24.
"""

from __future__ import annotations

import errno
import re
import socket
import ssl
from collections.abc import Sequence
from dataclasses import dataclass

from .wasi_p2_core import (
    KIND_ERROR,
    KIND_FIELDS,
    KIND_FUTURE_INCOMING_RESPONSE,
    KIND_FUTURE_TRAILERS,
    KIND_INCOMING_BODY,
    KIND_INCOMING_REQUEST,
    KIND_INCOMING_RESPONSE,
    KIND_OUTGOING_BODY,
    KIND_OUTGOING_REQUEST,
    KIND_OUTGOING_RESPONSE,
    KIND_OUTPUT_STREAM,
    KIND_POLLABLE,
    KIND_REQUEST_OPTIONS,
    KIND_RESPONSE_OUTPARAM,
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
    table_alive,
    table_drop,
    table_get,
    table_new,
)
from .wasi_p2_io import BufferOutput, MemoryInput, input_stream_new, output_stream_new

MAX_BODY = 1 << 28  # the most a body of a request or of an answer can have
MAX_HEAD = 65536  # the most the head of an answer can have
DEFAULT_TIMEOUT_NS = 600 * 1_000_000_000

# the error-code: (name, payload is in an option, kinds of the leaves); a leaf is an option of "n8", "n16", "n32", "n64" or a "str"
CASES: tuple[tuple[str, bool, tuple[str, ...]], ...] = (
    ("DNS-timeout", False, ()),
    ("DNS-error", False, ("str", "n16")),
    ("destination-not-found", False, ()),
    ("destination-unavailable", False, ()),
    ("destination-IP-prohibited", False, ()),
    ("destination-IP-unroutable", False, ()),
    ("connection-refused", False, ()),
    ("connection-terminated", False, ()),
    ("connection-timeout", False, ()),
    ("connection-read-timeout", False, ()),
    ("connection-write-timeout", False, ()),
    ("connection-limit-reached", False, ()),
    ("TLS-protocol-error", False, ()),
    ("TLS-certificate-error", False, ()),
    ("TLS-alert-received", False, ("n8", "str")),
    ("HTTP-request-denied", False, ()),
    ("HTTP-request-length-required", False, ()),
    ("HTTP-request-body-size", False, ("n64",)),
    ("HTTP-request-method-invalid", False, ()),
    ("HTTP-request-URI-invalid", False, ()),
    ("HTTP-request-URI-too-long", False, ()),
    ("HTTP-request-header-section-size", False, ("n32",)),
    ("HTTP-request-header-size", True, ("str", "n32")),
    ("HTTP-request-trailer-section-size", False, ("n32",)),
    ("HTTP-request-trailer-size", False, ("str", "n32")),
    ("HTTP-response-incomplete", False, ()),
    ("HTTP-response-header-section-size", False, ("n32",)),
    ("HTTP-response-header-size", False, ("str", "n32")),
    ("HTTP-response-body-size", False, ("n64",)),
    ("HTTP-response-trailer-section-size", False, ("n32",)),
    ("HTTP-response-trailer-size", False, ("str", "n32")),
    ("HTTP-response-transfer-coding", False, ("str",)),
    ("HTTP-response-content-coding", False, ("str",)),
    ("HTTP-response-timeout", False, ()),
    ("HTTP-upgrade-failed", False, ()),
    ("HTTP-protocol-error", False, ()),
    ("loop-detected", False, ()),
    ("configuration-error", False, ()),
    ("internal-error", False, ("str",)),
)
_CASE_INDEX = {c[0]: i for i, c in enumerate(CASES)}
_LEAF = {
    "n8": (2, 1),
    "n16": (4, 2),
    "n32": (8, 4),
    "n64": (16, 8),
    "str": (12, 4),
}  # size and alignment of an option of it

STD_METHODS = ("GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH")
FORBIDDEN = frozenset(
    {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "upgrade", "host", "http2-settings", "te"}
)
_TOKEN = re.compile(rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*")
INVALID_SYNTAX, FORBIDDEN_HEADER, IMMUTABLE = 0, 1, 2  # header-error


class ErrorCode(Exception):
    """A `wasi:http/types.error-code`: `ErrorCode("connection-refused")`, `ErrorCode("internal-error", "message")`, `ErrorCode("DNS-error", "NXDOMAIN", None)`.

    `values` has one item for each leaf of the payload: None (the option is none), an int or a str. `present` is for `HTTP-request-header-size`, whose payload is in an option.
    """

    def __init__(self, name: str, *values: int | str | None, present: bool = True) -> None:
        if name not in _CASE_INDEX:
            raise ValueError(f"no error-code {name}")
        kinds = CASES[_CASE_INDEX[name]][2]
        if len(values) > len(kinds):
            raise ValueError(f"{name} has {len(kinds)} values")
        self.name = name
        self.values = tuple(values) + (None,) * (len(kinds) - len(values))
        self.present = present
        super().__init__(name, *self.values)

    @property
    def tag(self) -> int:
        return _CASE_INDEX[self.name]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ErrorCode) and (self.name, self.values, self.present) == (
            other.name,
            other.values,
            other.present,
        )

    def __hash__(self) -> int:
        return hash((self.name, self.values, self.present))

    def __repr__(self) -> str:
        return f"ErrorCode({self.name!r}{''.join(', ' + repr(v) for v in self.values)})"


def _offsets(outer: bool, kinds: tuple[str, ...]) -> list[int]:
    """Where the leaves are, from the start of the payload."""
    pos = 0
    if outer:
        align = max(_LEAF[k][1] for k in kinds)
        pos = (1 + align - 1) // align * align
    offs: list[int] = []
    for k in kinds:
        size, align = _LEAF[k]
        pos = (pos + align - 1) // align * align
        offs.append(pos)
        pos += size
    return offs


def _store_string(host: Host, comp: int, at: int, text: str | bytes) -> None:
    data = text.encode() if isinstance(text, str) else text
    ptr = alloc(host, comp, 1, len(data))
    store_bytes(host, comp, ptr, data)
    store_u32(host, comp, at, ptr)
    store_u32(host, comp, at + 4, len(data))


def _store_opt_string(host: Host, comp: int, at: int, text: str | None) -> None:
    store_u8(host, comp, at, 0 if text is None else 1)
    if text is not None:
        _store_string(host, comp, at + 4, text)


def store_error_code(host: Host, comp: int, ptr: int, ec: ErrorCode) -> None:
    """Writes an `error-code` (32 bytes) at `ptr`."""
    _, outer, kinds = CASES[_CASE_INDEX[ec.name]]
    store_u8(host, comp, ptr, _CASE_INDEX[ec.name])
    base = ptr + 8
    if outer:
        store_u8(host, comp, base, 1 if ec.present else 0)
        if not ec.present:
            return
    for kind, off, value in zip(kinds, _offsets(outer, kinds), ec.values, strict=True):
        at = base + off
        if kind == "str":
            _store_opt_string(host, comp, at, None if value is None else str(value))
            continue
        store_u8(host, comp, at, 0 if value is None else 1)
        if value is not None:
            width = {"n8": 1, "n16": 2, "n32": 4, "n64": 8}[kind]
            data = int(value).to_bytes(width, "little")
            store_bytes(
                host, comp, at + _LEAF[kind][1], data
            )  # the value follows the tag, at the alignment of the number


def lift_error_code_flat(host: Host, comp: int, flat: Sequence[int]) -> ErrorCode:
    """An `error-code` that came as flat arguments: the tag, then the numbers of the payload (a string is a pointer and a length)."""
    tag = flat[0] & 0xFF if flat[0] < 256 else -1
    if not 0 <= tag < len(CASES):
        raise Trap(f"bad error-code {flat[0]}")
    name, outer, kinds = CASES[tag]
    pos = 1
    present = True
    if outer:
        present = bool(flat[pos] & 0xFF)
        pos += 1
    values: list[int | str | None] = []
    for kind in kinds:
        if not present:
            values.append(None)
            continue
        has = flat[pos] & 0xFF
        if kind == "str":
            ptr, n = flat[pos + 1] & 0xFFFFFFFF, flat[pos + 2] & 0xFFFFFFFF
            values.append(load_bytes(host, comp, ptr, n).decode("utf-8", "replace") if has else None)
            pos += 3
        else:
            width = {"n8": 8, "n16": 16, "n32": 32, "n64": 64}[kind]
            values.append(flat[pos + 1] & ((1 << width) - 1) if has else None)
            pos += 2
    return ErrorCode(name, *values, present=present)


# fields


class Fields:
    """The `fields` resource: names in lower case, values as bytes; `immutable` once something owns them."""

    def __init__(self, entries: Sequence[tuple[str, bytes]] = (), immutable: bool = False) -> None:
        self.entries: list[tuple[str, bytes]] = list(entries)
        self.immutable = immutable

    def get(self, name: str) -> list[bytes]:
        name = name.lower()
        return [v for n, v in self.entries if n == name]


def _check_entry(name: bytes, value: bytes) -> int | None:
    """None if (name, value) may be a field, else the header-error."""
    if not _TOKEN.fullmatch(name) or any(c in (0, 10, 13) or (c < 32 and c != 9) or c == 127 for c in value):
        return INVALID_SYNTAX
    if name.decode().lower() in FORBIDDEN:
        return FORBIDDEN_HEADER
    return None


def fields_new(host: Host, entries: Sequence[tuple[str, bytes]] = (), immutable: bool = False) -> int:
    return table_new(host, KIND_FIELDS, Fields([(n.lower(), v) for n, v in entries], immutable))


def _fields(host: Host, handle: int) -> Fields:
    return table_get(host, handle, KIND_FIELDS)  # type: ignore[return-value]


def _take_fields(host: Host, handle: int) -> Fields:
    """An own `fields` given to a request, a response or a body: the handle is spent, the fields are not to be changed any more."""
    f = _fields(host, handle)
    table_drop(host, handle, KIND_FIELDS)
    f.immutable = True
    return f


def _load_list_pairs(host: Host, comp: int, ptr: int, n: int) -> list[tuple[bytes, bytes]]:
    out: list[tuple[bytes, bytes]] = []
    for i in range(n):
        at = ptr + 16 * i
        name = load_bytes(host, comp, load_u32(host, comp, at), load_u32(host, comp, at + 4))
        value = load_bytes(host, comp, load_u32(host, comp, at + 8), load_u32(host, comp, at + 12))
        out.append((name, value))
    return out


def _store_pairs(host: Host, comp: int, entries: Sequence[tuple[str, bytes]], retptr: int) -> None:
    ptr = alloc(host, comp, 4, 16 * len(entries))
    for i, (name, value) in enumerate(entries):
        at = ptr + 16 * i
        _store_string(host, comp, at, name)
        _store_string(host, comp, at + 8, value)
    store_u32(host, comp, retptr, ptr)
    store_u32(host, comp, retptr + 4, len(entries))


def wasi_http_types_fields_new(host: Host) -> int:
    return fields_new(host)


def wasi_http_types_fields_from_list(host: Host, comp: int, ptr: int, len: int, retptr: int) -> None:
    pairs = _load_list_pairs(host, comp, ptr, len)
    for name, value in pairs:
        err = _check_entry(name, value)
        if err is not None:
            store_u8(host, comp, retptr, 1)
            store_u8(host, comp, retptr + 4, err)
            return
    store_u8(host, comp, retptr, 0)
    store_u32(host, comp, retptr + 4, fields_new(host, [(n.decode(), v) for n, v in pairs]))


def wasi_http_types_fields_get(host: Host, comp: int, self: int, name_ptr: int, name_len: int, retptr: int) -> None:
    values = _fields(host, self).get(load_bytes(host, comp, name_ptr, name_len).decode("latin-1"))
    ptr = alloc(host, comp, 4, 8 * len(values))
    for i, value in enumerate(values):
        _store_string(host, comp, ptr + 8 * i, value)
    store_u32(host, comp, retptr, ptr)
    store_u32(host, comp, retptr + 4, len(values))


def wasi_http_types_fields_has(host: Host, comp: int, self: int, name_ptr: int, name_len: int) -> int:
    return int(bool(_fields(host, self).get(load_bytes(host, comp, name_ptr, name_len).decode("latin-1"))))


def _header_result(host: Host, comp: int, retptr: int, err: int | None) -> None:
    store_u8(host, comp, retptr, 0 if err is None else 1)
    if err is not None:
        store_u8(host, comp, retptr + 1, err)


def _change(f: Fields, name: bytes, values: Sequence[bytes], replace: bool) -> int | None:
    if f.immutable:
        return IMMUTABLE
    for value in values or [b""]:
        err = _check_entry(name, value)
        if err is not None:
            return err
    key = name.decode().lower()
    if replace:
        f.entries = [e for e in f.entries if e[0] != key]
    f.entries += [(key, v) for v in values]
    return None


def wasi_http_types_fields_set(
    host: Host, comp: int, self: int, name_ptr: int, name_len: int, value_ptr: int, value_len: int, retptr: int
) -> None:
    values = [
        load_bytes(host, comp, load_u32(host, comp, value_ptr + 8 * i), load_u32(host, comp, value_ptr + 8 * i + 4))
        for i in range(value_len)
    ]
    err = _change(_fields(host, self), load_bytes(host, comp, name_ptr, name_len), values, True)
    _header_result(host, comp, retptr, err)


def wasi_http_types_fields_delete(host: Host, comp: int, self: int, name_ptr: int, name_len: int, retptr: int) -> None:
    err = _change(_fields(host, self), load_bytes(host, comp, name_ptr, name_len), [], True)
    _header_result(host, comp, retptr, err)


def wasi_http_types_fields_append(
    host: Host, comp: int, self: int, name_ptr: int, name_len: int, value_ptr: int, value_len: int, retptr: int
) -> None:
    value = load_bytes(host, comp, value_ptr, value_len)
    err = _change(_fields(host, self), load_bytes(host, comp, name_ptr, name_len), [value], False)
    _header_result(host, comp, retptr, err)


def wasi_http_types_fields_entries(host: Host, comp: int, self: int, retptr: int) -> None:
    _store_pairs(host, comp, _fields(host, self).entries, retptr)


def wasi_http_types_fields_clone(host: Host, self: int) -> int:
    return table_new(host, KIND_FIELDS, Fields(_fields(host, self).entries))


def wasi_http_types_fields_drop(host: Host, handle: int) -> None:
    _fields(host, handle)
    table_drop(host, handle, KIND_FIELDS)


# method, scheme, authority, path


def _lift_method(host: Host, comp: int, tag: int, ptr: int, n: int) -> str:
    if tag < 9:
        return STD_METHODS[tag]
    if tag > 9:
        raise Trap(f"bad method {tag}")
    return load_bytes(host, comp, ptr, n).decode("latin-1")


def _lift_scheme(host: Host, comp: int, tag: int, ptr: int, n: int) -> str:
    if tag < 2:
        return ("http", "https")[tag]
    if tag > 2:
        raise Trap(f"bad scheme {tag}")
    return load_bytes(host, comp, ptr, n).decode("latin-1")


def _store_method(host: Host, comp: int, at: int, method: str) -> None:
    if method in STD_METHODS:
        store_u8(host, comp, at, STD_METHODS.index(method))
    else:
        store_u8(host, comp, at, 9)
        _store_string(host, comp, at + 4, method)


def _store_scheme(host: Host, comp: int, at: int, scheme: str) -> None:
    if scheme in ("http", "https"):
        store_u8(host, comp, at, ("http", "https").index(scheme))
    else:
        store_u8(host, comp, at, 2)
        _store_string(host, comp, at + 4, scheme)


def _valid_path(path: str) -> bool:
    return (path.startswith("/") or path == "*") and all(32 < ord(c) < 127 for c in path)


def split_authority(authority: str, default_port: int) -> tuple[str, int] | None:
    """(host, port) of `host`, `host:port` or `[v6]:port`; None if it is not an authority."""
    if not authority or any(c in " /@?#\\" or ord(c) < 32 or ord(c) > 126 for c in authority):
        return None
    if authority.startswith("["):
        end = authority.find("]")
        if end < 0:
            return None
        host, rest = authority[1:end], authority[end + 1 :]
        if rest and not rest.startswith(":"):
            return None
        port_text = rest[1:] if rest else ""
    else:
        host, _, port_text = authority.partition(":")
        if ":" in port_text:
            return None
    if not host:
        return None
    if not port_text and (authority.endswith((":", "]:"))):
        return None
    if port_text:
        if not port_text.isdigit() or not 0 < int(port_text) < 65536:
            return None
        return host, int(port_text)
    return host, default_port


class OutgoingBody:
    def __init__(self, expected: int | None, kind: str) -> None:
        self.stream = BufferOutput(limit=MAX_BODY)
        self.stream_handle: int | None = None
        self.expected = expected  # the content-length the guest declared
        self.kind = kind  # "request" or "response"
        self.trailers: Fields | None = None
        self.finished = False
        self.abandoned = False

    def data(self) -> bytes:
        return bytes(self.stream.data)


def _declared_length(headers: Fields) -> int | None:
    for value in headers.get("content-length"):
        if value.isdigit():
            return int(value)
    return None


class OutgoingRequest:
    def __init__(self, headers: Fields) -> None:
        self.headers = headers
        self.method = "GET"
        self.path: str | None = None
        self.scheme: str | None = None
        self.authority: str | None = None
        self.body: OutgoingBody | None = None


class RequestOptions:
    def __init__(self) -> None:
        self.connect: int | None = None
        self.first_byte: int | None = None
        self.between_bytes: int | None = None


def _request(host: Host, handle: int) -> OutgoingRequest:
    return table_get(host, handle, KIND_OUTGOING_REQUEST)  # type: ignore[return-value]


def wasi_http_types_outgoing_request_new(host: Host, headers: int) -> int:
    return table_new(host, KIND_OUTGOING_REQUEST, OutgoingRequest(_take_fields(host, headers)))


def _new_body(
    host: Host, comp: int, owner_headers: Fields, kind: str, slot: OutgoingBody | None, retptr: int
) -> OutgoingBody | None:
    if slot is not None:
        store_u8(host, comp, retptr, 1)
        return None
    body = OutgoingBody(_declared_length(owner_headers), kind)
    store_u8(host, comp, retptr, 0)
    store_u32(host, comp, retptr + 4, table_new(host, KIND_OUTGOING_BODY, body))
    return body


def wasi_http_types_outgoing_request_body(host: Host, comp: int, self: int, retptr: int) -> None:
    req = _request(host, self)
    body = _new_body(host, comp, req.headers, "request", req.body, retptr)
    if body is not None:
        req.body = body


def wasi_http_types_outgoing_request_method(host: Host, comp: int, self: int, retptr: int) -> None:
    _store_method(host, comp, retptr, _request(host, self).method)


def wasi_http_types_outgoing_request_set_method(host: Host, comp: int, self: int, tag: int, ptr: int, len: int) -> int:
    method = _lift_method(host, comp, tag, ptr, len)
    if not _TOKEN.fullmatch(method.encode("latin-1")):
        return 1
    _request(host, self).method = method
    return 0


def _store_opt_text(host: Host, comp: int, retptr: int, text: str | None) -> None:
    _store_opt_string(host, comp, retptr, text)


def wasi_http_types_outgoing_request_path_with_query(host: Host, comp: int, self: int, retptr: int) -> None:
    _store_opt_text(host, comp, retptr, _request(host, self).path)


def wasi_http_types_outgoing_request_set_path_with_query(
    host: Host, comp: int, self: int, tag: int, ptr: int, len: int
) -> int:
    req = _request(host, self)
    path = load_bytes(host, comp, ptr, len).decode("latin-1") if tag else None
    if path is not None and not _valid_path(path):
        return 1
    req.path = path
    return 0


def wasi_http_types_outgoing_request_scheme(host: Host, comp: int, self: int, retptr: int) -> None:
    scheme = _request(host, self).scheme
    store_u8(host, comp, retptr, 0 if scheme is None else 1)
    if scheme is not None:
        _store_scheme(host, comp, retptr + 4, scheme)


def wasi_http_types_outgoing_request_set_scheme(
    host: Host, comp: int, self: int, tag: int, scheme_tag: int, ptr: int, len: int
) -> int:
    req = _request(host, self)
    scheme = _lift_scheme(host, comp, scheme_tag, ptr, len) if tag else None
    if scheme is not None and not _SCHEME.fullmatch(scheme):
        return 1
    req.scheme = scheme
    return 0


def wasi_http_types_outgoing_request_authority(host: Host, comp: int, self: int, retptr: int) -> None:
    _store_opt_text(host, comp, retptr, _request(host, self).authority)


def wasi_http_types_outgoing_request_set_authority(
    host: Host, comp: int, self: int, tag: int, ptr: int, len: int
) -> int:
    req = _request(host, self)
    authority = load_bytes(host, comp, ptr, len).decode("latin-1") if tag else None
    if authority is not None and split_authority(authority, 80) is None:
        return 1
    req.authority = authority
    return 0


def wasi_http_types_outgoing_request_headers(host: Host, self: int) -> int:
    return table_new(host, KIND_FIELDS, _request(host, self).headers)


def wasi_http_types_outgoing_request_drop(host: Host, handle: int) -> None:
    _request(host, handle)
    table_drop(host, handle, KIND_OUTGOING_REQUEST)


# request-options


def _options(host: Host, handle: int) -> RequestOptions:
    return table_get(host, handle, KIND_REQUEST_OPTIONS)  # type: ignore[return-value]


def wasi_http_types_request_options_new(host: Host) -> int:
    return table_new(host, KIND_REQUEST_OPTIONS, RequestOptions())


def _get_timeout(host: Host, comp: int, value: int | None, retptr: int) -> None:
    store_u8(host, comp, retptr, 0 if value is None else 1)
    if value is not None:
        store_u64(host, comp, retptr + 8, value)


def wasi_http_types_request_options_connect_timeout(host: Host, comp: int, self: int, retptr: int) -> None:
    _get_timeout(host, comp, _options(host, self).connect, retptr)


def wasi_http_types_request_options_set_connect_timeout(host: Host, self: int, tag: int, value: int) -> int:
    _options(host, self).connect = (value & 0xFFFFFFFFFFFFFFFF) if tag else None
    return 0


def wasi_http_types_request_options_first_byte_timeout(host: Host, comp: int, self: int, retptr: int) -> None:
    _get_timeout(host, comp, _options(host, self).first_byte, retptr)


def wasi_http_types_request_options_set_first_byte_timeout(host: Host, self: int, tag: int, value: int) -> int:
    _options(host, self).first_byte = (value & 0xFFFFFFFFFFFFFFFF) if tag else None
    return 0


def wasi_http_types_request_options_between_bytes_timeout(host: Host, comp: int, self: int, retptr: int) -> None:
    _get_timeout(host, comp, _options(host, self).between_bytes, retptr)


def wasi_http_types_request_options_set_between_bytes_timeout(host: Host, self: int, tag: int, value: int) -> int:
    _options(host, self).between_bytes = (value & 0xFFFFFFFFFFFFFFFF) if tag else None
    return 0


def wasi_http_types_request_options_drop(host: Host, handle: int) -> None:
    _options(host, handle)
    table_drop(host, handle, KIND_REQUEST_OPTIONS)


# bodies


class IncomingBody:
    def __init__(self, data: bytes, trailers: Fields | None) -> None:
        self.data = data
        self.trailers = trailers
        self.stream_handle: int | None = None
        self.stream_taken = False


class ReadyPollable(Pollable):
    def ready(self, host: Host) -> bool:
        return True


def _incoming_body(host: Host, handle: int) -> IncomingBody:
    return table_get(host, handle, KIND_INCOMING_BODY)  # type: ignore[return-value]


def _outgoing_body(host: Host, handle: int) -> OutgoingBody:
    return table_get(host, handle, KIND_OUTGOING_BODY)  # type: ignore[return-value]


def _consume(
    host: Host, comp: int, data: tuple[bytes, Fields | None] | None, retptr: int
) -> tuple[bytes, Fields | None] | None:
    """`result<incoming-body>`: the body once, then err."""
    if data is None:
        store_u8(host, comp, retptr, 1)
        return None
    store_u8(host, comp, retptr, 0)
    store_u32(host, comp, retptr + 4, table_new(host, KIND_INCOMING_BODY, IncomingBody(*data)))
    return data


def wasi_http_types_incoming_body_stream(host: Host, comp: int, self: int, retptr: int) -> None:
    body = _incoming_body(host, self)
    if body.stream_taken:
        store_u8(host, comp, retptr, 1)
        return
    body.stream_taken = True
    body.stream_handle = input_stream_new(host, MemoryInput(body.data))
    store_u8(host, comp, retptr, 0)
    store_u32(host, comp, retptr + 4, body.stream_handle)


class FutureTrailers:
    def __init__(self, trailers: Fields | None) -> None:
        self.trailers = trailers
        self.taken = False


def wasi_http_types_incoming_body_finish(host: Host, this: int) -> int:
    body = _incoming_body(host, this)
    if body.stream_handle is not None and table_alive(host, body.stream_handle, 3):  # KIND_INPUT_STREAM
        raise Trap("incoming-body.finish with its stream alive")
    table_drop(host, this, KIND_INCOMING_BODY)
    return table_new(host, KIND_FUTURE_TRAILERS, FutureTrailers(body.trailers))


def wasi_http_types_incoming_body_drop(host: Host, handle: int) -> None:
    _incoming_body(host, handle)
    table_drop(host, handle, KIND_INCOMING_BODY)


def _future_trailers(host: Host, handle: int) -> FutureTrailers:
    return table_get(host, handle, KIND_FUTURE_TRAILERS)  # type: ignore[return-value]


def wasi_http_types_future_trailers_subscribe(host: Host, self: int) -> int:
    _future_trailers(host, self)
    return table_new(host, KIND_POLLABLE, ReadyPollable())


def wasi_http_types_future_trailers_get(host: Host, comp: int, self: int, retptr: int) -> None:
    future = _future_trailers(host, self)
    store_u8(host, comp, retptr, 1)
    if future.taken:
        store_u8(host, comp, retptr + 8, 1)  # err: it was already taken
        return
    future.taken = True
    store_u8(host, comp, retptr + 8, 0)
    store_u8(host, comp, retptr + 16, 0)  # ok: no error-code
    if future.trailers is None:
        store_u8(host, comp, retptr + 24, 0)
    else:
        store_u8(host, comp, retptr + 24, 1)
        store_u32(host, comp, retptr + 28, table_new(host, KIND_FIELDS, future.trailers))


def wasi_http_types_future_trailers_drop(host: Host, handle: int) -> None:
    _future_trailers(host, handle)
    table_drop(host, handle, KIND_FUTURE_TRAILERS)


def wasi_http_types_outgoing_body_write(host: Host, comp: int, self: int, retptr: int) -> None:
    body = _outgoing_body(host, self)
    if body.stream_handle is not None:
        store_u8(host, comp, retptr, 1)
        return
    body.stream_handle = output_stream_new(host, body.stream)
    store_u8(host, comp, retptr, 0)
    store_u32(host, comp, retptr + 4, body.stream_handle)


def wasi_http_types_outgoing_body_finish(
    host: Host, comp: int, this: int, tag: int, trailers: int, retptr: int
) -> None:
    body = _outgoing_body(host, this)
    if body.stream_handle is not None and table_alive(host, body.stream_handle, KIND_OUTPUT_STREAM):
        raise Trap("outgoing-body.finish with its stream alive")
    if tag:
        body.trailers = _take_fields(host, trailers)
    table_drop(host, this, KIND_OUTGOING_BODY)
    size = len(body.stream.data)
    if body.expected is not None and body.expected != size:
        store_u8(host, comp, retptr, 1)
        store_error_code(host, comp, retptr + 8, ErrorCode(f"HTTP-{body.kind}-body-size", size))
        body.abandoned = True
        return
    body.finished = True
    store_u8(host, comp, retptr, 0)


def wasi_http_types_outgoing_body_drop(host: Host, handle: int) -> None:
    body = _outgoing_body(host, handle)
    table_drop(host, handle, KIND_OUTGOING_BODY)
    if not body.finished:
        body.abandoned = True


# the transport


@dataclass
class HttpRequest:
    method: str
    scheme: str  # "http" or "https"
    authority: str
    path: str
    headers: list[tuple[str, bytes]]
    body: bytes = b""
    trailers: list[tuple[str, bytes]] | None = None
    connect_ns: int | None = None
    first_byte_ns: int | None = None
    between_bytes_ns: int | None = None


@dataclass
class HttpResponse:
    status: int
    headers: list[tuple[str, bytes]]
    body: bytes = b""
    trailers: list[tuple[str, bytes]] | None = None


def _seconds(ns: int | None) -> float:
    return max((DEFAULT_TIMEOUT_NS if ns is None else ns) / 1e9, 1e-6)  # 0 would be a socket that does not wait at all


def _dns_error(e: socket.gaierror) -> ErrorCode:
    if e.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)):
        return ErrorCode("DNS-error", "NXDOMAIN", None)
    if e.errno == socket.EAI_AGAIN:
        return ErrorCode("DNS-error", "SERVFAIL", None)
    return ErrorCode("DNS-error", str(e.args[1]) if len(e.args) > 1 else "failed", None)


def _connect_error(e: OSError) -> ErrorCode:
    if e.errno == errno.ECONNREFUSED:
        return ErrorCode("connection-refused")
    if e.errno == errno.ETIMEDOUT:
        return ErrorCode("connection-timeout")
    if e.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH):
        return ErrorCode("destination-unavailable")
    if e.errno in (errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE):
        return ErrorCode("connection-terminated")
    return ErrorCode("internal-error", e.strerror or "connect failed")


def _connect(host: str, port: int, timeout: float) -> socket.socket:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise _dns_error(e) from None
    last: ErrorCode | None = None
    for family, kind, proto, _, addr in infos:
        s = socket.socket(family, kind, proto)
        try:
            s.settimeout(timeout)
            s.connect(addr)
            return s
        except TimeoutError:
            s.close()
            last = ErrorCode("connection-timeout")
        except OSError as e:
            s.close()
            last = _connect_error(e)
    raise last or ErrorCode("destination-not-found")


class _Reader:
    """Reads an answer: the head, a body by its length, in chunks or to the end of the stream."""

    def __init__(self, sock: socket.socket, first_s: float, between_s: float) -> None:
        self.sock = sock
        self.buf = b""
        self.first = True
        self.first_s, self.between_s = first_s, between_s

    def more(self) -> bool:
        self.sock.settimeout(self.first_s if self.first else self.between_s)
        try:
            data = self.sock.recv(65536)
        except TimeoutError:
            raise ErrorCode("connection-read-timeout") from None
        except OSError:
            raise ErrorCode("connection-terminated") from None
        self.first = False
        self.buf += data
        return bool(data)

    def line(self) -> bytes:
        while True:
            i = self.buf.find(b"\r\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 2 :]
                return line
            if len(self.buf) > MAX_HEAD:
                raise ErrorCode("HTTP-protocol-error")
            if not self.more():
                raise ErrorCode("HTTP-response-incomplete")

    def exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            if not self.more():
                raise ErrorCode("HTTP-response-incomplete")
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def rest(self) -> bytes:
        while self.more():
            if len(self.buf) > MAX_BODY:
                raise ErrorCode("HTTP-response-body-size", MAX_BODY)
        data, self.buf = self.buf, b""
        return data


def _parse_fields(lines: list[bytes], trailer: bool) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for line in lines:
        name, colon, value = line.partition(b":")
        if not colon or not _TOKEN.fullmatch(name) or line[:1] in (b" ", b"\t"):
            raise ErrorCode("HTTP-protocol-error")
        out.append((name.decode().lower(), value.strip(b" \t")))
    return out


def _read_head(r: _Reader, method: str) -> tuple[int, list[tuple[str, bytes]]]:
    while True:
        head = b""
        while True:
            line = r.line()
            if not line and not head:
                continue  # a blank line before the status line
            if not line:
                break
            head += line + b"\n"
            if len(head) > MAX_HEAD:
                raise ErrorCode("HTTP-response-header-section-size", MAX_HEAD)
        lines = head.split(b"\n")[:-1]
        m = re.fullmatch(rb"HTTP/1\.[01] ([0-9]{3})(?: .*)?", lines[0])
        if not m:
            raise ErrorCode("HTTP-protocol-error")
        status = int(m.group(1))
        if status == 101:
            raise ErrorCode("HTTP-upgrade-failed")
        if status < 200:
            continue  # informational
        return status, _parse_fields(lines[1:], False)


def _read_body(
    r: _Reader, method: str, status: int, headers: list[tuple[str, bytes]]
) -> tuple[bytes, list[tuple[str, bytes]] | None]:
    if method == "HEAD" or status in (204, 304):
        return b"", None
    coding = [
        v.decode("latin-1").strip().lower() for n, v in headers if n == "transfer-encoding" for v in v.split(b",")
    ]
    if coding:
        if coding != ["chunked"]:
            raise ErrorCode("HTTP-response-transfer-coding", ", ".join(coding))
        return _read_chunked(r)
    lengths = {v for n, v in headers if n == "content-length"}
    if lengths:
        if len(lengths) != 1:
            raise ErrorCode("HTTP-protocol-error")
        (value,) = lengths
        if not value.isdigit():
            raise ErrorCode("HTTP-protocol-error")
        n = min(int(value), (1 << 64) - 1)
        if n > MAX_BODY:
            raise ErrorCode("HTTP-response-body-size", n)
        return r.exact(n), None
    return r.rest(), None


def _read_chunked(r: _Reader) -> tuple[bytes, list[tuple[str, bytes]] | None]:
    body = bytearray()
    while True:
        size_text = r.line().split(b";")[0].strip()
        if not re.fullmatch(rb"[0-9A-Fa-f]{1,16}", size_text):
            raise ErrorCode("HTTP-protocol-error")
        size = int(size_text, 16)
        if size == 0:
            break
        if len(body) + size > MAX_BODY:
            raise ErrorCode("HTTP-response-body-size", len(body) + size)
        body += r.exact(size)
        if r.exact(2) != b"\r\n":
            raise ErrorCode("HTTP-protocol-error")
    lines: list[bytes] = []
    while True:
        line = r.line()
        if not line:
            break
        lines.append(line)
    trailers = _parse_fields(lines, True)
    return bytes(body), trailers or None


def build_request(req: HttpRequest) -> bytes:
    """The bytes of a request: head, then the body (in chunks, with the trailers, if trailers are given)."""
    out = [
        f"{req.method} {req.path} HTTP/1.1\r\n".encode("latin-1"),
        b"Host: " + req.authority.encode("latin-1") + b"\r\n",
    ]
    names = {n for n, _ in req.headers}
    for n, v in req.headers:
        out.append(n.encode("latin-1") + b": " + v + b"\r\n")
    if req.trailers is not None:
        out.append(b"transfer-encoding: chunked\r\n")
    elif "content-length" not in names and (req.body or req.method in ("POST", "PUT", "PATCH")):
        out.append(b"content-length: " + str(len(req.body)).encode() + b"\r\n")
    out.append(b"connection: close\r\n\r\n")
    if req.trailers is None:
        out.append(req.body)
    else:
        if req.body:
            out.append(b"%x\r\n" % len(req.body) + req.body + b"\r\n")
        out.append(b"0\r\n" + b"".join(n.encode("latin-1") + b": " + v + b"\r\n" for n, v in req.trailers) + b"\r\n")
    return b"".join(out)


def default_send(req: HttpRequest) -> HttpResponse:
    """The transport of the host: a connection for each request, `Connection: close`."""
    https = req.scheme == "https"
    parsed = split_authority(req.authority, 443 if https else 80)
    if parsed is None:
        raise ErrorCode("HTTP-request-URI-invalid")
    name, port = parsed
    sock = _connect(name, port, _seconds(req.connect_ns))
    try:
        if https:
            try:
                sock.settimeout(_seconds(req.connect_ns))
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=name)
            except ssl.SSLCertVerificationError:
                raise ErrorCode("TLS-certificate-error") from None
            except TimeoutError:
                raise ErrorCode("connection-timeout") from None
            except ssl.SSLError:
                raise ErrorCode("TLS-protocol-error") from None
            except OSError:
                raise ErrorCode("connection-terminated") from None
        between = _seconds(req.between_bytes_ns)
        sock.settimeout(between)
        try:
            sock.sendall(build_request(req))
        except TimeoutError:
            raise ErrorCode("connection-write-timeout") from None
        except OSError:
            raise ErrorCode("connection-terminated") from None
        r = _Reader(sock, _seconds(req.first_byte_ns), between)
        status, headers = _read_head(r, req.method)
        body, trailers = _read_body(r, req.method, status, headers)
        return HttpResponse(status, headers, body, trailers)
    finally:
        sock.close()


# the answer


class IncomingResponse:
    def __init__(self, status: int, headers: Fields, body: tuple[bytes, Fields | None] | None) -> None:
        self.status = status
        self.headers = headers
        self.body = body  # None once consumed


class FutureIncomingResponse:
    def __init__(self, request: OutgoingRequest, options: RequestOptions | None, prepared: HttpRequest) -> None:
        self.request, self.options, self.prepared = request, options, prepared
        self.result: IncomingResponse | ErrorCode | None = None
        self.taken = False

    def advance(self, host: Host) -> bool:
        if self.result is not None:
            return True
        body = self.request.body
        if body is not None and not (body.finished or body.abandoned):
            return False
        if body is not None and body.abandoned:
            self.result = ErrorCode("HTTP-protocol-error")
            return True
        if body is not None:
            self.prepared.body = body.data()
            if body.trailers is not None:
                self.prepared.trailers = list(body.trailers.entries)
        send = host.http_send or default_send
        try:
            response = send(self.prepared)
        except ErrorCode as e:
            self.result = e
        else:
            trailers = (
                None if response.trailers is None else Fields([(n.lower(), v) for n, v in response.trailers], True)
            )
            self.result = IncomingResponse(
                response.status,
                Fields([(n.lower(), v) for n, v in response.headers], True),
                (bytes(response.body), trailers),
            )
        return True


class FuturePollable(Pollable):
    def __init__(self, future: FutureIncomingResponse) -> None:
        self.future = future

    def ready(self, host: Host) -> bool:
        return self.future.advance(host)


def _future(host: Host, handle: int) -> FutureIncomingResponse:
    return table_get(host, handle, KIND_FUTURE_INCOMING_RESPONSE)  # type: ignore[return-value]


def _prepare(host: Host, req: OutgoingRequest, options: RequestOptions | None) -> HttpRequest:
    """The request as the transport takes it, or the `ErrorCode` for what is wrong with it (also: the policy)."""
    if not _TOKEN.fullmatch(req.method.encode("latin-1")):
        raise ErrorCode("HTTP-request-method-invalid")
    scheme = "https" if req.scheme is None else req.scheme
    if scheme not in ("http", "https") or req.authority is None:
        raise ErrorCode("HTTP-request-URI-invalid")
    if split_authority(req.authority, 80) is None:
        raise ErrorCode("HTTP-request-URI-invalid")
    if not host.http_check(scheme, req.authority):
        raise ErrorCode("HTTP-request-denied")
    options = options or RequestOptions()
    return HttpRequest(
        req.method,
        scheme,
        req.authority,
        req.path or "/",
        list(req.headers.entries),
        connect_ns=options.connect,
        first_byte_ns=options.first_byte,
        between_bytes_ns=options.between_bytes,
    )


def wasi_http_outgoing_handler_handle(
    host: Host, comp: int, request: int, opt_tag: int, opt_handle: int, retptr: int
) -> None:
    req = _request(host, request)
    options = _options(host, opt_handle) if opt_tag else None
    table_drop(host, request, KIND_OUTGOING_REQUEST)
    if opt_tag:
        table_drop(host, opt_handle, KIND_REQUEST_OPTIONS)
    try:
        prepared = _prepare(host, req, options)
    except ErrorCode as e:
        store_u8(host, comp, retptr, 1)
        store_error_code(host, comp, retptr + 8, e)
        return
    store_u8(host, comp, retptr, 0)
    store_u32(
        host,
        comp,
        retptr + 8,
        table_new(host, KIND_FUTURE_INCOMING_RESPONSE, FutureIncomingResponse(req, options, prepared)),
    )


def wasi_http_types_future_incoming_response_subscribe(host: Host, self: int) -> int:
    return table_new(host, KIND_POLLABLE, FuturePollable(_future(host, self)))


def wasi_http_types_future_incoming_response_get(host: Host, comp: int, self: int, retptr: int) -> None:
    future = _future(host, self)
    if not future.advance(host):
        store_u8(host, comp, retptr, 0)
        return
    store_u8(host, comp, retptr, 1)
    if future.taken:
        store_u8(host, comp, retptr + 8, 1)
        return
    future.taken = True
    store_u8(host, comp, retptr + 8, 0)
    if isinstance(future.result, ErrorCode):
        store_u8(host, comp, retptr + 16, 1)
        store_error_code(host, comp, retptr + 24, future.result)
    else:
        store_u8(host, comp, retptr + 16, 0)
        store_u32(host, comp, retptr + 24, table_new(host, KIND_INCOMING_RESPONSE, future.result))


def wasi_http_types_future_incoming_response_drop(host: Host, handle: int) -> None:
    _future(host, handle)
    table_drop(host, handle, KIND_FUTURE_INCOMING_RESPONSE)


def _response(host: Host, handle: int) -> IncomingResponse:
    return table_get(host, handle, KIND_INCOMING_RESPONSE)  # type: ignore[return-value]


def wasi_http_types_incoming_response_status(host: Host, self: int) -> int:
    return _response(host, self).status


def wasi_http_types_incoming_response_headers(host: Host, self: int) -> int:
    return table_new(host, KIND_FIELDS, _response(host, self).headers)


def wasi_http_types_incoming_response_consume(host: Host, comp: int, self: int, retptr: int) -> None:
    resp = _response(host, self)
    if _consume(host, comp, resp.body, retptr) is not None:
        resp.body = None


def wasi_http_types_incoming_response_drop(host: Host, handle: int) -> None:
    _response(host, handle)
    table_drop(host, handle, KIND_INCOMING_RESPONSE)


# the server side: what an embedder gives a component that exports incoming-handler, and what it gets back


class IncomingRequest:
    def __init__(
        self,
        method: str,
        path: str | None,
        scheme: str | None,
        authority: str | None,
        headers: Fields,
        body: tuple[bytes, Fields | None] | None,
    ) -> None:
        self.method, self.path, self.scheme, self.authority = method, path, scheme, authority
        self.headers = headers
        self.body = body


def incoming_request_new(
    host: Host,
    method: str,
    path: str | None,
    scheme: str | None,
    authority: str | None,
    headers: Sequence[tuple[str, bytes]] = (),
    body: bytes = b"",
    trailers: Sequence[tuple[str, bytes]] | None = None,
) -> int:
    """A request for the guest (its handle); `scheme` is "http", "https" or another text."""
    fields = Fields([(n.lower(), v) for n, v in headers], True)
    t = None if trailers is None else Fields([(n.lower(), v) for n, v in trailers], True)
    return table_new(
        host, KIND_INCOMING_REQUEST, IncomingRequest(method, path, scheme, authority, fields, (bytes(body), t))
    )


def _incoming_request(host: Host, handle: int) -> IncomingRequest:
    return table_get(host, handle, KIND_INCOMING_REQUEST)  # type: ignore[return-value]


def wasi_http_types_incoming_request_method(host: Host, comp: int, self: int, retptr: int) -> None:
    _store_method(host, comp, retptr, _incoming_request(host, self).method)


def wasi_http_types_incoming_request_path_with_query(host: Host, comp: int, self: int, retptr: int) -> None:
    _store_opt_text(host, comp, retptr, _incoming_request(host, self).path)


def wasi_http_types_incoming_request_scheme(host: Host, comp: int, self: int, retptr: int) -> None:
    scheme = _incoming_request(host, self).scheme
    store_u8(host, comp, retptr, 0 if scheme is None else 1)
    if scheme is not None:
        _store_scheme(host, comp, retptr + 4, scheme)


def wasi_http_types_incoming_request_authority(host: Host, comp: int, self: int, retptr: int) -> None:
    _store_opt_text(host, comp, retptr, _incoming_request(host, self).authority)


def wasi_http_types_incoming_request_headers(host: Host, self: int) -> int:
    return table_new(host, KIND_FIELDS, _incoming_request(host, self).headers)


def wasi_http_types_incoming_request_consume(host: Host, comp: int, self: int, retptr: int) -> None:
    req = _incoming_request(host, self)
    if _consume(host, comp, req.body, retptr) is not None:
        req.body = None


def wasi_http_types_incoming_request_drop(host: Host, handle: int) -> None:
    _incoming_request(host, handle)
    table_drop(host, handle, KIND_INCOMING_REQUEST)


class OutgoingResponse:
    def __init__(self, headers: Fields) -> None:
        self.headers = headers
        self.status = 200
        self.body: OutgoingBody | None = None

    def body_bytes(self) -> bytes:
        return b"" if self.body is None else self.body.data()

    @property
    def trailers(self) -> Fields | None:
        return None if self.body is None else self.body.trailers

    @property
    def finished(self) -> bool:
        return self.body is not None and self.body.finished


class OutParam:
    """Where the guest puts its answer: `response` or `error` is set when it calls `response-outparam.set`; `error` too if the handle is dropped without it."""

    def __init__(self) -> None:
        self.response: OutgoingResponse | None = None
        self.error: ErrorCode | None = None
        self.done = False


def response_outparam_new(host: Host) -> tuple[int, OutParam]:
    param = OutParam()
    return table_new(host, KIND_RESPONSE_OUTPARAM, param), param


def _outparam(host: Host, handle: int) -> OutParam:
    return table_get(host, handle, KIND_RESPONSE_OUTPARAM)  # type: ignore[return-value]


def wasi_http_types_response_outparam_set(
    host: Host, comp: int, param: int, tag: int, a1: int, a2: int, a3: int, a4: int, a5: int, a6: int, a7: int
) -> None:
    out = _outparam(host, param)
    if tag == 0:
        response: OutgoingResponse = table_get(host, a1, KIND_OUTGOING_RESPONSE)  # type: ignore[assignment]
        table_drop(host, a1, KIND_OUTGOING_RESPONSE)
        out.response = response
    elif tag == 1:
        out.error = lift_error_code_flat(host, comp, [a1, a2, a3, a4, a5, a6, a7])
    else:
        raise Trap(f"bad result {tag}")
    out.done = True
    table_drop(host, param, KIND_RESPONSE_OUTPARAM)


def wasi_http_types_response_outparam_drop(host: Host, handle: int) -> None:
    out = _outparam(host, handle)
    table_drop(host, handle, KIND_RESPONSE_OUTPARAM)
    if not out.done:
        out.error = ErrorCode("internal-error", "response-outparam dropped without a response")
        out.done = True


def _outgoing_response(host: Host, handle: int) -> OutgoingResponse:
    return table_get(host, handle, KIND_OUTGOING_RESPONSE)  # type: ignore[return-value]


def wasi_http_types_outgoing_response_new(host: Host, headers: int) -> int:
    return table_new(host, KIND_OUTGOING_RESPONSE, OutgoingResponse(_take_fields(host, headers)))


def wasi_http_types_outgoing_response_status_code(host: Host, self: int) -> int:
    return _outgoing_response(host, self).status


def wasi_http_types_outgoing_response_set_status_code(host: Host, self: int, status: int) -> int:
    if not 100 <= status <= 599:
        return 1
    _outgoing_response(host, self).status = status
    return 0


def wasi_http_types_outgoing_response_headers(host: Host, self: int) -> int:
    return table_new(host, KIND_FIELDS, _outgoing_response(host, self).headers)


def wasi_http_types_outgoing_response_body(host: Host, comp: int, self: int, retptr: int) -> None:
    resp = _outgoing_response(host, self)
    body = _new_body(host, comp, resp.headers, "response", resp.body, retptr)
    if body is not None:
        resp.body = body


def wasi_http_types_outgoing_response_drop(host: Host, handle: int) -> None:
    _outgoing_response(host, handle)
    table_drop(host, handle, KIND_OUTGOING_RESPONSE)


# errors of the io resource


def wasi_http_types_http_error_code(host: Host, comp: int, err: int, retptr: int) -> None:
    table_get(host, err, KIND_ERROR)
    store_u8(host, comp, retptr, 0)  # a stream of a body never fails here, so no error carries an http error-code
