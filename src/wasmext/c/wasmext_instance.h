/* The instance: the same for every module. A static core over a generated `wasmext_binding`, the part that names the symbols that wasm2c made for the module
   (see <name>_binding.c, made by wasmext from the model). No Python, nothing of a front end in this file. See docs/step3_instances.md.

   An instance is made in a store (wasmext_store.h): every call enters the store, so a call into a closed store answers WASMEXT_TRAP_CLOSED and `close` of a
   store refuses while a call is in flight. A call answers 0, or the code of a trap (> 0: a WASM_RT_TRAP_* of the runtime, or a WASMEXT_TRAP_*, described by
   wasmext_errors.h), or a negative code of the API (a call that cannot be made). */
#ifndef WASMEXT_INSTANCE_H
#define WASMEXT_INSTANCE_H

#include <errno.h>
#include "wasmext_errors.h"
#include "wasmext_glue.h"
#include "wasmext_store.h"
#include "wasmext_descriptor.h"

/* A value of WebAssembly: its type is a byte of the binary format (0x7F i32, 0x7E i64, 0x7D f32, 0x7C f64, 0x7B v128, 0x70 funcref, 0x6F externref). Passed by
   pointer or in an array, never by value (a union in a signature differs between platforms). A v128 is 16 bytes in the order of WebAssembly memory (little-endian). */
typedef struct {
    uint8_t type;
    union {
        int32_t i32;
        int64_t i64;
        float f32;
        double f64;
        uint8_t v128[16];
        void *ref;
    } as;
} wasmext_val;

/* the answers of the API that are not a trap */
enum {
    WASMEXT_INST_OK = 0,
    WASMEXT_INST_BAD_EXPORT = -1,    /* an index out of range, or an export of another kind than the call needs */
    WASMEXT_INST_BAD_ARGS = -2,      /* the number or the types of the arguments or of the results do not fit the signature */
    WASMEXT_INST_NOT_INSTANTIATED = -3,
    WASMEXT_INST_UNSUPPORTED = -4,   /* a type that the core does not carry yet (a reference) */
    WASMEXT_INST_NOMEM = -5,
    WASMEXT_INST_BAD_IMPORT = -6,    /* an index out of range, an import that is not a function, or one that the core answers */
    WASMEXT_INST_TOO_LATE = -7       /* the instance is made already: imports are bound before `instantiate` */
};

/* The host function of an import, one shape for every import: `args` and `results` are arrays of the counts and the types of its signature (the descriptor
   has them). 0 is success; any other answer is a failure of the host, which keeps its own error: the call traps with WASMEXT_TRAP_HOST. A host function that
   is the export of another instance answers WASMEXT_TRAP_LINKED + the code of a trap of that instance, and the trap goes through with that code. */
typedef int (*wasmext_host_fn)(void *user, const wasmext_val *args, wasmext_val *results);

/* What the generated function of an import looks at: the uniform host function, or a typed one (`result f(void *user, parameters..., int *trapped)`, no packing
   of values: the fast path), and the `user` of both. The binding makes the slots; the core fills them. */
typedef struct {
    wasmext_host_fn host;
    void *typed;
    void *user;
} wasmext_import_slot;

/* one export of the binding, by the index of the descriptor: for a function, the adapter of its signature and the typed function of wasm2c */
typedef struct {
    int (*adapter)(void *instance, void *function, const wasmext_val *args, wasmext_val *results); /* 0 or a trap code; NULL: no call (not a function, or unsupported) */
    void *function;
} wasmext_export_binding;

/* What the generated code gives the core for a module. Constant data and the functions that name the symbols of wasm2c. */
typedef struct {
    const wasmext_descriptor *descriptor;
    size_t instance_size;                   /* sizeof the structure of the instance that wasm2c made */
    int (*instantiate)(void *instance);     /* wasm2c's instantiate, a trap caught: 0, or the code (the instance is then freed and cleared) */
    void (*release)(void *instance);        /* wasm2c's free */
    const wasmext_export_binding *exports;  /* descriptor->n_exports entries */
    wasmext_import_slot *(*import_slot)(void *instance, uint32_t import);  /* the slot of the import (of the descriptor); NULL when the module has none */
} wasmext_binding;

typedef struct {
    const wasmext_binding *binding;
    wasmext_store *store;
    void *module; /* the structure of wasm2c (and, after it, the slots of the imports) */
    unsigned char *bound; /* for each import of the descriptor: 1 once it has a host function */
    int instantiated;
    wasmext_counter status; /* the answer of the last call: 0, or the code of the trap. Atomic: with calls from several threads it is the answer of one of them; use the result of the call */
} wasmext_instance;

/* the runtime of wasm2c is set up once for each thread that calls into a module */
static WASM_RT_THREAD_LOCAL int wasmext_thread_ready_;
static inline void wasmext_thread_ready(void) {
    if (!wasmext_thread_ready_) {
        wasm_rt_init();
        wasmext_thread_ready_ = 1;
    }
}
/* the host calls it at the end of a thread that called into a module */
static inline void wasmext_thread_free(void) {
    if (wasmext_thread_ready_) {
        wasm_rt_free_thread();
        wasmext_thread_ready_ = 0;
    }
}

/* Makes an instance in `store`: NULL with `*error` (an errno) when it cannot be made. Imports, if any, are bound before `wasmext_instance_instantiate`. */
static inline wasmext_instance *wasmext_instance_new(wasmext_store *store, const wasmext_binding *binding, int *error) {
    int ignored;
    wasmext_instance *i;
    if (error == NULL) error = &ignored;
    if (store == NULL || binding == NULL) { *error = EINVAL; return NULL; }
    if (wasmext_store_closed(store)) { *error = EBADF; return NULL; }
    i = (wasmext_instance *)calloc(1, sizeof *i);
    if (i == NULL) { *error = ENOMEM; return NULL; }
    i->module = calloc(1, binding->instance_size);
    if (i->module == NULL) { free(i); *error = ENOMEM; return NULL; }
    i->bound = (unsigned char *)calloc(binding->descriptor->n_imports ? binding->descriptor->n_imports : 1, 1);
    if (i->bound == NULL) { free(i->module); free(i); *error = ENOMEM; return NULL; }
    i->binding = binding;
    i->store = store;
    *error = 0;
    return i;
}

/* the index (of the descriptor) of the function import `module`.`name`, or -1 */
static inline int wasmext_instance_import_find(const wasmext_instance *i, const char *module, size_t module_n, const char *name, size_t name_n) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_imports; k++) {
        const wasmext_import_desc *m = &d->imports[k];
        if (m->kind == WASMEXT_DESC_FUNC && m->module.n == module_n && m->name.n == name_n && memcmp(m->module.p, module, module_n) == 0 &&
            memcmp(m->name.p, name, name_n) == 0)
            return (int)k;
    }
    return -1;
}

static inline int wasmext_instance_bind_check_(const wasmext_instance *i, uint32_t import) {
    const wasmext_descriptor *d = i->binding->descriptor;
    if (i->instantiated) return WASMEXT_INST_TOO_LATE;
    if (import >= d->n_imports || d->imports[import].kind != WASMEXT_DESC_FUNC || d->imports[import].core || i->binding->import_slot == NULL)
        return WASMEXT_INST_BAD_IMPORT;
    return 0;
}

/* Binds the function import `import` (of the descriptor) to a host function of the uniform shape. A function can be bound again until `instantiate`. */
static inline int wasmext_instance_bind_func(wasmext_instance *i, uint32_t import, wasmext_host_fn fn, void *user) {
    int rc = wasmext_instance_bind_check_(i, import);
    wasmext_import_slot *slot;
    if (rc != 0) return rc;
    if (fn == NULL) return WASMEXT_INST_BAD_IMPORT;
    slot = i->binding->import_slot(i->module, import);
    slot->host = fn;
    slot->typed = NULL;
    slot->user = user;
    i->bound[import] = 1;
    return 0;
}

/* The same with a typed function, `result f(void *user, parameters..., int *trapped)` for the signature of the import: no packing of values. `*trapped` is as the
   answer of a uniform one (0, or a failure of the host, or WASMEXT_TRAP_LINKED + a code). The core cannot check the signature; the descriptor has it. */
static inline int wasmext_instance_bind_typed(wasmext_instance *i, uint32_t import, void *fn, void *user) {
    int rc = wasmext_instance_bind_check_(i, import);
    wasmext_import_slot *slot;
    if (rc != 0) return rc;
    if (fn == NULL) return WASMEXT_INST_BAD_IMPORT;
    slot = i->binding->import_slot(i->module, import);
    slot->host = NULL;
    slot->typed = fn;
    slot->user = user;
    i->bound[import] = 1;
    return 0;
}

/* Runs the start function: 0, or the code of a trap (then the instance is not usable and can only be freed). An import that nobody answers is
   WASMEXT_TRAP_LINK_ERROR, before anything runs, with the name in the text of the store (`wasmext_store_error`): bind it and try again. */
static inline int wasmext_instance_instantiate(wasmext_instance *i) {
    int line, rc;
    if (i->instantiated) return 0;
    for (uint32_t k = 0; k < i->binding->descriptor->n_imports; k++) {
        const wasmext_import_desc *m = &i->binding->descriptor->imports[k];
        if (m->kind == WASMEXT_DESC_FUNC && !m->core && !i->bound[k]) {
            char text[WASMEXT_STORE_ERROR_SIZE];
            snprintf(text, sizeof text, "the import %.*s.%.*s is not bound", (int)m->module.n, m->module.p, (int)m->name.n, m->name.p);
            wasmext_store_set_error(i->store, text);
            return (int)WASMEXT_TRAP_LINK_ERROR;
        }
    }
    line = wasmext_store_enter(i->store);
    if (line < 0) return (int)WASMEXT_TRAP_CLOSED;
    wasmext_thread_ready();
    rc = i->binding->instantiate(i->module);
    wasmext_store_leave(i->store, line);
    wasmext_atomic_store(&i->status, rc);
    if (rc == 0) i->instantiated = 1;
    return rc;
}

/* the index of the export `name` (UTF-8, `n` bytes) of the kind, or -1 */
static inline int wasmext_instance_export_find(const wasmext_instance *i, const char *name, size_t n, int kind) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_exports; k++) {
        const wasmext_export_desc *e = &d->exports[k];
        if (e->kind == (uint8_t)kind && e->name.n == n && memcmp(e->name.p, name, n) == 0) return (int)k;
    }
    return -1;
}

/* Calls the function export `index` (of the descriptor): `args` and `results` are arrays of the counts and the types of its signature (a mismatch is
   WASMEXT_INST_BAD_ARGS and nothing is called). 0, or the code of a trap (the instance stays usable, as in WebAssembly). */
static inline int wasmext_instance_call(wasmext_instance *i, uint32_t index, const wasmext_val *args, uint32_t n_args, wasmext_val *results, uint32_t n_results) {
    const wasmext_descriptor *d = i->binding->descriptor;
    const wasmext_export_desc *e;
    const wasmext_export_binding *b;
    int line, rc;
    if (index >= d->n_exports || d->exports[index].kind != WASMEXT_DESC_FUNC) return WASMEXT_INST_BAD_EXPORT;
    e = &d->exports[index];
    b = &i->binding->exports[index];
    if (e->type.n_params != n_args || e->type.n_results != n_results) return WASMEXT_INST_BAD_ARGS;
    for (uint32_t k = 0; k < n_args; k++)
        if (args[k].type != e->type.params[k]) return WASMEXT_INST_BAD_ARGS;
    if (b->adapter == NULL) return WASMEXT_INST_UNSUPPORTED;
    if (!i->instantiated) return WASMEXT_INST_NOT_INSTANTIATED;
    line = wasmext_store_enter(i->store);
    if (line < 0) return (int)WASMEXT_TRAP_CLOSED;
    wasmext_thread_ready();
    rc = b->adapter(i->module, b->function, args, results);
    wasmext_store_leave(i->store, line);
    wasmext_atomic_store(&i->status, rc);
    return rc;
}

/* The answer of the last call of the instance: 0, or the code of the trap. */
static inline int wasmext_instance_status(const wasmext_instance *i) { return (int)wasmext_atomic_load((wasmext_counter *)&i->status); }

static inline void wasmext_instance_free(wasmext_instance *i) {
    if (i == NULL) return;
    if (i->instantiated) i->binding->release(i->module);
    free(i->module);
    free(i->bound);
    free(i);
}

#endif
