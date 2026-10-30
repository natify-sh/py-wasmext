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
#include "wasmext_rlock.h"
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

/* A function as an element of a table holds it: a copy of the four words of `wasm_rt_funcref_t` (its type, the function, the instance) and where it comes from. `store` and `owner` (the
   handle of the instance in the registry of that store) are how a table checks that it is given a function of its own store. Valid as a value for as long as the store is open. */
typedef struct {
    wasm_rt_funcref_t ref;
    const void *store;
    wasmext_owner owner;
} wasmext_funcref;

/* the answers of the API that are not a trap */
enum {
    WASMEXT_INST_OK = 0,
    WASMEXT_INST_BAD_EXPORT = -1,    /* an index out of range, or an export of another kind than the call needs */
    WASMEXT_INST_BAD_ARGS = -2,      /* the number or the types of the arguments or of the results do not fit the signature */
    WASMEXT_INST_NOT_INSTANTIATED = -3,
    WASMEXT_INST_UNSUPPORTED = -4,   /* a type that the core does not carry yet (a reference) */
    WASMEXT_INST_NOMEM = -5,
    WASMEXT_INST_BAD_IMPORT = -6,    /* an index out of range, an import that is not a function, or one that the core answers */
    WASMEXT_INST_TOO_LATE = -7,      /* the instance is made already: imports are bound before `instantiate` */
    WASMEXT_INST_IMMUTABLE = -8,     /* a global that cannot be set */
    WASMEXT_INST_LINK_FAILED = -9,   /* an export given for an import does not fit: the text, naming the import, is in the store (`wasmext_store_error`) */
    WASMEXT_INST_UNDECLARED_TYPE = -10, /* `call_ref`: the function is of a type that the module does not declare, so it has no way to call it (it can still be called by WebAssembly) */
    /* the answers of the operations on a table and on a funcref (wasmext_table.h) */
    WASMEXT_TAB_BOUNDS = -30,       /* an index outside the table */
    WASMEXT_TAB_FULL = -31,         /* the table cannot grow that much (its maximum, or memory) */
    WASMEXT_TAB_WRONG_STORE = -32,  /* the function is of another store, or is not a function of one */
    WASMEXT_TAB_STALE = -33,        /* the element is a function that no member of the store stands behind */
    WASMEXT_TAB_WRONG_ELEM = -34    /* an operation on the elements of a funcref table, on a table of externref, or the other way */
};

/* The host function of an import, one shape for every import: `args` and `results` are arrays of the counts and the types of its signature (the descriptor
   has them). 0 is success; any other answer is a failure of the host, which keeps its own error: the call traps with WASMEXT_TRAP_HOST. A host function that
   is the export of another instance answers WASMEXT_TRAP_LINKED + the code of a trap of that instance, and the trap goes through with that code. */
typedef int (*wasmext_host_fn)(void *user, const wasmext_val *args, wasmext_val *results);

/* checks of the references that come in (defined below, where the rest of the references are) */
static inline int wasmext_funcref_check_(wasmext_store *store, const wasmext_funcref *f);
static inline int wasmext_extern_check_(wasmext_store *store, const void *e);

/* A function type that the module declares (its type section) and can call an element of: wasm2c's type (the pointer it compares first, then the 256-bit hash, as `call_indirect`
   does, so a function of another module with the same type matches), the adapter, and the signature. */
typedef struct {
    const char *(*type)(void);
    int (*adapter)(void *instance, void *function, const wasmext_val *args, wasmext_val *results);
    wasmext_functype sig;
    void *trampoline; /* `result f(void *module_instance, parameters...)`: the function of an element of this type that stands for a function of the host (wasmext_instance_host_funcref) */
} wasmext_ref_type;

/* What the generated function of an import looks at: the uniform host function, or a typed one (`result f(void *user, parameters..., int *trapped)`, no packing
   of values: the fast path), and the `user` of both. The binding makes the slots; the core fills them. */
typedef struct {
    wasmext_host_fn host;
    void *typed;
    void *user;
    void *self; /* the instance (wasmext_instance *) that the slot is of: what the generated function of an import needs to make a funcref of the store, set when a function is bound */
} wasmext_import_slot;

/* one export of the binding, by the index of the descriptor: for a function, the adapter of its signature and the typed function of wasm2c */
typedef struct {
    int (*adapter)(void *instance, void *function, const wasmext_val *args, wasmext_val *results); /* 0 or a trap code; NULL: no call (not a function, or unsupported) */
    void *function;
    void *(*address)(void *instance); /* a memory: its wasm_rt_memory_t *; a global: the pointer to its value (wasm2c's accessor); NULL for the others */
    void *shim;                       /* a function: `result f(void *wasmext_instance, parameters..., int *trapped)` for the record that another instance imports; a trap of this
                                         instance is answered as WASMEXT_TRAP_LINKED + its code. NULL for the others, and for a function with a reference in its signature */
    const char *signature;            /* a function: its signature as the record says it (the parameters, '>', the results: i j f d o) */
    void (*funcref)(void *instance, wasm_rt_funcref_t *out); /* a function: fills the element of a table that stands for it; NULL for the others, and for a function with a reference in its signature */
} wasmext_export_binding;

/* What the generated code gives the core for a module. Constant data and the functions that name the symbols of wasm2c. */
typedef struct {
    const wasmext_descriptor *descriptor;
    size_t instance_size;                   /* sizeof the structure of the instance that wasm2c made */
    int (*instantiate)(void *instance, void *host); /* wasm2c's instantiate, a trap caught: 0, or the code (the instance is then freed and cleared). `host` is the host of the
                                                       store (wasmext_host.h) for a module that has imports the core answers, else NULL */
    void (*release)(void *instance);        /* wasm2c's free */
    const wasmext_export_binding *exports;  /* descriptor->n_exports entries */
    wasmext_import_slot *(*import_slot)(void *instance, uint32_t import);  /* the slot of a function import (of the descriptor); NULL when the module has none */
    void **(*ref_slot)(void *instance, uint32_t import);  /* the pointer that wasm2c reads for a memory or global import (of the descriptor); NULL when the module has none */
    void (*call_begin)(void *instance);     /* before each call: forgets how the last one ended (the end of a WASI program is what a call leaves); NULL when the module has no WASI */
    int (*wasi_end)(void *instance, uint32_t *value); /* how the last call ended the WASI program: WASMEXT_END_NONE, EXIT (the code) or SIGNAL (the number); NULL when no WASI */
    const wasmext_ref_type *ref_types;      /* the function types of the type section that `call_ref` can call */
    uint32_t n_ref_types;
} wasmext_binding;

typedef struct wasmext_instance_s_ {
    const wasmext_binding *binding;
    wasmext_store *store;
    void *module; /* the structure of wasm2c (and, after it, the slots of the imports) */
    unsigned char *bound; /* for each import of the descriptor: 1 once it has a host function */
    void **owners;          /* for each import of the descriptor: the `owner` of the record it was linked to (what keeps the exporter alive: the host's business) */
    uint64_t (*values)[4];  /* for each import of the descriptor: room for the value of an immutable global that the host gives (32 bytes: a funcref is four words) */
    wasm_rt_funcref_t *refs; /* for each export of the descriptor (a function): the element of a table that stands for it, filled when the instance is made */
    wasmext_counter *pins;  /* for each export of the descriptor (a memory): how many pins it has */
    uint64_t *saved_max;    /* ... and the maximum it had before the first pin */
    WASMEXT_MUTEX_T pin_mutex;
    int instantiated;
    wasmext_owner owner; /* its handle in the registry of the store, once it is instantiated (0 before) */
    wasmext_counter status; /* the answer of the last call: 0, or the code of the trap. Atomic: with calls from several threads it is the answer of one of them; use the result of the call */
} wasmext_instance;

/* The runtime of wasm2c is set up once for each thread that calls into a module. The flag is one for the artifact, not one for each file that includes this header (a
   binding and the code that calls it would each set the thread up, and the runtime aborts on the second): exactly one file of an artifact defines it, by defining
   WASMEXT_DEFINE_THREAD_STATE before it includes this header (the file with the front end; a test defines it in its main file). (`wasm_rt_is_initialized` is not used: a
   sanitizer installs an alternate stack of its own in every thread and the runtime then takes the thread for set up.) */
extern WASM_RT_THREAD_LOCAL int wasmext_thread_ready_;
#ifdef WASMEXT_DEFINE_THREAD_STATE
WASM_RT_THREAD_LOCAL int wasmext_thread_ready_;
#endif
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

/* What the store does with an instance. At the close it releases the structure of wasm2c (the wrapper `wasmext_instance` stays valid, closed, until the store is freed); the
   wrapper is freed with the store (adopted), or earlier by `wasmext_instance_free` for an instance that was never registered. */
static inline void wasmext_instance_close_(void *object) {
    wasmext_instance *i = (wasmext_instance *)object;
    if (i->module != NULL) {
        if (i->instantiated) i->binding->release(i->module);
        free(i->module);
        i->module = NULL;
    }
}
static inline void wasmext_instance_wrapper_free_(void *object) {
    wasmext_instance *i = (wasmext_instance *)object;
    wasmext_instance_close_(i);
    WASMEXT_MUTEX_DESTROY(&i->pin_mutex);
    free(i->bound);
    free(i->owners);
    free(i->values);
    free(i->refs);
    free(i->pins);
    free(i->saved_max);
    free(i);
}
static const wasmext_owner_ops wasmext_instance_ops_ = {NULL, NULL, NULL, wasmext_instance_close_};

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
    i->owners = (void **)calloc(binding->descriptor->n_imports ? binding->descriptor->n_imports : 1, sizeof(void *));
    i->values = (uint64_t (*)[4])calloc(binding->descriptor->n_imports ? binding->descriptor->n_imports : 1, sizeof(uint64_t[4]));
    i->pins = (wasmext_counter *)calloc(binding->descriptor->n_exports ? binding->descriptor->n_exports : 1, sizeof(wasmext_counter));
    i->saved_max = (uint64_t *)calloc(binding->descriptor->n_exports ? binding->descriptor->n_exports : 1, sizeof(uint64_t));
    i->refs = (wasm_rt_funcref_t *)calloc(binding->descriptor->n_exports ? binding->descriptor->n_exports : 1, sizeof(wasm_rt_funcref_t));
    if (i->owners == NULL || i->values == NULL || i->pins == NULL || i->saved_max == NULL || i->refs == NULL) {
        free(i->owners); free(i->values); free(i->pins); free(i->saved_max); free(i->refs); free(i->bound); free(i->module); free(i);
        *error = ENOMEM;
        return NULL;
    }
    WASMEXT_MUTEX_INIT(&i->pin_mutex);
    i->binding = binding;
    i->store = store;
    if (wasmext_store_adopt(store, i, wasmext_instance_wrapper_free_) != WASMEXT_STORE_OK) {
        wasmext_instance_wrapper_free_(i);
        *error = ENOMEM;
        return NULL;
    }
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
    slot->self = i;
    i->bound[import] = 1;
    return 0;
}

/* The same with a typed function, `result f(void *user, parameters..., int *trapped)` for the signature of the import: no packing of values. `*trapped` is as the
   answer of a uniform one (0, or a failure of the host, or WASMEXT_TRAP_LINKED + a code). The core cannot check the signature; the descriptor has it. */
static inline int wasmext_instance_bind_typed(wasmext_instance *i, uint32_t import, void *fn, void *user) {
    int rc = wasmext_instance_bind_check_(i, import);
    wasmext_import_slot *slot;
    const wasmext_functype *ft;
    if (rc != 0) return rc;
    if (fn == NULL) return WASMEXT_INST_BAD_IMPORT;
    ft = &i->binding->descriptor->imports[import].type;
    for (uint32_t k = 0; k < ft->n_params + ft->n_results; k++)
        {
            uint8_t t = k < ft->n_params ? ft->params[k] : ft->results[k - ft->n_params];
            if (t == 0x70 || t == 0x6F) return WASMEXT_INST_UNSUPPORTED; /* a reference is checked as it comes in: the typed shape has none, the uniform one does */
        }
    slot = i->binding->import_slot(i->module, import);
    slot->host = NULL;
    slot->typed = fn;
    slot->user = user;
    slot->self = i;
    i->bound[import] = 1;
    return 0;
}

/* ---- links between instances: the record of an export, and an import given one ---- */

static inline int wasmext_instance_link_fail_(wasmext_instance *i, const wasmext_import_desc *m, const char *what, const char *detail) {
    char text[WASMEXT_STORE_ERROR_SIZE];
    snprintf(text, sizeof text, "import %.*s.%.*s %s%s", (int)m->module.n, m->module.p, (int)m->name.n, m->name.p, what, detail);
    wasmext_store_set_error(i->store, text);
    return WASMEXT_INST_LINK_FAILED;
}

/* the signature as a record says it: the parameters, '>', the results, a letter each (i j f d o) */
static inline void wasmext_instance_signature_(const wasmext_functype *t, char *out, size_t cap) {
    size_t n = 0;
    for (uint32_t k = 0; k < t->n_params + t->n_results + 1 && n + 1 < cap; k++) {
        if (k == t->n_params) { out[n++] = '>'; continue; }
        {
            uint8_t b = k < t->n_params ? t->params[k] : t->results[k - t->n_params - 1];
            out[n++] = b == 0x7F ? 'i' : b == 0x7E ? 'j' : b == 0x7D ? 'f' : b == 0x7C ? 'd' : b == 0x7B ? 'o' : 'r';
        }
    }
    out[n] = 0;
}

/* The record of an exported function, memory or global, for another instance to import (`wasmext_export` of wasmext_glue.h: public, versioned). `owner` is whatever keeps this
   instance alive for as long as the record is used: the host's business, which the core only passes on. The record is valid as long as this instance is. */
static inline int wasmext_instance_export_record(wasmext_instance *i, uint32_t index, void *owner, wasmext_export *out) {
    const wasmext_descriptor *d = i->binding->descriptor;
    const wasmext_export_binding *b;
    if (index >= d->n_exports) return WASMEXT_INST_BAD_EXPORT;
    b = &i->binding->exports[index];
    if (!i->instantiated) return WASMEXT_INST_NOT_INSTANTIATED;
    if (wasmext_store_closed(i->store)) return (int)WASMEXT_TRAP_CLOSED;
    memset(out, 0, sizeof *out);
    out->size = sizeof *out;
    out->abi = WASMEXT_ABI;
    out->owner = owner;
    out->runtime = WASMEXT_RUNTIME;
    out->store = i->store;
    switch (d->exports[index].kind) {
        case WASMEXT_DESC_FUNC:
            if (b->shim == NULL) return WASMEXT_INST_UNSUPPORTED;
            out->kind = WASMEXT_FUNC;
            out->flags = 8u; /* callable with no Python */
            out->address = b->shim;
            out->instance = i;
            out->signature = b->signature;
            if (i->refs[index].func != NULL) {
                out->funcref = &i->refs[index];
                out->flags |= 16u; /* may be put in a table (of this store) */
            }
            break;
        case WASMEXT_DESC_MEMORY: {
            wasm_rt_memory_t *m = (wasm_rt_memory_t *)b->address(i->module);
            out->kind = WASMEXT_MEMORY;
            out->type = (uint32_t)sizeof(wasm_rt_memory_t);
            out->flags = (m->is64 ? 2u : 0u) | (WASM_RT_MEMCHECK_GUARD_PAGES ? 4u : 0u);
            out->address = m;
            break;
        }
        case WASMEXT_DESC_GLOBAL: {
            const wasmext_global_desc *g = &d->globals[d->exports[index].index];
            out->kind = WASMEXT_GLOBAL;
            out->type = g->type;
            out->flags = g->is_mutable ? 1u : 0u;
            out->address = b->address(i->module);
            break;
        }
        case WASMEXT_DESC_TABLE: {
            const wasmext_table_desc *t = &d->tables[d->exports[index].index];
            if ((t->elem != 0x70 && t->elem != 0x6F) || t->limits.is64 || t->limits.shared || b->address == NULL) return WASMEXT_INST_UNSUPPORTED;
            out->kind = WASMEXT_TABLE;
            out->type = (uint32_t)sizeof(wasm_rt_funcref_table_t); /* the same size for externref */
            if (t->elem == 0x6F) out->flags |= 32u; /* the elements are externref */
            out->address = b->address(i->module);
            break;
        }
        default:
            return WASMEXT_INST_UNSUPPORTED; /* a tag: step 7 */
    }
    wasmext_export_seal(out);
    return 0;
}

/* Gives an import the record of an export of another instance (of this store or another). The checks are those that the old glue made for each import, once, from the
   descriptor: the record is of a version this reader can use, of the kind of the import, and fits it (the signature of a function; the type and the mutability of a global;
   the runtime, the 64-bit and the guard pages of a memory, and its pages against what the import needs). WASMEXT_INST_LINK_FAILED, with the reason in the text of the store, when it does not. */
static inline int wasmext_instance_bind_export(wasmext_instance *i, uint32_t import, const wasmext_export *e) {
    const wasmext_descriptor *d = i->binding->descriptor;
    const wasmext_import_desc *m;
    if (i->instantiated) return WASMEXT_INST_TOO_LATE;
    if (import >= d->n_imports || d->imports[import].core) return WASMEXT_INST_BAD_IMPORT;
    m = &d->imports[import];
    if (!wasmext_export_ok(e)) return wasmext_instance_link_fail_(i, m, "is linked to an export from an incompatible version of wasmext", "");
    /* Instances are linked inside one store: the store frees its members when it is closed, and an importer in another store would read what the close freed. */
    if (e->size < offsetof(wasmext_export, store) + sizeof e->store || e->store != (const void *)i->store)
        return wasmext_instance_link_fail_(i, m, "is linked to an export of another store: instances are linked inside one store", "");
    switch (m->kind) {
        case WASMEXT_DESC_FUNC: {
            char want[160];
            wasmext_import_slot *slot;
            wasmext_instance_signature_(&m->type, want, sizeof want);
            if (e->kind != WASMEXT_FUNC || e->address == NULL) return wasmext_instance_link_fail_(i, m, "is a function: the export given is not", "");
            if (strchr(want, 'r') != NULL) return wasmext_instance_link_fail_(i, m, "has a funcref in its signature: a function with one cannot be linked to an export (a funcref is a struct, the typed shape has none)", "");
            if (e->signature == NULL || strcmp(e->signature, want) != 0) {
                char detail[200];
                snprintf(detail, sizeof detail, " %s: the export given is another one (%s)", want, e->signature != NULL ? e->signature : "none");
                return wasmext_instance_link_fail_(i, m, "is a function", detail);
            }
            if (i->binding->import_slot == NULL) return WASMEXT_INST_BAD_IMPORT;
            slot = i->binding->import_slot(i->module, import);
            slot->host = NULL;
            slot->typed = e->address;
            slot->user = e->instance;
            slot->self = i;
            break;
        }
        case WASMEXT_DESC_MEMORY: {
            const wasmext_limits *lim = &d->memories[m->index];
            const wasm_rt_memory_t *mem = (const wasm_rt_memory_t *)e->address;
            if (e->kind != WASMEXT_MEMORY || mem == NULL) return wasmext_instance_link_fail_(i, m, "is a memory: the export given is not", "");
            if (e->type != sizeof(wasm_rt_memory_t)) return wasmext_instance_link_fail_(i, m, ": the memory is from an incompatible runtime of wasm2c", "");
            if (((e->flags >> 1) & 1u) != (uint32_t)lim->is64) return wasmext_instance_link_fail_(i, m, " is a memory64 the other way: memory64 differs", "");
            if (((e->flags >> 2) & 1u) != (WASM_RT_MEMCHECK_GUARD_PAGES ? 1u : 0u))
                return wasmext_instance_link_fail_(i, m, ": one module is built with guard pages and the other without (--no-guard-pages)", "");
            if (mem->pages < lim->min) {
                char detail[120];
                snprintf(detail, sizeof detail, ": the memory has %llu pages, the module needs at least %llu", (unsigned long long)mem->pages, (unsigned long long)lim->min);
                return wasmext_instance_link_fail_(i, m, "", detail);
            }
            if (lim->has_max && mem->max_pages > lim->max) {
                char detail[120];
                snprintf(detail, sizeof detail, ": the memory may grow to %llu pages, the module allows %llu", (unsigned long long)mem->max_pages, (unsigned long long)lim->max);
                return wasmext_instance_link_fail_(i, m, "", detail);
            }
            if (i->binding->ref_slot == NULL) return WASMEXT_INST_BAD_IMPORT;
            *i->binding->ref_slot(i->module, import) = (void *)mem;
            break;
        }
        case WASMEXT_DESC_GLOBAL: {
            const wasmext_global_desc *g = &d->globals[m->index];
            if (e->kind != WASMEXT_GLOBAL || e->address == NULL) return wasmext_instance_link_fail_(i, m, "is a global: the export given is not", "");
            if (e->type != g->type || (e->flags & 1u) != (uint32_t)g->is_mutable)
                return wasmext_instance_link_fail_(i, m, "is a global of another type or mutability than the export given", "");
            if (i->binding->ref_slot == NULL) return WASMEXT_INST_BAD_IMPORT;
            *i->binding->ref_slot(i->module, import) = e->address;
            break;
        }
        case WASMEXT_DESC_TABLE: {
            const wasmext_table_desc *t = &d->tables[m->index];
            uint32_t size, max_size;
            if ((t->elem != 0x70 && t->elem != 0x6F) || t->limits.is64 || t->limits.shared) return WASMEXT_INST_UNSUPPORTED;
            if (e->kind != WASMEXT_TABLE || e->address == NULL) return wasmext_instance_link_fail_(i, m, "is a table: the export given is not", "");
            if (e->type != sizeof(wasm_rt_funcref_table_t)) return wasmext_instance_link_fail_(i, m, ": the table is from an incompatible runtime of wasm2c", "");
            if (((e->flags >> 5) & 1u) != (t->elem == 0x6F ? 1u : 0u)) return wasmext_instance_link_fail_(i, m, ": the elements of the table are not of the type the module needs (funcref or externref)", "");
            if (t->elem == 0x70) {
                size = ((const wasm_rt_funcref_table_t *)e->address)->size;
                max_size = ((const wasm_rt_funcref_table_t *)e->address)->max_size;
            } else {
                size = ((const wasm_rt_externref_table_t *)e->address)->size;
                max_size = ((const wasm_rt_externref_table_t *)e->address)->max_size;
            }
            if (size < t->limits.min) {
                char detail[120];
                snprintf(detail, sizeof detail, ": the table has %lu elements, the module needs at least %llu", (unsigned long)size, (unsigned long long)t->limits.min);
                return wasmext_instance_link_fail_(i, m, "", detail);
            }
            if (t->limits.has_max && max_size > t->limits.max) {
                char detail[120];
                snprintf(detail, sizeof detail, ": the table may grow to %lu elements, the module allows %llu", (unsigned long)max_size, (unsigned long long)t->limits.max);
                return wasmext_instance_link_fail_(i, m, "", detail);
            }
            if (i->binding->ref_slot == NULL) return WASMEXT_INST_BAD_IMPORT;
            *i->binding->ref_slot(i->module, import) = e->address;
            break;
        }
        default:
            return WASMEXT_INST_UNSUPPORTED; /* a tag: step 7 */
    }
    i->bound[import] = 1;
    i->owners[import] = e->owner;
    return 0;
}

/* Gives an immutable global import a value of the host (a number). */
static inline int wasmext_instance_bind_global_value(wasmext_instance *i, uint32_t import, const wasmext_val *v) {
    const wasmext_descriptor *d = i->binding->descriptor;
    const wasmext_import_desc *m;
    const wasmext_global_desc *g;
    void *cell;
    if (i->instantiated) return WASMEXT_INST_TOO_LATE;
    if (import >= d->n_imports || d->imports[import].core || d->imports[import].kind != WASMEXT_DESC_GLOBAL || i->binding->ref_slot == NULL) return WASMEXT_INST_BAD_IMPORT;
    m = &d->imports[import];
    g = &d->globals[m->index];
    if (g->is_mutable) return WASMEXT_INST_IMMUTABLE; /* a mutable global is the global of another instance */
    if (v->type != g->type) return WASMEXT_INST_BAD_ARGS;
    cell = i->values[import];
    switch (g->type) {
        case 0x7F: *(uint32_t *)cell = (uint32_t)v->as.i32; break;
        case 0x7E: *(uint64_t *)cell = (uint64_t)v->as.i64; break;
        case 0x7D: *(float *)cell = v->as.f32; break;
        case 0x7C: *(double *)cell = v->as.f64; break;
        case 0x70: { /* `as.ref` is a wasmext_funcref of the store, or NULL for a null funcref */
            const wasmext_funcref *f = (const wasmext_funcref *)v->as.ref;
            int rc = wasmext_funcref_check_(i->store, f);
            if (rc != 0) return rc;
            if (f == NULL) memset(cell, 0, sizeof(wasm_rt_funcref_t));
            else memcpy(cell, &f->ref, sizeof(wasm_rt_funcref_t));
            break;
        }
        case 0x6F: { /* `as.ref` is a reference of the store, or NULL */
            int rc = wasmext_extern_check_(i->store, v->as.ref);
            if (rc != 0) return rc;
            *(void **)cell = v->as.ref;
            break;
        }
        default: memcpy(cell, v->as.v128, 16); break;
    }
    *i->binding->ref_slot(i->module, import) = cell;
    i->bound[import] = 1;
    return 0;
}

/* the `owner` of the record that an import was linked to (what keeps the exporter alive), or NULL */
static inline void *wasmext_instance_import_owner(const wasmext_instance *i, uint32_t import) {
    return import < i->binding->descriptor->n_imports ? i->owners[import] : NULL;
}

/* For the typed function of an export that another instance calls (<name>_binding.c): enter this instance's store and the host lock level; the answer is 0, or the trap code
   to give the caller (as WASMEXT_TRAP_LINKED + it). `wasmext_instance_end_` lets go of what a trap left. */
static inline int wasmext_instance_begin_(wasmext_instance *i, int *line, long *level) {
    wasmext_rlock *lock;
    if (!i->instantiated) return (int)WASMEXT_TRAP_HOST;
    *line = wasmext_store_enter(i->store);
    if (*line < 0) return (int)WASMEXT_TRAP_CLOSED;
    wasmext_thread_ready();
    lock = (wasmext_rlock *)wasmext_store_host_lock(i->store);
    *level = lock != NULL ? wasmext_rlock_depth(lock) : 0;
    if (i->binding->call_begin != NULL) i->binding->call_begin(i->module);
    return 0;
}
static inline void wasmext_instance_end_(wasmext_instance *i, int line, long level) {
    wasmext_rlock *lock = (wasmext_rlock *)wasmext_store_host_lock(i->store);
    if (lock != NULL) wasmext_rlock_release_to(lock, level);
    wasmext_store_leave(i->store, line);
}

/* An instance whose instantiation failed has run its `elem` segments, and the start function, perhaps: functions of its own may stand in the tables it imports, and the structure
   they point to is released and cleared. Takes them out (the slots become null) so that the owner of the table, and the others that share it, do not call a function that is
   gone. The host does not call into the store with the tables while an instance is made (as `table.set` of WebAssembly, a write to a table is not synchronised). */
static inline void wasmext_instance_scrub_tables_(wasmext_instance *i) {
    const wasmext_descriptor *d = i->binding->descriptor;
    const char *lo = (const char *)i->module, *hi = lo + i->binding->instance_size;
    for (uint32_t k = 0; k < d->n_imports; k++) {
        wasm_rt_funcref_table_t *tab;
        if (d->imports[k].kind == WASMEXT_DESC_GLOBAL && i->bound[k] && i->binding->ref_slot != NULL && d->globals[d->imports[k].index].type == 0x70 && d->globals[d->imports[k].index].is_mutable) {
            /* a mutable global of funcref that the instance shares: its start function may have put a function of its own in it */
            wasm_rt_funcref_t *g = (wasm_rt_funcref_t *)*i->binding->ref_slot(i->module, k);
            const char *mi = g != NULL ? (const char *)g->module_instance : NULL;
            if (g != NULL && g->func != NULL && mi >= lo && mi < hi) memset(g, 0, sizeof *g);
            continue;
        }
        if (d->imports[k].kind != WASMEXT_DESC_TABLE || d->tables[d->imports[k].index].elem != 0x70 || !i->bound[k] || i->binding->ref_slot == NULL) continue; /* the elements of an externref table are not functions */
        tab = (wasm_rt_funcref_table_t *)*i->binding->ref_slot(i->module, k);
        for (uint32_t e = 0; tab != NULL && e < tab->size; e++) {
            const char *mi = (const char *)tab->data[e].module_instance;
            if (tab->data[e].func != NULL && mi >= lo && mi < hi) memset(&tab->data[e], 0, sizeof tab->data[e]);
        }
    }
}

/* Runs the start function: 0, or the code of a trap (then the instance is not usable and can only be freed). An import that nobody answers is
   WASMEXT_TRAP_LINK_ERROR, before anything runs, with the name in the text of the store (`wasmext_store_error`): bind it and try again. */
static inline int wasmext_instance_instantiate(wasmext_instance *i) {
    int line, rc;
    void *host = NULL;
    wasmext_rlock *lock;
    long level;
    if (i->instantiated) return 0;
    for (uint32_t k = 0; k < i->binding->descriptor->n_imports; k++) {
        const wasmext_import_desc *m = &i->binding->descriptor->imports[k];
        if (!m->core && !i->bound[k]) {
            char text[WASMEXT_STORE_ERROR_SIZE];
            snprintf(text, sizeof text, "the import %.*s.%.*s is not bound", (int)m->module.n, m->module.p, (int)m->name.n, m->name.p);
            wasmext_store_set_error(i->store, text);
            return (int)WASMEXT_TRAP_LINK_ERROR;
        }
    }
    if (i->binding->descriptor->flags & WASMEXT_DESC_USES_CORE) {
        host = wasmext_store_host(i->store);
        if (host == NULL) {
            wasmext_store_set_error(i->store, "the store has no host for the WASI imports of the module");
            return (int)WASMEXT_TRAP_LINK_ERROR;
        }
    }
    line = wasmext_store_enter(i->store);
    if (line < 0) return (int)WASMEXT_TRAP_CLOSED;
    wasmext_thread_ready();
    lock = (wasmext_rlock *)wasmext_store_host_lock(i->store);
    level = lock != NULL ? wasmext_rlock_depth(lock) : 0;
    rc = i->binding->instantiate(i->module, host);
    if (lock != NULL) wasmext_rlock_release_to(lock, level); /* a trap left the unlocks of fusedwasi behind */
    wasmext_store_leave(i->store, line);
    wasmext_atomic_store(&i->status, rc);
    if (rc != 0) wasmext_instance_scrub_tables_(i);
    if (rc == 0) {
        /* the store holds the instance from now until the close, and finds it by the pointer that its funcrefs carry */
        int reg = wasmext_store_register(i->store, i->module, i, &wasmext_instance_ops_, &i->owner);
        if (reg != WASMEXT_STORE_OK) {
            i->binding->release(i->module);
            wasmext_instance_scrub_tables_(i);
            memset(i->module, 0, i->binding->instance_size);
            rc = reg == WASMEXT_STORE_CLOSED ? (int)WASMEXT_TRAP_CLOSED : (int)WASMEXT_TRAP_NO_MEMORY;
            wasmext_atomic_store(&i->status, rc);
            return rc;
        }
        for (uint32_t k = 0; k < i->binding->descriptor->n_exports; k++)
            if (i->binding->exports[k].funcref != NULL) i->binding->exports[k].funcref(i->module, &i->refs[k]);
        i->instantiated = 1;
    }
    return rc;
}

/* Whether `f` is a function of `store` and was made by this API: its store, and the handle of its instance, which must be the member of the store under the pointer `f` carries. A null
   funcref is always acceptable (it is "no function"). 0, or WASMEXT_TAB_WRONG_STORE. */
static inline int wasmext_funcref_check_(wasmext_store *store, const wasmext_funcref *f) {
    wasmext_owner owner;
    if (f == NULL || f->ref.func == NULL) return 0;
    if (f->store != (const void *)store) return WASMEXT_TAB_WRONG_STORE;
    if (wasmext_store_find(store, f->ref.module_instance, &owner) != WASMEXT_STORE_OK || owner != f->owner) return WASMEXT_TAB_WRONG_STORE;
    return 0;
}

/* ---- externref (docs/step6_externref.md) ---- */

/* A value of the host that WebAssembly holds as an `externref`: the pointer to this record is the reference. WebAssembly never reads it; the store keeps the record until it is closed, then
   calls `release(user)` once. */
typedef struct {
    void *user;
    void (*release)(void *user);
    wasmext_store *store;
    int released;
} wasmext_extern;

static inline void wasmext_extern_close_(void *object) {
    wasmext_extern *e = (wasmext_extern *)object;
    if (!e->released) {
        e->released = 1;
        if (e->release != NULL) e->release(e->user);
    }
}
static inline void wasmext_extern_free_(void *object) {
    wasmext_extern_close_(object);
    free(object);
}
static const wasmext_owner_ops wasmext_extern_ops_ = {NULL, NULL, NULL, wasmext_extern_close_};

/* Gives the store a value to hold (`user`, which the host owns; `release(user)` is called once when the store is closed, and may be NULL). `*out` is the reference. */
static inline int wasmext_extern_new(wasmext_store *store, void *user, void (*release)(void *user), wasmext_extern **out) {
    wasmext_extern *e;
    wasmext_owner owner;
    int rc;
    if (store == NULL || out == NULL) return WASMEXT_INST_BAD_ARGS;
    if (wasmext_store_closed(store)) return (int)WASMEXT_TRAP_CLOSED;
    e = (wasmext_extern *)calloc(1, sizeof *e);
    if (e == NULL) return WASMEXT_INST_NOMEM;
    e->user = user;
    e->release = release;
    e->store = store;
    if (wasmext_store_adopt(store, e, wasmext_extern_free_) != WASMEXT_STORE_OK) {
        free(e);
        return WASMEXT_INST_NOMEM;
    }
    rc = wasmext_store_register(store, e, e, &wasmext_extern_ops_, &owner);
    if (rc != WASMEXT_STORE_OK) {
        wasmext_store_unadopt(store, e);
        free(e);
        return rc == WASMEXT_STORE_CLOSED ? (int)WASMEXT_TRAP_CLOSED : WASMEXT_INST_NOMEM;
    }
    *out = e;
    return 0;
}

/* The value of a reference (NULL for a null reference). Only for a reference that came out of the store, or that a check below accepted. */
static inline void *wasmext_extern_user(const wasmext_extern *e) { return e != NULL ? e->user : NULL; }

/* Whether `e` is a reference of `store` (made by wasmext_extern_new): it must be a member of the store; the pointer is not read before. NULL is a null reference, always acceptable. 0, or
   WASMEXT_TAB_WRONG_STORE. */
static inline int wasmext_extern_check_(wasmext_store *store, const void *e) {
    wasmext_owner owner;
    if (e == NULL) return 0;
    return wasmext_store_find(store, e, &owner) == WASMEXT_STORE_OK ? 0 : WASMEXT_TAB_WRONG_STORE;
}

/* The reference that a host function answers (`r`, of type 0x6F, whose `as.ref` is a reference of the store, or NULL) into `out`. */
static inline int wasmext_extern_result_(void *self, const wasmext_val *r, wasm_rt_externref_t *out) {
    wasmext_instance *i = (wasmext_instance *)self;
    int rc;
    if (r->type != 0x6F) return WASMEXT_INST_BAD_ARGS;
    rc = wasmext_extern_check_(i->store, r->as.ref);
    if (rc != 0) return rc;
    *out = r->as.ref;
    return 0;
}

/* The funcref that wasm passes to a host function: `out` is made from the element `r`, of the store of the instance `self` (the slot's). WASMEXT_TAB_STALE when `r` is a function
   that no member of the store stands behind. A null funcref is a funcref with no function. */
static inline int wasmext_funcref_from_(void *self, const wasm_rt_funcref_t *r, wasmext_funcref *out) {
    wasmext_instance *i = (wasmext_instance *)self;
    out->ref = *r;
    out->store = i->store;
    out->owner = 0;
    if (r->func == NULL) return 0;
    return wasmext_store_find(i->store, r->module_instance, &out->owner) == WASMEXT_STORE_OK ? 0 : WASMEXT_TAB_STALE;
}

/* The funcref that a host function answers (`r`, whose type must be 0x70 and whose `as.ref` is a `wasmext_funcref` of its own, or NULL for a null funcref) into `out`: 0, or an error
   (the call then traps with the failure of the host). */
static inline int wasmext_funcref_result_(void *self, const wasmext_val *r, wasm_rt_funcref_t *out) {
    wasmext_instance *i = (wasmext_instance *)self;
    const wasmext_funcref *f = (const wasmext_funcref *)r->as.ref;
    int rc;
    if (r->type != 0x70) return WASMEXT_INST_BAD_ARGS;
    rc = wasmext_funcref_check_(i->store, f);
    if (rc != 0) return rc;
    if (f == NULL) memset(out, 0, sizeof *out);
    else *out = f->ref;
    return 0;
}

/* Before a call: a funcref argument is of this store (or null), and a funcref result has a `wasmext_funcref` to be filled (the caller points `as.ref` at one). After it, the funcref
   results get their store and the handle of their instance. `ptypes` and `rtypes` are the types of the signature. */
static inline int wasmext_call_check_refs_(wasmext_store *s, const wasmext_functype *t, const wasmext_val *args, const wasmext_val *results) {
    for (uint32_t k = 0; k < t->n_params; k++) {
        int rc = 0;
        if (t->params[k] == 0x70) rc = wasmext_funcref_check_(s, (const wasmext_funcref *)args[k].as.ref);
        else if (t->params[k] == 0x6F) rc = wasmext_extern_check_(s, args[k].as.ref);
        if (rc != 0) return rc;
    }
    for (uint32_t k = 0; k < t->n_results; k++)
        if (t->results[k] == 0x70 && results[k].as.ref == NULL) return WASMEXT_INST_BAD_ARGS;
    return 0;
}
static inline int wasmext_call_fill_refs_(wasmext_store *s, const wasmext_functype *t, wasmext_val *results) {
    for (uint32_t k = 0; k < t->n_results; k++)
        if (t->results[k] == 0x70) {
            wasmext_funcref *f = (wasmext_funcref *)results[k].as.ref;
            f->store = s;
            f->owner = 0;
            if (f->ref.func != NULL && wasmext_store_find(s, f->ref.module_instance, &f->owner) != WASMEXT_STORE_OK) return WASMEXT_TAB_STALE;
        }
    return 0;
}

/* The exported function `index` as an element of a table: `out` is the value that `wasmext_tab_set` takes. WASMEXT_INST_UNSUPPORTED for a function with a reference in its signature. */
static inline int wasmext_instance_funcref(wasmext_instance *i, uint32_t index, wasmext_funcref *out) {
    const wasmext_descriptor *d = i->binding->descriptor;
    if (index >= d->n_exports || d->exports[index].kind != WASMEXT_DESC_FUNC) return WASMEXT_INST_BAD_EXPORT;
    if (!i->instantiated) return WASMEXT_INST_NOT_INSTANTIATED;
    if (wasmext_store_closed(i->store)) return (int)WASMEXT_TRAP_CLOSED;
    if (i->refs[index].func == NULL) return WASMEXT_INST_UNSUPPORTED;
    out->ref = i->refs[index];
    out->store = i->store;
    out->owner = i->owner;
    return 0;
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
    wasmext_rlock *lock;
    long level;
    if (index >= d->n_exports || d->exports[index].kind != WASMEXT_DESC_FUNC) return WASMEXT_INST_BAD_EXPORT;
    e = &d->exports[index];
    b = &i->binding->exports[index];
    if (e->type.n_params != n_args || e->type.n_results != n_results) return WASMEXT_INST_BAD_ARGS;
    for (uint32_t k = 0; k < n_args; k++)
        if (args[k].type != e->type.params[k]) return WASMEXT_INST_BAD_ARGS;
    if (b->adapter == NULL) return WASMEXT_INST_UNSUPPORTED;
    if (!i->instantiated) return WASMEXT_INST_NOT_INSTANTIATED;
    rc = wasmext_call_check_refs_(i->store, &e->type, args, results);
    if (rc != 0) return rc;
    line = wasmext_store_enter(i->store);
    if (line < 0) return (int)WASMEXT_TRAP_CLOSED;
    wasmext_thread_ready();
    lock = (wasmext_rlock *)wasmext_store_host_lock(i->store);
    level = lock != NULL ? wasmext_rlock_depth(lock) : 0;
    if (i->binding->call_begin != NULL) i->binding->call_begin(i->module);
    rc = b->adapter(i->module, b->function, args, results);
    if (lock != NULL) wasmext_rlock_release_to(lock, level); /* a trap left the unlocks of fusedwasi behind */
    if (rc == 0) rc = wasmext_call_fill_refs_(i->store, &e->type, results);
    wasmext_store_leave(i->store, line);
    wasmext_atomic_store(&i->status, rc);
    return rc;
}

/* Calls a function that stands for an element of a table (a `wasmext_funcref` of this store, from `wasmext_tab_get` or `wasmext_instance_funcref`) through this instance: the function
   must be of a type that this module declares (WASMEXT_INST_UNDECLARED_TYPE otherwise), and `args` and `results` are arrays of the counts and the types of that type, as for
   `wasmext_instance_call`. 0, or the code of a trap (a null funcref is WASM_RT_TRAP_NULL_REF; the instances stay usable). */
static inline int wasmext_instance_call_ref(wasmext_instance *i, const wasmext_funcref *f, const wasmext_val *args, uint32_t n_args, wasmext_val *results, uint32_t n_results) {
    const wasmext_ref_type *rt = NULL;
    int line, rc;
    wasmext_rlock *lock;
    long level;
    if (!i->instantiated) return WASMEXT_INST_NOT_INSTANTIATED;
    if (f == NULL || f->ref.func == NULL) return (int)WASM_RT_TRAP_NULL_REF;
    rc = wasmext_funcref_check_(i->store, f);
    if (rc != 0) return rc;
    if (f->ref.func_type == NULL) return WASMEXT_INST_UNDECLARED_TYPE;
    for (uint32_t k = 0; k < i->binding->n_ref_types && rt == NULL; k++) {
        const char *t = i->binding->ref_types[k].type();
        if (t != NULL && (t == f->ref.func_type || memcmp(t, f->ref.func_type, 32) == 0)) rt = &i->binding->ref_types[k];
    }
    if (rt == NULL) return WASMEXT_INST_UNDECLARED_TYPE;
    if (rt->sig.n_params != n_args || rt->sig.n_results != n_results) return WASMEXT_INST_BAD_ARGS;
    for (uint32_t k = 0; k < n_args; k++)
        if (args[k].type != rt->sig.params[k]) return WASMEXT_INST_BAD_ARGS;
    rc = wasmext_call_check_refs_(i->store, &rt->sig, args, results);
    if (rc != 0) return rc;
    line = wasmext_store_enter(i->store);
    if (line < 0) return (int)WASMEXT_TRAP_CLOSED;
    wasmext_thread_ready();
    lock = (wasmext_rlock *)wasmext_store_host_lock(i->store);
    level = lock != NULL ? wasmext_rlock_depth(lock) : 0;
    if (i->binding->call_begin != NULL) i->binding->call_begin(i->module);
    rc = rt->adapter(f->ref.module_instance, (void *)(void (*)(void))f->ref.func, args, results);
    if (lock != NULL) wasmext_rlock_release_to(lock, level); /* a trap left the unlocks of fusedwasi behind */
    if (rc == 0) rc = wasmext_call_fill_refs_(i->store, &rt->sig, results);
    wasmext_store_leave(i->store, line);
    wasmext_atomic_store(&i->status, rc);
    return rc;
}

/* A function of the host as an element of a table. The record starts with a slot of an import, so the trampoline that the binding makes for the type calls it as it calls an import: by
   the uniform shape, with a failure of the host a trap. `wasm_rt_funcref_t.module_instance` is the record, which is a member of the store under that pointer: the funcref passes the
   same checks as the one of an instance's function. */
typedef struct {
    wasmext_import_slot slot; /* first: the pointer to the record is the pointer to the slot */
    wasmext_store *store;
    void (*release)(void *user);
    int released;
} wasmext_host_func;

static inline void wasmext_host_func_close_(void *object) {
    wasmext_host_func *h = (wasmext_host_func *)object;
    if (!h->released) {
        h->released = 1;
        if (h->release != NULL) h->release(h->slot.user);
    }
}
static inline void wasmext_host_func_free_(void *object) {
    wasmext_host_func_close_(object);
    free(object);
}
static const wasmext_owner_ops wasmext_host_func_ops_ = {NULL, NULL, NULL, wasmext_host_func_close_};

/* Makes a function of the host (`fn`, one shape for every function: see wasmext_host_fn) of the type `params` -> `results` (bytes of the binary format) and gives it as an element of a table
   to put in this store (`out`). The type must be one that the module of `i` declares (its type section), else WASMEXT_INST_UNDECLARED_TYPE: the glue is made ahead of time, and a
   type that the module does not have has no trampoline. The store keeps the function until it is closed; then `release(user)` is called once (it may be NULL). The call may be made
   from any thread; `fn` is called as an import is, from inside a call of the module. */
static inline int wasmext_instance_host_funcref(wasmext_instance *i, const uint8_t *params, uint32_t n_params, const uint8_t *results, uint32_t n_results, wasmext_host_fn fn,
                                                void *user, void (*release)(void *user), wasmext_funcref *out) {
    const wasmext_ref_type *rt = NULL;
    wasmext_host_func *h;
    int rc;
    if (fn == NULL) return WASMEXT_INST_BAD_ARGS;
    if (!i->instantiated) return WASMEXT_INST_NOT_INSTANTIATED;
    if (wasmext_store_closed(i->store)) return (int)WASMEXT_TRAP_CLOSED;
    for (uint32_t k = 0; k < i->binding->n_ref_types && rt == NULL; k++) {
        const wasmext_ref_type *c = &i->binding->ref_types[k];
        if (c->trampoline != NULL && c->sig.n_params == n_params && c->sig.n_results == n_results && (n_params == 0 || memcmp(c->sig.params, params, n_params) == 0) &&
            (n_results == 0 || memcmp(c->sig.results, results, n_results) == 0))
            rt = c;
    }
    if (rt == NULL) return WASMEXT_INST_UNDECLARED_TYPE;
    h = (wasmext_host_func *)calloc(1, sizeof *h);
    if (h == NULL) return WASMEXT_INST_NOMEM;
    h->slot.host = fn;
    h->slot.user = user;
    h->slot.self = i;
    h->store = i->store;
    h->release = release;
    if (wasmext_store_adopt(i->store, h, wasmext_host_func_free_) != WASMEXT_STORE_OK) {
        free(h);
        return WASMEXT_INST_NOMEM;
    }
    rc = wasmext_store_register(i->store, h, h, &wasmext_host_func_ops_, &out->owner);
    if (rc != WASMEXT_STORE_OK) {
        wasmext_store_unadopt(i->store, h);
        free(h);
        return rc == WASMEXT_STORE_CLOSED ? (int)WASMEXT_TRAP_CLOSED : WASMEXT_INST_NOMEM;
    }
    memset(&out->ref, 0, sizeof out->ref);
    out->ref.func_type = rt->type();
    out->ref.func = (wasm_rt_function_ptr_t)rt->trampoline;
    out->ref.module_instance = h;
    out->store = i->store;
    return 0;
}

/* How the last call ended the WASI program of the module: WASMEXT_END_NONE, WASMEXT_END_EXIT (`*value` is the code of proc_exit) or WASMEXT_END_SIGNAL (the number of
   proc_raise). The call answered WASMEXT_TRAP_HOST. The end is what a call leaves: the next call forgets it, and the instance can be called again. */
static inline int wasmext_instance_wasi_end(const wasmext_instance *i, uint32_t *value) {
    uint32_t ignored;
    if (value == NULL) value = &ignored;
    *value = 0;
    return i->module != NULL && i->binding->wasi_end != NULL ? i->binding->wasi_end(i->module, value) : WASMEXT_END_NONE;
}

/* ---- memories ---- */

/* The bytes of an exported memory at this moment: valid until the module grows it (a `memory.grow` of the module, or `wasmext_instance_memory_grow`), or for good while it is pinned. */
typedef struct {
    uint8_t *base;
    uint64_t size;      /* bytes */
    uint64_t pages;
    uint64_t max_pages; /* what the memory may grow to (while pinned: what it has) */
    uint32_t page_size;
    int is64;
} wasmext_memory_view;

static inline wasm_rt_memory_t *wasmext_instance_memory_of_(const wasmext_instance *i, uint32_t index, int *rc) {
    const wasmext_descriptor *d = i->binding->descriptor;
    if (index >= d->n_exports || d->exports[index].kind != WASMEXT_DESC_MEMORY || i->binding->exports[index].address == NULL) { *rc = WASMEXT_INST_BAD_EXPORT; return NULL; }
    if (!i->instantiated) { *rc = WASMEXT_INST_NOT_INSTANTIATED; return NULL; }
    if (wasmext_store_closed(i->store)) { *rc = (int)WASMEXT_TRAP_CLOSED; return NULL; }
    *rc = 0;
    return (wasm_rt_memory_t *)i->binding->exports[index].address(i->module);
}

static inline int wasmext_instance_memory(wasmext_instance *i, uint32_t index, wasmext_memory_view *out) {
    int rc;
    wasm_rt_memory_t *m = wasmext_instance_memory_of_(i, index, &rc);
    if (m == NULL) return rc;
    out->base = m->data;
    out->size = m->size;
    out->pages = m->pages;
    out->max_pages = m->max_pages;
    out->page_size = m->page_size;
    out->is64 = m->is64;
    return 0;
}

/* Pins (pin != 0) or unpins an exported memory; pins count. While it is pinned, `memory.grow` answers -1 where the runtime would move the memory (a memory64, or no
   guard pages), so that the bytes stay where they are; the memory of a default 32-bit memory with guard pages never moves and pinning it does nothing. */
static inline int wasmext_instance_memory_pin(wasmext_instance *i, uint32_t index, int pin) {
    int rc;
    wasm_rt_memory_t *m = wasmext_instance_memory_of_(i, index, &rc);
    int moves;
    if (m == NULL) return rc;
#if WASM_RT_USE_MMAP
    moves = m->is64 || m->page_size != WASM_DEFAULT_PAGE_SIZE;
#else
    moves = 1;
#endif
    if (!moves) return 0;
    WASMEXT_LOCK(&i->pin_mutex);
    if (pin) {
        if (i->pins[index]++ == 0) {
            i->saved_max[index] = m->max_pages;
            m->max_pages = m->pages;
        }
    } else if (i->pins[index] > 0 && --i->pins[index] == 0) {
        m->max_pages = i->saved_max[index];
    }
    WASMEXT_UNLOCK(&i->pin_mutex);
    return 0;
}

/* Grows an exported memory by `delta` pages: the number of pages it had, or -1 when it cannot (its maximum, the memory, or a pin that would be broken by a move); a negative
   code of the API otherwise. The host asks it when no call of the module is growing the same memory. */
static inline int64_t wasmext_instance_memory_grow(wasmext_instance *i, uint32_t index, uint64_t delta) {
    int rc, line;
    uint64_t old;
    wasm_rt_memory_t *m = wasmext_instance_memory_of_(i, index, &rc);
    if (m == NULL) return rc;
    line = wasmext_store_enter(i->store);
    if (line < 0) return (int64_t)WASMEXT_TRAP_CLOSED;
    WASMEXT_LOCK(&i->pin_mutex);
    old = wasm_rt_grow_memory(m, delta);
    WASMEXT_UNLOCK(&i->pin_mutex);
    wasmext_store_leave(i->store, line);
    return old == (uint64_t)-1 ? -1 : (int64_t)old;
}

/* ---- globals ---- */

static inline int wasmext_instance_global_check_(const wasmext_instance *i, uint32_t index, void **address, const wasmext_global_desc **desc) {
    const wasmext_descriptor *d = i->binding->descriptor;
    if (index >= d->n_exports || d->exports[index].kind != WASMEXT_DESC_GLOBAL || i->binding->exports[index].address == NULL) return WASMEXT_INST_BAD_EXPORT;
    *desc = &d->globals[d->exports[index].index];
    if (!i->instantiated) return WASMEXT_INST_NOT_INSTANTIATED;
    if (wasmext_store_closed(i->store)) return (int)WASMEXT_TRAP_CLOSED;
    *address = i->binding->exports[index].address(i->module);
    return 0;
}

/* Reads an exported global into `out` (with its type). A global of funcref is written where the caller points `out->as.ref` (at a `wasmext_funcref`, NULL is WASMEXT_INST_BAD_ARGS); a
   global of externref gives its reference (NULL when it is null). */
static inline int wasmext_instance_global_get(wasmext_instance *i, uint32_t index, wasmext_val *out) {
    void *p;
    const wasmext_global_desc *g;
    int rc = wasmext_instance_global_check_(i, index, &p, &g);
    if (rc != 0) return rc;
    if (g->type == 0x70) {
        wasmext_funcref *f = (wasmext_funcref *)out->as.ref;
        if (f == NULL) return WASMEXT_INST_BAD_ARGS;
        f->ref = *(const wasm_rt_funcref_t *)p;
        f->store = i->store;
        f->owner = 0;
        if (f->ref.func != NULL && wasmext_store_find(i->store, f->ref.module_instance, &f->owner) != WASMEXT_STORE_OK) return WASMEXT_TAB_STALE;
        memset(out, 0, sizeof *out);
        out->type = 0x70;
        out->as.ref = f;
        return 0;
    }
    memset(out, 0, sizeof *out);
    out->type = g->type;
    switch (g->type) {
        case 0x6F: out->as.ref = *(void **)p; break;
        case 0x7F: out->as.i32 = (int32_t)*(uint32_t *)p; break;
        case 0x7E: out->as.i64 = (int64_t)*(uint64_t *)p; break;
        case 0x7D: out->as.f32 = *(float *)p; break;
        case 0x7C: out->as.f64 = *(double *)p; break;
        default: memcpy(out->as.v128, p, 16); break;
    }
    return 0;
}

/* Sets a mutable exported global; the value must have its type. */
static inline int wasmext_instance_global_set(wasmext_instance *i, uint32_t index, const wasmext_val *value) {
    void *p;
    const wasmext_global_desc *g;
    int rc = wasmext_instance_global_check_(i, index, &p, &g);
    if (rc != 0) return rc;
    if (!g->is_mutable) return WASMEXT_INST_IMMUTABLE;
    if (value->type != g->type) return WASMEXT_INST_BAD_ARGS;
    switch (g->type) {
        case 0x7F: *(uint32_t *)p = (uint32_t)value->as.i32; break;
        case 0x7E: *(uint64_t *)p = (uint64_t)value->as.i64; break;
        case 0x7D: *(float *)p = value->as.f32; break;
        case 0x7C: *(double *)p = value->as.f64; break;
        case 0x70: { /* a funcref of the store, or NULL */
            const wasmext_funcref *f = (const wasmext_funcref *)value->as.ref;
            rc = wasmext_funcref_check_(i->store, f);
            if (rc != 0) return rc;
            if (f == NULL) memset(p, 0, sizeof(wasm_rt_funcref_t));
            else memcpy(p, &f->ref, sizeof(wasm_rt_funcref_t));
            break;
        }
        case 0x6F: /* a reference of the store, or NULL */
            rc = wasmext_extern_check_(i->store, value->as.ref);
            if (rc != 0) return rc;
            *(void **)p = value->as.ref;
            break;
        default: memcpy(p, value->as.v128, 16); break;
    }
    return 0;
}

/* The answer of the last call of the instance: 0, or the code of the trap. */
static inline int wasmext_instance_status(const wasmext_instance *i) { return (int)wasmext_atomic_load((wasmext_counter *)&i->status); }

/* Frees the wrapper of an instance that the store does not hold: one that was never instantiated, or whose instantiation failed. An instantiated instance is a member of the
   store until the close (as in Wasmtime) and the store frees it when it is freed: WASMEXT_STORE_BUSY, nothing done. */
static inline int wasmext_instance_free(wasmext_instance *i) {
    if (i == NULL) return WASMEXT_STORE_OK;
    if (i->owner != 0) return WASMEXT_STORE_BUSY;
    wasmext_store_unadopt(i->store, i);
    wasmext_instance_wrapper_free_(i);
    return WASMEXT_STORE_OK;
}

#endif
