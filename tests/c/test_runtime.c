/* Step 8b-1 of docs/specs/S0008-shared-store.md: the forwarders `wasm_rt_*` of a copy (the real names, defined by the wrappers of the runtime that the product builds) send the call to the
   function of the runtime table `tls.rt` when it is set, and to the function of the copy itself when it is NULL. For each of the 23 functions: with a stub table whose functions count their
   calls, the counter of that function moves once and no other, the arguments and the result pass through; with `tls.rt` NULL no stub runs and the real function does its work. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_instance.h"

static int failures;
#define CHECK(COND, WHAT) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed for %s: %s\n", __FILE__, __LINE__, (WHAT), #COND); failures++; } } while (0)

enum {
    F_TRAP, F_LOAD, F_THROW, F_GET_UT, F_SET_UT, F_TAG, F_SIZE, F_DATA,
    F_ALLOC_MEM, F_GROW_MEM, F_FREE_MEM, F_ALLOC_SHM, F_GROW_SHM, F_FREE_SHM,
    F_ALLOC_FT, F_GROW_FT, F_FREE_FT, F_ALLOC_ET, F_GROW_ET, F_FREE_ET, F_ALLOC_XT, F_GROW_XT, F_FREE_XT,
    F_COUNT
};
static const char *const names[F_COUNT] = {
    "wasm_rt_trap", "wasm_rt_load_exception", "wasm_rt_throw", "wasm_rt_get_unwind_target", "wasm_rt_set_unwind_target", "wasm_rt_exception_tag", "wasm_rt_exception_size",
    "wasm_rt_exception", "wasm_rt_allocate_memory", "wasm_rt_grow_memory", "wasm_rt_free_memory", "wasm_rt_allocate_memory_shared", "wasm_rt_grow_memory_shared",
    "wasm_rt_free_memory_shared", "wasm_rt_allocate_funcref_table", "wasm_rt_grow_funcref_table", "wasm_rt_free_funcref_table", "wasm_rt_allocate_externref_table",
    "wasm_rt_grow_externref_table", "wasm_rt_free_externref_table", "wasm_rt_allocate_exnref_table", "wasm_rt_grow_exnref_table", "wasm_rt_free_exnref_table"};

/* ---- the stub runtime: every function counts, remembers its arguments, and answers a number of its own ---- */
static int hits[F_COUNT];
static uint64_t seen[3]; /* the arguments of the last call that were not pointers */
static const void *seen_pointer;
static wasm_rt_jmp_buf stub_jmp;
static char marker; /* an address the stub hands back */
static char marks[4]; /* addresses the test passes as the `init` of a grow */
static wasm_rt_funcref_t seen_funcref; /* the `init` the stub received */
static wasm_rt_exnref_t seen_exnref;

static void stub_trap(wasm_rt_trap_t code) { hits[F_TRAP]++; seen[0] = (uint64_t)code; WASM_RT_LONGJMP(stub_jmp, 77); }
static void stub_load(wasm_rt_tag_t tag, uint32_t size, const void *values) { hits[F_LOAD]++; seen_pointer = tag; seen[0] = size; seen[1] = (uint64_t)(uintptr_t)values; }
static void stub_throw(void) { hits[F_THROW]++; WASM_RT_LONGJMP(stub_jmp, 78); }
static WASM_RT_UNWIND_TARGET *stub_get_ut(void) { hits[F_GET_UT]++; return (WASM_RT_UNWIND_TARGET *)&marker; }
static void stub_set_ut(WASM_RT_UNWIND_TARGET *target) { hits[F_SET_UT]++; seen_pointer = target; }
static wasm_rt_tag_t stub_tag(void) { hits[F_TAG]++; return (wasm_rt_tag_t)&marker; }
static uint32_t stub_size(void) { hits[F_SIZE]++; return 4242; }
static void *stub_data(void) { hits[F_DATA]++; return &marker; }
static void stub_alloc_mem(wasm_rt_memory_t *m, uint64_t initial, uint64_t max, bool is64, uint32_t page) { hits[F_ALLOC_MEM]++; seen_pointer = m; seen[0] = initial; seen[1] = max; seen[2] = (uint64_t)is64 << 32 | page; }
static uint64_t stub_grow_mem(wasm_rt_memory_t *m, uint64_t pages) { hits[F_GROW_MEM]++; seen_pointer = m; seen[0] = pages; return 1001; }
static void stub_free_mem(wasm_rt_memory_t *m) { hits[F_FREE_MEM]++; seen_pointer = m; }
static void stub_alloc_shm(wasmext_shared_memory_t_ *m, uint64_t initial, uint64_t max, bool is64, uint32_t page) { hits[F_ALLOC_SHM]++; seen_pointer = m; seen[0] = initial; seen[1] = max; seen[2] = (uint64_t)is64 << 32 | page; }
static uint64_t stub_grow_shm(wasmext_shared_memory_t_ *m, uint64_t pages) { hits[F_GROW_SHM]++; seen_pointer = m; seen[0] = pages; return 1002; }
static void stub_free_shm(wasmext_shared_memory_t_ *m) { hits[F_FREE_SHM]++; seen_pointer = m; }
static void stub_alloc_ft(wasm_rt_funcref_table_t *t, uint32_t n, uint32_t max) { hits[F_ALLOC_FT]++; seen_pointer = t; seen[0] = n; seen[1] = max; }
static uint32_t stub_grow_ft(wasm_rt_funcref_table_t *t, uint32_t delta, wasm_rt_funcref_t init) { hits[F_GROW_FT]++; seen_pointer = t; seen[0] = delta; seen_funcref = init; return 1003; }
static void stub_free_ft(wasm_rt_funcref_table_t *t) { hits[F_FREE_FT]++; seen_pointer = t; }
static void stub_alloc_et(wasm_rt_externref_table_t *t, uint32_t n, uint32_t max) { hits[F_ALLOC_ET]++; seen_pointer = t; seen[0] = n; seen[1] = max; }
static uint32_t stub_grow_et(wasm_rt_externref_table_t *t, uint32_t delta, wasm_rt_externref_t init) { hits[F_GROW_ET]++; seen_pointer = t; seen[0] = delta; seen[1] = (uint64_t)(uintptr_t)init; return 1004; }
static void stub_free_et(wasm_rt_externref_table_t *t) { hits[F_FREE_ET]++; seen_pointer = t; }
static void stub_alloc_xt(wasm_rt_exnref_table_t *t, uint32_t n, uint32_t max) { hits[F_ALLOC_XT]++; seen_pointer = t; seen[0] = n; seen[1] = max; }
static uint32_t stub_grow_xt(wasm_rt_exnref_table_t *t, uint32_t delta, wasm_rt_exnref_t init) { hits[F_GROW_XT]++; seen_pointer = t; seen[0] = delta; seen_exnref = init; return 1005; }
static void stub_free_xt(wasm_rt_exnref_table_t *t) { hits[F_FREE_XT]++; seen_pointer = t; }

static wasmext_runtime stub;
static void make_stub(void) {
    memset(&stub, 0, sizeof stub);
    stub.trap = stub_trap; stub.load_exception = stub_load; stub.throw_exception = stub_throw; stub.get_unwind_target = stub_get_ut; stub.set_unwind_target = stub_set_ut;
    stub.exception_tag = stub_tag; stub.exception_size = stub_size; stub.exception_data = stub_data;
    stub.allocate_memory = stub_alloc_mem; stub.grow_memory = stub_grow_mem; stub.free_memory = stub_free_mem;
    stub.allocate_memory_shared = stub_alloc_shm; stub.grow_memory_shared = stub_grow_shm; stub.free_memory_shared = stub_free_shm;
    stub.allocate_funcref_table = stub_alloc_ft; stub.grow_funcref_table = stub_grow_ft; stub.free_funcref_table = stub_free_ft;
    stub.allocate_externref_table = stub_alloc_et; stub.grow_externref_table = stub_grow_et; stub.free_externref_table = stub_free_et;
    stub.allocate_exnref_table = stub_alloc_xt; stub.grow_exnref_table = stub_grow_xt; stub.free_exnref_table = stub_free_xt;
}

/* the call goes through the stub table (`stubbed`) or through the copy's own functions; the set-up and the clean-up of a case are always the copy's own */
static void begin(int stubbed) { wasmext_tls_.rt = NULL; memset(hits, 0, sizeof hits); memset(seen, 0, sizeof seen); seen_pointer = NULL; if (stubbed) wasmext_tls_.rt = &stub; }
static void end(void) { wasmext_tls_.rt = NULL; }

/* One case: `run(which, stubbed)` makes the call of function `which` and checks its result: the stub's number and arguments when stubbed, the real effect when not. */
static void run(int which, int stubbed) {
    wasm_rt_memory_t m;
    wasm_rt_funcref_table_t ft;
    wasm_rt_externref_table_t et;
    wasm_rt_exnref_table_t xt;
    wasm_rt_jmp_buf target;
    volatile int code = 0;
    const char *n = names[which];
    uint8_t bytes[4] = {9, 8, 7, 6};
    memset(&m, 0, sizeof m); memset(&ft, 0, sizeof ft); memset(&et, 0, sizeof et); memset(&xt, 0, sizeof xt);
    switch (which) {
    case F_TRAP:
        begin(stubbed);
        if (stubbed) { if (WASM_RT_SETJMP(stub_jmp) == 0) wasm_rt_trap(WASM_RT_TRAP_DIV_BY_ZERO); else code = 1; }
        else { wasmext_rt_entry entry; wasmext_rt_enter_(&entry); if (WASM_RT_SETJMP(entry.buf) == 0) wasm_rt_trap(WASM_RT_TRAP_DIV_BY_ZERO); else code = 1; wasmext_rt_leave_(&entry); } /* the trap of the copy comes back to the innermost entry (8b-2) */
        end();
        CHECK(code == 1, n);
        if (stubbed) CHECK(seen[0] == (uint64_t)WASM_RT_TRAP_DIV_BY_ZERO, n);
        break;
    case F_THROW:
        wasm_rt_set_unwind_target(&target); /* the copy's own (tls.rt is NULL here) */
        begin(stubbed);
        if (stubbed) { if (WASM_RT_SETJMP(stub_jmp) == 0) wasm_rt_throw(); else code = 1; }
        else { if (WASM_RT_SETJMP_EXN(target) == 0) wasm_rt_throw(); else code = 1; }
        end();
        CHECK(code == 1, n);
        break;
    case F_LOAD:
        begin(stubbed);
        wasm_rt_load_exception((wasm_rt_tag_t)&marker, 4, bytes);
        end();
        if (stubbed) CHECK(seen_pointer == &marker && seen[0] == 4 && seen[1] == (uint64_t)(uintptr_t)bytes, n);
        else CHECK(wasm_rt_exception_size() == 4 && wasm_rt_exception_tag() == (wasm_rt_tag_t)&marker && memcmp(wasm_rt_exception(), bytes, 4) == 0, n);
        break;
    case F_GET_UT: case F_SET_UT:
        begin(stubbed);
        if (which == F_SET_UT) wasm_rt_set_unwind_target(&target); else seen_pointer = wasm_rt_get_unwind_target();
        end();
        if (stubbed) CHECK((which == F_SET_UT ? seen_pointer == (void *)&target : seen_pointer == (void *)&marker), n);
        else { wasm_rt_set_unwind_target(&target); CHECK(wasm_rt_get_unwind_target() == &target, n); }
        break;
    case F_TAG: case F_SIZE: case F_DATA:
        wasm_rt_load_exception((wasm_rt_tag_t)&marker, 4, bytes);
        begin(stubbed);
        if (which == F_TAG) seen_pointer = wasm_rt_exception_tag();
        else if (which == F_SIZE) seen[0] = wasm_rt_exception_size();
        else seen_pointer = wasm_rt_exception();
        end();
        if (stubbed) CHECK(which == F_SIZE ? seen[0] == 4242 : seen_pointer == (const void *)&marker, n);
        else CHECK(which == F_SIZE ? seen[0] == 4 : which == F_TAG ? seen_pointer == (const void *)&marker : memcmp(seen_pointer, bytes, 4) == 0, n);
        break;
    case F_ALLOC_MEM: case F_GROW_MEM: case F_FREE_MEM:
        if (which != F_ALLOC_MEM) wasm_rt_allocate_memory(&m, 1, 2, false, 65536);
        begin(stubbed);
        if (which == F_ALLOC_MEM) wasm_rt_allocate_memory(&m, 3, 5, true, 65536);
        else if (which == F_GROW_MEM) seen[1] = wasm_rt_grow_memory(&m, 1);
        else wasm_rt_free_memory(&m);
        end();
        if (stubbed) {
            CHECK(seen_pointer == &m, n);
            if (which == F_ALLOC_MEM) CHECK(seen[0] == 3 && seen[1] == 5 && seen[2] == ((uint64_t)1 << 32 | 65536), n);
            if (which == F_GROW_MEM) CHECK(seen[0] == 1 && seen[1] == 1001, n);
        } else {
            if (which == F_ALLOC_MEM) { CHECK(m.pages == 3 && m.max_pages == 5 && m.data != NULL, n); wasm_rt_free_memory(&m); }
            if (which == F_GROW_MEM) { CHECK(seen[1] == 1 && m.pages == 2, n); wasm_rt_free_memory(&m); }
        }
        break;
#ifdef WASM_RT_C11_AVAILABLE
    case F_ALLOC_SHM: case F_GROW_SHM: case F_FREE_SHM: {
        wasm_rt_shared_memory_t sm;
        memset(&sm, 0, sizeof sm);
        if (which != F_ALLOC_SHM) wasm_rt_allocate_memory_shared(&sm, 1, 2, false, 65536);
        begin(stubbed);
        if (which == F_ALLOC_SHM) wasm_rt_allocate_memory_shared(&sm, 3, 5, true, 65536);
        else if (which == F_GROW_SHM) seen[1] = wasm_rt_grow_memory_shared(&sm, 1);
        else wasm_rt_free_memory_shared(&sm);
        end();
        if (stubbed) {
            CHECK(seen_pointer == &sm, n);
            if (which == F_ALLOC_SHM) CHECK(seen[0] == 3 && seen[1] == 5 && seen[2] == ((uint64_t)1 << 32 | 65536), n);
            if (which == F_GROW_SHM) CHECK(seen[0] == 1 && seen[1] == 1002, n);
        } else {
            if (which == F_ALLOC_SHM) { CHECK(sm.pages == 3 && sm.max_pages == 5 && sm.data != NULL, n); wasm_rt_free_memory_shared(&sm); }
            if (which == F_GROW_SHM) { CHECK(seen[1] == 1 && sm.pages == 2, n); wasm_rt_free_memory_shared(&sm); }
        }
        break;
    }
#endif
    case F_ALLOC_FT: case F_GROW_FT: case F_FREE_FT:
        if (which != F_ALLOC_FT) wasm_rt_allocate_funcref_table(&ft, 2, 8);
        begin(stubbed);
        if (which == F_ALLOC_FT) wasm_rt_allocate_funcref_table(&ft, 3, 6);
        else if (which == F_GROW_FT) {
            wasm_rt_funcref_t init = {(wasm_rt_func_type_t)&marks[0], NULL, {NULL}, &marks[1]};
            init.func = (wasm_rt_function_ptr_t)(uintptr_t)&marks[2]; /* a marked, non-null value in every field: a dropped or replaced `init` shows */
            seen[2] = wasm_rt_grow_funcref_table(&ft, 1, stubbed ? init : wasm_rt_funcref_null_value);
        }
        else wasm_rt_free_funcref_table(&ft);
        end();
        if (stubbed) {
            CHECK(seen_pointer == &ft, n);
            if (which == F_ALLOC_FT) CHECK(seen[0] == 3 && seen[1] == 6, n);
            if (which == F_GROW_FT) CHECK(seen[0] == 1 && seen[2] == 1003 && seen_funcref.func_type == (wasm_rt_func_type_t)&marks[0] && seen_funcref.module_instance == &marks[1] && (uintptr_t)seen_funcref.func == (uintptr_t)&marks[2], n);
        } else {
            if (which == F_ALLOC_FT) { CHECK(ft.size == 3 && ft.max_size == 6 && ft.data != NULL, n); wasm_rt_free_funcref_table(&ft); }
            if (which == F_GROW_FT) { CHECK(seen[2] == 2 && ft.size == 3, n); wasm_rt_free_funcref_table(&ft); }
        }
        break;
    case F_ALLOC_ET: case F_GROW_ET: case F_FREE_ET:
        if (which != F_ALLOC_ET) wasm_rt_allocate_externref_table(&et, 2, 8);
        begin(stubbed);
        if (which == F_ALLOC_ET) wasm_rt_allocate_externref_table(&et, 3, 6);
        else if (which == F_GROW_ET) seen[2] = wasm_rt_grow_externref_table(&et, 1, stubbed ? (wasm_rt_externref_t)&marks[3] : wasm_rt_externref_null_value);
        else wasm_rt_free_externref_table(&et);
        end();
        if (stubbed) {
            CHECK(seen_pointer == &et, n);
            if (which == F_ALLOC_ET) CHECK(seen[0] == 3 && seen[1] == 6, n);
            if (which == F_GROW_ET) CHECK(seen[0] == 1 && seen[2] == 1004 && seen[1] == (uint64_t)(uintptr_t)&marks[3], n);
        } else {
            if (which == F_ALLOC_ET) { CHECK(et.size == 3 && et.max_size == 6 && et.data != NULL, n); wasm_rt_free_externref_table(&et); }
            if (which == F_GROW_ET) { CHECK(seen[2] == 2 && et.size == 3, n); wasm_rt_free_externref_table(&et); }
        }
        break;
    case F_ALLOC_XT: case F_GROW_XT: case F_FREE_XT:
        if (which != F_ALLOC_XT) wasm_rt_allocate_exnref_table(&xt, 2, 8);
        begin(stubbed);
        if (which == F_ALLOC_XT) wasm_rt_allocate_exnref_table(&xt, 3, 6);
        else if (which == F_GROW_XT) {
            wasm_rt_exnref_t init = wasm_rt_exnref_null_value;
            init.tag = (wasm_rt_tag_t)&marks[0];
            init.size = 7;
            init.data[0] = 5;
            seen[2] = wasm_rt_grow_exnref_table(&xt, 1, stubbed ? init : wasm_rt_exnref_null_value);
        }
        else wasm_rt_free_exnref_table(&xt);
        end();
        if (stubbed) {
            CHECK(seen_pointer == &xt, n);
            if (which == F_ALLOC_XT) CHECK(seen[0] == 3 && seen[1] == 6, n);
            if (which == F_GROW_XT) CHECK(seen[0] == 1 && seen[2] == 1005 && seen_exnref.tag == (wasm_rt_tag_t)&marks[0] && seen_exnref.size == 7 && seen_exnref.data[0] == 5, n);
        } else {
            if (which == F_ALLOC_XT) { CHECK(xt.size == 3 && xt.max_size == 6 && xt.data != NULL, n); wasm_rt_free_exnref_table(&xt); }
            if (which == F_GROW_XT) { CHECK(seen[2] == 2 && xt.size == 3, n); wasm_rt_free_exnref_table(&xt); }
        }
        break;
    default:
        break;
    }
}

static void test_forwarders(void) {
    int which, k;
    make_stub();
    for (which = 0; which < F_COUNT; which++) {
#ifndef WASM_RT_C11_AVAILABLE
        if (which >= F_ALLOC_SHM && which <= F_FREE_SHM) continue;
#endif
        /* through the stub: the counter of this function moves once and no other */
        run(which, 1);
        for (k = 0; k < F_COUNT; k++) {
            if (k == which) CHECK(hits[k] == 1, names[which]);
            else if (hits[k] != 0) { fprintf(stderr, "%s:%d: %s went to the function of %s\n", __FILE__, __LINE__, names[which], names[k]); failures++; }
        }
        /* with tls.rt NULL: no function of the stub runs (the copy's own does the work: run checked its effect) */
        run(which, 0);
        for (k = 0; k < F_COUNT; k++)
            if (hits[k] != 0) { fprintf(stderr, "%s:%d: %s with tls.rt NULL ran the stub's %s\n", __FILE__, __LINE__, names[which], names[k]); failures++; }
    }
}

/* the table of this copy: what a store made here points at, and every slot holds the function of its name (a slot with another function, or two swapped, would send a forwarder to the wrong one) */
#define SLOT(NAME, MEMBER) {"wasm_rt_" #NAME, (const void *)(uintptr_t)own->MEMBER, (const void *)(uintptr_t)&wasmext_own_wasm_rt_##NAME}
static void test_own_table(void) {
    const wasmext_runtime *own = &wasmext_runtime_own_;
    wasmext_store *s = wasmext_store_new();
    struct { const char *name; const void *slot, *function; } slots[] = {
        SLOT(trap, trap), SLOT(load_exception, load_exception), SLOT(throw, throw_exception), SLOT(get_unwind_target, get_unwind_target), SLOT(set_unwind_target, set_unwind_target),
        SLOT(exception_tag, exception_tag), SLOT(exception_size, exception_size), SLOT(exception, exception_data),
        SLOT(allocate_memory, allocate_memory), SLOT(grow_memory, grow_memory), SLOT(free_memory, free_memory),
#ifdef WASM_RT_C11_AVAILABLE
        SLOT(allocate_memory_shared, allocate_memory_shared), SLOT(grow_memory_shared, grow_memory_shared), SLOT(free_memory_shared, free_memory_shared),
#endif
        SLOT(allocate_funcref_table, allocate_funcref_table), SLOT(grow_funcref_table, grow_funcref_table), SLOT(free_funcref_table, free_funcref_table),
        SLOT(allocate_externref_table, allocate_externref_table), SLOT(grow_externref_table, grow_externref_table), SLOT(free_externref_table, free_externref_table),
        SLOT(allocate_exnref_table, allocate_exnref_table), SLOT(grow_exnref_table, grow_exnref_table), SLOT(free_exnref_table, free_exnref_table)};
    size_t k;
    CHECK(s != NULL && s->head.rt == (const void *)own, "the store points at the runtime table of the copy");
    CHECK(own->head.size == sizeof(wasmext_runtime) && own->head.version == WASMEXT_RUNTIME_VERSION && own->head.layout == WASMEXT_CORE_LAYOUT && own->head.flags == WASMEXT_RT_FLAGS, "the head of the table");
    size_t expected = F_COUNT; /* the shared-memory slots exist only with C11 atomics; a directive inside the arguments of a macro is not allowed (MSVC refuses it) */
#ifndef WASM_RT_C11_AVAILABLE
    expected -= 3;
#endif
    CHECK(sizeof slots / sizeof slots[0] == expected, "all the slots of the table are compared");
    for (k = 0; k < sizeof slots / sizeof slots[0]; k++) CHECK(slots[k].slot == slots[k].function, slots[k].name);
    CHECK(wasmext_store_free(s) == WASMEXT_STORE_OK, "free");
}

int main(void) {
    test_forwarders();
    test_own_table();
    if (failures) { fprintf(stderr, "%d failures\n", failures); return 1; }
    puts("ok");
    return 0;
}
