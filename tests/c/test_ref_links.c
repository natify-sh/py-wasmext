/* Links of functions with a funcref or an externref in the signature (docs/specs/S0008-shared-store.md, 8a-2) in plain C: the letters F and E in the record, the call through the shim
   with the reference by value, the checks where a reference comes in (the shim) and where it comes out (the importer), a trap of the callee, and what is still refused.
   Three real wasm2c modules (`rlib` exports, `rapp` imports, `rbad` has imports that do not fit). */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_table.h"

extern const wasmext_binding rlib_binding, rapp_binding, rbad_binding;

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static wasmext_val I32(int32_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7F; x.as.i32 = v; return x; }
static wasmext_val I64(int64_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7E; x.as.i64 = v; return x; }
static wasmext_val REF(wasmext_funcref *f) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x70; x.as.ref = f; return x; }
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
static int funcref_of(wasmext_instance *i, const char *name, wasmext_funcref *f) { return wasmext_instance_funcref(i, (uint32_t)export_of(i, name, WASMEXT_DESC_FUNC), f); }
static int record_of(wasmext_instance *lib, const char *name, wasmext_export *rec) { return wasmext_instance_export_record(lib, (uint32_t)export_of(lib, name, WASMEXT_DESC_FUNC), NULL, rec); }
static int link_to(wasmext_instance *app, const char *module, const char *name, wasmext_instance *lib, const char *export_name) {
    wasmext_export rec;
    int rc = record_of(lib, export_name, &rec);
    return rc != 0 ? rc : wasmext_instance_bind_export(app, (uint32_t)import_of(app, module, name), &rec);
}

typedef struct { int released; int id; } item_t;
static void item_release(void *user) { ((item_t *)user)->released++; }
static wasmext_extern *give(wasmext_store *s, item_t *it) {
    wasmext_extern *e = NULL;
    return wasmext_extern_new(s, it, item_release, &e) == 0 ? e : NULL;
}

static void link_all(wasmext_instance *app, wasmext_instance *lib) {
    static const char *const names[] = {"fident", "eident", "mixed", "getf", "boom", "isnull"};
    for (size_t k = 0; k < sizeof names / sizeof names[0]; k++) CHECK(link_to(app, "libr", names[k], lib, names[k]) == 0);
}

static void test_calls_through_links(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *lib = wasmext_instance_new(s, &rlib_binding, NULL), *app = wasmext_instance_new(s, &rapp_binding, NULL);
    wasmext_funcref nine, seven, back, back2;
    wasmext_val a[4], r[4];
    item_t it1 = {0, 1};
    wasmext_extern *e1;
    wasmext_export rec;
    CHECK(wasmext_instance_instantiate(lib) == 0);
    /* the letters of the record: F for a funcref, E for an externref, and they do not mix */
    CHECK(record_of(lib, "fident", &rec) == 0 && strcmp(rec.signature, "F>F") == 0);
    CHECK(record_of(lib, "eident", &rec) == 0 && strcmp(rec.signature, "E>E") == 0);
    CHECK(record_of(lib, "mixed", &rec) == 0 && strcmp(rec.signature, "iFEj>EjFi") == 0);
    link_all(app, lib);
    CHECK(wasmext_instance_instantiate(app) == 0);
    e1 = give(s, &it1);
    CHECK(e1 != NULL && funcref_of(app, "nine", &nine) == 0 && funcref_of(lib, "seven", &seven) == 0);
    /* a funcref in and out: the same function, of the instance it belongs to; a null one stays null */
    a[0] = REF(&nine); r[0] = REF(&back);
    CHECK(call(app, "fi", a, 1, r, 1) == 0 && back.ref.func == nine.ref.func && back.owner == app->owner && back.store == s);
    a[0] = REF(NULL); r[0] = REF(&back);
    CHECK(call(app, "fi", a, 1, r, 1) == 0 && back.ref.func == NULL);
    a[0] = REF(&nine);
    CHECK(call(app, "isn", a, 1, r, 1) == 0 && r[0].as.i32 == 0);
    a[0] = REF(NULL);
    CHECK(call(app, "isn", a, 1, r, 1) == 0 && r[0].as.i32 == 1);
    /* a funcref that wasm makes (ref.func) and sends through the link */
    r[0] = REF(&back);
    CHECK(call(app, "fnine", NULL, 0, r, 1) == 0 && back.ref.func != NULL && back.ref.module_instance == nine.ref.module_instance && back.owner == app->owner); /* (ref.func names the function itself, the export its wrapper: the instance is what is compared) */
    /* an externref in and out: the same pointer, and the host reads its value */
    a[0] = XREF(e1); r[0].type = 0;
    CHECK(call(app, "ei", a, 1, r, 1) == 0 && r[0].type == 0x6F && r[0].as.ref == e1 && wasmext_extern_user(r[0].as.ref) == &it1);
    a[0] = XREF(NULL);
    CHECK(call(app, "ei", a, 1, r, 1) == 0 && r[0].as.ref == NULL);
    /* numbers, a funcref and an externref in, several results out, in order */
    a[0] = I32(5); a[1] = REF(&nine); a[2] = XREF(e1); a[3] = I64(77);
    r[0] = XREF(NULL); r[1] = I64(0); r[2] = REF(&back2); r[3] = I32(0);
    CHECK(call(app, "mx", a, 4, r, 4) == 0);
    CHECK(r[0].type == 0x6F && r[0].as.ref == e1 && r[1].type == 0x7E && r[1].as.i64 == 77 && r[2].type == 0x70 && r[3].type == 0x7F && r[3].as.i32 == 5);
    CHECK(back2.ref.func == nine.ref.func && back2.owner == app->owner);
    /* the funcref that comes out of the callee belongs to the callee's instance and can be used: call_ref, and a table element called by call_indirect */
    r[0] = REF(&back);
    CHECK(call(app, "gf", NULL, 0, r, 1) == 0 && back.ref.func != NULL && back.ref.module_instance == seven.ref.module_instance && back.owner == lib->owner && back.owner != app->owner);
    r[0] = I32(0);
    CHECK(wasmext_instance_call_ref(app, &back, NULL, 0, r, 1) == 0 && r[0].as.i32 == 7);
    CHECK(wasmext_instance_table_set(app, (uint32_t)export_of(app, "tab", WASMEXT_DESC_TABLE), 2, &back) == 0);
    a[0] = I32(2);
    CHECK(call(app, "callslot", a, 1, r, 1) == 0 && r[0].as.i32 == 7);
    wasmext_store_free(s);
    CHECK(it1.released == 1);
}

/* a trap of the callee goes through the link with its code, and both instances are usable after it */
static void test_a_trap_in_the_callee(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *lib = wasmext_instance_new(s, &rlib_binding, NULL), *app = wasmext_instance_new(s, &rapp_binding, NULL);
    item_t it1 = {0, 1};
    wasmext_extern *e1;
    wasmext_val a[1], r[1];
    wasmext_export rec;
    typedef void *(*eshim_t)(void *, void *, int *);
    int trapped = 0;
    CHECK(wasmext_instance_instantiate(lib) == 0);
    link_all(app, lib);
    CHECK(wasmext_instance_instantiate(app) == 0);
    e1 = give(s, &it1);
    a[0] = XREF(e1);
    CHECK(call(app, "bm", a, 1, r, 1) == (int)WASM_RT_TRAP_UNREACHABLE);
    CHECK(call(app, "ei", a, 1, r, 1) == 0 && r[0].as.ref == e1);
    /* the shim itself answers WASMEXT_TRAP_LINKED + the code */
    CHECK(record_of(lib, "boom", &rec) == 0);
    ((eshim_t)rec.address)(rec.instance, e1, &trapped);
    CHECK(trapped == WASMEXT_TRAP_LINKED + (int)WASM_RT_TRAP_UNREACHABLE);
    wasmext_store_free(s);
}

/* a reference that comes into the shim is checked there: a pointer that is not a reference of the store is WASMEXT_TAB_WRONG_STORE, a funcref that no member stands behind WASMEXT_TAB_STALE */
static void test_the_shim_checks_what_comes_in(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *lib = wasmext_instance_new(s, &rlib_binding, NULL), *app = wasmext_instance_new(s, &rapp_binding, NULL);
    item_t it1 = {0, 1}, it2 = {0, 2};
    wasmext_extern *e1, *foreign;
    wasmext_funcref nine;
    wasmext_export rec;
    typedef void *(*eshim_t)(void *, void *, int *);
    typedef wasm_rt_funcref_t (*fshim_t)(void *, wasm_rt_funcref_t, int *);
    int trapped, not_a_reference = 5;
    wasm_rt_funcref_t forged, got;
    CHECK(wasmext_instance_instantiate(lib) == 0);
    link_all(app, lib);
    CHECK(wasmext_instance_instantiate(app) == 0);
    e1 = give(s, &it1);
    foreign = give(other, &it2);
    CHECK(e1 != NULL && foreign != NULL && funcref_of(app, "nine", &nine) == 0);
    CHECK(record_of(lib, "eident", &rec) == 0);
    trapped = 77;
    CHECK(((eshim_t)rec.address)(rec.instance, e1, &trapped) == e1 && trapped == 77); /* untouched when the call is made: the shim sets *trapped only on a failure */
    trapped = 0;
    ((eshim_t)rec.address)(rec.instance, foreign, &trapped);
    CHECK(trapped == WASMEXT_TAB_WRONG_STORE);
    trapped = 0;
    ((eshim_t)rec.address)(rec.instance, &not_a_reference, &trapped);
    CHECK(trapped == WASMEXT_TAB_WRONG_STORE);
    trapped = 0;
    CHECK(((eshim_t)rec.address)(rec.instance, NULL, &trapped) == NULL && trapped == 0);
    CHECK(record_of(lib, "fident", &rec) == 0);
    trapped = 0;
    got = ((fshim_t)rec.address)(rec.instance, nine.ref, &trapped);
    CHECK(trapped == 0 && got.func == nine.ref.func && got.module_instance == nine.ref.module_instance);
    forged = nine.ref;
    forged.module_instance = &not_a_reference;
    trapped = 0;
    ((fshim_t)rec.address)(rec.instance, forged, &trapped);
    CHECK(trapped == WASMEXT_TAB_STALE);
    wasmext_store_free(s);
    wasmext_store_free(other);
}

/* what is still refused: a signature that differs in the letter, and a typed host function with a reference */
static void test_refusals(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *lib = wasmext_instance_new(s, &rlib_binding, NULL), *bad = wasmext_instance_new(s, &rbad_binding, NULL), *bad2 = wasmext_instance_new(s, &rbad_binding, NULL);
    char text[WASMEXT_STORE_ERROR_SIZE];
    CHECK(wasmext_instance_instantiate(lib) == 0);
    /* the import wants F>F, the export is E>E; and the other way round */
    CHECK(link_to(bad, "libb", "eident", lib, "eident") == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "libb.eident") != NULL && strstr(text, "F>F") != NULL && strstr(text, "E>E") != NULL);
    CHECK(link_to(bad, "libb2", "fident", lib, "fident") == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "libb2.fident") != NULL && strstr(text, "E>E") != NULL && strstr(text, "F>F") != NULL);
    /* the letters are the whole check: the same shapes link */
    CHECK(link_to(bad, "libb", "eident", lib, "fident") == 0);
    CHECK(link_to(bad, "libb2", "fident", lib, "eident") == 0);
    /* a typed function of the host (FFIs cannot pass a struct by value) is refused for an import with a reference: the uniform shape is the way */
    CHECK(wasmext_instance_bind_typed(bad2, (uint32_t)import_of(bad2, "libb", "eident"), (void *)link_all, NULL) == WASMEXT_INST_UNSUPPORTED);
    CHECK(wasmext_instance_bind_typed(bad2, (uint32_t)import_of(bad2, "libb2", "fident"), (void *)link_all, NULL) == WASMEXT_INST_UNSUPPORTED);
    wasmext_store_free(s);
}

int main(void) {
    test_calls_through_links();
    test_a_trap_in_the_callee();
    test_the_shim_checks_what_comes_in();
    test_refusals();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
