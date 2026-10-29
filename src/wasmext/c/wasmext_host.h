/* The host of WASI of a store: the configuration (arguments, environment, directories, the hooks of the standard streams, the clocks, the random bytes and sleeping, the
   policies of the network) and the state of fusedwasi built from it. The same for every module and every front end: the library, the executable and the extension
   all make their host here, and a front end that is not C gives the hooks as functions with a `user`.

   `wasmext_host_new` makes it, `wasmext_host_free` lets it go; a store owns it through its arena (`wasmext_store_own(store, host, wasmext_host_free)`), as it owns
   any other object. Needs the headers of fusedwasi and the runtime of wasm2c (a failed hook traps the host), not a module. Define WASMEXT_HOST_P1 in a build for
   WASI 0.1: the descriptors of 0.1 are then made at once (a directory that cannot be opened is told by `wasmext_host_new`), and an errno of WASI is turned back
   into the system's. See docs/step2_store.md. */
#ifndef WASMEXT_HOST_H
#define WASMEXT_HOST_H

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wasmext_glue.h"
#include "fusedwasi/p2/wasi_p2_core.h"
#include "fusedwasi/p2/wasi_p2_io.h"
#ifdef WASMEXT_HOST_P1
#include "fusedwasi/p1/wasi_p1_core.h"
#endif

/* what a hook answers for a failure of its own (a positive number below it is an errno of WASI): the host traps */
#define WASMEXT_HOOK_TRAP 0x10000

/* Every field may be 0. A hook answers 0, an errno of WASI, or WASMEXT_HOOK_TRAP; without one the core uses the descriptors 0, 1 and 2 and the system. */
typedef struct {
    const char *const *args; size_t nargs;  /* NULL: the name of the module; not NULL with nargs 0: no arguments */
    const char *const *env; size_t nenv;    /* "NAME=value", cut at the first '='; an item with no '=' or with an empty NAME is EINVAL */
    const char *const *dirs; size_t ndirs;  /* "host::guest", both parts not empty; anything else is EINVAL */
    const int *dirs_readonly;               /* NULL, or a flag for each dir: 1 for a directory that the program cannot change */
    int (*stdin_read)(void *user, uint8_t *buf, size_t cap, size_t *got);
    int (*stdout_write)(void *user, int fd, const uint8_t *buf, size_t n);  /* fd 1 or 2 */
    int (*clock)(void *user, uint32_t id, uint64_t *ns);  /* id: 0 realtime, 1 monotonic, 2 and 3 of the process and the thread */
    int (*random)(void *user, uint8_t *buf, size_t n);
    int (*sleep)(void *user, uint64_t ns);  /* without it the core sleeps in slices of 100 ms */
    void *user;
    /* WASI 0.2: the network is refused unless it is allowed here (as in Wasmtime). 1 allows, 0 refuses, a negative number is a failure (a trap). Unused by 0.1. */
    int (*sockets)(void *user, const char *ip, uint16_t port, uint32_t use);  /* use: 0 tcp-bind, 1 tcp-connect, 2 udp-bind, 3 udp-connect, 4 udp-outgoing */
    int sockets_all;       /* every bind and connect is allowed (the function is not asked) */
    int no_tcp, no_udp;    /* the protocol is refused whatever `sockets` says */
    int dns;               /* names may be resolved */
    int (*http)(void *user, const char *scheme, const char *authority);
    int http_all;
} wasmext_config;

typedef struct wasmext_host {
    fusedwasi_p2_state wasi;  /* first: the world of the host, one for WASI 0.1 and 0.2, shared by the instances of the store; its `user` is this struct */
    int (*stdin_read)(void *user, uint8_t *buf, size_t cap, size_t *got);
    int (*stdout_write)(void *user, int fd, const uint8_t *buf, size_t n);
    int (*clock)(void *user, uint32_t id, uint64_t *ns);
    int (*random)(void *user, uint8_t *buf, size_t n);
    int (*sleep)(void *user, uint64_t ns);
    int (*sockets)(void *user, const char *ip, uint16_t port, uint32_t use);
    int (*http)(void *user, const char *scheme, const char *authority);
    int sockets_all, no_tcp, no_udp, http_all;
    void *user;
    char **args_v, **env_n, **env_v;
    size_t nargs_v, nenv_v;
    struct fusedwasi_p2_preopen *preopens;
    size_t npreopens;
    fusedwasi_p2_stream streams[3];
    char message[160];  /* why the host trapped, when it did not say with an exception of the front end */
    void (*wait)(fusedwasi_p2_guest *g);  /* the `wait` for the guests of this host (NULL: the default of fusedwasi) */
} wasmext_host;

static inline wasmext_host *wasmext_host_of_(fusedwasi_p2_state *s) { return (wasmext_host *)s->user; }

static inline void wasmext_host_trap_(fusedwasi_p2_state *s, const char *message) {
    snprintf(wasmext_host_of_(s)->message, sizeof(((wasmext_host *)0)->message), "%s", message);
    wasm_rt_trap(WASMEXT_TRAP_HOST);
}

static inline char *wasmext_host_dup_(const char *text) {
    size_t n = strlen(text) + 1;
    char *copy = (char *)malloc(n);
    if (copy != NULL) memcpy(copy, text, n);
    return copy;
}

/* the errno of the system for an errno of WASI that a hook gave (the first that WASI 0.1 would turn back into it); 0.2 has only the message */
static inline int wasmext_host_c_errno_(int wasi) {
#ifdef WASMEXT_HOST_P1
    for (int c = 1; c < 256; c++)
        if (fusedwasi_p1_errno(c) == (uint32_t)wasi) return c;
#else
    (void)wasi;
#endif
    return EIO;
}

/* the status of a stream after a hook: a hook that failed on its own traps, a closed pipe (EPIPE of WASI, 64) closes the stream, the rest fails it */
static inline int wasmext_host_status_(fusedwasi_p2_state *s, fusedwasi_p2_stream *st, int rc) {
    if (rc == 0) return FUSEDWASI_P2_STREAM_OK;
    if (rc == WASMEXT_HOOK_TRAP) wasmext_host_trap_(s, "a hook of the host failed");
    if (rc == 64) return FUSEDWASI_P2_STREAM_CLOSED;
    st->failure = "i/o error";
    st->failure_errno = wasmext_host_c_errno_(rc);
    return FUSEDWASI_P2_STREAM_FAILED;
}
static int wasmext_host_read_(fusedwasi_p2_state *s, fusedwasi_p2_stream *st, uint8_t *buf, uint64_t len, uint64_t *got) {
    wasmext_host *h = wasmext_host_of_(s);
    size_t n = 0;
    int rc;
    *got = 0;
    if (len == 0) return FUSEDWASI_P2_STREAM_OK;
    rc = h->stdin_read(h->user, buf, (size_t)(len < 65536u ? len : 65536u), &n);
    if (rc != 0) return wasmext_host_status_(s, st, rc);
    *got = n;
    return n == 0 ? FUSEDWASI_P2_STREAM_CLOSED : FUSEDWASI_P2_STREAM_OK;  /* nothing at all is the end of the input */
}
static int wasmext_host_write_(fusedwasi_p2_state *s, fusedwasi_p2_stream *st, const uint8_t *data, uint64_t len) {
    wasmext_host *h = wasmext_host_of_(s);
    if (len == 0) return FUSEDWASI_P2_STREAM_OK;
    return wasmext_host_status_(s, st, h->stdout_write(h->user, (int)(st - h->streams), data, (size_t)len));
}
static uint64_t wasmext_host_check_write_(fusedwasi_p2_state *s, fusedwasi_p2_stream *st, int *status) {
    (void)s; (void)st;
    *status = FUSEDWASI_P2_STREAM_OK;
    return 65536u;
}
static int wasmext_host_flush_(fusedwasi_p2_state *s, fusedwasi_p2_stream *st) { (void)s; (void)st; return FUSEDWASI_P2_STREAM_OK; }
static int wasmext_host_ready_(fusedwasi_p2_state *s, fusedwasi_p2_stream *st) { (void)s; (void)st; return 1; }
/* a hook that failed on its own traps; another status is a clock that cannot be read, a source that failed: the caller of the state decides what that is */
static int wasmext_host_clock_(fusedwasi_p2_state *s, uint32_t id, uint64_t *ns) {
    wasmext_host *h = wasmext_host_of_(s);
    int rc = h->clock(h->user, id, ns);
    if (rc == WASMEXT_HOOK_TRAP) wasmext_host_trap_(s, "the clock of the host failed");
    return rc != 0;
}
static int wasmext_host_random_(fusedwasi_p2_state *s, uint8_t *buf, size_t n) {
    wasmext_host *h = wasmext_host_of_(s);
    int rc = h->random(h->user, buf, n);
    if (rc == WASMEXT_HOOK_TRAP) wasmext_host_trap_(s, "the source of random bytes of the host failed");
    return rc != 0;
}
static int wasmext_host_sleep_(fusedwasi_p2_state *s, uint64_t ns) {
    wasmext_host *h = wasmext_host_of_(s);
    int rc = h->sleep(h->user, ns);
    if (rc == WASMEXT_HOOK_TRAP) wasmext_host_trap_(s, "the sleep of the host failed");
    return rc != 0;
}
static void wasmext_host_wait_(fusedwasi_p2_guest *g) {
    wasmext_host *h = wasmext_host_of_(g->state);
    if (h->sleep(h->user, 1000000u) != 0) g->trap(g, "the sleep of the host failed");
}
static int wasmext_host_sockets_(fusedwasi_p2_state *s, const char *ip, uint16_t port, int use) {
    wasmext_host *h = wasmext_host_of_(s);
    int rc;
    if (use >= FUSEDWASI_P2_USE_UDP_BIND ? h->no_udp : h->no_tcp) return 0;
    if (h->sockets_all) return 1;
    if (h->sockets == NULL) return 0;
    rc = h->sockets(h->user, ip, port, (uint32_t)use);
    if (rc < 0) wasmext_host_trap_(s, "a policy of the network failed");
    return rc;
}
static int wasmext_host_http_(fusedwasi_p2_state *s, const char *scheme, const char *authority) {
    wasmext_host *h = wasmext_host_of_(s);
    int rc;
    if (h->http_all) return 1;
    if (h->http == NULL) return 0;
    rc = h->http(h->user, scheme, authority);
    if (rc < 0) wasmext_host_trap_(s, "a policy of the network failed");
    return rc;
}

static inline void wasmext_host_release_copies_(wasmext_host *h) {
    for (size_t i = 0; i < h->nargs_v; i++) free(h->args_v[i]);
    for (size_t i = 0; i < h->nenv_v; i++) { free(h->env_n[i]); free(h->env_v[i]); }
    for (size_t i = 0; i < h->npreopens; i++) { free((void *)h->preopens[i].path); free((void *)h->preopens[i].name); }
    free(h->args_v); free(h->env_n); free(h->env_v); free(h->preopens);
}

/* Lets the host go: the state of fusedwasi (the descriptors of 0.1 and the handles of 0.2 are in its table) and what the state points into. Fits `wasmext_store_own`. */
static inline void wasmext_host_free(void *host) {
    wasmext_host *h = (wasmext_host *)host;
    if (h == NULL) return;
    fusedwasi_p2_free(&h->wasi);
    wasmext_host_release_copies_(h);
    free(h);
}

/* Makes the host from `config` (it may be NULL). `program` is the name of the module: the first argument when the configuration gives none. NULL with `*error` (an errno) when it
   cannot be made: ENOMEM, EINVAL for an array that is NULL with a count, a NULL item, an environment item with no '=' or no name, or a directory that is not `host::guest` with both parts, or the errno of a directory of WASI 0.1 that cannot be opened. */
static inline wasmext_host *wasmext_host_new(const wasmext_config *config, const char *program, int *error) {
    int ignored;
    wasmext_host *h;
    fusedwasi_p2_state *s;
    size_t nargs, nenv, ndirs;
    if (error == NULL) error = &ignored;
    nargs = config != NULL && config->args != NULL ? config->nargs : 1;
    nenv = config != NULL ? config->nenv : 0;
    ndirs = config != NULL ? config->ndirs : 0;
    if (config != NULL && ((nenv != 0 && config->env == NULL) || (ndirs != 0 && config->dirs == NULL))) { *error = EINVAL; return NULL; }
    for (size_t i = 0; config != NULL && i < nenv; i++) {
        const char *eq = config->env[i] != NULL ? strchr(config->env[i], '=') : NULL;
        if (eq == NULL || eq == config->env[i]) { *error = EINVAL; return NULL; }  /* NULL, no '=', or no NAME */
    }
    for (size_t i = 0; config != NULL && i < ndirs; i++) {
        const char *item = config->dirs[i], *sep = item != NULL ? strstr(item, "::") : NULL;
        if (sep == NULL || sep == item || sep[2] == '\0') { *error = EINVAL; return NULL; }  /* NULL, or not host::guest with both parts */
    }
    for (size_t i = 0; config != NULL && config->args != NULL && i < nargs; i++) if (config->args[i] == NULL) { *error = EINVAL; return NULL; }
    h = (wasmext_host *)calloc(1, sizeof *h);
    if (h == NULL) { *error = ENOMEM; return NULL; }
    fusedwasi_p2_init(&h->wasi);
    s = &h->wasi;
    s->user = h;
    if (config != NULL) {
        h->stdin_read = config->stdin_read;
        h->stdout_write = config->stdout_write;
        h->clock = config->clock;
        h->random = config->random;
        h->sleep = config->sleep;
        h->user = config->user;
        h->sockets = config->sockets;
        h->sockets_all = config->sockets_all;
        h->no_tcp = config->no_tcp;
        h->no_udp = config->no_udp;
        h->http = config->http;
        h->http_all = config->http_all;
        s->allow_ip_name_lookup = config->dns;
    }
    h->args_v = (char **)calloc(nargs ? nargs : 1, sizeof(char *));
    h->env_n = (char **)calloc(nenv ? nenv : 1, sizeof(char *));
    h->env_v = (char **)calloc(nenv ? nenv : 1, sizeof(char *));
    h->preopens = (struct fusedwasi_p2_preopen *)calloc(ndirs ? ndirs : 1, sizeof *h->preopens);
    if (h->args_v == NULL || h->env_n == NULL || h->env_v == NULL || h->preopens == NULL) goto nomem;
    for (size_t i = 0; i < nargs; i++) {
        h->args_v[i] = wasmext_host_dup_(config != NULL && config->args != NULL ? config->args[i] : (program != NULL ? program : "wasm"));
        if (h->args_v[i] == NULL) goto nomem;
        h->nargs_v = i + 1;
    }
    for (size_t i = 0; i < nenv; i++) {
        const char *item = config->env[i], *eq = strchr(item, '=');  /* checked above: there is one, and a name before it */
        size_t name_len = (size_t)(eq - item);
        h->env_n[i] = (char *)malloc(name_len + 1);
        if (h->env_n[i] == NULL) goto nomem;
        memcpy(h->env_n[i], item, name_len);
        h->env_n[i][name_len] = '\0';
        h->env_v[i] = wasmext_host_dup_(eq + 1);
        if (h->env_v[i] == NULL) goto nomem;
        h->nenv_v = i + 1;
    }
    for (size_t i = 0; i < ndirs; i++) {
        const char *item = config->dirs[i], *sep = strstr(item, "::");  /* checked above: both parts are there */
        size_t host_len = (size_t)(sep - item);
        char *path = (char *)malloc(host_len + 1);
        if (path == NULL) goto nomem;
        memcpy(path, item, host_len);
        path[host_len] = '\0';
        h->preopens[i].path = path;
        h->preopens[i].name = wasmext_host_dup_(sep + 2);
        h->preopens[i].writable = !(config->dirs_readonly != NULL && config->dirs_readonly[i] != 0);
        h->npreopens = i + 1;
        if (h->preopens[i].name == NULL) goto nomem;
    }
    s->args = (const char *const *)h->args_v;
    s->arg_count = (uint32_t)nargs;
    s->env_names = (const char *const *)h->env_n;
    s->env_values = (const char *const *)h->env_v;
    s->env_count = (uint32_t)nenv;
    s->preopens = h->preopens;
    s->preopen_count = (uint32_t)ndirs;
    for (int i = 0; i < 3; i++) {
        fusedwasi_p2_stream *st = &h->streams[i];
        if (i == 0 ? h->stdin_read == NULL : h->stdout_write == NULL) continue;  /* the descriptors of the process */
        st->failure_network_code = -1;
        st->ready = wasmext_host_ready_;
        if (i == 0) {
            st->read = wasmext_host_read_;
        } else {
            st->check_write = wasmext_host_check_write_;
            st->write = wasmext_host_write_;
            st->flush = wasmext_host_flush_;
        }
        s->std[i] = st;
    }
    if (h->clock != NULL) s->clock = wasmext_host_clock_;
    if (h->random != NULL) s->random_bytes = s->insecure_random_bytes = wasmext_host_random_;
    if (h->sleep != NULL) {
        h->wait = wasmext_host_wait_;
        s->sleep = wasmext_host_sleep_;
    }
    s->socket_addr_check = wasmext_host_sockets_;
    s->http_check = wasmext_host_http_;
#ifdef WASMEXT_HOST_P1
    {   /* the descriptors of 0.1 are made now, so that a directory that cannot be opened is told here */
        size_t bad = (size_t)-1;
        int err = 0;
        if (fusedwasi_p1_open_descriptors(s, &err, &bad) != 0) {
            *error = err;
            wasmext_host_free(h);
            return NULL;
        }
    }
#endif
    *error = 0;
    return h;
nomem:
    *error = ENOMEM;
    wasmext_host_free(h);
    return NULL;
}

#endif
