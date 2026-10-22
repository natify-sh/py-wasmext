/* The same measurement as bench.c, around REAL calls into a wasm2c module through the C API of a wasmext shared library (no Python anywhere):
 * the entry guard of a call (counter of active calls + "closed" check, or a registry lookup under a mutex) around bm_add (a few ns of work) and bm_work(n) (a loop).
 * Threads of this host call into instances: each thread its own instance, or all of them the same one. Build the library first (see README.md).
 * cc -O2 -pthread real.c -I<dir with bm_api.h> -L<dir with libbm.so> -lbm -Wl,-rpath,<dir> -o real && ./real
 */
#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "bm_api.h"

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

typedef struct { _Alignas(64) atomic_long active; atomic_int closed; } guard_t;       /* a line of its own */
typedef struct { _Alignas(64) pthread_mutex_t mu; void* owner; } registry_t;           /* one context's registry (reduced to the lock + a lookup) */
enum { BARE, PLAIN, ATOMIC_OWN, ATOMIC_CTX, LOOKUP, ATOMIC_INST };
static const char* names[] = {"bare call", "plain counter+check", "atomic per thread", "atomic per context", "mutex+lookup per call", "atomic per instance"};
static long plain_active; static int plain_closed;
static guard_t ctx_guard; static registry_t registry = {PTHREAD_MUTEX_INITIALIZER, NULL};
static void* table[1024];

typedef struct { bm_t* m; guard_t* own; guard_t* inst; int mode; int work; long iters; long sink; } job_t;

static void* worker(void* a) {
  job_t* j = a; int32_t r = 0; long acc = 0;
  bm_add(j->m, 1, 2, &r);   /* the first call sets the thread up for traps */
  for (long i = 0; i < j->iters; i++) {
    switch (j->mode) {
      case PLAIN: if (__builtin_expect(plain_closed, 0)) abort(); plain_active++; break;
      case ATOMIC_OWN: atomic_fetch_add(&j->own->active, 1); if (__builtin_expect(atomic_load(&j->own->closed), 0)) abort(); break;
      case ATOMIC_CTX: atomic_fetch_add(&ctx_guard.active, 1); if (__builtin_expect(atomic_load(&ctx_guard.closed), 0)) abort(); break;
      case ATOMIC_INST: atomic_fetch_add(&j->inst->active, 1); if (__builtin_expect(atomic_load(&j->inst->closed), 0)) abort(); break;
      case LOOKUP: pthread_mutex_lock(&registry.mu); registry.owner = table[(i * 2654435761u) & 1023]; pthread_mutex_unlock(&registry.mu); break;
      default: break;
    }
    if (j->work) bm_work(j->m, j->work, &r); else bm_add(j->m, (int32_t)i, 2, &r);
    switch (j->mode) {
      case PLAIN: plain_active--; break;
      case ATOMIC_OWN: atomic_fetch_sub(&j->own->active, 1); break;
      case ATOMIC_CTX: atomic_fetch_sub(&ctx_guard.active, 1); break;
      case ATOMIC_INST: atomic_fetch_sub(&j->inst->active, 1); break;
      default: break;
    }
    acc += r;
  }
  j->sink = acc; bm_thread_free(); return NULL;
}

/* ns per call, per thread (wall time over the iterations of one thread) */
static double run(int threads, int same_instance, int mode, int work, long iters) {
  bm_t* shared = NULL; int err = 0;
  if (same_instance) { shared = bm_new(NULL, &err); bm_instantiate(shared); }
  pthread_t th[8]; job_t jobs[8]; guard_t* g = aligned_alloc(64, sizeof(guard_t) * 8);
  for (int t = 0; t < threads; t++) {
    atomic_init(&g[t].active, 0); atomic_init(&g[t].closed, 0);
    bm_t* m = shared; if (!m) { m = bm_new(NULL, &err); bm_instantiate(m); }
    jobs[t] = (job_t){m, &g[t], &g[same_instance ? 0 : t], mode, work, iters, 0};
  }
  double t0 = now();
  for (int t = 0; t < threads; t++) pthread_create(&th[t], NULL, worker, &jobs[t]);
  for (int t = 0; t < threads; t++) pthread_join(th[t], NULL);
  double dt = now() - t0;
  for (int t = 0; t < threads; t++) if (!same_instance) bm_free(jobs[t].m);
  if (shared) bm_free(shared);
  free(g);
  return dt / (double)iters * 1e9;
}

int main(void) {
  struct { const char* name; int work; long iters; } loads[] = {{"add (a few ns of work)", 0, 20000000}, {"work(1000) (about 1 us)", 1000, 1000000}, {"work(100000) (about 100 us)", 100000, 20000}};
  for (int l = 0; l < 3; l++) {
    printf("\n%s: ns per call\n%-24s %10s %22s %22s\n", loads[l].name, "", "1 thread", "4 threads, own inst.", "4 threads, same inst.");
    for (int m = 0; m < 6; m++) {
      printf("%-24s %10.1f", names[m], run(1, 0, m, loads[l].work, loads[l].iters));
      if (m == PLAIN) { printf(" %22s %22s\n", "not safe (the GIL's)", "not safe (the GIL's)"); continue; }   /* one thread at a time only */
      printf(" %22.1f %22.1f\n", run(4, 0, m, loads[l].work, loads[l].iters), run(4, 1, m, loads[l].work, loads[l].iters));
    }
  }
  return 0;
}
