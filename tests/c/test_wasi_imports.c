/* The WASI imports of a module answered by the host of the store (WASI 0.1), in plain C: a store, a host with hooks, instances of a real wasm2c module. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_host.h"
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

/* a store with a host: the configuration, the hooks */
static wasmext_store *make_store(void) {
    static const char *args[] = {"prog", "one"};
    static const char *env[] = {"K=V", "A=B"};
    wasmext_config c;
    wasmext_store *s = wasmext_store_new();
    wasmext_host *h;
    int err;
    memset(&c, 0, sizeof c);
    c.args = args; c.nargs = 2; c.env = env; c.nenv = 2;
    c.stdout_write = hook_write; c.clock = hook_clock; c.random = hook_random;
    h = wasmext_host_new(&c, "prog", &err);
    CHECK(h != NULL);
    CHECK(wasmext_store_set_host(s, h, wasmext_host_free, &h->lock) == WASMEXT_STORE_OK);
    return s;
}

static void test_a_store_with_no_host(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = wasmext_instance_new(s, BINDING, NULL);
    char text[WASMEXT_STORE_ERROR_SIZE];
    CHECK(wasmext_instance_instantiate(i) == (int)WASMEXT_TRAP_LINK_ERROR);
    wasmext_store_error(s, text, sizeof text);
    CHECK(strstr(text, "no host") != NULL);
    CHECK(wasmext_instance_bind_func(i, 0, NULL, NULL) == WASMEXT_INST_BAD_IMPORT); /* a core import cannot be bound by hand */
    wasmext_instance_free(i);
    wasmext_store_free(s);
}

static void test_the_calls(void) {
    wasmext_store *s = make_store();
    wasmext_instance *i = wasmext_instance_new(s, BINDING, NULL);
    wasmext_val a[2], r[2];
    CHECK(wasmext_instance_instantiate(i) == 0);
    /* fd_write of "hi\n" to stdout through the hook */
    write_calls = 0; written_n = 0;
    CHECK(call(i, "hello", NULL, 0, r, 1) == 0 && r[0].as.i32 == 0); /* errno 0 */
    CHECK(write_calls == 1 && last_fd == 1 && written_n == 3 && memcmp(written, "hi\n", 3) == 0);
    /* the arguments and the environment of the host */
    CHECK(call(i, "argc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 2);
    CHECK(call(i, "environc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 2);
    /* the clock and random bytes come from the hooks */
    CHECK(call(i, "time", NULL, 0, r, 1) == 0 && r[0].type == 0x7E && r[0].as.i64 == 123456789);
    CHECK(call(i, "random", NULL, 0, r, 1) == 0 && r[0].as.i32 == (int32_t)0xABABABABu);
    /* proc_exit: the call answers the trap of the host, and says how the program ended */
    {
        uint32_t value = 99;
        CHECK(wasmext_instance_wasi_end(i, &value) == WASMEXT_END_NONE && value == 0);
        a[0] = I32(7);
        CHECK(call(i, "exit", a, 1, NULL, 0) == (int)WASMEXT_TRAP_HOST);
        CHECK(wasmext_instance_wasi_end(i, &value) == WASMEXT_END_EXIT && value == 7);
        /* the end is what the call leaves: the next call forgets it, the instance is usable */
        CHECK(call(i, "argc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 2);
        CHECK(wasmext_instance_wasi_end(i, &value) == WASMEXT_END_NONE);
        /* proc_raise: a signal that ends a process, and one that does not */
        a[0] = I32(15);
        CHECK(call(i, "raise", a, 1, r, 1) == (int)WASMEXT_TRAP_HOST);
        CHECK(wasmext_instance_wasi_end(i, &value) == WASMEXT_END_SIGNAL && value == 15);
        a[0] = I32(20); /* SIGCHLD: ignored when nothing handles it */
        CHECK(call(i, "raise", a, 1, r, 1) == 0 && r[0].as.i32 == 0);
        CHECK(wasmext_instance_wasi_end(i, &value) == WASMEXT_END_NONE);
    }
    /* the host lock was let go by every trap above: it can be taken from here */
    {
        wasmext_host *h = (wasmext_host *)wasmext_store_host(s);
        CHECK(wasmext_rlock_depth(&h->lock) == 0);
    }
    wasmext_instance_free(i);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    wasmext_store_free(s);
}

/* two instances of one module in one store: one host, the same hooks and arguments */
static void test_two_instances_share_the_host(void) {
    wasmext_store *s = make_store();
    wasmext_instance *a = wasmext_instance_new(s, BINDING, NULL), *b = wasmext_instance_new(s, BINDING, NULL);
    wasmext_val r[1];
    CHECK(wasmext_instance_instantiate(a) == 0 && wasmext_instance_instantiate(b) == 0);
    write_calls = 0; written_n = 0;
    CHECK(call(a, "hello", NULL, 0, r, 1) == 0 && call(b, "hello", NULL, 0, r, 1) == 0);
    CHECK(write_calls == 2 && written_n == 6);
    CHECK(call(a, "argc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 2 && call(b, "argc", NULL, 0, r, 1) == 0 && r[0].as.i32 == 2);
    { /* one instance ends its program: the other is not touched */
        wasmext_val e = I32(3);
        uint32_t value;
        CHECK(call(a, "exit", &e, 1, NULL, 0) == (int)WASMEXT_TRAP_HOST);
        CHECK(wasmext_instance_wasi_end(a, &value) == WASMEXT_END_EXIT && value == 3);
        CHECK(wasmext_instance_wasi_end(b, &value) == WASMEXT_END_NONE);
        CHECK(call(b, "argc", NULL, 0, r, 1) == 0);
    }
    wasmext_instance_free(a);
    wasmext_instance_free(b);
    wasmext_store_free(s);
}

/* many threads call WASI of instances of one store: the lock of the host keeps the state of fusedwasi right */
#ifdef _WIN32
#include <process.h>
typedef HANDLE thread_t;
#define THREAD_RESULT unsigned __stdcall
static void thread_start(thread_t *t, unsigned (__stdcall *f)(void *), void *arg) { *t = (HANDLE)_beginthreadex(NULL, 0, f, arg, 0, NULL); }
static void thread_join(thread_t t) { WaitForSingleObject(t, INFINITE); CloseHandle(t); }
#else
typedef pthread_t thread_t;
#define THREAD_RESULT void *
static void thread_start(thread_t *t, THREAD_RESULT (*f)(void *), void *arg) { pthread_create(t, NULL, f, arg); }
static void thread_join(thread_t t) { pthread_join(t, NULL); }
#endif
typedef struct { wasmext_instance *i; int failed; } work_t;
static THREAD_RESULT worker(void *arg) {
    work_t *w = (work_t *)arg;
    for (int n = 0; n < 300; n++) {
        wasmext_val r[1], e = I32(1);
        if (call(w->i, "hello", NULL, 0, r, 1) != 0) w->failed = 1;
        if (call(w->i, "argc", NULL, 0, r, 1) != 0 || r[0].as.i32 != 2) w->failed = 1;
        if (call(w->i, "exit", &e, 1, NULL, 0) != (int)WASMEXT_TRAP_HOST) w->failed = 1; /* a trap while others hold or wait for the lock */
    }
    wasmext_thread_free();
    return 0;
}
static void test_threads(void) {
    enum { N = 4 };
    wasmext_store *s = make_store();
    wasmext_instance *inst[N];
    work_t w[N];
    thread_t t[N];
    for (int k = 0; k < N; k++) { inst[k] = wasmext_instance_new(s, BINDING, NULL); CHECK(wasmext_instance_instantiate(inst[k]) == 0); w[k].i = inst[k]; w[k].failed = 0; }
    write_calls = 0;
    for (int k = 0; k < N; k++) thread_start(&t[k], worker, &w[k]);
    for (int k = 0; k < N; k++) { thread_join(t[k]); CHECK(!w[k].failed); }
    CHECK(write_calls == N * 300); /* the hook ran under the lock: no write was lost (a plain counter) */
    CHECK(wasmext_rlock_depth(&((wasmext_host *)wasmext_store_host(s))->lock) == 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    for (int k = 0; k < N; k++) wasmext_instance_free(inst[k]);
    wasmext_store_free(s);
}

int main(void) {
    test_a_store_with_no_host();
    test_the_calls();
    test_two_instances_share_the_host();
    test_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
