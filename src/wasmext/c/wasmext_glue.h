/* The glue that is the same for every module: the traps and how a call of WebAssembly code is guarded, and the fingerprint of the layout
   of the structs of the wasm2c runtime that two extensions share. No Python.h here (nor in the <name>_glue.h that includes it): a
   host that is not Python (the shared library, the executable) uses these files as they are. See "Design: C first" in FEATURES.md.

   A function of the glue that the module exports is called as `result f(void *instance, parameters..., int *trapped)`: `*trapped` is 0,
   or the code of the trap (a WASM_RT_TRAP_* of the runtime, or one of those below) and the result is then undefined. A host function that
   the module imports has the same form, but there `*trapped` is only nonzero or not: the host keeps what it needs to report the error
   (Python keeps its exception), and the frames of the module are unwound with WASMEXT_TRAP_HOST, as the protocol of errors says. */
#ifndef WASMEXT_GLUE_H
#define WASMEXT_GLUE_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "wasm-rt.h"
#include "wasm-rt-impl.h"
#include "wasm-rt-exceptions.h"
#ifndef _WIN32
#include <signal.h>
#endif

/* the codes of traps that are not the runtime's */
#define WASMEXT_TRAP_HOST ((wasm_rt_trap_t)0x7000)       /* a host function failed and kept its error (Python: the exception is already set) */
#define WASMEXT_TRAP_NO_MEMORY ((wasm_rt_trap_t)0x7001)  /* the copy of the runtime that wasmext brings cannot allocate a memory */
#define WASMEXT_TRAP_ENDED ((wasm_rt_trap_t)0x7002)      /* the WASI program of the instance is over (proc_exit, proc_raise, a trap of a command) */

/* A fingerprint of the layout of the structs of the wasm2c runtime that are shared between extensions (a memory, a table): an extension
   built with another runtime reads another layout, and its exports must not be linked. (Overridable, for the tests.) */
#ifndef WASMEXT_RUNTIME
#define WASMEXT_RUNTIME ((uint32_t)(sizeof(wasm_rt_memory_t) * 1000003u ^ offsetof(wasm_rt_memory_t, data) * 8191u ^ \
    offsetof(wasm_rt_memory_t, pages) * 131u ^ offsetof(wasm_rt_memory_t, size) * 17u ^ offsetof(wasm_rt_memory_t, is64) * 7u ^ \
    sizeof(wasm_rt_funcref_table_t) * 65537u))
#endif

/* a value of WebAssembly that is not a parameter or a result of a call: the values of an exception that nothing caught (`type` is the
   number of the type in the binary format: 0x7F i32, 0x7E i64, 0x7D f32, 0x7C f64, 0x7B v128, whose 16 bytes are in `o`) */
typedef struct {
    uint8_t type;
    union {
        uint32_t i;
        uint64_t j;
        float f;
        double d;
        uint8_t o[16];
    } as;
} wasmext_value;

/* a trap from a signal handler (an access past the guard pages) leaves the signal blocked: sigsetjmp saves no mask, for speed */
static void wasmext_unblock_fault_signals(void) {
#ifndef _WIN32
    sigset_t set_;
    sigemptyset(&set_);
    sigaddset(&set_, SIGSEGV);
    sigaddset(&set_, SIGBUS);
    pthread_sigmask(SIG_UNBLOCK, &set_, NULL);
#endif
}

/* the unwind target is where a `throw` that no `try` of the module catches goes: the trap of this call */
#define WASMEXT_SET_UP_TRAP_() \
    (WASM_RT_SAVE_STACK_DEPTH(), wasm_rt_set_unwind_target(&g_wasm_rt_jmp_buf), (wasm_rt_trap_t)wasm_rt_try(g_wasm_rt_jmp_buf))

/* A call of WebAssembly code: `WASMEXT_ENTER(CODE, FAIL)` makes the variable CODE (0 the first time, the trap when the code comes back
   by a trap) and runs FAIL then; `WASMEXT_LEAVE()` after the call. A module that imports something can be called again from inside the call
   (a function of the host can call it): the buffer of the outer call is put back afterwards. A module that imports nothing cannot, and
   saves the copy. */
#define WASMEXT_ENTER_REENTRANT(CODE, FAIL) \
    wasm_rt_jmp_buf saved_jmp_; \
    memcpy(&saved_jmp_, &g_wasm_rt_jmp_buf, sizeof saved_jmp_); \
    wasm_rt_trap_t CODE = WASMEXT_SET_UP_TRAP_(); \
    if (CODE) { \
        wasmext_unblock_fault_signals(); \
        memcpy(&g_wasm_rt_jmp_buf, &saved_jmp_, sizeof saved_jmp_); \
        FAIL; \
    }
#define WASMEXT_LEAVE_REENTRANT() memcpy(&g_wasm_rt_jmp_buf, &saved_jmp_, sizeof saved_jmp_)
#define WASMEXT_ENTER_PLAIN(CODE, FAIL) \
    wasm_rt_trap_t CODE = WASMEXT_SET_UP_TRAP_(); \
    if (CODE) { wasmext_unblock_fault_signals(); FAIL; }
#define WASMEXT_LEAVE_PLAIN() ((void)0)

#endif
