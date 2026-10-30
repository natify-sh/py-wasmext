/* Globals of funcref and of externref (docs/step6_externref.md, 6c): read and written by the host and by the module, shared between instances, given a value by the host when they are
   immutable imports, and what a failed start leaves in a shared global of funcref. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_table.h"

extern const wasmext_binding rg_binding, ri_binding, rt_binding;

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static wasmext_val I32(int32_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7F; x.as.i32 = v; return x; }
static wasmext_val XREF(void *p) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x6F; x.as.ref = p; return x; }
static wasmext_val FREF(wasmext_funcref *f) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x70; x.as.ref = f; return x; }
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
static int32_t value(wasmext_instance *i, const char *name) { wasmext_val r; return call(i, name, NULL, 0, &r, 1) == 0 ? r.as.i32 : -99999; }
static int funcref_of(wasmext_instance *i, const char *name, wasmext_funcref *f) { return wasmext_instance_funcref(i, (uint32_t)export_of(i, name, WASMEXT_DESC_FUNC), f); }
static int link_global(wasmext_instance *importer, const char *module, const char *name, wasmext_instance *exporter, const char *export_name) {
    wasmext_export rec;
    int rc = wasmext_instance_export_record(exporter, (uint32_t)export_of(exporter, export_name, WASMEXT_DESC_GLOBAL), NULL, &rec);
    return rc != 0 ? rc : wasmext_instance_bind_export(importer, (uint32_t)import_of(importer, module, name), &rec);
}

typedef struct { int released; } item_t;
static void item_release(void *user) { ((item_t *)user)->released++; }
static wasmext_extern *give(wasmext_store *s, item_t *it) {
    wasmext_extern *e = NULL;
    return wasmext_extern_new(s, it, item_release, &e) == 0 ? e : NULL;
}

static void test_globals(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *rg = wasmext_instance_new(s, &rg_binding, NULL), *ri = wasmext_instance_new(s, &ri_binding, NULL), *bad = wasmext_instance_new(s, &rt_binding, NULL);
    wasmext_instance *stranger = wasmext_instance_new(other, &rg_binding, NULL);
    item_t a1 = {0}, a2 = {0}, b1 = {0};
    wasmext_extern *e1, *e2, *foreign;
    wasmext_funcref f5, back, foreign_f;
    wasmext_val v, r;
    uint32_t GX, GF;
    CHECK(wasmext_instance_instantiate(rg) == 0 && wasmext_instance_instantiate(stranger) == 0);
    e1 = give(s, &a1); e2 = give(s, &a2); foreign = give(other, &b1);
    GX = (uint32_t)export_of(rg, "gx", WASMEXT_DESC_GLOBAL);
    GF = (uint32_t)export_of(rg, "gf", WASMEXT_DESC_GLOBAL);
    CHECK(funcref_of(rg, "f", &f5) == 0 && funcref_of(stranger, "f", &foreign_f) == 0);
    /* externref: empty at first, written by the host, read by the module, written by the module, read by the host */
    memset(&v, 0, sizeof v);
    CHECK(wasmext_instance_global_get(rg, GX, &v) == 0 && v.type == 0x6F && v.as.ref == NULL);
    v = XREF(e1);
    CHECK(wasmext_instance_global_set(rg, GX, &v) == 0);
    CHECK(call(rg, "getgx", NULL, 0, &r, 1) == 0 && r.as.ref == e1);
    v = XREF(e2);
    CHECK(call(rg, "setgx", &v, 1, NULL, 0) == 0);
    memset(&v, 0, sizeof v);
    CHECK(wasmext_instance_global_get(rg, GX, &v) == 0 && v.as.ref == e2);
    /* what goes in is a reference of the store, and of the type of the global */
    v = XREF(foreign);
    CHECK(wasmext_instance_global_set(rg, GX, &v) == WASMEXT_TAB_WRONG_STORE);
    v = XREF((char *)e1 + 1);
    CHECK(wasmext_instance_global_set(rg, GX, &v) == WASMEXT_TAB_WRONG_STORE);
    v = I32(1);
    CHECK(wasmext_instance_global_set(rg, GX, &v) == WASMEXT_INST_BAD_ARGS);
    v = XREF(NULL);
    CHECK(wasmext_instance_global_set(rg, GX, &v) == 0);
    memset(&v, 0, sizeof v);
    CHECK(wasmext_instance_global_get(rg, GX, &v) == 0 && v.as.ref == NULL);
    /* funcref: the host reads into its own storage; null at first */
    v = FREF(&back);
    CHECK(wasmext_instance_global_get(rg, GF, &v) == 0 && v.type == 0x70 && v.as.ref == &back && back.ref.func == NULL && back.owner == 0);
    v = FREF(NULL);
    CHECK(wasmext_instance_global_get(rg, GF, &v) == WASMEXT_INST_BAD_ARGS);
    v = FREF(&f5);
    CHECK(wasmext_instance_global_set(rg, GF, &v) == 0);
    CHECK(value(rg, "callgf") == 5);
    v = FREF(&back);
    CHECK(wasmext_instance_global_get(rg, GF, &v) == 0 && back.ref.func == f5.ref.func && back.owner == rg->owner && back.store == s);
    v = FREF(&foreign_f);
    CHECK(wasmext_instance_global_set(rg, GF, &v) == WASMEXT_TAB_WRONG_STORE);
    v = FREF(NULL);
    CHECK(wasmext_instance_global_set(rg, GF, &v) == 0);
    v = FREF(&back);
    CHECK(wasmext_instance_global_get(rg, GF, &v) == 0 && back.ref.func == NULL);
    v = I32(0);
    CHECK(wasmext_instance_global_set(rg, GF, &v) == WASMEXT_INST_BAD_ARGS);
    /* another instance imports both globals, and is given the value of two immutable ones by the host */
    v = XREF(e1);
    CHECK(wasmext_instance_bind_global_value(ri, (uint32_t)import_of(ri, "genv", "ix"), &v) == 0);
    v = XREF(foreign);
    CHECK(wasmext_instance_bind_global_value(ri, (uint32_t)import_of(ri, "genv", "ix"), &v) == WASMEXT_TAB_WRONG_STORE);
    v = I32(1);
    CHECK(wasmext_instance_bind_global_value(ri, (uint32_t)import_of(ri, "genv", "ix"), &v) == WASMEXT_INST_BAD_ARGS);
    v = FREF(&foreign_f);
    CHECK(wasmext_instance_bind_global_value(ri, (uint32_t)import_of(ri, "genv", "if"), &v) == WASMEXT_TAB_WRONG_STORE);
    v = FREF(&f5);
    CHECK(wasmext_instance_bind_global_value(ri, (uint32_t)import_of(ri, "genv", "if"), &v) == 0);
    CHECK(link_global(ri, "gown", "gx", rg, "gx") == 0 && link_global(ri, "gown", "gf", rg, "gf") == 0);
    CHECK(wasmext_instance_instantiate(ri) == 0);
    CHECK(call(ri, "getix", NULL, 0, &r, 1) == 0 && r.as.ref == e1);
    v = FREF(&back);
    CHECK(call(ri, "getif", NULL, 0, &v, 1) == 0 && back.ref.func == f5.ref.func && back.owner == rg->owner);
    /* ... the mutable ones are the globals of the exporter: a write by one is seen by the other, the host included */
    v = XREF(e2);
    CHECK(call(ri, "setgx", &v, 1, NULL, 0) == 0);
    memset(&v, 0, sizeof v);
    CHECK(wasmext_instance_global_get(rg, GX, &v) == 0 && v.as.ref == e2);
    CHECK(call(ri, "setgf", NULL, 0, NULL, 0) == 0);
    CHECK(value(rg, "callgf") == 7); /* the function of the importer, put in the global of the exporter, is called by the exporter */
    v = FREF(&back);
    CHECK(wasmext_instance_global_get(rg, GF, &v) == 0 && back.owner == ri->owner);
    /* an instance that fails to start after it put a function of its own in the shared global: the global is empty again, not left with a function that is gone */
    v = FREF(&f5);
    CHECK(wasmext_instance_global_set(rg, GF, &v) == 0);
    CHECK(link_global(bad, "gtown", "gf", rg, "gf") == 0);
    CHECK(wasmext_instance_instantiate(bad) == (int)WASM_RT_TRAP_UNREACHABLE);
    v = FREF(&back);
    CHECK(wasmext_instance_global_get(rg, GF, &v) == 0 && back.ref.func == NULL);
    /* the close: each value is released once; then a global is not read */
    CHECK(a1.released == 0 && a2.released == 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK && a1.released == 1 && a2.released == 1);
    v = XREF(NULL);
    CHECK(wasmext_instance_global_set(rg, GX, &v) == (int)WASMEXT_TRAP_CLOSED);
    v = FREF(&back);
    CHECK(wasmext_instance_global_get(rg, GF, &v) == (int)WASMEXT_TRAP_CLOSED);
    wasmext_instance_free(bad);
    wasmext_store_free(s);
    wasmext_store_free(other);
}

int main(void) {
    test_globals();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
