/* The WASI 0.2 imports of a module (a fused core module: flat types, the canonical ABI by hand) answered by the host of the store. Plain C over a real wasm2c module. */
#include <stdio.h>
#include "wasmext_host.h"
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
static int call(wasmext_instance *i, const char *name, const wasmext_val *a, uint32_t na, wasmext_val *r, uint32_t nr) {
    return wasmext_instance_call(i, (uint32_t)fn(i, name), a, na, r, nr);
}

static char written[256];
static size_t written_n;
static int write_calls, last_fd;
static int hook_write(void *user, int fd, const uint8_t *buf, size_t n) {
    (void)user;
    write_calls++;
    last_fd = fd;
    if (written_n + n < sizeof written) { memcpy(written + written_n, buf, n); written_n += n; }
    return 0;
}
static int hook_clock(void *user, uint32_t id, uint64_t *ns) { (void)user; (void)id; *ns = 123456789u; return 0; }
static int hook_random(void *user, uint8_t *buf, size_t n) { (void)user; memset(buf, 0xAB, n); return 0; }

static wasmext_store *make_store(void) {
    static const char *args[] = {"prog", "one"};
    wasmext_config c;
    wasmext_store *s = wasmext_store_new();
    wasmext_host *h;
    int err;
    memset(&c, 0, sizeof c);
    c.args = args; c.nargs = 2;
    c.stdout_write = hook_write; c.clock = hook_clock; c.random = hook_random;
    h = wasmext_host_new(&c, "prog", &err);
    CHECK(h != NULL);
    CHECK(wasmext_store_set_host(s, h, wasmext_host_free, &h->lock) == WASMEXT_STORE_OK);
    return s;
}

static void test_the_calls(void) {
    wasmext_store *s = make_store();
    wasmext_instance *i = wasmext_instance_new(s, BINDING, NULL);
    wasmext_val a[1], r[1];
    uint32_t value = 99;
    CHECK(wasmext_instance_instantiate(i) == 0);
    /* stdout: get-stdout, then blocking-write-and-flush; the result<_, stream-error> is in memory: 0 is ok */
    write_calls = 0; written_n = 0;
    CHECK(call(i, "hello", NULL, 0, r, 1) == 0 && r[0].as.i32 == 0);
    CHECK(write_calls == 1 && last_fd == 1 && written_n == 3 && memcmp(written, "hi\n", 3) == 0);
    /* get-arguments: a list<string> that the host allocates through cabi_realloc of the module */
    CHECK(call(i, "argc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 2);
    /* the clock and the random bytes come from the hooks */
    CHECK(call(i, "now", NULL, 0, r, 1) == 0 && r[0].type == 0x7E && r[0].as.i64 == 123456789);
    CHECK(call(i, "rand", NULL, 0, r, 1) == 0 && (uint64_t)r[0].as.i64 == 0xABABABABABABABABull);
    /* exit(status): the status is the flat result<_, _>: 1 is an error */
    CHECK(wasmext_instance_wasi_end(i, &value) == WASMEXT_END_NONE);
    a[0] = I32(1);
    CHECK(call(i, "exit", a, 1, NULL, 0) == (int)WASMEXT_TRAP_HOST);
    CHECK(wasmext_instance_wasi_end(i, &value) == WASMEXT_END_EXIT && value == 1);
    CHECK(call(i, "argc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 2); /* usable afterwards, the end forgotten */
    CHECK(wasmext_instance_wasi_end(i, &value) == WASMEXT_END_NONE);
    a[0] = I32(0);
    CHECK(call(i, "exit", a, 1, NULL, 0) == (int)WASMEXT_TRAP_HOST);
    CHECK(wasmext_instance_wasi_end(i, &value) == WASMEXT_END_EXIT && value == 0);
    CHECK(wasmext_rlock_depth(&((wasmext_host *)wasmext_store_host(s))->lock) == 0);
    wasmext_instance_free(i);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    wasmext_store_free(s);
}

/* two instances share the host: the same stdout hook, the same arguments */
static void test_two_instances(void) {
    wasmext_store *s = make_store();
    wasmext_instance *a = wasmext_instance_new(s, BINDING, NULL), *b = wasmext_instance_new(s, BINDING, NULL);
    wasmext_val r[1];
    CHECK(wasmext_instance_instantiate(a) == 0 && wasmext_instance_instantiate(b) == 0);
    write_calls = 0; written_n = 0;
    CHECK(call(a, "hello", NULL, 0, r, 1) == 0 && call(b, "hello", NULL, 0, r, 1) == 0);
    CHECK(write_calls == 2 && written_n == 6);
    CHECK(call(a, "argc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 2 && call(b, "argc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 2);
    wasmext_instance_free(a);
    wasmext_instance_free(b);
    wasmext_store_free(s);
}

int main(void) {
    test_the_calls();
    test_two_instances();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
