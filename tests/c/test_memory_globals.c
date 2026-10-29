/* The exported memories and globals of an instance, in plain C over a real wasm2c module. MODULE is the prefix; MEMORY64 (a macro) selects the checks of a memory64 module. */
#include <stdio.h>
#include "wasmext_instance.h"

#define CAT_(a, b) a##b
#define CAT(a, b) CAT_(a, b)
extern const wasmext_binding CAT(MODULE, _binding);
#define BINDING (&CAT(MODULE, _binding))

#ifdef _WIN32
#include <process.h>
typedef HANDLE thread_t;
#define THREAD_RESULT unsigned __stdcall
static void thread_start(thread_t *t, unsigned (__stdcall *f)(void *), void *arg) { *t = (HANDLE)_beginthreadex(NULL, 0, f, arg, 0, NULL); }
static void thread_join(thread_t t) { WaitForSingleObject(t, INFINITE); CloseHandle(t); }
#else
typedef pthread_t thread_t;
#define THREAD_RESULT void *
static void thread_start(thread_t *t, THREAD_RESULT (*f)(void *), void *arg) { pthread_create(t, NULL, f, arg); }
static void thread_join(thread_t t) { pthread_join(t, NULL); }
#endif

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static wasmext_val I32(int32_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7F; x.as.i32 = v; return x; }
static int export_of(wasmext_instance *i, const char *name, int kind) { return wasmext_instance_export_find(i, name, strlen(name), kind); }
static int call(wasmext_instance *i, const char *name, const wasmext_val *a, uint32_t na, wasmext_val *r, uint32_t nr) {
    return wasmext_instance_call(i, (uint32_t)export_of(i, name, WASMEXT_DESC_FUNC), a, na, r, nr);
}

#ifndef MEMORY64
static void test_globals(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = wasmext_instance_new(s, BINDING, NULL);
    wasmext_val v, r[1];
    int gm, gc, gf, gd, gv;
    CHECK(wasmext_instance_instantiate(i) == 0);
    gm = export_of(i, "gm", WASMEXT_DESC_GLOBAL); gc = export_of(i, "gc", WASMEXT_DESC_GLOBAL); gf = export_of(i, "gf", WASMEXT_DESC_GLOBAL);
    gd = export_of(i, "gd", WASMEXT_DESC_GLOBAL); gv = export_of(i, "gv", WASMEXT_DESC_GLOBAL);
    CHECK(gm >= 0 && gc >= 0 && gf >= 0 && gd >= 0 && gv >= 0);
    CHECK(wasmext_instance_global_get(i, (uint32_t)gm, &v) == 0 && v.type == 0x7F && v.as.i32 == 5);
    CHECK(wasmext_instance_global_get(i, (uint32_t)gc, &v) == 0 && v.type == 0x7E && v.as.i64 == 9);
    CHECK(wasmext_instance_global_get(i, (uint32_t)gf, &v) == 0 && v.type == 0x7D && v.as.f32 == 1.5f);
    CHECK(wasmext_instance_global_get(i, (uint32_t)gd, &v) == 0 && v.type == 0x7C && v.as.f64 == 2.5);
    {
        int32_t lanes[4], want[4] = {1, 2, 3, 4};
        CHECK(wasmext_instance_global_get(i, (uint32_t)gv, &v) == 0 && v.type == 0x7B);
        memcpy(lanes, v.as.v128, 16);
        CHECK(memcmp(lanes, want, 16) == 0);
    }
    /* set, and the module sees it; the module changes it, and the host sees it */
    v = I32(100);
    CHECK(wasmext_instance_global_set(i, (uint32_t)gm, &v) == 0);
    CHECK(call(i, "bump", NULL, 0, r, 1) == 0 && r[0].as.i32 == 101);
    CHECK(wasmext_instance_global_get(i, (uint32_t)gm, &v) == 0 && v.as.i32 == 101);
    memset(&v, 0, sizeof v); v.type = 0x7C; v.as.f64 = -0.5;
    CHECK(wasmext_instance_global_set(i, (uint32_t)gd, &v) == 0 && wasmext_instance_global_get(i, (uint32_t)gd, &v) == 0 && v.as.f64 == -0.5);
    memset(&v, 0, sizeof v); v.type = 0x7B; memset(v.as.v128, 7, 16);
    CHECK(wasmext_instance_global_set(i, (uint32_t)gv, &v) == 0);
    memset(&v, 0, sizeof v);
    CHECK(wasmext_instance_global_get(i, (uint32_t)gv, &v) == 0 && v.as.v128[15] == 7);
    /* refused: an immutable global, a value of another type, a bad index, a function */
    memset(&v, 0, sizeof v); v.type = 0x7E; v.as.i64 = 1;
    CHECK(wasmext_instance_global_set(i, (uint32_t)gc, &v) == WASMEXT_INST_IMMUTABLE);
    CHECK(wasmext_instance_global_set(i, (uint32_t)gm, &v) == WASMEXT_INST_BAD_ARGS);
    CHECK(wasmext_instance_global_get(i, 999, &v) == WASMEXT_INST_BAD_EXPORT);
    CHECK(wasmext_instance_global_get(i, (uint32_t)export_of(i, "bump", WASMEXT_DESC_FUNC), &v) == WASMEXT_INST_BAD_EXPORT);
    /* a closed store */
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_instance_global_get(i, (uint32_t)gm, &v) == (int)WASMEXT_TRAP_CLOSED);
    wasmext_instance_free(i);
    wasmext_store_free(s);
}
#endif

static void test_memory(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = wasmext_instance_new(s, BINDING, NULL);
    wasmext_memory_view v, w;
    wasmext_val a[2], r[1];
    int mem = export_of(i, "mem", WASMEXT_DESC_MEMORY);
    CHECK(mem >= 0);
    CHECK(wasmext_instance_memory(i, (uint32_t)mem, &v) == WASMEXT_INST_NOT_INSTANTIATED);
    CHECK(wasmext_instance_instantiate(i) == 0);
    CHECK(wasmext_instance_memory(i, (uint32_t)mem, &v) == 0);
    CHECK(v.base != NULL && v.pages == 1 && v.size == 65536 && v.page_size == 65536 && v.max_pages == 4);
#ifdef MEMORY64
    CHECK(v.is64);
#else
    CHECK(!v.is64);
    CHECK(memcmp(v.base + 8, "wasm", 4) == 0); /* the data segment */
#endif
    /* bytes written through the view are seen by the module, and the other way */
    v.base[100] = 42;
    a[0] = I32(100);
    CHECK(call(i, "load", a, 1, r, 1) == 0 && r[0].as.i32 == 42);
    a[0] = I32(101); a[1] = I32(77);
    CHECK(call(i, "store", a, 2, NULL, 0) == 0 && v.base[101] == 77);
    /* growing from the host: the pages it had, and -1 past the maximum */
    CHECK(wasmext_instance_memory_grow(i, (uint32_t)mem, 1) == 1);
    CHECK(wasmext_instance_memory(i, (uint32_t)mem, &w) == 0 && w.pages == 2 && w.size == 131072 && w.base[100] == 42); /* the bytes are kept, wherever they went */
    a[0] = I32(1);
    CHECK(call(i, "grow", a, 1, r, 1) == 0 && r[0].as.i32 == 2); /* from the module */
    CHECK(wasmext_instance_memory_grow(i, (uint32_t)mem, 5) == -1);
    CHECK(wasmext_instance_memory_grow(i, 999, 1) == WASMEXT_INST_BAD_EXPORT);
    /* a pin: a memory that the runtime moves when it grows cannot grow while it is pinned, and does not move; a memory that never moves is not touched by it */
    CHECK(wasmext_instance_memory(i, (uint32_t)mem, &v) == 0 && v.pages == 3);
    CHECK(wasmext_instance_memory_pin(i, (uint32_t)mem, 1) == 0 && wasmext_instance_memory_pin(i, (uint32_t)mem, 1) == 0); /* pins count */
    {
        int pinned_refuses = v.is64 || !WASM_RT_USE_MMAP;
        a[0] = I32(1);
        CHECK((wasmext_instance_memory_grow(i, (uint32_t)mem, 1) == -1) == pinned_refuses);
        if (pinned_refuses) {
            CHECK(call(i, "grow", a, 1, r, 1) == 0 && r[0].as.i32 == -1); /* the module is refused too */
            CHECK(wasmext_instance_memory(i, (uint32_t)mem, &w) == 0 && w.base == v.base && w.pages == 3 && w.max_pages == 3);
            CHECK(wasmext_instance_memory_pin(i, (uint32_t)mem, 0) == 0); /* one pin is left */
            CHECK(wasmext_instance_memory_grow(i, (uint32_t)mem, 1) == -1);
            CHECK(wasmext_instance_memory_pin(i, (uint32_t)mem, 0) == 0);
            CHECK(wasmext_instance_memory_grow(i, (uint32_t)mem, 1) == 3); /* unpinned: the maximum is back */
            CHECK(wasmext_instance_memory(i, (uint32_t)mem, &w) == 0 && w.max_pages == 4 && w.pages == 4);
        } else {
            CHECK(wasmext_instance_memory_pin(i, (uint32_t)mem, 0) == 0 && wasmext_instance_memory_pin(i, (uint32_t)mem, 0) == 0);
        }
    }
    CHECK(wasmext_instance_memory_pin(i, (uint32_t)mem, 0) == 0); /* more unpins than pins: nothing happens */
    CHECK(wasmext_instance_memory_pin(i, 999, 1) == WASMEXT_INST_BAD_EXPORT);
    /* a memory export is not a function, and the other way */
    CHECK(wasmext_instance_call(i, (uint32_t)mem, NULL, 0, r, 0) == WASMEXT_INST_BAD_EXPORT);
    /* a closed store */
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_instance_memory(i, (uint32_t)mem, &v) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(wasmext_instance_memory_grow(i, (uint32_t)mem, 1) == (int64_t)WASMEXT_TRAP_CLOSED);
    wasmext_instance_free(i);
    wasmext_store_free(s);
}

/* pins from several threads: the counts add up and the maximum comes back */
typedef struct { wasmext_instance *i; int mem; } work_t;
static THREAD_RESULT worker(void *arg) {
    work_t *w = (work_t *)arg;
    for (int n = 0; n < 2000; n++) {
        wasmext_instance_memory_pin(w->i, (uint32_t)w->mem, 1);
        wasmext_instance_memory_pin(w->i, (uint32_t)w->mem, 0);
    }
    return 0;
}
static void test_pins_from_threads(void) {
    enum { N = 4 };
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = wasmext_instance_new(s, BINDING, NULL);
    work_t w = {NULL, 0};
    thread_t t[N];
    wasmext_memory_view v;
    CHECK(wasmext_instance_instantiate(i) == 0);
    w.i = i; w.mem = export_of(i, "mem", WASMEXT_DESC_MEMORY);
    for (int k = 0; k < N; k++) thread_start(&t[k], worker, &w);
    for (int k = 0; k < N; k++) thread_join(t[k]);
    CHECK(wasmext_instance_memory(i, (uint32_t)w.mem, &v) == 0 && v.max_pages == 4); /* no pin is left */
    CHECK(wasmext_instance_memory_grow(i, (uint32_t)w.mem, 1) == 1);
    wasmext_instance_free(i);
    wasmext_store_free(s);
}

int main(void) {
#ifndef MEMORY64
    test_globals();
#endif
    test_memory();
    test_pins_from_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
