/* Tests of wasmext_instance.h in plain C over a module built by wasm2c and its generated binding: no Python. The module is MODULE (a prefix), built from
   tests/test_instance_core.py. Exit 0 and "ok" when all pass. */
#include <stdio.h>
#include "wasmext_errors.h"
#define WASMEXT_DEFINE_THREAD_STATE
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
#include <pthread.h>
typedef pthread_t thread_t;
#define THREAD_RESULT void *
static void thread_start(thread_t *t, THREAD_RESULT (*f)(void *), void *arg) { pthread_create(t, NULL, f, arg); }
static void thread_join(thread_t t) { pthread_join(t, NULL); }
#endif

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static wasmext_val I32(int32_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7F; x.as.i32 = v; return x; }
static wasmext_val I64(int64_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7E; x.as.i64 = v; return x; }

static int find(wasmext_instance *i, const char *name) { return wasmext_instance_export_find(i, name, strlen(name), WASMEXT_DESC_FUNC); }

static void test_calls(void) {
    wasmext_store *s = wasmext_store_new();
    int err = -1;
    wasmext_instance *i = wasmext_instance_new(s, BINDING, &err);
    wasmext_val a[2], r[2];
    CHECK(i != NULL && err == 0);
    CHECK(BINDING->descriptor->n_exports >= 5);
    CHECK(find(i, "add") >= 0 && find(i, "absent") == -1);
    /* a call before the start function has run */
    a[0] = I32(1); a[1] = I32(2);
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "add"), a, 2, r, 1) == WASMEXT_INST_NOT_INSTANTIATED);
    CHECK(wasmext_instance_instantiate(i) == 0);
    CHECK(wasmext_instance_instantiate(i) == 0); /* twice is fine */
    /* the start function ran: the global it increments is 6 */
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "g"), NULL, 0, r, 1) == 0 && r[0].type == 0x7F && r[0].as.i32 == 6);
    /* add */
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "add"), a, 2, r, 1) == 0 && r[0].type == 0x7F && r[0].as.i32 == 3);
    a[0] = I32(-5); a[1] = I32(2);
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "add"), a, 2, r, 1) == 0 && r[0].as.i32 == -3);
    /* a trap: the code, and the instance is usable after it */
    a[0] = I32(7); a[1] = I32(0);
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "div"), a, 2, r, 1) == (int)WASM_RT_TRAP_DIV_BY_ZERO);
    CHECK(wasmext_instance_status(i) == (int)WASM_RT_TRAP_DIV_BY_ZERO);
    CHECK(wasmext_error_describe(wasmext_instance_status(i)).kind == WASMEXT_ERR_TRAP);
    a[0] = I32(7); a[1] = I32(2);
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "div"), a, 2, r, 1) == 0 && r[0].as.i32 == 3 && wasmext_instance_status(i) == 0);
    a[0] = I32(INT32_MIN); a[1] = I32(-1);
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "div"), a, 2, r, 1) == (int)WASM_RT_TRAP_INT_OVERFLOW);
    /* several results, in the order of the signature */
    a[0] = I32(1); a[1] = I64(9);
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "swap"), a, 2, r, 2) == 0);
    CHECK(r[0].type == 0x7E && r[0].as.i64 == 9 && r[1].type == 0x7F && r[1].as.i32 == 1);
    /* no result */
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "nothing"), NULL, 0, NULL, 0) == 0);
    /* floats */
    {
        wasmext_val f[2];
        memset(f, 0, sizeof f);
        f[0].type = 0x7D; f[0].as.f32 = 1.5f; f[1].type = 0x7C; f[1].as.f64 = 2.25;
        CHECK(wasmext_instance_call(i, (uint32_t)find(i, "mix"), f, 2, r, 1) == 0 && r[0].type == 0x7C && r[0].as.f64 == 3.75);
    }
    /* a call that cannot be made is not a trap */
    a[0] = I32(1);
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "add"), a, 1, r, 1) == WASMEXT_INST_BAD_ARGS);  /* too few */
    a[1] = I64(2);
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "add"), a, 2, r, 1) == WASMEXT_INST_BAD_ARGS);  /* wrong type */
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "add"), a, 2, r, 2) == WASMEXT_INST_BAD_ARGS);  /* wrong number of results */
    CHECK(wasmext_instance_call(i, 999, a, 2, r, 1) == WASMEXT_INST_BAD_EXPORT);
    CHECK(wasmext_instance_export_find(i, "mem", 3, WASMEXT_DESC_MEMORY) >= 0);
    CHECK(wasmext_instance_call(i, (uint32_t)wasmext_instance_export_find(i, "mem", 3, WASMEXT_DESC_MEMORY), NULL, 0, r, 0) == WASMEXT_INST_BAD_EXPORT);
    /* the store closed: a call is refused with the code of a closed store, nothing runs */
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    a[0] = I32(1); a[1] = I32(2);
    CHECK(wasmext_instance_call(i, (uint32_t)find(i, "add"), a, 2, r, 1) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(wasmext_error_describe((int)WASMEXT_TRAP_CLOSED).kind == WASMEXT_ERR_CLOSED);
    wasmext_instance_free(i);
    CHECK(wasmext_instance_new(s, BINDING, &err) == NULL && err == EBADF); /* no instance in a closed store */
    wasmext_store_free(s);
}

static void test_arguments_of_new(void) {
    wasmext_store *s = wasmext_store_new();
    int err = 0;
    CHECK(wasmext_instance_new(NULL, BINDING, &err) == NULL && err == EINVAL);
    CHECK(wasmext_instance_new(s, NULL, &err) == NULL && err == EINVAL);
    wasmext_instance_free(NULL);
    wasmext_store_free(s);
}

/* many threads call one instance: each sets the runtime up for itself, the store counts the calls, and a trap in one thread is the trap of that call */
typedef struct { wasmext_instance *i; int failed; } work_t;
static THREAD_RESULT worker(void *arg) {
    work_t *w = (work_t *)arg;
    uint32_t add = (uint32_t)find(w->i, "add"), div = (uint32_t)find(w->i, "div");
    for (int n = 0; n < 2000; n++) {
        wasmext_val a[2], r[1];
        a[0] = I32(n); a[1] = I32(1);
        if (wasmext_instance_call(w->i, add, a, 2, r, 1) != 0 || r[0].as.i32 != n + 1) w->failed = 1;
        a[1] = I32(0);
        if (wasmext_instance_call(w->i, div, a, 2, r, 1) != (int)WASM_RT_TRAP_DIV_BY_ZERO) w->failed = 1;
    }
    wasmext_thread_free();
    return 0;
}
static void test_threads(void) {
    enum { N = 4 };
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = wasmext_instance_new(s, BINDING, NULL);
    work_t w[N];
    thread_t t[N];
    CHECK(wasmext_instance_instantiate(i) == 0);
    for (int k = 0; k < N; k++) { w[k].i = i; w[k].failed = 0; thread_start(&t[k], worker, &w[k]); }
    for (int k = 0; k < N; k++) { thread_join(t[k]); CHECK(!w[k].failed); }
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK); /* no call is left in flight */
    wasmext_instance_free(i);
    wasmext_store_free(s);
}

int main(void) {
    test_calls();
    test_arguments_of_new();
    test_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
