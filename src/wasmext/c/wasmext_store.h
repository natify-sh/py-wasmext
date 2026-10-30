/* The store: what a group of instances share and what ends with it. The same for every module; no module, no Python, no wasm2c runtime in this
   file (a host that is not Python uses it as it is). It is a header of `static inline` functions, like wasmext_glue.h: every artifact compiles its own
   copy. See docs/specs/S0002-store.md.

   - an arena of what the store owns (`wasmext_store_own`), freed in the reverse order when the store is closed;
   - a counter of active calls that is split by thread, and a flag `closing`: `close` refuses (WASMEXT_STORE_BUSY) while a call is in flight, so a
     `close` from inside a call is refused too, and after a successful `close` every `enter` fails;
   - a lock that is taken only to add to the arena, to close, and to set or read the text of an error; never held across a call outward;
   - the text of the last refusal.

   A call that races with a `close` that is then refused (BUSY) may fail with "closed" though the store stays open: it is the same as if it had come
   after the close was tried. Nothing else can be wrong: a successful `close` means no call was in flight, and none starts after it. */
#ifndef WASMEXT_STORE_H
#define WASMEXT_STORE_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wasmext_registry.h"

/* results of the functions of the store */
#define WASMEXT_STORE_OK 0
#define WASMEXT_STORE_CLOSED 1 /* the store is closed (or closing) */
#define WASMEXT_STORE_BUSY 2   /* a call is in flight: nothing was closed */
#define WASMEXT_STORE_NOMEM 3
#define WASMEXT_STORE_DUPLICATE 4 /* the pointer is a member of the store already */
#define WASMEXT_STORE_UNKNOWN 5   /* the pointer is not a member of this store (of another store, or of none) */
#define WASMEXT_STORE_WRONG 6     /* the handle is of another store */
#define WASMEXT_STORE_STALE 7     /* the handle is of a member that is gone */
#define WASMEXT_STORE_INCOMPATIBLE 8 /* `attach` refused: the reason is in the caller's buffer (S0008) */

/* ---- atomics and the lock: one thread at a time (WASMEXT_NO_THREADS) needs none ---- */
#if defined(WASMEXT_NO_THREADS)
typedef long wasmext_counter;
#define wasmext_atomic_add(P, D) (*(P) += (D))
#define wasmext_atomic_load(P) (*(P))
#define wasmext_atomic_store(P, V) (*(P) = (V))
#define WASMEXT_THREAD_LOCAL
#define WASMEXT_MUTEX_T int
#define WASMEXT_MUTEX_INIT(M) ((void)(M))
#define WASMEXT_MUTEX_DESTROY(M) ((void)(M))
#define WASMEXT_LOCK(M) ((void)(M))
#define WASMEXT_UNLOCK(M) ((void)(M))
#elif defined(__GNUC__) || defined(__clang__)
#include <pthread.h>
typedef long wasmext_counter;
#define wasmext_atomic_add(P, D) __atomic_add_fetch((P), (D), __ATOMIC_SEQ_CST)
#define wasmext_atomic_load(P) __atomic_load_n((P), __ATOMIC_SEQ_CST)
#define wasmext_atomic_store(P, V) __atomic_store_n((P), (V), __ATOMIC_SEQ_CST)
#define WASMEXT_THREAD_LOCAL __thread
#define WASMEXT_MUTEX_T pthread_mutex_t
#define WASMEXT_MUTEX_INIT(M) pthread_mutex_init((M), NULL)
#define WASMEXT_MUTEX_DESTROY(M) pthread_mutex_destroy(M)
#define WASMEXT_LOCK(M) pthread_mutex_lock(M)
#define WASMEXT_UNLOCK(M) pthread_mutex_unlock(M)
#elif defined(_MSC_VER)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <intrin.h>
typedef long wasmext_counter;
#define wasmext_atomic_add(P, D) (_InterlockedExchangeAdd((P), (D)) + (D))
#define wasmext_atomic_load(P) _InterlockedCompareExchange((P), 0, 0)
#define wasmext_atomic_store(P, V) ((void)_InterlockedExchange((P), (V)))
#define WASMEXT_THREAD_LOCAL __declspec(thread)
#define WASMEXT_MUTEX_T SRWLOCK
#define WASMEXT_MUTEX_INIT(M) InitializeSRWLock(M)
#define WASMEXT_MUTEX_DESTROY(M) ((void)(M))
#define WASMEXT_LOCK(M) AcquireSRWLockExclusive(M)
#define WASMEXT_UNLOCK(M) ReleaseSRWLockExclusive(M)
#else
#error "wasmext_store.h: no atomics for this compiler; define WASMEXT_NO_THREADS where there is one thread at a time"
#endif

/* the lines of the counter of active calls: each on a cache line of its own, a thread uses the one its address of a thread-local variable selects */
#define WASMEXT_STORE_LINES 8
#define WASMEXT_STORE_ERROR_SIZE 256

typedef struct wasmext_arena_node_ {
    void *object;
    void (*release)(void *object);
    struct wasmext_arena_node_ *next;
} wasmext_arena_node;

typedef struct {
    wasmext_counter active;
    char pad_[64 - sizeof(wasmext_counter)];
} wasmext_store_line_;

/* The serial of a store: one for the artifact, taken from a counter that exactly one file defines (WASMEXT_DEFINE_THREAD_STATE, as for the set-up of the thread). */
extern wasmext_counter wasmext_store_serial_;
#ifdef WASMEXT_DEFINE_THREAD_STATE
wasmext_counter wasmext_store_serial_;
#endif

/* The identity of an artifact (one shared library, extension or executable, which has its own copy of the code of the core and of the runtime of wasm2c): the address of a variable
   that exactly one file of the artifact defines, as for the serial above. A store knows the artifacts that made or attached to it (S0008). It is hidden where the compiler can
   say so (as `wasmext_stack_limit` is): with the default visibility the dynamic linker would let one library's variable stand for another's, and two artifacts would have one identity. */
#if (defined(__GNUC__) || defined(__clang__)) && !defined(_WIN32)
extern char wasmext_artifact_ __attribute__((visibility("hidden")));
#else
extern char wasmext_artifact_;
#endif
#ifdef WASMEXT_DEFINE_THREAD_STATE
char wasmext_artifact_;
#endif
#define WASMEXT_ARTIFACT ((const void *)&wasmext_artifact_)

/* The fixed head of a store: the first bytes, read by an artifact that did not make the store, before it reads anything else (`wasmext_store_attach`). Its layout never changes;
   the rest of the store is the same only if `size`, `layout` and `runtime` agree. */
typedef struct {
    uint32_t size;    /* sizeof(wasmext_store) of the artifact that made it */
    uint32_t abi;     /* WASMEXT_ABI of that artifact */
    uint32_t floor;   /* the lowest WASMEXT_ABI of a reader that can use the store */
    uint32_t layout;  /* WASMEXT_CORE_LAYOUT of that artifact: the sizes and offsets of the structs of the core */
    uint32_t runtime; /* WASMEXT_RUNTIME of that artifact: the layout of the structs and of the jump buffer of wasm2c */
    uint32_t flags;   /* none yet */
    uint32_t host_layout; /* WASMEXT_HOST_LAYOUT of the artifact that set the host (0: none, or set from a file that does not know the host): checked by the first call that touches the host */
    void *rt;         /* reserved for the runtime of the store (S0008, 8b): NULL */
} wasmext_store_head;

typedef struct {
    wasmext_store_head head; /* first */
    wasmext_store_line_ lines[WASMEXT_STORE_LINES];
    wasmext_counter closing; /* 1 while `close` decides, and for good once it has succeeded */
    wasmext_counter closed;  /* 1 once the arena is let go */
    WASMEXT_MUTEX_T mutex;
    wasmext_arena_node *arena; /* the last owned first */
    wasmext_arena_node *adopted; /* what the store frees when it is freed (not at the close): the wrappers of the members, which stay valid, closed, until then */
    wasmext_registry registry;
    void *host;      /* the host of WASI (wasmext_host.h), opaque here: set once; the store owns it through the arena */
    void *host_lock; /* its lock (wasmext_rlock.h), for the code that calls into the host from the instance */
    const void **artifacts; /* the artifacts that made the store or attached to it: only their instances may be made in it */
    uint32_t n_artifacts, cap_artifacts;
    char error[WASMEXT_STORE_ERROR_SIZE];
} wasmext_store;

/* One field of a struct in a hash of the layout (S0008): its offset and its size, each weighted by the number `n` of the field in its struct, so that two fields that are swapped
   (even of one size), or one that is moved or resized, change the hash. The structs that another copy of the core reads inline are all hashed this way, field by field. */
#define WASMEXT_LF_(n, T, m) ((uint32_t)((uint32_t)offsetof(T, m) * (2u * (n) + 1u) * 2654435761u + (uint32_t)sizeof(((T *)0)->m) * (2u * (n) + 1u) * 40503u + (n)))
#define WASMEXT_LS_(k, T) ((uint32_t)sizeof(T) * (k))

/* What the head of a store says, for the artifact that makes or attaches: the ABI, the floor, the layout of the core and the layout of the runtime of wasm2c. This file does not know
   the last three (it has no wasm2c, and not the instance), so wasmext_instance.h redefines this once it does; a program with the store alone gets the layout of the store. */
#define WASMEXT_STORE_LAYOUT_ (WASMEXT_LS_(3u, wasmext_store_head) ^ WASMEXT_LF_(0, wasmext_store_head, size) ^ WASMEXT_LF_(1, wasmext_store_head, abi) ^ \
    WASMEXT_LF_(2, wasmext_store_head, floor) ^ WASMEXT_LF_(3, wasmext_store_head, layout) ^ WASMEXT_LF_(4, wasmext_store_head, runtime) ^ WASMEXT_LF_(5, wasmext_store_head, flags) ^ \
    WASMEXT_LF_(6, wasmext_store_head, host_layout) ^ WASMEXT_LF_(7, wasmext_store_head, rt) ^ \
    WASMEXT_LS_(5u, wasmext_store_line_) ^ WASMEXT_LF_(0, wasmext_store_line_, active) ^ WASMEXT_LF_(1, wasmext_store_line_, pad_) ^ \
    WASMEXT_LS_(7u, wasmext_store) ^ WASMEXT_LF_(0, wasmext_store, head) ^ WASMEXT_LF_(1, wasmext_store, lines) ^ WASMEXT_LF_(2, wasmext_store, closing) ^ \
    WASMEXT_LF_(3, wasmext_store, closed) ^ WASMEXT_LF_(4, wasmext_store, mutex) ^ WASMEXT_LF_(5, wasmext_store, arena) ^ WASMEXT_LF_(6, wasmext_store, adopted) ^ \
    WASMEXT_LF_(7, wasmext_store, registry) ^ WASMEXT_LF_(8, wasmext_store, host) ^ WASMEXT_LF_(9, wasmext_store, host_lock) ^ WASMEXT_LF_(10, wasmext_store, artifacts) ^ \
    WASMEXT_LF_(11, wasmext_store, n_artifacts) ^ WASMEXT_LF_(12, wasmext_store, cap_artifacts) ^ WASMEXT_LF_(13, wasmext_store, error) ^ \
    WASMEXT_LS_(11u, wasmext_registry) ^ WASMEXT_LF_(0, wasmext_registry, version) ^ WASMEXT_LF_(1, wasmext_registry, size) ^ WASMEXT_LF_(2, wasmext_registry, serial) ^ \
    WASMEXT_LF_(3, wasmext_registry, slots) ^ WASMEXT_LF_(4, wasmext_registry, count) ^ WASMEXT_LF_(5, wasmext_registry, capacity) ^ WASMEXT_LF_(6, wasmext_registry, free_head) ^ \
    WASMEXT_LF_(7, wasmext_registry, sequence) ^ WASMEXT_LF_(8, wasmext_registry, table) ^ WASMEXT_LF_(9, wasmext_registry, table_capacity) ^ WASMEXT_LF_(10, wasmext_registry, deleted) ^ \
    WASMEXT_LS_(13u, wasmext_slot) ^ WASMEXT_LF_(0, wasmext_slot, key) ^ WASMEXT_LF_(1, wasmext_slot, object) ^ WASMEXT_LF_(2, wasmext_slot, ops) ^ WASMEXT_LF_(3, wasmext_slot, sequence) ^ \
    WASMEXT_LF_(4, wasmext_slot, generation) ^ WASMEXT_LF_(5, wasmext_slot, next_free) ^ WASMEXT_LF_(6, wasmext_slot, used) ^ \
    WASMEXT_LS_(17u, wasmext_owner_ops) ^ WASMEXT_LF_(0, wasmext_owner_ops, retain) ^ WASMEXT_LF_(1, wasmext_owner_ops, release) ^ WASMEXT_LF_(2, wasmext_owner_ops, unlink) ^ \
    WASMEXT_LF_(3, wasmext_owner_ops, close) ^ WASMEXT_LF_(4, wasmext_owner_ops, kind) ^ \
    WASMEXT_LS_(19u, wasmext_arena_node) ^ WASMEXT_LF_(0, wasmext_arena_node, object) ^ WASMEXT_LF_(1, wasmext_arena_node, release) ^ WASMEXT_LF_(2, wasmext_arena_node, next) ^ \
    WASMEXT_LAYOUT_BITS_)
#ifdef WASMEXT_NO_THREADS
#define WASMEXT_LAYOUT_NO_THREADS_ 0x5BD1E995u
#else
#define WASMEXT_LAYOUT_NO_THREADS_ 0u
#endif
#ifdef _MSC_VER
#define WASMEXT_LAYOUT_MSC_ 0x1B873593u
#else
#define WASMEXT_LAYOUT_MSC_ 0u
#endif
#define WASMEXT_LAYOUT_BITS_ (WASMEXT_LAYOUT_NO_THREADS_ ^ WASMEXT_LAYOUT_MSC_)
#define WASMEXT_CORE_IDENT 0u, 0u, WASMEXT_STORE_LAYOUT_, 0u

static inline int wasmext_store_add_artifact_(wasmext_store *s, const void *artifact) {
    uint32_t i;
    for (i = 0; i < s->n_artifacts; i++)
        if (s->artifacts[i] == artifact) return WASMEXT_STORE_OK;
    if (s->n_artifacts == s->cap_artifacts) {
        uint32_t cap = s->cap_artifacts ? s->cap_artifacts * 2 : 4u;
        const void **list = (const void **)realloc((void *)s->artifacts, cap * sizeof(void *));
        if (list == NULL) return WASMEXT_STORE_NOMEM;
        s->artifacts = list;
        s->cap_artifacts = cap;
    }
    s->artifacts[s->n_artifacts++] = artifact;
    return WASMEXT_STORE_OK;
}

/* Makes a store of this artifact: `wasmext_store_new()` (a macro, to put the identity of the core in the head). */
static inline wasmext_store *wasmext_store_new_(uint32_t abi, uint32_t since, uint32_t layout, uint32_t runtime) {
    wasmext_store *s = (wasmext_store *)calloc(1, sizeof(wasmext_store));
    if (s != NULL) {
        s->head.size = (uint32_t)sizeof(wasmext_store);
        s->head.abi = abi;
        s->head.floor = since;
        s->head.layout = layout;
        s->head.runtime = runtime;
        WASMEXT_MUTEX_INIT(&s->mutex);
        wasmext_registry_init(&s->registry, (uint32_t)wasmext_atomic_add(&wasmext_store_serial_, 1));
        if (wasmext_store_add_artifact_(s, WASMEXT_ARTIFACT) != WASMEXT_STORE_OK) {
            WASMEXT_MUTEX_DESTROY(&s->mutex);
            wasmext_registry_destroy(&s->registry);
            free(s);
            return NULL;
        }
    }
    return s;
}
#define wasmext_store_new() wasmext_store_new_(WASMEXT_CORE_IDENT)

/* Whether this artifact made the store or attached to it. A store whose head is not that of this copy (the size, the layout of the core and the runtime of wasm2c that the
   caller says are its own: `wasmext_instance.h` gives the full ones, a store-only layout is not enough) is not looked into, before the lock or anything else past the head is read:
   its other fields may be elsewhere. It is not attached. */
static inline int wasmext_store_has_artifact(wasmext_store *s, uint32_t layout, uint32_t runtime) {
    uint32_t i;
    int found = 0;
    if (s->head.size != (uint32_t)sizeof(wasmext_store) || s->head.layout != layout || s->head.runtime != runtime) return 0;
    WASMEXT_LOCK(&s->mutex);
    for (i = 0; i < s->n_artifacts; i++) found |= s->artifacts[i] == WASMEXT_ARTIFACT;
    WASMEXT_UNLOCK(&s->mutex);
    return found;
}

/* An artifact that did not make the store joins it: `wasmext_store_attach(s, why, cap)` (a macro, as above). WASMEXT_STORE_OK, or WASMEXT_STORE_INCOMPATIBLE with the reason in `why`
   (the caller's buffer: the store may be of a layout that this copy cannot read) when the x of the ABI differs, the reader is below the floor, or the size, the layout of the core or
   the runtime of wasm2c differ; WASMEXT_STORE_CLOSED when the store is closed. The artifact must stay loaded until `wasmext_store_free` returns: the store calls the functions of the
   artifacts that added members, whichever copy closes it. */
static inline int wasmext_store_attach_(wasmext_store *s, uint32_t abi, uint32_t since, uint32_t layout, uint32_t runtime, char *why, size_t cap) {
    int rc;
#define WASMEXT_WHY_(...) do { if (why != NULL && cap > 0) snprintf(why, cap, __VA_ARGS__); } while (0)
    (void)since;
    if (s == NULL) { WASMEXT_WHY_("no store"); return WASMEXT_STORE_INCOMPATIBLE; }
    if ((s->head.abi >> 24) != (abi >> 24)) {
        WASMEXT_WHY_("the store is of x %u of the ABI of wasmext, this copy is of x %u", (unsigned)(s->head.abi >> 24), (unsigned)(abi >> 24));
        return WASMEXT_STORE_INCOMPATIBLE;
    }
    if (abi < s->head.floor) {
        WASMEXT_WHY_("the store needs a reader of the ABI 0x%08x at least, this copy is 0x%08x", (unsigned)s->head.floor, (unsigned)abi);
        return WASMEXT_STORE_INCOMPATIBLE;
    }
    if (s->head.size != (uint32_t)sizeof(wasmext_store)) {
        WASMEXT_WHY_("the store is %u bytes, this copy of the core has a store of %u", (unsigned)s->head.size, (unsigned)sizeof(wasmext_store));
        return WASMEXT_STORE_INCOMPATIBLE;
    }
    if (s->head.layout != layout) {
        WASMEXT_WHY_("the layout of the structs of the core differs (the store 0x%08x, this copy 0x%08x)", (unsigned)s->head.layout, (unsigned)layout);
        return WASMEXT_STORE_INCOMPATIBLE;
    }
    if (s->head.runtime != runtime) {
        WASMEXT_WHY_("the layout of the runtime of wasm2c differs (the store 0x%08x, this copy 0x%08x)", (unsigned)s->head.runtime, (unsigned)runtime);
        return WASMEXT_STORE_INCOMPATIBLE;
    }
#undef WASMEXT_WHY_
    WASMEXT_LOCK(&s->mutex);
    if (wasmext_atomic_load(&s->closing)) rc = WASMEXT_STORE_CLOSED;
    else rc = wasmext_store_add_artifact_(s, WASMEXT_ARTIFACT);
    WASMEXT_UNLOCK(&s->mutex);
    if (rc == WASMEXT_STORE_CLOSED && why != NULL && cap > 0) snprintf(why, cap, "the store is closed");
    return rc;
}
#define wasmext_store_attach(S, WHY, CAP) wasmext_store_attach_((S), WASMEXT_CORE_IDENT, (WHY), (CAP))

static inline int wasmext_store_closed(const wasmext_store *s) {
    return s == NULL || wasmext_atomic_load((wasmext_counter *)&s->closed) != 0;
}

static inline unsigned wasmext_store_line_of_(void) {
#ifdef WASMEXT_NO_THREADS
    return 0;
#else
    static WASMEXT_THREAD_LOCAL char here_;
    return (unsigned)(((uintptr_t)&here_ >> 6) % WASMEXT_STORE_LINES);
#endif
}

/* A call into the store begins: the number of its line (to give back to `wasmext_store_leave`), or -1 when the store is closed or closing. The order is the
   whole proof: `enter` adds, then reads the flag; `close` raises the flag, then reads the counters; both are sequentially consistent, so either the call
   sees the flag or `close` sees the call. */
static inline int wasmext_store_enter(wasmext_store *s) {
    unsigned line = wasmext_store_line_of_();
    wasmext_atomic_add(&s->lines[line].active, 1);
    if (wasmext_atomic_load(&s->closing)) {
        wasmext_atomic_add(&s->lines[line].active, -1);
        return -1;
    }
    return (int)line;
}

static inline void wasmext_store_leave(wasmext_store *s, int line) {
    wasmext_atomic_add(&s->lines[line].active, -1);
}

/* The store owns `object` until it is closed, and then `release(object)` is called (not held under the lock), in the reverse order of owning. On a refusal
   the object is not owned: the caller still frees it. */
static inline int wasmext_store_own(wasmext_store *s, void *object, void (*release)(void *object)) {
    wasmext_arena_node *node = (wasmext_arena_node *)malloc(sizeof(wasmext_arena_node));
    if (node == NULL) return WASMEXT_STORE_NOMEM;
    WASMEXT_LOCK(&s->mutex);
    if (wasmext_atomic_load(&s->closing)) {
        WASMEXT_UNLOCK(&s->mutex);
        free(node);
        return WASMEXT_STORE_CLOSED;
    }
    node->object = object;
    node->release = release;
    node->next = s->arena;
    s->arena = node;
    WASMEXT_UNLOCK(&s->mutex);
    return WASMEXT_STORE_OK;
}

/* The store has one host. It is given once: WASMEXT_STORE_BUSY if there is one already (nothing is changed), the refusals of `wasmext_store_own` otherwise (then the
   host is not owned and the caller frees it). `release` is called at the close, as for any owned object; `lock` is the lock of the host (may be NULL). */
static inline int wasmext_store_set_host_(wasmext_store *s, void *host, void (*release)(void *object), void *lock, uint32_t host_layout) {
    int rc;
    WASMEXT_LOCK(&s->mutex);
    if (s->host != NULL) {
        WASMEXT_UNLOCK(&s->mutex);
        return WASMEXT_STORE_BUSY;
    }
    WASMEXT_UNLOCK(&s->mutex);
    rc = wasmext_store_own(s, host, release);
    if (rc != WASMEXT_STORE_OK) return rc;
    WASMEXT_LOCK(&s->mutex);
    s->host = host;
    s->host_lock = lock;
    s->head.host_layout = host_layout;
    WASMEXT_UNLOCK(&s->mutex);
    return WASMEXT_STORE_OK;
}
/* ... `wasmext_store_set_host(s, host, release, lock)` is a macro that adds the layout of the host (wasmext_host.h redefines WASMEXT_HOST_LAYOUT_ID once it knows the struct; 0 before). */
#define WASMEXT_HOST_LAYOUT_ID 0u
#define wasmext_store_set_host(S, H, R, L) wasmext_store_set_host_((S), (H), (R), (L), WASMEXT_HOST_LAYOUT_ID)
static inline void *wasmext_store_host(wasmext_store *s) {
    void *host;
    WASMEXT_LOCK(&s->mutex);
    host = s->host;
    WASMEXT_UNLOCK(&s->mutex);
    return host;
}
/* the layout of the host as the artifact that set it said it (0: not said) */
static inline uint32_t wasmext_store_host_layout(wasmext_store *s) {
    uint32_t layout;
    WASMEXT_LOCK(&s->mutex);
    layout = s->head.host_layout;
    WASMEXT_UNLOCK(&s->mutex);
    return layout;
}
static inline void *wasmext_store_host_lock(wasmext_store *s) {
    void *lock;
    WASMEXT_LOCK(&s->mutex);
    lock = s->host_lock;
    WASMEXT_UNLOCK(&s->mutex);
    return lock;
}

/* The text of the last refusal (cut to fit), and a copy of it for the caller. */
static inline void wasmext_store_set_error(wasmext_store *s, const char *text) {
    WASMEXT_LOCK(&s->mutex);
    strncpy(s->error, text, WASMEXT_STORE_ERROR_SIZE - 1);
    s->error[WASMEXT_STORE_ERROR_SIZE - 1] = 0;
    WASMEXT_UNLOCK(&s->mutex);
}
static inline void wasmext_store_error(wasmext_store *s, char *buffer, size_t capacity) {
    if (capacity == 0) return;
    WASMEXT_LOCK(&s->mutex);
    strncpy(buffer, s->error, capacity - 1);
    buffer[capacity - 1] = 0;
    WASMEXT_UNLOCK(&s->mutex);
}

/* ---- the members (docs/specs/S0004-owners-registry.md) ---- */

static inline int wasmext_store_registry_code_(int rc) {
    switch (rc) {
        case WASMEXT_REGISTRY_NOMEM: return WASMEXT_STORE_NOMEM;
        case WASMEXT_REGISTRY_DUPLICATE: return WASMEXT_STORE_DUPLICATE;
        case WASMEXT_REGISTRY_UNKNOWN: return WASMEXT_STORE_UNKNOWN;
        case WASMEXT_REGISTRY_WRONG_STORE: return WASMEXT_STORE_WRONG;
        case WASMEXT_REGISTRY_STALE: return WASMEXT_STORE_STALE;
        default: return WASMEXT_STORE_OK;
    }
}

/* Makes `object` a member under `key` (for an instance, the `module_instance` pointer of its funcrefs). The store holds it until the close; `ops` (may be NULL) says what it does
   with it (see wasmext_registry.h). WASMEXT_STORE_CLOSED when the store is closed or closing, DUPLICATE if the key is a member already. */
static inline int wasmext_store_register(wasmext_store *s, void *key, void *object, const wasmext_owner_ops *ops, wasmext_owner *out) {
    int rc;
    WASMEXT_LOCK(&s->mutex);
    if (wasmext_atomic_load(&s->closing)) {
        WASMEXT_UNLOCK(&s->mutex);
        return WASMEXT_STORE_CLOSED;
    }
    rc = wasmext_store_registry_code_(wasmext_registry_add(&s->registry, key, object, ops, out));
    WASMEXT_UNLOCK(&s->mutex);
    return rc;
}

/* The handle of the member under `key`, or WASMEXT_STORE_UNKNOWN: this store has no such member (the pointer is of another store, or of none: the registry of one store cannot
   tell which; the front end reports it as a wrong store). */
static inline int wasmext_store_find(wasmext_store *s, const void *key, wasmext_owner *out) {
    int rc;
    WASMEXT_LOCK(&s->mutex);
    rc = wasmext_store_registry_code_(wasmext_registry_find(&s->registry, key, out));
    WASMEXT_UNLOCK(&s->mutex);
    return rc;
}

/* The same, if the member is of this kind (WASMEXT_KIND_*): a pointer of an instance is not accepted where a reference is expected, nor the other way. */
static inline int wasmext_store_find_kind(wasmext_store *s, const void *key, int kind, wasmext_owner *out) {
    int rc;
    WASMEXT_LOCK(&s->mutex);
    rc = wasmext_store_registry_code_(wasmext_registry_find_kind(&s->registry, key, kind, out));
    WASMEXT_UNLOCK(&s->mutex);
    return rc;
}

/* Sets `*slot` from NULL to `value`, once (for a process-wide cell that is written at a link and read by running code): 1 if it was NULL (now `value`) or was `value` already, else 0. */
static inline int wasmext_cell_set_once(void *volatile *slot, void *value) {
#if defined(_WIN32)
    void *old = _InterlockedCompareExchangePointer((void *volatile *)slot, value, NULL);
#elif defined(__GNUC__) || defined(__clang__)
    void *old = NULL;
    __atomic_compare_exchange_n(slot, &old, value, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST);
#else
    void *old = *slot;
    if (old == NULL) *slot = value;
#endif
    return old == NULL || old == value;
}

/* The object of a handle: WASMEXT_STORE_OK, WASMEXT_STORE_WRONG (a handle of another store) or WASMEXT_STORE_STALE (of a member that is gone). */
static inline int wasmext_store_member(wasmext_store *s, wasmext_owner owner, void **object) {
    int rc;
    WASMEXT_LOCK(&s->mutex);
    rc = wasmext_store_registry_code_(wasmext_registry_object(&s->registry, owner, object));
    WASMEXT_UNLOCK(&s->mutex);
    return rc;
}

/* Takes a member out before the close (the ops are not run: the caller releases what it holds). The slot is used again later with another generation. */
static inline int wasmext_store_unregister(wasmext_store *s, wasmext_owner owner) {
    int rc;
    WASMEXT_LOCK(&s->mutex);
    rc = wasmext_store_registry_code_(wasmext_registry_remove(&s->registry, owner));
    WASMEXT_UNLOCK(&s->mutex);
    return rc;
}

/* For a front end that shows its members to a cyclic collector (`tp_traverse` of CPython): calls `visit(object, arg)` for each member and for each object of the arena, with
   the lock held (so `visit` must not call the store). A member with an `object` of NULL is skipped. */
static inline void wasmext_store_each(wasmext_store *s, void (*visit)(void *object, void *arg), void *arg) {
    wasmext_arena_node *node;
    uint32_t i;
    WASMEXT_LOCK(&s->mutex);
    for (i = 0; i < s->registry.count; i++)
        if (s->registry.slots[i].used && s->registry.slots[i].object != NULL) visit(s->registry.slots[i].object, arg);
    for (node = s->arena; node != NULL; node = node->next) visit(node->object, arg);
    WASMEXT_UNLOCK(&s->mutex);
}

/* The store frees `object` (with `free_fn`) when it is freed, not when it is closed: what stays valid, closed, after the close (the wrapper of an instance). */
static inline int wasmext_store_adopt(wasmext_store *s, void *object, void (*free_fn)(void *object)) {
    wasmext_arena_node *node = (wasmext_arena_node *)malloc(sizeof(wasmext_arena_node));
    if (node == NULL) return WASMEXT_STORE_NOMEM;
    node->object = object;
    node->release = free_fn;
    WASMEXT_LOCK(&s->mutex);
    node->next = s->adopted;
    s->adopted = node;
    WASMEXT_UNLOCK(&s->mutex);
    return WASMEXT_STORE_OK;
}
/* ... and takes it back (the caller frees it): WASMEXT_STORE_UNKNOWN if it was not adopted. */
static inline int wasmext_store_unadopt(wasmext_store *s, void *object) {
    wasmext_arena_node **link, *node = NULL;
    WASMEXT_LOCK(&s->mutex);
    for (link = &s->adopted; *link != NULL; link = &(*link)->next)
        if ((*link)->object == object) {
            node = *link;
            *link = node->next;
            break;
        }
    WASMEXT_UNLOCK(&s->mutex);
    if (node == NULL) return WASMEXT_STORE_UNKNOWN;
    free(node);
    return WASMEXT_STORE_OK;
}

/* Closes the store: WASMEXT_STORE_OK (also when it was closed already), or WASMEXT_STORE_BUSY with nothing done when a call is in flight (a call of this very
   thread is one, so a `close` from inside a call is refused, never waits). Then, outside the lock: (1) `unlink` of every member, newest first, so that an importer lets go of
   what it was linked to; (2) `close` of every member in the same order; (3) `release` of the objects that members retained; (4) the arena, in the reverse order of owning. */
static inline int wasmext_store_close(wasmext_store *s) {
    wasmext_arena_node *node;
    wasmext_slot **members;
    uint32_t n, i;
    long sum = 0;
    WASMEXT_LOCK(&s->mutex);
    if (wasmext_atomic_load(&s->closed)) {
        WASMEXT_UNLOCK(&s->mutex);
        return WASMEXT_STORE_OK;
    }
    wasmext_atomic_store(&s->closing, 1);
    for (i = 0; i < WASMEXT_STORE_LINES; i++) sum += wasmext_atomic_load(&s->lines[i].active);
    if (sum != 0) {
        wasmext_atomic_store(&s->closing, 0);
        WASMEXT_UNLOCK(&s->mutex);
        return WASMEXT_STORE_BUSY;
    }
    members = wasmext_registry_newest_first(&s->registry, &n);
    node = s->arena;
    s->arena = NULL;
    wasmext_atomic_store(&s->closed, 1);
    WASMEXT_UNLOCK(&s->mutex);
    for (i = 0; i < n; i++)
        if (members[i]->ops != NULL && members[i]->ops->unlink != NULL) members[i]->ops->unlink(members[i]->object);
    for (i = 0; i < n; i++)
        if (members[i]->ops != NULL && members[i]->ops->close != NULL) members[i]->ops->close(members[i]->object);
    for (i = 0; i < n; i++)
        if (members[i]->ops != NULL && members[i]->ops->release != NULL) members[i]->ops->release(members[i]->object);
    free(members);
    while (node != NULL) {
        wasmext_arena_node *next = node->next;
        if (node->release != NULL) node->release(node->object);
        free(node);
        node = next;
    }
    return WASMEXT_STORE_OK;
}

/* Frees the memory of the store: it closes it first, and answers WASMEXT_STORE_BUSY (nothing freed) when a call is in flight. What was adopted is freed; nothing may refer to the
   store, or to what it adopted, afterwards. */
static inline int wasmext_store_free(wasmext_store *s) {
    int rc;
    wasmext_arena_node *node;
    if (s == NULL) return WASMEXT_STORE_OK;
    rc = wasmext_store_close(s);
    if (rc != WASMEXT_STORE_OK) return rc;
    for (node = s->adopted; node != NULL;) {
        wasmext_arena_node *next = node->next;
        if (node->release != NULL) node->release(node->object);
        free(node);
        node = next;
    }
    wasmext_registry_destroy(&s->registry);
    WASMEXT_MUTEX_DESTROY(&s->mutex);
    free((void *)s->artifacts);
    free(s);
    return WASMEXT_STORE_OK;
}

#endif
