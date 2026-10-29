/* Links between instances in plain C: the record of an export of one (`lib`) is given to an import of another (`app`), in one store and in two. Also the checks that
   refuse a record that does not fit (`tiny`, `big`: memories with other limits). Four real wasm2c modules. */
#include <stdio.h>
#define WASMEXT_DEFINE_THREAD_STATE
#include "wasmext_instance.h"

extern const wasmext_binding lib_binding, app_binding, tiny_binding, big_binding;

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static wasmext_val I32(int32_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7F; x.as.i32 = v; return x; }
static wasmext_val I64(int64_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7E; x.as.i64 = v; return x; }
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

/* gives the import app.<module>.<name> the record of lib.<export> of any kind */
static int link_to(wasmext_instance *app, const char *module, const char *name, wasmext_instance *lib, const char *export_name, int kind, void *owner) {
    wasmext_export rec;
    int rc = wasmext_instance_export_record(lib, (uint32_t)export_of(lib, export_name, kind), owner, &rec);
    if (rc != 0) return rc;
    return wasmext_instance_bind_export(app, (uint32_t)import_of(app, module, name), &rec);
}

static void link_all(wasmext_instance *app, wasmext_instance *lib, void *owner) {
    CHECK(link_to(app, "libx", "add", lib, "add", WASMEXT_DESC_FUNC, owner) == 0);
    CHECK(link_to(app, "libx", "div", lib, "div", WASMEXT_DESC_FUNC, owner) == 0);
    CHECK(link_to(app, "libx", "swap", lib, "swap", WASMEXT_DESC_FUNC, owner) == 0);
    CHECK(link_to(app, "libx", "vec", lib, "vec", WASMEXT_DESC_FUNC, owner) == 0);
    CHECK(link_to(app, "libx", "mem", lib, "mem", WASMEXT_DESC_MEMORY, owner) == 0);
    CHECK(link_to(app, "libx", "counter", lib, "counter", WASMEXT_DESC_GLOBAL, owner) == 0);
    CHECK(link_to(app, "libx", "ver", lib, "ver", WASMEXT_DESC_GLOBAL, owner) == 0);
    {
        wasmext_val k = I32(42);
        CHECK(wasmext_instance_bind_global_value(app, (uint32_t)import_of(app, "env", "k"), &k) == 0);
    }
}

static void test_two_instances_one_store(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *lib = wasmext_instance_new(s, &lib_binding, NULL), *app = wasmext_instance_new(s, &app_binding, NULL);
    wasmext_val a[2], r[2];
    wasmext_memory_view v;
    int owner_marker;
    char text[WASMEXT_STORE_ERROR_SIZE];
    /* nothing is linked yet: the importer says which import is missing */
    CHECK(wasmext_instance_instantiate(lib) == 0);
    CHECK(wasmext_instance_instantiate(app) == (int)WASMEXT_TRAP_LINK_ERROR);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "is not bound") != NULL);
    link_all(app, lib, &owner_marker);
    CHECK(wasmext_instance_import_owner(app, (uint32_t)import_of(app, "libx", "add")) == &owner_marker);
    CHECK(wasmext_instance_instantiate(app) == 0);
    /* functions: the call goes through the record into the other instance */
    a[0] = I32(2); a[1] = I32(3);
    CHECK(call(app, "call_add", a, 2, r, 1) == 0 && r[0].as.i32 == 5);
    a[0] = I32(1); a[1] = I64(9);
    CHECK(call(app, "call_swap", a, 2, r, 2) == 0 && r[0].type == 0x7E && r[0].as.i64 == 9 && r[1].as.i32 == 1);
    {
        wasmext_val x, y;
        int32_t in[4] = {1, 2, 3, 4}, out[4];
        memset(&x, 0, sizeof x); x.type = 0x7B; memcpy(x.as.v128, in, 16);
        CHECK(call(app, "call_vec", &x, 1, &y, 1) == 0);
        memcpy(out, y.as.v128, 16);
        CHECK(out[0] == 2 && out[3] == 8);
    }
    /* a trap in the other instance goes through with its code, and both are usable after it */
    a[0] = I32(7); a[1] = I32(0);
    CHECK(call(app, "call_div", a, 2, r, 1) == (int)WASM_RT_TRAP_DIV_BY_ZERO);
    a[0] = I32(7); a[1] = I32(2);
    CHECK(call(app, "call_div", a, 2, r, 1) == 0 && r[0].as.i32 == 3);
    CHECK(call(lib, "get_counter", NULL, 0, r, 1) == 0 && r[0].as.i32 == 10);
    /* the memory is one: a byte written by app is seen by lib, and the growth of one is the other's */
    a[0] = I32(100); a[1] = I32(77);
    CHECK(call(app, "poke", a, 2, NULL, 0) == 0);
    CHECK(wasmext_instance_memory(lib, (uint32_t)export_of(lib, "mem", WASMEXT_DESC_MEMORY), &v) == 0 && v.base[100] == 77);
    a[0] = I32(1);
    CHECK(call(app, "grow", a, 1, r, 1) == 0 && r[0].as.i32 == 1);
    CHECK(wasmext_instance_memory(lib, (uint32_t)export_of(lib, "mem", WASMEXT_DESC_MEMORY), &v) == 0 && v.pages == 2 && v.base[100] == 77);
    /* the global is one: app increments it, lib sees it; lib sets it, app sees it */
    CHECK(call(app, "inc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 11);
    CHECK(call(lib, "get_counter", NULL, 0, r, 1) == 0 && r[0].as.i32 == 11);
    {
        wasmext_val g = I32(500);
        CHECK(wasmext_instance_global_set(lib, (uint32_t)export_of(lib, "counter", WASMEXT_DESC_GLOBAL), &g) == 0);
    }
    CHECK(call(app, "inc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 501);
    CHECK(call(app, "get_ver", NULL, 0, r, 1) == 0 && r[0].as.i64 == 7);
    CHECK(call(app, "get_k", NULL, 0, r, 1) == 0 && r[0].as.i32 == 42); /* the value the host gave */
    wasmext_instance_free(app);
    wasmext_instance_free(lib);
    wasmext_store_free(s);
}

/* two stores: each call enters the store of the instance that runs; closing the exporter's store refuses the calls into it, as a closed store does */
static void test_two_stores(void) {
    wasmext_store *sa = wasmext_store_new(), *sb = wasmext_store_new();
    wasmext_instance *lib = wasmext_instance_new(sa, &lib_binding, NULL), *app = wasmext_instance_new(sb, &app_binding, NULL);
    wasmext_val a[2], r[1];
    CHECK(wasmext_instance_instantiate(lib) == 0);
    link_all(app, lib, NULL);
    CHECK(wasmext_instance_instantiate(app) == 0);
    a[0] = I32(2); a[1] = I32(3);
    CHECK(call(app, "call_add", a, 2, r, 1) == 0 && r[0].as.i32 == 5);
    CHECK(wasmext_store_close(sa) == WASMEXT_STORE_OK);
    CHECK(call(app, "call_add", a, 2, r, 1) == (int)WASMEXT_TRAP_CLOSED); /* the trap of the closed store goes through */
    CHECK(wasmext_error_describe((int)WASMEXT_TRAP_CLOSED).kind == WASMEXT_ERR_CLOSED);
    CHECK(wasmext_store_close(sb) == WASMEXT_STORE_OK);
    wasmext_instance_free(app);
    wasmext_instance_free(lib);
    wasmext_store_free(sa);
    wasmext_store_free(sb);
}

/* records that do not fit */
static void test_refusals(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *lib = wasmext_instance_new(s, &lib_binding, NULL), *app = wasmext_instance_new(s, &app_binding, NULL);
    wasmext_instance *tiny = wasmext_instance_new(s, &tiny_binding, NULL), *big = wasmext_instance_new(s, &big_binding, NULL);
    wasmext_export rec;
    char text[WASMEXT_STORE_ERROR_SIZE];
    int add = import_of(app, "libx", "add"), mem = import_of(app, "libx", "mem"), counter = import_of(app, "libx", "counter");
    CHECK(wasmext_instance_export_record(lib, 0, NULL, &rec) == WASMEXT_INST_NOT_INSTANTIATED); /* a record only from an instantiated instance */
    CHECK(wasmext_instance_instantiate(lib) == 0 && wasmext_instance_instantiate(tiny) == 0 && wasmext_instance_instantiate(big) == 0);
    /* a function of another signature */
    CHECK(link_to(app, "libx", "add", lib, "log", WASMEXT_DESC_FUNC, NULL) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "libx.add") != NULL && strstr(text, "another one") != NULL && strstr(text, "i>") != NULL);
    /* a record of another kind */
    CHECK(link_to(app, "libx", "add", lib, "mem", WASMEXT_DESC_MEMORY, NULL) == WASMEXT_INST_LINK_FAILED);
    CHECK(link_to(app, "libx", "mem", lib, "add", WASMEXT_DESC_FUNC, NULL) == WASMEXT_INST_LINK_FAILED);
    CHECK(link_to(app, "libx", "counter", lib, "mem", WASMEXT_DESC_MEMORY, NULL) == WASMEXT_INST_LINK_FAILED);
    /* a global of the other mutability or type */
    CHECK(link_to(app, "libx", "counter", lib, "ver", WASMEXT_DESC_GLOBAL, NULL) == WASMEXT_INST_LINK_FAILED);
    CHECK(link_to(app, "libx", "ver", lib, "counter", WASMEXT_DESC_GLOBAL, NULL) == WASMEXT_INST_LINK_FAILED);
    /* memories: fewer pages than the import needs, a maximum above what it allows */
    CHECK(link_to(app, "libx", "mem", tiny, "mem", WASMEXT_DESC_MEMORY, NULL) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "needs at least") != NULL);
    CHECK(link_to(app, "libx", "mem", big, "mem", WASMEXT_DESC_MEMORY, NULL) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "allows") != NULL);
    /* a record of a version this reader cannot use */
    CHECK(wasmext_instance_export_record(lib, (uint32_t)export_of(lib, "add", WASMEXT_DESC_FUNC), NULL, &rec) == 0);
    rec.abi = 0x7F000001u; /* another x */
    CHECK(wasmext_instance_bind_export(app, (uint32_t)add, &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "incompatible version") != NULL);
    CHECK(wasmext_export_ok(&rec) == 0);
    /* an import that is not there, a core import, a table, after instantiate */
    CHECK(wasmext_instance_bind_export(app, 999, &rec) == WASMEXT_INST_BAD_IMPORT);
    {
        wasmext_val v = I32(1);
        CHECK(wasmext_instance_bind_global_value(app, (uint32_t)counter, &v) == WASMEXT_INST_IMMUTABLE); /* a mutable global is another instance's */
        CHECK(wasmext_instance_bind_global_value(app, (uint32_t)add, &v) == WASMEXT_INST_BAD_IMPORT);
        v = I64(1);
        CHECK(wasmext_instance_bind_global_value(app, (uint32_t)import_of(app, "env", "k"), &v) == WASMEXT_INST_BAD_ARGS); /* the wrong type */
    }
    (void)mem;
    wasmext_instance_free(app);
    wasmext_instance_free(lib);
    wasmext_instance_free(tiny);
    wasmext_instance_free(big);
    wasmext_store_free(s);
}

int main(void) {
    test_two_instances_one_store();
    test_two_stores();
    test_refusals();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
