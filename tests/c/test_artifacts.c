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
    CHECK(good.size == sizeof(wasmext_store) && good.rt == A->runtime_id() && good.flags == 0);
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

/* D45: the counter of a runtime starts at a value derived from the address of its table (`(a >> 4) ^ (a >> 20) ^ (a >> 36)`), so the FIRST store of an artifact has serial seed + 1. Run before any other
   store is made. The seeds themselves are not compared with each other: they come from addresses, so such a check would fail by chance (about 1 in 65536 per run). */
static uint32_t seed_of(const artifact_api *api) {
    uint64_t a = (uint64_t)(uintptr_t)api->runtime_id();
    return (uint32_t)((a >> 4) ^ (a >> 20) ^ (a >> 36));
}
static void test_seeds(void) {
    wasmext_store *a = A->store_new(), *b = B->store_new();
    CHECK(a->registry.serial == ((seed_of(A) + 1u) & 0xFFFFu));
    CHECK(b->registry.serial == ((seed_of(B) + 1u) & 0xFFFFu));
    CHECK(A->store_free(a) == WASMEXT_STORE_OK && B->store_free(b) == WASMEXT_STORE_OK);
}

/* 8b-1: what `attach` says of the runtime of the store and of the list of artifacts */
static void test_attach_runtime(void) {
    wasmext_store *s = A->store_new();
    wasmext_runtime fake;
    wasmext_artifact_entry saved[WASMEXT_MAX_ARTIFACTS];
    char why[200];
    void *rt = s->head.rt;
    long k;
    CHECK(s != NULL && rt != NULL && s->head.rt == A->runtime_id());
    CHECK(((const wasmext_runtime *)rt)->head.flags != 0 && ((const wasmext_runtime *)rt)->head.size == sizeof(wasmext_runtime));
    /* a store with no runtime is refused, with its reason */
    s->head.rt = NULL;
    why[0] = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "no runtime") != NULL);
    /* ... and so is one whose runtime checks the stack another way (the table is a copy of A's with another mode) */
    memcpy(&fake, rt, sizeof fake);
    fake.head.flags ^= 1u;
    s->head.rt = &fake;
    why[0] = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "mode of the stack check") != NULL);
    s->head.rt = rt;
    CHECK(wasmext_atomic_load(&s->n_artifacts) == 1); /* nothing was added by the refusals */
    /* the list holds 8: a ninth is refused with its reason, nothing is added; the artifact that is in the list can attach again */
    memcpy(saved, s->artifacts, sizeof saved);
    for (k = 1; k < WASMEXT_MAX_ARTIFACTS; k++) s->artifacts[k].identity = (const void *)(uintptr_t)(0x1000 + k);
    wasmext_atomic_store(&s->n_artifacts, WASMEXT_MAX_ARTIFACTS);
    why[0] = 0;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_INCOMPATIBLE && strstr(why, "8 artifacts") != NULL);
    CHECK(wasmext_atomic_load(&s->n_artifacts) == WASMEXT_MAX_ARTIFACTS && s->artifacts[WASMEXT_MAX_ARTIFACTS - 1].identity == (const void *)(uintptr_t)(0x1000 + WASMEXT_MAX_ARTIFACTS - 1));
    CHECK(A->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK);
    memcpy(s->artifacts, saved, sizeof saved);
    wasmext_atomic_store(&s->n_artifacts, 1);
    /* the good one: B is in the list with the functions of its copy */
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK && wasmext_atomic_load(&s->n_artifacts) == 2);
    CHECK(s->artifacts[0].identity == A->id && s->artifacts[1].identity == B->id && s->artifacts[1].activate != NULL && s->artifacts[1].deactivate != NULL);
    CHECK(A->store_free(s) == WASMEXT_STORE_OK);
}

/* 8b-1: the forwarders of a copy reach the table of the runtime it is told to, and the functions of its own when none is */
static void test_forwarders_across_copies(void) {
    static const uint8_t bytes[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    wasmext_store *s = A->store_new();
    const void *tag = (const void *)&bytes, *was;
    CHECK(B->store_attach(s, NULL, 0) == WASMEXT_STORE_OK);
    A->exception_load(tag, 5, bytes); /* each copy on its own table: the state of the exception is the copy's */
    CHECK(A->exception_size() == 5 && B->exception_size() == 0);
    CHECK(B->set_tls_rt(NULL) == NULL);
    /* B told to use A's table: B's wasm_rt_load_exception and wasm_rt_exception_size are A's */
    CHECK(B->set_tls_rt(A->runtime_id()) == NULL);
    B->exception_load(tag, 3, bytes);
    CHECK(A->exception_size() == 3 && B->exception_size() == 3);
    CHECK(B->set_tls_rt(NULL) == A->runtime_id());
    CHECK(B->exception_size() == 0 && A->exception_size() == 3); /* B's own state was not touched */
    /* the entries of the list do the same (what the entry of a call will use): B's activate, with A's table */
    was = s->artifacts[1].activate(A->runtime_id());
    CHECK(was == NULL);
    B->exception_load(tag, 2, bytes);
    CHECK(A->exception_size() == 2);
    s->artifacts[1].deactivate(was);
    CHECK(B->exception_size() == 0);
    /* an entry told its own table leaves the copy on its own functions (tls.rt NULL) */
    was = s->artifacts[0].activate(A->runtime_id());
    CHECK(A->set_tls_rt(NULL) == NULL && was == NULL);
    CHECK(A->store_free(s) == WASMEXT_STORE_OK);
}

/* 8b-1, D45: the serials of the stores of one runtime differ; two runtimes may share one, and the registry then answers for the wrong store (the stated limit) */
static void test_serials(void) {
    static unsigned char seen[65536];
    uint32_t first = 0;
    long k;
    wasmext_store *a, *b;
    wasmext_owner o, p;
    void *object = NULL;
    for (k = 0; k < 65536; k++) {
        wasmext_store *s = A->store_new();
        uint32_t serial = s->registry.serial;
        if (k == 0) first = serial;
        CHECK(serial < 65536u && !seen[serial]);
        seen[serial & 0xFFFFu] = 1;
        CHECK(A->store_free(s) == WASMEXT_STORE_OK);
    }
    {
        wasmext_store *s = A->store_new(); /* the 65537th: the 16 bits wrap */
        CHECK(s->registry.serial == first);
        CHECK(A->store_free(s) == WASMEXT_STORE_OK);
    }
    /* two runtimes with fixed seeds: the serial is seed + 1, and a handle of B's store given to A's is WRONG */
    A->fix_seed(100);
    B->fix_seed(200);
    a = A->store_new();
    b = B->store_new();
    CHECK(a->registry.serial == 101 && b->registry.serial == 201);
    CHECK(A->register_object(a, &o) == WASMEXT_STORE_OK && B->register_object(b, &p) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_member(a, p, &object) == WASMEXT_STORE_WRONG);
    CHECK(wasmext_store_member(a, o, &object) == WASMEXT_STORE_OK);
    CHECK(B->store_free(b) == WASMEXT_STORE_OK);
    /* ... and when the seeds are equal the handle is taken for A's own: the limit, said in the spec */
    B->fix_seed(100);
    b = B->store_new();
    CHECK(b->registry.serial == 101);
    CHECK(B->register_object(b, &p) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_member(a, p, &object) == WASMEXT_STORE_OK);
    CHECK(A->store_free(a) == WASMEXT_STORE_OK && B->store_free(b) == WASMEXT_STORE_OK);
    A->fix_seed(1000);
    B->fix_seed(2000);
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

/* ---- 8b-2: a trap in the code of any copy of a store comes back to the innermost entry of the thread (S0008). The store is made by `maker`, the other copy attaches; every case runs both ways, so the
   entry is the copy of the runtime of the store and the copy that is not. Explicit traps only (`unreachable`, division by zero, a host function that fails): the signals are 8b-3. ---- */
typedef struct { const void *rt, *top, *unwind; } cstate;
static cstate state_of(const artifact_api *api) {
    cstate c;
    api->state(&c.rt, &c.top, &c.unwind);
    return c;
}
/* after a call, however it ended: nothing is active, no entry is left, and the unwind target is what it was (checked in the line of the caller) */
#define CLEAN(API, BEFORE) do { cstate now_ = state_of(API); CHECK(now_.rt == NULL && now_.top == NULL && now_.unwind == (BEFORE).unwind); } while (0)

struct nest { const artifact_api *api; wasmext_instance *inst; const char *name; int depth_seen; int bad; };
/* the host function of the nested cases: calls back into the store (`name` of `inst` through `api`) with n - 1, and passes the answer on; a failure of the callee is a failure of the host */
static int host_nest(void *user, const wasmext_val *args, wasmext_val *results) {
    struct nest *n = (struct nest *)user;
    wasmext_val a, r;
    cstate a0 = state_of(A), b0 = state_of(B), a1, b1;
    int rc;
    n->depth_seen++;
    a = I32(args[0].as.i32 - 1);
    memset(&r, 0, sizeof r);
    rc = n->api->call(n->inst, n->name, &a, 1, &r, 1);
    /* a nested call, whichever way it ended, leaves what each copy had: the active runtime (a different one in each copy: the copy that was entered has A's or B's table, the other has none), the innermost entry, the unwind target */
    a1 = state_of(A);
    b1 = state_of(B);
    if (a1.rt != a0.rt || a1.top != a0.top || a1.unwind != a0.unwind || b1.rt != b0.rt || b1.top != b0.top || b1.unwind != b0.unwind) n->bad++;
    if (rc != 0) return rc;
    results[0] = r;
    return 0;
}
static int host_fail(void *user, const wasmext_val *args, wasmext_val *results) { (void)user; (void)args; (void)results; return 1; }
static int host_nop(void *user, const wasmext_val *args, wasmext_val *results) {
    struct nest *n = (struct nest *)user;
    wasmext_val r;
    (void)args; (void)results;
    memset(&r, 0, sizeof r);
    return n->api->call(n->inst, n->name, NULL, 0, &r, 1) == 0 && r.as.i32 == 1 ? 0 : 1;
}

struct pair {
    const artifact_api *maker, *other;
    wasmext_store *s;
    wasmext_instance *ta, *tb, *tc, *na, *nb, *ya, *yb;
};
static void pair_new(struct pair *p, const artifact_api *maker, const artifact_api *other) {
    wasmext_export rec;
    char why[200];
    int error = 0;
    memset(p, 0, sizeof *p);
    p->maker = maker;
    p->other = other;
    p->s = maker->store_new();
    CHECK(p->s != NULL && other->store_attach(p->s, why, sizeof why) == WASMEXT_STORE_OK);
    p->ta = A->instance_new(p->s, "trapa", &error);
    p->tb = B->instance_new(p->s, "trapb", &error);
    p->tc = B->instance_new(p->s, "trapc", &error);
    p->na = A->instance_new(p->s, "nesta", &error);
    p->nb = B->instance_new(p->s, "nestb", &error);
    p->ya = A->instance_new(p->s, "trya", &error);
    p->yb = B->instance_new(p->s, "tryb", &error);
    CHECK(p->ta && p->tb && p->tc && p->na && p->nb && p->ya && p->yb);
    CHECK(A->instantiate(p->ta) == 0);
    /* B takes the table of A: a raw table, the artifact left unsaid (the guard of 8a would refuse it) */
    CHECK(A->export_record(p->ta, "tab", WASMEXT_DESC_TABLE, &rec) == 0);
    rec.artifact = NULL;
    CHECK(B->bind(p->tb, "tt", "tab", &rec) == 0 && B->instantiate(p->tb) == 0);
    /* B's links to the functions of A */
    CHECK(A->export_record(p->ta, "boom", WASMEXT_DESC_FUNC, &rec) == 0 && B->bind(p->tc, "lk", "boom", &rec) == 0);
    CHECK(A->export_record(p->ta, "div", WASMEXT_DESC_FUNC, &rec) == 0 && B->bind(p->tc, "lk", "div", &rec) == 0);
    CHECK(B->instantiate(p->tc) == 0);
}

/* c1, c2, c5: a trap in the code of the other copy, through a raw table, through a link, and in mutual recursion */
static void trap_cases(struct pair *p) {
    cstate a0 = state_of(A), b0 = state_of(B);
    const int unreachable = (int)WASM_RT_TRAP_UNREACHABLE;
    /* c1: B's entry, A's function (the table: slot 1 is `boom`) and A's entry, B's function through the table (`pb` is at 3, `pa` calls it) */
    CHECK(call_i32(B, p->tb, "call", 0, 0, 1) == 7);
    CHECK(B->call(p->tb, "call", (wasmext_val[]){I32(1)}, 1, (wasmext_val[]){I32(0)}, 1) == unreachable);
    CLEAN(A, a0); CLEAN(B, b0);
    CHECK(call_i32(A, p->ta, "call", 0, 0, 1) == 7); /* both are usable after the trap */
    CHECK(call_i32(B, p->tb, "call", 0, 0, 1) == 7);
    /* c2: through a link: A's shim answers LINKED + the trap, B raises it again, and the entry of B answers the code of the trap */
    CHECK(B->call(p->tc, "call_boom", NULL, 0, (wasmext_val[]){I32(0)}, 1) == unreachable);
    CLEAN(A, a0); CLEAN(B, b0);
    CHECK(B->call(p->tc, "call_div", (wasmext_val[]){I32(5), I32(0)}, 2, (wasmext_val[]){I32(0)}, 1) == (int)WASM_RT_TRAP_DIV_BY_ZERO);
    CLEAN(A, a0); CLEAN(B, b0);
    CHECK(call_i32(B, p->tc, "call_div", 12, 4, 2) == 3);
    /* c5: A and B call each other through the table n times and trap at 0, whichever copy the thread entered by; the depth is explicit, the stack is not exhausted */
    for (int n = 0; n <= 300; n += (n < 5 ? 1 : 97)) {
        wasmext_val a = I32(n), r = I32(0);
        CHECK(A->call(p->ta, "pa", &a, 1, &r, 1) == unreachable);
        CHECK(B->call(p->tb, "pb", &a, 1, &r, 1) == unreachable);
        CLEAN(A, a0); CLEAN(B, b0);
    }
    CHECK(call_i32(A, p->ta, "div", 9, 3, 2) == 3 && call_i32(B, p->tb, "call", 0, 0, 1) == 7);
    /* a throw that nothing catches ends the call as a trap, and the exception is the one of the runtime of the store: either copy reads it (the scope of `wasmext_instance_exception`) */
    {
        const void *tag_b = NULL, *tag_a = NULL;
        CHECK(B->call(p->tb, "thrower", NULL, 0, NULL, 0) == (int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION);
        CLEAN(A, a0); CLEAN(B, b0);
        CHECK(B->exception_of(p->tb, &tag_b) == 0 && tag_b != NULL && A->exception_of(p->ta, &tag_a) == 0 && tag_a == tag_b);
        CLEAN(A, a0); CLEAN(B, b0);
    }
}

/* c4 and c7: a host function that fails, one that calls back (a nested entry, of the same copy and of the other) and a trap deep inside; then the next call works and nothing is left active */
static void nested_cases(struct pair *p) {
    cstate a0 = state_of(A), b0 = state_of(B);
    struct nest same = {B, p->nb, "rec", 0}, back = {B, p->nb, "rec", 0};
    wasmext_val a = I32(5), r = I32(0);
    /* c4: a host function of an instance of B fails: the trap is a trap of the host, and the same for A (both with the runtime of the store the other copy's) */
    CHECK(B->bind_host(p->nb, "nb", "cb", host_fail, NULL) == 0 && B->instantiate(p->nb) == 0);
    CHECK(A->bind_host(p->na, "na", "cb", host_fail, NULL) == 0 && A->instantiate(p->na) == 0);
    CHECK(B->call(p->nb, "rec", &a, 1, &r, 1) == (int)WASMEXT_TRAP_HOST);
    CHECK(A->call(p->na, "rec", &a, 1, &r, 1) == (int)WASMEXT_TRAP_HOST);
    CLEAN(A, a0); CLEAN(B, b0);
    /* c7: the host function of B's instance calls B again, n times, and `rec(0)` traps at the bottom; each level passes the failure up. The functions are bound after instantiate for the first
       modules, so these are two more instances */
    {
        int error = 0;
        wasmext_instance *n1 = B->instance_new(p->s, "nestb", &error), *n2 = A->instance_new(p->s, "nesta", &error);
        CHECK(n1 && n2);
        same.inst = n1;
        back.api = A;
        back.inst = n2;
        CHECK(B->bind_host(n1, "nb", "cb", host_nest, &same) == 0 && B->instantiate(n1) == 0);
        CHECK(A->bind_host(n2, "na", "cb", host_nest, &back) == 0 && A->instantiate(n2) == 0);
        a = I32(6);
        CHECK(B->call(n1, "rec", &a, 1, &r, 1) == (int)WASMEXT_TRAP_HOST && same.depth_seen == 6 && same.bad == 0); /* six host calls, the seventh call traps */
        CLEAN(A, a0); CLEAN(B, b0);
        back.depth_seen = 0;
        CHECK(A->call(n2, "rec", &a, 1, &r, 1) == (int)WASMEXT_TRAP_HOST && back.depth_seen == 6 && back.bad == 0);
        CLEAN(A, a0); CLEAN(B, b0);
        /* the two copies take turns: B's host function calls A's instance, whose host function calls B's */
        same.api = A;
        same.inst = n2;
        back.api = B;
        back.inst = n1;
        same.depth_seen = back.depth_seen = 0;
        a = I32(7);
        CHECK(B->call(n1, "rec", &a, 1, &r, 1) == (int)WASMEXT_TRAP_HOST && same.depth_seen + back.depth_seen == 7 && same.bad + back.bad == 0);
        CLEAN(A, a0); CLEAN(B, b0);
        /* the next call on the same thread works, with the result */
        a = I32(1);
        same.depth_seen = back.depth_seen = 0;
        CHECK(B->call(n1, "rec", &a, 1, &r, 1) == (int)WASMEXT_TRAP_HOST);
        CLEAN(A, a0); CLEAN(B, b0);
        CHECK(call_i32(B, p->tb, "call", 0, 0, 1) == 7 && call_i32(A, p->ta, "call", 0, 0, 1) == 7);
    }
}

/* the unwind target after a nested entry is the `try` of the code that called, not the buffer of the outer entry: the throw after the host function (which entered the store again) is caught by it */
static void try_cases(struct pair *p) {
    cstate a0 = state_of(A), b0 = state_of(B);
    struct nest inner_b = {B, p->nb, "noop", 0}, inner_a = {A, p->na, "noop", 0};
    wasmext_val r;
    CHECK(B->bind_host(p->yb, "yb", "cb", host_nop, &inner_b) == 0 && B->instantiate(p->yb) == 0);
    CHECK(A->bind_host(p->ya, "ya", "cb", host_nop, &inner_a) == 0 && A->instantiate(p->ya) == 0);
    memset(&r, 0, sizeof r);
    CHECK(B->call(p->yb, "run", NULL, 0, &r, 1) == 0 && r.as.i32 == 31);
    CLEAN(A, a0); CLEAN(B, b0);
    memset(&r, 0, sizeof r);
    CHECK(A->call(p->ya, "run", NULL, 0, &r, 1) == 0 && r.as.i32 == 31);
    CLEAN(A, a0); CLEAN(B, b0);
}

static void *first_entry(void *arg) {
    struct pair *p = (struct pair *)arg;
    cstate a0 = state_of(A), b0 = state_of(B);
    /* c6: this thread never entered A (nor B); its first entry is B's, and the trap is in A's code */
    CHECK(a0.rt == NULL && a0.top == NULL && b0.rt == NULL && b0.top == NULL);
    CHECK(B->call(p->tb, "call", (wasmext_val[]){I32(1)}, 1, (wasmext_val[]){I32(0)}, 1) == (int)WASM_RT_TRAP_UNREACHABLE);
    CLEAN(A, a0); CLEAN(B, b0);
    CHECK(call_i32(B, p->tb, "call", 0, 0, 1) == 7);
    A->thread_free();
    B->thread_free();
    return NULL;
}

/* c9: two threads on one store in opposite directions (one enters by B and traps in A, the other enters by A and traps in B), many traps each */
static void *toward_a(void *arg) {
    struct pair *p = (struct pair *)arg;
    cstate a0 = state_of(A), b0 = state_of(B);
    for (int k = 0; k < 400; k++) {
        wasmext_val a = I32(1 + k % 3), r = I32(0);
        CHECK(B->call(p->tb, "pb", &a, 1, &r, 1) == (int)WASM_RT_TRAP_UNREACHABLE);
        CHECK(call_i32(B, p->tb, "call", 0, 0, 1) == 7);
    }
    CLEAN(A, a0); CLEAN(B, b0);
    A->thread_free();
    B->thread_free();
    return NULL;
}
static void *toward_b(void *arg) {
    struct pair *p = (struct pair *)arg;
    cstate a0 = state_of(A), b0 = state_of(B);
    for (int k = 0; k < 400; k++) {
        wasmext_val a = I32(1 + k % 3), r = I32(0);
        CHECK(A->call(p->ta, "pa", &a, 1, &r, 1) == (int)WASM_RT_TRAP_UNREACHABLE);
        CHECK(call_i32(A, p->ta, "call", 0, 0, 1) == 7);
    }
    CLEAN(A, a0); CLEAN(B, b0);
    A->thread_free();
    B->thread_free();
    return NULL;
}

static void test_traps_across_copies(void) {
    for (int variant = 0; variant < 2; variant++) {
        struct pair p;
        pthread_t t[3];
        pair_new(&p, variant ? B : A, variant ? A : B);
        trap_cases(&p);
        nested_cases(&p);
        try_cases(&p);
        /* c6, then c9 */
        pthread_create(&t[0], NULL, first_entry, &p);
        pthread_join(t[0], NULL);
        pthread_create(&t[1], NULL, toward_a, &p);
        pthread_create(&t[2], NULL, toward_b, &p);
        pthread_join(t[1], NULL);
        pthread_join(t[2], NULL);
        CHECK(call_i32(B, p.tb, "call", 0, 0, 1) == 7 && A->store_free(p.s) == WASMEXT_STORE_OK);
    }
}

/* ---- 8b-3a: a signal in the code of any copy of a store is a trap that reaches the innermost entry of the thread: c3, a guard page touched in the memory of A and reached from B (and the other way),
   and a recursion that the stack cannot hold, in one copy and reached from the other. The handler is the core's (wasmext_signals.h): the one of the copy installed last runs and goes through the
   forwarder, so it does not matter which copy that is. `stock` is not here: the handler of the runtime of each copy bypasses `tls.rt` (it calls its own trap), which is not a thing that two copies
   in one process can do; the single copy of that mode is tests/test_signals.py. ---- */
#ifndef TEST_MODE_STOCK
#ifdef TEST_NO_RECURSION /* ThreadSanitizer: its own handler faults when a stack runs out (tests/test_signals.py), so there the signals are the guard-page accesses only */
#define RECURSION 0
#else
#define RECURSION 1
#endif
#ifdef TEST_MODE_GUARD
#define LIMIT_MODE 0
#else
#define LIMIT_MODE 1
#endif
/* the answer of a recursion: EXHAUSTION where the limit sees it and on the main thread; on another thread the guard page of the stack is a mapped page without access, which a handler of the guard
   mode reports as OOB (docs/experiments/stack_limit/README.md) */
static int is_stack_trap(int rc, int main_thread) {
    int ok = rc == (int)WASM_RT_TRAP_EXHAUSTION || (!LIMIT_MODE && !main_thread && rc == (int)WASM_RT_TRAP_OOB);
    if (!ok) { /* say what happened: the answer, the thread, the mode, and for each copy the limit it computed and the stack of the thread */
        const artifact_api *copies[2] = {A, B};
        fprintf(stderr, "a recursion answered %d (EXHAUSTION is %d, OOB %d); main_thread=%d mode=%s\n", rc, (int)WASM_RT_TRAP_EXHAUSTION, (int)WASM_RT_TRAP_OOB, main_thread, LIMIT_MODE ? "limit" : "guard");
        for (int k = 0; k < 2; k++) {
            uintptr_t limit, low, size, here;
            copies[k]->stack_info(&limit, &low, &size, &here);
            fprintf(stderr, "  copy %c: limit=%#lx stack low=%#lx size=%#lx (top %#lx) frame here=%#lx\n", k ? 'B' : 'A', (unsigned long)limit, (unsigned long)low, (unsigned long)size, (unsigned long)(low + size), (unsigned long)here);
        }
    }
    return ok;
}
static void signal_cases(struct pair *p, int main_thread) {
    cstate a0 = state_of(A), b0 = state_of(B);
    const int oob = (int)WASM_RT_TRAP_OOB;
    wasmext_val r = I32(0);
    /* this thread is ready in both copies (the limit of each): the readiness of the copy that is not the runtime of the store is 8b-3b */
    A->thread_ready();
    B->thread_ready();
    for (int k = 0; k < 3; k++) {
        /* c3: B's entry, A's `ld` (slot 4) through the raw table, and A's entry, B's `ld` (slot 7); the instances are usable after it */
        CHECK(B->call(p->tb, "calln", (wasmext_val[]){I32(1 << 20), I32(4)}, 2, &r, 1) == oob);
        CLEAN(A, a0); CLEAN(B, b0);
        CHECK(A->call(p->ta, "calln", (wasmext_val[]){I32(1 << 20), I32(7)}, 2, &r, 1) == oob);
        CLEAN(A, a0); CLEAN(B, b0);
        CHECK(call_i32(A, p->ta, "call", 0, 0, 1) == 7 && call_i32(B, p->tb, "call", 0, 0, 1) == 7);
        /* the same in one copy */
        CHECK(A->call(p->ta, "ld", (wasmext_val[]){I32(1 << 20)}, 1, &r, 1) == oob);
        CHECK(B->call(p->tb, "ld", (wasmext_val[]){I32((int32_t)0xFFFFFFF0u)}, 1, &r, 1) == oob);
        CLEAN(A, a0); CLEAN(B, b0);
        /* a recursion with no end: in A's code and in B's code, entered by its own copy and by the other (slot 5 is A's `deep`, slot 6 B's) */
        if (RECURSION) {
            CHECK(is_stack_trap(A->call(p->ta, "deep", (wasmext_val[]){I32(1)}, 1, &r, 1), main_thread));
            CHECK(is_stack_trap(B->call(p->tb, "deep", (wasmext_val[]){I32(1)}, 1, &r, 1), main_thread));
            CLEAN(A, a0); CLEAN(B, b0);
            CHECK(is_stack_trap(B->call(p->tb, "calln", (wasmext_val[]){I32(1), I32(5)}, 2, &r, 1), main_thread));
            CLEAN(A, a0); CLEAN(B, b0);
            CHECK(is_stack_trap(A->call(p->ta, "calln", (wasmext_val[]){I32(1), I32(6)}, 2, &r, 1), main_thread));
            CLEAN(A, a0); CLEAN(B, b0);
        }
        CHECK(call_i32(A, p->ta, "div", 9, 3, 2) == 3 && call_i32(B, p->tb, "call", 0, 0, 1) == 7);
    }
}
static void *signals_fresh(void *arg) {
    signal_cases((struct pair *)arg, 0);
    A->thread_free();
    B->thread_free();
    return NULL;
}
/* two threads on one store, each trapping by signal, in opposite directions (one enters by B and faults in A, the other enters by A and faults in B), and recursion in turns */
static void *signals_toward_a(void *arg) {
    struct pair *p = (struct pair *)arg;
    wasmext_val r = I32(0);
    A->thread_ready();
    B->thread_ready();
    for (int k = 0; k < 150; k++) {
        CHECK(B->call(p->tb, "calln", (wasmext_val[]){I32(1 << 20), I32(4)}, 2, &r, 1) == (int)WASM_RT_TRAP_OOB);
        if (RECURSION && k % 25 == 0) CHECK(B->call(p->tb, "calln", (wasmext_val[]){I32(1), I32(5)}, 2, &r, 1) != 0);
        CHECK(call_i32(B, p->tb, "call", 0, 0, 1) == 7);
    }
    A->thread_free();
    B->thread_free();
    return NULL;
}
static void *signals_toward_b(void *arg) {
    struct pair *p = (struct pair *)arg;
    wasmext_val r = I32(0);
    A->thread_ready();
    B->thread_ready();
    for (int k = 0; k < 150; k++) {
        CHECK(A->call(p->ta, "calln", (wasmext_val[]){I32(1 << 20), I32(7)}, 2, &r, 1) == (int)WASM_RT_TRAP_OOB);
        if (RECURSION && k % 25 == 0) CHECK(A->call(p->ta, "calln", (wasmext_val[]){I32(1), I32(6)}, 2, &r, 1) != 0);
        CHECK(call_i32(A, p->ta, "call", 0, 0, 1) == 7);
    }
    A->thread_free();
    B->thread_free();
    return NULL;
}
/* A fresh process: the store is made by A, B attaches, and the thread calls only through B (an instance of `solob`, which imports nothing of A): A is never made ready on the thread, its handler is
   never installed, and a fault in B's code reaches B's handler with `tls.rt` = A's table and `tls.top` NULL (the entry went into A's runtime): only the `rt` half of the condition traps it. */
static wasmext_store *only_store;
static wasmext_instance *only_inst;
static void only_b_cases(int main_thread) {
    wasmext_val r = I32(0);
    cstate b0 = state_of(B);
    CHECK(B->call(only_inst, "ld", (wasmext_val[]){I32(0)}, 1, &r, 1) == 0);
    for (int k = 0; k < 3; k++) {
        CHECK(B->call(only_inst, "ld", (wasmext_val[]){I32(1 << 20)}, 1, &r, 1) == (int)WASM_RT_TRAP_OOB);
        CLEAN(B, b0);
        if (RECURSION) CHECK(is_stack_trap(B->call(only_inst, "deep", (wasmext_val[]){I32(1)}, 1, &r, 1), main_thread));
        CLEAN(B, b0);
        CHECK(B->call(only_inst, "ld", (wasmext_val[]){I32(0)}, 1, &r, 1) == 0);
    }
}
static void *only_b_thread(void *arg) {
    (void)arg;
    only_b_cases(0);
    B->thread_free();
    return NULL;
}
static void test_only_b(void) {
    pthread_t t;
    int error = 0;
    char why[200];
    only_store = A->store_new();
    CHECK(only_store != NULL && B->store_attach(only_store, why, sizeof why) == WASMEXT_STORE_OK);
    only_inst = B->instance_new(only_store, "solob", &error);
    CHECK(only_inst != NULL && B->instantiate(only_inst) == 0);
    only_b_cases(1);
    pthread_create(&t, NULL, only_b_thread, NULL);
    pthread_join(t, NULL);
    CHECK(A->store_free(only_store) == WASMEXT_STORE_OK);
}
static void test_signals_across_copies(void) {
    for (int variant = 0; variant < 2; variant++) { /* the store made by A and then by B: the entry is the copy of the runtime of the store, and the copy that is not */
        struct pair p;
        pthread_t t[2];
        pair_new(&p, variant ? B : A, variant ? A : B);
        signal_cases(&p, 1); /* the thread of the test is the main thread of the process (on it a stack overflow is EXHAUSTION in every mode) */
        pthread_create(&t[0], NULL, signals_fresh, &p);
        pthread_join(t[0], NULL);
        pthread_create(&t[0], NULL, signals_toward_a, &p);
        pthread_create(&t[1], NULL, signals_toward_b, &p);
        pthread_join(t[0], NULL);
        pthread_join(t[1], NULL);
        CHECK(A->store_free(p.s) == WASMEXT_STORE_OK);
    }
}
#endif

/* 8b-2: the runtime functions that the core calls outside a call of WebAssembly code (memory_grow, the table functions, the close of a member) go through the runtime of the store, whichever copy
   calls them. The runtime of the store is a copy of A's table whose functions count (and call A's); the operations are made by B, the copy that is not the runtime. */
enum { N_FREE_TABLE, N_FREE_MEMORY, N_GROW_MEMORY, N_ALLOC_TABLE, N_GROW_TABLE, N_ALLOC_XTABLE, N_GROW_XTABLE, N_FREE_XTABLE, N_COUNTERS };
static int hits[N_COUNTERS];
static wasmext_runtime counting_rt;
static void (*real_free_table)(wasm_rt_funcref_table_t *);
static void (*real_free_memory)(wasm_rt_memory_t *);
static uint64_t (*real_grow_memory)(wasm_rt_memory_t *, uint64_t);
static void (*real_alloc_table)(wasm_rt_funcref_table_t *, uint32_t, uint32_t);
static uint32_t (*real_grow_table)(wasm_rt_funcref_table_t *, uint32_t, wasm_rt_funcref_t);
static void (*real_alloc_xtable)(wasm_rt_externref_table_t *, uint32_t, uint32_t);
static uint32_t (*real_grow_xtable)(wasm_rt_externref_table_t *, uint32_t, wasm_rt_externref_t);
static void (*real_free_xtable)(wasm_rt_externref_table_t *);
static void c_free_table(wasm_rt_funcref_table_t *t) { hits[N_FREE_TABLE]++; real_free_table(t); }
static void c_free_memory(wasm_rt_memory_t *m) { hits[N_FREE_MEMORY]++; real_free_memory(m); }
static uint64_t c_grow_memory(wasm_rt_memory_t *m, uint64_t p) { hits[N_GROW_MEMORY]++; return real_grow_memory(m, p); }
static void c_alloc_table(wasm_rt_funcref_table_t *t, uint32_t e, uint32_t x) { hits[N_ALLOC_TABLE]++; real_alloc_table(t, e, x); }
static uint32_t c_grow_table(wasm_rt_funcref_table_t *t, uint32_t d, wasm_rt_funcref_t i) { hits[N_GROW_TABLE]++; return real_grow_table(t, d, i); }
static void c_alloc_xtable(wasm_rt_externref_table_t *t, uint32_t e, uint32_t x) { hits[N_ALLOC_XTABLE]++; real_alloc_xtable(t, e, x); }
static uint32_t c_grow_xtable(wasm_rt_externref_table_t *t, uint32_t d, wasm_rt_externref_t i) { hits[N_GROW_XTABLE]++; return real_grow_xtable(t, d, i); }
static void c_free_xtable(wasm_rt_externref_table_t *t) { hits[N_FREE_XTABLE]++; real_free_xtable(t); }
/* a store of A whose runtime is the counting one, and B attached */
static wasmext_store *counting_store(void) {
    wasmext_store *s = A->store_new();
    char why[200];
    memcpy(&counting_rt, A->runtime_id(), sizeof counting_rt);
    real_free_table = counting_rt.free_funcref_table; counting_rt.free_funcref_table = c_free_table;
    real_free_memory = counting_rt.free_memory; counting_rt.free_memory = c_free_memory;
    real_grow_memory = counting_rt.grow_memory; counting_rt.grow_memory = c_grow_memory;
    real_alloc_table = counting_rt.allocate_funcref_table; counting_rt.allocate_funcref_table = c_alloc_table;
    real_grow_table = counting_rt.grow_funcref_table; counting_rt.grow_funcref_table = c_grow_table;
    real_alloc_xtable = counting_rt.allocate_externref_table; counting_rt.allocate_externref_table = c_alloc_xtable;
    real_grow_xtable = counting_rt.grow_externref_table; counting_rt.grow_externref_table = c_grow_xtable;
    real_free_xtable = counting_rt.free_externref_table; counting_rt.free_externref_table = c_free_xtable;
    memset(hits, 0, sizeof hits);
    s->head.rt = &counting_rt;
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK);
    return s;
}

static void test_close_scope(void) {
    wasmext_store *s = counting_store();
    wasmext_instance *ownb, *la;
    int error = 0;
    ownb = B->instance_new(s, "ownb", &error);
    la = A->instance_new(s, "liba", &error);
    CHECK(ownb && la && B->instantiate(ownb) == 0 && A->instantiate(la) == 0);
    CHECK(hits[N_FREE_TABLE] == 0 && hits[N_FREE_MEMORY] == 0);
    CHECK(A->store_close(s) == WASMEXT_STORE_OK);
    /* ownb has one table, liba one table and one memory: three frees, all through the runtime of the store, the instance of the other copy included */
    CHECK(hits[N_FREE_TABLE] == 2 && hits[N_FREE_MEMORY] == 1);
    CHECK(A->store_free(s) == WASMEXT_STORE_OK);
}

/* B grows a memory, makes and grows tables of both kinds, and the store is closed with them in it: each of these goes through the runtime of the store */
static void test_scopes(void) {
    wasmext_store *s = counting_store();
    wasmext_instance *m;
    wasmext_tab *ft, *xt;
    int error = 0;
    uint32_t before = 0;
    m = B->instance_new(s, "memb", &error);
    CHECK(m && B->instantiate(m) == 0);
    CHECK(B->mem_grow(m, "mem", 1) == 1 && hits[N_GROW_MEMORY] == 1); /* the memory had 1 page */
    ft = B->tab_make(s, 0x70, &error);
    CHECK(ft != NULL && hits[N_ALLOC_TABLE] == 1);
    xt = B->tab_make(s, 0x6F, &error);
    CHECK(xt != NULL && hits[N_ALLOC_XTABLE] == 1);
    CHECK(B->tab_grow(ft, 1, &before) == 0 && before == 2 && hits[N_GROW_TABLE] == 1);
    CHECK(B->tab_grow(xt, 1, &before) == 0 && before == 2 && hits[N_GROW_XTABLE] == 1);
    CHECK(hits[N_FREE_TABLE] == 0 && hits[N_FREE_XTABLE] == 0);
    CHECK(A->store_close(s) == WASMEXT_STORE_OK);
    CHECK(hits[N_FREE_TABLE] == 1 && hits[N_FREE_XTABLE] == 1 && hits[N_FREE_MEMORY] == 1); /* the host tables and the memory of the instance */
    CHECK(A->store_free(s) == WASMEXT_STORE_OK);
}

/* attach during a call in flight is refused: the artifact would never be activated for that call (S0008); it works once the call has returned */
struct attacher { wasmext_store *s; int rc; char why[200]; wasmext_counter seen; };
static int host_attach(void *user, const wasmext_val *args, wasmext_val *results) {
    struct attacher *a = (struct attacher *)user;
    (void)args;
    a->rc = B->store_attach(a->s, a->why, sizeof a->why);
    results[0] = I32(1);
    return 0;
}
static void test_attach_in_a_call(void) {
    struct attacher at;
    wasmext_store *s = A->store_new();
    wasmext_instance *na, *tb;
    wasmext_val a = I32(1), r = I32(0);
    char why[200];
    int error = 0;
    memset(&at, 0, sizeof at);
    at.s = s;
    na = A->instance_new(s, "nesta", &error);
    CHECK(na && A->bind_host(na, "na", "cb", host_attach, &at) == 0 && A->instantiate(na) == 0);
    CHECK(A->call(na, "rec", &a, 1, &r, 1) == 0 && r.as.i32 == 1);
    CHECK(at.rc == WASMEXT_STORE_BUSY && strstr(at.why, "a call is in flight") != NULL);
    CHECK(wasmext_atomic_load(&s->n_artifacts) == 1 && B->instance_new(s, "trapb", &error) == NULL && error == EXDEV);
    CHECK(B->store_attach(s, why, sizeof why) == WASMEXT_STORE_OK && wasmext_atomic_load(&s->n_artifacts) == 2);
    tb = B->instance_new(s, "memb", &error);
    CHECK(tb != NULL);
    CHECK(A->store_free(s) == WASMEXT_STORE_OK);
}

int main(int argc, char **argv) {
    A = artifact_a();
    B = artifact_b();
#ifndef TEST_MODE_STOCK
    if (argc > 1 && strcmp(argv[1], "only_b") == 0) { /* a process of its own: nothing here may make A ready on the thread */
        test_only_b();
        if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
        puts("ok");
        return 0;
    }
#endif
    (void)argc; (void)argv;
    test_seeds();
    test_two_copies();
    test_attach();
    test_attach_runtime();
    test_forwarders_across_copies();
    test_serials();
    test_store_only();
    test_one_store();
    test_the_other_way();
    test_references_through_links();
    test_host_tags();
    test_host_tags_threads();
    test_traps_across_copies();
#ifndef TEST_MODE_STOCK
    test_signals_across_copies();
#endif
    test_close_scope();
    test_scopes();
    test_attach_in_a_call();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
