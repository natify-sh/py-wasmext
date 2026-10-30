/* PROTOTYPE (not product code). Included FIRST by every C file of the program. A: nothing changes. PROTO_B: wasmext_store_enter / _leave / _host_lock become
   indirect calls through proto_tab (functions of store_lib.c, a separate shared library). PROTO_C: wasmext_instance_call is one indirect call. The renaming
   trick: the original inline functions are still defined (under another name), the names the headers call afterwards are the wrappers. */
#ifndef PROTO_OPS_H
#define PROTO_OPS_H
#ifdef PROTO_B
#define wasmext_store_enter wasmext_store_enter_orig_
#define wasmext_store_leave wasmext_store_leave_orig_
#define wasmext_store_host_lock wasmext_store_host_lock_orig_
#endif
#include "wasmext_store.h"
#ifdef PROTO_B
#undef wasmext_store_enter
#undef wasmext_store_leave
#undef wasmext_store_host_lock
#endif
typedef struct wasmext_instance wasmext_instance_fwd_;
typedef struct proto_ops {
    int (*enter)(wasmext_store *);
    void (*leave)(wasmext_store *, int);
    void *(*host_lock)(wasmext_store *);
    int (*call)(void *i, uint32_t index, const void *args, uint32_t n_args, void *results, uint32_t n_results);
} proto_ops;
extern const proto_ops *proto_tab; /* set once from proto_get() */
const proto_ops *proto_get(void);
#ifdef PROTO_B
static inline int wasmext_store_enter(wasmext_store *s) { return proto_tab->enter(s); }
static inline void wasmext_store_leave(wasmext_store *s, int line) { proto_tab->leave(s, line); }
static inline void *wasmext_store_host_lock(wasmext_store *s) { return proto_tab->host_lock(s); }
#endif
#ifdef PROTO_C
#define wasmext_instance_call wasmext_instance_call_orig_
#endif
#include "wasmext_instance.h"
#ifdef PROTO_C
#undef wasmext_instance_call
static inline int wasmext_instance_call(wasmext_instance *i, uint32_t index, const wasmext_val *args, uint32_t n_args, wasmext_val *results, uint32_t n_results) {
    return proto_tab->call(i, index, args, n_args, results, n_results);
}
#endif
#endif
