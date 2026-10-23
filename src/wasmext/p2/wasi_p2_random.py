"""wasi:random (5 imports): `random`, `insecure` and `insecure-seed` (the twin of `c/p2/wasi_p2_random.h`).

The bytes come from `Host.random_bytes` (`os.urandom`) and, for the insecure interfaces, `Host.insecure_random_bytes` (the same source unless replaced). A list is returned
through the pointer that is the last argument, in memory of the component (`cabi_realloc`); `insecure-seed` is a tuple of two u64 (16 bytes). A request of more than
`MAX_BYTES` bytes is a trap, so that a guest cannot ask the host for all its memory.
"""

from __future__ import annotations

from .wasi_p2_core import Host, Trap, alloc, store_bytes, store_u32, store_u64

MAX_BYTES = 1 << 26


def _bytes(host: Host, comp: int, insecure: bool, length: int, retptr: int) -> None:
    if length > MAX_BYTES:
        raise Trap(f"{length} random bytes requested")
    data = (host.insecure_random_bytes if insecure else host.random_bytes)(length)
    ptr = alloc(host, comp, 1, length)
    store_bytes(host, comp, ptr, data)
    store_u32(host, comp, retptr, ptr)
    store_u32(host, comp, retptr + 4, length)


def _u64(host: Host, insecure: bool) -> int:
    return int.from_bytes((host.insecure_random_bytes if insecure else host.random_bytes)(8), "little")


def wasi_random_random_get_random_bytes(host: Host, comp: int, len: int, retptr: int) -> None:
    _bytes(host, comp, False, len, retptr)


def wasi_random_random_get_random_u64(host: Host) -> int:
    return _u64(host, False)


def wasi_random_insecure_get_insecure_random_bytes(host: Host, comp: int, len: int, retptr: int) -> None:
    _bytes(host, comp, True, len, retptr)


def wasi_random_insecure_get_insecure_random_u64(host: Host) -> int:
    return _u64(host, True)


def wasi_random_insecure_seed_insecure_seed(host: Host, comp: int, retptr: int) -> None:
    store_u64(host, comp, retptr, _u64(host, True))
    store_u64(host, comp, retptr + 8, _u64(host, True))
