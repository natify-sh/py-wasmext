/* The state of a host of WASI 0.2 and the helpers of the canonical ABI that every package uses (the twin of p2/wasi_p2_core.py).
 *
 * Header-only, every function static (WASI_P2_FN). No mutable global and no thread-local: everything that changes is in one `wasi_p2_state`, passed as the first argument of every
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
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN /* without winsock.h, which winsock2.h (wasi_p2_net.h) does not go with */
#endif
#include <windows.h>
#ifdef _MSC_VER
#pragma comment(lib, "bcrypt") /* elsewhere: -lbcrypt */
#endif
#include <bcrypt.h>
#else
#include <time.h>
#endif

struct wasi_p2_state;
struct wasi_p2_http_request;
struct wasi_p2_http_response;
struct wasi_p2_http_error;

enum { WASI_P2_USE_TCP_BIND, WASI_P2_USE_TCP_CONNECT, WASI_P2_USE_UDP_BIND, WASI_P2_USE_UDP_CONNECT, WASI_P2_USE_UDP_OUTGOING };

/* a directory of the host that the guest sees under `name`; `writable` 0: the guest can only read it */
struct wasi_p2_preopen {
    const char *path, *name;
    int writable;
};

/* every function is static, and `inline` so that the ones a module does not use do not warn */
#define WASI_P2_FN static inline

#define WASI_P2_MAX_MEMORIES 8
#define WASI_P2_INDEX_BITS 20 /* a handle is (generation << INDEX_BITS) | index; index 0 is never given out */
#define WASI_P2_INDEX_MASK ((1u << WASI_P2_INDEX_BITS) - 1)
#define WASI_P2_GENERATION_MASK ((1u << (32 - WASI_P2_INDEX_BITS)) - 1)

enum { WASI_P2_KIND_POLLABLE = 1, WASI_P2_KIND_ERROR = 2, WASI_P2_KIND_INPUT_STREAM = 3, WASI_P2_KIND_OUTPUT_STREAM = 4,
       WASI_P2_KIND_TERMINAL_INPUT = 5, WASI_P2_KIND_TERMINAL_OUTPUT = 6,
       WASI_P2_KIND_DESCRIPTOR = 7, WASI_P2_KIND_DIRECTORY_ENTRY_STREAM = 8,
       WASI_P2_KIND_NETWORK = 9, WASI_P2_KIND_TCP_SOCKET = 10, WASI_P2_KIND_UDP_SOCKET = 11, WASI_P2_KIND_INCOMING_DATAGRAM_STREAM = 12,
       WASI_P2_KIND_OUTGOING_DATAGRAM_STREAM = 13, WASI_P2_KIND_RESOLVE_STREAM = 14,
       WASI_P2_KIND_FIELDS = 15, WASI_P2_KIND_INCOMING_REQUEST = 16, WASI_P2_KIND_OUTGOING_REQUEST = 17, WASI_P2_KIND_REQUEST_OPTIONS = 18,
       WASI_P2_KIND_RESPONSE_OUTPARAM = 19, WASI_P2_KIND_INCOMING_RESPONSE = 20, WASI_P2_KIND_INCOMING_BODY = 21, WASI_P2_KIND_FUTURE_TRAILERS = 22,
       WASI_P2_KIND_OUTGOING_RESPONSE = 23, WASI_P2_KIND_OUTGOING_BODY = 24, WASI_P2_KIND_FUTURE_INCOMING_RESPONSE = 25 };

enum { WASI_P2_TERMINAL_STDIN = 1, WASI_P2_TERMINAL_STDOUT = 2, WASI_P2_TERMINAL_STDERR = 4 };

typedef struct {
    uint8_t *base;
    uint64_t size;
} wasi_p2_memory;

/* Something a guest can wait for; wasi:clocks and wasi:io make the kinds. `ctx` is the owner's, `deadline` is for the clocks. */
typedef struct wasi_p2_pollable {
    int (*ready)(struct wasi_p2_state *s, struct wasi_p2_pollable *p);
    void *ctx;
    uint64_t deadline;
} wasi_p2_pollable;

typedef struct {
    uint32_t generation;
    uint32_t kind;
    int live;
    void *obj;
    void (*destroy)(struct wasi_p2_state *s, void *obj); /* called when the handle is dropped, or the state is freed; may be NULL */
} wasi_p2_slot;

typedef struct wasi_p2_state {
    wasi_p2_memory memory[WASI_P2_MAX_MEMORIES];
    uint32_t memories;
    wasi_p2_slot *slots; /* slot 0 is never used */
    uint32_t slot_count, slot_capacity;
    /* a trap does not return; in a module it is `wasm_rt_trap`, the default aborts */
    void (*trap)(struct wasi_p2_state *s, const char *message);
    /* the `cabi_realloc` of component `comp`: returns the pointer, or 0 for out of memory */
    uint32_t (*realloc)(struct wasi_p2_state *s, uint32_t comp, uint32_t old_ptr, uint32_t old_size, uint32_t align, uint32_t new_size);
    /* what a blocking call does between two looks at a pollable */
    void (*wait)(struct wasi_p2_state *s);
    /* wasi:cli/environment: owned by the caller, they must outlive the state */
    const char *const *args;
    uint32_t arg_count;
    const char *const *env_names, *const *env_values;
    uint32_t env_count;
    const char *initial_cwd; /* NULL: none */
    /* wasi:filesystem/preopens: owned by the caller */
    const struct wasi_p2_preopen *preopens;
    uint32_t preopen_count;
    /* wasi:sockets: nothing is allowed unless the caller says so, as in Wasmtime. `socket_addr_check` decides for each bind or connect (`use` is a WASI_P2_USE_*),
       `allow_ip_name_lookup` for resolve-addresses. `ip` is the address as text. NULL: everything is refused. */
    int (*socket_addr_check)(struct wasi_p2_state *s, const char *ip, uint16_t port, int use);
    int allow_ip_name_lookup;
    /* wasi:http: an outgoing request is refused (`HTTP-request-denied`) unless `http_check` says yes (`scheme` is "http" or "https"; NULL: everything is refused).
       `http_send` replaces the transport of wasi_p2_http.h: returns 0 with `out` filled, or nonzero with `err` filled. */
    int (*http_check)(struct wasi_p2_state *s, const char *scheme, const char *authority);
    int (*http_send)(struct wasi_p2_state *s, const struct wasi_p2_http_request *req, struct wasi_p2_http_response *out, struct wasi_p2_http_error *err);
    /* the standard streams (wasi_p2_stream, wasi_p2_io.h): [0] stdin, [1] stdout, [2] stderr; NULL means the descriptors of the process, made when first asked for
       (`std_default`, freed with the state). The streams of the caller are not closed when a handle to them is dropped. */
    void *std[3];
    void *std_default[3];
    unsigned terminals; /* WASI_P2_TERMINAL_*: which of the three are terminals */
    /* the guest called wasi:cli/exit: `exit` is told, and by default records the code and traps; the code is in `exit_code` when `exited` */
    void (*exit)(struct wasi_p2_state *s, uint32_t code);
    int exited;
    uint32_t exit_code;
    /* random bytes: returns 0, or nonzero if the source failed (a trap). `insecure_random_bytes` is the same source unless replaced. */
    int (*random_bytes)(struct wasi_p2_state *s, uint8_t *buf, size_t n);
    int (*insecure_random_bytes)(struct wasi_p2_state *s, uint8_t *buf, size_t n);
    /* the clocks, in nanoseconds; replaced in tests */
    uint64_t (*wall_ns)(struct wasi_p2_state *s);
    uint64_t (*monotonic_ns)(struct wasi_p2_state *s);
    uint64_t wall_resolution_ns, monotonic_resolution_ns;
    void *user;
} wasi_p2_state;

WASI_P2_FN void wasi_p2_default_trap(wasi_p2_state *s, const char *message) {
    (void)s;
    fprintf(stderr, "wasi_p2 trap: %s\n", message);
    abort();
}

#ifdef _WIN32
WASI_P2_FN uint64_t wasi_p2_default_wall_ns(wasi_p2_state *s) {
    FILETIME ft;
    (void)s;
    GetSystemTimePreciseAsFileTime(&ft);
    uint64_t t = ((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime; /* 100 ns since 1601 */
    return (t - 116444736000000000ULL) * 100;
}
WASI_P2_FN uint64_t wasi_p2_default_monotonic_ns(wasi_p2_state *s) {
    LARGE_INTEGER f, c;
    (void)s;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&c);
    return (uint64_t)(c.QuadPart / f.QuadPart) * 1000000000ULL + (uint64_t)(c.QuadPart % f.QuadPart) * 1000000000ULL / (uint64_t)f.QuadPart;
}
#else
WASI_P2_FN uint64_t wasi_p2_clock_ns(clockid_t id) {
    struct timespec ts;
    clock_gettime(id, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}
WASI_P2_FN uint64_t wasi_p2_default_wall_ns(wasi_p2_state *s) { (void)s; return wasi_p2_clock_ns(CLOCK_REALTIME); }
WASI_P2_FN uint64_t wasi_p2_default_monotonic_ns(wasi_p2_state *s) { (void)s; return wasi_p2_clock_ns(CLOCK_MONOTONIC); }
#endif

WASI_P2_FN uint64_t wasi_p2_default_resolution_ns(int monotonic) {
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

WASI_P2_FN int wasi_p2_default_random_bytes(wasi_p2_state *s, uint8_t *buf, size_t n) {
    (void)s;
#ifdef _WIN32
    return BCryptGenRandom(NULL, buf, (ULONG)n, BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0;
#else
    FILE *f = fopen("/dev/urandom", "rb");
    if (!f) return 1;
    size_t got = fread(buf, 1, n, f);
    fclose(f);
    return got != n;
#endif
}

WASI_P2_FN void wasi_p2_default_exit(wasi_p2_state *s, uint32_t code) {
    s->exited = 1;
    s->exit_code = code;
    s->trap(s, "exit");
}

WASI_P2_FN void wasi_p2_default_wait(wasi_p2_state *s) {
    (void)s;
#ifdef _WIN32
    Sleep(1);
#else
    struct timespec ts = {0, 1000000};
    nanosleep(&ts, NULL);
#endif
}

WASI_P2_FN void wasi_p2_init(wasi_p2_state *s) {
    memset(s, 0, sizeof *s);
    s->trap = wasi_p2_default_trap;
    s->wait = wasi_p2_default_wait;
    s->exit = wasi_p2_default_exit;
    s->random_bytes = s->insecure_random_bytes = wasi_p2_default_random_bytes;
    s->wall_ns = wasi_p2_default_wall_ns;
    s->monotonic_ns = wasi_p2_default_monotonic_ns;
    s->wall_resolution_ns = wasi_p2_default_resolution_ns(0);
    s->monotonic_resolution_ns = wasi_p2_default_resolution_ns(1);
}

WASI_P2_FN void wasi_p2_free(wasi_p2_state *s) {
    for (uint32_t i = 1; i < s->slot_count; i++)
        if (s->slots[i].live && s->slots[i].destroy) s->slots[i].destroy(s, s->slots[i].obj);
    for (int i = 0; i < 3; i++) free(s->std_default[i]), s->std_default[i] = NULL;
    free(s->slots);
    s->slots = NULL;
    s->slot_count = s->slot_capacity = 0;
}

/* Binds memory number `comp` (the base moves when the module grows its memory: set it again). Returns 0, or -1 if the number is too big. */
WASI_P2_FN int wasi_p2_set_memory(wasi_p2_state *s, uint32_t comp, uint8_t *base, uint64_t size) {
    if (comp >= WASI_P2_MAX_MEMORIES) return -1;
    s->memory[comp].base = base;
    s->memory[comp].size = size;
    if (comp >= s->memories) s->memories = comp + 1;
    return 0;
}

/* the table of handles (own and borrow share it; a handle is an i32 for the guest) */

WASI_P2_FN uint32_t wasi_p2_table_new(wasi_p2_state *s, uint32_t kind, void *obj, void (*destroy)(wasi_p2_state *, void *)) {
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
    slot->obj = obj;
    slot->destroy = destroy;
    return (slot->generation << WASI_P2_INDEX_BITS) | index;
}

/* The slot of a live handle of the given kind; anything else is a trap. */
WASI_P2_FN wasi_p2_slot *wasi_p2_table_get(wasi_p2_state *s, uint32_t handle, uint32_t kind) {
    uint32_t index = handle & WASI_P2_INDEX_MASK;
    if (index == 0 || index >= s->slot_count) s->trap(s, "bad handle");
    wasi_p2_slot *slot = &s->slots[index];
    if (!slot->live || slot->generation != (handle >> WASI_P2_INDEX_BITS) || slot->kind != kind) s->trap(s, "bad handle");
    return slot;
}

/* The object of a live handle of the given kind; the handle is spent and `destroy` is not called (the caller owns the object now). */
WASI_P2_FN void *wasi_p2_table_take(wasi_p2_state *s, uint32_t handle, uint32_t kind) {
    wasi_p2_slot *slot = wasi_p2_table_get(s, handle, kind);
    void *obj = slot->obj;
    slot->live = 0;
    slot->obj = NULL;
    return obj;
}

WASI_P2_FN int wasi_p2_table_alive(wasi_p2_state *s, uint32_t handle, uint32_t kind) {
    uint32_t index = handle & WASI_P2_INDEX_MASK;
    if (index == 0 || index >= s->slot_count) return 0;
    wasi_p2_slot *slot = &s->slots[index];
    return slot->live && slot->generation == (handle >> WASI_P2_INDEX_BITS) && slot->kind == kind;
}

WASI_P2_FN void wasi_p2_table_drop(wasi_p2_state *s, uint32_t handle, uint32_t kind) {
    wasi_p2_slot *slot = wasi_p2_table_get(s, handle, kind);
    slot->live = 0;
    if (slot->destroy) slot->destroy(s, slot->obj);
    slot->obj = NULL;
}

/* memory: little-endian, checked */

WASI_P2_FN uint8_t *wasi_p2_mem(wasi_p2_state *s, uint32_t comp, uint32_t ptr, uint32_t size) {
    if (comp >= s->memories) s->trap(s, "no such memory");
    if ((uint64_t)ptr + size > s->memory[comp].size) s->trap(s, "pointer outside the memory");
    return s->memory[comp].base + ptr;
}

WASI_P2_FN void wasi_p2_store_u32(wasi_p2_state *s, uint32_t comp, uint32_t ptr, uint32_t v) {
    uint8_t *p = wasi_p2_mem(s, comp, ptr, 4);
    for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i));
}

WASI_P2_FN void wasi_p2_store_u64(wasi_p2_state *s, uint32_t comp, uint32_t ptr, uint64_t v) {
    uint8_t *p = wasi_p2_mem(s, comp, ptr, 8);
    for (int i = 0; i < 8; i++) p[i] = (uint8_t)(v >> (8 * i));
}

WASI_P2_FN void wasi_p2_store_u8(wasi_p2_state *s, uint32_t comp, uint32_t ptr, uint8_t v) { *wasi_p2_mem(s, comp, ptr, 1) = v; }

WASI_P2_FN void wasi_p2_store_u16(wasi_p2_state *s, uint32_t comp, uint32_t ptr, uint16_t v) {
    uint8_t *p = wasi_p2_mem(s, comp, ptr, 2);
    p[0] = (uint8_t)v, p[1] = (uint8_t)(v >> 8);
}

WASI_P2_FN uint8_t wasi_p2_load_u8(wasi_p2_state *s, uint32_t comp, uint32_t ptr) { return *wasi_p2_mem(s, comp, ptr, 1); }

WASI_P2_FN uint16_t wasi_p2_load_u16(wasi_p2_state *s, uint32_t comp, uint32_t ptr) {
    const uint8_t *p = wasi_p2_mem(s, comp, ptr, 2);
    return (uint16_t)(p[0] | p[1] << 8);
}

WASI_P2_FN uint32_t wasi_p2_load_u32(wasi_p2_state *s, uint32_t comp, uint32_t ptr) {
    const uint8_t *p = wasi_p2_mem(s, comp, ptr, 4);
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

/* Memory from the component for a list or a string that the host returns (`cabi_realloc`). */
WASI_P2_FN uint32_t wasi_p2_alloc(wasi_p2_state *s, uint32_t comp, uint32_t align, uint32_t size) {
    if (size == 0) return align;
    if (!s->realloc) s->trap(s, "the component has no cabi_realloc");
    uint32_t ptr = s->realloc(s, comp, 0, 0, align, size);
    if (!ptr) s->trap(s, "cabi_realloc failed");
    return ptr;
}

WASI_P2_FN void wasi_p2_string(wasi_p2_state *s, uint32_t comp, const char *text, uint32_t at) {
    uint32_t n = (uint32_t)strlen(text);
    uint32_t ptr = wasi_p2_alloc(s, comp, 1, n);
    if (n) memcpy(wasi_p2_mem(s, comp, ptr, n), text, n);
    wasi_p2_store_u32(s, comp, at, ptr);
    wasi_p2_store_u32(s, comp, at + 4, n);
}

#endif /* WASI_P2_CORE_H */
