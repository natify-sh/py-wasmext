/* wasi:random (5 imports): random, insecure and insecure-seed (the twin of p2/wasi_p2_random.py).
 *
 * The bytes come from `s->random_bytes` and, for the insecure interfaces, `s->insecure_random_bytes` (the same source unless replaced); a source that fails is a trap.
 * A list is returned through the pointer that is the last argument, in memory of the component (`cabi_realloc`); insecure-seed is a tuple of two u64 (16 bytes).
 * A request of more than WASI_P2_RANDOM_MAX bytes is a trap, so that a guest cannot ask the host for all its memory. */
#ifndef WASI_P2_RANDOM_H
#define WASI_P2_RANDOM_H

#include "wasi_p2_core.h"

#define WASI_P2_RANDOM_MAX (1u << 26)

WASI_P2_FN void wasi_p2_random_fill(wasi_p2_state *s, int insecure, uint8_t *buf, size_t n) {
    int (*source)(wasi_p2_state *, uint8_t *, size_t) = insecure ? s->insecure_random_bytes : s->random_bytes;
    if (n && source(s, buf, n) != 0) s->trap(s, "the source of random bytes failed");
}

WASI_P2_FN void wasi_p2_random_bytes(wasi_p2_state *s, uint32_t comp, int insecure, uint64_t len, uint32_t retptr) {
    if (len > WASI_P2_RANDOM_MAX) s->trap(s, "too many random bytes requested");
    uint32_t n = (uint32_t)len;
    uint32_t ptr = wasi_p2_alloc(s, comp, 1, n);
    wasi_p2_random_fill(s, insecure, wasi_p2_mem(s, comp, ptr, n), n);
    wasi_p2_store_u32(s, comp, retptr, ptr);
    wasi_p2_store_u32(s, comp, retptr + 4, n);
}

WASI_P2_FN uint64_t wasi_p2_random_u64(wasi_p2_state *s, int insecure) {
    uint8_t b[8];
    uint64_t v = 0;
    wasi_p2_random_fill(s, insecure, b, 8);
    for (int i = 0; i < 8; i++) v |= (uint64_t)b[i] << (8 * i);
    return v;
}

WASI_P2_FN void wasi_random_random_get_random_bytes(wasi_p2_state *s, uint32_t comp, uint64_t len, uint32_t retptr) {
    wasi_p2_random_bytes(s, comp, 0, len, retptr);
}
WASI_P2_FN uint64_t wasi_random_random_get_random_u64(wasi_p2_state *s) { return wasi_p2_random_u64(s, 0); }

WASI_P2_FN void wasi_random_insecure_get_insecure_random_bytes(wasi_p2_state *s, uint32_t comp, uint64_t len, uint32_t retptr) {
    wasi_p2_random_bytes(s, comp, 1, len, retptr);
}
WASI_P2_FN uint64_t wasi_random_insecure_get_insecure_random_u64(wasi_p2_state *s) { return wasi_p2_random_u64(s, 1); }

WASI_P2_FN void wasi_random_insecure_seed_insecure_seed(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    uint64_t a = wasi_p2_random_u64(s, 1), b = wasi_p2_random_u64(s, 1); /* in this order */
    wasi_p2_store_u64(s, comp, retptr, a);
    wasi_p2_store_u64(s, comp, retptr + 8, b);
}

#endif /* WASI_P2_RANDOM_H */
