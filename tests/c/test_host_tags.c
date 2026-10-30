/* Tags made by the host belong to the store (docs/specs/S0008-shared-store.md, 8a-3): modules import a tag that `wasmext_tag_new` made, one throws it and another catches it, the host throws it
   from a host function, the refusals; the process-global cell of an imported tag (D34) is cleared when the store closes, only if it still holds that tag; while a store holds the tag a second
   tag for the same import name is refused with the reason; a tag of a module (static in the program) is not cleared. Modules: ha (throws), hb (catches through a table), hh (a host function
   in between), hs (another signature), hx, hy, hz (a tag import each, catch their own throw), ta and tb (a tag of a module). */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_table.h"

extern const wasmext_binding ha_binding, hb_binding, hh_binding, hs_binding, hx_binding, hy_binding, hz_binding, ta_binding, tb_binding;

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

static const uint8_t TYPES_IJ[] = {0x7F, 0x7E};

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
static int bind_tag(wasmext_instance *i, const wasmext_export *rec) { return wasmext_instance_bind_export(i, (uint32_t)import_of_kind(i, WASMEXT_DESC_TAG), rec); }
/* the global that the module reads for its tag import: the cell of D34 */
static void *volatile *cell_of(wasmext_instance *i) { return (void *volatile *)i->binding->ref_slot(i->module, (uint32_t)import_of_kind(i, WASMEXT_DESC_TAG)); }
static int self_catch(wasmext_instance *i) {
    wasmext_val r;
    memset(&r, 0, sizeof r);
    return call(i, "self_catch", NULL, 0, &r, 1) == 0 ? r.as.i32 : -999999;
}

/* what the host function of hh does: throws the tag */
typedef struct { wasmext_instance *self; const void *tag; } host_t;
static int host_h(void *user, const wasmext_val *args, wasmext_val *results) {
    host_t *h = (host_t *)user;
    wasmext_val v[2];
    int rc;
    (void)args; (void)results;
    v[0] = I32(21);
    v[1] = I64(22);
    rc = wasmext_instance_throw(h->self, h->tag, v, 2);
    return rc != 0 ? rc : WASMEXT_HOST_THROW;
}

/* one store: a tag of the host is imported by modules that throw it, catch it (through a table of the thrower), and have it thrown by a host function; the refusals */
static void test_one_store(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *a = wasmext_instance_new(s, &ha_binding, NULL), *b = wasmext_instance_new(s, &hb_binding, NULL), *h = wasmext_instance_new(s, &hh_binding, NULL);
    wasmext_instance *bad = wasmext_instance_new(s, &hs_binding, NULL), *foreign = wasmext_instance_new(other, &ha_binding, NULL);
    wasmext_export rec, rec2, none;
    wasmext_exception ex;
    wasmext_val x, r[2];
    host_t hs;
    char text[WASMEXT_STORE_ERROR_SIZE];
    uint8_t bad_type[] = {0x7F, 0x42};
    CHECK(wasmext_tag_new(s, TYPES_IJ, 2, &rec) == 0);
    CHECK(rec.kind == WASMEXT_TAG && rec.address != NULL && rec.signature != NULL && strcmp(rec.signature, "ij>") == 0 && rec.store == s && rec.artifact == WASMEXT_ARTIFACT);
    CHECK(wasmext_tag_new(s, TYPES_IJ, 2, &rec2) == 0 && rec2.address != rec.address); /* a tag made again is another tag */
    /* the arguments */
    CHECK(wasmext_tag_new(NULL, TYPES_IJ, 2, &none) == WASMEXT_INST_BAD_ARGS && wasmext_tag_new(s, TYPES_IJ, 2, NULL) == WASMEXT_INST_BAD_ARGS);
    CHECK(wasmext_tag_new(s, NULL, 2, &none) == WASMEXT_INST_BAD_ARGS && wasmext_tag_new(s, bad_type, 2, &none) == WASMEXT_INST_BAD_ARGS);
    CHECK(wasmext_tag_new(s, TYPES_IJ, 63, &none) == WASMEXT_INST_BAD_ARGS);
    CHECK(wasmext_tag_new(s, NULL, 0, &none) == 0 && strcmp(none.signature, ">") == 0);
    /* ha throws it, hb catches it through the table of ha, with its values */
    CHECK(bind_tag(a, &rec) == 0 && wasmext_instance_instantiate(a) == 0);
    CHECK(bind_tag(b, &rec) == 0 && link_export(b, WASMEXT_DESC_TABLE, a, "tab") == 0 && wasmext_instance_instantiate(b) == 0);
    CHECK(*cell_of(a) == rec.address && *cell_of(b) == rec.address);
    /* the tag remembers each cell once: the same import bound again, or by another instance of the module, adds none */
    {
        wasmext_host_tag *ht = (wasmext_host_tag *)rec.address;
        wasmext_instance *a2 = wasmext_instance_new(s, &ha_binding, NULL), *b2 = wasmext_instance_new(s, &hb_binding, NULL);
        CHECK(ht->n_cells == 2); /* hga.t and hgb.t */
        CHECK(bind_tag(a2, &rec) == 0 && bind_tag(a2, &rec) == 0 && bind_tag(b2, &rec) == 0);
        CHECK(ht->n_cells == 2);
    }
    x = I32(0);
    CHECK(call(b, "catch_slot", &x, 1, r, 2) == 0 && r[0].type == 0x7F && r[0].as.i32 == 7 && r[1].type == 0x7E && r[1].as.i64 == 9);
    /* nobody catches it: the host reads the exception, its tag is the identity of the record */
    CHECK(call(a, "throw_it", NULL, 0, NULL, 0) == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION);
    CHECK(wasmext_instance_exception(a, &ex) == 0 && ex.tag == rec.address && ex.tag_index >= 0 && ex.n_values == 2 && ex.values[0].as.i32 == 5 && ex.values[1].as.i64 == 6);
    /* a host function throws it, hh catches it */
    memset(&hs, 0, sizeof hs);
    hs.self = h;
    hs.tag = rec.address;
    CHECK(bind_tag(h, &rec) == 0);
    CHECK(wasmext_instance_bind_func(h, (uint32_t)import_of_kind(h, WASMEXT_DESC_FUNC), host_h, &hs) == 0 && wasmext_instance_instantiate(h) == 0);
    CHECK(((wasmext_host_tag *)rec.address)->n_cells == 3);
    CHECK(call(h, "run", NULL, 0, r, 2) == 0 && r[0].as.i32 == 21 && r[1].as.i64 == 22);
    /* another signature: refused with both signatures */
    CHECK(bind_tag(bad, &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "is a tag") != NULL && strstr(text, "i>") != NULL && strstr(text, "ij>") != NULL);
    CHECK(*cell_of(bad) == NULL); /* nothing was set */
    /* a tag of another store: refused, as every record of another store */
    CHECK(bind_tag(foreign, &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(other, text, sizeof text);
    CHECK(strstr(text, "another store") != NULL);
    /* the close clears the cell, a closed store makes no tag */
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(*cell_of(a) == NULL && *cell_of(b) == NULL && *cell_of(h) == NULL);
    CHECK(wasmext_tag_new(s, TYPES_IJ, 2, &none) == (int)WASMEXT_TRAP_CLOSED);
    /* the record of a closed store is not read (its signature was freed by the close), by bind_export or by the link of a cell: nothing is set */
    CHECK(bind_tag(bad, &rec) == (int)WASMEXT_TRAP_CLOSED && *cell_of(bad) == NULL);
    {
        int host = 0, set = 0;
        char got[64];
        CHECK(wasmext_tag_link_(s, rec.address, "ij>", "ij>", got, sizeof got, (void **)cell_of(a), &host, &set) == WASMEXT_STORE_CLOSED && host == 0 && set == 0 && *cell_of(a) == NULL);
    }
    CHECK(wasmext_store_free(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_free(other) == WASMEXT_STORE_OK);
}

/* the cell: set once, held while the store lives, cleared at the close; a second tag for the name is refused with the reason while it is held, and may be linked once the first is let go */
static void test_cell(void) {
    wasmext_store *s1 = wasmext_store_new(), *s2 = wasmext_store_new(), *s3 = wasmext_store_new();
    wasmext_instance *x1 = wasmext_instance_new(s1, &hx_binding, NULL), *x1b = wasmext_instance_new(s1, &hx_binding, NULL);
    wasmext_instance *x2 = wasmext_instance_new(s2, &hx_binding, NULL), *x3 = wasmext_instance_new(s3, &hx_binding, NULL);
    wasmext_export t1, t1b, t2, t3;
    void *volatile *cell = cell_of(x1);
    char text[WASMEXT_STORE_ERROR_SIZE];
    CHECK(*cell == NULL);
    CHECK(wasmext_tag_new(s1, TYPES_IJ, 2, &t1) == 0 && wasmext_tag_new(s1, TYPES_IJ, 2, &t1b) == 0 && wasmext_tag_new(s2, TYPES_IJ, 2, &t2) == 0 && wasmext_tag_new(s3, TYPES_IJ, 2, &t3) == 0);
    CHECK(bind_tag(x1, &t1) == 0 && wasmext_instance_instantiate(x1) == 0 && *cell == t1.address && self_catch(x1) == 11);
    CHECK(bind_tag(x1b, &t1) == 0); /* the same tag again, from another instance */
    /* a second tag of the same store, and a tag of another live store, for the same import name: refused, with the reason */
    CHECK(bind_tag(x1b, &t1b) == WASMEXT_INST_TAG_HELD);
    wasmext_store_error(s1, text, sizeof text);
    CHECK(strstr(text, "hgx.t") != NULL && strstr(text, "another tag holds the import already") != NULL && strstr(text, "one tag for each import name") != NULL);
    CHECK(bind_tag(x2, &t2) == WASMEXT_INST_TAG_HELD);
    wasmext_store_error(s2, text, sizeof text);
    CHECK(strstr(text, "hgx.t") != NULL && strstr(text, "another tag holds the import already") != NULL && strstr(text, "until the store that holds it is closed") != NULL);
    CHECK(*cell == t1.address && self_catch(x1) == 11); /* the refusal changed nothing */
    /* the store that holds it is freed: the cell is empty, and nothing is refused any more */
    CHECK(wasmext_store_free(s1) == WASMEXT_STORE_OK);
    CHECK(*cell == NULL);
    CHECK(bind_tag(x3, &t3) == 0 && wasmext_instance_instantiate(x3) == 0 && *cell == t3.address && self_catch(x3) == 11);
    CHECK(wasmext_store_free(s3) == WASMEXT_STORE_OK && *cell == NULL);
    CHECK(bind_tag(x2, &t2) == 0 && wasmext_instance_instantiate(x2) == 0 && *cell == t2.address && self_catch(x2) == 11); /* the refused store may link now */
    CHECK(wasmext_store_free(s2) == WASMEXT_STORE_OK && *cell == NULL);
}

/* a store whose tag was refused remembers the cell, and its close must leave alone a cell that another store holds now */
static void test_clear_is_compare_and_swap(void) {
    wasmext_store *first = wasmext_store_new(), *second = wasmext_store_new();
    wasmext_instance *y1 = wasmext_instance_new(first, &hy_binding, NULL), *y2 = wasmext_instance_new(second, &hy_binding, NULL);
    wasmext_export t1, t2;
    void *volatile *cell = cell_of(y1);
    CHECK(wasmext_tag_new(first, TYPES_IJ, 2, &t1) == 0 && wasmext_tag_new(second, TYPES_IJ, 2, &t2) == 0);
    CHECK(bind_tag(y1, &t1) == 0);
    CHECK(wasmext_store_free(first) == WASMEXT_STORE_OK && *cell == NULL);
    /* now `second` holds the cell; a third store whose tag is refused is closed first, and the cell stays as it is */
    {
        wasmext_store *third = wasmext_store_new();
        wasmext_instance *y3 = wasmext_instance_new(third, &hy_binding, NULL);
        wasmext_export t3;
        CHECK(wasmext_tag_new(third, TYPES_IJ, 2, &t3) == 0);
        CHECK(bind_tag(y2, &t2) == 0 && wasmext_instance_instantiate(y2) == 0 && *cell == t2.address);
        CHECK(bind_tag(y3, &t3) == WASMEXT_INST_TAG_HELD);
        CHECK(wasmext_store_free(third) == WASMEXT_STORE_OK);
        CHECK(*cell == t2.address && self_catch(y2) == 11);
    }
    CHECK(wasmext_store_free(second) == WASMEXT_STORE_OK && *cell == NULL);
}

/* a tag of a module is static data of the program: it does not dangle when the store of its exporter closes, and so the cell keeps it, and a new store links it again */
static void test_a_tag_of_a_module(void) {
    void *volatile *cell = NULL;
    const void *first = NULL;
    for (int round = 0; round < 2; round++) {
        wasmext_store *s = wasmext_store_new();
        wasmext_instance *a = wasmext_instance_new(s, &ta_binding, NULL), *b = wasmext_instance_new(s, &tb_binding, NULL);
        wasmext_export rec;
        wasmext_val x, r[2];
        CHECK(wasmext_instance_instantiate(a) == 0);
        CHECK(link_export(b, WASMEXT_DESC_TABLE, a, "tab") == 0 && link_export(b, WASMEXT_DESC_TAG, a, "t") == 0 && wasmext_instance_instantiate(b) == 0);
        CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "t", WASMEXT_DESC_TAG), NULL, &rec) == 0);
        cell = cell_of(b);
        if (round == 0) first = rec.address;
        CHECK(*cell == rec.address && rec.address == first);
        x = I32(0);
        CHECK(call(b, "catch_slot", &x, 1, r, 2) == 0 && r[0].as.i32 == 7 && r[1].as.i64 == 9);
        CHECK(wasmext_store_free(s) == WASMEXT_STORE_OK);
        CHECK(*cell == first); /* not cleared: it points at data that lives as long as the program */
    }
}

/* a record of an export of a store that is closed is not used: the tag of a module, a table of a module, a table of the host (the close freed what it points into) */
static void test_a_record_of_a_closed_store(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *a = wasmext_instance_new(s, &ta_binding, NULL), *b = wasmext_instance_new(s, &tb_binding, NULL);
    wasmext_export tab, tag, htab;
    int err = 0;
    wasmext_tab *ht = wasmext_tab_new(s, 0x70, 4, 8, &err); /* a table of the host: the close frees it, and the record points into it */
    CHECK(ht != NULL && wasmext_tab_record(ht, NULL, &htab) == 0);
    CHECK(wasmext_instance_instantiate(a) == 0);
    CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "tab", WASMEXT_DESC_TABLE), NULL, &tab) == 0);
    CHECK(wasmext_instance_export_record(a, (uint32_t)export_of(a, "t", WASMEXT_DESC_TAG), NULL, &tag) == 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_instance_bind_export(b, (uint32_t)import_of_kind(b, WASMEXT_DESC_TABLE), &tab) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(wasmext_instance_bind_export(b, (uint32_t)import_of_kind(b, WASMEXT_DESC_TABLE), &htab) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(bind_tag(b, &tag) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(wasmext_store_free(s) == WASMEXT_STORE_OK);
}

/* a barrier for the two threads of a round: both spin until the round is started */
static wasmext_counter go_;
typedef struct { wasmext_store *s; wasmext_instance *i; wasmext_export *rec; int rc; } round_t;
static THREAD_RESULT make_tags(void *arg) {
    round_t *r = (round_t *)arg;
    wasmext_export rec;
    while (!wasmext_atomic_load(&go_)) ;
    r->rc = wasmext_tag_new(r->s, TYPES_IJ, 2, &rec); /* 0, or WASMEXT_TRAP_CLOSED if the close came first */
    return 0;
}
static THREAD_RESULT close_it(void *arg) {
    round_t *r = (round_t *)arg;
    while (!wasmext_atomic_load(&go_)) ;
    wasmext_store_close(r->s);
    return 0;
}
/* two threads that start together on the flag: `first` and the close of r->s */
static void race_with_close(THREAD_RESULT (*first)(void *), round_t *r) {
    thread_t a, b;
    wasmext_atomic_store(&go_, 0);
    thread_start(&a, first, r);
    thread_start(&b, close_it, r);
    wasmext_atomic_store(&go_, 1);
    thread_join(a);
    thread_join(b);
}
static THREAD_RESULT bind_it(void *arg) {
    round_t *r = (round_t *)arg;
    while (!wasmext_atomic_load(&go_)) ;
    r->rc = bind_tag(r->i, r->rec);
    return 0;
}

/* tag_new against the close: the tag is owned before it is registered, so a close in between takes both or neither. Under AddressSanitizer a tag that the close freed and tag_new then
   freed again, or a close that ran the member of a tag already freed, is a heap-use-after-free. */
static void test_new_against_close(void) {
    for (int k = 0; k < 30000; k++) {
        wasmext_store *s = wasmext_store_new();
        round_t r;
        memset(&r, 0, sizeof r);
        r.s = s;
        race_with_close(make_tags, &r);
        CHECK(r.rc == 0 || r.rc == (int)WASMEXT_TRAP_CLOSED);
        CHECK(wasmext_store_free(s) == WASMEXT_STORE_OK);
    }
}

/* bind_export against the close: the cell is set under the lock of the store, after the check of `closing`. A bind that came too late must not write the tag the close has freed into the
   cell, which the whole program reads. With the set outside the lock this fails in 6 of 6 runs at 100000 rounds (3 of 4 at 30000), so the rounds are many. The outcome of each round is 0 (bound, then cleared by the close) or closed; the cell is empty after it, always. */
static void test_bind_against_close(void) {
    int bound = 0, closed = 0;
    for (int k = 0; k < 100000; k++) {
        wasmext_store *s = wasmext_store_new();
        wasmext_instance *x = wasmext_instance_new(s, &hz_binding, NULL);
        wasmext_export rec;
        round_t r;
        void *volatile *cell = cell_of(x);
        memset(&r, 0, sizeof r);
        r.s = s; r.i = x; r.rec = &rec;
        if (wasmext_tag_new(s, TYPES_IJ, 2, &rec) != 0) { CHECK(0); wasmext_store_free(s); continue; }
        race_with_close(bind_it, &r);
        if (r.rc == 0) bound++;
        else if (r.rc == (int)WASMEXT_TRAP_CLOSED) closed++;
        CHECK(r.rc == 0 || r.rc == (int)WASMEXT_TRAP_CLOSED);
        if (*cell != NULL) { CHECK(*cell == NULL); *cell = NULL; } /* a freed tag in the cell: said once, and put right so the rounds go on */
        CHECK(wasmext_store_free(s) == WASMEXT_STORE_OK);
    }
    CHECK(bound + closed == 100000);
}

/* threads, each with stores of its own: one thread per cell (nothing refused), and two threads for one cell (a store holds it, or is refused, and then holds it later) */
typedef struct { const wasmext_binding *binding; int rounds; int bad; int refused; int linked; } worker_t;
static THREAD_RESULT worker(void *arg) {
    worker_t *w = (worker_t *)arg;
    for (int k = 0; k < w->rounds; k++) {
        wasmext_store *s = wasmext_store_new();
        wasmext_instance *i = wasmext_instance_new(s, w->binding, NULL);
        wasmext_export rec;
        int rc;
        if (s == NULL || i == NULL || wasmext_tag_new(s, TYPES_IJ, 2, &rec) != 0) { w->bad++; continue; }
        rc = bind_tag(i, &rec);
        if (rc == WASMEXT_INST_TAG_HELD) w->refused++;
        else if (rc == 0) w->linked++;
        if (rc != 0 && rc != WASMEXT_INST_TAG_HELD) w->bad++;
        else if (rc == 0 && (wasmext_instance_instantiate(i) != 0 || self_catch(i) != 11)) w->bad++;
        if (wasmext_store_free(s) != WASMEXT_STORE_OK) w->bad++;
    }
    wasmext_thread_free();
    return 0;
}
static void run_workers(worker_t *w, const wasmext_binding *const *b, int n) {
    thread_t t[4];
    for (int k = 0; k < n; k++) { memset(&w[k], 0, sizeof w[k]); w[k].binding = b[k]; w[k].rounds = 300; }
    for (int k = 0; k < n; k++) thread_start(&t[k], worker, &w[k]);
    for (int k = 0; k < n; k++) thread_join(t[k]);
}
static void test_threads(void) {
    worker_t w[4];
    const wasmext_binding *b[4] = {&hx_binding, &hz_binding, &hy_binding, &hy_binding};
    /* one thread for a cell: never refused */
    run_workers(w, b, 4);
    CHECK(w[0].bad == 0 && w[0].refused == 0 && w[0].linked == 300 && w[1].bad == 0 && w[1].refused == 0 && w[1].linked == 300);
    /* two for one cell: some linked (the first bind of all finds the cell empty), none wrong; the count that were refused is a matter of timing */
    CHECK(w[2].bad == 0 && w[3].bad == 0 && w[2].linked + w[3].linked >= 1 && w[2].linked + w[3].linked + w[2].refused + w[3].refused == 600);
    {   /* two for one cell while a store of the main thread holds it: every one of them is refused, and when that store is freed they may link */
        wasmext_store *held = wasmext_store_new();
        wasmext_instance *y = wasmext_instance_new(held, &hy_binding, NULL);
        wasmext_export rec;
        const wasmext_binding *two[2] = {&hy_binding, &hy_binding};
        CHECK(wasmext_tag_new(held, TYPES_IJ, 2, &rec) == 0 && bind_tag(y, &rec) == 0);
        run_workers(w, two, 2);
        CHECK(w[0].bad == 0 && w[1].bad == 0 && w[0].refused == 300 && w[1].refused == 300 && w[0].linked == 0 && w[1].linked == 0);
        CHECK(wasmext_store_free(held) == WASMEXT_STORE_OK);
        run_workers(w, two, 2);
        CHECK(w[0].bad == 0 && w[1].bad == 0 && w[0].linked + w[1].linked >= 1 && w[0].linked + w[1].linked + w[0].refused + w[1].refused == 600);
    }
    {
        wasmext_store *s = wasmext_store_new();
        wasmext_instance *x = wasmext_instance_new(s, &hx_binding, NULL), *y = wasmext_instance_new(s, &hy_binding, NULL), *z = wasmext_instance_new(s, &hz_binding, NULL);
        CHECK(*cell_of(x) == NULL && *cell_of(y) == NULL && *cell_of(z) == NULL); /* every store let go of its cell */
        wasmext_store_free(s);
    }
}

int main(void) {
    test_one_store();
    test_cell();
    test_clear_is_compare_and_swap();
    test_a_tag_of_a_module();
    test_a_record_of_a_closed_store();
    test_new_against_close();
    test_bind_against_close();
    test_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
