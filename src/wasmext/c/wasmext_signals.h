/* The stack limit of a thread and the chain handler of SIGSEGV/SIGBUS in the core (S0008, 8b-3a; D43). A COPY of what the layer 3 of the Python front end has in _gen.py (the limit
   `wasmext_stack_limit_init_`, the handler `wasmext_chain_handler_`; docs/layers.md lists both as duplicates until layer 3 moves onto the core), so that a program with no Python gets
   EXHAUSTION from a recursion and OOB from an access past a guard page.

   Built only where the build defines WASMEXT_CHAIN (`core_build_macros` of _natify.py: the modes `limit` and `guard`; `stock` leaves the handler to the runtime of wasm2c) and not on Windows (its
   own mechanism). Everywhere else this file is empty and `wasmext_signals_thread_` does nothing.

   * WASMEXT_STACK_LIMIT: the prologue of each function (`_stack_limit_prologue` of _natify.py) compares its frame with the thread-local `wasmext_stack_limit` (defined by the `impl` wrapper of the
     runtime); a thread sets it once, at its first call (`wasmext_thread_ready`). The margin is what a function of the host can use when the limit is reached.
   * The handler is installed at the first `wasmext_thread_ready` of a copy, once per process for that copy, and keeps the action that was there. A fault is a trap when this thread is inside a call
     as THIS copy sees it (`tls.rt` is set: the copy is a peer of the store being run, `tls.top` is set: the copy is the runtime of the store); the trap goes through the FORWARDER `wasm_rt_trap`, so
     it reaches the runtime of the store whichever copy's code faulted. Any other fault is given to the handler that was before (a real crash is still one). The handler of the copy installed LAST
     runs; a fault in a call of a copy that is not in the store is chained down to the one that is. In the `stock` mode this handler is not installed: the runtime's own handler calls the renamed
     own trap and bypasses `tls.rt`, so a signal across copies is not supported there (one copy, as before).
   * Linux libraries are linked with `-z now` (`signal_build_flags`): the handler reads thread-local data, and with lazy binding the first access resolves `__tls_get_addr` inside the handler. */
#ifndef WASMEXT_SIGNALS_H
#define WASMEXT_SIGNALS_H

#include "wasmext_runtime.h"

#if defined(WASMEXT_CHAIN) && !defined(_WIN32)
#define WASMEXT_SIGNALS_ 1
#include <pthread.h>
#include <signal.h>
#include <string.h>

WASMEXT_HIDDEN_ void wasmext_signals_install_(void); /* defined by the file that defines WASMEXT_DEFINE_THREAD_STATE */

#ifdef WASMEXT_STACK_LIMIT
extern __thread uintptr_t wasmext_stack_limit WASMEXT_HIDDEN_;
/* The lowest address of the stack of this thread that is still safe: a quarter of the stack above its low end, between 32 and 256 KiB (the margin of what a function of the host can use when the
   limit is reached). A thread whose stack cannot be measured gets 128 KiB below here. */
static inline void wasmext_stack_limit_init_(void) {
    uintptr_t low = 0, size = 0, margin;
#if defined(__APPLE__)
    pthread_t self = pthread_self();
    size = (uintptr_t)pthread_get_stacksize_np(self);
    low = (uintptr_t)pthread_get_stackaddr_np(self) - size; /* the address it gives is the top */
#else
    extern int pthread_getattr_np(pthread_t, pthread_attr_t *);
    pthread_attr_t attr;
    if (pthread_getattr_np(pthread_self(), &attr) == 0) {
        void *addr = NULL;
        size_t length = 0;
        if (pthread_attr_getstack(&attr, &addr, &length) == 0) {
            low = (uintptr_t)addr;
            size = (uintptr_t)length;
            /* The main thread under `ulimit -s unlimited`: glibc reports the gap down to the previous mapping (tens of TiB) and a recursion would run until memory ends. The limit is measured from the
               top of the stack over at most 64 MiB, which no thread stack of a normal size exceeds. (Only the `limit` mode has this: `guard` and `stock` see the guard page itself.) */
            if (size > (uintptr_t)64 * 1024 * 1024) {
                low = low + size - (uintptr_t)64 * 1024 * 1024;
                size = (uintptr_t)64 * 1024 * 1024;
            }
        }
        pthread_attr_destroy(&attr);
    }
#endif
    if (size == 0) {
        wasmext_stack_limit = (uintptr_t)__builtin_frame_address(0) - 128 * 1024;
        return;
    }
    margin = size / 4;
    if (margin < 32 * 1024) margin = 32 * 1024;
    if (margin > 256 * 1024) margin = 256 * 1024;
    wasmext_stack_limit = low + margin;
}
#endif

#ifdef WASMEXT_DEFINE_THREAD_STATE
static struct sigaction wasmext_old_segv_, wasmext_old_bus_;
static void wasmext_signal_handler_(int sig, siginfo_t *si, void *ctx) {
    if (wasmext_tls_.rt != NULL || wasmext_tls_.top != NULL) {
#ifdef WASMEXT_STACK_LIMIT
        (void)si;
        wasm_rt_trap(WASM_RT_TRAP_OOB); /* the stack is checked in the prologue, so a fault in a call is the memory (macOS gives the guard page another si_code than ACCERR); does not return */
#else
        wasm_rt_trap(si->si_code == SEGV_ACCERR ? WASM_RT_TRAP_OOB : WASM_RT_TRAP_EXHAUSTION); /* does not return */
#endif
    }
    {
        const struct sigaction *old = sig == SIGSEGV ? &wasmext_old_segv_ : &wasmext_old_bus_;
        if (old->sa_flags & SA_SIGINFO) {
            old->sa_sigaction(sig, si, ctx);
        } else if (old->sa_handler == SIG_DFL || old->sa_handler == SIG_IGN) {
            signal(sig, SIG_DFL); /* the fault happens again when this returns, and the default action ends the process as if nobody had a handler */
        } else {
            old->sa_handler(sig);
        }
    }
}
static void wasmext_signals_install_once_(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    sa.sa_sigaction = wasmext_signal_handler_;
    if (sigaction(SIGSEGV, &sa, &wasmext_old_segv_) != 0 || sigaction(SIGBUS, &sa, &wasmext_old_bus_) != 0) return;
    /* The thread-local block of this thread is made now: the first access may allocate (macOS, lazy TLS), which a handler must not do. Known limit (copied from _gen.py, not a regression): this covers
       the installing thread only. With glibc a thread that never touched this copy (a dlopen'ed library) gets its block made by `__tls_get_addr` on its first access, a malloc, which can happen inside the
       handler; `-z now` does not prevent it. A thread that made the copy ready (`wasmext_thread_ready`) has it made already; 8b-3b (the copies made ready on the threads of a store) narrows the window. */
    (void)*(volatile int *)&wasmext_tls_;
}
void wasmext_signals_install_(void) {
#ifdef WASMEXT_NO_THREADS
    static int done_;
    if (!done_) {
        done_ = 1;
        wasmext_signals_install_once_();
    }
#else
    static pthread_once_t once_ = PTHREAD_ONCE_INIT;
    pthread_once(&once_, wasmext_signals_install_once_);
#endif
}
#endif
#endif /* WASMEXT_CHAIN && !_WIN32 */

/* what `wasmext_thread_ready` does for a thread besides the runtime: the handler of this copy (once per process), and the limit of this thread */
static inline void wasmext_signals_thread_(void) {
#ifdef WASMEXT_SIGNALS_
    wasmext_signals_install_();
#ifdef WASMEXT_STACK_LIMIT
    wasmext_stack_limit_init_();
#endif
#endif
}

#endif /* WASMEXT_SIGNALS_H */
