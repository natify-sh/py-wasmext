/* WASI 0.1 (`wasi_snapshot_preview1`) for a module built by wasmext. See wasi_preview1.h and "Design: WASI" in FEATURES.md.

   First stage: arguments, environment, clocks, random bytes, the standard streams, proc_exit. The calls of the file system answer
   ENOSYS (the descriptors beyond 2 are not open, so BADF where the specification asks for it). Written from the specification
   (the witx files of the wasi-0.1 branch of WebAssembly/WASI). */

#include "wasi_preview1.h"

#include <stdint.h>
#include <string.h>

/* errno of WASI (not the C library's) */
enum {
    E_SUCCESS = 0, E_BADF = 8, E_FAULT = 21, E_INVAL = 28, E_IO = 29, E_NOMEM = 48, E_NOSYS = 52, E_NOTSOCK = 57,
    E_PIPE = 64, E_SPIPE = 70
};
enum { FILETYPE_CHARACTER_DEVICE = 2 };
/* the rights of the standard streams: fd_read, fd_fdstat_set_flags, fd_filestat_get, poll_fd_readwrite / fd_write, fd_sync ... */
#define RIGHTS_STDIN UINT64_C(0x820000a)
#define RIGHTS_STDOUT UINT64_C(0x8200058)

struct wasmext_wasi {
    char *args;       /* the arguments, each ended by a NUL */
    size_t args_size;
    uint32_t argc;
    char *env;        /* "NAME=value", each ended by a NUL */
    size_t env_size;
    uint32_t envc;
    PyObject *stream[3];  /* what the caller gave for stdin, stdout, stderr (NULL: sys.stdin, sys.stdout, sys.stderr) */
    Py_ssize_t stdin_pos; /* when stdin is bytes */
    PyObject *exit_type;
    PyObject *time_module;
    PyObject *os_module;
    wasm_rt_memory_t *memory;
};

/* ---- the state ---------------------------------------------------------------------------------------------------- */

/* the strings of a sequence into one buffer of NUL-ended strings */
static int pack_strings(PyObject *seq, const char *what, char **out, size_t *size, uint32_t *count) {
    PyObject *list = PySequence_List(seq);
    if (list == NULL) return -1;
    Py_ssize_t n = PyList_Size(list), total = 0;
    for (Py_ssize_t i = 0; i < n; i++) {
        Py_ssize_t len;
        if (PyUnicode_AsUTF8AndSize(PyList_GetItem(list, i), &len) == NULL) {
            Py_DECREF(list);
            return -1;
        }
        total += len + 1;
    }
    char *buf = (char *)PyMem_Malloc(total > 0 ? (size_t)total : 1);
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
    (void)what;
    *out = buf;
    *size = (size_t)total;
    *count = (uint32_t)n;
    return 0;
}

static int config_stream(PyObject *value, PyObject **slot) {
    if (value == Py_None) return 0;
    Py_INCREF(value);
    *slot = value;
    return 0;
}

/* one key of the config; 0, or -1 with an exception set */
static int apply_option(wasmext_wasi *w, const char *name, PyObject *value) {
    if (strcmp(name, "args") == 0) return pack_strings(value, "args", &w->args, &w->args_size, &w->argc);
    if (strcmp(name, "env") == 0) {
        PyObject *items = PyMapping_Items(value), *strings = NULL;
        if (items == NULL) return -1;
        strings = PyList_New(0);
        Py_ssize_t n = PyList_Size(items);
        for (Py_ssize_t i = 0; strings != NULL && i < n; i++) {
            PyObject *pair = PyList_GetItem(items, i);
            PyObject *line = PyUnicode_FromFormat("%U=%U", PyTuple_GetItem(pair, 0), PyTuple_GetItem(pair, 1));
            if (line == NULL || PyList_Append(strings, line) < 0) {
                Py_XDECREF(line);
                Py_CLEAR(strings);
                break;
            }
            Py_DECREF(line);
        }
        Py_DECREF(items);
        if (strings == NULL) return -1;
        int rc = pack_strings(strings, "env", &w->env, &w->env_size, &w->envc);
        Py_DECREF(strings);
        return rc;
    }
    if (strcmp(name, "stdin") == 0) return config_stream(value, &w->stream[0]);
    if (strcmp(name, "stdout") == 0) return config_stream(value, &w->stream[1]);
    if (strcmp(name, "stderr") == 0) return config_stream(value, &w->stream[2]);
    if (strcmp(name, "preopens") == 0) {
        if (value != Py_None && PyObject_IsTrue(value) != 0) {
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_NotImplementedError, "wasi: preopens are not supported yet");
            return -1;
        }
        return 0;
    }
    PyErr_Format(PyExc_TypeError, "wasi: unknown option '%s'", name);
    return -1;
}

wasmext_wasi *wasmext_wasi_new(PyObject *config, PyObject *exit_type, const char *program) {
    wasmext_wasi *w = (wasmext_wasi *)PyMem_Calloc(1, sizeof(wasmext_wasi));
    if (w == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    Py_INCREF(exit_type);
    w->exit_type = exit_type;
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
        int rc = apply_option(w, PyBytes_AsString(encoded), value);
        Py_DECREF(encoded);
        if (rc < 0) goto fail;
    }
    if (w->args == NULL) {  /* no args given: the program's own name */
        size_t len = strlen(program);
        w->args = (char *)PyMem_Malloc(len + 1);
        if (w->args == NULL) {
            PyErr_NoMemory();
            goto fail;
        }
        memcpy(w->args, program, len + 1);
        w->args_size = len + 1;
        w->argc = 1;
    }
    return w;
fail:
    wasmext_wasi_clear(w);
    wasmext_wasi_free(w);
    return NULL;
}

void wasmext_wasi_free(wasmext_wasi *w) {
    if (w == NULL) return;
    PyMem_Free(w->args);
    PyMem_Free(w->env);
    PyMem_Free(w);
}

int wasmext_wasi_traverse(wasmext_wasi *w, visitproc visit, void *arg) {
    for (int i = 0; i < 3; i++) Py_VISIT(w->stream[i]);
    Py_VISIT(w->exit_type);
    Py_VISIT(w->time_module);
    Py_VISIT(w->os_module);
    return 0;
}

void wasmext_wasi_clear(wasmext_wasi *w) {
    for (int i = 0; i < 3; i++) Py_CLEAR(w->stream[i]);
    Py_CLEAR(w->exit_type);
    Py_CLEAR(w->time_module);
    Py_CLEAR(w->os_module);
}

void wasmext_wasi_bind(wasmext_wasi *w, wasm_rt_memory_t *memory) { w->memory = memory; }

/* ---- the memory of the instance (little-endian, as WebAssembly says) -------------------------------------------------- */

static int in_memory(const wasmext_wasi *w, uint32_t ptr, uint64_t len) {
    return w->memory != NULL && (uint64_t)ptr + len <= w->memory->size;
}

static int put_u8(wasmext_wasi *w, uint32_t ptr, uint8_t v) {
    if (!in_memory(w, ptr, 1)) return 0;
    w->memory->data[ptr] = v;
    return 1;
}

static int put_u16(wasmext_wasi *w, uint32_t ptr, uint16_t v) {
    if (!in_memory(w, ptr, 2)) return 0;
    w->memory->data[ptr] = (uint8_t)v;
    w->memory->data[ptr + 1] = (uint8_t)(v >> 8);
    return 1;
}

static int put_u32(wasmext_wasi *w, uint32_t ptr, uint32_t v) {
    if (!in_memory(w, ptr, 4)) return 0;
    for (int i = 0; i < 4; i++) w->memory->data[ptr + i] = (uint8_t)(v >> (8 * i));
    return 1;
}

static int put_u64(wasmext_wasi *w, uint32_t ptr, uint64_t v) {
    if (!in_memory(w, ptr, 8)) return 0;
    for (int i = 0; i < 8; i++) w->memory->data[ptr + i] = (uint8_t)(v >> (8 * i));
    return 1;
}

static int get_u32(const wasmext_wasi *w, uint32_t ptr, uint32_t *v) {
    if (!in_memory(w, ptr, 4)) return 0;
    *v = 0;
    for (int i = 0; i < 4; i++) *v |= (uint32_t)w->memory->data[ptr + i] << (8 * i);
    return 1;
}

/* ---- errors of Python ------------------------------------------------------------------------------------------------ */

/* An OSError becomes an errno of WASI; anything else is a trap of the call, with the exception still set. */
static uint32_t python_error(int *trapped) {
    if (PyErr_ExceptionMatches(PyExc_BrokenPipeError)) {
        PyErr_Clear();
        return E_PIPE;
    }
    if (PyErr_ExceptionMatches(PyExc_OSError)) {
        PyErr_Clear();
        return E_IO;
    }
    *trapped = 1;
    return 0;
}

#define STATE(s) wasmext_wasi *w = (wasmext_wasi *)(s)

/* ---- arguments and environment --------------------------------------------------------------------------------------- */

static uint32_t strings_sizes(wasmext_wasi *w, uint32_t count, size_t size, uint32_t count_ptr, uint32_t size_ptr) {
    if (!put_u32(w, count_ptr, count) || !put_u32(w, size_ptr, (uint32_t)size)) return E_FAULT;
    return E_SUCCESS;
}

static uint32_t strings_get(wasmext_wasi *w, const char *buf, size_t size, uint32_t count, uint32_t table, uint32_t out) {
    if (!in_memory(w, out, size) || !in_memory(w, table, (uint64_t)count * 4)) return E_FAULT;
    memcpy(w->memory->data + out, buf, size);
    size_t offset = 0;
    for (uint32_t i = 0; i < count; i++) {
        put_u32(w, table + 4 * i, out + (uint32_t)offset);
        offset += strlen(buf + offset) + 1;
    }
    return E_SUCCESS;
}

static uint32_t p1_args_sizes_get(void *s, uint32_t argc, uint32_t size, int *trapped) {
    STATE(s);
    (void)trapped;
    return strings_sizes(w, w->argc, w->args_size, argc, size);
}

static uint32_t p1_args_get(void *s, uint32_t argv, uint32_t buf, int *trapped) {
    STATE(s);
    (void)trapped;
    return strings_get(w, w->args, w->args_size, w->argc, argv, buf);
}

static uint32_t p1_environ_sizes_get(void *s, uint32_t count, uint32_t size, int *trapped) {
    STATE(s);
    (void)trapped;
    return strings_sizes(w, w->envc, w->env_size, count, size);
}

static uint32_t p1_environ_get(void *s, uint32_t environ_, uint32_t buf, int *trapped) {
    STATE(s);
    (void)trapped;
    return strings_get(w, w->env, w->env_size, w->envc, environ_, buf);
}

/* ---- clocks and random bytes (through Python: the sources differ between systems) --------------------------------------- */

static PyObject *module_of(PyObject **slot, const char *name) {
    if (*slot == NULL) *slot = PyImport_ImportModule(name);
    return *slot;
}

static const struct { const char *function, *info; } clocks[] = {
    {"time_ns", "time"}, {"monotonic_ns", "monotonic"}, {"process_time_ns", "process_time"}, {"thread_time_ns", "thread_time"},
};

static uint32_t p1_clock_res_get(void *s, uint32_t id, uint32_t ptr, int *trapped) {
    STATE(s);
    if (id > 3) return E_INVAL;
    PyObject *time = module_of(&w->time_module, "time");
    PyObject *info = time ? PyObject_CallMethod(time, "get_clock_info", "s", clocks[id].info) : NULL;
    PyObject *res = info ? PyObject_GetAttrString(info, "resolution") : NULL;
    Py_XDECREF(info);
    double seconds = res ? PyFloat_AsDouble(res) : -1.0;
    Py_XDECREF(res);
    if (seconds < 0 && PyErr_Occurred()) return python_error(trapped);
    uint64_t ns = seconds * 1e9 < 1.0 ? 1 : (uint64_t)(seconds * 1e9);
    return put_u64(w, ptr, ns) ? E_SUCCESS : E_FAULT;
}

static uint32_t p1_clock_time_get(void *s, uint32_t id, uint64_t precision, uint32_t ptr, int *trapped) {
    STATE(s);
    (void)precision;
    if (id > 3) return E_INVAL;
    PyObject *time = module_of(&w->time_module, "time");
    PyObject *value = time ? PyObject_CallMethod(time, clocks[id].function, NULL) : NULL;
    if (value == NULL) return python_error(trapped);
    unsigned long long ns = PyLong_AsUnsignedLongLongMask(value);
    Py_DECREF(value);
    return put_u64(w, ptr, ns) ? E_SUCCESS : E_FAULT;
}

static uint32_t p1_random_get(void *s, uint32_t buf, uint32_t size, int *trapped) {
    STATE(s);
    if (!in_memory(w, buf, size)) return E_FAULT;
    if (size == 0) return E_SUCCESS;
    PyObject *os = module_of(&w->os_module, "os");
    PyObject *bytes = os ? PyObject_CallMethod(os, "urandom", "I", size) : NULL;
    if (bytes == NULL) return python_error(trapped);
    char *data;
    Py_ssize_t len;
    if (PyBytes_AsStringAndSize(bytes, &data, &len) < 0 || (uint64_t)len != size) {
        Py_DECREF(bytes);
        return python_error(trapped);
    }
    memcpy(w->memory->data + buf, data, (size_t)len);
    Py_DECREF(bytes);
    return E_SUCCESS;
}

static uint32_t p1_sched_yield(void *s, int *trapped) {
    (void)s;
    (void)trapped;
    return E_SUCCESS;
}

static void p1_proc_exit(void *s, uint32_t code, int *trapped) {
    STATE(s);
    PyObject *exc = PyObject_CallFunction(w->exit_type, "I", code);
    if (exc != NULL) {
        PyObject *number = PyLong_FromUnsignedLong(code);
        if (number == NULL || PyObject_SetAttrString(exc, "code", number) < 0) PyErr_Clear();
        Py_XDECREF(number);
        PyErr_SetObject(w->exit_type, exc);
        Py_DECREF(exc);
    }
    *trapped = 1;
}

/* ---- the standard streams (through Python by default, so that the order against print() and a capture in a notebook or a test
   are right) --------------------------------------------------------------------------------------------------------- */

static int is_std(uint32_t fd) { return fd <= 2; }

/* the binary side of sys.stdout (after flushing its text layer), or the object the caller gave */
static int write_bytes(wasmext_wasi *w, uint32_t fd, const char *data, Py_ssize_t size) {
    PyObject *given = w->stream[fd], *target = given, *r;
    if (given == NULL) {
        PyObject *sys_stream = PySys_GetObject(fd == 1 ? "stdout" : "stderr");  /* borrowed */
        if (sys_stream == NULL || sys_stream == Py_None) return 0;
        PyObject *flushed = PyObject_CallMethod(sys_stream, "flush", NULL);
        if (flushed == NULL) return -1;
        Py_DECREF(flushed);
        PyObject *buffer = PyObject_GetAttrString(sys_stream, "buffer");
        if (buffer == NULL) {  /* a text stream with no binary side: it gets the text */
            PyErr_Clear();
            PyObject *text = PyUnicode_DecodeUTF8(data, size, "replace");
            r = text ? PyObject_CallMethod(sys_stream, "write", "O", text) : NULL;
            Py_XDECREF(text);
            Py_XDECREF(r);
            return r ? 0 : -1;
        }
        PyObject *bytes = PyBytes_FromStringAndSize(data, size);
        r = bytes ? PyObject_CallMethod(buffer, "write", "O", bytes) : NULL;
        Py_XDECREF(bytes);
        Py_DECREF(buffer);
        Py_XDECREF(r);
        return r ? 0 : -1;
    }
    PyObject *bytes = PyBytes_FromStringAndSize(data, size);
    if (bytes == NULL) return -1;
    if (PyObject_HasAttrString(target, "write")) r = PyObject_CallMethod(target, "write", "O", bytes);
    else r = PyObject_CallFunctionObjArgs(target, bytes, NULL);
    Py_DECREF(bytes);
    Py_XDECREF(r);
    return r ? 0 : -1;
}

static uint32_t p1_fd_write(void *s, uint32_t fd, uint32_t iovs, uint32_t count, uint32_t nwritten, int *trapped) {
    STATE(s);
    if (!is_std(fd) || fd == 0) return E_BADF;
    if (!in_memory(w, iovs, (uint64_t)count * 8)) return E_FAULT;
    uint64_t total = 0;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t base, len;
        get_u32(w, iovs + 8 * i, &base);
        get_u32(w, iovs + 8 * i + 4, &len);
        if (!in_memory(w, base, len)) return E_FAULT;
        if (len == 0) continue;
        if (write_bytes(w, fd, (const char *)w->memory->data + base, (Py_ssize_t)len) < 0) return python_error(trapped);
        total += len;
    }
    return put_u32(w, nwritten, (uint32_t)total) ? E_SUCCESS : E_FAULT;
}

/* up to `size` bytes of stdin, a new bytes object (empty at the end), or NULL with an exception */
static PyObject *read_bytes(wasmext_wasi *w, Py_ssize_t size) {
    PyObject *given = w->stream[0];
    if (given != NULL && (PyBytes_Check(given) || PyByteArray_Check(given))) {
        Py_ssize_t have = PyObject_Size(given);
        if (have < 0) return NULL;
        Py_ssize_t n = have - w->stdin_pos < size ? have - w->stdin_pos : size;
        PyObject *slice = PySequence_GetSlice(given, w->stdin_pos, w->stdin_pos + n);
        if (slice != NULL) w->stdin_pos += n;
        return slice;
    }
    PyObject *source = given;
    if (source == NULL) {
        source = PySys_GetObject("stdin");  /* borrowed */
        if (source == NULL || source == Py_None) return PyBytes_FromStringAndSize("", 0);
        PyObject *buffer = PyObject_GetAttrString(source, "buffer");
        if (buffer == NULL) {  /* a text stream: its text, as UTF-8 */
            PyErr_Clear();
            PyObject *text = PyObject_CallMethod(source, "read", "n", size);
            PyObject *bytes = text ? PyUnicode_AsUTF8String(text) : NULL;
            Py_XDECREF(text);
            return bytes;
        }
        PyObject *bytes = PyObject_HasAttrString(buffer, "read1") ? PyObject_CallMethod(buffer, "read1", "n", size)
                                                                  : PyObject_CallMethod(buffer, "read", "n", size);
        Py_DECREF(buffer);
        return bytes;
    }
    return PyObject_CallMethod(source, "read", "n", size);
}

static uint32_t p1_fd_read(void *s, uint32_t fd, uint32_t iovs, uint32_t count, uint32_t nread, int *trapped) {
    STATE(s);
    if (fd != 0) return is_std(fd) ? E_BADF : E_BADF;
    if (!in_memory(w, iovs, (uint64_t)count * 8)) return E_FAULT;
    uint32_t base = 0, len = 0;
    for (uint32_t i = 0; i < count; i++) {  /* the first buffer that is not empty: a short read is allowed */
        get_u32(w, iovs + 8 * i, &base);
        get_u32(w, iovs + 8 * i + 4, &len);
        if (len) break;
    }
    if (!in_memory(w, base, len)) return E_FAULT;
    uint32_t got = 0;
    if (len) {
        PyObject *bytes = read_bytes(w, (Py_ssize_t)len);
        if (bytes == NULL) return python_error(trapped);
        char *data;
        Py_ssize_t n;
        if (PyBytes_AsStringAndSize(bytes, &data, &n) < 0 || (uint64_t)n > len) {
            Py_DECREF(bytes);
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "stdin gave more bytes than were asked for");
            return python_error(trapped);
        }
        memcpy(w->memory->data + base, data, (size_t)n);
        got = (uint32_t)n;
        Py_DECREF(bytes);
    }
    return put_u32(w, nread, got) ? E_SUCCESS : E_FAULT;
}

static uint32_t p1_fd_close(void *s, uint32_t fd, int *trapped) {
    (void)s;
    (void)trapped;
    return is_std(fd) ? E_SUCCESS : E_BADF;
}

static uint32_t p1_fd_fdstat_get(void *s, uint32_t fd, uint32_t ptr, int *trapped) {
    STATE(s);
    (void)trapped;
    if (!is_std(fd)) return E_BADF;
    uint64_t rights = fd == 0 ? RIGHTS_STDIN : RIGHTS_STDOUT;
    if (!in_memory(w, ptr, 24)) return E_FAULT;
    memset(w->memory->data + ptr, 0, 24);
    put_u8(w, ptr, FILETYPE_CHARACTER_DEVICE);
    put_u16(w, ptr + 2, 0);  /* fdflags */
    put_u64(w, ptr + 8, rights);
    put_u64(w, ptr + 16, 0);
    return E_SUCCESS;
}

static uint32_t p1_fd_prestat_get(void *s, uint32_t fd, uint32_t ptr, int *trapped) {
    (void)s;
    (void)fd;
    (void)ptr;
    (void)trapped;
    return E_BADF;  /* no directory is preopened: the end of the list the program walks */
}

static uint32_t p1_fd_prestat_dir_name(void *s, uint32_t fd, uint32_t path, uint32_t size, int *trapped) {
    (void)s;
    (void)fd;
    (void)path;
    (void)size;
    (void)trapped;
    return E_BADF;
}

static uint32_t p1_fd_seek(void *s, uint32_t fd, uint64_t offset, uint32_t whence, uint32_t ptr, int *trapped) {
    (void)s;
    (void)offset;
    (void)whence;
    (void)ptr;
    (void)trapped;
    return is_std(fd) ? E_SPIPE : E_BADF;
}

static uint32_t p1_fd_tell(void *s, uint32_t fd, uint32_t ptr, int *trapped) {
    (void)s;
    (void)ptr;
    (void)trapped;
    return is_std(fd) ? E_SPIPE : E_BADF;
}

/* ---- not yet: ENOSYS, as the specification allows (ENOTSOCK for the sockets, which will not be there) --------------------- */

#define NOT_YET(name, code, ...) \
    static uint32_t p1_##name(void *s, __VA_ARGS__, int *trapped) { \
        (void)s; \
        (void)trapped; \
        return code; \
    }

NOT_YET(proc_raise, E_NOSYS, uint32_t a)
NOT_YET(poll_oneoff, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d)
NOT_YET(fd_pread, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint64_t d, uint32_t e)
NOT_YET(fd_pwrite, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint64_t d, uint32_t e)
NOT_YET(fd_advise, E_NOSYS, uint32_t a, uint64_t b, uint64_t c, uint32_t d)
NOT_YET(fd_allocate, E_NOSYS, uint32_t a, uint64_t b, uint64_t c)
NOT_YET(fd_datasync, E_NOSYS, uint32_t a)
NOT_YET(fd_sync, E_NOSYS, uint32_t a)
NOT_YET(fd_renumber, E_NOSYS, uint32_t a, uint32_t b)
NOT_YET(fd_fdstat_set_flags, E_NOSYS, uint32_t a, uint32_t b)
NOT_YET(fd_fdstat_set_rights, E_NOSYS, uint32_t a, uint64_t b, uint64_t c)
NOT_YET(fd_filestat_get, E_NOSYS, uint32_t a, uint32_t b)
NOT_YET(fd_filestat_set_size, E_NOSYS, uint32_t a, uint64_t b)
NOT_YET(fd_filestat_set_times, E_NOSYS, uint32_t a, uint64_t b, uint64_t c, uint32_t d)
NOT_YET(fd_readdir, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint64_t d, uint32_t e)
NOT_YET(path_create_directory, E_NOSYS, uint32_t a, uint32_t b, uint32_t c)
NOT_YET(path_filestat_get, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e)
NOT_YET(path_filestat_set_times, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint64_t e, uint64_t f, uint32_t g)
NOT_YET(path_link, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f, uint32_t g)
NOT_YET(path_open, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint64_t f, uint64_t g, uint32_t h, uint32_t i)
NOT_YET(path_readlink, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f)
NOT_YET(path_remove_directory, E_NOSYS, uint32_t a, uint32_t b, uint32_t c)
NOT_YET(path_rename, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f)
NOT_YET(path_symlink, E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e)
NOT_YET(path_unlink_file, E_NOSYS, uint32_t a, uint32_t b, uint32_t c)
NOT_YET(sock_accept, E_NOTSOCK, uint32_t a, uint32_t b, uint32_t c)
NOT_YET(sock_recv, E_NOTSOCK, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f)
NOT_YET(sock_send, E_NOTSOCK, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e)
NOT_YET(sock_shutdown, E_NOTSOCK, uint32_t a, uint32_t b)

/* ---- the table ------------------------------------------------------------------------------------------------------- */

#define ENTRY(name) {#name, (void *)p1_##name}

static const struct { const char *name; void *function; } functions[] = {
    ENTRY(args_get), ENTRY(args_sizes_get), ENTRY(environ_get), ENTRY(environ_sizes_get), ENTRY(clock_res_get),
    ENTRY(clock_time_get), ENTRY(random_get), ENTRY(sched_yield), ENTRY(proc_exit), ENTRY(proc_raise), ENTRY(poll_oneoff),
    ENTRY(fd_read), ENTRY(fd_pread), ENTRY(fd_write), ENTRY(fd_pwrite), ENTRY(fd_seek), ENTRY(fd_tell), ENTRY(fd_advise),
    ENTRY(fd_allocate), ENTRY(fd_datasync), ENTRY(fd_sync), ENTRY(fd_close), ENTRY(fd_renumber), ENTRY(fd_fdstat_get),
    ENTRY(fd_fdstat_set_flags), ENTRY(fd_fdstat_set_rights), ENTRY(fd_filestat_get), ENTRY(fd_filestat_set_size),
    ENTRY(fd_filestat_set_times), ENTRY(fd_prestat_get), ENTRY(fd_prestat_dir_name), ENTRY(fd_readdir),
    ENTRY(path_create_directory), ENTRY(path_filestat_get), ENTRY(path_filestat_set_times), ENTRY(path_link), ENTRY(path_open),
    ENTRY(path_readlink), ENTRY(path_remove_directory), ENTRY(path_rename), ENTRY(path_symlink), ENTRY(path_unlink_file),
    ENTRY(sock_accept), ENTRY(sock_recv), ENTRY(sock_send), ENTRY(sock_shutdown),
};

void *wasmext_wasi_preview1_lookup(const char *name) {
    for (size_t i = 0; i < sizeof functions / sizeof functions[0]; i++)
        if (strcmp(functions[i].name, name) == 0) return functions[i].function;
    return NULL;
}
