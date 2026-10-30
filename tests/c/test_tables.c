/* Tables of funcref in plain C (wasmext_table.h): a table that an instance exports and another imports, a table of the host, elements made by other instances, the types that
   call_indirect checks, growth, the refusals, a failed instantiation that leaves functions in a table, the close, and the host operations from several threads.
   Five real wasm2c modules in one program (one copy of the runtime). */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_table.h"

extern const wasmext_binding owner_binding, user_binding, trapper_binding, strict_binding, capped_binding, hostf_binding;

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
static int export_of(wasmext_instance *i, const char *name, int kind) { return wasmext_instance_export_find(i, name, strlen(name), kind); }
static int import_of(wasmext_instance *i, const char *module, const char *name) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_imports; k++)
        if (d->imports[k].module.n == strlen(module) && memcmp(d->imports[k].module.p, module, d->imports[k].module.n) == 0 &&
            d->imports[k].name.n == strlen(name) && memcmp(d->imports[k].name.p, name, d->imports[k].name.n) == 0)
            return (int)k;
    return -1;
}
/* calls `name(arg)` -> i32 (or `name()` when `arg` is negative): the trap code, or 0 with the result in *out */
static int call(wasmext_instance *i, const char *name, int32_t arg, int32_t *out) {
    wasmext_val a = I32(arg), r;
    int rc = wasmext_instance_call(i, (uint32_t)export_of(i, name, WASMEXT_DESC_FUNC), arg >= 0 ? &a : NULL, arg >= 0 ? 1u : 0u, &r, 1);
    if (rc == 0 && out != NULL) *out = r.as.i32;
    return rc;
}
static int32_t value(wasmext_instance *i, const char *name, int32_t arg) { int32_t v = -12345; return call(i, name, arg, &v) == 0 ? v : -99999; }
/* the (only) table import of a module: they are named alike apart from the module, as each is a global symbol of wasm2c in the program that holds all the modules */
static uint32_t table_import(wasmext_instance *i) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_imports; k++)
        if (d->imports[k].kind == WASMEXT_DESC_TABLE) return k;
    return 0xFFFFFFFFu;
}
/* gives the table import of `app` the table export `tab` of `lib` */
static int link_table(wasmext_instance *app, wasmext_instance *lib) {
    wasmext_export rec;
    int rc = wasmext_instance_export_record(lib, (uint32_t)export_of(lib, "tab", WASMEXT_DESC_TABLE), NULL, &rec);
    return rc != 0 ? rc : wasmext_instance_bind_export(app, table_import(app), &rec);
}
static uint32_t tab_export(wasmext_instance *i) { return (uint32_t)export_of(i, "tab", WASMEXT_DESC_TABLE); }
static int funcref_of(wasmext_instance *i, const char *name, wasmext_funcref *f) { return wasmext_instance_funcref(i, (uint32_t)export_of(i, name, WASMEXT_DESC_FUNC), f); }

/* the table of `owner`, shared with `user`, whose `elem` segment put its own function `nine` in slot 1 */
static void test_shared_table(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL), *user = wasmext_instance_new(s, &user_binding, NULL);
    wasmext_funcref f, g;
    uint32_t size, maximum, previous;
    int32_t v;
    CHECK(wasmext_instance_instantiate(owner) == 0);
    CHECK(link_table(user, owner) == 0);
    CHECK(wasmext_instance_instantiate(user) == 0);
    /* slot 0 is the owner's own function, slot 1 the user's: call_indirect goes to whichever instance made the element */
    CHECK(value(owner, "call", 0) == 7);
    CHECK(value(owner, "call", 1) == 9);
    CHECK(value(user, "call", 0) == 7 && value(user, "call", 1) == 9);
    /* the elements, as values: the instance that stands behind each is its member */
    CHECK(wasmext_instance_table_get(owner, tab_export(owner), 0, &f) == 0 && f.ref.func != NULL && f.owner == owner->owner && f.store == s);
    CHECK(wasmext_instance_table_get(owner, tab_export(owner), 1, &g) == 0 && g.ref.func != NULL && g.owner == user->owner);
    CHECK(wasmext_instance_table_get(owner, tab_export(owner), 2, &g) == 0 && g.ref.func == NULL && g.owner == 0); /* empty */
    CHECK(wasmext_instance_table_get(owner, tab_export(owner), 4, &g) == WASMEXT_TAB_BOUNDS);
    CHECK(wasmext_instance_table_size(owner, tab_export(owner), &size, &maximum) == 0 && size == 4 && maximum == 8);
    /* a function made by the host into a slot: the user's `nine` into slot 2, and the owner calls it */
    CHECK(funcref_of(user, "nine", &f) == 0 && f.owner == user->owner);
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 2, &f) == 0);
    CHECK(value(owner, "call", 2) == 9);
    /* the type is checked by call_indirect, not by the table: a function of another type traps in the caller, which stays usable */
    CHECK(funcref_of(owner, "one", &f) == 0);
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 2, &f) == 0);
    CHECK(call(owner, "call", 2, &v) == (int)WASM_RT_TRAP_CALL_INDIRECT);
    CHECK(call(user, "call", 2, &v) == (int)WASM_RT_TRAP_CALL_INDIRECT);
    CHECK(value(owner, "call", 0) == 7);
    /* an empty slot is a trap too */
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 2, NULL) == 0);
    CHECK(call(owner, "call", 2, &v) != 0);
    /* a trap inside a function that came through the table goes to the caller, whichever instance the function is of */
    CHECK(funcref_of(owner, "bad", &f) == 0 && wasmext_instance_table_set(owner, tab_export(owner), 3, &f) == 0);
    CHECK(call(user, "call", 3, &v) == (int)WASM_RT_TRAP_UNREACHABLE);
    CHECK(call(owner, "call", 3, &v) == (int)WASM_RT_TRAP_UNREACHABLE);
    CHECK(value(user, "call", 1) == 9 && value(owner, "call", 0) == 7);
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 4, &f) == WASMEXT_TAB_BOUNDS);
    /* growth is seen by both; a maximum is kept, by the module and by the host */
    CHECK(value(owner, "grow", 2) == 4 && value(user, "size", -1) == 6 && value(owner, "size", -1) == 6);
    CHECK(wasmext_instance_table_grow(owner, tab_export(owner), 1, &previous) == 0 && previous == 6);
    CHECK(value(user, "size", -1) == 7);
    CHECK(value(owner, "grow", 5) == -1);
    CHECK(wasmext_instance_table_grow(owner, tab_export(owner), 2, &previous) == WASMEXT_TAB_FULL);
    CHECK(wasmext_instance_table_grow(owner, tab_export(owner), 1, &previous) == 0 && previous == 7);
    CHECK(wasmext_instance_table_size(user, tab_export(user), NULL, NULL) == WASMEXT_INST_BAD_EXPORT); /* the user exports no table */
    CHECK(wasmext_instance_table_size(owner, (uint32_t)export_of(owner, "call", WASMEXT_DESC_FUNC), NULL, NULL) == WASMEXT_INST_BAD_EXPORT);
    wasmext_store_free(s);
}

/* a table of the host: made in the store, given to an import by its record, filled by the module's `elem` segment and by the host */
static void test_host_table(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL), *user = wasmext_instance_new(s, &user_binding, NULL);
    wasmext_tab *t;
    wasmext_export rec;
    wasmext_funcref f;
    uint32_t size, maximum, previous;
    int error = -1;
    CHECK(wasmext_tab_new(NULL, 0x70, 1, 1, &error) == NULL && error == EINVAL);
    CHECK(wasmext_tab_new(s, 0x70, 3, 2, &error) == NULL && error == EINVAL); /* initial above maximum */
    t = wasmext_tab_new(s, 0x70, 4, WASMEXT_TABLE_NO_MAXIMUM, &error);
    CHECK(t != NULL && error == 0);
    CHECK(wasmext_tab_size(t, &size, &maximum) == 0 && size == 4 && maximum == WASMEXT_TABLE_NO_MAXIMUM);
    CHECK(wasmext_instance_instantiate(owner) == 0);
    CHECK(wasmext_tab_record(t, NULL, &rec) == 0 && rec.kind == WASMEXT_TABLE && rec.store == s);
    CHECK(wasmext_instance_bind_export(user, table_import(user), &rec) == 0);
    CHECK(wasmext_instance_instantiate(user) == 0);
    CHECK(wasmext_tab_get(t, 1, &f) == 0 && f.ref.func != NULL && f.owner == user->owner); /* the segment of the user filled the table of the host */
    CHECK(value(user, "call", 1) == 9);
    CHECK(wasmext_tab_get(t, 0, &f) == 0 && f.ref.func == NULL);
    CHECK(funcref_of(owner, "seven", &f) == 0 && wasmext_tab_set(t, 0, &f) == 0);
    CHECK(value(user, "call", 0) == 7);
    CHECK(wasmext_tab_set(t, 9, &f) == WASMEXT_TAB_BOUNDS && wasmext_tab_get(t, 9, &f) == WASMEXT_TAB_BOUNDS);
    CHECK(wasmext_tab_grow(t, 10, &previous) == 0 && previous == 4 && value(user, "size", -1) == 14);
    CHECK(wasmext_tab_set(t, 0, NULL) == 0 && call(user, "call", 0, NULL) != 0);
    /* the host table is a member of the store: the close frees it, and then every operation answers the code of a closed store */
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_tab_get(t, 0, &f) == (int)WASMEXT_TRAP_CLOSED && wasmext_tab_set(t, 0, NULL) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(wasmext_tab_grow(t, 1, NULL) == (int)WASMEXT_TRAP_CLOSED && wasmext_tab_size(t, NULL, NULL) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(wasmext_tab_record(t, NULL, &rec) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(wasmext_instance_table_get(owner, 0, 0, &f) != 0);
    CHECK(wasmext_tab_new(s, 0x70, 1, 1, &error) == NULL && error == EBADF);
    wasmext_store_free(s);
}

/* a function that is not of the store, or not a function of anyone, is not put in */
static void test_foreign_functions(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL), *stranger = wasmext_instance_new(other, &owner_binding, NULL);
    wasmext_funcref f, g;
    CHECK(wasmext_instance_instantiate(owner) == 0 && wasmext_instance_instantiate(stranger) == 0);
    CHECK(funcref_of(stranger, "seven", &f) == 0);
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 0, &f) == WASMEXT_TAB_WRONG_STORE);
    /* the same function claimed to be of this store, and a handle that is not the member's */
    CHECK(funcref_of(owner, "seven", &g) == 0);
    f = g;
    f.owner = g.owner + 1;
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 0, &f) == WASMEXT_TAB_WRONG_STORE);
    f = g;
    f.ref.module_instance = (char *)g.ref.module_instance + 1; /* a pointer that no member has */
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 0, &f) == WASMEXT_TAB_WRONG_STORE);
    f = g;
    f.store = other; /* a function of this store that says it is of another */
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 0, &f) == WASMEXT_TAB_WRONG_STORE);
    f = g;
    f.owner = stranger->owner; /* a handle of the other store */
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 0, &f) == WASMEXT_TAB_WRONG_STORE);
    CHECK(value(owner, "size", -1) == 4);
    CHECK(wasmext_instance_table_get(owner, tab_export(owner), 2, &f) == 0 && f.ref.func == NULL); /* nothing was put in */
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 0, &g) == 0 && value(owner, "call", 0) == 7);
    wasmext_store_free(s);
    wasmext_store_free(other);
}

/* an import that does not fit, and an instance that fails to start after its `elem` segment put a function in the table of another */
static void test_refusals_and_failed_start(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL), *strict = wasmext_instance_new(s, &strict_binding, NULL);
    wasmext_instance *capped = wasmext_instance_new(s, &capped_binding, NULL), *trapper = wasmext_instance_new(s, &trapper_binding, NULL);
    wasmext_instance *stranger_app = wasmext_instance_new(other, &user_binding, NULL);
    wasmext_export rec;
    wasmext_funcref f;
    char text[WASMEXT_STORE_ERROR_SIZE];
    CHECK(wasmext_instance_instantiate(owner) == 0);
    CHECK(wasmext_instance_export_record(owner, tab_export(owner), NULL, &rec) == 0 && rec.kind == WASMEXT_TABLE && rec.store == s);
    /* the module needs more elements than the table has, or a maximum the table is above */
    CHECK(wasmext_instance_bind_export(strict, table_import(strict), &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "own_s.tab") != NULL && strstr(text, "needs at least 8") != NULL);
    CHECK(wasmext_instance_bind_export(capped, table_import(capped), &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "may grow to 8") != NULL && strstr(text, "allows 2") != NULL);
    /* a record of another kind, and a table of another store */
    CHECK(wasmext_instance_export_record(owner, (uint32_t)export_of(owner, "seven", WASMEXT_DESC_FUNC), NULL, &rec) == 0);
    CHECK(wasmext_instance_bind_export(strict, table_import(strict), &rec) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "is a table") != NULL);
    CHECK(link_table(stranger_app, owner) == WASMEXT_INST_LINK_FAILED);
    wasmext_store_error(other, text, sizeof text);
    CHECK(strstr(text, "another store") != NULL);
    /* the start function traps after the segment put `ten` in slot 3: the instance is released, and the slot is empty again */
    CHECK(link_table(trapper, owner) == 0);
    CHECK(wasmext_instance_instantiate(trapper) == (int)WASM_RT_TRAP_UNREACHABLE);
    CHECK(wasmext_instance_table_get(owner, tab_export(owner), 3, &f) == 0 && f.ref.func == NULL);
    CHECK(wasmext_instance_table_get(owner, tab_export(owner), 0, &f) == 0 && f.ref.func != NULL); /* the owner's own element stays */
    CHECK(value(owner, "call", 0) == 7);
    CHECK(call(owner, "call", 3, NULL) != 0); /* a trap, not a call into what was released */
    wasmext_instance_free(trapper);
    wasmext_instance_free(strict);
    wasmext_instance_free(capped);
    wasmext_instance_free(stranger_app);
    wasmext_store_free(s);
    wasmext_store_free(other);
}

/* a function that stands for an element is called from the host through an instance that declares its type: the function is another instance's, the types are numbers, several
   results, a vector, and nothing; a type the instance does not declare, a null funcref, a trap, a wrong number of arguments and a funcref of another store are refused */
static wasmext_val F32(float v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7D; x.as.f32 = v; return x; }
static wasmext_val F64(double v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7C; x.as.f64 = v; return x; }
static wasmext_val I64(int64_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7E; x.as.i64 = v; return x; }
static void test_call_ref(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL), *user = wasmext_instance_new(s, &user_binding, NULL);
    wasmext_instance *stranger = wasmext_instance_new(other, &owner_binding, NULL);
    wasmext_funcref f;
    wasmext_val a[4], r[2];
    CHECK(wasmext_instance_instantiate(owner) == 0 && link_table(user, owner) == 0 && wasmext_instance_instantiate(user) == 0 && wasmext_instance_instantiate(stranger) == 0);
    /* the `add` of the user adds 100: the call is to the user's function, through the declaration of the type by the owner */
    CHECK(funcref_of(user, "add", &f) == 0);
    a[0] = I32(2); a[1] = I32(3);
    CHECK(wasmext_instance_call_ref(owner, &f, a, 2, r, 1) == 0 && r[0].type == 0x7F && r[0].as.i32 == 105);
    CHECK(wasmext_instance_call_ref(user, &f, a, 2, r, 1) == 0 && r[0].as.i32 == 105); /* ... and through the user's own */
    /* several results, in order; floats; nothing; a vector */
    CHECK(funcref_of(user, "swap", &f) == 0);
    a[0] = I32(7); a[1] = I64(9);
    CHECK(wasmext_instance_call_ref(owner, &f, a, 2, r, 2) == 0 && r[0].type == 0x7E && r[0].as.i64 == 9 && r[1].type == 0x7F && r[1].as.i32 == 7);
    CHECK(funcref_of(user, "mix", &f) == 0);
    a[0] = F32(1.5f); a[1] = F64(10.0);
    CHECK(wasmext_instance_call_ref(owner, &f, a, 2, r, 1) == 0 && r[0].type == 0x7C && r[0].as.f64 == 8.5);
    CHECK(funcref_of(user, "nothing", &f) == 0 && wasmext_instance_call_ref(owner, &f, NULL, 0, NULL, 0) == 0);
    {
        wasmext_val x, y;
        int32_t in[4] = {1, 2, 3, 4}, out[4];
        memset(&x, 0, sizeof x); x.type = 0x7B; memcpy(x.as.v128, in, 16);
        CHECK(funcref_of(user, "vec", &f) == 0 && wasmext_instance_call_ref(owner, &f, &x, 1, &y, 1) == 0);
        memcpy(out, y.as.v128, 16);
        CHECK(out[0] == 1 && out[3] == 4); /* the `vec` of the user returns its argument; the owner's would double it */
    }
    /* an element read from a table is called the same way: the `nine` of the user, in slot 1 */
    CHECK(wasmext_instance_table_get(owner, tab_export(owner), 1, &f) == 0);
    CHECK(wasmext_instance_call_ref(owner, &f, NULL, 0, r, 1) == 0 && r[0].as.i32 == 9);
    /* a type that the owner does not declare (four parameters), and one it does, called with the wrong arguments */
    CHECK(funcref_of(user, "mul4", &f) == 0);
    a[0] = I32(2); a[1] = I32(3); a[2] = I32(4); a[3] = I32(1);
    CHECK(wasmext_instance_call_ref(owner, &f, a, 4, r, 1) == WASMEXT_INST_UNDECLARED_TYPE);
    CHECK(wasmext_instance_call_ref(user, &f, a, 4, r, 1) == 0 && r[0].as.i32 == 24); /* the user declares it */
    CHECK(funcref_of(user, "add", &f) == 0);
    CHECK(wasmext_instance_call_ref(owner, &f, a, 1, r, 1) == WASMEXT_INST_BAD_ARGS);
    CHECK(wasmext_instance_call_ref(owner, &f, a, 2, r, 0) == WASMEXT_INST_BAD_ARGS);
    a[1] = I64(1);
    CHECK(wasmext_instance_call_ref(owner, &f, a, 2, r, 1) == WASMEXT_INST_BAD_ARGS); /* the second is not an i32 */
    /* a trap in the function is the code of the call; both instances are usable after it */
    {
        wasmext_funcref d;
        CHECK(funcref_of(user, "div", &d) == 0);
        a[0] = I32(7); a[1] = I32(0);
        CHECK(wasmext_instance_call_ref(owner, &d, a, 2, r, 1) == (int)WASM_RT_TRAP_DIV_BY_ZERO);
        a[1] = I32(2);
        CHECK(wasmext_instance_call_ref(owner, &d, a, 2, r, 1) == 0 && r[0].as.i32 == 3);
        CHECK(value(owner, "call", 0) == 7 && value(user, "call", 1) == 9);
    }
    /* a null funcref is a trap of WebAssembly; a function of another store, or a forged one, is refused */
    memset(&f, 0, sizeof f);
    CHECK(wasmext_instance_call_ref(owner, &f, NULL, 0, r, 1) == (int)WASM_RT_TRAP_NULL_REF);
    CHECK(wasmext_instance_call_ref(owner, NULL, NULL, 0, r, 1) == (int)WASM_RT_TRAP_NULL_REF);
    CHECK(funcref_of(stranger, "seven", &f) == 0);
    CHECK(wasmext_instance_call_ref(owner, &f, NULL, 0, r, 1) == WASMEXT_TAB_WRONG_STORE);
    CHECK(funcref_of(owner, "seven", &f) == 0);
    CHECK(wasmext_instance_call_ref(owner, &f, NULL, 0, r, 1) == 0 && r[0].as.i32 == 7);
    f.owner += 1;
    CHECK(wasmext_instance_call_ref(owner, &f, NULL, 0, r, 1) == WASMEXT_TAB_WRONG_STORE);
    /* the close */
    CHECK(funcref_of(owner, "seven", &f) == 0 && wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_instance_call_ref(owner, &f, NULL, 0, r, 1) == (int)WASMEXT_TRAP_CLOSED);
    wasmext_store_free(s);
    wasmext_store_free(other);
}

/* a funcref as a parameter and as a result of an exported function, in the middle of a call (`get`, `put`) and in the signature of an import: the host function is given the funcref and
   answers one. An argument is of the store (or null); a result is written where the caller points `as.ref`. */
static wasmext_val REF(wasmext_funcref *f) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x70; x.as.ref = f; return x; }
static int export_call(wasmext_instance *i, const char *name, const wasmext_val *a, uint32_t na, wasmext_val *r, uint32_t nr) {
    return wasmext_instance_call(i, (uint32_t)export_of(i, name, WASMEXT_DESC_FUNC), a, na, r, nr);
}
static void test_funcref_values(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL), *user = wasmext_instance_new(s, &user_binding, NULL);
    wasmext_instance *stranger = wasmext_instance_new(other, &owner_binding, NULL);
    wasmext_funcref nine, seven, back, back2, none, foreign;
    wasmext_val a[2], r[2];
    CHECK(wasmext_instance_instantiate(owner) == 0 && link_table(user, owner) == 0 && wasmext_instance_instantiate(user) == 0 && wasmext_instance_instantiate(stranger) == 0);
    CHECK(funcref_of(user, "nine", &nine) == 0 && funcref_of(owner, "seven", &seven) == 0 && funcref_of(stranger, "seven", &foreign) == 0);
    /* the identity: the function of another instance goes in and comes out as the same function, with its owner and its store */
    a[0] = REF(&nine); r[0] = REF(&back);
    CHECK(export_call(owner, "ident", a, 1, r, 1) == 0 && r[0].type == 0x70);
    CHECK(back.ref.func == nine.ref.func && back.ref.module_instance == nine.ref.module_instance && back.owner == user->owner && back.store == s);
    CHECK(wasmext_instance_call_ref(owner, &back, NULL, 0, r, 1) == 0 && r[0].as.i32 == 9); /* ... and it can be called */
    /* null: a null pointer, and a pointer to a funcref with no function */
    memset(&none, 0, sizeof none);
    a[0] = REF(NULL); r[0] = REF(&back);
    CHECK(export_call(owner, "ident", a, 1, r, 1) == 0 && back.ref.func == NULL && back.owner == 0 && back.store == s);
    a[0] = REF(&none); r[0] = REF(&back);
    CHECK(export_call(owner, "ident", a, 1, r, 1) == 0 && back.ref.func == NULL);
    a[0] = REF(NULL);
    CHECK(export_call(owner, "isnull", a, 1, r, 1) == 0 && r[0].as.i32 == 1);
    a[0] = REF(&nine);
    CHECK(export_call(owner, "isnull", a, 1, r, 1) == 0 && r[0].as.i32 == 0);
    /* the place for a result is the caller's: none is a refusal, and nothing is called */
    a[0] = REF(&nine); r[0] = REF(NULL);
    CHECK(export_call(owner, "ident", a, 1, r, 1) == WASMEXT_INST_BAD_ARGS);
    /* several results, in order */
    a[0] = REF(&nine); a[1] = REF(&seven); r[0] = REF(&back); r[1] = REF(&back2);
    CHECK(export_call(owner, "pair", a, 2, r, 2) == 0 && back.ref.func == seven.ref.func && back.owner == owner->owner && back2.ref.func == nine.ref.func && back2.owner == user->owner);
    /* a function of another store, a forged one: refused before the call */
    a[0] = REF(&foreign); r[0] = REF(&back);
    CHECK(export_call(owner, "ident", a, 1, r, 1) == WASMEXT_TAB_WRONG_STORE);
    foreign = nine; foreign.owner += 1;
    a[0] = REF(&foreign);
    CHECK(export_call(owner, "ident", a, 1, r, 1) == WASMEXT_TAB_WRONG_STORE);
    /* `put` and `get` use the table inside the module: the function put in slot 2 is called by `call_indirect`, and `get` gives back what a table holds */
    {
        wasmext_val i2 = I32(2);
        a[0] = i2; a[1] = REF(&nine);
        CHECK(export_call(owner, "put", a, 2, NULL, 0) == 0 && value(owner, "call", 2) == 9);
        r[0] = REF(&back);
        CHECK(export_call(owner, "get", &i2, 1, r, 1) == 0 && back.ref.func == nine.ref.func && back.owner == user->owner);
        i2 = I32(3);
        CHECK(export_call(owner, "get", &i2, 1, r, 1) == 0 && back.ref.func == NULL); /* an empty slot is a null funcref */
        i2 = I32(9);
        CHECK(export_call(owner, "get", &i2, 1, r, 1) == (int)WASM_RT_TRAP_OOB); /* a trap of the module, the instance stays */
    }
    /* call_ref of a function with a funcref in its signature, through the instance that declares the type */
    {
        wasmext_funcref ident;
        CHECK(funcref_of(owner, "ident", &ident) == 0);
        a[0] = REF(&nine); r[0] = REF(&back);
        CHECK(wasmext_instance_call_ref(owner, &ident, a, 1, r, 1) == 0 && back.ref.func == nine.ref.func && back.owner == user->owner);
        r[0] = REF(NULL);
        CHECK(wasmext_instance_call_ref(owner, &ident, a, 1, r, 1) == WASMEXT_INST_BAD_ARGS);
    }
    /* a function with a funcref in its signature has a record (8a-2): the letter of a funcref is F */
    {
        wasmext_export rec;
        CHECK(wasmext_instance_export_record(owner, (uint32_t)export_of(owner, "ident", WASMEXT_DESC_FUNC), NULL, &rec) == 0 && strcmp(rec.signature, "F>F") == 0);
    }
    wasmext_store_free(s);
    wasmext_store_free(other);
}

/* what a host function is given and answers when its signature has a funcref (the import `env.visit`) */
typedef struct { int mode; wasmext_funcref seen; wasmext_funcref give; int calls; } visit_t;
static int visit(void *user, const wasmext_val *args, wasmext_val *results) {
    visit_t *v = (visit_t *)user;
    v->calls++;
    if (args[0].type == 0x70 && args[0].as.ref != NULL) v->seen = *(const wasmext_funcref *)args[0].as.ref;
    switch (v->mode) {
        case 0: results[0].type = 0x70; results[0].as.ref = args[0].as.ref; return 0; /* the same funcref back */
        case 1: results[0].type = 0x70; results[0].as.ref = NULL; return 0;          /* null */
        case 2: results[0].type = 0x70; results[0].as.ref = &v->give; return 0;      /* what the test chose */
        case 3: results[0].type = 0x7F; return 0;                                    /* a value of another type */
        default: return 77;                                                          /* a failure of the host */
    }
}
static void test_funcref_in_an_import(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL), *user = wasmext_instance_new(s, &user_binding, NULL), *h = wasmext_instance_new(s, &hostf_binding, NULL);
    wasmext_funcref nine, back, other_store;
    wasmext_val a[1], r[1];
    visit_t v;
    int import = import_of(h, "env", "visit");
    wasmext_store *other = wasmext_store_new();
    wasmext_instance *stranger = wasmext_instance_new(other, &owner_binding, NULL);
    memset(&v, 0, sizeof v);
    CHECK(wasmext_instance_instantiate(owner) == 0 && link_table(user, owner) == 0 && wasmext_instance_instantiate(user) == 0 && wasmext_instance_instantiate(stranger) == 0);
    CHECK(funcref_of(user, "nine", &nine) == 0 && funcref_of(stranger, "seven", &other_store) == 0);
    /* the typed shape has no funcref: refused, and the uniform one is taken */
    CHECK(wasmext_instance_bind_typed(h, (uint32_t)import, (void *)visit, &v) == WASMEXT_INST_UNSUPPORTED);
    CHECK(wasmext_instance_bind_func(h, (uint32_t)import, visit, &v) == 0 && wasmext_instance_instantiate(h) == 0);
    /* the host function is given the funcref of the function, with its owner and the store, and answers the same */
    a[0] = REF(&nine); r[0] = REF(&back);
    CHECK(export_call(h, "via", a, 1, r, 1) == 0 && v.calls == 1);
    CHECK(v.seen.ref.func == nine.ref.func && v.seen.owner == user->owner && v.seen.store == s);
    CHECK(back.ref.func == nine.ref.func && back.owner == user->owner);
    /* a null funcref is given as a funcref with no function, and answered as null */
    a[0] = REF(NULL);
    CHECK(export_call(h, "via", a, 1, r, 1) == 0 && v.seen.ref.func == NULL && back.ref.func == NULL);
    v.mode = 1;
    a[0] = REF(&nine);
    CHECK(export_call(h, "via", a, 1, r, 1) == 0 && back.ref.func == NULL);
    /* the host answers a function of the store: it goes through */
    v.mode = 2;
    v.give = nine;
    CHECK(export_call(h, "via", a, 1, r, 1) == 0 && back.ref.func == nine.ref.func);
    /* ... a function of another store, a forged one, a value of another type, a failure: the call traps, with the failure of the host, and the instance is usable after it */
    v.give = other_store;
    CHECK(export_call(h, "via", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    v.give = nine; v.give.owner += 1;
    CHECK(export_call(h, "via", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    v.mode = 3;
    CHECK(export_call(h, "via", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    v.mode = 4;
    CHECK(export_call(h, "via", a, 1, r, 1) != 0);
    v.mode = 0;
    CHECK(export_call(h, "via", a, 1, r, 1) == 0 && back.ref.func == nine.ref.func);
    /* a function with a funcref in the signature is linked to this import (8a-2); one of another signature is not, and the text says the letters */
    {
        wasmext_instance *h2 = wasmext_instance_new(s, &hostf_binding, NULL);
        wasmext_export rec;
        char text[WASMEXT_STORE_ERROR_SIZE];
        CHECK(wasmext_instance_export_record(owner, (uint32_t)export_of(owner, "seven", WASMEXT_DESC_FUNC), NULL, &rec) == 0);
        CHECK(wasmext_instance_bind_export(h2, (uint32_t)import_of(h2, "env", "visit"), &rec) == WASMEXT_INST_LINK_FAILED);
        wasmext_store_error(s, text, sizeof text);
        CHECK(strstr(text, "F>F") != NULL && strstr(text, ">i") != NULL);
        CHECK(wasmext_instance_export_record(owner, (uint32_t)export_of(owner, "ident", WASMEXT_DESC_FUNC), NULL, &rec) == 0);
        CHECK(wasmext_instance_bind_export(h2, (uint32_t)import_of(h2, "env", "visit"), &rec) == 0 && wasmext_instance_instantiate(h2) == 0);
        a[0] = REF(&nine); r[0] = REF(&back);
        CHECK(export_call(h2, "via", a, 1, r, 1) == 0 && back.ref.func == nine.ref.func && back.owner == user->owner);
        wasmext_instance_free(h2);
    }
    wasmext_store_free(s);
    wasmext_store_free(other);
}

/* a function of the host as an element of a table: wasm calls it by `call_indirect`, the host by `call_ref`; its type must be one the module declares; its failure is a trap; it can call
   back into the store; the store lets go of it at the close, once */
typedef struct { int calls; int released; wasmext_instance *back; } hf_t;
static int hf_const(void *user, const wasmext_val *a, wasmext_val *r) { ((hf_t *)user)->calls++; (void)a; r[0] = I32(42); return 0; }
static int hf_add(void *user, const wasmext_val *a, wasmext_val *r) { ((hf_t *)user)->calls++; r[0] = I32(a[0].as.i32 + a[1].as.i32 + 1000); return 0; }
static int hf_swap(void *user, const wasmext_val *a, wasmext_val *r) { ((hf_t *)user)->calls++; r[0] = I64(a[1].as.i64); r[1] = I32(a[0].as.i32); return 0; }
static int hf_fail(void *user, const wasmext_val *a, wasmext_val *r) { ((hf_t *)user)->calls++; (void)a; (void)r; return 77; }
static int hf_ident(void *user, const wasmext_val *a, wasmext_val *r) { ((hf_t *)user)->calls++; r[0].type = 0x70; r[0].as.ref = a[0].as.ref; return 0; }
static int hf_nested(void *user, const wasmext_val *a, wasmext_val *r) { /* calls the module again, from inside a call of it */
    hf_t *h = (hf_t *)user;
    wasmext_val x;
    int rc = wasmext_instance_call(h->back, (uint32_t)export_of(h->back, "seven", WASMEXT_DESC_FUNC), NULL, 0, &x, 1);
    (void)a;
    h->calls++;
    r[0] = I32(x.as.i32 + 1);
    return rc;
}
static void hf_release(void *user) { ((hf_t *)user)->released++; }
static const uint8_t T_NONE[] = {0}, T_I32[] = {0x7F}, T_I32I32[] = {0x7F, 0x7F}, T_I32I64[] = {0x7F, 0x7E}, T_I64I32[] = {0x7E, 0x7F}, T_REF[] = {0x70}, T_I32X4[] = {0x7F, 0x7F, 0x7F, 0x7F};
static void test_host_functions_in_tables(void) {
    wasmext_store *s = wasmext_store_new(), *other = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL), *user = wasmext_instance_new(s, &user_binding, NULL);
    wasmext_instance *stranger = wasmext_instance_new(other, &owner_binding, NULL);
    wasmext_funcref f, g, nine, back;
    hf_t c = {0, 0, NULL}, add = {0, 0, NULL}, swap = {0, 0, NULL}, fail = {0, 0, NULL}, ident = {0, 0, NULL}, nested = {0, 0, NULL};
    wasmext_val a[3], r[2];
    int32_t v;
    CHECK(wasmext_instance_instantiate(owner) == 0 && link_table(user, owner) == 0 && wasmext_instance_instantiate(user) == 0 && wasmext_instance_instantiate(stranger) == 0);
    /* () -> i32 in slot 2: wasm calls it through the table, from the instance that made the function and from another one that has the same type */
    CHECK(wasmext_instance_host_funcref(owner, T_NONE, 0, T_I32, 1, hf_const, &c, hf_release, &f) == 0 && f.store == s && f.owner != 0 && f.ref.func != NULL);
    CHECK(wasmext_instance_table_set(owner, tab_export(owner), 2, &f) == 0);
    CHECK(value(owner, "call", 2) == 42 && c.calls == 1);
    CHECK(value(user, "call", 2) == 42 && c.calls == 2);
    CHECK(wasmext_instance_table_get(owner, tab_export(owner), 2, &g) == 0 && g.ref.func == f.ref.func && g.owner == f.owner); /* it is a member of the store, like an instance */
    CHECK(wasmext_instance_call_ref(owner, &g, NULL, 0, r, 1) == 0 && r[0].as.i32 == 42 && c.calls == 3); /* ... and the host calls it too */
    /* the type is checked by call_indirect: this slot is not a function of the type the other exports ask for */
    a[0] = I32(2); a[1] = I32(3); a[2] = I32(4);
    CHECK(export_call(owner, "calladd", a, 3, r, 1) == (int)WASM_RT_TRAP_CALL_INDIRECT);
    /* (i32, i32) -> i32: the arguments reach the host function, its result reaches the module */
    CHECK(wasmext_instance_host_funcref(owner, T_I32I32, 2, T_I32, 1, hf_add, &add, hf_release, &f) == 0 && wasmext_instance_table_set(owner, tab_export(owner), 3, &f) == 0);
    a[0] = I32(3); a[1] = I32(5); a[2] = I32(6);
    CHECK(export_call(owner, "calladd", a, 3, r, 1) == 0 && r[0].as.i32 == 1011 && add.calls == 1);
    /* several results, in order, through call_ref */
    CHECK(wasmext_instance_host_funcref(owner, T_I32I64, 2, T_I64I32, 2, hf_swap, &swap, hf_release, &f) == 0);
    a[0] = I32(7); a[1] = I64(9);
    CHECK(wasmext_instance_call_ref(owner, &f, a, 2, r, 2) == 0 && r[0].type == 0x7E && r[0].as.i64 == 9 && r[1].as.i32 == 7);
    /* a funcref in the signature of a host function in a table */
    CHECK(funcref_of(user, "nine", &nine) == 0);
    CHECK(wasmext_instance_host_funcref(owner, T_REF, 1, T_REF, 1, hf_ident, &ident, hf_release, &f) == 0);
    a[0] = REF(&nine); r[0] = REF(&back);
    CHECK(wasmext_instance_call_ref(owner, &f, a, 1, r, 1) == 0 && back.ref.func == nine.ref.func && back.owner == user->owner && ident.calls == 1);
    /* a failure of the host function is a trap of the call that reached it, and the instances stay usable */
    CHECK(wasmext_instance_host_funcref(owner, T_NONE, 0, T_I32, 1, hf_fail, &fail, hf_release, &f) == 0 && wasmext_instance_table_set(owner, tab_export(owner), 2, &f) == 0);
    CHECK(call(owner, "call", 2, &v) == (int)WASMEXT_TRAP_HOST && fail.calls == 1);
    CHECK(wasmext_error_describe(wasmext_instance_status(owner)).kind == WASMEXT_ERR_HOST);
    CHECK(value(owner, "call", 0) == 7 && value(user, "call", 1) == 9);
    /* it can call the module again from inside the call */
    nested.back = owner;
    CHECK(wasmext_instance_host_funcref(owner, T_NONE, 0, T_I32, 1, hf_nested, &nested, hf_release, &f) == 0 && wasmext_instance_table_set(owner, tab_export(owner), 2, &f) == 0);
    CHECK(value(owner, "call", 2) == 8 && nested.calls == 1);
    CHECK(value(owner, "call", 0) == 7); /* the buffer of the outer call was put back */
    /* a type that the module does not declare has no trampoline: refused, nothing is made */
    CHECK(wasmext_instance_host_funcref(owner, T_I32X4, 4, T_I32, 1, hf_add, &add, hf_release, &f) == WASMEXT_INST_UNDECLARED_TYPE);
    CHECK(wasmext_instance_host_funcref(user, T_I32X4, 4, T_I32, 1, hf_add, &add, NULL, &f) == 0); /* the user declares it */
    CHECK(wasmext_instance_host_funcref(owner, T_NONE, 0, T_I32, 1, NULL, &c, NULL, &f) == WASMEXT_INST_BAD_ARGS);
    /* the store of the function is the store of the instance that made it: another store's table refuses it */
    CHECK(wasmext_instance_host_funcref(owner, T_NONE, 0, T_I32, 1, hf_const, &c, NULL, &f) == 0);
    CHECK(wasmext_instance_table_set(stranger, tab_export(stranger), 0, &f) == WASMEXT_TAB_WRONG_STORE);
    /* the close: each release is called once, and not before */
    CHECK(c.released == 0 && add.released == 0 && swap.released == 0 && fail.released == 0 && ident.released == 0 && nested.released == 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(c.released == 1 && add.released == 1 && swap.released == 1 && fail.released == 1 && ident.released == 1 && nested.released == 1);
    CHECK(wasmext_instance_call_ref(owner, &f, NULL, 0, r, 1) == (int)WASMEXT_TRAP_CLOSED);
    CHECK(wasmext_instance_host_funcref(owner, T_NONE, 0, T_I32, 1, hf_const, &c, NULL, &f) == (int)WASMEXT_TRAP_CLOSED);
    wasmext_store_free(s);
    CHECK(c.released == 1 && nested.released == 1); /* not again at the free */
    wasmext_store_free(other);
}

/* the record of an exported function says it can be put in a table */
static void test_function_records(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL);
    wasmext_export rec;
    wasmext_funcref f;
    CHECK(wasmext_instance_funcref(owner, (uint32_t)export_of(owner, "seven", WASMEXT_DESC_FUNC), &f) == WASMEXT_INST_NOT_INSTANTIATED);
    CHECK(wasmext_instance_instantiate(owner) == 0);
    CHECK(wasmext_instance_export_record(owner, (uint32_t)export_of(owner, "seven", WASMEXT_DESC_FUNC), NULL, &rec) == 0);
    CHECK(rec.funcref != NULL && (rec.flags & 16u) != 0 && rec.floor >= WASMEXT_SINCE_FUNCREF);
    CHECK(funcref_of(owner, "seven", &f) == 0 && f.ref.func == ((const wasm_rt_funcref_t *)rec.funcref)->func && f.ref.module_instance == owner->module);
    CHECK(wasmext_instance_funcref(owner, tab_export(owner), &f) == WASMEXT_INST_BAD_EXPORT); /* the export is a table */
    CHECK(wasmext_instance_funcref(owner, 999, &f) == WASMEXT_INST_BAD_EXPORT);
    wasmext_store_close(s);
    CHECK(funcref_of(owner, "seven", &f) == (int)WASMEXT_TRAP_CLOSED);
    wasmext_store_free(s);
}

/* the operations of the host from several threads: the lock of the table keeps its elements and its size whole (calls of the module are not made meanwhile: see the header) */
typedef struct { wasmext_tab *t; wasmext_funcref f; int id; int failed; } work_t;
static THREAD_RESULT worker(void *arg) {
    work_t *w = (work_t *)arg;
    for (int n = 0; n < 3000; n++) {
        wasmext_funcref g;
        uint32_t size;
        if (wasmext_tab_set(w->t, 0, &w->f) != 0) w->failed = 1;
        if (wasmext_tab_get(w->t, 0, &g) != 0 || (g.ref.func != NULL && g.ref.func != w->f.ref.func)) w->failed = 1;
        if (n % 500 == 0 && wasmext_tab_grow(w->t, 1, NULL) != 0) w->failed = 1;
        if (wasmext_tab_size(w->t, &size, NULL) != 0 || size < 4) w->failed = 1;
        if (wasmext_tab_set(w->t, 0, NULL) != 0) w->failed = 1;
    }
    return 0;
}
static void test_threads(void) {
    enum { N = 4 };
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *owner = wasmext_instance_new(s, &owner_binding, NULL);
    wasmext_tab *t = wasmext_tab_new(s, 0x70, 4, WASMEXT_TABLE_NO_MAXIMUM, NULL);
    work_t w[N];
    thread_t th[N];
    uint32_t size;
    CHECK(wasmext_instance_instantiate(owner) == 0 && t != NULL);
    for (int k = 0; k < N; k++) {
        w[k].t = t; w[k].id = k; w[k].failed = 0;
        CHECK(funcref_of(owner, "seven", &w[k].f) == 0);
        thread_start(&th[k], worker, &w[k]);
    }
    for (int k = 0; k < N; k++) { thread_join(th[k]); CHECK(!w[k].failed); }
    CHECK(wasmext_tab_size(t, &size, NULL) == 0 && size == 4 + (uint32_t)N * 6);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK); /* no operation is left in flight */
    wasmext_store_free(s);
}

int main(void) {
    test_shared_table();
    test_host_table();
    test_foreign_functions();
    test_refusals_and_failed_start();
    test_function_records();
    test_call_ref();
    test_funcref_values();
    test_funcref_in_an_import();
    test_host_functions_in_tables();
    test_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
