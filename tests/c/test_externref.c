/* externref in plain C (docs/step6_externref.md): the values the host gives the store, as arguments, results and answers of host functions; what is refused (a value of another store, a
   pointer that this API did not make); the release at the close, once; call_ref and a host function of a table with an externref in the signature; many threads giving values. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_table.h"

extern const wasmext_binding xr_binding, xu_binding, xf_binding, xs_binding, xc_binding, xt_binding;

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

/* tables of externref: one that a module exports and another imports, one of the host, the checks of what goes in, the element type that an import needs, and the limits */
static uint32_t table_import(wasmext_instance *i) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_imports; k++)
        if (d->imports[k].kind == WASMEXT_DESC_TABLE) return k;
    return 0xFFFFFFFFu;
}
static int bind_table(wasmext_instance *importer, const wasmext_export *rec) { return wasmext_instance_bind_export(importer, table_import(importer), rec); }
static void test_tables(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *x = wasmext_instance_new(s, &xr_binding, NULL), *u = wasmext_instance_new(s, &xu_binding, NULL), *u2 = wasmext_instance_new(s, &xu_binding, NULL);
    wasmext_instance *xf = wasmext_instance_new(s, &xf_binding, NULL), *xs = wasmext_instance_new(s, &xs_binding, NULL), *xc = wasmext_instance_new(s, &xc_binding, NULL);
    item_t a1 = {0, 1}, a2 = {0, 2}, b1 = {0, 3};
    wasmext_extern *e1, *e2, *foreign;
    wasmext_val a[2], r[1];
    wasmext_export rec;
    wasmext_tab *ht, *ft;
    visit_t v;
    void *p = (void *)1;
    uint32_t size, maximum, previous, T;
    char text[WASMEXT_STORE_ERROR_SIZE];
    memset(&v, 0, sizeof v);
    CHECK(wasmext_instance_bind_func(x, (uint32_t)import_of(x, "xenv", "visit"), visit, &v) == 0 && wasmext_instance_instantiate(x) == 0);
    e1 = give(s, &a1); e2 = give(s, &a2); foreign = give(other, &b1);
    T = (uint32_t)export_of(x, "t", WASMEXT_DESC_TABLE);
    /* the table that the module exports: the host and the module write and read the same slots */
    CHECK(wasmext_instance_table_size(x, T, &size, &maximum) == 0 && size == 4 && maximum == 8);
    CHECK(wasmext_instance_table_set_extern(x, T, 0, e1) == 0);
    a[0] = I32(0);
    CHECK(call(x, "tget", a, 1, r, 1) == 0 && r[0].type == 0x6F && r[0].as.ref == e1);
    a[0] = I32(1); a[1] = XREF(e2);
    CHECK(call(x, "tset", a, 2, NULL, 0) == 0 && wasmext_instance_table_get_extern(x, T, 1, &p) == 0 && p == e2);
    CHECK(wasmext_instance_table_get_extern(x, T, 2, &p) == 0 && p == NULL); /* empty */
    CHECK(wasmext_instance_table_set_extern(x, T, 1, NULL) == 0 && wasmext_instance_table_get_extern(x, T, 1, &p) == 0 && p == NULL);
    CHECK(wasmext_instance_table_get_extern(x, T, 4, &p) == WASMEXT_TAB_BOUNDS && wasmext_instance_table_set_extern(x, T, 4, e1) == WASMEXT_TAB_BOUNDS);
    /* what goes in is a reference of the store: a value of another store, a pointer that this API did not make */
    CHECK(wasmext_instance_table_set_extern(x, T, 2, foreign) == WASMEXT_TAB_WRONG_STORE);
    CHECK(wasmext_instance_table_set_extern(x, T, 2, (char *)e1 + 1) == WASMEXT_TAB_WRONG_STORE);
    CHECK(wasmext_instance_table_get_extern(x, T, 2, &p) == 0 && p == NULL);
    a[0] = I32(2); a[1] = XREF(foreign);
    CHECK(call(x, "tset", a, 2, NULL, 0) == WASMEXT_TAB_WRONG_STORE);
    /* the operations of the other kind are refused */
    {
        wasmext_funcref f;
        CHECK(wasmext_instance_table_get(x, T, 0, &f) == WASMEXT_TAB_WRONG_ELEM && wasmext_instance_table_set(x, T, 0, NULL) == WASMEXT_TAB_WRONG_ELEM);
    }
    /* growth is seen by both, and the maximum is kept by both */
    a[0] = I32(2);
    CHECK(call(x, "tgrow", a, 1, r, 1) == 0 && r[0].as.i32 == 4 && wasmext_instance_table_size(x, T, &size, NULL) == 0 && size == 6);
    CHECK(wasmext_instance_table_grow(x, T, 1, &previous) == 0 && previous == 6);
    CHECK(wasmext_instance_table_grow(x, T, 2, &previous) == WASMEXT_TAB_FULL);
    a[0] = I32(9);
    CHECK(call(x, "tgrow", a, 1, r, 1) == 0 && r[0].as.i32 == -1);
    /* another instance imports the table of the module: it is one table */
    CHECK(wasmext_instance_export_record(x, T, NULL, &rec) == 0 && rec.kind == WASMEXT_TABLE && (rec.flags & 32u) != 0 && rec.store == s);
    CHECK(bind_table(u, &rec) == 0 && wasmext_instance_instantiate(u) == 0);
    a[0] = I32(3); a[1] = XREF(e1);
    CHECK(call(u, "tset", a, 2, NULL, 0) == 0 && wasmext_instance_table_get_extern(x, T, 3, &p) == 0 && p == e1);
    CHECK(call(u, "tget", a, 1, r, 1) == 0 && r[0].as.ref == e1);
    CHECK(call(u, "tsize", NULL, 0, r, 1) == 0 && r[0].as.i32 == 7);
    a[0] = I32(20);
    CHECK(call(u, "tget", a, 1, r, 1) == (int)WASM_RT_TRAP_OOB); /* a trap of the module; the instances stay */
    CHECK(call(x, "tsize", NULL, 0, r, 1) == 0 && r[0].as.i32 == 7);
    /* an instance that fails to start and imports the table: the references in the table are not functions of it, and are all still there (the take-back of a failed start is for funcref tables) */
    {
        wasmext_instance *bad = wasmext_instance_new(s, &xt_binding, NULL);
        void *q = NULL;
        CHECK(wasmext_instance_export_record(x, T, NULL, &rec) == 0 && bind_table(bad, &rec) == 0);
        CHECK(wasmext_instance_instantiate(bad) == (int)WASM_RT_TRAP_UNREACHABLE);
        CHECK(wasmext_instance_table_get_extern(x, T, 3, &q) == 0 && q == e1);
        wasmext_instance_free(bad);
    }
    /* a table of the host */
    ht = wasmext_tab_new(s, 0x6F, 4, WASMEXT_TABLE_NO_MAXIMUM, NULL);
    ft = wasmext_tab_new(s, 0x70, 2, WASMEXT_TABLE_NO_MAXIMUM, NULL);
    CHECK(ht != NULL && ft != NULL && wasmext_tab_size(ht, &size, &maximum) == 0 && size == 4 && maximum == WASMEXT_TABLE_NO_MAXIMUM);
    CHECK(wasmext_tab_record(ht, NULL, &rec) == 0 && (rec.flags & 32u) != 0);
    CHECK(bind_table(u2, &rec) == 0 && wasmext_instance_instantiate(u2) == 0);
    a[0] = I32(0); a[1] = XREF(e2);
    CHECK(call(u2, "tset", a, 2, NULL, 0) == 0 && wasmext_tab_get_extern(ht, 0, &p) == 0 && p == e2);
    CHECK(wasmext_tab_set_extern(ht, 1, e1) == 0 && call(u2, "tget", &a[0], 1, r, 1) == 0 && r[0].as.ref == e2);
    a[0] = I32(1);
    CHECK(call(u2, "tget", a, 1, r, 1) == 0 && r[0].as.ref == e1);
    CHECK(wasmext_tab_set_extern(ht, 1, foreign) == WASMEXT_TAB_WRONG_STORE && wasmext_tab_set_extern(ht, 9, e1) == WASMEXT_TAB_BOUNDS && wasmext_tab_get_extern(ht, 9, &p) == WASMEXT_TAB_BOUNDS);
    CHECK(wasmext_tab_grow(ht, 3, &previous) == 0 && previous == 4 && call(u2, "tsize", NULL, 0, r, 1) == 0 && r[0].as.i32 == 7);
    {
        wasmext_funcref f;
        CHECK(wasmext_tab_get(ht, 0, &f) == WASMEXT_TAB_WRONG_ELEM && wasmext_tab_set(ht, 0, NULL) == WASMEXT_TAB_WRONG_ELEM);
        CHECK(wasmext_tab_get_extern(ft, 0, &p) == WASMEXT_TAB_WRONG_ELEM && wasmext_tab_set_extern(ft, 0, NULL) == WASMEXT_TAB_WRONG_ELEM);
    }
    /* the element type an import needs: an externref table for a funcref import, and the other way, are refused; so are the limits */
    CHECK(wasmext_instance_export_record(x, T, NULL, &rec) == 0);
    CHECK(bind_table(xf, &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "not of the type") != NULL);
    CHECK(wasmext_tab_record(ft, NULL, &rec) == 0 && (rec.flags & 32u) == 0);
    CHECK(bind_table(u, &rec) == WASMEXT_INST_TOO_LATE); /* u is made already */
    {
        wasmext_instance *u3 = wasmext_instance_new(s, &xu_binding, NULL);
        CHECK(bind_table(u3, &rec) == WASMEXT_INST_LINK_FAILED);
        wasmext_store_error(s, text, sizeof text);
        CHECK(strstr(text, "not of the type") != NULL);
        wasmext_instance_free(u3);
    }
    CHECK(wasmext_instance_export_record(x, T, NULL, &rec) == 0);
    CHECK(bind_table(xs, &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "needs at least 8") != NULL);
    CHECK(bind_table(xc, &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "allows 2") != NULL);
    /* the close releases each value once, and the tables answer the code of a closed store */
    CHECK(a1.released == 0 && a2.released == 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(a1.released == 1 && a2.released == 1);
    CHECK(wasmext_tab_get_extern(ht, 0, &p) == (int)WASMEXT_TRAP_CLOSED && wasmext_tab_set_extern(ht, 0, NULL) == (int)WASMEXT_TRAP_CLOSED && wasmext_tab_grow(ht, 1, NULL) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(wasmext_instance_table_get_extern(x, T, 0, &p) == (int)WASMEXT_TRAP_CLOSED);
    wasmext_store_free(s);
    wasmext_store_free(other);
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
    test_tables();
    test_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
