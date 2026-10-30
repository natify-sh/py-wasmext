/* PROTOTYPE: the "one place" that owns the store code: a separate shared library, built -fPIC -fvisibility=hidden. The program gets the table from proto_get()
   and calls through it, so the compiler can neither inline nor devirtualise. The functions are the unchanged inline ones of the product. */
#include "proto_ops.h" /* no PROTO_B / PROTO_C here: the real inline functions */
#define HIDDEN __attribute__((visibility("hidden"), noinline))
HIDDEN static int e_(wasmext_store *s) { return wasmext_store_enter(s); }
HIDDEN static void l_(wasmext_store *s, int line) { wasmext_store_leave(s, line); }
HIDDEN static void *h_(wasmext_store *s) { return wasmext_store_host_lock(s); }
HIDDEN static int c_(void *i, uint32_t index, const void *a, uint32_t na, void *r, uint32_t nr) {
    return wasmext_instance_call((wasmext_instance *)i, index, (const wasmext_val *)a, na, (wasmext_val *)r, nr);
}
static const proto_ops table_ = {e_, l_, h_, c_};
__attribute__((visibility("default"))) const proto_ops *proto_get(void) { return &table_; }
