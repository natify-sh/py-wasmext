/* Tables of `funcref`: a table of the store, and the operations on it and on a table that an instance exports. No Python. See docs/step5_tables.md.

   A table is a member of a store (wasmext_store.h), as in WebAssembly and in Wasmtime: it lives until the store is closed. An element is a `wasmext_funcref` (wasmext_instance.h): a
   function of an instance of the SAME store; a function of another store is refused (WASMEXT_TAB_WRONG_STORE), and so is a value that was not made by this API (the pointer of its
   instance must be a member of the store, and the handle in the value must be that member's). The type of an element is not checked when it is put in: `call_indirect` of the
   module that calls it compares it, as in WebAssembly.

   Every operation enters the store (a closed store answers WASMEXT_TRAP_CLOSED, and `close` refuses while an operation is in flight) and takes the lock of the table, so the host can
   call them from any thread. A write to the table by WebAssembly code (`table.set`, `table.grow`, an `elem` segment) is not synchronised with the host's: a host that grows or sets a
   table does it when no call of the store is running, as it does for a memory (the threads proposal is step 11). */
#ifndef WASMEXT_TABLE_H
#define WASMEXT_TABLE_H

#include "wasmext_instance.h"

/* A table that no module owns, made by the host. The record of it (wasmext_tab_record) is what an import of a module is given. */
typedef struct wasmext_tab_s_ {
    wasm_rt_funcref_table_t table;
    wasmext_store *store;
    wasmext_owner owner;
    WASMEXT_MUTEX_T mutex;
    int live; /* 0 once the store is closed: the wrapper stays until the store is freed */
} wasmext_tab;

static inline void wasmext_tab_close_(void *object) {
    wasmext_tab *t = (wasmext_tab *)object;
    if (t->live) {
        wasmext_table_free(&t->table);
        t->live = 0;
    }
}
static inline void wasmext_tab_wrapper_free_(void *object) {
    wasmext_tab *t = (wasmext_tab *)object;
    wasmext_tab_close_(t);
    WASMEXT_MUTEX_DESTROY(&t->mutex);
    free(t);
}
static const wasmext_owner_ops wasmext_tab_ops_ = {NULL, NULL, NULL, wasmext_tab_close_};

/* Makes a table of `initial` elements (null) in `store`; `maximum` is WASMEXT_TABLE_NO_MAXIMUM for none. NULL with `*error` (an errno: EINVAL, EBADF for a closed store, ENOMEM) when it
   cannot be made. */
static inline wasmext_tab *wasmext_tab_new(wasmext_store *store, uint32_t initial, uint32_t maximum, int *error) {
    int ignored;
    wasmext_tab *t;
    if (error == NULL) error = &ignored;
    if (store == NULL || (maximum != WASMEXT_TABLE_NO_MAXIMUM && initial > maximum)) { *error = EINVAL; return NULL; }
    if (wasmext_store_closed(store)) { *error = EBADF; return NULL; }
    t = (wasmext_tab *)calloc(1, sizeof *t);
    if (t == NULL) { *error = ENOMEM; return NULL; }
    if (wasmext_table_new(&t->table, initial, maximum) != 0) { free(t); *error = ENOMEM; return NULL; }
    WASMEXT_MUTEX_INIT(&t->mutex);
    t->store = store;
    t->live = 1;
    if (wasmext_store_adopt(store, t, wasmext_tab_wrapper_free_) != WASMEXT_STORE_OK) {
        wasmext_tab_wrapper_free_(t);
        *error = ENOMEM;
        return NULL;
    }
    if (wasmext_store_register(store, &t->table, t, &wasmext_tab_ops_, &t->owner) != WASMEXT_STORE_OK) {
        wasmext_store_unadopt(store, t);
        wasmext_tab_wrapper_free_(t);
        *error = wasmext_store_closed(store) ? EBADF : ENOMEM;
        return NULL;
    }
    *error = 0;
    return t;
}

/* ---- the operations, on any `wasm_rt_funcref_table_t` of a store ---- */

static inline int wasmext_tab_get_(wasmext_store *s, WASMEXT_MUTEX_T *mutex, wasm_rt_funcref_table_t *t, uint32_t index, wasmext_funcref *out) {
    int line, rc = 0;
    wasmext_owner owner;
    line = wasmext_store_enter(s);
    if (line < 0) return (int)WASMEXT_TRAP_CLOSED;
    WASMEXT_LOCK(mutex);
    if (index >= t->size) rc = WASMEXT_TAB_BOUNDS;
    else {
        out->ref = t->data[index];
        out->store = s;
        out->owner = 0;
        if (out->ref.func != NULL) {
            if (wasmext_store_find(s, out->ref.module_instance, &owner) != WASMEXT_STORE_OK) rc = WASMEXT_TAB_STALE;
            else out->owner = owner;
        }
    }
    WASMEXT_UNLOCK(mutex);
    wasmext_store_leave(s, line);
    return rc;
}

/* a null funcref (`ref.func` is NULL) empties the slot */
static inline int wasmext_tab_set_(wasmext_store *s, WASMEXT_MUTEX_T *mutex, wasm_rt_funcref_table_t *t, uint32_t index, const wasmext_funcref *f) {
    int line, rc;
    rc = wasmext_funcref_check_(s, f);
    if (rc != 0) return rc;
    line = wasmext_store_enter(s);
    if (line < 0) return (int)WASMEXT_TRAP_CLOSED;
    WASMEXT_LOCK(mutex);
    if (index >= t->size) rc = WASMEXT_TAB_BOUNDS;
    else if (f == NULL || f->ref.func == NULL) memset(&t->data[index], 0, sizeof t->data[index]);
    else t->data[index] = f->ref;
    WASMEXT_UNLOCK(mutex);
    wasmext_store_leave(s, line);
    return rc;
}

/* the new elements are null; `*previous` is the size before */
static inline int wasmext_tab_grow_(wasmext_store *s, WASMEXT_MUTEX_T *mutex, wasm_rt_funcref_table_t *t, uint32_t delta, uint32_t *previous) {
    int line, rc = 0;
    int64_t old;
    line = wasmext_store_enter(s);
    if (line < 0) return (int)WASMEXT_TRAP_CLOSED;
    WASMEXT_LOCK(mutex);
    old = wasmext_table_grow(t, delta);
    if (old < 0) rc = WASMEXT_TAB_FULL;
    else if (previous != NULL) *previous = (uint32_t)old;
    WASMEXT_UNLOCK(mutex);
    wasmext_store_leave(s, line);
    return rc;
}

static inline int wasmext_tab_size_(wasmext_store *s, WASMEXT_MUTEX_T *mutex, const wasm_rt_funcref_table_t *t, uint32_t *size, uint32_t *maximum) {
    int line = wasmext_store_enter(s);
    if (line < 0) return (int)WASMEXT_TRAP_CLOSED;
    WASMEXT_LOCK(mutex);
    if (size != NULL) *size = t->size;
    if (maximum != NULL) *maximum = t->max_size;
    WASMEXT_UNLOCK(mutex);
    wasmext_store_leave(s, line);
    return 0;
}

/* ---- a table of the host ---- */

/* The element `index` (empty when `out->ref.func` is NULL). */
static inline int wasmext_tab_get(wasmext_tab *t, uint32_t index, wasmext_funcref *out) { return wasmext_tab_get_(t->store, &t->mutex, &t->table, index, out); }
/* Puts a function in the slot `index`; NULL, or a null funcref, empties it. */
static inline int wasmext_tab_set(wasmext_tab *t, uint32_t index, const wasmext_funcref *f) { return wasmext_tab_set_(t->store, &t->mutex, &t->table, index, f); }
/* Grows by `delta` (null elements): WASMEXT_TAB_FULL when it cannot. */
static inline int wasmext_tab_grow(wasmext_tab *t, uint32_t delta, uint32_t *previous) { return wasmext_tab_grow_(t->store, &t->mutex, &t->table, delta, previous); }
/* The size, and the maximum (WASMEXT_TABLE_NO_MAXIMUM for none); either may be NULL. */
static inline int wasmext_tab_size(wasmext_tab *t, uint32_t *size, uint32_t *maximum) { return wasmext_tab_size_(t->store, &t->mutex, &t->table, size, maximum); }

/* The record of the table, for an import of a module (wasmext_instance_bind_export); valid until the store is closed. `owner` is what the host keeps alive (it is passed on). */
static inline int wasmext_tab_record(wasmext_tab *t, void *owner, wasmext_export *out) {
    if (!t->live || wasmext_store_closed(t->store)) return (int)WASMEXT_TRAP_CLOSED;
    wasmext_table_export(out, &t->table, owner);
    out->store = t->store;
    return 0;
}

/* ---- a table that an instance exports (the export `index` of its descriptor) ---- */

static inline int wasmext_instance_table_of_(wasmext_instance *i, uint32_t index, wasm_rt_funcref_table_t **t) {
    const wasmext_descriptor *d = i->binding->descriptor;
    const wasmext_table_desc *desc;
    if (index >= d->n_exports || d->exports[index].kind != WASMEXT_DESC_TABLE || i->binding->exports[index].address == NULL) return WASMEXT_INST_BAD_EXPORT;
    desc = &d->tables[d->exports[index].index];
    if (desc->elem != 0x70 || desc->limits.is64 || desc->limits.shared) return WASMEXT_INST_UNSUPPORTED;
    if (!i->instantiated) return WASMEXT_INST_NOT_INSTANTIATED;
    if (wasmext_store_closed(i->store)) return (int)WASMEXT_TRAP_CLOSED;
    *t = (wasm_rt_funcref_table_t *)i->binding->exports[index].address(i->module);
    return 0;
}

static inline int wasmext_instance_table_get(wasmext_instance *i, uint32_t index, uint32_t element, wasmext_funcref *out) {
    wasm_rt_funcref_table_t *t;
    int rc = wasmext_instance_table_of_(i, index, &t);
    return rc != 0 ? rc : wasmext_tab_get_(i->store, &i->pin_mutex, t, element, out);
}
static inline int wasmext_instance_table_set(wasmext_instance *i, uint32_t index, uint32_t element, const wasmext_funcref *f) {
    wasm_rt_funcref_table_t *t;
    int rc = wasmext_instance_table_of_(i, index, &t);
    return rc != 0 ? rc : wasmext_tab_set_(i->store, &i->pin_mutex, t, element, f);
}
static inline int wasmext_instance_table_grow(wasmext_instance *i, uint32_t index, uint32_t delta, uint32_t *previous) {
    wasm_rt_funcref_table_t *t;
    int rc = wasmext_instance_table_of_(i, index, &t);
    return rc != 0 ? rc : wasmext_tab_grow_(i->store, &i->pin_mutex, t, delta, previous);
}
static inline int wasmext_instance_table_size(wasmext_instance *i, uint32_t index, uint32_t *size, uint32_t *maximum) {
    wasm_rt_funcref_table_t *t;
    int rc = wasmext_instance_table_of_(i, index, &t);
    return rc != 0 ? rc : wasmext_tab_size_(i->store, &i->pin_mutex, t, size, maximum);
}

#endif
