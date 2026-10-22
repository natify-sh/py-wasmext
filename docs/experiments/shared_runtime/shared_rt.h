/* An experiment (docs/shared_runtime_concept.md): one runtime of wasm2c for several modules built apart.
 * The MASTER module has the runtime (wasm-rt-impl.c and the others) and publishes a table of its functions in a capsule in the dict of the interpreter state.
 * A SLAVE module is built WITHOUT the runtime: the functions the generated code needs are forwarded to the master's table (slave_shim.c).
 * Nothing here is a part of wasmext. */
#ifndef SHARED_RT_H
#define SHARED_RT_H
#include <Python.h>
#include "wasm-rt.h"
#include "wasm-rt-exceptions.h"

#define RT_CAPSULE "wasmext.rt.experiment.v1"

typedef struct {
    uint32_t size;     /* sizeof of this table for the module that made it: a reader takes only what is within it */
    uint32_t runtime;  /* WASMEXT_RUNTIME of the master: the layout of the structs of the runtime (wasmext_glue.h) */
    void (*init)(void);
    bool (*is_initialized)(void);
    void (*init_thread)(void);
    void (*free_thread)(void);
    void (*thread_ready)(void);  /* idempotent: sets this thread up if it is not (the master keeps the flag and gives the stack back) */
    void (*trap)(wasm_rt_trap_t);
    const char *(*strerror_)(wasm_rt_trap_t);
    void (*allocate_memory)(wasm_rt_memory_t *, uint64_t, uint64_t, bool, uint32_t);
    uint64_t (*grow_memory)(wasm_rt_memory_t *, uint64_t);
    void (*free_memory)(wasm_rt_memory_t *);
    void (*allocate_funcref_table)(wasm_rt_funcref_table_t *, uint32_t, uint32_t);
    uint32_t (*grow_funcref_table)(wasm_rt_funcref_table_t *, uint32_t, wasm_rt_funcref_t);
    void (*free_funcref_table)(wasm_rt_funcref_table_t *);
    void (*allocate_externref_table)(wasm_rt_externref_table_t *, uint32_t, uint32_t);
    uint32_t (*grow_externref_table)(wasm_rt_externref_table_t *, uint32_t, wasm_rt_externref_t);
    void (*free_externref_table)(wasm_rt_externref_table_t *);
    void (*set_unwind_target)(WASM_RT_UNWIND_TARGET *);
    WASM_RT_UNWIND_TARGET *(*get_unwind_target)(void);
    void (*load_exception)(const wasm_rt_tag_t, uint32_t, const void *);
    void (*throw_)(void);
    wasm_rt_tag_t (*exception_tag)(void);
    uint32_t (*exception_size)(void);
    void *(*exception)(void);
} rt_vtable;


#ifdef RT_DUAL
/* A DUAL module: it has a runtime of its own (compiled with its function names changed to own_*, see build.sh) and the forwarders of slave_shim: it attaches to the
 * runtime of a master if there is one that is the same, and runs on its own runtime if not; the first dual module becomes the master. */
#define RT_FUNCTIONS(X) X(init) X(is_initialized) X(init_thread) X(free_thread) X(trap) X(strerror) X(allocate_memory) X(grow_memory) X(free_memory) \
    X(allocate_funcref_table) X(grow_funcref_table) X(free_funcref_table) X(allocate_externref_table) X(grow_externref_table) X(free_externref_table) \
    X(set_unwind_target) X(get_unwind_target) X(load_exception) X(throw) X(exception_tag) X(exception_size) X(exception)
#define RT_DECLARE_OWN(n) __typeof__(wasm_rt_##n) own_wasm_rt_##n;
RT_FUNCTIONS(RT_DECLARE_OWN)
extern const rt_vtable *rt_M;
#ifndef RT_SHIM
static void own_thread_ready(void) {
    if (!wasmext_py_ready_) wasmext_py_thread_setup_();
}
static const rt_vtable rt_own = {
    sizeof(rt_vtable), WASMEXT_RUNTIME,
    own_wasm_rt_init, own_wasm_rt_is_initialized, own_wasm_rt_init_thread, own_wasm_rt_free_thread, own_thread_ready, own_wasm_rt_trap, own_wasm_rt_strerror,
    own_wasm_rt_allocate_memory, own_wasm_rt_grow_memory, own_wasm_rt_free_memory,
    own_wasm_rt_allocate_funcref_table, own_wasm_rt_grow_funcref_table, own_wasm_rt_free_funcref_table,
    own_wasm_rt_allocate_externref_table, own_wasm_rt_grow_externref_table, own_wasm_rt_free_externref_table,
    own_wasm_rt_set_unwind_target, own_wasm_rt_get_unwind_target, own_wasm_rt_load_exception, own_wasm_rt_throw,
    own_wasm_rt_exception_tag, own_wasm_rt_exception_size, own_wasm_rt_exception};
/* before the runtime starts: attach to the master if there is one that is the same, or note that this module runs on its own */
static int rt_dual_start(void) {
    PyObject *state = PyInterpreterState_GetDict(PyInterpreterState_Get());
    if (state == NULL) return -1;
    PyObject *found = PyDict_GetItemString(state, RT_CAPSULE);
    if (found != NULL) {
        const rt_vtable *t = (const rt_vtable *)PyCapsule_GetPointer(found, RT_CAPSULE);
        if (t == NULL) return -1;
        if (t->size >= sizeof(rt_vtable) && t->runtime == WASMEXT_RUNTIME) rt_M = t;  /* else: its runtime is another one, so this module runs on its own */
    }
    return 0;
}
/* after it started: a module on its own runtime becomes the master if there is none yet */
static int rt_dual_publish(void) {
    PyObject *state = PyInterpreterState_GetDict(PyInterpreterState_Get());
    if (state == NULL) return -1;
    if (rt_M != NULL || PyDict_GetItemString(state, RT_CAPSULE) != NULL) return 0;
    PyObject *cap = PyCapsule_New((void *)&rt_own, RT_CAPSULE, NULL);
    if (cap == NULL) return -1;
    int bad = PyDict_SetItemString(state, RT_CAPSULE, cap) < 0;
    Py_DECREF(cap);
    return bad ? -1 : 0;
}
#endif
#endif

#ifdef RT_SLAVE
/* the table of the master, set before anything of the runtime is called */
extern const rt_vtable *rt_M;
#ifndef RT_SHIM  /* the shim needs the table only */
static int rt_slave_attach(void) {
    PyObject *state = PyInterpreterState_GetDict(PyInterpreterState_Get());
    if (state == NULL) return -1;
    PyObject *found = PyDict_GetItemString(state, RT_CAPSULE);
    if (found == NULL) {
        PyErr_SetString(PyExc_ImportError, "shared runtime: no master module is loaded (import the master first)");
        return -1;
    }
    const rt_vtable *t = (const rt_vtable *)PyCapsule_GetPointer(found, RT_CAPSULE);
    if (t == NULL) return -1;
    if (t->size < sizeof(rt_vtable) || t->runtime != WASMEXT_RUNTIME) {
        PyErr_SetString(PyExc_ImportError, "shared runtime: the master's runtime is not the one this module was built for");
        return -1;
    }
    rt_M = t;
    return 0;
}
#endif
#elif !defined(RT_DUAL)
/* the master: the functions of its own runtime, and the table that holds them */
static void rt_thread_ready(void) {
    if (!wasmext_py_ready_) wasmext_py_thread_setup_();
}
static const rt_vtable rt_master = {
    sizeof(rt_vtable), WASMEXT_RUNTIME,
    wasm_rt_init, wasm_rt_is_initialized, wasm_rt_init_thread, wasm_rt_free_thread, rt_thread_ready, wasm_rt_trap, wasm_rt_strerror,
    wasm_rt_allocate_memory, wasm_rt_grow_memory, wasm_rt_free_memory,
    wasm_rt_allocate_funcref_table, wasm_rt_grow_funcref_table, wasm_rt_free_funcref_table,
    wasm_rt_allocate_externref_table, wasm_rt_grow_externref_table, wasm_rt_free_externref_table,
    wasm_rt_set_unwind_target, wasm_rt_get_unwind_target, wasm_rt_load_exception, wasm_rt_throw,
    wasm_rt_exception_tag, wasm_rt_exception_size, wasm_rt_exception};
static int rt_master_publish(void) {
    PyObject *state = PyInterpreterState_GetDict(PyInterpreterState_Get());
    if (state == NULL) return -1;
    if (PyDict_GetItemString(state, RT_CAPSULE) != NULL) return 0;  /* another master is there: this one runs on its own runtime */
    PyObject *cap = PyCapsule_New((void *)&rt_master, RT_CAPSULE, NULL);
    if (cap == NULL) return -1;
    int bad = PyDict_SetItemString(state, RT_CAPSULE, cap) < 0;
    Py_DECREF(cap);
    return bad ? -1 : 0;
}
#endif
#endif
