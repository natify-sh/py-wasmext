/* Tags between instances in plain C (docs/step7_tags.md, 7a): a module exports a tag and another imports it, so an exception thrown by a function of the one that is reached by the other
   (through a shared table) is caught by the other; a tag of the same signature that is another tag is not the same; the refusals. Modules: ta (the tag and a table), tb (imports both),
   tc (a tag of its own with the same signature), td (another tag), te (a tag import of another signature). */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_table.h"

extern const wasmext_binding ta_binding, tb_binding, tc_binding, td_binding, te_binding, th_binding;

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
static int export_of(wasmext_instance *i, const char *name, int kind) { return wasmext_instance_export_find(i, name, strlen(name), kind); }
static int import_of_kind(wasmext_instance *i, int kind) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_imports; k++)
        if (d->imports[k].kind == kind) return (int)k;
    return -1;
}
static int call(wasmext_instance *i, const char *name, const wasmext_val *a, uint32_t na, wasmext_val *r, uint32_t nr) {
    return wasmext_instance_call(i, (uint32_t)export_of(i, name, WASMEXT_DESC_FUNC), a, na, r, nr);
}
static int link_export(wasmext_instance *importer, int kind, wasmext_instance *exporter, const char *name) {
    wasmext_export rec;
    int rc = wasmext_instance_export_record(exporter, (uint32_t)export_of(exporter, name, kind), NULL, &rec);
    return rc != 0 ? rc : wasmext_instance_bind_export(importer, (uint32_t)import_of_kind(importer, kind), &rec);
}

static void test_tags(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *a = wasmext_instance_new(s, &ta_binding, NULL), *b = wasmext_instance_new(s, &tb_binding, NULL), *c = wasmext_instance_new(s, &tc_binding, NULL);
    wasmext_instance *d = wasmext_instance_new(s, &td_binding, NULL), *e = wasmext_instance_new(s, &te_binding, NULL), *b2 = wasmext_instance_new(s, &tb_binding, NULL);
    wasmext_instance *b3 = wasmext_instance_new(s, &tb_binding, NULL);
    wasmext_export rec;
    wasmext_val x, r[2];
    char text[WASMEXT_STORE_ERROR_SIZE];
    CHECK(wasmext_instance_instantiate(a) == 0 && wasmext_instance_instantiate(d) == 0);
    /* the record of a tag: its identity and the types of its values */
    CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "t", WASMEXT_DESC_TAG), NULL, &rec) == 0);
    CHECK(rec.kind == WASMEXT_TAG && rec.address != NULL && rec.signature != NULL && strcmp(rec.signature, "ij>") == 0 && rec.store == s);
    CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "call_slot", WASMEXT_DESC_FUNC), NULL, &rec) == 0 && rec.kind == WASMEXT_FUNC);
    /* b imports the tag and the table of a */
    CHECK(link_export(b, WASMEXT_DESC_TABLE, a, "tab") == 0 && link_export(b, WASMEXT_DESC_TAG, a, "t") == 0 && wasmext_instance_instantiate(b) == 0);
    x = I32(0);
    /* the function of a, called through the shared table, throws the tag; b catches it, with its values */
    CHECK(call(b, "catch_slot", &x, 1, r, 2) == 0 && r[0].type == 0x7F && r[0].as.i32 == 7 && r[1].type == 0x7E && r[1].as.i64 == 9);
    /* nobody catches it: the call ends with the trap of an exception that nothing caught, in the one that made the call too, and both stay usable */
    CHECK(call(a, "call_slot", &x, 1, NULL, 0) == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION);
    {   /* ... and the host asks which: the tag (the identity a record of the exported tag gives), the values, the bytes */
        wasmext_exception ex;
        wasmext_export trec;
        int32_t first;
        CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "t", WASMEXT_DESC_TAG), NULL, &trec) == 0);
        CHECK(wasmext_instance_exception(a, &ex) == 0 && ex.tag == trec.address && ex.tag_index >= 0 && ex.n_values == 2);
        CHECK(ex.values[0].type == 0x7F && ex.values[0].as.i32 == 7 && ex.values[1].type == 0x7E && ex.values[1].as.i64 == 9);
        CHECK(ex.size == 16);
        memcpy(&first, ex.raw, sizeof first);
        CHECK(first == 7);
    }
    CHECK(call(b, "call_slot", &x, 1, NULL, 0) == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION);
    {   /* b imports the tag: it knows it by the import, and reads the values the same */
        wasmext_exception ex;
        CHECK(wasmext_instance_exception(b, &ex) == 0 && ex.tag_index >= 0 && ex.n_values == 2 && ex.values[1].as.i64 == 9);
    }
    CHECK(call(b, "catch_slot", &x, 1, r, 2) == 0 && r[0].as.i32 == 7);
    /* a tag of another module with the same signature is another tag: c catches its own, and does not catch a's */
    CHECK(link_export(c, WASMEXT_DESC_TABLE, a, "tab") == 0 && wasmext_instance_instantiate(c) == 0);
    CHECK(call(c, "self_catch", NULL, 0, r, 1) == 0 && r[0].as.i32 == 11);
    CHECK(call(c, "catch_slot", &x, 1, r, 2) == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION);
    {   /* c does not know a's tag: it tells the tag and the bytes, and no values */
        wasmext_exception ex;
        wasmext_export trec;
        int32_t first;
        CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "t", WASMEXT_DESC_TAG), NULL, &trec) == 0);
        CHECK(wasmext_instance_exception(c, &ex) == 0 && ex.tag == trec.address && ex.tag_index == -1 && ex.n_values == 0 && ex.size == 16);
        memcpy(&first, ex.raw, sizeof first);
        CHECK(first == 7);
    }
    /* a tag that the module keeps to itself: the table of the tags of the build tells it (an index, no values to read: it has none) */
    CHECK(call(c, "throw_priv", NULL, 0, NULL, 0) == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION);
    {
        wasmext_exception ex;
        CHECK(wasmext_instance_exception(c, &ex) == 0 && ex.tag != NULL && ex.tag_index >= 0 && ex.size == 0 && ex.n_values == 0);
    }
    /* what an import does not accept: another signature, another kind of export */
    CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "t", WASMEXT_DESC_TAG), NULL, &rec) == 0);
    CHECK(wasmext_instance_bind_export(e, (uint32_t)import_of_kind(e, WASMEXT_DESC_TAG), &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "is a tag") != NULL && strstr(text, "i>") != NULL && strstr(text, "ij>") != NULL);
    CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "tab", WASMEXT_DESC_TABLE), NULL, &rec) == 0);
    CHECK(wasmext_instance_bind_export(e, (uint32_t)import_of_kind(e, WASMEXT_DESC_TAG), &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "the export given is not") != NULL);
    /* wasm2c reads an imported tag from a global: the program holds one tag for it. The same tag again is accepted; another one is not */
    CHECK(link_export(b2, WASMEXT_DESC_TABLE, a, "tab") == 0 && link_export(b2, WASMEXT_DESC_TAG, a, "t") == 0);
    CHECK(link_export(b3, WASMEXT_DESC_TAG, d, "t") == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "linked to another tag already") != NULL);
    /* a tag that is not linked is not run, even though the program holds a tag for the import from the other instances */
    CHECK(link_export(b3, WASMEXT_DESC_TABLE, a, "tab") == 0);
    CHECK(wasmext_instance_instantiate(b3) == (int)WASMEXT_TRAP_LINK_ERROR);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "is not bound") != NULL);
    CHECK(wasmext_instance_instantiate(b2) == 0 && call(b2, "catch_slot", &x, 1, r, 2) == 0 && r[1].as.i64 == 9);
    /* the close */
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "t", WASMEXT_DESC_TAG), NULL, &rec) == (int)WASMEXT_TRAP_CLOSED);
    wasmext_instance_free(b3);
    wasmext_instance_free(e);
    wasmext_store_free(s);
}

/* a thread that has had no exception has none to tell */
typedef struct { wasmext_instance *i; int got; } probe_t;
static THREAD_RESULT probe(void *arg) {
    probe_t *p = (probe_t *)arg;
    wasmext_exception ex;
    p->got = wasmext_instance_exception(p->i, &ex);
    return 0;
}

/* what a host function does: nothing, or throws the tag `tag` with `values`, or does it wrong */
typedef struct { int mode; wasmext_instance *self; const void *tag; const void *foreign_tag; const void *private_tag; int calls; } host_t;
static int host_h(void *user, const wasmext_val *args, wasmext_val *results) {
    host_t *h = (host_t *)user;
    wasmext_val v[2];
    (void)args; (void)results;
    h->calls++;
    switch (h->mode) {
        case 0: return 0;
        case 1: v[0] = I32(21); v[1] = I64(22); { int rc = wasmext_instance_throw(h->self, h->tag, v, 2); return rc != 0 ? rc : WASMEXT_HOST_THROW; }
        case 2: v[0] = I32(1); v[1] = I32(2); { int rc = wasmext_instance_throw(h->self, h->tag, v, 2); return rc != 0 ? rc : WASMEXT_HOST_THROW; } /* the wrong types */
        case 3: v[0] = I32(1); v[1] = I64(2); { int rc = wasmext_instance_throw(h->self, h->foreign_tag, v, 2); return rc != 0 ? rc : WASMEXT_HOST_THROW; } /* a tag the module has not */
        case 4: return WASMEXT_HOST_THROW; /* nothing was made */
        case 5: v[0] = I32(77); { int rc = wasmext_instance_throw(h->self, h->private_tag, v, 1); return rc != 0 ? rc : WASMEXT_HOST_THROW; } /* a tag the module keeps to itself */
        default: return 0;
    }
}
static void host_typed(void *user, int *trapped) {
    host_t *h = (host_t *)user;
    wasmext_val v[2];
    h->calls++;
    v[0] = I32(31); v[1] = I64(32);
    *trapped = wasmext_instance_throw(h->self, h->tag, v, 2);
    if (*trapped == 0) *trapped = WASMEXT_HOST_THROW;
}

static void test_throw(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *a = wasmext_instance_new(s, &ta_binding, NULL), *h = wasmext_instance_new(s, &th_binding, NULL), *h2 = wasmext_instance_new(s, &th_binding, NULL);
    wasmext_export trec, arec;
    host_t hs, hs2;
    wasmext_val r[2];
    wasmext_exception ex;
    memset(&hs, 0, sizeof hs); memset(&hs2, 0, sizeof hs2);
    CHECK(wasmext_instance_instantiate(a) == 0);
    CHECK(wasmext_instance_bind_func(h, (uint32_t)import_of_kind(h, WASMEXT_DESC_FUNC), host_h, &hs) == 0 && wasmext_instance_instantiate(h) == 0);
    CHECK(wasmext_instance_bind_typed(h2, (uint32_t)import_of_kind(h2, WASMEXT_DESC_FUNC), (void *)host_typed, &hs2) == 0 && wasmext_instance_instantiate(h2) == 0);
    CHECK(wasmext_instance_export_record(h, (uint32_t)export_of(h, "t", WASMEXT_DESC_TAG), NULL, &trec) == 0);
    CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "t", WASMEXT_DESC_TAG), NULL, &arec) == 0);
    hs.self = h; hs.tag = trec.address; hs.foreign_tag = arec.address;
    hs2.self = h2; hs2.tag = trec.address;
    /* the host function does not throw */
    hs.mode = 0;
    CHECK(call(h, "run", NULL, 0, r, 2) == 0 && r[0].as.i32 == -1);
    /* it throws the tag of the module: the `catch` of the module catches it, with the values */
    hs.mode = 1;
    CHECK(call(h, "run", NULL, 0, r, 2) == 0 && r[0].type == 0x7F && r[0].as.i32 == 21 && r[1].type == 0x7E && r[1].as.i64 == 22);
    /* ... and where nothing catches it the call ends with the trap of an exception that nothing caught, which the host reads */
    CHECK(call(h, "plain", NULL, 0, NULL, 0) == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION);
    CHECK(wasmext_instance_exception(h, &ex) == 0 && ex.tag == trec.address && ex.n_values == 2 && ex.values[0].as.i32 == 21 && ex.values[1].as.i64 == 22);
    /* the typed shape throws the same way */
    CHECK(call(h2, "run", NULL, 0, r, 2) == 0 && r[0].as.i32 == 31 && r[1].as.i64 == 32 && hs2.calls == 1);
    /* what is wrong is a failure of the host (a trap), not an exception: the wrong types, a tag the module does not have, and an answer with nothing made */
    hs.mode = 2;
    CHECK(call(h, "run", NULL, 0, r, 2) == (int)WASMEXT_TRAP_HOST);
    hs.mode = 3;
    CHECK(call(h, "run", NULL, 0, r, 2) == (int)WASMEXT_TRAP_HOST);
    hs.mode = 4;
    CHECK(call(h, "run", NULL, 0, r, 2) == (int)WASMEXT_TRAP_HOST);
    CHECK(wasmext_instance_throw(h, trec.address, NULL, 0) == WASMEXT_INST_BAD_ARGS); /* the number of values */
    {   /* a tag the module neither exports nor imports (the one of a): it has no way to make the payload */
        wasmext_val two[2];
        two[0] = I32(1); two[1] = I64(2);
        CHECK(wasmext_instance_throw(h, arec.address, two, 2) == WASMEXT_INST_UNDECLARED_TYPE);
        CHECK(wasmext_instance_throw(h, trec.address, two, 2) == 0); /* its own tag is made (and is dropped by the next throw or the next trap) */
        wasmext_pending_throw_.tag = NULL;
    }
    CHECK(wasmext_instance_throw(h, NULL, NULL, 0) == WASMEXT_INST_BAD_ARGS);
    hs.mode = 0;
    CHECK(call(h, "run", NULL, 0, r, 2) == 0 && r[0].as.i32 == -1);
    /* a tag that the module keeps to itself: its exception is read with its values, and the host throws it by the identity it learned from there */
    {
        wasmext_val p = I32(5);
        CHECK(call(h, "throw_p", &p, 1, NULL, 0) == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION);
        CHECK(wasmext_instance_exception(h, &ex) == 0 && ex.tag_index >= 0 && ex.n_values == 1 && ex.values[0].as.i32 == 5);
        hs.private_tag = ex.tag;
        hs.mode = 5;
        CHECK(call(h, "catch_p", NULL, 0, r, 1) == 0 && r[0].as.i32 == 77);
        hs.mode = 0;
        CHECK(call(h, "catch_p", NULL, 0, r, 1) == 0 && r[0].as.i32 == -1);
    }
    /* a host function that is an element of a table: it is called by call_ref, throws, and the call ends with the trap of an uncaught exception */
    {
        wasmext_funcref f;
        static const uint8_t T_NONE[] = {0};
        host_t ht;
        memset(&ht, 0, sizeof ht);
        ht.self = h; ht.tag = trec.address; ht.mode = 1;
        CHECK(wasmext_instance_host_funcref(h, T_NONE, 0, T_NONE, 0, host_h, &ht, NULL, &f) == 0);
        CHECK(wasmext_instance_call_ref(h, &f, NULL, 0, NULL, 0) == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION);
        CHECK(wasmext_instance_exception(h, &ex) == 0 && ex.n_values == 2 && ex.values[0].as.i32 == 21);
    }
    /* a thread that has had no exception has none to tell */
    {
        probe_t p;
        thread_t t;
        p.i = h; p.got = 99;
        thread_start(&t, probe, &p);
        thread_join(t);
        CHECK(p.got == WASMEXT_INST_NO_EXCEPTION);
    }
    wasmext_store_free(s);
}

int main(void) {
    test_tags();
    test_throw();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
