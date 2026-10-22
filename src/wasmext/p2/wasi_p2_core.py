"""The state of a host of WASI 0.2 and the helpers of the canonical ABI that every package uses (the twin of `c/p2/wasi_p2_core.h`).

No mutable state at the level of the module: everything that changes is in a `Host`, which is passed as the first argument of every function of the packages.
A memory is any writable buffer (`bytearray`, `memoryview`); a module fused from components has one for each component, and a function takes the number of its own.
"""

from __future__ import annotations

import struct
import time
from collections.abc import Callable, Sequence

INDEX_BITS = 20  # a handle is (generation << INDEX_BITS) | index; index 0 is never given out
INDEX_MASK = (1 << INDEX_BITS) - 1
GENERATION_MASK = (1 << (32 - INDEX_BITS)) - 1

KIND_POLLABLE = 1


class Trap(Exception):
    """What the canonical ABI calls a trap: a bad handle, a pointer outside the memory."""


class Slot:
    __slots__ = ("generation", "kind", "live", "obj")

    def __init__(self) -> None:
        self.generation = 0
        self.kind = 0
        self.live = False
        self.obj: object = None


class Host:
    """The state of one instance: its memories, the table of handles and the clocks."""

    def __init__(
        self,
        memories: Sequence[object] = (),
        *,
        wall_ns: Callable[[], int] = time.time_ns,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_resolution_ns: int | None = None,
        monotonic_resolution_ns: int | None = None,
    ) -> None:
        self.memories: list[object] = list(memories)
        self.slots: list[Slot] = [Slot()]  # slot 0 is never used
        self.wall_ns = wall_ns
        self.monotonic_ns = monotonic_ns
        self.wall_resolution_ns = wall_resolution_ns or round(time.get_clock_info("time").resolution * 1e9) or 1
        self.monotonic_resolution_ns = (
            monotonic_resolution_ns or round(time.get_clock_info("monotonic").resolution * 1e9) or 1
        )


# the table of handles (own and borrow share it; a handle is an i32 for the guest)


def table_new(host: Host, kind: int, obj: object) -> int:
    for index, slot in enumerate(host.slots):
        if index and not slot.live:
            break
    else:
        index = len(host.slots)
        if index > INDEX_MASK:
            raise Trap("table of handles is full")
        host.slots.append(Slot())
        slot = host.slots[index]
    slot.generation = (slot.generation + 1) & GENERATION_MASK
    slot.kind, slot.live, slot.obj = kind, True, obj
    return (slot.generation << INDEX_BITS) | index


def table_get(host: Host, handle: int, kind: int) -> object:
    """The object of a live handle of the given kind; anything else is a trap."""
    index = handle & INDEX_MASK
    if index == 0 or index >= len(host.slots):
        raise Trap(f"bad handle {handle}")
    slot = host.slots[index]
    if not slot.live or slot.generation != handle >> INDEX_BITS or slot.kind != kind:
        raise Trap(f"bad handle {handle}")
    return slot.obj


def table_drop(host: Host, handle: int, kind: int) -> None:
    table_get(host, handle, kind)
    slot = host.slots[handle & INDEX_MASK]
    slot.live, slot.obj = False, None


# memory: little-endian, checked


def _check(host: Host, comp: int, ptr: int, size: int) -> memoryview:
    if comp >= len(host.memories):
        raise Trap(f"no memory {comp}")
    view = memoryview(host.memories[comp])  # type: ignore[call-overload]
    if ptr < 0 or ptr + size > len(view):
        raise Trap(f"pointer {ptr:#x}+{size} is outside the memory")
    return view


def store_u8(host: Host, comp: int, ptr: int, value: int) -> None:
    _check(host, comp, ptr, 1)[ptr] = value & 0xFF


def store_u32(host: Host, comp: int, ptr: int, value: int) -> None:
    struct.pack_into("<I", _check(host, comp, ptr, 4), ptr, value & 0xFFFFFFFF)


def store_u64(host: Host, comp: int, ptr: int, value: int) -> None:
    struct.pack_into("<Q", _check(host, comp, ptr, 8), ptr, value & 0xFFFFFFFFFFFFFFFF)


def load_u32(host: Host, comp: int, ptr: int) -> int:
    return struct.unpack_from("<I", _check(host, comp, ptr, 4), ptr)[0]
