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

/* results of the functions of the store */
#define WASMEXT_STORE_OK 0
#define WASMEXT_STORE_CLOSED 1 /* the store is closed (or closing) */
#define WASMEXT_STORE_BUSY 2   /* a call is in flight: nothing was closed */
#define WASMEXT_STORE_NOMEM 3

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

typedef struct {
    wasmext_store_line_ lines[WASMEXT_STORE_LINES];
    wasmext_counter closing; /* 1 while `close` decides, and for good once it has succeeded */
    wasmext_counter closed;  /* 1 once the arena is let go */
    WASMEXT_MUTEX_T mutex;
    wasmext_arena_node *arena; /* the last owned first */
    void *host;      /* the host of WASI (wasmext_host.h), opaque here: set once; the store owns it through the arena */
    void *host_lock; /* its lock (wasmext_rlock.h), for the code that calls into the host from the instance */
    char error[WASMEXT_STORE_ERROR_SIZE];
} wasmext_store;

static inline wasmext_store *wasmext_store_new(void) {
    wasmext_store *s = (wasmext_store *)calloc(1, sizeof(wasmext_store));
    if (s != NULL) WASMEXT_MUTEX_INIT(&s->mutex);
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

/* Closes the store: WASMEXT_STORE_OK (also when it was closed already), or WASMEXT_STORE_BUSY with nothing done when a call is in flight (a call of this very
   thread is one, so a `close` from inside a call is refused, never waits). The arena is let go in the reverse order, outside the lock. */
static inline int wasmext_store_close(wasmext_store *s) {
    wasmext_arena_node *node;
    long sum = 0;
    WASMEXT_LOCK(&s->mutex);
    if (wasmext_atomic_load(&s->closed)) {
        WASMEXT_UNLOCK(&s->mutex);
        return WASMEXT_STORE_OK;
    }
    wasmext_atomic_store(&s->closing, 1);
    for (int i = 0; i < WASMEXT_STORE_LINES; i++) sum += wasmext_atomic_load(&s->lines[i].active);
    if (sum != 0) {
        wasmext_atomic_store(&s->closing, 0);
        WASMEXT_UNLOCK(&s->mutex);
        return WASMEXT_STORE_BUSY;
    }
    node = s->arena;
    s->arena = NULL;
    wasmext_atomic_store(&s->closed, 1);
    WASMEXT_UNLOCK(&s->mutex);
    while (node != NULL) {
        wasmext_arena_node *next = node->next;
        if (node->release != NULL) node->release(node->object);
        free(node);
        node = next;
    }
    return WASMEXT_STORE_OK;
}

/* Frees the memory of the store: it closes it first, and answers WASMEXT_STORE_BUSY (nothing freed) when a call is in flight. Nothing may refer to the store afterwards. */
static inline int wasmext_store_free(wasmext_store *s) {
    int rc;
    if (s == NULL) return WASMEXT_STORE_OK;
    rc = wasmext_store_close(s);
    if (rc != WASMEXT_STORE_OK) return rc;
    WASMEXT_MUTEX_DESTROY(&s->mutex);
    free(s);
    return WASMEXT_STORE_OK;
}

#endif
