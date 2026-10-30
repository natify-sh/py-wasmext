/* externref in plain C (docs/step6_externref.md): the values the host gives the store, as arguments, results and answers of host functions; what is refused (a value of another store, a
   pointer that this API did not make); the release at the close, once; call_ref and a host function of a table with an externref in the signature; many threads giving values. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_table.h"

extern const wasmext_binding xr_binding;

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
static wasmext_val F64(double v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7C; x.as.f64 = v; return x; }
static wasmext_val XREF(void *p) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x6F; x.as.ref = p; return x; }
static int export_of(wasmext_instance *i, const char *name, int kind) { return wasmext_instance_export_find(i, name, strlen(name), kind); }
static int import_of(wasmext_instance *i, const char *module, const char *name) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_imports; k++)
        if (d->imports[k].module.n == strlen(module) && memcmp(d->imports[k].module.p, module, d->imports[k].module.n) == 0 &&
            d->imports[k].name.n == strlen(name) && memcmp(d->imports[k].name.p, name, d->imports[k].name.n) == 0)
            return (int)k;
    return -1;
}
static int call(wasmext_instance *i, const char *name, const wasmext_val *a, uint32_t na, wasmext_val *r, uint32_t nr) {
    return wasmext_instance_call(i, (uint32_t)export_of(i, name, WASMEXT_DESC_FUNC), a, na, r, nr);
}

typedef struct { int released; int id; } item_t;
static void item_release(void *user) { ((item_t *)user)->released++; }
static wasmext_extern *give(wasmext_store *s, item_t *it) {
    wasmext_extern *e = NULL;
    return wasmext_extern_new(s, it, item_release, &e) == 0 ? e : NULL;
}

/* what the host function `xenv.visit` does with the reference it is given */
typedef struct { int mode; int calls; void *seen; void *give; } visit_t;
static int visit(void *user, const wasmext_val *args, wasmext_val *results) {
    visit_t *v = (visit_t *)user;
    v->calls++;
    if (args[0].type == 0x6F) v->seen = args[0].as.ref;
    switch (v->mode) {
        case 0: results[0].type = 0x6F; results[0].as.ref = args[0].as.ref; return 0; /* the same reference back */
        case 1: results[0].type = 0x6F; results[0].as.ref = NULL; return 0;          /* null */
        case 2: results[0].type = 0x6F; results[0].as.ref = v->give; return 0;       /* what the test chose */
        case 3: results[0].type = 0x7F; return 0;                                    /* a value of another type */
        default: return 77;                                                          /* a failure of the host */
    }
}

static void test_values(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *x = wasmext_instance_new(s, &xr_binding, NULL);
    item_t a1 = {0, 1}, a2 = {0, 2}, b1 = {0, 3};
    wasmext_extern *e1, *e2, *foreign;
    wasmext_val a[3], r[2];
    visit_t v;
    int rc;
    memset(&v, 0, sizeof v);
    CHECK(wasmext_instance_bind_typed(x, (uint32_t)import_of(x, "xenv", "visit"), (void *)visit, &v) == WASMEXT_INST_UNSUPPORTED); /* a reference: only the uniform shape */
    CHECK(wasmext_instance_bind_func(x, (uint32_t)import_of(x, "xenv", "visit"), visit, &v) == 0 && wasmext_instance_instantiate(x) == 0);
    e1 = give(s, &a1); e2 = give(s, &a2); foreign = give(other, &b1);
    CHECK(e1 != NULL && e2 != NULL && foreign != NULL && wasmext_extern_user(e1) == &a1 && wasmext_extern_user(NULL) == NULL);
    /* the identity: the same reference comes out as went in, and the host reads its value */
    a[0] = XREF(e1);
    CHECK(call(x, "id", a, 1, r, 1) == 0 && r[0].type == 0x6F && r[0].as.ref == e1 && wasmext_extern_user(r[0].as.ref) == &a1);
    a[0] = XREF(NULL);
    CHECK(call(x, "id", a, 1, r, 1) == 0 && r[0].as.ref == NULL);
    CHECK(call(x, "isnull", a, 1, r, 1) == 0 && r[0].as.i32 == 1);
    a[0] = XREF(e1);
    CHECK(call(x, "isnull", a, 1, r, 1) == 0 && r[0].as.i32 == 0);
    /* several results in order, and references among other types */
    a[0] = XREF(e1); a[1] = XREF(e2);
    CHECK(call(x, "pair", a, 2, r, 2) == 0 && r[0].as.ref == e2 && r[1].as.ref == e1);
    a[0] = I32(1); a[1] = XREF(e2); a[2] = F64(2.5);
    CHECK(call(x, "mixed", a, 3, r, 2) == 0 && r[0].type == 0x7C && r[0].as.f64 == 2.5 && r[1].type == 0x6F && r[1].as.ref == e2);
    /* a value of another store, and a pointer that this API did not make: refused before the call */
    a[0] = XREF(foreign);
    CHECK(call(x, "id", a, 1, r, 1) == WASMEXT_TAB_WRONG_STORE);
    {
        int not_a_reference = 5;
        a[0] = XREF(&not_a_reference);
        CHECK(call(x, "id", a, 1, r, 1) == WASMEXT_TAB_WRONG_STORE);
    }
    a[0] = XREF((char *)e1 + 1);
    CHECK(call(x, "id", a, 1, r, 1) == WASMEXT_TAB_WRONG_STORE);
    /* the host function is given the reference and answers one */
    a[0] = XREF(e1);
    CHECK(call(x, "via", a, 1, r, 1) == 0 && v.calls == 1 && v.seen == e1 && r[0].as.ref == e1);
    a[0] = XREF(NULL);
    CHECK(call(x, "via", a, 1, r, 1) == 0 && v.seen == NULL && r[0].as.ref == NULL);
    v.mode = 1; a[0] = XREF(e1);
    CHECK(call(x, "via", a, 1, r, 1) == 0 && r[0].as.ref == NULL);
    v.mode = 2; v.give = e2;
    CHECK(call(x, "via", a, 1, r, 1) == 0 && r[0].as.ref == e2);
    /* ... an answer of another store, a forged one, a value of another type, a failure: the call traps, and the instance is usable after it */
    v.give = foreign;
    CHECK(call(x, "via", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    v.give = (char *)e2 + 1;
    CHECK(call(x, "via", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    v.mode = 3;
    CHECK(call(x, "via", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    v.mode = 4;
    CHECK(call(x, "via", a, 1, r, 1) != 0);
    v.mode = 0;
    CHECK(call(x, "via", a, 1, r, 1) == 0 && r[0].as.ref == e1);
    /* call_ref of a function with an externref in the signature, and a host function of that type as a funcref */
    {
        wasmext_funcref id, hf;
        static const uint8_t T_X[] = {0x6F};
        CHECK(wasmext_instance_funcref(x, (uint32_t)export_of(x, "id", WASMEXT_DESC_FUNC), &id) == 0);
        a[0] = XREF(e2);
        CHECK(wasmext_instance_call_ref(x, &id, a, 1, r, 1) == 0 && r[0].as.ref == e2);
        a[0] = XREF(foreign);
        CHECK(wasmext_instance_call_ref(x, &id, a, 1, r, 1) == WASMEXT_TAB_WRONG_STORE);
        CHECK(wasmext_instance_host_funcref(x, T_X, 1, T_X, 1, visit, &v, NULL, &hf) == 0);
        a[0] = XREF(e1);
        v.mode = 0;
        CHECK(wasmext_instance_call_ref(x, &hf, a, 1, r, 1) == 0 && r[0].as.ref == e1);
        v.mode = 2; v.give = foreign;
        CHECK(wasmext_instance_call_ref(x, &hf, a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    }
    /* the close: each value is released once, and not before; then nothing is given or called */
    CHECK(a1.released == 0 && a2.released == 0 && b1.released == 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(a1.released == 1 && a2.released == 1 && b1.released == 0);
    a[0] = XREF(e1);
    CHECK(call(x, "id", a, 1, r, 1) == (int)WASMEXT_TRAP_CLOSED);
    {
        wasmext_extern *late = NULL;
        rc = wasmext_extern_new(s, &a1, item_release, &late);
        CHECK(rc == (int)WASMEXT_TRAP_CLOSED && late == NULL);
    }
    wasmext_store_free(s);
    CHECK(a1.released == 1 && a2.released == 1); /* not again at the free */
    CHECK(wasmext_store_close(other) == WASMEXT_STORE_OK && b1.released == 1);
    wasmext_store_free(other);
    {
        wasmext_extern *none = NULL;
        CHECK(wasmext_extern_new(NULL, &a1, NULL, &none) == WASMEXT_INST_BAD_ARGS);
    }
}

/* many threads give the store values at once: each is a member, each is released at the close */
typedef struct { wasmext_store *s; item_t *items; int n; int failed; } work_t;
static THREAD_RESULT worker(void *arg) {
    work_t *w = (work_t *)arg;
    for (int k = 0; k < w->n; k++) {
        wasmext_extern *e = NULL;
        if (wasmext_extern_new(w->s, &w->items[k], item_release, &e) != 0 || e == NULL || wasmext_extern_user(e) != &w->items[k] || wasmext_extern_check_(w->s, e) != 0) w->failed = 1;
    }
    return 0;
}
static void test_threads(void) {
    enum { N = 4, PER = 400 };
    wasmext_store *s = wasmext_store_new();
    static item_t items[N][PER];
    work_t w[N];
    thread_t th[N];
    memset(items, 0, sizeof items);
    for (int k = 0; k < N; k++) { w[k].s = s; w[k].items = items[k]; w[k].n = PER; w[k].failed = 0; thread_start(&th[k], worker, &w[k]); }
    for (int k = 0; k < N; k++) { thread_join(th[k]); CHECK(!w[k].failed); }
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    {
        int all = 1;
        for (int k = 0; k < N; k++)
            for (int j = 0; j < PER; j++)
                if (items[k][j].released != 1) all = 0;
        CHECK(all);
    }
    wasmext_store_free(s);
}

int main(void) {
    test_values();
    test_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
