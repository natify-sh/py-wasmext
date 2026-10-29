/* Tests of wasmext_store.h in plain C: no wasm, no Python. Exit 0 and "ok" when all pass. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_store.h"

#ifdef _WIN32
#include <process.h>
typedef HANDLE thread_t;
typedef unsigned (__stdcall *thread_fn)(void *);
#define THREAD_RESULT unsigned __stdcall
static void thread_start(thread_t *t, thread_fn f, void *arg) { *t = (HANDLE)_beginthreadex(NULL, 0, f, arg, 0, NULL); }
static void thread_join(thread_t t) { WaitForSingleObject(t, INFINITE); CloseHandle(t); }
static void yield_(void) { SwitchToThread(); }
#else
#include <pthread.h>
#include <sched.h>
typedef pthread_t thread_t;
#define THREAD_RESULT void *
static void thread_start(thread_t *t, THREAD_RESULT (*f)(void *), void *arg) { pthread_create(t, NULL, f, arg); }
static void thread_join(thread_t t) { pthread_join(t, NULL); }
static void yield_(void) { sched_yield(); }
#endif

#ifndef ROUNDS
#define ROUNDS 20
#endif

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static int order[8], order_n;
static void note(void *object) { order[order_n++] = (int)(intptr_t)object; }

static void test_lifecycle(void) {
    wasmext_store *s = wasmext_store_new();
    CHECK(s != NULL);
    CHECK(!wasmext_store_closed(s));
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_closed(s));
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK); /* twice is fine */
    CHECK(wasmext_store_free(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_free(NULL) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_closed(NULL));
}

static void test_arena(void) {
    wasmext_store *s = wasmext_store_new();
    order_n = 0;
    CHECK(wasmext_store_own(s, (void *)(intptr_t)1, note) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_own(s, (void *)(intptr_t)2, note) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_own(s, (void *)(intptr_t)3, note) == WASMEXT_STORE_OK);
    CHECK(order_n == 0); /* nothing is let go before the close */
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(order_n == 3 && order[0] == 3 && order[1] == 2 && order[2] == 1); /* the reverse order, each once */
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(order_n == 3);
    CHECK(wasmext_store_own(s, (void *)(intptr_t)4, note) == WASMEXT_STORE_CLOSED); /* refused: not owned */
    CHECK(order_n == 3);
    CHECK(wasmext_store_free(s) == WASMEXT_STORE_OK);
}

static void test_calls(void) {
    wasmext_store *s = wasmext_store_new();
    int a = wasmext_store_enter(s), b = wasmext_store_enter(s);
    CHECK(a >= 0 && b >= 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_BUSY); /* from inside a call too: this thread is in one */
    CHECK(!wasmext_store_closed(s));
    wasmext_store_leave(s, a);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_BUSY);
    wasmext_store_leave(s, b);
    {
        int c = wasmext_store_enter(s); /* a refused close left the store open */
        CHECK(c >= 0);
        wasmext_store_leave(s, c);
    }
    CHECK(wasmext_store_free(s) == WASMEXT_STORE_OK);
    s = wasmext_store_new();
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_enter(s) == -1); /* a call into a closed store fails */
    wasmext_store_free(s);
}

static void test_error_text(void) {
    wasmext_store *s = wasmext_store_new();
    char small[8], big[WASMEXT_STORE_ERROR_SIZE];
    char text[400];
    wasmext_store_error(s, big, sizeof big);
    CHECK(big[0] == 0);
    wasmext_store_set_error(s, "a refusal");
    wasmext_store_error(s, big, sizeof big);
    CHECK(strcmp(big, "a refusal") == 0);
    wasmext_store_error(s, small, sizeof small);
    CHECK(strcmp(small, "a refus") == 0 && strlen(small) == 7); /* cut to fit, and ended */
    memset(text, 'x', sizeof text - 1);
    text[sizeof text - 1] = 0;
    wasmext_store_set_error(s, text);
    wasmext_store_error(s, big, sizeof big);
    CHECK(strlen(big) == WASMEXT_STORE_ERROR_SIZE - 1);
    wasmext_store_free(s);
}

/* ---- threads: calls against a close ---- */
typedef struct {
    wasmext_store *store;
    wasmext_counter stop;
    wasmext_counter inside; /* the calls that are inside right now, counted by the test itself */
    wasmext_counter entered_after_close;
} shared_t;

static THREAD_RESULT caller(void *arg) {
    shared_t *sh = (shared_t *)arg;
    while (!wasmext_atomic_load(&sh->stop)) {
        int line = wasmext_store_enter(sh->store);
        if (line < 0) {
            if (wasmext_store_closed(sh->store)) break;
            yield_();
            continue;
        }
        wasmext_atomic_add(&sh->inside, 1);
        for (int k = 0; k < 200; k++) (void)wasmext_atomic_load(&sh->stop); /* some work inside the call */
        wasmext_atomic_add(&sh->inside, -1);
        wasmext_store_leave(sh->store, line);
        yield_(); /* most of the time a caller is outside a call, as a real one is; a close that never finds a moment with none is refused (BUSY) and tries again */
    }
    return 0;
}

static void test_threads(void) {
    enum { N = 6 };
    for (int round = 0; round < ROUNDS; round++) {
        shared_t sh;
        thread_t t[N];
        int rc = WASMEXT_STORE_BUSY;
        memset(&sh, 0, sizeof sh);
        sh.store = wasmext_store_new();
        for (int i = 0; i < N; i++) thread_start(&t[i], caller, &sh);
        for (int tries = 0; tries < 1000000 && rc == WASMEXT_STORE_BUSY; tries++) {
            rc = wasmext_store_close(sh.store);
            if (rc == WASMEXT_STORE_BUSY) yield_();
        }
        CHECK(rc == WASMEXT_STORE_OK);
        /* the proof: after a close that succeeded no call is inside, and none can enter */
        CHECK(wasmext_atomic_load(&sh.inside) == 0);
        CHECK(wasmext_store_enter(sh.store) == -1);
        wasmext_atomic_store(&sh.stop, 1);
        for (int i = 0; i < N; i++) thread_join(t[i]);
        CHECK(wasmext_store_free(sh.store) == WASMEXT_STORE_OK);
    }
}

static int host_released;
static void host_release(void *host) { (void)host; host_released++; }

static void test_host_slot(void) {
    wasmext_store *s = wasmext_store_new();
    int host_a, host_b, lock;
    CHECK(wasmext_store_host(s) == NULL && wasmext_store_host_lock(s) == NULL);
    CHECK(wasmext_store_set_host(s, &host_a, host_release, &lock) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_host(s) == &host_a && wasmext_store_host_lock(s) == &lock);
    CHECK(wasmext_store_set_host(s, &host_b, host_release, NULL) == WASMEXT_STORE_BUSY); /* once */
    CHECK(wasmext_store_host(s) == &host_a);
    CHECK(host_released == 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(host_released == 1); /* the store lets it go, once */
    wasmext_store_free(s);
    s = wasmext_store_new();
    wasmext_store_close(s);
    CHECK(wasmext_store_set_host(s, &host_b, host_release, NULL) == WASMEXT_STORE_CLOSED); /* refused: not owned */
    CHECK(wasmext_store_host(s) == NULL && host_released == 1);
    wasmext_store_free(s);
}

int main(void) {
    test_lifecycle();
    test_host_slot();
    test_arena();
    test_calls();
    test_error_text();
    test_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
