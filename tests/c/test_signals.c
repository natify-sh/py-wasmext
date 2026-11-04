/* Step 8b-3a of docs/specs/S0008-shared-store.md: the stack limit and the chain handler of signals in the core, one copy of the runtime, a host in plain C (no Python, no layer 3). The module is
   MODULE (`sig`: tests/test_signals.py). The case is argv[1]; the mode of the build is the macros it was built with: `limit` (WASMEXT_STACK_LIMIT), `guard` (WASMEXT_CHAIN only) or `stock` (neither: the runtime
   installs its own handler). Exit 0 and "ok" when the case passes. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <pthread.h>
#include <setjmp.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "wasmext_errors.h"
#include "wasmext_instance.h"

#define CAT_(a, b) a##b
#define CAT(a, b) CAT_(a, b)
extern const wasmext_binding CAT(MODULE, _binding);
#define BINDING (&CAT(MODULE, _binding))

#if defined(WASMEXT_STACK_LIMIT)
#define MODE_LIMIT 1
#else
#define MODE_LIMIT 0
#endif

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static wasmext_val I32(int32_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7F; x.as.i32 = v; return x; }

static wasmext_store *store;
static wasmext_instance *inst;

static void setup(void) {
    int err = -1;
    store = wasmext_store_new();
    inst = wasmext_instance_new(store, BINDING, &err);
    CHECK(store != NULL && inst != NULL && err == 0 && wasmext_instance_instantiate(inst) == 0);
}
static int call(const char *name, int32_t arg, int32_t *out) {
    wasmext_val a = I32(arg), r = I32(0);
    int rc = wasmext_instance_call(inst, (uint32_t)wasmext_instance_export_find(inst, name, strlen(name), WASMEXT_DESC_FUNC), &a, 1, &r, 1);
    if (rc == 0 && out != NULL) *out = r.as.i32;
    return rc;
}
/* the trap state of this thread after a call, however it ended: nothing active, no entry left */
static int clean(void) { return wasmext_tls_.rt == NULL && wasmext_tls_.top == NULL; }

/* a recursion that the stack cannot hold: EXHAUSTION where the limit sees it (limit mode) and where the signal is on the main thread; on a thread other than the main one the guard page of the
   stack is a mapped page without access, which the handler of the runtime reports as OOB (docs/experiments/stack_limit/README.md): there a trap of either kind is what the mode promises */
static int is_stack_trap(int rc, int main_thread) {
    if (rc == (int)WASM_RT_TRAP_EXHAUSTION) return 1;
    return !MODE_LIMIT && !main_thread && rc == (int)WASM_RT_TRAP_OOB;
}
static void recursion_here(int main_thread) {
    int32_t v = 0;
    for (int k = 0; k < 3; k++) {
        int rc = call("deep", 1, NULL);
        if (!is_stack_trap(rc, main_thread)) fprintf(stderr, "recursion answered %d (EXHAUSTION is %d)\n", rc, (int)WASM_RT_TRAP_EXHAUSTION);
        CHECK(is_stack_trap(rc, main_thread));
        CHECK(clean());
        CHECK(call("ok", 0, &v) == 0 && v == 7); /* the next call on the same thread works */
        CHECK(clean());
    }
}
static void *recursion_thread(void *arg) {
    (void)arg;
    recursion_here(0);
    wasmext_thread_free();
    return NULL;
}
static void case_recursion_thread(void) {
    pthread_t t;
    setup();
    for (int k = 0; k < 2; k++) { /* a fresh thread each time: it has no limit and no alternate stack until its first call */
        pthread_create(&t, NULL, recursion_thread, NULL);
        pthread_join(t, NULL);
    }
}
static void case_recursion_main(void) {
    setup();
    recursion_here(1);
}

/* a guard-page access: OOB, and the instance is usable after it */
static void oob_here(void) {
    int32_t v = -1;
    CHECK(call("ld", 0, &v) == 0 && v == 0);
    for (int k = 0; k < 3; k++) {
        CHECK(call("ld", 1 << 20, &v) == (int)WASM_RT_TRAP_OOB);
        CHECK(clean());
        CHECK(call("ld", (int32_t)0xFFFFFFF0u, &v) == (int)WASM_RT_TRAP_OOB);
        CHECK(clean());
        CHECK(call("ld", 5, &v) == 0 && v == 0 && clean());
    }
}
static void case_oob(void) {
    setup();
    oob_here();
}

/* after a trap by signal the next call of the thread works, whichever kind it was, in turns; and the state of the thread is clean each time */
static void case_after(void) {
    int32_t v = 0;
    setup();
    for (int k = 0; k < 40; k++) {
        CHECK(call("ld", 1 << 20, &v) == (int)WASM_RT_TRAP_OOB && clean());
        CHECK(call("ok", 0, &v) == 0 && v == 7 && clean());
        CHECK(call("deep", 1, &v) != 0 && clean());
        CHECK(call("ok", 0, &v) == 0 && v == 7 && clean());
    }
}

/* two threads, each trapping by signal in turns (an access and a recursion), many times */
static int with_recursion = 1;
static void *signals_thread(void *arg) {
    int32_t v = 0;
    (void)arg;
    for (int k = 0; k < 150; k++) {
        CHECK(call("ld", 1 << 20, &v) == (int)WASM_RT_TRAP_OOB && clean());
        if (with_recursion && k % 10 == 0) CHECK(call("deep", 1, &v) != 0 && clean());
        CHECK(call("ok", 0, &v) == 0 && v == 7);
    }
    wasmext_thread_free();
    return NULL;
}
static void case_threads(void) {
    pthread_t t[2];
    setup();
    pthread_create(&t[0], NULL, signals_thread, NULL);
    pthread_create(&t[1], NULL, signals_thread, NULL);
    pthread_join(t[0], NULL);
    pthread_join(t[1], NULL);
}

/* A fault outside any call reaches the handler that was installed BEFORE the core's. The test's handler is in force before the first call (the core installs its link at the first `thread_ready`);
   it either jumps back (`chain`) or ends the process with its own status (`chain_exit`), which the test of Python reads. The calls before and after show the core's own link still works. */
static sigjmp_buf back;
static volatile sig_atomic_t chained;
static void test_handler(int sig, siginfo_t *si, void *ctx) {
    static const char msg[] = "the handler of the test ran\n";
    (void)si; (void)ctx;
    if (write(2, msg, sizeof msg - 1) < 0) _exit(1);
    chained = sig;
    if (getenv("CHAIN_EXIT") != NULL) _exit(42);
    siglongjmp(back, 1);
}
static void install_test_handler(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = test_handler;
    sa.sa_flags = SA_SIGINFO | SA_NODEFER;
    sigemptyset(&sa.sa_mask);
    CHECK(sigaction(SIGSEGV, &sa, NULL) == 0 && sigaction(SIGBUS, &sa, NULL) == 0);
}
static void case_chain(void) {
    int32_t v = 0;
    install_test_handler();
    setup(); /* the first call of this copy installs its link of the chain, over the test's handler */
    CHECK(call("ld", 1 << 20, &v) == (int)WASM_RT_TRAP_OOB && clean());
    for (int k = 0; k < 3; k++) {
        chained = 0;
        if (sigsetjmp(back, 1) == 0) {
            *(volatile int *)8 = 1; /* host code, in no call: not a trap of the module */
            fprintf(stderr, "the fault of the host did not happen\n");
            failures++;
        }
        CHECK(chained == SIGSEGV || chained == SIGBUS);
        CHECK(call("ld", 1 << 20, &v) == (int)WASM_RT_TRAP_OOB && clean()); /* the link of the core still turns a fault in a call into a trap */
        CHECK(call("ok", 0, &v) == 0 && v == 7);
    }
}

int main(int argc, char **argv) {
    const char *which = argc > 1 ? argv[1] : "";
    if (strcmp(which, "recursion_thread") == 0) case_recursion_thread();
    else if (strcmp(which, "recursion_main") == 0) case_recursion_main();
    else if (strcmp(which, "oob") == 0) case_oob();
    else if (strcmp(which, "after") == 0) case_after();
    else if (strcmp(which, "threads") == 0) case_threads();
    else if (strcmp(which, "threads_oob") == 0) { with_recursion = 0; case_threads(); } /* no recursion: ThreadSanitizer's own handler faults when a stack runs out (tests/test_signals.py) */
    else if (strcmp(which, "chain") == 0 || strcmp(which, "chain_exit") == 0) case_chain();
    else { fprintf(stderr, "no case %s\n", which); return 2; }
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
