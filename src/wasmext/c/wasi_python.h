/* WASI 0.1 for a host that is Python: the configuration `wasi=` (a dict) turned into the plain-C `fusedwasi_p1_config` of wasi_p1_core.h,
   and the hooks of the core (the standard streams as Python objects, the functions `clock` and `random`, the sleep that lets a signal
   through, the exceptions of proc_exit and proc_raise). The glue of the extension includes it after wasi_p1.h / wasi_p1_unstable.h.

   The Python objects are in `wasmext_wasi_py`, which the core knows only as `user`. A hook that fails with an exception of Python
   keeps it where Python keeps it, in the state of the thread, and answers FUSEDWASI_P1_HOOK_TRAP; an OSError becomes an errno of WASI. */
#ifndef WASMEXT_WASI_PYTHON_H
#define WASMEXT_WASI_PYTHON_H

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "wasi_p1_core.h"

typedef struct {
    PyObject *stream[3];  /* what the caller gave for stdin, stdout, stderr (NULL: sys.stdin, sys.stdout, sys.stderr) */
    Py_ssize_t stdin_pos; /* when stdin is bytes */
    PyObject *exit_type, *signal_type, *ended_type;  /* WasiExit, WasiSignal, and WasiTerminated, the base of both */
    PyObject *time_module;
    PyObject *os_module;
    PyObject *text_base;  /* io.TextIOBase, to tell a text stream from a binary one */
    PyObject *clock_fn, *random_fn;  /* what the caller gave in place of the clocks and of the random bytes */
    PyObject *decoder[3];  /* a text stream with no binary side gets text: the bytes of one character may come in two writes, so each stream has its decoder */
    PyObject *stdin_rest;  /* the bytes of a text stdin that did not fit in the last read */
} wasmext_wasi_py;

#define WASI_PY(w) ((wasmext_wasi_py *)(w)->user)

static inline PyObject *wasi_module_of(PyObject **slot, const char *name) {
    if (*slot == NULL) *slot = PyImport_ImportModule(name);
    return *slot;
}

/* ---- errors of Python ------------------------------------------------------------------------------------------------ */

/* An OSError becomes the errno of WASI that its errno says (and is cleared); anything else is FUSEDWASI_P1_HOOK_TRAP, with the exception still set. */
static inline int wasi_python_status(void) {
    if (PyErr_ExceptionMatches(PyExc_BrokenPipeError)) {
        PyErr_Clear();
        return FUSEDWASI_P1_E_PIPE;
    }
    if (PyErr_ExceptionMatches(PyExc_OSError)) {
        PyObject *type, *value, *traceback;
        PyErr_Fetch(&type, &value, &traceback);
        PyErr_NormalizeException(&type, &value, &traceback);
        uint32_t code = FUSEDWASI_P1_E_IO;
        PyObject *number = value ? PyObject_GetAttrString(value, "errno") : NULL;
        if (number != NULL && PyLong_Check(number)) code = fusedwasi_p1_errno((int)PyLong_AsLong(number));
        PyErr_Clear();
        Py_XDECREF(number);
        Py_XDECREF(type);
        Py_XDECREF(value);
        Py_XDECREF(traceback);
        return (int)code;
    }
    return FUSEDWASI_P1_HOOK_TRAP;
}

static inline uint32_t wasi_python_error(int *trapped) { return fusedwasi_p1_hook_status(wasi_python_status(), trapped); }

/* ---- the standard streams ---------------------------------------------------------------------------------------------- */

/* is `stream` a text stream (an io.TextIOBase): 1, 0, or -1 with an exception */
static inline int wasi_is_text(wasmext_wasi_py *p, PyObject *stream) {
    if (p->text_base == NULL) {
        PyObject *io = PyImport_ImportModule("io");
        if (io == NULL) return -1;
        p->text_base = PyObject_GetAttrString(io, "TextIOBase");
        Py_DECREF(io);
        if (p->text_base == NULL) return -1;
    }
    return PyObject_IsInstance(stream, p->text_base);
}

/* a stream that has been closed: the program gets EBADF, as for a descriptor that is closed (not a trap for the ValueError that the write would raise) */
static inline int wasi_stream_closed(PyObject *stream) {
    PyObject *closed = PyObject_GetAttrString(stream, "closed");
    if (closed == NULL) {
        PyErr_Clear();
        return 0;
    }
    int yes = PyObject_IsTrue(closed);
    Py_DECREF(closed);
    if (yes < 0) PyErr_Clear();
    if (yes > 0) {
        errno = EBADF;
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }
    return 0;
}

/* all of `data` to the `write` of an object, which may take less than it is given (a raw stream does): 0, or -1 with an exception */
static inline int wasi_write_all(PyObject *writer, const char *data, Py_ssize_t size) {
    Py_ssize_t done = 0;
    while (done < size) {
        PyObject *bytes = PyBytes_FromStringAndSize(data + done, size - done);
        if (bytes == NULL) return -1;
        PyObject *r = PyObject_CallMethod(writer, "write", "O", bytes);
        Py_DECREF(bytes);
        if (r == NULL) return -1;
        Py_ssize_t n = size - done;  /* a write that gives no number (None) is taken as all written, as io.BufferedIOBase does */
        if (PyLong_Check(r)) n = PyLong_AsSsize_t(r);
        Py_DECREF(r);
        if (n == -1 && PyErr_Occurred()) return -1;
        if (n <= 0) {
            errno = EIO;
            PyErr_SetFromErrno(PyExc_OSError);
            return -1;
        }
        done += n > size - done ? size - done : n;
    }
    return 0;
}

/* bytes to a text stream (sys.stdout, or any text stream the caller gave): through its binary side after flushing its text layer, or
   as text (decoded as the bytes come, a character in two writes is one character) where it has none */
static inline int wasi_write_text_stream(wasmext_wasi_py *p, uint32_t fd, PyObject *stream, const char *data, Py_ssize_t size) {
    PyObject *r;
    if (PyObject_HasAttrString(stream, "flush")) {  /* a stand-in for sys.stdout may have only write */
        PyObject *flushed = PyObject_CallMethod(stream, "flush", NULL);
        if (flushed == NULL) return -1;
        Py_DECREF(flushed);
    }
    PyObject *buffer = PyObject_GetAttrString(stream, "buffer");
    if (buffer == NULL) {  /* a text stream with no binary side: it gets the text */
        PyErr_Clear();
        if (p->decoder[fd] == NULL) {
            PyObject *codecs = PyImport_ImportModule("codecs");
            PyObject *factory = codecs ? PyObject_CallMethod(codecs, "getincrementaldecoder", "s", "utf-8") : NULL;
            p->decoder[fd] = factory ? PyObject_CallFunction(factory, "s", "replace") : NULL;
            Py_XDECREF(factory);
            Py_XDECREF(codecs);
            if (p->decoder[fd] == NULL) return -1;
        }
        PyObject *bytes = PyBytes_FromStringAndSize(data, size);
        PyObject *text = bytes ? PyObject_CallMethod(p->decoder[fd], "decode", "O", bytes) : NULL;
        Py_XDECREF(bytes);
        if (text == NULL) return -1;
        r = PyObject_CallMethod(stream, "write", "O", text);
        Py_DECREF(text);
        Py_XDECREF(r);
        return r ? 0 : -1;
    }
    int rc = wasi_write_all(buffer, data, size);
    Py_DECREF(buffer);
    return rc;
}

/* the stream the caller gave (None: thrown away), or sys.stdout / sys.stderr as they are now */
static inline int wasi_write_bytes(wasmext_wasi_py *p, uint32_t fd, const char *data, Py_ssize_t size) {
    PyObject *target = p->stream[fd], *r;
    if (target == Py_None) return 0;
    if (target == NULL) {
        target = PySys_GetObject(fd == 1 ? "stdout" : "stderr");  /* borrowed */
        if (target == NULL || target == Py_None) return 0;
        if (wasi_stream_closed(target) < 0) return -1;
        return wasi_write_text_stream(p, fd, target, data, size);
    }
    int text = wasi_is_text(p, target);
    if (text < 0) return -1;
    if (wasi_stream_closed(target) < 0) return -1;
    if (text) return wasi_write_text_stream(p, fd, target, data, size);
    if (PyObject_HasAttrString(target, "write")) return wasi_write_all(target, data, size);
    PyObject *bytes = PyBytes_FromStringAndSize(data, size);  /* a function: it is called once with the bytes */
    if (bytes == NULL) return -1;
    r = PyObject_CallFunctionObjArgs(target, bytes, NULL);
    Py_DECREF(bytes);
    Py_XDECREF(r);
    return r ? 0 : -1;
}

/* up to `size` bytes of stdin, a new bytes object (empty at the end), or NULL with an exception */
static inline PyObject *wasi_read_bytes(wasmext_wasi_py *p, Py_ssize_t size) {
    PyObject *given = p->stream[0];
    if (given != NULL && (PyBytes_Check(given) || PyByteArray_Check(given))) {
        Py_ssize_t have = PyObject_Size(given);
        if (have < 0) return NULL;
        Py_ssize_t n = have - p->stdin_pos < size ? have - p->stdin_pos : size;
        PyObject *slice = PySequence_GetSlice(given, p->stdin_pos, p->stdin_pos + n);
        if (slice != NULL) p->stdin_pos += n;
        return slice;
    }
    PyObject *source = given;
    int text = 1;
    if (source == NULL) {
        source = PySys_GetObject("stdin");  /* borrowed */
        if (source == NULL || source == Py_None) return PyBytes_FromStringAndSize("", 0);
    } else if ((text = wasi_is_text(p, source)) < 0) {
        return NULL;
    }
    if (!text) return PyObject_CallMethod(source, "read", "n", size);
    PyObject *buffer = PyObject_GetAttrString(source, "buffer");
    if (buffer == NULL) {  /* a text stream with no binary side: its text, as UTF-8; what does not fit in this read waits for the next */
        PyErr_Clear();
        if (p->stdin_rest == NULL || PyBytes_Size(p->stdin_rest) == 0) {
            Py_CLEAR(p->stdin_rest);
            PyObject *chars = PyObject_CallMethod(source, "read", "n", size);
            p->stdin_rest = chars ? PyUnicode_AsUTF8String(chars) : NULL;
            Py_XDECREF(chars);
            if (p->stdin_rest == NULL) return NULL;
        }
        Py_ssize_t have = PyBytes_Size(p->stdin_rest), n = have < size ? have : size;
        PyObject *head = PyBytes_FromStringAndSize(PyBytes_AsString(p->stdin_rest), n);
        PyObject *tail = head ? PyBytes_FromStringAndSize(PyBytes_AsString(p->stdin_rest) + n, have - n) : NULL;
        if (tail == NULL) {
            Py_XDECREF(head);
            return NULL;
        }
        { PyObject *old_ = p->stdin_rest; p->stdin_rest = tail; Py_XDECREF(old_); }
        return head;
    }
    PyObject *bytes = PyObject_HasAttrString(buffer, "read1") ? PyObject_CallMethod(buffer, "read1", "n", size)
                                                              : PyObject_CallMethod(buffer, "read", "n", size);
    Py_DECREF(buffer);
    return bytes;
}

/* ---- the hooks of the core ---------------------------------------------------------------------------------------------- */

static int wasi_py_stdout_write(void *user, int fd, const uint8_t *buf, size_t n) {
    return wasi_write_bytes((wasmext_wasi_py *)user, (uint32_t)fd, (const char *)buf, (Py_ssize_t)n) < 0 ? wasi_python_status() : 0;
}

static int wasi_py_stdin_read(void *user, uint8_t *buf, size_t cap, size_t *got) {
    PyObject *bytes = wasi_read_bytes((wasmext_wasi_py *)user, (Py_ssize_t)cap);
    if (bytes == NULL) return wasi_python_status();
    char *data;
    Py_ssize_t n;
    if (PyBytes_AsStringAndSize(bytes, &data, &n) < 0 || (size_t)n > cap) {
        Py_DECREF(bytes);
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "stdin gave more bytes than were asked for");
        return wasi_python_status();
    }
    memcpy(buf, data, (size_t)n);
    *got = (size_t)n;
    Py_DECREF(bytes);
    return 0;
}

static int wasi_py_clock(void *user, uint32_t id, uint64_t *ns) {
    PyObject *value = PyObject_CallFunction(((wasmext_wasi_py *)user)->clock_fn, "I", id);
    if (value == NULL) return wasi_python_status();
    unsigned long long n = PyLong_AsUnsignedLongLong(value);
    Py_DECREF(value);
    if (n == (unsigned long long)-1 && PyErr_Occurred()) return wasi_python_status();
    *ns = n;
    return 0;
}

static int wasi_py_random(void *user, uint8_t *buf, size_t size) {
    PyObject *bytes = PyObject_CallFunction(((wasmext_wasi_py *)user)->random_fn, "I", (unsigned)size);
    if (bytes == NULL) return wasi_python_status();
    char *data;
    Py_ssize_t len;
    if (PyBytes_AsStringAndSize(bytes, &data, &len) < 0 || (size_t)len != size) {
        if (!PyErr_Occurred()) PyErr_Format(PyExc_ValueError, "wasi: 'random' gave %zd bytes, %u were asked for", len, (unsigned)size);
        Py_DECREF(bytes);
        return wasi_python_status();
    }
    memcpy(buf, data, (size_t)len);
    Py_DECREF(bytes);
    return 0;
}

/* waits `ns` nanoseconds on the monotonic clock without holding the interpreter, in slices so that a signal (Ctrl+C) is seen */
static int wasi_py_sleep(void *user, uint64_t ns) {
    (void)user;
    uint64_t start;
    if (fusedwasi_p1_clock_system(1, &start) != 0) {
        PyErr_SetString(PyExc_OSError, "wasi: the monotonic clock cannot be read");
        return wasi_python_status();
    }
    for (;;) {
        uint64_t now;
        if (fusedwasi_p1_clock_system(1, &now) != 0) return 0;
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
        if (PyErr_CheckSignals() < 0) return FUSEDWASI_P1_HOOK_TRAP;
    }
}

static const char *const wasi_signal_names[31] = {
    "", "SIGHUP", "SIGINT", "SIGQUIT", "SIGILL", "SIGTRAP", "SIGABRT", "SIGBUS", "SIGFPE", "SIGKILL", "SIGUSR1",
    "SIGSEGV", "SIGUSR2", "SIGPIPE", "SIGALRM", "SIGTERM", "SIGCHLD", "SIGCONT", "SIGSTOP", "SIGTSTP", "SIGTTIN",
    "SIGTTOU", "SIGURG", "SIGXCPU", "SIGXFSZ", "SIGVTALRM", "SIGPROF", "SIGWINCH", "SIGPOLL", "SIGPWR", "SIGSYS",
};

/* the program is over by proc_exit (WasiExit, with .code) or by proc_raise (WasiSignal, with .signal and .name): raised in the call */
static void wasi_py_end(void *user, int how, uint32_t value) {
    wasmext_wasi_py *p = (wasmext_wasi_py *)user;
    if (how == FUSEDWASI_P1_END_EXIT) {
        PyObject *exc = PyObject_CallFunction(p->exit_type, "I", value);
        if (exc != NULL) {
            PyObject *number = PyLong_FromUnsignedLong(value);
            if (number == NULL || PyObject_SetAttrString(exc, "code", number) < 0) PyErr_Clear();
            Py_XDECREF(number);
            PyErr_SetObject(p->exit_type, exc);
            Py_DECREF(exc);
        }
    } else {
        PyObject *exc = PyObject_CallFunction(p->signal_type, "s", wasi_signal_names[value]);
        if (exc != NULL) {
            PyObject *number = PyLong_FromUnsignedLong(value), *name = PyUnicode_FromString(wasi_signal_names[value]);
            if (number == NULL || name == NULL || PyObject_SetAttrString(exc, "signal", number) < 0 ||
                PyObject_SetAttrString(exc, "name", name) < 0)
                PyErr_Clear();
            Py_XDECREF(number);
            Py_XDECREF(name);
            PyErr_SetObject(p->signal_type, exc);
            Py_DECREF(exc);
        }
    }
}

/* ---- the configuration `wasi=` ----------------------------------------------------------------------------------------- */

/* what the dict says, before the core copies it */
typedef struct {
    char *args, *env;
    size_t args_size, env_size;
    uint32_t argc, envc;
    PyObject *preopens, *readonly;  /* until the preopens are made */
    fusedwasi_p1_preopen *items;    /* the preopens, made: names and paths are new memory */
    size_t nitems;
} wasi_py_options;

static inline void wasi_py_options_free(wasi_py_options *o) {
    FUSEDWASI_P1_FREE(o->args);
    FUSEDWASI_P1_FREE(o->env);
    for (size_t i = 0; i < o->nitems; i++) {
        FUSEDWASI_P1_FREE((char *)o->items[i].name);
        FUSEDWASI_P1_FREE((char *)o->items[i].host);
    }
    FUSEDWASI_P1_FREE(o->items);
    Py_CLEAR(o->preopens);
    Py_CLEAR(o->readonly);
}

/* the strings of a sequence into one buffer of NUL-ended strings */
static inline int wasi_pack_strings(PyObject *seq, char **out, size_t *size, uint32_t *count) {
    if (PyUnicode_Check(seq) || PyBytes_Check(seq) || PyByteArray_Check(seq)) {  /* a string is a sequence of characters: not the list of arguments */
        PyErr_SetString(PyExc_TypeError, "wasi: args and env are lists of strings (and not one string, or bytes)");
        return -1;
    }
    PyObject *list = PySequence_List(seq);
    if (list == NULL) return -1;
    Py_ssize_t n = PyList_Size(list), total = 0;
    for (Py_ssize_t i = 0; i < n; i++) {
        Py_ssize_t len;
        PyObject *item = PyList_GetItem(list, i);
        const char *text = PyUnicode_Check(item) ? PyUnicode_AsUTF8AndSize(item, &len) : NULL;
        if (text == NULL) {
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_TypeError, "wasi: args and env are strings");
            Py_DECREF(list);
            return -1;
        }
        if ((Py_ssize_t)strlen(text) != len) {  /* each is ended by a NUL in the table of the program: one inside it would make two */
            PyErr_SetString(PyExc_ValueError, "wasi: a string of args or env has a null character in it");
            Py_DECREF(list);
            return -1;
        }
        total += len + 1;
    }
    char *buf = (char *)FUSEDWASI_P1_MALLOC(total > 0 ? (size_t)total : 1);
    if (buf == NULL) {
        Py_DECREF(list);
        PyErr_NoMemory();
        return -1;
    }
    char *p = buf;
    for (Py_ssize_t i = 0; i < n; i++) {
        Py_ssize_t len;
        const char *s = PyUnicode_AsUTF8AndSize(PyList_GetItem(list, i), &len);
        memcpy(p, s, (size_t)len);
        p[len] = '\0';
        p += len + 1;
    }
    Py_DECREF(list);
    *out = buf;
    *size = (size_t)total;
    *count = (uint32_t)n;
    return 0;
}

static inline int wasi_config_stream(PyObject *value, PyObject **slot) {
    if (value == Py_None) return 0;
    Py_INCREF(value);
    *slot = value;
    return 0;
}

/* stdin, stdout, stderr: None is nothing (an empty input, an output that is thrown away); an absent key is sys.stdin, sys.stdout, sys.stderr */
static inline int wasi_config_std(PyObject *value, PyObject **slot, int input) {
    if (value == Py_None && input) {
        *slot = PyBytes_FromStringAndSize("", 0);
        return *slot ? 0 : -1;
    }
    Py_INCREF(value);
    *slot = value;
    return 0;
}

/* clock, random: a function; None is not an answer for either */
static inline int wasi_config_function(PyObject *value, const char *name, PyObject **slot) {
    if (!PyCallable_Check(value)) {
        PyErr_Format(PyExc_TypeError, "wasi: '%s' must be a function", name);
        return -1;
    }
    Py_INCREF(value);
    *slot = value;
    return 0;
}

/* the preopens of the config: for each name, the real directory it stands for (one that is not a directory is an error) */
static inline int wasi_setup_preopens(wasmext_wasi_py *p, wasi_py_options *o) {
    if (o->preopens == NULL) {
        if (o->readonly != NULL) {
            PyErr_SetString(PyExc_ValueError, "wasi: readonly without preopens");
            return -1;
        }
        return 0;
    }
    if (!PyDict_Check(o->preopens)) {
        PyErr_SetString(PyExc_TypeError, "wasi: preopens must be a dict {name: directory}");
        return -1;
    }
    /* readonly: True (all of them), a name, or a list of names */
    PyObject *names = NULL;
    int all_readonly = 0;
    if (o->readonly != NULL) {
        if (o->readonly == Py_True) {
            all_readonly = 1;
        } else if (o->readonly == Py_False) {
            all_readonly = 0;
        } else if (PyUnicode_Check(o->readonly)) {
            names = Py_BuildValue("[O]", o->readonly);
        } else {
            names = PySequence_List(o->readonly);
        }
        if (names == NULL && PyErr_Occurred()) return -1;
    }
    for (Py_ssize_t i = 0; names != NULL && i < PyList_Size(names); i++) {
        if (!PyDict_Contains(o->preopens, PyList_GetItem(names, i))) {
            PyErr_Format(PyExc_ValueError, "wasi: readonly: no preopen of that name: %R", PyList_GetItem(names, i));
            Py_DECREF(names);
            return -1;
        }
    }
    PyObject *os = wasi_module_of(&p->os_module, "os");
    PyObject *ospath = os ? PyObject_GetAttrString(os, "path") : NULL;
    PyObject *items = ospath ? PyMapping_Items(o->preopens) : NULL;
    int rc = -1;
    if (items == NULL) goto done;
    o->items = (fusedwasi_p1_preopen *)FUSEDWASI_P1_CALLOC((size_t)PyList_Size(items) + 1, sizeof(fusedwasi_p1_preopen));
    if (o->items == NULL) {
        PyErr_NoMemory();
        goto done;
    }
    for (Py_ssize_t i = 0; i < PyList_Size(items); i++) {
        PyObject *pair = PyList_GetItem(items, i), *name = PyTuple_GetItem(pair, 0), *host = PyTuple_GetItem(pair, 1);
        PyObject *given = PyOS_FSPath(host);
        PyObject *real = given ? PyObject_CallMethod(ospath, "realpath", "O", given) : NULL;
        PyObject *isdir = real ? PyObject_CallMethod(ospath, "isdir", "O", real) : NULL;
        if (isdir != NULL && !PyObject_IsTrue(isdir)) {
            PyErr_Format(PyExc_NotADirectoryError, "preopen %R: %R is not a directory", name, host);
            Py_CLEAR(isdir);
        }
        PyObject *root = isdir ? PyObject_CallMethod(os, "fsencode", "O", real) : NULL;
        PyObject *shown = PyUnicode_Check(name) ? PyUnicode_AsUTF8String(name) : NULL;
        if (shown == NULL && !PyErr_Occurred()) PyErr_SetString(PyExc_TypeError, "wasi: the names of preopens must be strings");
        Py_XDECREF(given);
        Py_XDECREF(real);
        Py_XDECREF(isdir);
        int made = 0;
        if (root != NULL && shown != NULL) {
            fusedwasi_p1_preopen *item = &o->items[o->nitems];
            item->name = fusedwasi_p1_copy(PyBytes_AsString(shown), (size_t)PyBytes_Size(shown));
            item->name_len = (size_t)PyBytes_Size(shown);
            item->host = fusedwasi_p1_copy(PyBytes_AsString(root), strlen(PyBytes_AsString(root)));
            o->nitems++;  /* counted before the check, so that both are freed */
            if (item->name == NULL || item->host == NULL) {
                PyErr_NoMemory();
            } else {
                item->readonly = all_readonly;
                for (Py_ssize_t k = 0; names != NULL && k < PyList_Size(names); k++) {
                    int same = PyObject_RichCompareBool(PyList_GetItem(names, k), name, Py_EQ);
                    if (same < 0) PyErr_Clear();
                    if (same == 1) item->readonly = 1;
                }
                made = 1;
            }
        }
        Py_XDECREF(root);
        Py_XDECREF(shown);
        if (!made) goto done;
    }
    rc = 0;
done:
    Py_XDECREF(items);
    Py_XDECREF(ospath);
    Py_XDECREF(names);
    Py_CLEAR(o->preopens);
    Py_CLEAR(o->readonly);
    return rc;
}

/* one key of the config; 0, or -1 with an exception set */
static inline int wasi_apply_option(wasmext_wasi_py *p, wasi_py_options *o, const char *name, PyObject *value) {
    if (strcmp(name, "args") == 0) {
        if (value == Py_None) {  /* none, which is not the name of the program */
            o->args = (char *)FUSEDWASI_P1_MALLOC(1);
            if (o->args == NULL) return (PyErr_NoMemory(), -1);
            o->args_size = 0;
            o->argc = 0;
            return 0;
        }
        return wasi_pack_strings(value, &o->args, &o->args_size, &o->argc);
    }
    if (strcmp(name, "env") == 0) {
        if (value == Py_None) return 0;  /* empty, as when it is absent */
        PyObject *items = PyMapping_Items(value), *strings = NULL;
        if (items == NULL) return -1;
        strings = PyList_New(0);
        Py_ssize_t n = PyList_Size(items);
        for (Py_ssize_t i = 0; strings != NULL && i < n; i++) {
            PyObject *pair = PyList_GetItem(items, i);
            PyObject *key = PyTuple_GetItem(pair, 0), *val = PyTuple_GetItem(pair, 1);
            if (!PyUnicode_Check(key) || !PyUnicode_Check(val)) {
                PyErr_SetString(PyExc_TypeError, "wasi: env: names and values are strings");
                Py_CLEAR(strings);
                break;
            }
            if (PyUnicode_GetLength(key) == 0 || PyUnicode_FindChar(key, '=', 0, PyUnicode_GetLength(key), 1) >= 0) {
                PyErr_SetString(PyExc_ValueError, "wasi: env: a name is not empty and has no '=' in it");
                Py_CLEAR(strings);
                break;
            }
            PyObject *line = PyUnicode_FromFormat("%U=%U", key, val);
            if (line == NULL || PyList_Append(strings, line) < 0) {
                Py_XDECREF(line);
                Py_CLEAR(strings);
                break;
            }
            Py_DECREF(line);
        }
        Py_DECREF(items);
        if (strings == NULL) return -1;
        int rc = wasi_pack_strings(strings, &o->env, &o->env_size, &o->envc);
        Py_DECREF(strings);
        return rc;
    }
    if (strcmp(name, "stdin") == 0) return wasi_config_std(value, &p->stream[0], 1);
    if (strcmp(name, "stdout") == 0) return wasi_config_std(value, &p->stream[1], 0);
    if (strcmp(name, "stderr") == 0) return wasi_config_std(value, &p->stream[2], 0);
    if (strcmp(name, "clock") == 0) return wasi_config_function(value, "clock", &p->clock_fn);
    if (strcmp(name, "random") == 0) return wasi_config_function(value, "random", &p->random_fn);
    if (strcmp(name, "preopens") == 0) return wasi_config_stream(value, &o->preopens);
    if (strcmp(name, "readonly") == 0) return wasi_config_stream(value, &o->readonly);
    PyErr_Format(PyExc_TypeError, "wasi: unknown option '%s'", name);
    return -1;
}

/* ---- the state of the extension: what the glue calls --------------------------------------------------------------------- */

static inline int wasmext_wasi_traverse(fusedwasi_p1_state *w, visitproc visit, void *arg) {
    wasmext_wasi_py *p = WASI_PY(w);
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

static inline void wasi_py_clear(wasmext_wasi_py *p) {
    for (int i = 0; i < 3; i++) Py_CLEAR(p->stream[i]);
    Py_CLEAR(p->exit_type);
    Py_CLEAR(p->signal_type);
    Py_CLEAR(p->ended_type);
    Py_CLEAR(p->time_module);
    Py_CLEAR(p->os_module);
    Py_CLEAR(p->text_base);
    Py_CLEAR(p->clock_fn);
    Py_CLEAR(p->random_fn);
    for (int i = 0; i < 3; i++) Py_CLEAR(p->decoder[i]);
    Py_CLEAR(p->stdin_rest);
}

static inline void wasmext_wasi_clear(fusedwasi_p1_state *w) { wasi_py_clear(WASI_PY(w)); }

static inline void wasmext_wasi_free(fusedwasi_p1_state *w) {
    if (w == NULL) return;
    wasmext_wasi_py *p = WASI_PY(w);
    wasi_py_clear(p);
    fusedwasi_p1_destroy(w);
    FUSEDWASI_P1_FREE(p);
}

/* `config` is None or a dict with the keys args, env, stdin, stdout, stderr, clock, random, preopens, readonly; the exceptions are
   those that proc_exit and proc_raise raise; `program` is argv[0] when the config has no args. NULL with an exception set. */
static inline fusedwasi_p1_state *wasmext_wasi_new(PyObject *config, PyObject *exit_type, PyObject *signal_type, PyObject *ended_type,
                                             const char *program) {
    wasmext_wasi_py *p = (wasmext_wasi_py *)FUSEDWASI_P1_CALLOC(1, sizeof(wasmext_wasi_py));
    if (p == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    wasi_py_options o;
    memset(&o, 0, sizeof o);
    fusedwasi_p1_state *w = NULL;
    Py_INCREF(exit_type);
    p->exit_type = exit_type;
    Py_INCREF(signal_type);
    p->signal_type = signal_type;
    Py_INCREF(ended_type);
    p->ended_type = ended_type;
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
        int rc = wasi_apply_option(p, &o, PyBytes_AsString(encoded), value);
        Py_DECREF(encoded);
        if (rc < 0) goto fail;
    }
    if (wasi_setup_preopens(p, &o) < 0) goto fail;
    fusedwasi_p1_config cfg;
    memset(&cfg, 0, sizeof cfg);
    cfg.args = o.args;
    cfg.args_size = o.args_size;
    cfg.argc = o.argc;
    cfg.env = o.env;
    cfg.env_size = o.env_size;
    cfg.envc = o.envc;
    cfg.preopens = o.items;
    cfg.npreopens = o.nitems;
    cfg.program = program;
    cfg.hooks.stdin_read = wasi_py_stdin_read;
    cfg.hooks.stdout_write = wasi_py_stdout_write;
    cfg.hooks.sleep = wasi_py_sleep;
    cfg.hooks.end = wasi_py_end;
    if (p->clock_fn != NULL) cfg.hooks.clock = wasi_py_clock;
    if (p->random_fn != NULL) cfg.hooks.random = wasi_py_random;
    cfg.user = p;
    int err = 0;
    size_t bad = (size_t)-1;
    w = fusedwasi_p1_create(&cfg, &err, &bad);
    if (w == NULL) {
        errno = err;
        if (bad != (size_t)-1) PyErr_SetFromErrnoWithFilename(PyExc_OSError, o.items[bad].host);
        else PyErr_NoMemory();
        goto fail;
    }
    wasi_py_options_free(&o);
    return w;
fail:
    wasi_py_options_free(&o);
    wasi_py_clear(p);
    FUSEDWASI_P1_FREE(p);
    return NULL;
}

/* 0, or -1 with an exception set: the program is over */
static inline int wasmext_wasi_check(fusedwasi_p1_state *w) {
    if (w == NULL || !w->finished) return 0;
    PyObject *ended = WASI_PY(w)->ended_type;
    switch (w->finished) {
    case FUSEDWASI_P1_END_EXIT: PyErr_Format(ended, "the program has ended: proc_exit(%u)", (unsigned)w->end_value); break;
    case FUSEDWASI_P1_END_SIGNAL: PyErr_Format(ended, "the program has ended: proc_raise(%u)", (unsigned)w->end_value); break;
    default: PyErr_SetString(ended, "the program has ended: it trapped"); break;
    }
    return -1;
}

#endif
