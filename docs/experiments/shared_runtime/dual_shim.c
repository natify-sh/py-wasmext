/* The runtime of a DUAL module: each function the generated code calls goes to the master's table if the module attached to one, and to its own runtime (own_*) if not. */
#define RT_DUAL 1
#define RT_SHIM 1
#include "wasm-rt.h"
#include "wasm-rt-exceptions.h"
#include <Python.h>
#include "shared_rt.h"

const rt_vtable *rt_M;
#define M rt_M

void wasm_rt_init(void) { if (M) M->thread_ready(); else own_wasm_rt_init(); }
bool wasm_rt_is_initialized(void) { return M ? M->is_initialized() : own_wasm_rt_is_initialized(); }
void wasm_rt_init_thread(void) { if (M) M->thread_ready(); else own_wasm_rt_init_thread(); }
void wasm_rt_free_thread(void) { if (!M) own_wasm_rt_free_thread(); /* a slave never owns a thread */ }
WASM_RT_NO_RETURN void wasm_rt_trap(wasm_rt_trap_t code) {
    if (M) M->trap(code); else own_wasm_rt_trap(code);
    __builtin_unreachable();
}
const char *wasm_rt_strerror(wasm_rt_trap_t t) { return M ? M->strerror_(t) : own_wasm_rt_strerror(t); }
void wasm_rt_allocate_memory(wasm_rt_memory_t *m, uint64_t i, uint64_t x, bool is64, uint32_t ps) { if (M) M->allocate_memory(m, i, x, is64, ps); else own_wasm_rt_allocate_memory(m, i, x, is64, ps); }
uint64_t wasm_rt_grow_memory(wasm_rt_memory_t *m, uint64_t p) { return M ? M->grow_memory(m, p) : own_wasm_rt_grow_memory(m, p); }
void wasm_rt_free_memory(wasm_rt_memory_t *m) { if (M) M->free_memory(m); else own_wasm_rt_free_memory(m); }
void wasm_rt_allocate_funcref_table(wasm_rt_funcref_table_t *t, uint32_t n, uint32_t x) { if (M) M->allocate_funcref_table(t, n, x); else own_wasm_rt_allocate_funcref_table(t, n, x); }
uint32_t wasm_rt_grow_funcref_table(wasm_rt_funcref_table_t *t, uint32_t d, wasm_rt_funcref_t init) { return M ? M->grow_funcref_table(t, d, init) : own_wasm_rt_grow_funcref_table(t, d, init); }
void wasm_rt_free_funcref_table(wasm_rt_funcref_table_t *t) { if (M) M->free_funcref_table(t); else own_wasm_rt_free_funcref_table(t); }
void wasm_rt_allocate_externref_table(wasm_rt_externref_table_t *t, uint32_t n, uint32_t x) { if (M) M->allocate_externref_table(t, n, x); else own_wasm_rt_allocate_externref_table(t, n, x); }
uint32_t wasm_rt_grow_externref_table(wasm_rt_externref_table_t *t, uint32_t d, wasm_rt_externref_t init) { return M ? M->grow_externref_table(t, d, init) : own_wasm_rt_grow_externref_table(t, d, init); }
void wasm_rt_free_externref_table(wasm_rt_externref_table_t *t) { if (M) M->free_externref_table(t); else own_wasm_rt_free_externref_table(t); }
void wasm_rt_set_unwind_target(WASM_RT_UNWIND_TARGET *t) { if (M) M->set_unwind_target(t); else own_wasm_rt_set_unwind_target(t); }
WASM_RT_UNWIND_TARGET *wasm_rt_get_unwind_target(void) { return M ? M->get_unwind_target() : own_wasm_rt_get_unwind_target(); }
void wasm_rt_load_exception(const wasm_rt_tag_t tag, uint32_t size, const void *v) { if (M) M->load_exception(tag, size, v); else own_wasm_rt_load_exception(tag, size, v); }
WASM_RT_NO_RETURN void wasm_rt_throw(void) {
    if (M) M->throw_(); else own_wasm_rt_throw();
    __builtin_unreachable();
}
wasm_rt_tag_t wasm_rt_exception_tag(void) { return M ? M->exception_tag() : own_wasm_rt_exception_tag(); }
uint32_t wasm_rt_exception_size(void) { return M ? M->exception_size() : own_wasm_rt_exception_size(); }
void *wasm_rt_exception(void) { return M ? M->exception() : own_wasm_rt_exception(); }
