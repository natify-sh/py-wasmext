/* The experiment of ONE handler of signals for the process (docs/shared_runtime_concept.md, "Conclusion").
 * Every module is built with WASM_RT_SKIP_SIGNAL_RECOVERY=1 (its runtime installs no handler) and WASM_RT_STACK_EXHAUSTION_HANDLER=1 (it still sets up the alternate stack of a thread).
 * The first module that loads installs THE handler and marks it in the dict of the interpreter state; the others find the mark and install nothing.
 * The handler turns the signal into a trap on the stack of entries of wasmext_traps (the innermost call into WebAssembly code of this thread, of any module). */
#ifndef ONE_HANDLER_H
#define ONE_HANDLER_H
#include <Python.h>
#include <signal.h>
#include <string.h>

#define ONE_HANDLER_KEY "wasmext.sighandler.experiment.v1"

static void one_handler_(int sig, siginfo_t *si, void *unused) {
    (void)sig;
    (void)unused;
    wasmext_traps_->trap(si->si_code == SEGV_ACCERR ? WASM_RT_TRAP_OOB : WASM_RT_TRAP_EXHAUSTION);
}

static int one_handler_install(void) {
    PyObject *state = PyInterpreterState_GetDict(PyInterpreterState_Get());
    if (state == NULL) return -1;
    if (PyDict_GetItemString(state, ONE_HANDLER_KEY) != NULL) return 0;  /* another module did it */
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    sa.sa_sigaction = one_handler_;
    if (sigaction(SIGSEGV, &sa, NULL) != 0 || sigaction(SIGBUS, &sa, NULL) != 0) {
        PyErr_SetString(PyExc_ImportError, "one handler: sigaction failed");
        return -1;
    }
    PyObject *mark = PyLong_FromVoidPtr((void *)one_handler_);
    if (mark == NULL) return -1;
    int bad = PyDict_SetItemString(state, ONE_HANDLER_KEY, mark) < 0;
    Py_DECREF(mark);
    return bad ? -1 : 0;
}
#endif
