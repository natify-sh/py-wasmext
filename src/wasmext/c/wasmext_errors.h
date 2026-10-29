/* The codes of errors of a call and what they mean, in one table: the trap codes of the runtime of wasm2c and those of wasmext. A front end maps `kind` to
   its own exception; `text` is the message. No Python. Needs wasm-rt.h (through wasmext_glue.h) and, for the text of a trap of the runtime, wasm-rt-impl.c. */
#ifndef WASMEXT_ERRORS_H
#define WASMEXT_ERRORS_H

#include "wasmext_glue.h"

/* the code of an import that was not set (the library's; the generated C API names it by the module) */
#define WASMEXT_TRAP_LINK_ERROR ((wasm_rt_trap_t)0x7003)

enum {
    WASMEXT_ERR_TRAP = 0,   /* a trap of WebAssembly: `text` says which */
    WASMEXT_ERR_HOST = 1,   /* a host function failed and kept its own error */
    WASMEXT_ERR_NOMEM = 2,  /* out of memory */
    WASMEXT_ERR_ENDED = 3,  /* the call ended the WASI program (see `wasi_end`) */
    WASMEXT_ERR_LINK = 4,   /* an import was not set */
    WASMEXT_ERR_CLOSED = 5, /* the store is closed */
    WASMEXT_ERR_UNCAUGHT = 6 /* an exception of WebAssembly that nothing caught */
};

typedef struct {
    int kind;
    const char *text;
} wasmext_error_info;

static inline wasmext_error_info wasmext_error_describe(int code) {
    wasmext_error_info info;
    info.kind = WASMEXT_ERR_TRAP;
    info.text = NULL;
    if (code == (int)WASMEXT_TRAP_HOST) { info.kind = WASMEXT_ERR_HOST; info.text = "a host function failed"; }
    else if (code == (int)WASMEXT_TRAP_NO_MEMORY) { info.kind = WASMEXT_ERR_NOMEM; info.text = "out of memory"; }
    else if (code == (int)WASMEXT_TRAP_ENDED) { info.kind = WASMEXT_ERR_ENDED; info.text = "the call ended the WASI program"; }
    else if (code == (int)WASMEXT_TRAP_LINK_ERROR) { info.kind = WASMEXT_ERR_LINK; info.text = "an import was not set"; }
    else if (code == (int)WASMEXT_TRAP_CLOSED) { info.kind = WASMEXT_ERR_CLOSED; info.text = "the store is closed"; }
    else {
        if (code == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION) info.kind = WASMEXT_ERR_UNCAUGHT;
        info.text = wasm_rt_strerror((wasm_rt_trap_t)code);
    }
    return info;
}

#endif
