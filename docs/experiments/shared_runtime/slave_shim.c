/* The runtime of a slave module: nothing of its own. Every function that the generated code (and the glue of wasmext) calls goes to the table of the master. */
#define RT_SLAVE 1
#define RT_SHIM 1
#include "wasm-rt.h"
#include "wasm-rt-exceptions.h"
#include <Python.h>
#include "shared_rt.h"

const rt_vtable *rt_M;
#define M rt_M

void wasm_rt_init(void) { M->thread_ready(); }  /* the master did the runtime (handler of signals, ...); this thread has to be ready */
bool wasm_rt_is_initialized(void) { return M->is_initialized(); }
void wasm_rt_init_thread(void) { M->thread_ready(); }
void wasm_rt_free_thread(void) { /* the master gives a thread back; a slave never owns one */ }
WASM_RT_NO_RETURN void wasm_rt_trap(wasm_rt_trap_t code) {
    M->trap(code);
    __builtin_unreachable();
}
const char *wasm_rt_strerror(wasm_rt_trap_t trap) { return M->strerror_(trap); }
void wasm_rt_allocate_memory(wasm_rt_memory_t *m, uint64_t i, uint64_t x, bool is64, uint32_t ps) { M->allocate_memory(m, i, x, is64, ps); }
uint64_t wasm_rt_grow_memory(wasm_rt_memory_t *m, uint64_t pages) { return M->grow_memory(m, pages); }
void wasm_rt_free_memory(wasm_rt_memory_t *m) { M->free_memory(m); }
void wasm_rt_allocate_funcref_table(wasm_rt_funcref_table_t *t, uint32_t n, uint32_t x) { M->allocate_funcref_table(t, n, x); }
uint32_t wasm_rt_grow_funcref_table(wasm_rt_funcref_table_t *t, uint32_t d, wasm_rt_funcref_t init) { return M->grow_funcref_table(t, d, init); }
void wasm_rt_free_funcref_table(wasm_rt_funcref_table_t *t) { M->free_funcref_table(t); }
void wasm_rt_allocate_externref_table(wasm_rt_externref_table_t *t, uint32_t n, uint32_t x) { M->allocate_externref_table(t, n, x); }
uint32_t wasm_rt_grow_externref_table(wasm_rt_externref_table_t *t, uint32_t d, wasm_rt_externref_t init) { return M->grow_externref_table(t, d, init); }
void wasm_rt_free_externref_table(wasm_rt_externref_table_t *t) { M->free_externref_table(t); }
void wasm_rt_set_unwind_target(WASM_RT_UNWIND_TARGET *t) { M->set_unwind_target(t); }
WASM_RT_UNWIND_TARGET *wasm_rt_get_unwind_target(void) { return M->get_unwind_target(); }
void wasm_rt_load_exception(const wasm_rt_tag_t tag, uint32_t size, const void *values) { M->load_exception(tag, size, values); }
WASM_RT_NO_RETURN void wasm_rt_throw(void) {
    M->throw_();
    __builtin_unreachable();
}
wasm_rt_tag_t wasm_rt_exception_tag(void) { return M->exception_tag(); }
uint32_t wasm_rt_exception_size(void) { return M->exception_size(); }
void *wasm_rt_exception(void) { return M->exception(); }
