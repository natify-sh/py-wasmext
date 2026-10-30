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
} artifact_api;

/* in artifact_store_only.c: the file that includes only wasmext_store.h */
wasmext_store *artifact_so_new(void);
int artifact_so_attach(wasmext_store *s, char *why, size_t cap);

#endif
