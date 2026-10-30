/* One artifact of tests/test_artifacts.py: this file, the modules of `modules.inc` (MODULE(name) lines, made by the test) and a copy of the runtime of wasm2c, built as a shared
   library. `ARTIFACT_NAME` names the function that returns the table of the copy. */
#define WASMEXT_DEFINE_THREAD_STATE
#include "wasmext_table.h"
#include "artifact.h"

#define MODULE(n) extern const wasmext_binding n##_binding;
#include "modules.inc"
#undef MODULE
static const struct { const char *name; const wasmext_binding *binding; } modules_[] = {
#define MODULE(n) {#n, &n##_binding},
#include "modules.inc"
#undef MODULE
};

static const void *trap_address_(void) { return (const void *)&wasm_rt_trap; }
static wasmext_store *store_new_(void) { return wasmext_store_new(); }
static int store_attach_(wasmext_store *s, char *why, size_t cap) { return wasmext_store_attach(s, why, cap); }
static int store_close_(wasmext_store *s) { return wasmext_store_close(s); }
static int store_free_(wasmext_store *s) { return wasmext_store_free(s); }

static wasmext_counter released_; /* the releases of this copy */
static void release_(void *object) { (void)object; wasmext_atomic_add(&released_, 1); }
static int store_own_(wasmext_store *s) { return wasmext_store_own(s, (void *)&released_, release_); }
static long releases_(void) { return (long)wasmext_atomic_load(&released_); }
static void store_error_(wasmext_store *s, char *buffer, size_t cap) { wasmext_store_error(s, buffer, cap); }

static wasmext_instance *instance_new_(wasmext_store *s, const char *module, int *error) {
    for (size_t k = 0; k < sizeof modules_ / sizeof modules_[0]; k++)
        if (strcmp(modules_[k].name, module) == 0) return wasmext_instance_new(s, modules_[k].binding, error);
    *error = ENOENT;
    return NULL;
}
static int instantiate_(wasmext_instance *i) { return wasmext_instance_instantiate(i); }
static int export_of_(wasmext_instance *i, const char *name, int kind) { return wasmext_instance_export_find(i, name, strlen(name), kind); }
static int call_(wasmext_instance *i, const char *name, const wasmext_val *a, uint32_t na, wasmext_val *r, uint32_t nr) {
    int k = export_of_(i, name, WASMEXT_DESC_FUNC);
    return k < 0 ? WASMEXT_INST_BAD_EXPORT : wasmext_instance_call(i, (uint32_t)k, a, na, r, nr);
}
static int export_record_(wasmext_instance *i, const char *name, int kind, wasmext_export *out) {
    int k = export_of_(i, name, kind);
    return k < 0 ? WASMEXT_INST_BAD_EXPORT : wasmext_instance_export_record(i, (uint32_t)k, NULL, out);
}
static int bind_(wasmext_instance *i, const char *module, const char *name, const wasmext_export *record) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_imports; k++)
        if (d->imports[k].module.n == strlen(module) && memcmp(d->imports[k].module.p, module, d->imports[k].module.n) == 0 && d->imports[k].name.n == strlen(name) &&
            memcmp(d->imports[k].name.p, name, d->imports[k].name.n) == 0)
            return wasmext_instance_bind_export(i, k, record);
    return WASMEXT_INST_BAD_IMPORT;
}
static int funcref_(wasmext_instance *i, const char *name, wasmext_funcref *out) {
    int k = export_of_(i, name, WASMEXT_DESC_FUNC);
    return k < 0 ? WASMEXT_INST_BAD_EXPORT : wasmext_instance_funcref(i, (uint32_t)k, out);
}
static int table_set_(wasmext_instance *i, const char *name, uint32_t index, const wasmext_funcref *f) {
    int k = export_of_(i, name, WASMEXT_DESC_TABLE);
    return k < 0 ? WASMEXT_INST_BAD_EXPORT : wasmext_instance_table_set(i, (uint32_t)k, index, f);
}
static int global_set_funcref_(wasmext_instance *i, const char *name, const wasmext_funcref *f) {
    wasmext_val v;
    int k = export_of_(i, name, WASMEXT_DESC_GLOBAL);
    if (k < 0) return WASMEXT_INST_BAD_EXPORT;
    memset(&v, 0, sizeof v);
    v.type = 0x70;
    v.as.ref = (void *)f;
    return wasmext_instance_global_set(i, (uint32_t)k, &v);
}
static struct wasmext_tab_s_ *tab_new_(wasmext_store *s, int *error) { return wasmext_tab_new(s, 0x70, 2, WASMEXT_TABLE_NO_MAXIMUM, error); }
static int tab_set_(struct wasmext_tab_s_ *t, uint32_t index, const wasmext_funcref *f) { return wasmext_tab_set(t, index, f); }
static int tab_get_(struct wasmext_tab_s_ *t, uint32_t index, wasmext_funcref *out) { return wasmext_tab_get(t, index, out); }

static int call_ref_(wasmext_instance *i, const wasmext_funcref *f, wasmext_val *results, uint32_t n_results) { return wasmext_instance_call_ref(i, f, NULL, 0, results, n_results); }
static int bind_host_(wasmext_instance *i, const char *module, const char *name, wasmext_host_fn fn, void *user) {
    int k = wasmext_instance_import_find(i, module, strlen(module), name, strlen(name));
    return k < 0 ? WASMEXT_INST_BAD_IMPORT : wasmext_instance_bind_func(i, (uint32_t)k, fn, user);
}
static int bind_global_funcref_(wasmext_instance *i, const char *module, const char *name, const wasmext_funcref *f) {
    wasmext_val v;
    const wasmext_descriptor *d = i->binding->descriptor;
    memset(&v, 0, sizeof v);
    v.type = 0x70;
    v.as.ref = (void *)f;
    for (uint32_t k = 0; k < d->n_imports; k++)
        if (d->imports[k].kind == WASMEXT_DESC_GLOBAL && d->imports[k].module.n == strlen(module) && memcmp(d->imports[k].module.p, module, d->imports[k].module.n) == 0 &&
            d->imports[k].name.n == strlen(name) && memcmp(d->imports[k].name.p, name, d->imports[k].name.n) == 0)
            return wasmext_instance_bind_global_value(i, k, &v);
    return WASMEXT_INST_BAD_IMPORT;
}
static int host_funcref_(wasmext_instance *i, wasmext_host_fn fn, wasmext_funcref *out) {
    static const uint8_t result[1] = {0x7F};
    return wasmext_instance_host_funcref(i, NULL, 0, result, 1, fn, NULL, NULL, out);
}

static int extern_new_(wasmext_store *s) {
    wasmext_extern *e = NULL;
    return wasmext_extern_new(s, NULL, NULL, &e);
}
static wasmext_extern *extern_make_(wasmext_store *s, void *user) {
    wasmext_extern *e = NULL;
    return wasmext_extern_new(s, user, NULL, &e) == 0 ? e : NULL;
}
static void no_free_(void *object) { (void)object; }
static int store_misc_(wasmext_store *s, int which) {
    static char object_;
    wasmext_owner owner;
    if (which == 0) return wasmext_store_adopt(s, &object_, no_free_);
    if (which == 1) return wasmext_store_register(s, &object_, &object_, NULL, &owner);
    return wasmext_store_set_host(s, &object_, no_free_, NULL);
}

static int tag_new_(wasmext_store *s, const uint8_t *types, uint32_t n, wasmext_export *out) { return wasmext_tag_new(s, types, n, out); }
static void *volatile *tag_cell_(wasmext_instance *i) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_imports; k++)
        if (d->imports[k].kind == WASMEXT_DESC_TAG) return (void *volatile *)i->binding->ref_slot(i->module, k);
    return NULL;
}

static const artifact_api api_ = {
    (const void *)&wasmext_artifact_, trap_address_, store_new_, store_attach_, store_close_, store_free_, store_own_, releases_, store_error_, instance_new_, instantiate_, call_,
    export_record_, bind_, funcref_, table_set_, global_set_funcref_, tab_new_, tab_set_, tab_get_, wasmext_thread_free, call_ref_, bind_host_, bind_global_funcref_, host_funcref_, extern_new_, store_misc_, artifact_so_new, artifact_so_attach, extern_make_, tag_new_, tag_cell_};

#define ARTIFACT_CAT_(a, b) a##b
#define ARTIFACT_CAT(a, b) ARTIFACT_CAT_(a, b)
#ifdef _WIN32
__declspec(dllexport)
#else
__attribute__((visibility("default")))
#endif
const artifact_api *ARTIFACT_CAT(artifact_, ARTIFACT_NAME)(void) { return &api_; }
