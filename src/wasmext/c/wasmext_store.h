/* The store: what a group of instances share and what ends with it. The same for every module; no module, no Python, no wasm2c runtime in this
   file (a host that is not Python uses it as it is). It is a header of `static inline` functions, like wasmext_glue.h: every artifact compiles its own
   copy. See docs/step2_store.md.

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

typedef struct {
    wasmext_store_line_ lines[WASMEXT_STORE_LINES];
    wasmext_counter closing; /* 1 while `close` decides, and for good once it has succeeded */
    wasmext_counter closed;  /* 1 once the arena is let go */
    WASMEXT_MUTEX_T mutex;
    wasmext_arena_node *arena; /* the last owned first */
    wasmext_arena_node *adopted; /* what the store frees when it is freed (not at the close): the wrappers of the members, which stay valid, closed, until then */
    wasmext_registry registry;
    void *host;      /* the host of WASI (wasmext_host.h), opaque here: set once; the store owns it through the arena */
    void *host_lock; /* its lock (wasmext_rlock.h), for the code that calls into the host from the instance */
    char error[WASMEXT_STORE_ERROR_SIZE];
} wasmext_store;

static inline wasmext_store *wasmext_store_new(void) {
    wasmext_store *s = (wasmext_store *)calloc(1, sizeof(wasmext_store));
    if (s != NULL) {
        WASMEXT_MUTEX_INIT(&s->mutex);
        wasmext_registry_init(&s->registry, (uint32_t)wasmext_atomic_add(&wasmext_store_serial_, 1));
    }
    return s;
}

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
static inline int wasmext_store_set_host(wasmext_store *s, void *host, void (*release)(void *object), void *lock) {
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
    WASMEXT_UNLOCK(&s->mutex);
    return WASMEXT_STORE_OK;
}
static inline void *wasmext_store_host(wasmext_store *s) {
    void *host;
    WASMEXT_LOCK(&s->mutex);
    host = s->host;
    WASMEXT_UNLOCK(&s->mutex);
    return host;
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

/* ---- the members (docs/step4_owners.md) ---- */

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
    free(s);
    return WASMEXT_STORE_OK;
}

#endif
