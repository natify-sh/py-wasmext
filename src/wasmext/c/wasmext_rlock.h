/* A recursive lock that can be let go down to a level. The host of WASI is shared by every instance of a store, and the state of fusedwasi has no lock (it is not
   the library's business: the runtime that embeds it decides), so wasmext takes this one around each call into fusedwasi. It is recursive because a hook of the host
   (a stream, the clock) may call the module back, and `release_to` exists because a trap leaves a function of fusedwasi by a long jump, which skips its unlock: the call that
   catches the trap lets go of whatever was taken below it. No Python, no module. */
#ifndef WASMEXT_RLOCK_H
#define WASMEXT_RLOCK_H

#include "wasmext_store.h"

#if defined(WASMEXT_NO_THREADS)
#define WASMEXT_THREAD_ID() ((uintptr_t)1)
#elif defined(__GNUC__) || defined(__clang__)
#define WASMEXT_THREAD_ID() ((uintptr_t)pthread_self())
#else
#define WASMEXT_THREAD_ID() ((uintptr_t)GetCurrentThreadId())
#endif

typedef struct {
    WASMEXT_MUTEX_T mutex;
    wasmext_counter owner; /* the thread that holds it (0: none); written only by the holder */
    long depth;            /* how many times the holder took it; read only by the holder */
} wasmext_rlock;

static inline void wasmext_rlock_init(wasmext_rlock *l) {
    WASMEXT_MUTEX_INIT(&l->mutex);
    l->owner = 0;
    l->depth = 0;
}
static inline void wasmext_rlock_destroy(wasmext_rlock *l) { WASMEXT_MUTEX_DESTROY(&l->mutex); }

static inline void wasmext_rlock_lock(wasmext_rlock *l) {
    wasmext_counter me = (wasmext_counter)WASMEXT_THREAD_ID();
    if (wasmext_atomic_load(&l->owner) == me) {
        l->depth++;
        return;
    }
    WASMEXT_LOCK(&l->mutex);
    wasmext_atomic_store(&l->owner, me);
    l->depth = 1;
}
static inline void wasmext_rlock_unlock(wasmext_rlock *l) {
    if (--l->depth == 0) {
        wasmext_atomic_store(&l->owner, 0);
        WASMEXT_UNLOCK(&l->mutex);
    }
}
/* how many times this thread holds it (0 when it does not) */
static inline long wasmext_rlock_depth(wasmext_rlock *l) {
    return wasmext_atomic_load(&l->owner) == (wasmext_counter)WASMEXT_THREAD_ID() ? l->depth : 0;
}
/* lets go of what this thread took above `level` (a trap skipped the unlocks) */
static inline void wasmext_rlock_release_to(wasmext_rlock *l, long level) {
    while (wasmext_rlock_depth(l) > level) wasmext_rlock_unlock(l);
}

#endif
