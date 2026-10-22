/* The experiment of one handler: force-included into the files of the RUNTIME only (build.sh). The runtime of wasm2c cannot have the alternate stack of a thread for a stack overflow without installing its
 * own handler of signals (wasm-rt.h: WASM_RT_STACK_EXHAUSTION_HANDLER needs WASM_RT_INSTALL_SIGNAL_HANDLER, and WASM_RT_SKIP_SIGNAL_RECOVERY turns the second off), so here the call of `sigaction` of
 * the runtime goes to a function that does nothing: the runtime thinks it installed a handler, and the one handler of the process is installed by the first module in its own file (one_handler.h). */
#ifndef NO_SIGACTION_H
#define NO_SIGACTION_H
#include <signal.h>  /* first, so that the declaration of sigaction is not touched by the macro below */
static inline int wasmext_noop_sigaction(int signal, const void *act, void *old) {
    (void)signal;
    (void)act;
    (void)old;
    return 0;
}
#define sigaction(a, b, c) wasmext_noop_sigaction((a), (b), (c))
#endif
