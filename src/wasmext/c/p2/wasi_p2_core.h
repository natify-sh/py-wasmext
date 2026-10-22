/* The state of a host of WASI 0.2 and the helpers of the canonical ABI that every package uses (the twin of p2/wasi_p2_core.py).
 *
 * Header-only, every function static. No mutable global and no thread-local: everything that changes is in one `wasi_p2_state`, passed as the first argument of every
 * function of the packages. A memory is a base and a size; a module fused from components has one for each component, and a function takes the number of its own.
 * Not part of the ABI of wasmext: this directory is not read by the fingerprint of `c/` (docs/abi_policy.md). Memory is written byte by byte, little-endian.
 * POSIX clocks need `clock_gettime` (a GNU or POSIX mode of the compiler). */
#ifndef WASI_P2_CORE_H
#define WASI_P2_CORE_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <time.h>
#endif

#define WASI_P2_MAX_MEMORIES 8
#define WASI_P2_INDEX_BITS 20 /* a handle is (generation << INDEX_BITS) | index; index 0 is never given out */
#define WASI_P2_INDEX_MASK ((1u << WASI_P2_INDEX_BITS) - 1)
#define WASI_P2_GENERATION_MASK ((1u << (32 - WASI_P2_INDEX_BITS)) - 1)

enum { WASI_P2_KIND_POLLABLE = 1 };

typedef struct {
    uint8_t *base;
    uint64_t size;
} wasi_p2_memory;

typedef struct {
    uint32_t generation;
    uint32_t kind;
    int live;
    uint64_t value; /* what the kind needs: the deadline of a pollable */
    void *obj;
} wasi_p2_slot;

typedef struct wasi_p2_state {
    wasi_p2_memory memory[WASI_P2_MAX_MEMORIES];
    uint32_t memories;
    wasi_p2_slot *slots; /* slot 0 is never used */
    uint32_t slot_count, slot_capacity;
    /* a trap does not return; in a module it is `wasm_rt_trap`, the default aborts */
    void (*trap)(struct wasi_p2_state *s, const char *message);
    /* the clocks, in nanoseconds; replaced in tests */
    uint64_t (*wall_ns)(struct wasi_p2_state *s);
    uint64_t (*monotonic_ns)(struct wasi_p2_state *s);
    uint64_t wall_resolution_ns, monotonic_resolution_ns;
    void *user;
} wasi_p2_state;

static void wasi_p2_default_trap(wasi_p2_state *s, const char *message) {
    (void)s;
    fprintf(stderr, "wasi_p2 trap: %s\n", message);
    abort();
}

#ifdef _WIN32
static uint64_t wasi_p2_default_wall_ns(wasi_p2_state *s) {
    FILETIME ft;
    (void)s;
    GetSystemTimePreciseAsFileTime(&ft);
    uint64_t t = ((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime; /* 100 ns since 1601 */
    return (t - 116444736000000000ULL) * 100;
}
static uint64_t wasi_p2_default_monotonic_ns(wasi_p2_state *s) {
    LARGE_INTEGER f, c;
    (void)s;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&c);
    return (uint64_t)(c.QuadPart / f.QuadPart) * 1000000000ULL + (uint64_t)(c.QuadPart % f.QuadPart) * 1000000000ULL / (uint64_t)f.QuadPart;
}
#else
static uint64_t wasi_p2_clock_ns(clockid_t id) {
    struct timespec ts;
    clock_gettime(id, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}
static uint64_t wasi_p2_default_wall_ns(wasi_p2_state *s) { (void)s; return wasi_p2_clock_ns(CLOCK_REALTIME); }
static uint64_t wasi_p2_default_monotonic_ns(wasi_p2_state *s) { (void)s; return wasi_p2_clock_ns(CLOCK_MONOTONIC); }
#endif

static uint64_t wasi_p2_default_resolution_ns(int monotonic) {
#ifdef _WIN32
    (void)monotonic;
    return 100;
#else
    struct timespec ts;
    if (clock_getres(monotonic ? CLOCK_MONOTONIC : CLOCK_REALTIME, &ts) != 0) return 1;
    uint64_t ns = (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
    return ns ? ns : 1;
#endif
}

static void wasi_p2_init(wasi_p2_state *s) {
    memset(s, 0, sizeof *s);
    s->trap = wasi_p2_default_trap;
    s->wall_ns = wasi_p2_default_wall_ns;
    s->monotonic_ns = wasi_p2_default_monotonic_ns;
    s->wall_resolution_ns = wasi_p2_default_resolution_ns(0);
    s->monotonic_resolution_ns = wasi_p2_default_resolution_ns(1);
}

static void wasi_p2_free(wasi_p2_state *s) {
    free(s->slots);
    s->slots = NULL;
    s->slot_count = s->slot_capacity = 0;
}

/* Binds memory number `comp` (the base moves when the module grows its memory: set it again). Returns 0, or -1 if the number is too big. */
static int wasi_p2_set_memory(wasi_p2_state *s, uint32_t comp, uint8_t *base, uint64_t size) {
    if (comp >= WASI_P2_MAX_MEMORIES) return -1;
    s->memory[comp].base = base;
    s->memory[comp].size = size;
    if (comp >= s->memories) s->memories = comp + 1;
    return 0;
}

/* the table of handles (own and borrow share it; a handle is an i32 for the guest) */

static uint32_t wasi_p2_table_new(wasi_p2_state *s, uint32_t kind, uint64_t value, void *obj) {
    uint32_t index = 0;
    for (uint32_t i = 1; i < s->slot_count; i++)
        if (!s->slots[i].live) {
            index = i;
            break;
        }
    if (!index) {
        if (s->slot_count == 0) s->slot_count = 1; /* slot 0 */
        if (s->slot_count > WASI_P2_INDEX_MASK) s->trap(s, "table of handles is full");
        if (s->slot_count >= s->slot_capacity) {
            uint32_t cap = s->slot_capacity ? s->slot_capacity * 2 : 16;
            wasi_p2_slot *grown = (wasi_p2_slot *)realloc(s->slots, cap * sizeof *grown);
            if (!grown) s->trap(s, "out of memory");
            memset(grown + s->slot_capacity, 0, (cap - s->slot_capacity) * sizeof *grown);
            s->slots = grown;
            s->slot_capacity = cap;
        }
        index = s->slot_count++;
    }
    wasi_p2_slot *slot = &s->slots[index];
    slot->generation = (slot->generation + 1) & WASI_P2_GENERATION_MASK;
    slot->kind = kind;
    slot->live = 1;
    slot->value = value;
    slot->obj = obj;
    return (slot->generation << WASI_P2_INDEX_BITS) | index;
}

/* The slot of a live handle of the given kind; anything else is a trap. */
static wasi_p2_slot *wasi_p2_table_get(wasi_p2_state *s, uint32_t handle, uint32_t kind) {
    uint32_t index = handle & WASI_P2_INDEX_MASK;
    if (index == 0 || index >= s->slot_count) s->trap(s, "bad handle");
    wasi_p2_slot *slot = &s->slots[index];
    if (!slot->live || slot->generation != (handle >> WASI_P2_INDEX_BITS) || slot->kind != kind) s->trap(s, "bad handle");
    return slot;
}

static void wasi_p2_table_drop(wasi_p2_state *s, uint32_t handle, uint32_t kind) {
    wasi_p2_slot *slot = wasi_p2_table_get(s, handle, kind);
    slot->live = 0;
    slot->obj = NULL;
}

/* memory: little-endian, checked */

static uint8_t *wasi_p2_mem(wasi_p2_state *s, uint32_t comp, uint32_t ptr, uint32_t size) {
    if (comp >= s->memories) s->trap(s, "no such memory");
    if ((uint64_t)ptr + size > s->memory[comp].size) s->trap(s, "pointer outside the memory");
    return s->memory[comp].base + ptr;
}

static void wasi_p2_store_u32(wasi_p2_state *s, uint32_t comp, uint32_t ptr, uint32_t v) {
    uint8_t *p = wasi_p2_mem(s, comp, ptr, 4);
    for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i));
}

static void wasi_p2_store_u64(wasi_p2_state *s, uint32_t comp, uint32_t ptr, uint64_t v) {
    uint8_t *p = wasi_p2_mem(s, comp, ptr, 8);
    for (int i = 0; i < 8; i++) p[i] = (uint8_t)(v >> (8 * i));
}

#endif /* WASI_P2_CORE_H */
