/* The runtime of a store (S0008, step 8b; D40, D42, D45): the table of the functions of the wasm2c runtime that generated code or the core can call, and the forwarders that send
   the calls to it.

   Every artifact has a full copy of the wasm2c runtime. In a build of the core the wrappers of the runtime (`_RUNTIME_WRAPPERS` in _natify.py) rename the functions of that copy to
   `wasmext_own_wasm_rt_*` and define the real `wasm_rt_*` names as forwarders (the second inclusion of this file, below): a forwarder calls the function of the table `tls.rt` when
   it is set, and the function of the copy itself when it is NULL. `tls` is one thread-local record for each copy. Nothing sets `tls.rt` yet (8b-2 does, at the entry of a call), so a
   copy still runs on its own functions.

   The table `wasmext_runtime_own_` is the runtime of the copy: one for each artifact, hidden, defined by the file that defines WASMEXT_DEFINE_THREAD_STATE (as the identity of the artifact
   is; the address of a `static const` of a header is not one object). Its address is the identity of the runtime. A store made by the copy points at it (`head.rt`). Fields are only added at the end.

   Built only with WASMEXT_STORE_RUNTIME, which every builder of the core defines (`core_build_macros` in _natify.py). The old layer 3 (_gen.py, _shared.py, _exe.py) does not, and its wrappers
   stay as they were. */
#ifndef WASMEXT_RUNTIME_H
#define WASMEXT_RUNTIME_H

#ifndef WASMEXT_STORE_RUNTIME
#error "wasmext: the core is built with -DWASMEXT_STORE_RUNTIME (core_build_macros() of _natify.py gives it): the runtime functions of wasm2c are renamed wasmext_own_* and forwarded to the runtime of the store (S0008, D42)"
#endif

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include "wasm-rt.h"
#include "wasm-rt-exceptions.h"
#include "wasmext_store.h"

#define WASMEXT_RUNTIME_VERSION 1u

/* `flags` of the table: the mode of the stack check of the build. `attach` refuses a store whose flags differ from the copy's: a copy that counts the depth cannot share a stack with one that
   compares the frame with a limit. (In 8b-1 the flags only say it; the entry that depends on the mode is 8b-2.) */
#ifdef WASMEXT_STACK_LIMIT
#define WASMEXT_RT_FLAG_LIMIT_ 1u /* the frame is compared with a limit in each function */
#else
#define WASMEXT_RT_FLAG_LIMIT_ 0u
#endif
#ifdef WASMEXT_CHAIN
#define WASMEXT_RT_FLAG_CHAIN_ 2u /* the runtime installs no handler of signals of its own: a link of a chain does */
#else
#define WASMEXT_RT_FLAG_CHAIN_ 0u
#endif
#if WASM_RT_STACK_DEPTH_COUNT
#define WASMEXT_RT_FLAG_DEPTH_ 4u /* a counter of the depth of the calls */
#else
#define WASMEXT_RT_FLAG_DEPTH_ 0u
#endif
#if WASM_RT_STACK_EXHAUSTION_HANDLER
#define WASMEXT_RT_FLAG_HANDLER_ 8u /* a handler of the guard page on an alternate stack */
#else
#define WASMEXT_RT_FLAG_HANDLER_ 0u
#endif
#define WASMEXT_RT_FLAGS (WASMEXT_RT_FLAG_LIMIT_ | WASMEXT_RT_FLAG_CHAIN_ | WASMEXT_RT_FLAG_DEPTH_ | WASMEXT_RT_FLAG_HANDLER_)

/* A shared memory exists in wasm2c only where the compiler has C11 (WASM_RT_C11_AVAILABLE); the fields are there in every build, the functions behind them are not. */
#ifdef WASM_RT_C11_AVAILABLE
typedef wasm_rt_shared_memory_t wasmext_shared_memory_t_;
#else
typedef struct { int unused_; } wasmext_shared_memory_t_;
#endif

/* The functions of the runtime of wasm2c (1.0.42) that generated code or the core can call: 23. `wasm_rt_init`, `wasm_rt_free`, `wasm_rt_init_thread`, `wasm_rt_free_thread` (set-up of a thread:
   D44, 8b-3b), `wasm_rt_is_initialized` and `wasm_rt_strerror` are not in it. A feature added later adds its functions here in the same step (D-6). */
typedef struct {
    wasmext_runtime_head head; /* first */
    void (*trap)(wasm_rt_trap_t code);
    void (*load_exception)(wasm_rt_tag_t tag, uint32_t size, const void *values);
    void (*throw_exception)(void);
    WASM_RT_UNWIND_TARGET *(*get_unwind_target)(void);
    void (*set_unwind_target)(WASM_RT_UNWIND_TARGET *target);
    wasm_rt_tag_t (*exception_tag)(void);
    uint32_t (*exception_size)(void);
    void *(*exception_data)(void);
    void (*allocate_memory)(wasm_rt_memory_t *memory, uint64_t initial_pages, uint64_t max_pages, bool is64, uint32_t page_size);
    uint64_t (*grow_memory)(wasm_rt_memory_t *memory, uint64_t pages);
    void (*free_memory)(wasm_rt_memory_t *memory);
    void (*allocate_memory_shared)(wasmext_shared_memory_t_ *memory, uint64_t initial_pages, uint64_t max_pages, bool is64, uint32_t page_size);
    uint64_t (*grow_memory_shared)(wasmext_shared_memory_t_ *memory, uint64_t pages);
    void (*free_memory_shared)(wasmext_shared_memory_t_ *memory);
    void (*allocate_funcref_table)(wasm_rt_funcref_table_t *table, uint32_t elements, uint32_t max_elements);
    uint32_t (*grow_funcref_table)(wasm_rt_funcref_table_t *table, uint32_t delta, wasm_rt_funcref_t init);
    void (*free_funcref_table)(wasm_rt_funcref_table_t *table);
    void (*allocate_externref_table)(wasm_rt_externref_table_t *table, uint32_t elements, uint32_t max_elements);
    uint32_t (*grow_externref_table)(wasm_rt_externref_table_t *table, uint32_t delta, wasm_rt_externref_t init);
    void (*free_externref_table)(wasm_rt_externref_table_t *table);
    void (*allocate_exnref_table)(wasm_rt_exnref_table_t *table, uint32_t elements, uint32_t max_elements);
    uint32_t (*grow_exnref_table)(wasm_rt_exnref_table_t *table, uint32_t delta, wasm_rt_exnref_t init);
    void (*free_exnref_table)(wasm_rt_exnref_table_t *table);
} wasmext_runtime;

#define WASMEXT_SALT_wasmext_runtime 3141592653u
#define WASMEXT_RUNTIME_LAYOUT_ ( \
    WASMEXT_LS_(71u, wasmext_runtime) ^ WASMEXT_LF_(0, wasmext_runtime, head) ^ WASMEXT_LF_(1, wasmext_runtime, trap) ^ WASMEXT_LF_(2, wasmext_runtime, load_exception) ^ \
    WASMEXT_LF_(3, wasmext_runtime, throw_exception) ^ WASMEXT_LF_(4, wasmext_runtime, get_unwind_target) ^ WASMEXT_LF_(5, wasmext_runtime, set_unwind_target) ^ \
    WASMEXT_LF_(6, wasmext_runtime, exception_tag) ^ WASMEXT_LF_(7, wasmext_runtime, exception_size) ^ WASMEXT_LF_(8, wasmext_runtime, exception_data) ^ \
    WASMEXT_LF_(9, wasmext_runtime, allocate_memory) ^ WASMEXT_LF_(10, wasmext_runtime, grow_memory) ^ WASMEXT_LF_(11, wasmext_runtime, free_memory) ^ \
    WASMEXT_LF_(12, wasmext_runtime, allocate_memory_shared) ^ WASMEXT_LF_(13, wasmext_runtime, grow_memory_shared) ^ WASMEXT_LF_(14, wasmext_runtime, free_memory_shared) ^ \
    WASMEXT_LF_(15, wasmext_runtime, allocate_funcref_table) ^ WASMEXT_LF_(16, wasmext_runtime, grow_funcref_table) ^ WASMEXT_LF_(17, wasmext_runtime, free_funcref_table) ^ \
    WASMEXT_LF_(18, wasmext_runtime, allocate_externref_table) ^ WASMEXT_LF_(19, wasmext_runtime, grow_externref_table) ^ WASMEXT_LF_(20, wasmext_runtime, free_externref_table) ^ \
    WASMEXT_LF_(21, wasmext_runtime, allocate_exnref_table) ^ WASMEXT_LF_(22, wasmext_runtime, grow_exnref_table) ^ WASMEXT_LF_(23, wasmext_runtime, free_exnref_table))

/* What a copy keeps for each thread, and nobody else reads (so it is not in the layout hash): `rt` is the table to which the forwarders of THIS copy send the call, NULL for the copy's own. */
typedef struct {
    const wasmext_runtime *rt;
} wasmext_tls;

/* hidden where the compiler can say so (as `wasmext_artifact_` is): with the default visibility the dynamic linker would let one library's table or thread record stand for another's */
#if (defined(__GNUC__) || defined(__clang__)) && !defined(_WIN32)
#define WASMEXT_HIDDEN_ __attribute__((visibility("hidden")))
#else
#define WASMEXT_HIDDEN_
#endif
extern WASM_RT_THREAD_LOCAL wasmext_tls wasmext_tls_ WASMEXT_HIDDEN_;
extern const wasmext_runtime wasmext_runtime_own_ WASMEXT_HIDDEN_;
/* A test sets the start of the counter of serials of this copy (the first store then has serial seed + 1, modulo 65536) and restarts it, so that the serials are known. */
void wasmext_runtime_fix_seed_(uint32_t seed) WASMEXT_HIDDEN_;

/* The functions of this copy, renamed by its wrappers (the real names are the forwarders) */
WASM_RT_NO_RETURN void wasmext_own_wasm_rt_trap(wasm_rt_trap_t code);
void wasmext_own_wasm_rt_load_exception(const wasm_rt_tag_t tag, uint32_t size, const void *values);
WASM_RT_NO_RETURN void wasmext_own_wasm_rt_throw(void);
WASM_RT_UNWIND_TARGET *wasmext_own_wasm_rt_get_unwind_target(void);
void wasmext_own_wasm_rt_set_unwind_target(WASM_RT_UNWIND_TARGET *target);
wasm_rt_tag_t wasmext_own_wasm_rt_exception_tag(void);
uint32_t wasmext_own_wasm_rt_exception_size(void);
void *wasmext_own_wasm_rt_exception(void);
void wasmext_own_wasm_rt_allocate_memory(wasm_rt_memory_t *, uint64_t initial_pages, uint64_t max_pages, bool is64, uint32_t page_size);
uint64_t wasmext_own_wasm_rt_grow_memory(wasm_rt_memory_t *, uint64_t pages);
void wasmext_own_wasm_rt_free_memory(wasm_rt_memory_t *);
#ifdef WASM_RT_C11_AVAILABLE
void wasmext_own_wasm_rt_allocate_memory_shared(wasm_rt_shared_memory_t *, uint64_t initial_pages, uint64_t max_pages, bool is64, uint32_t page_size);
uint64_t wasmext_own_wasm_rt_grow_memory_shared(wasm_rt_shared_memory_t *, uint64_t pages);
void wasmext_own_wasm_rt_free_memory_shared(wasm_rt_shared_memory_t *);
#endif
void wasmext_own_wasm_rt_allocate_funcref_table(wasm_rt_funcref_table_t *, uint32_t elements, uint32_t max_elements);
uint32_t wasmext_own_wasm_rt_grow_funcref_table(wasm_rt_funcref_table_t *, uint32_t delta, wasm_rt_funcref_t init);
void wasmext_own_wasm_rt_free_funcref_table(wasm_rt_funcref_table_t *);
void wasmext_own_wasm_rt_allocate_externref_table(wasm_rt_externref_table_t *, uint32_t elements, uint32_t max_elements);
uint32_t wasmext_own_wasm_rt_grow_externref_table(wasm_rt_externref_table_t *, uint32_t delta, wasm_rt_externref_t init);
void wasmext_own_wasm_rt_free_externref_table(wasm_rt_externref_table_t *);
void wasmext_own_wasm_rt_allocate_exnref_table(wasm_rt_exnref_table_t *, uint32_t elements, uint32_t max_elements);
uint32_t wasmext_own_wasm_rt_grow_exnref_table(wasm_rt_exnref_table_t *, uint32_t delta, wasm_rt_exnref_t init);
void wasmext_own_wasm_rt_free_exnref_table(wasm_rt_exnref_table_t *);

/* What the list of a store holds for this copy (wasmext_artifact_entry): `activate` makes `rt` the active runtime of this copy on the calling thread (NULL when it is the copy's own) and answers
   the one it was, `deactivate` puts that back. The entry of a call calls them for every other copy of the store (8b-2). */
static inline const void *wasmext_activate_(const void *rt) {
    const void *previous = wasmext_tls_.rt;
    wasmext_tls_.rt = rt == (const void *)&wasmext_runtime_own_ ? NULL : (const wasmext_runtime *)rt;
    return previous;
}
static inline void wasmext_deactivate_(const void *saved) {
    wasmext_tls_.rt = (const wasmext_runtime *)saved;
}

#ifdef WASMEXT_DEFINE_THREAD_STATE
WASM_RT_THREAD_LOCAL wasmext_tls wasmext_tls_;
/* The serials of the stores of this runtime: `seed + n` for the n-th store, modulo 2^16 (the handle keeps 16 bits), so two stores of this runtime never share one until 65536 are made. The seed
   comes from the address of the table (D45): two runtimes in a process start at places that differ by chance, and collide with a chance of 1 in 65536. */
static wasmext_counter wasmext_serial_count_;
static uint32_t wasmext_serial_seed_;
static int wasmext_serial_fixed_;
void wasmext_runtime_fix_seed_(uint32_t seed) {
    wasmext_serial_seed_ = seed;
    wasmext_serial_fixed_ = 1;
    wasmext_atomic_store(&wasmext_serial_count_, 0);
}
static uint32_t wasmext_runtime_next_serial_(void) {
    uint32_t seed = wasmext_serial_seed_;
    if (!wasmext_serial_fixed_) {
        uint64_t a = (uint64_t)(uintptr_t)&wasmext_runtime_own_;
        seed = (uint32_t)((a >> 4) ^ (a >> 20) ^ (a >> 36));
    }
    return (seed + (uint32_t)wasmext_atomic_add(&wasmext_serial_count_, 1)) & 0xFFFFu;
}
#endif

#endif /* WASMEXT_RUNTIME_H */

/* ---- The forwarders. A wrapper of the runtime includes this file a second time, after its `#undef` of the renaming, with one of WASMEXT_RT_FORWARD_IMPL / _EXC / _MEM defined; the real names
   are declared by wasm-rt.h (read before the renaming), so a signature that does not agree with the header is an error here. ---- */
#define WASMEXT_FWD_VOID_(NAME, MEMBER, PARAMS, ARGS) \
    void NAME PARAMS { const wasmext_runtime *rt = wasmext_tls_.rt; if (rt != NULL) rt->MEMBER ARGS; else wasmext_own_##NAME ARGS; }
#define WASMEXT_FWD_VALUE_(TYPE, NAME, MEMBER, PARAMS, ARGS) \
    TYPE NAME PARAMS { const wasmext_runtime *rt = wasmext_tls_.rt; return rt != NULL ? rt->MEMBER ARGS : wasmext_own_##NAME ARGS; }

#ifdef WASMEXT_RT_FORWARD_IMPL
#undef WASMEXT_RT_FORWARD_IMPL
/* a trap does not return: if the function of the table does, that is a bug of the table, and it is not run on into the code that trapped */
WASM_RT_NO_RETURN void wasm_rt_trap(wasm_rt_trap_t code) {
    const wasmext_runtime *rt = wasmext_tls_.rt;
    if (rt != NULL) {
        rt->trap(code);
        abort();
    }
    wasmext_own_wasm_rt_trap(code);
}
WASMEXT_FWD_VOID_(wasm_rt_allocate_funcref_table, allocate_funcref_table, (wasm_rt_funcref_table_t *table, uint32_t elements, uint32_t max_elements), (table, elements, max_elements))
WASMEXT_FWD_VALUE_(uint32_t, wasm_rt_grow_funcref_table, grow_funcref_table, (wasm_rt_funcref_table_t *table, uint32_t delta, wasm_rt_funcref_t init), (table, delta, init))
WASMEXT_FWD_VOID_(wasm_rt_free_funcref_table, free_funcref_table, (wasm_rt_funcref_table_t *table), (table))
WASMEXT_FWD_VOID_(wasm_rt_allocate_externref_table, allocate_externref_table, (wasm_rt_externref_table_t *table, uint32_t elements, uint32_t max_elements), (table, elements, max_elements))
WASMEXT_FWD_VALUE_(uint32_t, wasm_rt_grow_externref_table, grow_externref_table, (wasm_rt_externref_table_t *table, uint32_t delta, wasm_rt_externref_t init), (table, delta, init))
WASMEXT_FWD_VOID_(wasm_rt_free_externref_table, free_externref_table, (wasm_rt_externref_table_t *table), (table))
#endif

#ifdef WASMEXT_RT_FORWARD_EXC
#undef WASMEXT_RT_FORWARD_EXC
WASMEXT_FWD_VOID_(wasm_rt_load_exception, load_exception, (const wasm_rt_tag_t tag, uint32_t size, const void *values), (tag, size, values))
WASM_RT_NO_RETURN void wasm_rt_throw(void) {
    const wasmext_runtime *rt = wasmext_tls_.rt;
    if (rt != NULL) {
        rt->throw_exception();
        abort();
    }
    wasmext_own_wasm_rt_throw();
}
WASMEXT_FWD_VALUE_(WASM_RT_UNWIND_TARGET *, wasm_rt_get_unwind_target, get_unwind_target, (void), ())
WASMEXT_FWD_VOID_(wasm_rt_set_unwind_target, set_unwind_target, (WASM_RT_UNWIND_TARGET *target), (target))
WASMEXT_FWD_VALUE_(wasm_rt_tag_t, wasm_rt_exception_tag, exception_tag, (void), ())
WASMEXT_FWD_VALUE_(uint32_t, wasm_rt_exception_size, exception_size, (void), ())
WASMEXT_FWD_VALUE_(void *, wasm_rt_exception, exception_data, (void), ())
WASMEXT_FWD_VOID_(wasm_rt_allocate_exnref_table, allocate_exnref_table, (wasm_rt_exnref_table_t *table, uint32_t elements, uint32_t max_elements), (table, elements, max_elements))
WASMEXT_FWD_VALUE_(uint32_t, wasm_rt_grow_exnref_table, grow_exnref_table, (wasm_rt_exnref_table_t *table, uint32_t delta, wasm_rt_exnref_t init), (table, delta, init))
WASMEXT_FWD_VOID_(wasm_rt_free_exnref_table, free_exnref_table, (wasm_rt_exnref_table_t *table), (table))
#endif

#ifdef WASMEXT_RT_FORWARD_MEM
#undef WASMEXT_RT_FORWARD_MEM
WASMEXT_FWD_VOID_(wasm_rt_allocate_memory, allocate_memory, (wasm_rt_memory_t *memory, uint64_t initial_pages, uint64_t max_pages, bool is64, uint32_t page_size), (memory, initial_pages, max_pages, is64, page_size))
WASMEXT_FWD_VALUE_(uint64_t, wasm_rt_grow_memory, grow_memory, (wasm_rt_memory_t *memory, uint64_t pages), (memory, pages))
WASMEXT_FWD_VOID_(wasm_rt_free_memory, free_memory, (wasm_rt_memory_t *memory), (memory))
#ifdef WASM_RT_C11_AVAILABLE
WASMEXT_FWD_VOID_(wasm_rt_allocate_memory_shared, allocate_memory_shared, (wasm_rt_shared_memory_t *memory, uint64_t initial_pages, uint64_t max_pages, bool is64, uint32_t page_size), (memory, initial_pages, max_pages, is64, page_size))
WASMEXT_FWD_VALUE_(uint64_t, wasm_rt_grow_memory_shared, grow_memory_shared, (wasm_rt_shared_memory_t *memory, uint64_t pages), (memory, pages))
WASMEXT_FWD_VOID_(wasm_rt_free_memory_shared, free_memory_shared, (wasm_rt_shared_memory_t *memory), (memory))
#endif
#endif
