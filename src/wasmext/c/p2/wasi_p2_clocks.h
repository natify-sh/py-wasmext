/* wasi:clocks (6 imports): `wall-clock` and `monotonic-clock` (the twin of p2/wasi_p2_clocks.py).
 *
 * Names carry the interface: wasi_clocks_<interface>_<function>. A result that does not fit in one flat value is written through the pointer that is the last
 * argument (the canonical ABI); `datetime` is a record {seconds: u64, nanoseconds: u32} of 16 bytes, 8-aligned. */
#ifndef WASI_P2_CLOCKS_H
#define WASI_P2_CLOCKS_H

#include "wasi_p2_core.h"

static void wasi_p2_datetime(wasi_p2_state *s, uint32_t comp, uint32_t retptr, uint64_t ns) {
    wasi_p2_store_u64(s, comp, retptr, ns / 1000000000ULL);
    wasi_p2_store_u32(s, comp, retptr + 8, (uint32_t)(ns % 1000000000ULL));
}

static void wasi_clocks_wall_clock_now(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    wasi_p2_datetime(s, comp, retptr, s->wall_ns(s));
}

static void wasi_clocks_wall_clock_resolution(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    wasi_p2_datetime(s, comp, retptr, s->wall_resolution_ns);
}

static uint64_t wasi_clocks_monotonic_clock_now(wasi_p2_state *s) { return s->monotonic_ns(s); }

static uint64_t wasi_clocks_monotonic_clock_resolution(wasi_p2_state *s) { return s->monotonic_resolution_ns; }

/* a pollable that is ready at an instant of the monotonic clock (the other kinds come with wasi:io); its value is the deadline */
static uint32_t wasi_clocks_monotonic_clock_subscribe_instant(wasi_p2_state *s, uint64_t when) {
    return wasi_p2_table_new(s, WASI_P2_KIND_POLLABLE, when, NULL);
}

static uint32_t wasi_clocks_monotonic_clock_subscribe_duration(wasi_p2_state *s, uint64_t when) {
    uint64_t now = s->monotonic_ns(s);
    return wasi_p2_table_new(s, WASI_P2_KIND_POLLABLE, when > UINT64_MAX - now ? UINT64_MAX : now + when, NULL);
}

#endif /* WASI_P2_CLOCKS_H */
