/* WASI 0.2 for a host that is Python: the configuration `wasi=` (a dict) turned into the state of fusedwasi (`fusedwasi_p2_state`, p2/wasi_p2_core.h), the standard
   streams as Python objects, the functions `clock` and `random`, and the sleep that lets a signal through. It reads `wasi=` with the code of WASI 0.1 (wasi_python.h:
   the same keys, the same errors), so a user writes the same for both; what 0.1 builds into its own configuration is built here into the state of 0.2.

   The glue of the module (no Python in it) makes the state and gives the callbacks that need the module (`trap`, `realloc`); this file adds the ones that need Python.
   The state's `user` is a `wasmext_wasi2_py`, whose first member is the pointer to the instance of the glue (`core`), which the callbacks of the glue read.

   A hook that fails with an exception of Python keeps it where Python keeps it, in the state of the thread, and traps through `s->trap`, which does not return: the
   call into the module that was running comes back to Python with that exception. An OSError of a stream is an error of the stream, as an operating system has it. */
#ifndef WASMEXT_WASI2_PYTHON_H
#define WASMEXT_WASI2_PYTHON_H

#include "wasi_python.h"

#define WASI2_READ_CAP 65536u

typedef struct wasmext_wasi2_py {
    void *core;                    /* the instance of the glue: first, the callbacks of the glue read it through `s->user` */
    wasmext_wasi_py py;            /* what 0.1 keeps for Python: the streams, the functions clock and random, the exceptions */
    wasi_py_options keep;          /* the buffers that the state points into (arguments, environment, directories) */
    const char **args_v;
    const char **env_n, **env_v;
    struct fusedwasi_p2_preopen *preopens;
    fusedwasi_p2_stream streams[3];
    char *program;                 /* argv[0] when the configuration has no arguments */
    PyObject *sockets_fn;          /* sockets=callable(ip, port, use), or NULL */
    PyObject *http_fn;             /* http=callable(scheme, authority), or NULL */
    int sockets_all, http_all;     /* sockets=True, http=True */
    int tcp, udp;                  /* tcp=, udp=: 1 (the default) lets the policy of sockets decide, 0 refuses the use */
} wasmext_wasi2_py;

#define WASI2_PY(s) ((wasmext_wasi2_py *)(s)->user)

/* ---- the standard streams ---------------------------------------------------------------------------------------------- */

/* the status of a stream after an exception of Python: an exception that is not an OSError traps (it stays set); a closed pipe closes the stream; the rest fails */
static inline int wasi2_stream_status(fusedwasi_p2_state *s, fusedwasi_p2_stream *st) {
    int code = wasi_python_errno();
    if (code < 0) s->trap(s, "an exception of Python in a stream of the host");
    if (code == EPIPE) return FUSEDWASI_P2_STREAM_CLOSED;
    st->failure = "i/o error";
    st->failure_errno = code;
    return FUSEDWASI_P2_STREAM_FAILED;
}

static int wasi2_stream_write(fusedwasi_p2_state *s, fusedwasi_p2_stream *st, const uint8_t *data, uint64_t len) {
    wasmext_wasi2_py *w = WASI2_PY(s);
    if (len == 0) return FUSEDWASI_P2_STREAM_OK;
    if (wasi_write_bytes(&w->py, (uint32_t)(st - w->streams), (const char *)data, (Py_ssize_t)len) < 0) return wasi2_stream_status(s, st);
    return FUSEDWASI_P2_STREAM_OK;
}

static uint64_t wasi2_stream_check_write(fusedwasi_p2_state *s, fusedwasi_p2_stream *st, int *status) {
    (void)s;
    (void)st;
    *status = FUSEDWASI_P2_STREAM_OK;
    return WASI2_READ_CAP;
}

static int wasi2_stream_flush(fusedwasi_p2_state *s, fusedwasi_p2_stream *st) {
    (void)s;
    (void)st;
    return FUSEDWASI_P2_STREAM_OK;
}

static int wasi2_stream_ready(fusedwasi_p2_state *s, fusedwasi_p2_stream *st) {
    (void)s;
    (void)st;
    return 1;
}

static int wasi2_stream_read(fusedwasi_p2_state *s, fusedwasi_p2_stream *st, uint8_t *buf, uint64_t len, uint64_t *got) {
    wasmext_wasi2_py *w = WASI2_PY(s);
    *got = 0;
    if (len == 0) return FUSEDWASI_P2_STREAM_OK;
    PyObject *bytes = wasi_read_bytes(&w->py, (Py_ssize_t)(len < WASI2_READ_CAP ? len : WASI2_READ_CAP));
    if (bytes == NULL) return wasi2_stream_status(s, st);
    char *data;
    Py_ssize_t n;
    if (PyBytes_AsStringAndSize(bytes, &data, &n) < 0 || (uint64_t)n > len) {
        Py_DECREF(bytes);
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "stdin gave more bytes than were asked for");
        return wasi2_stream_status(s, st);
    }
    memcpy(buf, data, (size_t)n);
    *got = (uint64_t)n;
    Py_DECREF(bytes);
    return n == 0 ? FUSEDWASI_P2_STREAM_CLOSED : FUSEDWASI_P2_STREAM_OK;  /* nothing at all is the end of the input */
}

/* ---- clocks, random bytes, waiting ------------------------------------------------------------------------------------------ */

/* a Python exception that is not an OSError traps (it stays set); an OSError is a clock that cannot be read, a source that failed: the caller of the state decides what that is */
static int wasi2_clock(fusedwasi_p2_state *s, uint32_t id, uint64_t *ns) {
    int rc = wasi_py_clock(&WASI2_PY(s)->py, id, ns);
    if (rc == FUSEDWASI_P1_HOOK_TRAP) s->trap(s, "the function 'clock' of the host failed");
    return rc != 0;
}

static int wasi2_random_bytes(fusedwasi_p2_state *s, uint8_t *buf, size_t n) {
    int rc = wasi_py_random(&WASI2_PY(s)->py, buf, n);
    if (rc == FUSEDWASI_P1_HOOK_TRAP) s->trap(s, "the function 'random' of the host failed");
    return rc != 0;
}

/* waits `ns` nanoseconds on the monotonic clock without holding the interpreter, in slices so that a signal (Ctrl+C) is seen */
static int wasi2_sleep(fusedwasi_p2_state *s, uint64_t ns) {
    uint64_t start, now;
    if (s->clock(s, 1, &start) != 0) return -1;
    for (;;) {
        if (s->clock(s, 1, &now) != 0) return -1;
        uint64_t spent = now - start;
        if (spent >= ns) return 0;
        uint64_t left = ns - spent, slice = left < 100000000ull ? left : 100000000ull;
        Py_BEGIN_ALLOW_THREADS
#ifdef _WIN32
        Sleep((DWORD)((slice + 999999u) / 1000000u));
#else
        {
            struct timespec t;
            t.tv_sec = (time_t)(slice / 1000000000ull);
            t.tv_nsec = (long)(slice % 1000000000ull);
            nanosleep(&t, NULL);
        }
#endif
        Py_END_ALLOW_THREADS
        if (PyErr_CheckSignals() < 0) s->trap(s, "interrupted");
    }
}

/* what a blocking call does between two looks at a pollable: a millisecond without the interpreter, so that another thread runs and a signal (Ctrl+C) is seen */
static void wasi2_wait(fusedwasi_p2_state *s) {
    Py_BEGIN_ALLOW_THREADS
#ifdef _WIN32
    Sleep(1);
#else
    {
        struct timespec t = {0, 1000000};
        nanosleep(&t, NULL);
    }
#endif
    Py_END_ALLOW_THREADS
    if (PyErr_CheckSignals() < 0) s->trap(s, "interrupted");
}

/* ---- the policies of the network (as in Wasmtime: callables or True, nothing is allowed by default) ------------------------------ */

static const char *const wasi2_uses[] = {"tcp-bind", "tcp-connect", "udp-bind", "udp-connect", "udp-outgoing"};

/* the answer of a policy callable: true allows; an exception of Python traps (it stays set) */
static int wasi2_policy(fusedwasi_p2_state *s, PyObject *res) {
    if (res == NULL) s->trap(s, "an exception of Python in a policy of the network");
    int ok = PyObject_IsTrue(res);
    Py_DECREF(res);
    if (ok < 0) s->trap(s, "an exception of Python in a policy of the network");
    return ok;
}

static int wasi2_socket_addr_check(fusedwasi_p2_state *s, const char *ip, uint16_t port, int use) {
    wasmext_wasi2_py *w = WASI2_PY(s);
    int udp = use >= FUSEDWASI_P2_USE_UDP_BIND;
    if (udp ? !w->udp : !w->tcp) return 0;
    if (w->sockets_all) return 1;
    if (w->sockets_fn == NULL) return 0;
    return wasi2_policy(s, PyObject_CallFunction(w->sockets_fn, "sis", ip, (int)port, wasi2_uses[use]));
}

static int wasi2_http_check(fusedwasi_p2_state *s, const char *scheme, const char *authority) {
    wasmext_wasi2_py *w = WASI2_PY(s);
    if (w->http_all) return 1;
    if (w->http_fn == NULL) return 0;
    return wasi2_policy(s, PyObject_CallFunction(w->http_fn, "ss", scheme, authority));
}

/* one of the keys sockets, dns, http, tcp, udp: 1 when `name` is one of them (and it is applied), 0 when not, -1 with an exception set */
static int wasi2_network_option(fusedwasi_p2_state *s, wasmext_wasi2_py *w, const char *name, PyObject *value) {
    PyObject **fn = NULL;
    int *all = NULL, *flag = NULL;
    if (strcmp(name, "sockets") == 0) fn = &w->sockets_fn, all = &w->sockets_all;
    else if (strcmp(name, "http") == 0) fn = &w->http_fn, all = &w->http_all;
    else if (strcmp(name, "dns") == 0) flag = &s->allow_ip_name_lookup;
    else if (strcmp(name, "tcp") == 0) flag = &w->tcp;
    else if (strcmp(name, "udp") == 0) flag = &w->udp;
    else return 0;
    if (value == Py_None) value = Py_False;
    if (flag != NULL || PyBool_Check(value)) {
        if (!PyBool_Check(value)) {
            PyErr_Format(PyExc_TypeError, "wasi: '%s' must be a bool", name);
            return -1;
        }
        int on = value == Py_True;
        if (flag != NULL) *flag = on;
        else *all = on;
        return 1;
    }
    if (!PyCallable_Check(value)) {
        PyErr_Format(PyExc_TypeError, "wasi: '%s' must be True, False, None or a callable", name);
        return -1;
    }
    Py_INCREF(value);
    Py_XDECREF(*fn);
    *fn = value;
    return 1;
}

/* ---- the state ------------------------------------------------------------------------------------------------------------ */

static inline int wasmext_wasi2_traverse(wasmext_wasi2_py *w, visitproc visit, void *arg) {
    if (w == NULL) return 0;
    wasmext_wasi_py *p = &w->py;
    Py_VISIT(w->sockets_fn);
    Py_VISIT(w->http_fn);
    for (int i = 0; i < 3; i++) Py_VISIT(p->stream[i]);
    Py_VISIT(p->exit_type);
    Py_VISIT(p->signal_type);
    Py_VISIT(p->ended_type);
    Py_VISIT(p->time_module);
    Py_VISIT(p->os_module);
    Py_VISIT(p->text_base);
    Py_VISIT(p->clock_fn);
    Py_VISIT(p->random_fn);
    for (int i = 0; i < 3; i++) Py_VISIT(p->decoder[i]);
    Py_VISIT(p->stdin_rest);
    return 0;
}

static inline void wasmext_wasi2_clear(wasmext_wasi2_py *w) {
    if (w == NULL) return;
    Py_CLEAR(w->sockets_fn);
    Py_CLEAR(w->http_fn);
    wasi_py_clear(&w->py);
}

static inline void wasmext_wasi2_free(wasmext_wasi2_py *w) {
    if (w == NULL) return;
    Py_XDECREF(w->sockets_fn);
    Py_XDECREF(w->http_fn);
    wasi_py_clear(&w->py);
    wasi_py_options_free(&w->keep);
    free(w->args_v);
    free(w->env_n);
    free(w->env_v);
    free(w->preopens);
    free(w->program);
    free(w);
}

/* The Python side of the state `s` (already made by `fusedwasi_p2_init` in the glue): `config` is None or a dict with the keys args, env, stdin, stdout, stderr,
   clock, random, preopens, readonly (those of WASI 0.1); the exceptions are those that the end of the program raises; `program` is argv[0] when the config
   has no args. Returns the Python side (to free with `wasmext_wasi2_free`), or NULL with an exception set. */
static inline wasmext_wasi2_py *wasmext_wasi2_new(fusedwasi_p2_state *s, void *core, PyObject *config, PyObject *exit_type, PyObject *signal_type,
                                                PyObject *ended_type, const char *program) {
    wasmext_wasi2_py *w = (wasmext_wasi2_py *)calloc(1, sizeof(wasmext_wasi2_py));
    if (w == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    w->core = core;
    w->tcp = w->udp = 1;
    wasmext_wasi_py *p = &w->py;
    Py_INCREF(exit_type);
    p->exit_type = exit_type;
    Py_INCREF(signal_type);
    p->signal_type = signal_type;
    Py_INCREF(ended_type);
    p->ended_type = ended_type;
    wasi_py_options *o = &w->keep;
    if (config == Py_None) config = NULL;
    else if (!PyDict_Check(config)) {
        PyErr_SetString(PyExc_TypeError, "wasi must be a dict (args, env, stdin, stdout, stderr)");
        goto fail;
    }
    PyObject *key, *value;
    Py_ssize_t pos = 0;
    while (config != NULL && PyDict_Next(config, &pos, &key, &value)) {
        PyObject *encoded = PyUnicode_Check(key) ? PyUnicode_AsUTF8String(key) : NULL;
        if (encoded == NULL) {
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_TypeError, "the keys of wasi must be strings");
            goto fail;
        }
        int rc = wasi2_network_option(s, w, PyBytes_AsString(encoded), value);
        if (rc == 0) rc = wasi_apply_option(p, o, PyBytes_AsString(encoded), value);
        else if (rc > 0) rc = 0;
        Py_DECREF(encoded);
        if (rc < 0) goto fail;
    }
    if (wasi_setup_preopens(p, o) < 0) goto fail;

    /* arguments: a pointer to each string of the buffer; the name of the program when there are none */
    if (o->args == NULL) {
        w->program = (char *)malloc(strlen(program) + 1);
        if (w->program != NULL) memcpy(w->program, program, strlen(program) + 1);
        w->args_v = (const char **)calloc(1, sizeof(char *));
        if (w->program == NULL || w->args_v == NULL) goto nomem;
        w->args_v[0] = w->program;
        s->arg_count = 1;
    } else {
        w->args_v = (const char **)calloc(o->argc ? o->argc : 1, sizeof(char *));
        if (w->args_v == NULL) goto nomem;
        const char *at = o->args;
        for (uint32_t i = 0; i < o->argc; i++) {
            w->args_v[i] = at;
            at += strlen(at) + 1;
        }
        s->arg_count = o->argc;
    }
    s->args = w->args_v;
    /* environment: "NAME=value" cut at the first '=' in the buffer we own */
    w->env_n = (const char **)calloc(o->envc ? o->envc : 1, sizeof(char *));
    w->env_v = (const char **)calloc(o->envc ? o->envc : 1, sizeof(char *));
    if (w->env_n == NULL || w->env_v == NULL) goto nomem;
    {
        char *at = o->env;
        for (uint32_t i = 0; i < o->envc; i++) {
            size_t len = strlen(at);
            char *eq = (char *)memchr(at, '=', len);
            w->env_n[i] = at;
            if (eq != NULL) {
                *eq = '\0';
                w->env_v[i] = eq + 1;
            } else {
                w->env_v[i] = at + len;
            }
            at += len + 1;
        }
    }
    s->env_names = w->env_n;
    s->env_values = w->env_v;
    s->env_count = o->envc;
    /* directories */
    w->preopens = (struct fusedwasi_p2_preopen *)calloc(o->nitems ? o->nitems : 1, sizeof(struct fusedwasi_p2_preopen));
    if (w->preopens == NULL) goto nomem;
    for (size_t i = 0; i < o->nitems; i++) {
        w->preopens[i].path = o->items[i].host;
        w->preopens[i].name = o->items[i].name;
        w->preopens[i].writable = !o->items[i].readonly;
    }
    s->preopens = w->preopens;
    s->preopen_count = (uint32_t)o->nitems;
    /* the three streams are Python objects (None, or the absent key, are decided by the code of 0.1: nothing, or sys.stdin / sys.stdout / sys.stderr) */
    for (int i = 0; i < 3; i++) {
        fusedwasi_p2_stream *st = &w->streams[i];
        st->failure_network_code = -1;
        st->ctx = w;
        st->ready = wasi2_stream_ready;
        if (i == 0) {
            st->read = wasi2_stream_read;
        } else {
            st->check_write = wasi2_stream_check_write;
            st->write = wasi2_stream_write;
            st->flush = wasi2_stream_flush;
        }
        s->std[i] = st;
    }
    if (p->clock_fn != NULL) s->clock = wasi2_clock;
    if (p->random_fn != NULL) s->random_bytes = s->insecure_random_bytes = wasi2_random_bytes;
    s->sleep = wasi2_sleep;
    s->wait = wasi2_wait;
    s->socket_addr_check = wasi2_socket_addr_check;
    s->http_check = wasi2_http_check;
    s->user = w;
    return w;
nomem:
    PyErr_NoMemory();
fail:
    wasmext_wasi2_free(w);
    return NULL;
}

/* The state of WASI 0.1 over the state `s` of 0.2 that `w` is the Python side of: the same arguments, environment, clocks, random bytes and directories, and the standard streams
   of 0.1 (its hooks) over the same Python objects. NULL with an exception set. Free it with `fusedwasi_p1_destroy` before the state `s`. */
static inline fusedwasi_p1_state *wasmext_wasi_over(wasmext_wasi2_py *w, fusedwasi_p2_state *s) {
    fusedwasi_p1_config cfg;
    memset(&cfg, 0, sizeof cfg);
    cfg.preopens = w->keep.items;
    cfg.npreopens = w->keep.nitems;
    cfg.hooks.end = wasi_py_end;
    cfg.user = &w->py;
    int err = 0;
    size_t bad = (size_t)-1;
    fusedwasi_p1_state *p1 = fusedwasi_p1_create(&cfg, s, &err, &bad);
    if (p1 == NULL) {
        errno = err;
        if (bad != (size_t)-1) PyErr_SetFromErrnoWithFilename(PyExc_OSError, w->keep.items[bad].host);
        else PyErr_NoMemory();
    }
    return p1;
}

/* the program called wasi:cli/exit: WasiExit(code) is raised in the call */
static inline void wasmext_wasi2_raise_exit(wasmext_wasi2_py *w, uint32_t code) { wasi_py_end(&w->py, FUSEDWASI_P1_END_EXIT, code); }

/* the call into an instance that has ended: the exception says how */
static inline void wasmext_wasi2_ended(wasmext_wasi2_py *w, uint32_t code) {
    PyErr_Format(w->py.ended_type, "the program has ended: exit(%u)", (unsigned)code);
}

#endif
