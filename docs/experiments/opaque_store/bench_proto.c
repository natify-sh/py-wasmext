/* Benchmark of the call path of the static core (tools/bench_calls.py builds and runs it): `bench_calls <case> <n>` makes n calls of one case and prints
   `<case> <n> <seconds> <calls per second>`. Not a test: nothing is checked but the results of the calls (a wrong one aborts the run).
     1 wasmext_instance_call of ops.add (the generic adapter, store enter/leave)
     2 the same function through a link: app.call_add calls the import libx.add that lib answers (typed shim, TRAP_LINKED conversion)
     3 bench.run calls an import that a uniform host function answers (wasmext_instance_bind_func)
     4 the same import answered by a typed host function (wasmext_instance_bind_typed)
     5 owner.call(1): call_indirect through a table that owner and user share, slot 1 holds user.nine
     6 reference: w2c_ops_add called directly inside WASMEXT_ENTER_PLAIN / WASMEXT_LEAVE_PLAIN (no store)
   Cases 3 to 5 include the call of the export that holds the import or the call_indirect, as every user-visible call does. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "proto_ops.h" /* PROTO: the store ops (B) or wasmext_instance_call (C) go through the table of store_lib.c */
#if defined(PROTO_B) || defined(PROTO_C)
const proto_ops *proto_tab;
#endif

extern const wasmext_binding ops_binding, lib_binding, app_binding, bench_binding, owner_binding, user_binding;
extern uint32_t w2c_ops_add(void *instance, uint32_t a, uint32_t b); /* the function of wasm2c (instance first, as the glue calls it) */

static volatile int32_t sink; /* the results go here: the loops are not folded */

static wasmext_val I32(int32_t v) { wasmext_val x; memset(&x, 0, sizeof x); x.type = 0x7F; x.as.i32 = v; return x; }
static void die(const char *what, int line) { fprintf(stderr, "bench_calls.c:%d: %s\n", line, what); exit(2); }
#define MUST(COND) do { if (!(COND)) die(#COND, __LINE__); } while (0)

static uint32_t fn(wasmext_instance *i, const char *name) {
    int k = wasmext_instance_export_find(i, name, strlen(name), WASMEXT_DESC_FUNC);
    MUST(k >= 0);
    return (uint32_t)k;
}
/* the index of the import `module.name` of any kind (wasmext_instance_import_find knows the functions only) */
static uint32_t imp(wasmext_instance *i, const char *module, const char *name) {
    const wasmext_descriptor *d = i->binding->descriptor;
    for (uint32_t k = 0; k < d->n_imports; k++)
        if (d->imports[k].module.n == strlen(module) && memcmp(d->imports[k].module.p, module, d->imports[k].module.n) == 0 &&
            d->imports[k].name.n == strlen(name) && memcmp(d->imports[k].name.p, name, d->imports[k].name.n) == 0)
            return k;
    die("no such import", __LINE__);
    return 0;
}
static wasmext_instance *make(wasmext_store *s, const wasmext_binding *b) {
    wasmext_instance *i = wasmext_instance_new(s, b, NULL);
    MUST(i != NULL);
    return i;
}
/* gives the import `module.name` of `to` the export `export_name` of `from`, of the given kind */
static void link_export(wasmext_instance *to, const char *module, const char *name, wasmext_instance *from, const char *export_name, int kind) {
    wasmext_export rec;
    int k = wasmext_instance_export_find(from, export_name, strlen(export_name), kind);
    MUST(k >= 0);
    MUST(wasmext_instance_export_record(from, (uint32_t)k, NULL, &rec) == 0);
    MUST(wasmext_instance_bind_export(to, imp(to, module, name), &rec) == 0);
}

static int host_add(void *user, const wasmext_val *a, wasmext_val *r) {
    (void)user;
    r[0] = I32(a[0].as.i32 + a[1].as.i32);
    return 0;
}
static uint32_t typed_add(void *user, uint32_t a, uint32_t b, int *trapped) {
    (void)user;
    *trapped = 0;
    return a + b;
}

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

int main(int argc, char **argv) {
    int which = argc > 1 ? atoi(argv[1]) : 0;
    long n = argc > 2 ? atol(argv[2]) : 0;
#if defined(PROTO_B) || defined(PROTO_C)
    proto_tab = proto_get();
#endif
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *main_i = NULL, *ops = NULL;
    uint32_t export_index = 0;
    wasmext_val a[2], r[1];
    double t0, t1;
    MUST(s != NULL && which >= 1 && which <= 6 && n > 0);
    switch (which) {
    case 1: case 6:
        ops = main_i = make(s, &ops_binding);
        MUST(wasmext_instance_instantiate(ops) == 0);
        export_index = fn(ops, "add");
        break;
    case 2: {
        wasmext_instance *lib = make(s, &lib_binding);
        main_i = make(s, &app_binding);
        MUST(wasmext_instance_instantiate(lib) == 0);
        link_export(main_i, "libx", "add", lib, "add", WASMEXT_DESC_FUNC);
        MUST(wasmext_instance_instantiate(main_i) == 0);
        export_index = fn(main_i, "call_add");
        break;
    }
    case 3: case 4:
        main_i = make(s, &bench_binding);
        MUST((which == 3 ? wasmext_instance_bind_func(main_i, imp(main_i, "env", "f"), host_add, NULL)
                         : wasmext_instance_bind_typed(main_i, imp(main_i, "env", "f"), (void *)typed_add, NULL)) == 0);
        MUST(wasmext_instance_instantiate(main_i) == 0);
        export_index = fn(main_i, "run");
        break;
    case 5: {
        wasmext_instance *owner = make(s, &owner_binding), *user = make(s, &user_binding);
        MUST(wasmext_instance_instantiate(owner) == 0);
        link_export(user, "own_u", "tab", owner, "tab", WASMEXT_DESC_TABLE);
        MUST(wasmext_instance_instantiate(user) == 0);
        main_i = owner;
        export_index = fn(owner, "call");
        break;
    }
    }
    a[0] = I32(1);
    a[1] = I32(2);
    if (which == 5) { a[0] = I32(1); MUST(wasmext_instance_call(main_i, export_index, a, 1, r, 1) == 0 && r[0].as.i32 == 9); }
    else if (which != 6) { MUST(wasmext_instance_call(main_i, export_index, a, 2, r, 1) == 0 && r[0].as.i32 == 3); }
    t0 = now();
    if (which == 6) {
        void *inst = ops->module;
        int32_t acc = 0;
        for (long k = 0; k < n; k++) {
            uint32_t res;
            WASMEXT_ENTER_PLAIN(trap_, { die("trap", __LINE__); })
            res = w2c_ops_add(inst, (uint32_t)k, 2u);
            WASMEXT_LEAVE_PLAIN();
            acc += (int32_t)res;
        }
        sink = acc;
    } else {
        int32_t acc = 0;
        uint32_t na = which == 5 ? 1u : 2u;
        for (long k = 0; k < n; k++) {
            a[0] = I32(which == 5 ? 1 : (int32_t)k);
            if (wasmext_instance_call(main_i, export_index, a, na, r, 1) != 0) die("call failed", __LINE__);
            acc += r[0].as.i32;
        }
        sink = acc;
    }
    t1 = now();
    printf("%d %ld %.6f %.1f\n", which, n, t1 - t0, (double)n / (t1 - t0));
    return 0;
}
