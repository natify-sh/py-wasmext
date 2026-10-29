/* Tests of the function imports of wasmext_instance.h in plain C over a module built by wasm2c and its generated binding. MODULE is the prefix. */
#include <stdio.h>
#define WASMEXT_DEFINE_THREAD_STATE
#include "wasmext_instance.h"

#define CAT_(a, b) a##b
#define CAT(a, b) CAT_(a, b)
extern const wasmext_binding CAT(MODULE, _binding);
#define BINDING (&CAT(MODULE, _binding))

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static wasmext_val I32(int32_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7F; x.as.i32 = v; return x; }

static int fn(wasmext_instance *i, const char *name) { return wasmext_instance_export_find(i, name, strlen(name), WASMEXT_DESC_FUNC); }
static int imp(wasmext_instance *i, const char *module, const char *name) {
    return wasmext_instance_import_find(i, module, strlen(module), name, strlen(name));
}
static int call(wasmext_instance *i, const char *name, const wasmext_val *a, uint32_t na, wasmext_val *r, uint32_t nr) {
    return wasmext_instance_call(i, (uint32_t)fn(i, name), a, na, r, nr);
}

/* ---- the host functions ---- */
static int f_calls, log_calls, log_last, again_calls;
static wasmext_instance *self;

static int host_f(void *user, const wasmext_val *a, wasmext_val *r) {
    f_calls++;
    if (user != (void *)0x11 || a[0].type != 0x7F || a[1].type != 0x7E) return 1;
    r[0] = I32(a[0].as.i32 + (int32_t)a[1].as.i64);
    return 0;
}
static int host_multi(void *user, const wasmext_val *a, wasmext_val *r) {
    (void)user;
    r[0] = I32((int32_t)(a[0].as.f32 * 2));
    r[1].type = 0x7C; r[1].as.f64 = 2.5;
    return 0;
}
static int host_fails(void *user, const wasmext_val *a, wasmext_val *r) { (void)user; (void)a; (void)r; return 7; }
static int host_traps_like_other(void *user, const wasmext_val *a, wasmext_val *r) { (void)user; (void)a; (void)r; return (int)WASMEXT_TRAP_LINKED + (int)WASM_RT_TRAP_DIV_BY_ZERO; }
static int host_wrong_type(void *user, const wasmext_val *a, wasmext_val *r) { (void)user; (void)a; r[0].type = 0x7E; r[0].as.i64 = 5; return 0; }
static int host_log(void *user, const wasmext_val *a, wasmext_val *r) { (void)user; (void)r; log_calls++; log_last = a[0].as.i32; return 0; }
/* typed: result f(void *user, parameters..., int *trapped) */
static uint32_t typed_f(void *user, uint32_t a0, uint64_t a1, int *trapped) { (void)user; f_calls++; *trapped = 0; return a0 * 10 + (uint32_t)a1; }
static void typed_log(void *user, uint32_t a0, int *trapped) { (void)user; log_calls++; log_last = (int)a0 + 1000; *trapped = 0; }
static uint32_t typed_fails(void *user, uint32_t a0, uint64_t a1, int *trapped) { (void)user; (void)a0; (void)a1; *trapped = 3; return 0; }
/* reentrant: the host calls an export of the instance that called it */
static int host_again(void *user, const wasmext_val *a, wasmext_val *r) {
    wasmext_val x[2], y[1];
    (void)user;
    again_calls++;
    x[0] = a[0]; x[1] = I32(1000);
    int rc = call(self, "add", x, 2, y, 1);
    if (rc != 0) return rc;
    r[0] = y[0];
    return 0;
}
static int host_again_div0(void *user, const wasmext_val *a, wasmext_val *r) {
    wasmext_val x[2], y[1];
    (void)user; (void)r;
    x[0] = a[0]; x[1] = I32(0);
    int rc = call(self, "div", x, 2, y, 1); /* traps inside the nested call */
    return rc == 0 ? 0 : (int)WASMEXT_TRAP_LINKED + rc;
}
static int host_vec(void *user, const wasmext_val *a, wasmext_val *r) {
    int32_t lanes[4];
    (void)user;
    memcpy(lanes, a[0].as.v128, 16);
    for (int k = 0; k < 4; k++) lanes[k] += 1;
    r[0].type = 0x7B; memcpy(r[0].as.v128, lanes, 16);
    return 0;
}

static wasmext_instance *make(wasmext_store *s) { return wasmext_instance_new(s, BINDING, NULL); }

static void test_unbound_and_bad_binds(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = make(s);
    char text[WASMEXT_STORE_ERROR_SIZE];
    int f = imp(i, "env", "f"), log = imp(i, "env", "log");
    CHECK(f >= 0 && log >= 0 && imp(i, "env", "absent") == -1 && imp(i, "nope", "f") == -1);
    /* an import nobody answers: the code, the name in the text of the store, nothing runs */
    CHECK(wasmext_instance_instantiate(i) == (int)WASMEXT_TRAP_LINK_ERROR);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "is not bound") != NULL && strstr(text, "vec.inc") != NULL);
    CHECK(wasmext_error_describe((int)WASMEXT_TRAP_LINK_ERROR).kind == WASMEXT_ERR_LINK);
    CHECK(log_calls == 0);
    /* binds that are refused */
    CHECK(wasmext_instance_bind_func(i, 999, host_f, NULL) == WASMEXT_INST_BAD_IMPORT);
    CHECK(wasmext_instance_bind_func(i, (uint32_t)f, NULL, NULL) == WASMEXT_INST_BAD_IMPORT);
    CHECK(wasmext_instance_bind_typed(i, (uint32_t)f, NULL, NULL) == WASMEXT_INST_BAD_IMPORT);
    /* bind them all, then try again: it works the second time */
    CHECK(wasmext_instance_bind_func(i, (uint32_t)f, host_f, (void *)0x11) == 0);
    CHECK(wasmext_instance_instantiate(i) == (int)WASMEXT_TRAP_LINK_ERROR); /* the others are not */
    wasmext_instance_free(i);
    wasmext_store_free(s);
}

static void bind_all(wasmext_instance *i) {
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "f"), host_f, (void *)0x11) == 0);
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "multi"), host_multi, NULL) == 0);
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "log"), host_log, NULL) == 0);
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "again"), host_again, NULL) == 0);
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "again0"), host_again_div0, NULL) == 0);
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "vec", "inc"), host_vec, NULL) == 0);
}

static void test_uniform(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = make(s);
    wasmext_val a[2], r[2];
    int rc;
    self = i;
    bind_all(i);
    log_calls = 0;
    CHECK(wasmext_instance_instantiate(i) == 0);
    CHECK(log_calls == 1 && log_last == 99); /* the start function called an import */
    /* bind after instantiate */
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "log"), host_log, NULL) == WASMEXT_INST_TOO_LATE);
    /* run(x) calls f(x, 7) */
    a[0] = I32(5);
    CHECK(call(i, "run", a, 1, r, 1) == 0 && r[0].type == 0x7F && r[0].as.i32 == 12);
    /* several results */
    memset(a, 0, sizeof a); a[0].type = 0x7D; a[0].as.f32 = 4.0f;
    CHECK(call(i, "twice", a, 1, r, 2) == 0 && r[0].as.i32 == 8 && r[1].type == 0x7C && r[1].as.f64 == 2.5);
    /* no result */
    a[0] = I32(42);
    CHECK(call(i, "say", a, 1, NULL, 0) == 0 && log_last == 42);
    /* a v128 both ways */
    {
        wasmext_val v[1], w[1];
        int32_t in[4] = {1, 2, 3, 4}, out[4];
        memset(v, 0, sizeof v); v[0].type = 0x7B; memcpy(v[0].as.v128, in, 16);
        CHECK(call(i, "vec", v, 1, w, 1) == 0);
        memcpy(out, w[0].as.v128, 16);
        CHECK(out[0] == 2 && out[3] == 5);
    }
    /* reentrancy: the host calls add(x, 1000) on this instance */
    a[0] = I32(5);
    again_calls = 0;
    rc = call(i, "viaagain", a, 1, r, 1);
    CHECK(rc == 0 && r[0].as.i32 == 1005 && again_calls == 1);
    /* a trap inside the nested call goes through the host and comes out of the outer call with its code; the instance is usable afterwards */
    a[0] = I32(9);
    CHECK(call(i, "viaagain0", a, 1, NULL, 0) == (int)WASM_RT_TRAP_DIV_BY_ZERO);
    a[0] = I32(5);
    CHECK(call(i, "viaagain", a, 1, r, 1) == 0 && r[0].as.i32 == 1005);
    CHECK(call(i, "run", a, 1, r, 1) == 0 && r[0].as.i32 == 12);
    wasmext_instance_free(i);
    wasmext_store_free(s);
}

static void test_failures_of_the_host(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = make(s);
    wasmext_val a[2], r[2];
    self = i;
    bind_all(i);
    CHECK(wasmext_instance_instantiate(i) == 0);
    a[0] = I32(1);
    /* a host function that fails: the host's trap, the host keeps its own error */
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "f"), host_fails, NULL) == WASMEXT_INST_TOO_LATE); /* after instantiate: not rebound */
    wasmext_instance_free(i);
    /* a second instance, to rebind before instantiate */
    i = make(s);
    self = i;
    bind_all(i);
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "f"), host_fails, NULL) == 0); /* rebinding before instantiate is fine */
    CHECK(wasmext_instance_instantiate(i) == 0);
    CHECK(call(i, "run", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    CHECK(wasmext_error_describe(wasmext_instance_status(i)).kind == WASMEXT_ERR_HOST);
    wasmext_instance_free(i);
    /* a trap of another instance goes through with its code */
    i = make(s); self = i; bind_all(i);
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "f"), host_traps_like_other, NULL) == 0);
    CHECK(wasmext_instance_instantiate(i) == 0);
    CHECK(call(i, "run", a, 1, r, 1) == (int)WASM_RT_TRAP_DIV_BY_ZERO);
    wasmext_instance_free(i);
    /* a host function that answers a result of the wrong type */
    i = make(s); self = i; bind_all(i);
    CHECK(wasmext_instance_bind_func(i, (uint32_t)imp(i, "env", "f"), host_wrong_type, NULL) == 0);
    CHECK(wasmext_instance_instantiate(i) == 0);
    CHECK(call(i, "run", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    CHECK(call(i, "say", a, 1, NULL, 0) == 0); /* usable after it */
    wasmext_instance_free(i);
    wasmext_store_free(s);
}

static void test_typed_fast_path(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = make(s);
    wasmext_val a[1], r[1];
    self = i;
    bind_all(i);
    CHECK(wasmext_instance_bind_typed(i, (uint32_t)imp(i, "env", "f"), (void *)typed_f, NULL) == 0);
    CHECK(wasmext_instance_bind_typed(i, (uint32_t)imp(i, "env", "log"), (void *)typed_log, NULL) == 0);
    log_calls = 0; f_calls = 0;
    CHECK(wasmext_instance_instantiate(i) == 0);
    CHECK(log_last == 1099);
    a[0] = I32(5);
    CHECK(call(i, "run", a, 1, r, 1) == 0 && r[0].as.i32 == 57 && f_calls == 1); /* 5 * 10 + 7 */
    a[0] = I32(3);
    CHECK(call(i, "say", a, 1, NULL, 0) == 0 && log_last == 1003);
    wasmext_instance_free(i);
    /* a typed function that fails: *trapped */
    i = make(s); self = i; bind_all(i);
    CHECK(wasmext_instance_bind_typed(i, (uint32_t)imp(i, "env", "f"), (void *)typed_fails, NULL) == 0);
    CHECK(wasmext_instance_instantiate(i) == 0);
    a[0] = I32(1);
    CHECK(call(i, "run", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
    wasmext_instance_free(i);
    wasmext_store_free(s);
}

static void test_closed_store(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = make(s);
    self = i;
    bind_all(i);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(wasmext_instance_instantiate(i) == (int)WASMEXT_TRAP_CLOSED);
    wasmext_instance_free(i);
    wasmext_store_free(s);
}

int main(void) {
    test_unbound_and_bad_binds();
    test_uniform();
    test_failures_of_the_host();
    test_typed_fast_path();
    test_closed_store();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
