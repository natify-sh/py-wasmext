/* Two artifacts built apart (two shared libraries, each with its own copy of the core and of the runtime of wasm2c) share ONE store: attach and its refusals, the instances of both
   in it, links through the shims, a function of the other artifact refused where a table or a global would let it be called (a guard of step 8a, removed by 8b), and the store closed and
   freed from either copy. docs/specs/S0008-shared-store.md. The host calls the core only through the tables of the two copies. */
#include <stdio.h>
#include "artifact.h"

#ifdef _WIN32
#error "this test is for the platforms with pthreads"
#endif
#include <pthread.h>

extern const artifact_api *artifact_a(void), *artifact_b(void);

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static const artifact_api *A, *B;

static wasmext_val I32(int32_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7F; x.as.i32 = v; return x; }
static wasmext_val I64(int64_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7E; x.as.i64 = v; return x; }
static wasmext_val REF(wasmext_funcref *f) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x70; x.as.ref = f; return x; }
static wasmext_val XREF(void *p) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x6F; x.as.ref = p; return x; }
static int32_t call_i32(const artifact_api *api, wasmext_instance *i, const char *name, int32_t a, int32_t b, int n_args) {
    wasmext_val args[2], r;
    args[0] = I32(a);
    args[1] = I32(b);
    memset(&r, 0, sizeof r);
    if (api->call(i, name, args, (uint32_t)n_args, &r, 1) != 0) return -999999;
    return r.as.i32;
}

static void test_two_copies(void) {
    CHECK(A->id != NULL && B->id != NULL && A->id != B->id);
    /* the proof that these are two copies of the runtime: a build where the dynamic linker merged them would give one address */
    CHECK(A->trap_address() != B->trap_address());
}

static void test_attach(void) {
    wasmext_store *s = A->store_new(), *closed = A->store_new();
    wasmext_store_head good;
    char why[200];
    int error = 0;
    CHECK(s != NULL);
    /* B did not make the store and has not attached to it */
    CHECK(B->instance_new(s, "appb", &error) == NULL && error == EXDEV);
    CHECK(A->instance_new(s, "liba", &error) != NULL && error == 0);
    good = s->head;
    CHECK(good.size == sizeof(wasmext_store) && good.rt == NULL && good.flags == 0);
    /* each refusal has its text, in the buffer of the caller */
    s->head.abi = good.abi | 0x01000000u; /* another x */
    why[0] = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "x 1 of the ABI") != NULL);
    s->head = good;
    s->head.floor = 0x00FFFFFFu; /* a floor above this reader, the same x */
    why[0] = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "at least") != NULL);
    s->head = good;
    s->head.size += 8;
    why[0] = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "bytes") != NULL);
    s->head = good;
    s->head.layout ^= 1u;
    why[0] = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "layout of the structs of the core") != NULL);
    s->head = good;
    s->head.runtime ^= 1u;
    why[0] = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "runtime of wasm2c") != NULL);
    s->head = good;
    /* the text is cut to the buffer of the caller, never past it, and a NULL buffer is allowed */
    s->head.layout ^= 1u;
    memset(why, 'x', sizeof why);
    CHECK(B->store_attach(s, why, 8) == WASMEXT_STORE_INCOMPATIBLE && why[7] == 0 && why[8] == 'x');
    CHECK(B->store_attach(s, NULL, 0) == WASMEXT_STORE_INCOMPATIBLE);
    s->head = good;
    /* B has not attached: what it would add to the store is refused, nothing is added (the store of A is still whole) */
    {
        long b0 = B->releases();
        CHECK(B->tab_new(s, &error) == NULL && error == EXDEV);
        CHECK(B->store_own(s) == WASMEXT_STORE_INCOMPATIBLE);
        CHECK(B->extern_new(s) == WASMEXT_INST_BAD_ARGS);
        CHECK(B->store_misc(s, 0) == WASMEXT_STORE_INCOMPATIBLE && B->store_misc(s, 1) == WASMEXT_STORE_INCOMPATIBLE && B->store_misc(s, 2) == WASMEXT_STORE_INCOMPATIBLE);
        CHECK(A->tab_new(s, &error) != NULL && A->extern_new(s) == 0); /* the artifact that made it can */
        CHECK(B->releases() == b0);
    }
    /* nothing was attached by the refusals */
    CHECK(B->instance_new(s, "appb", &error) == NULL && error == EXDEV);
    /* a store that is closed */
    CHECK(A->store_close(closed) == WASMEXT_STORE_OK);
    why[0] = 0;
    CHECK(B->store_attach(closed, why, sizeof why) == WASMEXT_STORE_CLOSED && strstr(why, "closed") != NULL);
    CHECK(B->instance_new(closed, "appb", &error) == NULL && error == EXDEV);
    CHECK(A->store_free(closed) == WASMEXT_STORE_OK);
    /* the good one, twice */
    why[0] = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK && why[0] == 0);
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK);
    CHECK(B->instance_new(s, "appb", &error) != NULL && error == 0);
    CHECK(A->store_free(s) == WASMEXT_STORE_OK);
}

/* host functions of the guard cases: one answers the funcref it is given as its `user`; one is a function of the type () -> i32 */
static int host_answer(void *user, const wasmext_val *args, wasmext_val *results) {
    (void)args;
    memset(&results[0], 0, sizeof results[0]);
    results[0].type = 0x70;
    results[0].as.ref = user;
    return 0;
}
static int host_five(void *user, const wasmext_val *args, wasmext_val *results) {
    (void)user; (void)args;
    results[0] = I32(5);
    return 0;
}

/* a store made by a file of an artifact that includes wasmext_store.h alone has the identity of the store without the instance and the runtime: a full copy refuses to attach to it, and
   to make instances in it, though it is the artifact that made it; two such files agree with each other and a full copy still refuses the store */
static void test_store_only(void) {
    wasmext_store *so = A->so_new(), *full = A->store_new();
    char why[200];
    int error = 0;
    CHECK(so != NULL);
    why[0] = 0;
    CHECK(B->store_attach(so, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "layout of the structs of the core differs") != NULL);
    CHECK(A->instance_new(so, "liba", &error) == NULL && error == EXDEV);
    CHECK(B->instance_new(so, "appb", &error) == NULL && error == EXDEV);
    why[0] = 0;
    CHECK(B->so_attach(so, why, sizeof why) == WASMEXT_STORE_OK); /* two store-only files agree ... */
    CHECK(B->instance_new(so, "appb", &error) == NULL && error == EXDEV); /* ... and a full copy still does not make instances in it */
    why[0] = 0;
    CHECK(B->so_attach(full, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "at least") != NULL); /* a store-only reader is below the floor of a full store */
    CHECK(B->store_attach(full, why, sizeof why) == WASMEXT_STORE_OK); /* full against full is fine */
    CHECK(B->instance_new(full, "appb", &error) != NULL);
    CHECK(A->store_free(so) == WASMEXT_STORE_OK && A->store_free(full) == WASMEXT_STORE_OK);
}

struct worker { const artifact_api *api; wasmext_instance *i; const char *name; int bad; };
static void *work(void *arg) {
    struct worker *w = (struct worker *)arg;
    for (int k = 0; k < 2000; k++)
        if (call_i32(w->api, w->i, w->name, k, 3, 2) != k + 3) w->bad++;
    /* a thread lets go of the copy it called into. A thread that calls into both copies (a link) cannot let go of both: each copy installs its own alternate stack for signals, the
       second replaces the first, and the runtime frees only the one that is in place (8b makes the copies of a store ready together) */
    w->api->thread_free();
    return NULL;
}

/* links through the shims, funcrefs of the other artifact refused, threads in both artifacts, and the store freed by the copy that did not make it */
static void test_one_store(void) {
    wasmext_store *s = A->store_new();
    wasmext_instance *la, *ua, *appb, *tabb, *glb, *ownb;
    wasmext_export rec;
    wasmext_funcref seven, nine, got;
    struct wasmext_tab_s_ *host_table;
    char why[200], text[WASMEXT_STORE_ERROR_SIZE];
    int error = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK);
    la = A->instance_new(s, "liba", &error);
    ua = A->instance_new(s, "usea", &error);
    appb = B->instance_new(s, "appb", &error);
    tabb = B->instance_new(s, "tabb", &error);
    glb = B->instance_new(s, "glb", &error);
    ownb = B->instance_new(s, "ownb", &error);
    CHECK(la && ua && appb && tabb && glb && ownb);
    CHECK(A->instantiate(la) == 0);
    /* function, memory and global of an instance of A, imported by an instance of B: through the shim of A */
    CHECK(A->export_record(la, "add", WASMEXT_DESC_FUNC, &rec) == 0 && B->bind(appb, "libx", "add", &rec) == 0);
    CHECK(A->export_record(la, "mem", WASMEXT_DESC_MEMORY, &rec) == 0 && B->bind(appb, "libx", "mem", &rec) == 0);
    CHECK(A->export_record(la, "counter", WASMEXT_DESC_GLOBAL, &rec) == 0 && B->bind(appb, "libx", "counter", &rec) == 0);
    CHECK(B->instantiate(appb) == 0);
    CHECK(call_i32(B, appb, "call_add", 2, 3, 2) == 5);
    {
        wasmext_val a[2];
        a[0] = I32(100);
        a[1] = I32(77);
        CHECK(B->call(appb, "poke", a, 2, NULL, 0) == 0);
    }
    CHECK(call_i32(A, la, "load", 100, 0, 1) == 77); /* one memory */
    CHECK(call_i32(B, appb, "inc", 0, 0, 0) == 11);
    CHECK(call_i32(A, la, "get_counter", 0, 0, 0) == 10 + 1); /* one global */

    /* a funcref of the other artifact: refused where a table, a global or a call would let it be called */
    CHECK(A->instantiate(la) == 0 && A->funcref(la, "seven", &seven) == 0);
    CHECK(B->instantiate(ownb) == 0 && B->funcref(ownb, "nine", &nine) == 0);
    CHECK(A->export_record(la, "tab", WASMEXT_DESC_TABLE, &rec) == 0);
    CHECK(B->bind(tabb, "libt", "tab", &rec) == WASMEXT_TAB_FOREIGN_ARTIFACT);
    B->store_error(s, text, sizeof text);
    CHECK(strstr(text, "libt.tab") != NULL && strstr(text, "another artifact") != NULL);
    CHECK(A->bind(ua, "libt", "tab", &rec) == 0 && A->instantiate(ua) == 0); /* the same artifact links */
    CHECK(A->export_record(la, "gf", WASMEXT_DESC_GLOBAL, &rec) == 0);
    CHECK(B->bind(glb, "libg", "gf", &rec) == WASMEXT_TAB_FOREIGN_ARTIFACT);
    CHECK(B->table_set(ownb, "tab", 0, &seven) == WASMEXT_TAB_FOREIGN_ARTIFACT);
    CHECK(B->table_set(ownb, "tab", 0, &nine) == 0 && call_i32(B, ownb, "call", 0, 0, 1) == 9);
    CHECK(A->table_set(la, "tab", 1, &nine) == WASMEXT_TAB_FOREIGN_ARTIFACT);
    CHECK(A->table_set(la, "tab", 1, &seven) == 0 && call_i32(A, la, "call", 1, 0, 1) == 7);
    CHECK(B->global_set_funcref(ownb, "gf", &seven) == WASMEXT_TAB_FOREIGN_ARTIFACT);
    CHECK(B->global_set_funcref(ownb, "gf", &nine) == 0);
    host_table = A->tab_new(s, &error);
    CHECK(host_table != NULL);
    CHECK(A->tab_set(host_table, 0, &seven) == 0);
    CHECK(A->tab_set(host_table, 1, &nine) == WASMEXT_TAB_FOREIGN_ARTIFACT);
    CHECK(A->tab_get(host_table, 1, &got) == 0 && got.ref.func == NULL); /* nothing was put in */
    CHECK(A->tab_get(host_table, 0, &got) == 0 && got.ref.func == seven.ref.func);

    /* the other places that let a funcref in: an argument of a call, call_ref, the answer of a host function, a global given by the host, and a host function as an element */
    {
        wasmext_instance *hostb = B->instance_new(s, "hostb", &error), *ifb = B->instance_new(s, "ifb", &error);
        wasmext_funcref out, hf;
        wasmext_val arg, res;
        CHECK(hostb && ifb);
        memset(&out, 0, sizeof out);
        memset(&res, 0, sizeof res);
        memset(&arg, 0, sizeof arg);
        arg.type = 0x70;
        res.as.ref = &out;
        arg.as.ref = &seven; /* an argument of a function of B that is a function of A */
        CHECK(B->call(ownb, "ident", &arg, 1, &res, 1) == WASMEXT_TAB_FOREIGN_ARTIFACT);
        arg.as.ref = &nine;
        CHECK(B->call(ownb, "ident", &arg, 1, &res, 1) == 0 && out.ref.func == nine.ref.func);
        memset(&res, 0, sizeof res);
        res.as.ref = &out;
        CHECK(B->call_ref(ownb, &seven, &res, 1) == WASMEXT_TAB_FOREIGN_ARTIFACT); /* call_ref through B of a function of A */
        CHECK(B->call_ref(ownb, &nine, &res, 1) == 0 && res.as.i32 == 9);
        CHECK(A->call_ref(la, &seven, &res, 1) == 0 && res.as.i32 == 7);
        /* a host function of B answers a funcref of A: the call traps (the answer is refused), and a funcref of B is fine */
        CHECK(B->bind_host(hostb, "env", "visit", host_answer, &seven) == 0 && B->instantiate(hostb) == 0);
        memset(&res, 0, sizeof res);
        res.as.ref = &out;
        arg.as.ref = NULL;
        CHECK(B->call(hostb, "via", &arg, 1, &res, 1) == (int)WASMEXT_TRAP_HOST);
        CHECK(B->bind_host(hostb, "env", "visit", host_answer, &nine) == WASMEXT_INST_TOO_LATE); /* after instantiate */
        /* a funcref global given by the host */
        CHECK(B->bind_global_funcref(ifb, "genv", "if", &seven) == WASMEXT_TAB_FOREIGN_ARTIFACT);
        CHECK(B->bind_global_funcref(ifb, "genv", "if", &nine) == 0);
        /* a host function of A as an element of a table of B (the artifact is that of the instance that made it) */
        CHECK(A->host_funcref(la, host_five, &hf) == 0);
        CHECK(B->table_set(ownb, "tab", 1, &hf) == WASMEXT_TAB_FOREIGN_ARTIFACT);
        CHECK(A->table_set(la, "tab", 2, &hf) == 0 && call_i32(A, la, "call", 2, 0, 1) == 5);
    }

    /* two threads in each artifact, and this thread calls through the link (B into the shim of A) meanwhile */
    {
        pthread_t t[4];
        struct worker w[4] = {{A, la, "add", 0}, {A, la, "add", 0}, {B, ownb, "plus", 0}, {B, ownb, "plus", 0}};
        for (int k = 0; k < 4; k++) pthread_create(&t[k], NULL, work, &w[k]);
        for (int k = 0; k < 2000; k++) CHECK(call_i32(B, appb, "call_add", k, 5, 2) == k + 5);
        for (int k = 0; k < 4; k++) pthread_join(t[k], NULL);
        for (int k = 0; k < 4; k++) CHECK(w[k].bad == 0);
    }

    /* the members of both artifacts run their releases once, whichever copy frees the store */
    {
        long a0 = A->releases(), b0 = B->releases();
        CHECK(A->store_own(s) == 0 && B->store_own(s) == 0 && B->store_own(s) == 0);
        CHECK(A->store_close(s) == WASMEXT_STORE_OK); /* closed by the copy that made it ... */
        CHECK(A->releases() - a0 == 1 && B->releases() - b0 == 2);
        CHECK(call_i32(B, appb, "call_add", 2, 3, 2) == -999999); /* closed */
        CHECK(B->store_free(s) == WASMEXT_STORE_OK); /* ... freed by the other: the wrappers of the instances of A are freed here */
        CHECK(A->releases() - a0 == 1 && B->releases() - b0 == 2);
    }
}

/* the same the other way round: B makes the store, A attaches, A frees it */
static void test_the_other_way(void) {
    wasmext_store *s = B->store_new();
    wasmext_instance *ownb, *la;
    long a0 = A->releases(), b0 = B->releases();
    char why[200];
    int error = 0;
    CHECK(A->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK);
    ownb = B->instance_new(s, "ownb", &error);
    la = A->instance_new(s, "liba", &error);
    CHECK(ownb && la && B->instantiate(ownb) == 0 && A->instantiate(la) == 0);
    CHECK(B->store_own(s) == 0 && A->store_own(s) == 0);
    CHECK(A->store_free(s) == WASMEXT_STORE_OK);
    CHECK(A->releases() - a0 == 1 && B->releases() - b0 == 1);
}

/* functions with references in the signature, linked from B to A (8a-2): the externref goes through as the same pointer, with numbers and several results; a funcref of B is refused in the shim
   of A, and a funcref of A that A answers is refused in the forwarder of B (the temporary guard of 8a, removed by 8b), as a trap of the host; null funcrefs go through. No trap of the
   callee here: until 8b a trap in code of one copy is not tested across copies (docs/LESSONS.md). */
static void test_references_through_links(void) {
    wasmext_store *s = A->store_new();
    wasmext_instance *lib, *app;
    wasmext_export rec;
    wasmext_funcref nine, seven, back, back2;
    wasmext_val a[4], r[4];
    wasmext_extern *e1;
    int item = 1, error = 0;
    static const char *const names[] = {"fident", "eident", "mixed", "getf", "boom", "isnull", "mfr"};
    char why[200], text[WASMEXT_STORE_ERROR_SIZE];
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK);
    lib = A->instance_new(s, "rlib", &error);
    app = B->instance_new(s, "rapp", &error);
    CHECK(lib && app && A->instantiate(lib) == 0);
    for (size_t k = 0; k < sizeof names / sizeof names[0]; k++) CHECK(A->export_record(lib, names[k], WASMEXT_DESC_FUNC, &rec) == 0 && B->bind(app, "libr", names[k], &rec) == 0);
    CHECK(A->export_record(lib, "fident", WASMEXT_DESC_FUNC, &rec) == 0 && strcmp(rec.signature, "F>F") == 0);
    CHECK(B->instantiate(app) == 0);
    e1 = A->extern_make(s, &item);
    CHECK(e1 != NULL && B->funcref(app, "nine", &nine) == 0 && A->funcref(lib, "seven", &seven) == 0);
    /* an externref and numbers cross the artifacts */
    a[0] = XREF(e1);
    CHECK(B->call(app, "ei", a, 1, r, 1) == 0 && r[0].as.ref == e1 && wasmext_extern_user(r[0].as.ref) == &item);
    a[0] = I32(5); a[1] = REF(NULL); a[2] = XREF(e1); a[3] = I64(77);
    r[0] = XREF(NULL); r[1] = I64(0); r[2] = REF(&back2); r[3] = I32(0);
    CHECK(B->call(app, "mx", a, 4, r, 4) == 0 && r[0].as.ref == e1 && r[1].as.i64 == 77 && back2.ref.func == NULL && r[3].as.i32 == 5);
    /* a null funcref goes through, in and out */
    a[0] = REF(NULL); r[0] = REF(&back);
    CHECK(B->call(app, "fi", a, 1, r, 1) == 0 && back.ref.func == NULL);
    CHECK(B->call(app, "isn", a, 1, r, 1) == 0 && r[0].as.i32 == 1);
    /* a funcref of B into a function of A (as an argument of the host's call, or one that wasm makes): refused in the shim of A. The temporary guard */
    a[0] = REF(&nine); r[0] = REF(&back);
    CHECK(B->call(app, "fi", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    CHECK(B->call(app, "isn", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    CHECK(B->call(app, "fnine", NULL, 0, r, 1) == (int)WASMEXT_TRAP_HOST);
    /* a funcref of A that A answers: refused where it comes out into the code of B */
    CHECK(B->call(app, "gf", NULL, 0, r, 1) == (int)WASMEXT_TRAP_HOST);
    B->store_error(s, text, sizeof text);
    CHECK(strstr(text, "another artifact") != NULL);
    /* ... also one inside a multi-value result (a funcref that A makes with ref.func, and a number) */
    r[0] = REF(&back); r[1] = I32(0);
    CHECK(B->call(app, "mf", NULL, 0, r, 2) == (int)WASMEXT_TRAP_HOST);
    /* a funcref of B in the funcref position of a function with several parameters */
    a[0] = I32(5); a[1] = REF(&nine); a[2] = XREF(e1); a[3] = I64(77);
    r[0] = XREF(NULL); r[1] = I64(0); r[2] = REF(&back2); r[3] = I32(0);
    CHECK(B->call(app, "mx", a, 4, r, 4) == (int)WASMEXT_TRAP_HOST);
    B->store_error(s, text, sizeof text);
    CHECK(strstr(text, "another artifact") != NULL);
    /* ... but A's own call of it is its own business */
    r[0] = REF(&back);
    CHECK(A->call(lib, "getf", NULL, 0, r, 1) == 0 && back.ref.module_instance == seven.ref.module_instance);
    a[0] = REF(&nine);
    CHECK(A->call(lib, "fident", a, 1, r, 1) == WASMEXT_TAB_FOREIGN_ARTIFACT);
    /* B is still usable after the refusals */
    a[0] = XREF(e1);
    CHECK(B->call(app, "ei", a, 1, r, 1) == 0 && r[0].as.ref == e1);
    CHECK(A->store_free(s) == WASMEXT_STORE_OK);
}

/* a tag of the host (8a-3): made in the store by one artifact, imported by an instance of each; the close clears both cells, from either copy, and each release runs once. The artifact that has
   not attached makes no tag in the store. */
static void test_host_tags(void) {
    static const uint8_t types[] = {0x7F};
    int error = 0;
    char why[200], text[WASMEXT_STORE_ERROR_SIZE];
    for (int variant = 0; variant < 4; variant++) {
        const artifact_api *maker = variant & 1 ? B : A, *closer = variant & 2 ? B : A, *other = variant & 1 ? A : B;
        wasmext_store *s = maker->store_new();
        wasmext_instance *ia, *ib;
        wasmext_export rec, none;
        void *volatile *cell_a, *volatile *cell_b;
        long a0 = A->releases(), b0 = B->releases();
        CHECK(other->tag_new(s, types, 1, &none) == WASMEXT_INST_BAD_ARGS); /* not attached: refused, nothing made */
        CHECK(other->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK);
        CHECK(maker->tag_new(s, types, 1, &rec) == 0 && rec.kind == WASMEXT_TAG && strcmp(rec.signature, "i>") == 0 && rec.artifact == maker->id);
        ia = A->instance_new(s, "tha", &error);
        ib = B->instance_new(s, "thb", &error);
        CHECK(ia && ib);
        cell_a = A->tag_cell(ia);
        cell_b = B->tag_cell(ib);
        CHECK(*cell_a == NULL && *cell_b == NULL);
        CHECK(A->bind(ia, "hgna", "t", &rec) == 0 && B->bind(ib, "hgnb", "t", &rec) == 0); /* the record of one copy is read by the other */
        CHECK(A->instantiate(ia) == 0 && B->instantiate(ib) == 0);
        CHECK(*cell_a == rec.address && *cell_b == rec.address);
        CHECK(call_i32(A, ia, "self_catch", 0, 0, 0) == 31 && call_i32(B, ib, "self_catch", 0, 0, 0) == 31);
        CHECK(other->tag_new(s, types, 1, &none) == 0); /* attached now: a tag of each copy */
        CHECK(A->store_own(s) == 0 && B->store_own(s) == 0);
        CHECK(closer->store_close(s) == WASMEXT_STORE_OK);
        CHECK(*cell_a == NULL && *cell_b == NULL); /* both cells let go, by the copy that closed */
        CHECK(A->releases() - a0 == 1 && B->releases() - b0 == 1);
        CHECK(maker->tag_new(s, types, 1, &none) == (int)WASMEXT_TRAP_CLOSED);
        CHECK(B->store_free(s) == WASMEXT_STORE_OK); /* freed by B: the tags are not freed twice (AddressSanitizer) */
        CHECK(A->releases() - a0 == 1 && B->releases() - b0 == 1 && *cell_a == NULL && *cell_b == NULL);
    }
    /* a second store for the name is refused while the first holds it, with the reason; the cell is the first's after the second is gone, and empty after the first */
    {
        wasmext_store *s1 = A->store_new(), *s2 = A->store_new();
        wasmext_instance *i1 = A->instance_new(s1, "tha", &error), *i2 = A->instance_new(s2, "tha", &error);
        wasmext_export t1, t2;
        void *volatile *cell = A->tag_cell(i1);
        CHECK(A->tag_new(s1, types, 1, &t1) == 0 && A->tag_new(s2, types, 1, &t2) == 0);
        CHECK(A->bind(i1, "hgna", "t", &t1) == 0);
        CHECK(A->bind(i2, "hgna", "t", &t2) == WASMEXT_INST_TAG_HELD);
        A->store_error(s2, text, sizeof text);
        CHECK(strstr(text, "hgna.t") != NULL && strstr(text, "another tag holds the import already") != NULL);
        CHECK(B->store_attach(s2, why, sizeof why) == WASMEXT_STORE_OK && B->store_free(s2) == WASMEXT_STORE_OK); /* the refused store goes (freed by the other copy) */
        CHECK(*cell == t1.address);
        CHECK(A->store_free(s1) == WASMEXT_STORE_OK && *cell == NULL);
    }
}

static void *tag_work(void *arg) {
    struct worker *w = (struct worker *)arg;
    static const uint8_t types[] = {0x7F};
    int error = 0;
    for (int k = 0; k < 200; k++) {
        wasmext_store *s = w->api->store_new();
        wasmext_instance *i = w->api->instance_new(s, w->name, &error);
        wasmext_export rec;
        void *volatile *cell;
        if (s == NULL || i == NULL || w->api->tag_new(s, types, 1, &rec) != 0) { w->bad++; continue; }
        cell = w->api->tag_cell(i);
        if (w->api->bind(i, w->api == A ? "hgna" : "hgnb", "t", &rec) != 0 || w->api->instantiate(i) != 0 || call_i32(w->api, i, "self_catch", 0, 0, 0) != 31) w->bad++;
        if (w->api->store_free(s) != WASMEXT_STORE_OK || *cell != NULL) w->bad++;
    }
    w->api->thread_free();
    return NULL;
}

/* two threads, one in each copy, each making and freeing stores with a tag (the cells are the copies' own) */
static void test_host_tags_threads(void) {
    pthread_t t[2];
    struct worker w[2] = {{A, NULL, "tha", 0}, {B, NULL, "thb", 0}};
    for (int k = 0; k < 2; k++) pthread_create(&t[k], NULL, tag_work, &w[k]);
    for (int k = 0; k < 2; k++) pthread_join(t[k], NULL);
    CHECK(w[0].bad == 0 && w[1].bad == 0);
}

int main(void) {
    A = artifact_a();
    B = artifact_b();
    test_two_copies();
    test_attach();
    test_store_only();
    test_one_store();
    test_the_other_way();
    test_references_through_links();
    test_host_tags();
    test_host_tags_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
