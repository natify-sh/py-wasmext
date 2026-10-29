/* Tests of wasmext_rlock.h in plain C. Exit 0 and "ok" when all pass. */
#include <stdio.h>
#include "wasmext_rlock.h"

#ifdef _WIN32
#include <process.h>
typedef HANDLE thread_t;
#define THREAD_RESULT unsigned __stdcall
static void thread_start(thread_t *t, unsigned (__stdcall *f)(void *), void *arg) { *t = (HANDLE)_beginthreadex(NULL, 0, f, arg, 0, NULL); }
static void thread_join(thread_t t) { WaitForSingleObject(t, INFINITE); CloseHandle(t); }
#else
typedef pthread_t thread_t;
#define THREAD_RESULT void *
static void thread_start(thread_t *t, THREAD_RESULT (*f)(void *), void *arg) { pthread_create(t, NULL, f, arg); }
static void thread_join(thread_t t) { pthread_join(t, NULL); }
#endif

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static void test_recursion(void) {
    wasmext_rlock l;
    wasmext_rlock_init(&l);
    CHECK(wasmext_rlock_depth(&l) == 0);
    wasmext_rlock_lock(&l);
    wasmext_rlock_lock(&l);
    wasmext_rlock_lock(&l);
    CHECK(wasmext_rlock_depth(&l) == 3);
    wasmext_rlock_unlock(&l);
    CHECK(wasmext_rlock_depth(&l) == 2);
    wasmext_rlock_release_to(&l, 1); /* what a trap left above level 1 */
    CHECK(wasmext_rlock_depth(&l) == 1);
    wasmext_rlock_release_to(&l, 1); /* nothing above it: nothing happens */
    CHECK(wasmext_rlock_depth(&l) == 1);
    wasmext_rlock_release_to(&l, 0);
    CHECK(wasmext_rlock_depth(&l) == 0);
    wasmext_rlock_lock(&l); /* free again: can be taken */
    wasmext_rlock_unlock(&l);
    wasmext_rlock_destroy(&l);
}

typedef struct { wasmext_rlock lock; long plain; int rounds; } shared_t;
static THREAD_RESULT worker(void *arg) {
    shared_t *sh = (shared_t *)arg;
    for (int n = 0; n < sh->rounds; n++) {
        wasmext_rlock_lock(&sh->lock);
        wasmext_rlock_lock(&sh->lock); /* recursive */
        sh->plain++;                   /* not atomic: only the lock keeps it right */
        wasmext_rlock_unlock(&sh->lock);
        wasmext_rlock_unlock(&sh->lock);
    }
    return 0;
}
static void test_exclusion(void) {
    enum { N = 6 };
    shared_t sh;
    thread_t t[N];
    memset(&sh, 0, sizeof sh);
    sh.rounds = 20000;
    wasmext_rlock_init(&sh.lock);
    for (int k = 0; k < N; k++) thread_start(&t[k], worker, &sh);
    for (int k = 0; k < N; k++) thread_join(t[k]);
    CHECK(sh.plain == (long)N * sh.rounds);
    CHECK(wasmext_rlock_depth(&sh.lock) == 0);
    wasmext_rlock_destroy(&sh.lock);
}

int main(void) {
    test_recursion();
    test_exclusion();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
