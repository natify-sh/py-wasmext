/* Micro-benchmark for docs/context_concept.md, "Overhead":
 *  1. the registry: a lookup of the owner by the pointer `module_instance` (open addressing), under a mutex, with a rwlock, and with no lock;
 *     N members; 1, 2 and 4 threads on ONE context (the worst case: one lock) and on one context EACH (no sharing).
 *  2. the entry of a call: a counter of active calls plus a "closed" check, atomic (seq_cst and relaxed) and plain, against a bare indirect call;
 *     1 thread, and 4 threads on the SAME counter (one context) against one counter each (cache lines apart).
 * cc -O2 -pthread bench.c -o bench && ./bench
 */
#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static double now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec * 1e-9;
}

/* ---- 1. registry ---- */
typedef struct { const void* key; void* owner; } entry_t;
typedef struct {
  entry_t* slots; size_t mask;
  pthread_mutex_t mu; pthread_rwlock_t rw;
} ctx_t;

static size_t hash(const void* p) { uintptr_t x = (uintptr_t)p; x ^= x >> 33; x *= 0xff51afd7ed558ccdULL; x ^= x >> 33; return (size_t)x; }

static void ctx_init(ctx_t* c, size_t n, char** keys) {
  size_t cap = 1; while (cap < n * 2) cap <<= 1;
  c->slots = calloc(cap, sizeof(entry_t)); c->mask = cap - 1;
  pthread_mutex_init(&c->mu, NULL); pthread_rwlock_init(&c->rw, NULL);
  for (size_t i = 0; i < n; i++) {
    size_t h = hash(keys[i]) & c->mask;
    while (c->slots[h].key) h = (h + 1) & c->mask;
    c->slots[h].key = keys[i]; c->slots[h].owner = keys[i] + 1;
  }
}
static inline void* find(ctx_t* c, const void* k) {
  size_t h = hash(k) & c->mask;
  while (c->slots[h].key) { if (c->slots[h].key == k) return c->slots[h].owner; h = (h + 1) & c->mask; }
  return NULL;
}
enum { NOLOCK, MUTEX, RWLOCK };
typedef struct { ctx_t* ctx; char** keys; size_t n; long iters; int mode; void* sink; } rjob_t;

static void* rworker(void* a) {
  rjob_t* j = a; uintptr_t acc = 0; uint32_t r = 12345;
  for (long i = 0; i < j->iters; i++) {
    r = r * 1664525u + 1013904223u;
    const void* k = j->keys[(r >> 8) % j->n];
    void* o;
    if (j->mode == MUTEX) { pthread_mutex_lock(&j->ctx->mu); o = find(j->ctx, k); pthread_mutex_unlock(&j->ctx->mu); }
    else if (j->mode == RWLOCK) { pthread_rwlock_rdlock(&j->ctx->rw); o = find(j->ctx, k); pthread_rwlock_unlock(&j->ctx->rw); }
    else o = find(j->ctx, k);
    acc += (uintptr_t)o;
  }
  j->sink = (void*)acc; return NULL;
}

static double run_registry(size_t n, int threads, int shared, int mode, long iters) {
  char* pool = malloc(n * 64 + 64); char** keys = malloc(n * sizeof(char*));
  for (size_t i = 0; i < n; i++) keys[i] = pool + i * 64;
  ctx_t* ctxs = calloc(threads, sizeof(ctx_t));
  for (int t = 0; t < (shared ? 1 : threads); t++) ctx_init(&ctxs[t], n, keys);
  pthread_t th[8]; rjob_t jobs[8];
  double t0 = now();
  for (int t = 0; t < threads; t++) {
    jobs[t] = (rjob_t){&ctxs[shared ? 0 : t], keys, n, iters, mode, NULL};
    pthread_create(&th[t], NULL, rworker, &jobs[t]);
  }
  for (int t = 0; t < threads; t++) pthread_join(th[t], NULL);
  double dt = now() - t0;
  return dt / (double)(iters) * 1e9;   /* ns per lookup, per thread (wall time / iterations of one thread) */
}

/* ---- 2. entry of a call ---- */
typedef struct { _Alignas(64) atomic_long active; atomic_int closed; char pad[48]; } guard_t;
static long plain_active; static int plain_closed;
static long __attribute__((noinline)) body(long x) { return x * 3 + 1; }
static long (*volatile body_ptr)(long) = body;

enum { BARE, PLAIN, ATOMIC_SC, ATOMIC_RELAXED };
typedef struct { guard_t* g; long iters; int mode; long sink; } cjob_t;
static void* cworker(void* a) {
  cjob_t* j = a; long acc = 0;
  for (long i = 0; i < j->iters; i++) {
    switch (j->mode) {
      case BARE: acc += body_ptr(i); break;
      case PLAIN:
        if (__builtin_expect(plain_closed, 0)) abort();
        plain_active++; acc += body_ptr(i); plain_active--; break;
      case ATOMIC_SC:
        atomic_fetch_add(&j->g->active, 1);
        if (__builtin_expect(atomic_load(&j->g->closed), 0)) abort();
        acc += body_ptr(i); atomic_fetch_sub(&j->g->active, 1); break;
      case ATOMIC_RELAXED:
        atomic_fetch_add_explicit(&j->g->active, 1, memory_order_acquire);
        if (__builtin_expect(atomic_load_explicit(&j->g->closed, memory_order_relaxed), 0)) abort();
        acc += body_ptr(i); atomic_fetch_sub_explicit(&j->g->active, 1, memory_order_release); break;
    }
  }
  j->sink = acc; return NULL;
}
static double run_call(int threads, int shared, int mode, long iters) {
  guard_t* g = aligned_alloc(64, sizeof(guard_t) * 8); for (int i = 0; i < 8; i++) { atomic_init(&g[i].active, 0); atomic_init(&g[i].closed, 0); }
  pthread_t th[8]; cjob_t jobs[8]; double t0 = now();
  for (int t = 0; t < threads; t++) { jobs[t] = (cjob_t){&g[shared ? 0 : t], iters, mode, 0}; pthread_create(&th[t], NULL, cworker, &jobs[t]); }
  for (int t = 0; t < threads; t++) pthread_join(th[t], NULL);
  return (now() - t0) / (double)iters * 1e9;
}

int main(void) {
  const char* modes[] = {"no lock", "mutex", "rwlock"};
  printf("1. lookup of the owner by pointer (ns per lookup, wall time per thread's iterations)\n");
  printf("%-9s %-8s %-9s %9s %9s %9s\n", "members", "threads", "contexts", "no lock", "mutex", "rwlock");
  size_t ns[] = {10, 1000, 100000, 1000000};
  for (int a = 0; a < 4; a++)
    for (int t = 1; t <= 4; t *= (t == 1 ? 2 : 2))
      for (int sh = 1; sh >= 0; sh--) {
        if (t == 1 && !sh) continue;
        printf("%-9zu %-8d %-9s", ns[a], t, sh ? "one" : "each");
        for (int m = 0; m < 3; m++) printf(" %9.1f", run_registry(ns[a], t, sh, m, ns[a] >= 100000 ? 2000000 : 5000000));
        printf("\n");
      }
  (void)modes;
  printf("\n2. the entry of a call (ns per call)\n%-30s %9s %9s\n", "", "1 thread", "4 threads");
  const char* names[] = {"bare indirect call", "plain counter + check (GIL)", "atomic seq_cst counter + check", "atomic acq/rel counter + check"};
  for (int m = 0; m < 4; m++) {
    double one = run_call(1, 0, m, 50000000);
    if (m == PLAIN) { printf("%-30s %9.2f %9s\n", names[m], one, "(racy; not run)"); continue; }
    double sh = run_call(4, 1, m, 20000000), each = run_call(4, 0, m, 20000000);
    printf("%-30s %9.2f   same counter %.2f, own counter %.2f\n", names[m], one, sh, each);
  }
  return 0;
}
