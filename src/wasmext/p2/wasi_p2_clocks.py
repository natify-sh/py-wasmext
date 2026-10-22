"""wasi:clocks (6 imports): `wall-clock` and `monotonic-clock` (the twin of `c/p2/wasi_p2_clocks.h`).

Names carry the interface, as in C: `wasi_clocks_<interface>_<function>`. A result that does not fit in one flat value is written through the pointer that is the last
argument (the canonical ABI); `datetime` is a record `{seconds: u64, nanoseconds: u32}` of 16 bytes, 8-aligned.
"""

from __future__ import annotations

from .wasi_p2_core import KIND_POLLABLE, Host, store_u32, store_u64, table_new

_NS = 1_000_000_000
_MAX_U64 = (1 << 64) - 1


def _datetime(host: Host, comp: int, retptr: int, ns: int) -> None:
    store_u64(host, comp, retptr, ns // _NS)
    store_u32(host, comp, retptr + 8, ns % _NS)


def wasi_clocks_wall_clock_now(host: Host, comp: int, retptr: int) -> None:
    _datetime(host, comp, retptr, host.wall_ns())


def wasi_clocks_wall_clock_resolution(host: Host, comp: int, retptr: int) -> None:
    _datetime(host, comp, retptr, host.wall_resolution_ns)


def wasi_clocks_monotonic_clock_now(host: Host) -> int:
    return host.monotonic_ns()


def wasi_clocks_monotonic_clock_resolution(host: Host) -> int:
    return host.monotonic_resolution_ns


class Pollable:
    """A pollable that is ready at an instant of the monotonic clock (the other kinds come with `wasi:io`)."""

    __slots__ = ("deadline",)

    def __init__(self, deadline: int) -> None:
        self.deadline = deadline

    def ready(self, host: Host) -> bool:
        return host.monotonic_ns() >= self.deadline


def wasi_clocks_monotonic_clock_subscribe_instant(host: Host, when: int) -> int:
    return table_new(host, KIND_POLLABLE, Pollable(when))


def wasi_clocks_monotonic_clock_subscribe_duration(host: Host, when: int) -> int:
    return table_new(host, KIND_POLLABLE, Pollable(min(host.monotonic_ns() + when, _MAX_U64)))
