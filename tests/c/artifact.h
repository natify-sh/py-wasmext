/* What an artifact of tests/test_artifacts.py gives the host: one function that returns this table. The artifact is a shared library (hidden visibility) with its own copy of the
   core and of the runtime of wasm2c; the host calls the core only through the tables of the two copies. */
#ifndef ARTIFACT_H
#define ARTIFACT_H

#include "wasmext_instance.h" /* not wasmext_table.h: the host links no runtime of wasm2c, and the table code would need it */

struct wasmext_tab_s_;

typedef struct {
    const void *id;                      /* WASMEXT_ARTIFACT of this copy */
    const void *(*trap_address)(void);   /* the address of wasm_rt_trap in this copy: two copies of the runtime have two */
    wasmext_store *(*store_new)(void);
    int (*store_attach)(wasmext_store *s, char *why, size_t cap);
    int (*store_close)(wasmext_store *s);
    int (*store_free)(wasmext_store *s);
    int (*store_own)(wasmext_store *s);  /* the store owns an object whose release (a function of this copy) counts */
    long (*releases)(void);              /* how many releases of this copy ran */
    void (*store_error)(wasmext_store *s, char *buffer, size_t cap);
    wasmext_instance *(*instance_new)(wasmext_store *s, const char *module, int *error);
    int (*instantiate)(wasmext_instance *i);
    int (*call)(wasmext_instance *i, const char *name, const wasmext_val *args, uint32_t n_args, wasmext_val *results, uint32_t n_results);
    int (*export_record)(wasmext_instance *i, const char *name, int kind, wasmext_export *out);
    int (*bind)(wasmext_instance *i, const char *module, const char *name, const wasmext_export *record);
    int (*funcref)(wasmext_instance *i, const char *name, wasmext_funcref *out);
    int (*table_set)(wasmext_instance *i, const char *name, uint32_t index, const wasmext_funcref *f);
    int (*global_set_funcref)(wasmext_instance *i, const char *name, const wasmext_funcref *f);
    struct wasmext_tab_s_ *(*tab_new)(wasmext_store *s, int *error);
    int (*tab_set)(struct wasmext_tab_s_ *t, uint32_t index, const wasmext_funcref *f);
    int (*tab_get)(struct wasmext_tab_s_ *t, uint32_t index, wasmext_funcref *out);
    void (*thread_free)(void);           /* at the end of a thread that called into this copy */
    int (*call_ref)(wasmext_instance *i, const wasmext_funcref *f, wasmext_val *results, uint32_t n_results); /* a function of the type () -> i32 */
    int (*bind_host)(wasmext_instance *i, const char *module, const char *name, wasmext_host_fn fn, void *user);
    int (*bind_global_funcref)(wasmext_instance *i, const char *module, const char *name, const wasmext_funcref *f);
    int (*host_funcref)(wasmext_instance *i, wasmext_host_fn fn, wasmext_funcref *out); /* a host function of the type () -> i32 as an element of a table */
    int (*extern_new)(wasmext_store *s);  /* an extern with no value */
    int (*store_misc)(wasmext_store *s, int which); /* 0: adopt, 1: register, 2: set_host, each with an object of this copy */
    wasmext_store *(*so_new)(void);      /* a store made, and attached to, by a file of this copy that includes wasmext_store.h alone */
    int (*so_attach)(wasmext_store *s, char *why, size_t cap);
    wasmext_extern *(*extern_make)(wasmext_store *s, void *user); /* an externref of the store holding `user`, made by this copy (NULL on failure) */
    int (*tag_new)(wasmext_store *s, const uint8_t *types, uint32_t n, wasmext_export *out); /* a tag of the host, made by this copy */
    void *volatile *(*tag_cell)(wasmext_instance *i); /* the global that the (first) tag import of the instance is read from: its address does not need the instance (8a-3) */
    uint32_t host_layout;                /* WASMEXT_HOST_LAYOUT as this copy was built */
    /* 8b-1: the runtime of the store */
    const void *(*runtime_id)(void);     /* the address of the table of the runtime of this copy (wasmext_runtime_own_) */
    const void *(*set_tls_rt)(const void *rt); /* sets the active runtime of the calling thread in this copy (what the forwarders of this copy send to); answers the one it was */
    void (*exception_load)(const void *tag, uint32_t size, const void *values); /* this copy's wasm_rt_load_exception */
    uint32_t (*exception_size)(void);    /* this copy's wasm_rt_exception_size */
    void (*fix_seed)(uint32_t seed);     /* fixes the start of the serials of this copy's runtime */
    int (*register_object)(wasmext_store *s, wasmext_owner *out); /* registers a new object of this copy in the store: its handle */
    /* 8b-2: what this copy keeps for the calling thread: the active runtime (`tls.rt`, NULL outside a call), the innermost entry (`tls.top`, NULL outside a call) and the unwind target as this copy's
       wasm_rt_get_unwind_target answers it (the one of the active runtime) */
    void (*state)(const void **rt, const void **top, const void **unwind);
    wasmext_tab *(*tab_make)(wasmext_store *s, int elem, int *error); /* a host table of 2 elements, funcref (0x70) or externref (0x6F) */
    int (*tab_grow)(wasmext_tab *t, uint32_t delta, uint32_t *previous);
    int64_t (*mem_grow)(wasmext_instance *i, const char *name, uint64_t delta); /* wasmext_instance_memory_grow of the exported memory `name` */
    int (*exception_of)(wasmext_instance *i, const void **tag); /* wasmext_instance_exception: its answer, and the tag of the active exception */
} artifact_api;

/* in artifact_store_only.c: the file that includes only wasmext_store.h */
wasmext_store *artifact_so_new(void);
int artifact_so_attach(wasmext_store *s, char *why, size_t cap);

#endif
