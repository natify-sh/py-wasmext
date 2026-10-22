/* The experiment: how a wasm2c module can know that the native stack is about to run out.
 *   guard : the default (WASM_RT_STACK_EXHAUSTION_HANDLER): the guard page of the stack, a handler of SIGSEGV on an alternate stack. No code in the functions.
 *   depth : WASM_RT_STACK_DEPTH_COUNT: ++depth in the prologue, --depth in the epilogue, a limit of 500 calls (not bytes).
 *   sp    : a patch of FUNC_PROLOGUE (build.sh): the address of the frame is compared with a limit kept per thread (the lowest address that is still safe). No epilogue.
 * One executable, so that the thread-local variable is the cheap kind; each thread sets its limit from the real size of its stack (stack_limit_init). */
#define _GNU_SOURCE
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wasm-rt.h>
#include <wasm-rt-impl.h>
#include <wasm-rt-exceptions.h>
#include "ft.h"

#ifdef MODE_SP
__thread uintptr_t wasmext_stack_limit;
static void stack_limit_init(size_t margin) {
    pthread_attr_t a;
    void *addr;
    size_t size;
    pthread_getattr_np(pthread_self(), &a);
    pthread_attr_getstack(&a, &addr, &size);
    pthread_attr_destroy(&a);
    wasmext_stack_limit = (uintptr_t)addr + margin;
}
#else
static void stack_limit_init(size_t margin) { (void)margin; }
#endif

static w2c_ft inst;
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

static int try_recurse(void) {
    wasm_rt_trap_t code = wasm_rt_impl_try();
    if (code) return (int)code;
    w2c_ft_recurse_count(&inst, 0);
    return 0;
}

static unsigned depth_reached(void) { return *(uint32_t *)w2c_ft_memory(&inst)->data; }

static void report(const char *where) {
    int code = try_recurse();
    printf("  %-28s %s, depth reached %u\n", where, code == WASM_RT_TRAP_EXHAUSTION ? "EXHAUSTION trap" : "OTHER", depth_reached());
    fflush(stdout);
}

static void *deep_in_thread(void *arg) { (void)arg; wasm_rt_init_thread(); stack_limit_init(128 * 1024); report("recursion in a 512 KiB thread"); return NULL; }

int main(int argc, char **argv) {
    int n = argc > 1 ? atoi(argv[1]) : 32;
    wasm_rt_init();
    stack_limit_init(128 * 1024);
    wasm2c_ft_instantiate(&inst);
    /* correctness: the stack running out is a trap, and the process goes on */
    report("recursion in the main thread");
    pthread_attr_t at;
    pthread_attr_init(&at);
    pthread_attr_setstacksize(&at, 512 * 1024);
    pthread_t t;
    pthread_create(&t, &at, deep_in_thread, NULL);
    pthread_join(t, NULL);
    /* the cost: calls through the table, each pays the prologue (and the epilogue) */
    uint32_t sink = 0;
    double best = 1e9;
    for (int r = 0; r < 7; r++) {
        double t0 = now();
        sink += w2c_ft_fib(&inst, (u32)n);
        double dt = now() - t0;
        if (dt < best) best = dt;
    }
    printf("  fib(%d) = %u, best of 7: %.1f ms\n", n, sink / 7, best * 1e3);
    return 0;
}
