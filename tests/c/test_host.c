/* Tests of wasmext_host.h in plain C over the headers of fusedwasi and the runtime of wasm2c: no module, no Python. Exit 0 and "ok" when all pass. */
#include <stdio.h>
#include "wasmext_host.h"
#include "wasmext_store.h"

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

/* ---- hooks that record what they were given ---- */
static struct { int fd; char data[64]; size_t n; int calls; } out;
static int hook_out(void *user, int fd, const uint8_t *buf, size_t n) {
    out.calls++;
    out.fd = fd;
    out.n = n < sizeof out.data ? n : sizeof out.data;
    memcpy(out.data, buf, out.n);
    return user == (void *)0x5a ? 0 : EINVAL;
}
static int in_rc, in_len;
static int hook_in(void *user, uint8_t *buf, size_t cap, size_t *got) {
    (void)user;
    if (in_rc) return in_rc;
    *got = (size_t)in_len < cap ? (size_t)in_len : cap;
    memset(buf, 'z', *got);
    return 0;
}
static int hook_clock(void *user, uint32_t id, uint64_t *ns) { (void)user; *ns = 1000u + id; return id == 9 ? 1 : (id == 8 ? WASMEXT_HOOK_TRAP : 0); }
static int hook_random(void *user, uint8_t *buf, size_t n) { (void)user; memset(buf, 7, n); return 0; }
static uint64_t slept;
static int hook_sleep(void *user, uint64_t ns) { (void)user; slept += ns; return 0; }
static int policy_rc, policy_calls;
static int hook_sockets(void *user, const char *ip, uint16_t port, uint32_t use) { (void)user; policy_calls++; return strcmp(ip, "10.0.0.1") == 0 && port == 80 && use == 1 ? 1 : policy_rc; }
static int hook_http(void *user, const char *scheme, const char *authority) { (void)user; policy_calls++; return strcmp(scheme, "https") == 0 && strcmp(authority, "example.org") == 0 ? 1 : policy_rc; }

static void test_defaults(void) {
    int err = -1;
    wasmext_host *h = wasmext_host_new(NULL, "prog", &err);
    CHECK(h != NULL && err == 0);
    CHECK(h->wasi.arg_count == 1 && strcmp(h->wasi.args[0], "prog") == 0); /* the name of the module is the first argument */
    CHECK(h->wasi.env_count == 0 && h->wasi.preopen_count == 0);
    CHECK(h->wasi.std[0] == NULL && h->wasi.std[1] == NULL && h->wasi.std[2] == NULL); /* the descriptors of the process */
    CHECK(h->wasi.user == h);
    CHECK(h->wasi.socket_addr_check(&h->wasi, "1.2.3.4", 1, FUSEDWASI_P2_USE_TCP_CONNECT) == 0); /* the network is refused */
    CHECK(h->wasi.http_check(&h->wasi, "https", "a") == 0);
    wasmext_host_free(h);
    wasmext_host_free(NULL);
    h = wasmext_host_new(NULL, NULL, NULL);
    CHECK(h != NULL && strcmp(h->wasi.args[0], "wasm") == 0);
    wasmext_host_free(h);
}

static void test_copied_configuration(void) {
    const char *args[] = {"a", "b c"};
    const char *env[] = {"K=V", "ONLY_NAME", "EMPTY=", "A=B=C"};
    const char *dirs[] = {"/tmp::/data", "/x", "/y::", "/z::/w"};
    const int ro[] = {0, 1, 0, 1};
    wasmext_config c;
    wasmext_host *h;
    int err = -1;
    memset(&c, 0, sizeof c);
    c.args = args; c.nargs = 2; c.env = env; c.nenv = 4; c.dirs = dirs; c.ndirs = 4; c.dirs_readonly = ro;
    h = wasmext_host_new(&c, "prog", &err);
#ifdef WASMEXT_HOST_P1
    CHECK(h == NULL && err != 0); /* WASI 0.1 opens the directories now: /x does not exist */
    return;
#endif
    CHECK(h != NULL && err == 0);
    CHECK(h->wasi.arg_count == 2 && strcmp(h->wasi.args[0], "a") == 0 && strcmp(h->wasi.args[1], "b c") == 0);
    CHECK(h->wasi.args[0] != args[0]); /* a copy: the caller may drop its strings */
    CHECK(h->wasi.env_count == 4);
    CHECK(strcmp(h->wasi.env_names[0], "K") == 0 && strcmp(h->wasi.env_values[0], "V") == 0);
    CHECK(strcmp(h->wasi.env_names[1], "ONLY_NAME") == 0 && strcmp(h->wasi.env_values[1], "") == 0);
    CHECK(strcmp(h->wasi.env_names[2], "EMPTY") == 0 && strcmp(h->wasi.env_values[2], "") == 0);
    CHECK(strcmp(h->wasi.env_names[3], "A") == 0 && strcmp(h->wasi.env_values[3], "B=C") == 0); /* cut at the first '=' */
    CHECK(h->wasi.preopen_count == 4);
    CHECK(strcmp(h->wasi.preopens[0].path, "/tmp") == 0 && strcmp(h->wasi.preopens[0].name, "/data") == 0 && h->wasi.preopens[0].writable);
    CHECK(strcmp(h->wasi.preopens[1].path, "/x") == 0 && strcmp(h->wasi.preopens[1].name, "/") == 0 && !h->wasi.preopens[1].writable);
    CHECK(strcmp(h->wasi.preopens[2].path, "/y") == 0 && strcmp(h->wasi.preopens[2].name, "/") == 0 && h->wasi.preopens[2].writable);
    CHECK(strcmp(h->wasi.preopens[3].name, "/w") == 0 && !h->wasi.preopens[3].writable);
    wasmext_host_free(h);
    c.nargs = 0; /* not NULL with no arguments: no arguments */
    h = wasmext_host_new(&c, "prog", &err);
    CHECK(h != NULL && h->wasi.arg_count == 0);
    wasmext_host_free(h);
}

static void test_bad_configuration(void) {
    const char *env_null[] = {"A=1", NULL};
    wasmext_config c;
    int err = 0;
    memset(&c, 0, sizeof c);
    c.nenv = 1; /* an array that is NULL with a count */
    CHECK(wasmext_host_new(&c, "p", &err) == NULL && err == EINVAL);
    c.nenv = 0; c.ndirs = 2;
    CHECK(wasmext_host_new(&c, "p", &err) == NULL && err == EINVAL);
    c.ndirs = 0; c.env = env_null; c.nenv = 2; /* an item that is NULL */
    CHECK(wasmext_host_new(&c, "p", &err) == NULL && err == EINVAL);
}

static void test_hooks(void) {
    wasmext_config c;
    wasmext_host *h;
    int err = -1, status;
    uint8_t buf[16];
    uint64_t got, ns;
    memset(&c, 0, sizeof c);
    c.stdin_read = hook_in; c.stdout_write = hook_out; c.clock = hook_clock; c.random = hook_random; c.sleep = hook_sleep;
    c.sockets = hook_sockets; c.http = hook_http; c.user = (void *)0x5a;
    h = wasmext_host_new(&c, "p", &err);
    CHECK(h != NULL);
    /* stdout and stderr reach the hook with the fd */
    CHECK(h->wasi.std[1]->write(&h->wasi, h->wasi.std[1], (const uint8_t *)"hello", 5) == FUSEDWASI_P2_STREAM_OK);
    CHECK(out.calls == 1 && out.fd == 1 && out.n == 5 && memcmp(out.data, "hello", 5) == 0);
    CHECK(h->wasi.std[2]->write(&h->wasi, h->wasi.std[2], (const uint8_t *)"e", 1) == FUSEDWASI_P2_STREAM_OK && out.fd == 2);
    CHECK(h->wasi.std[1]->write(&h->wasi, h->wasi.std[1], (const uint8_t *)"", 0) == FUSEDWASI_P2_STREAM_OK && out.calls == 2); /* nothing to write: no call */
    CHECK(h->wasi.std[1]->flush(&h->wasi, h->wasi.std[1]) == FUSEDWASI_P2_STREAM_OK);
    CHECK(h->wasi.std[1]->check_write(&h->wasi, h->wasi.std[1], &status) == 65536u && status == FUSEDWASI_P2_STREAM_OK);
    /* stdin: data, the end, a closed pipe, a failure */
    in_rc = 0; in_len = 4;
    CHECK(h->wasi.std[0]->read(&h->wasi, h->wasi.std[0], buf, 16, &got) == FUSEDWASI_P2_STREAM_OK && got == 4 && buf[0] == 'z');
    in_len = 0;
    CHECK(h->wasi.std[0]->read(&h->wasi, h->wasi.std[0], buf, 16, &got) == FUSEDWASI_P2_STREAM_CLOSED && got == 0); /* nothing at all is the end of the input */
    in_rc = 64;
    CHECK(h->wasi.std[0]->read(&h->wasi, h->wasi.std[0], buf, 16, &got) == FUSEDWASI_P2_STREAM_CLOSED);
    in_rc = 5;
    CHECK(h->wasi.std[0]->read(&h->wasi, h->wasi.std[0], buf, 16, &got) == FUSEDWASI_P2_STREAM_FAILED);
    CHECK(h->wasi.std[0]->failure != NULL && h->wasi.std[0]->failure_errno != 0);
    /* the clock, random bytes, sleeping */
    CHECK(h->wasi.clock(&h->wasi, 1, &ns) == 0 && ns == 1001u);
    CHECK(h->wasi.clock(&h->wasi, 9, &ns) != 0); /* the clock cannot be read: not a trap */
    memset(buf, 0, sizeof buf);
    CHECK(h->wasi.random_bytes(&h->wasi, buf, 4) == 0 && buf[3] == 7);
    CHECK(h->wasi.insecure_random_bytes == h->wasi.random_bytes);
    CHECK(h->wasi.sleep(&h->wasi, 123) == 0 && slept == 123u);
    CHECK(h->wait != NULL);
    /* the policies of the network */
    CHECK(h->wasi.socket_addr_check(&h->wasi, "10.0.0.1", 80, FUSEDWASI_P2_USE_TCP_CONNECT) == 1);
    policy_rc = 0;
    CHECK(h->wasi.socket_addr_check(&h->wasi, "10.0.0.2", 80, FUSEDWASI_P2_USE_TCP_CONNECT) == 0);
    CHECK(h->wasi.http_check(&h->wasi, "https", "example.org") == 1 && h->wasi.http_check(&h->wasi, "http", "example.org") == 0);
    h->no_tcp = 1; policy_calls = 0;
    CHECK(h->wasi.socket_addr_check(&h->wasi, "10.0.0.1", 80, FUSEDWASI_P2_USE_TCP_CONNECT) == 0 && policy_calls == 0); /* refused without asking */
    CHECK(h->wasi.socket_addr_check(&h->wasi, "10.0.0.1", 80, FUSEDWASI_P2_USE_UDP_BIND) == 0 && policy_calls == 1);     /* udp is another protocol */
    h->no_tcp = 0; h->sockets_all = 1; h->http_all = 1; policy_calls = 0;
    CHECK(h->wasi.socket_addr_check(&h->wasi, "9.9.9.9", 1, FUSEDWASI_P2_USE_TCP_BIND) == 1 && h->wasi.http_check(&h->wasi, "x", "y") == 1 && policy_calls == 0);
    h->no_udp = 1;
    CHECK(h->wasi.socket_addr_check(&h->wasi, "9.9.9.9", 1, FUSEDWASI_P2_USE_UDP_CONNECT) == 0);
    wasmext_host_free(h);
}

/* a hook that fails on its own traps the host: the trap comes back to the entry of the call, with the message kept */
static void test_trap_of_the_host(void) {
    wasmext_config c;
    wasmext_host *h;
    wasm_rt_trap_t code;
    uint64_t ns;
    int err;
    memset(&c, 0, sizeof c);
    c.clock = hook_clock;
    h = wasmext_host_new(&c, "p", &err);
    CHECK(h != NULL);
    code = (wasm_rt_trap_t)wasm_rt_try(g_wasm_rt_jmp_buf);
    if (code == 0) {
        h->wasi.clock(&h->wasi, 8, &ns); /* the hook answers WASMEXT_HOOK_TRAP */
        CHECK(0 && "not reached");
    } else {
        CHECK(code == WASMEXT_TRAP_HOST);
        CHECK(strcmp(h->message, "the clock of the host failed") == 0);
    }
    wasmext_host_free(h);
}

static int released;
static void released_host(void *host) { released++; wasmext_host_free(host); }

/* the store owns the host and lets it go when it is closed */
static void test_owned_by_the_store(void) {
    wasmext_store *s = wasmext_store_new();
    int err;
    wasmext_host *h = wasmext_host_new(NULL, "p", &err);
    CHECK(wasmext_store_own(s, h, released_host) == WASMEXT_STORE_OK);
    CHECK(released == 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    CHECK(released == 1);
    wasmext_store_free(s);
}

int main(void) {
    test_defaults();
    test_copied_configuration();
    test_bad_configuration();
    test_hooks();
    test_trap_of_the_host();
    test_owned_by_the_store();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
