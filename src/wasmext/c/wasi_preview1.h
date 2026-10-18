/* WASI 0.1, `wasi_snapshot_preview1`, for a module built by wasmext: the part that is the same on every platform is plain C, the
   rest goes through CPython (see "Design: WASI" in FEATURES.md). This file is copied next to the C of the module and compiled
   with it; nothing of wasmext is needed when the module runs. */
#ifndef WASMEXT_WASI_PREVIEW1_H
#define WASMEXT_WASI_PREVIEW1_H

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "wasm-rt.h"

typedef struct wasmext_wasi wasmext_wasi;

/* The state of one instance. `config` is None or a dict with the keys args, env, stdin, stdout, stderr, preopens; `exit_type`
   is the exception that proc_exit raises (called with the code); `program` is argv[0] when the config has no args. NULL, with an
   exception set, on a bad config. */
wasmext_wasi *wasmext_wasi_new(PyObject *config, PyObject *exit_type, const char *program);
void wasmext_wasi_free(wasmext_wasi *w);
int wasmext_wasi_traverse(wasmext_wasi *w, visitproc visit, void *arg);
void wasmext_wasi_clear(wasmext_wasi *w);
/* The memory of the instance, which the calls read and write; set once it exists. */
void wasmext_wasi_bind(wasmext_wasi *w, wasm_rt_memory_t *memory);
/* The function that implements an import of `wasi_snapshot_preview1`, or NULL if the specification has no such function. It is
   called as `uint32_t f(void *state, parameters..., int *trapped)`; a trap (an exception set in Python) is reported through
   `trapped`. proc_exit returns nothing. */
void *wasmext_wasi_preview1_lookup(const char *name);

#endif
