/* The experiment of a CHAIN of handlers (docs/shared_runtime_concept.md): no capsule, no shared stack, every module on a runtime of its own.
 * The runtime of the module installs no handler (no_sigaction.h in its files). The module installs one at its import and keeps the one that was there: when a fault comes and a call of THIS module is
 * running in this thread (chain_active_, set by the entry of every call, see patch.py), the module's own runtime turns it into its own trap; if not, the fault is given to the handler that was before. */
#ifndef CHAIN_HANDLER_H
#define CHAIN_HANDLER_H
#include <signal.h>
#include <string.h>
#include <Python.h>

static struct sigaction chain_old_segv_, chain_old_bus_;

static void chain_handler_(int sig, siginfo_t *si, void *ctx) {
    if (chain_active_) wasm_rt_trap(si->si_code == SEGV_ACCERR ? WASM_RT_TRAP_OOB : WASM_RT_TRAP_EXHAUSTION);  /* does not return */
    const struct sigaction *old = sig == SIGSEGV ? &chain_old_segv_ : &chain_old_bus_;
    if (old->sa_flags & SA_SIGINFO) {
        old->sa_sigaction(sig, si, ctx);
    } else if (old->sa_handler == SIG_DFL || old->sa_handler == SIG_IGN) {
        signal(sig, SIG_DFL);  /* the fault happens again when the handler returns, and the default action ends the process as if nobody had a handler */
    } else {
        old->sa_handler(sig);
    }
}

static int chain_install(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    sa.sa_sigaction = chain_handler_;
    if (sigaction(SIGSEGV, &sa, &chain_old_segv_) != 0 || sigaction(SIGBUS, &sa, &chain_old_bus_) != 0) {
        PyErr_SetString(PyExc_ImportError, "chain: sigaction failed");
        return -1;
    }
    return 0;
}
#endif
