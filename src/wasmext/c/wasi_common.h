/* The part of WASI 0.1 that `wasi_snapshot_preview1` and `wasi_unstable` (the first snapshot) share: the state of an instance and a
   function `wasi_<name>` for each call of the specification. Header only, included by wasi_preview1.h and wasi_unstable.h; the
   functions are `static inline`, so those the module does not import are not in the object. A module needs nothing of wasmext
   when it runs. See "Design: WASI" in FEATURES.md.

   First stage: arguments, environment, clocks, random bytes, the standard streams, proc_exit. The calls of the file system answer
   ENOSYS (the descriptors beyond 2 are not open, so BADF where the specification asks for it). Written from the specification
   (the witx files of the wasi-0.1 branch of WebAssembly/WASI).

   A WASI call is `uint32_t wasi_<name>(void *state, parameters..., int *trapped)` (proc_exit returns nothing): a trap (an exception
   set in Python) is reported through `trapped`. `wasmext_wasi_new` makes the state: `config` is None or a dict with the keys args,
   env, stdin, stdout, stderr, preopens; `exit_type` is the exception that proc_exit raises (called with the code); `program` is
   argv[0] when the config has no args.

   The two snapshots differ in four things (the order of `whence`, one right less, a 32-bit link count in `filestat`, an extra
   `identifier` in a clock subscription) and in `sock_accept`, which the first one has not. None of the calls built so far reads or
   writes them, so the same function serves both; the day one does, wasi_unstable.h defines `wasi_unstable_<name>`, which the glue
   then calls for it. */
#ifndef WASMEXT_WASI_COMMON_H
#define WASMEXT_WASI_COMMON_H

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#ifdef _WIN32
#include <io.h>
#define WASI_READ(fd, buf, n) _read((fd), (buf), (unsigned int)(n))
#define WASI_LSEEK(fd, off, whence) _lseeki64((fd), (off), (whence))
#define WASI_CLOSE(fd) _close(fd)
#else
#include <unistd.h>
#define WASI_READ(fd, buf, n) read((fd), (buf), (n))
#define WASI_LSEEK(fd, off, whence) lseek((fd), (off), (whence))
#define WASI_CLOSE(fd) close(fd)
#endif
#include "wasm-rt.h"

typedef struct wasmext_wasi wasmext_wasi;

static inline void wasmext_wasi_clear(wasmext_wasi *w);
static inline void wasmext_wasi_free(wasmext_wasi *w);

/* errno of WASI (not the C library's) */
enum {
    WASI_E_SUCCESS = 0, WASI_E_ACCES = 2, WASI_E_AGAIN = 6, WASI_E_BADF = 8, WASI_E_EXIST = 20, WASI_E_FAULT = 21, WASI_E_FBIG = 22,
    WASI_E_INTR = 27, WASI_E_INVAL = 28, WASI_E_IO = 29, WASI_E_ISDIR = 31, WASI_E_LOOP = 32, WASI_E_MFILE = 33, WASI_E_MLINK = 34,
    WASI_E_NAMETOOLONG = 37, WASI_E_NFILE = 41, WASI_E_NODEV = 43, WASI_E_NOENT = 44, WASI_E_NOMEM = 48, WASI_E_NOSPC = 51,
    WASI_E_NOSYS = 52, WASI_E_NOTDIR = 54, WASI_E_NOTEMPTY = 55, WASI_E_NOTSOCK = 57, WASI_E_NOTSUP = 58, WASI_E_PERM = 63,
    WASI_E_PIPE = 64, WASI_E_RANGE = 68, WASI_E_ROFS = 69, WASI_E_SPIPE = 70, WASI_E_XDEV = 75, WASI_E_NOTCAPABLE = 76
};
enum {
    WASI_FT_UNKNOWN = 0, WASI_FT_BLOCK = 1, WASI_FT_CHAR = 2, WASI_FT_DIR = 3, WASI_FT_REGULAR = 4, WASI_FT_SOCKET_STREAM = 6,
    WASI_FT_SYMLINK = 7
};
/* the oflags, fdflags and lookupflags of path_open */
enum { WASI_O_CREAT = 1, WASI_O_DIRECTORY = 2, WASI_O_EXCL = 4, WASI_O_TRUNC = 8, WASI_LOOKUP_FOLLOW = 1 };
/* the rights: one bit each, in the order of the specification */
#define WASI_R(n) (UINT64_C(1) << (n))
#define WASI_R_FD_READ WASI_R(1)
#define WASI_R_FD_SEEK WASI_R(2)
#define WASI_R_FD_TELL WASI_R(5)
#define WASI_R_FD_WRITE WASI_R(6)
#define WASI_R_PATH_OPEN WASI_R(13)
#define WASI_R_FD_READDIR WASI_R(14)
#define WASI_R_PATH_FILESTAT_GET WASI_R(18)
#define WASI_R_FD_FILESTAT_GET WASI_R(21)
#define WASI_R_ALL ((UINT64_C(1) << 30) - 1)
/* what changes something: taken away from a preopen that is read-only */
#define WASI_R_MUTATING \
    (WASI_R(0) | WASI_R(4) | WASI_R(6) | WASI_R(8) | WASI_R(9) | WASI_R(10) | WASI_R(11) | WASI_R(12) | WASI_R(16) | WASI_R(17) | \
     WASI_R(19) | WASI_R(20) | WASI_R(22) | WASI_R(23) | WASI_R(24) | WASI_R(25) | WASI_R(26))
/* the rights of the standard streams: fd_read, fd_fdstat_set_flags, fd_filestat_get, poll_fd_readwrite / fd_write, fd_sync ... */
#define WASI_RIGHTS_STDIN UINT64_C(0x820000a)
#define WASI_RIGHTS_STDOUT UINT64_C(0x8200058)

/* an open descriptor: a standard stream, a file (an operating system descriptor) or a directory (a path: Windows cannot open one) */
enum { WASI_K_NONE = 0, WASI_K_STD, WASI_K_FILE, WASI_K_DIR };
typedef struct {
    uint8_t kind;
    uint8_t filetype;
    uint16_t flags;      /* fdflags */
    int osfd;            /* a file */
    uint64_t rights, inheriting;
    char *root;          /* a directory: the real path of the preopen it is under (in the encoding of the file system) */
    char *rel;           /* ... and its place below it, '/' between names, "" at the root */
    char *preopen;       /* the name the program sees, for a preopen */
    size_t preopen_len;
    PyObject *listing;   /* fd_readdir: the list of the directory, made at cookie 0 */
} wasi_entry;

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
    wasi_entry *entries;  /* the descriptors, by number */
    uint32_t nentries;
    PyObject *cfg_preopens, *cfg_readonly;  /* from the config, until the preopens are made */
};

/* the errno of the C library (or of an OSError) as an errno of WASI */
static inline uint32_t wasi_errno(int e) {
    switch (e) {
    case 0: return WASI_E_SUCCESS;
    case EACCES: return WASI_E_ACCES;
    case EAGAIN: return WASI_E_AGAIN;
    case EBADF: return WASI_E_BADF;
    case EEXIST: return WASI_E_EXIST;
    case EFBIG: return WASI_E_FBIG;
    case EINTR: return WASI_E_INTR;
    case EINVAL: return WASI_E_INVAL;
    case EIO: return WASI_E_IO;
    case EISDIR: return WASI_E_ISDIR;
    case ELOOP: return WASI_E_LOOP;
    case EMFILE: return WASI_E_MFILE;
    case EMLINK: return WASI_E_MLINK;
    case ENAMETOOLONG: return WASI_E_NAMETOOLONG;
    case ENFILE: return WASI_E_NFILE;
    case ENODEV: return WASI_E_NODEV;
    case ENOENT: return WASI_E_NOENT;
    case ENOMEM: return WASI_E_NOMEM;
    case ENOSPC: return WASI_E_NOSPC;
    case ENOTDIR: return WASI_E_NOTDIR;
    case ENOTEMPTY: return WASI_E_NOTEMPTY;
    case ENOTSUP: return WASI_E_NOTSUP;
    case EPERM: return WASI_E_PERM;
    case EPIPE: return WASI_E_PIPE;
    case ERANGE: return WASI_E_RANGE;
    case EROFS: return WASI_E_ROFS;
    case ESPIPE: return WASI_E_SPIPE;
    case EXDEV: return WASI_E_XDEV;
    default: return WASI_E_IO;
    }
}

/* ---- the state ---------------------------------------------------------------------------------------------------- */

/* the strings of a sequence into one buffer of NUL-ended strings */
static inline int wasi_pack_strings(PyObject *seq, const char *what, char **out, size_t *size, uint32_t *count) {
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

static inline int wasi_config_stream(PyObject *value, PyObject **slot) {
    if (value == Py_None) return 0;
    Py_INCREF(value);
    *slot = value;
    return 0;
}

static inline PyObject *wasi_module_of(PyObject **slot, const char *name) {
    if (*slot == NULL) *slot = PyImport_ImportModule(name);
    return *slot;
}

static inline char *wasi_copy(const char *text, size_t len) {
    char *out = (char *)PyMem_Malloc(len + 1);
    if (out != NULL) {
        memcpy(out, text, len);
        out[len] = '\0';
    }
    return out;
}

/* closes what the descriptor holds; 0, or -1 with errno from the close of a file */
static inline int wasi_release(wasi_entry *e) {
    int rc = 0;
    if (e->kind == WASI_K_FILE) rc = WASI_CLOSE(e->osfd);
    PyMem_Free(e->root);
    PyMem_Free(e->rel);
    PyMem_Free(e->preopen);
    Py_CLEAR(e->listing);
    memset(e, 0, sizeof *e);
    return rc;
}

/* the lowest free number from 3 on; -1 when there is no memory */
static inline int64_t wasi_new_fd(wasmext_wasi *w) {
    for (uint32_t i = 3; i < w->nentries; i++)
        if (w->entries[i].kind == WASI_K_NONE) return i;
    uint32_t n = w->nentries * 2;
    wasi_entry *bigger = (wasi_entry *)PyMem_Realloc(w->entries, (size_t)n * sizeof(wasi_entry));
    if (bigger == NULL) return -1;
    memset(bigger + w->nentries, 0, (size_t)(n - w->nentries) * sizeof(wasi_entry));
    uint32_t first = w->nentries;
    w->entries = bigger;
    w->nentries = n;
    return first;
}

/* the preopens of the config: for each name, the real directory it stands for (one that is not a directory is an error) */
static inline int wasi_setup_preopens(wasmext_wasi *w) {
    if (w->cfg_preopens == NULL) {
        if (w->cfg_readonly != NULL) {
            PyErr_SetString(PyExc_ValueError, "wasi: readonly without preopens");
            return -1;
        }
        return 0;
    }
    if (!PyDict_Check(w->cfg_preopens)) {
        PyErr_SetString(PyExc_TypeError, "wasi: preopens must be a dict {name: directory}");
        return -1;
    }
    /* readonly: True (all of them), a name, or a list of names */
    PyObject *names = NULL;
    int all_readonly = 0;
    if (w->cfg_readonly != NULL) {
        if (w->cfg_readonly == Py_True) {
            all_readonly = 1;
        } else if (w->cfg_readonly == Py_False) {
            all_readonly = 0;
        } else if (PyUnicode_Check(w->cfg_readonly)) {
            names = Py_BuildValue("[O]", w->cfg_readonly);
        } else {
            names = PySequence_List(w->cfg_readonly);
        }
        if (names == NULL && PyErr_Occurred()) return -1;
    }
    for (Py_ssize_t i = 0; names != NULL && i < PyList_Size(names); i++) {
        if (!PyDict_Contains(w->cfg_preopens, PyList_GetItem(names, i))) {
            PyErr_Format(PyExc_ValueError, "wasi: readonly: no preopen of that name: %R", PyList_GetItem(names, i));
            Py_DECREF(names);
            return -1;
        }
    }
    PyObject *os = wasi_module_of(&w->os_module, "os");
    PyObject *ospath = os ? PyObject_GetAttrString(os, "path") : NULL;
    PyObject *items = ospath ? PyMapping_Items(w->cfg_preopens) : NULL;
    int rc = -1;
    if (items == NULL) goto done;
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
            int64_t number = wasi_new_fd(w);
            wasi_entry *e = number >= 0 ? &w->entries[number] : NULL;
            if (e == NULL) {
                PyErr_NoMemory();
            } else {
                int readonly = all_readonly;
                for (Py_ssize_t k = 0; names != NULL && k < PyList_Size(names); k++) {
                    int same = PyObject_RichCompareBool(PyList_GetItem(names, k), name, Py_EQ);
                    if (same < 0) PyErr_Clear();
                    if (same == 1) readonly = 1;
                }
                memset(e, 0, sizeof *e);
                e->kind = WASI_K_DIR;
                e->filetype = WASI_FT_DIR;
                e->rights = e->inheriting = readonly ? (WASI_R_ALL & ~WASI_R_MUTATING) : WASI_R_ALL;
                e->root = wasi_copy(PyBytes_AsString(root), (size_t)PyBytes_Size(root));
                e->rel = wasi_copy("", 0);
                e->preopen = wasi_copy(PyBytes_AsString(shown), (size_t)PyBytes_Size(shown));
                e->preopen_len = (size_t)PyBytes_Size(shown);
                if (e->root == NULL || e->rel == NULL || e->preopen == NULL) {
                    wasi_release(e);
                    PyErr_NoMemory();
                } else {
                    made = 1;
                }
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
    Py_CLEAR(w->cfg_preopens);
    Py_CLEAR(w->cfg_readonly);
    return rc;
}

/* one key of the config; 0, or -1 with an exception set */
static inline int wasi_apply_option(wasmext_wasi *w, const char *name, PyObject *value) {
    if (strcmp(name, "args") == 0) return wasi_pack_strings(value, "args", &w->args, &w->args_size, &w->argc);
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
        int rc = wasi_pack_strings(strings, "env", &w->env, &w->env_size, &w->envc);
        Py_DECREF(strings);
        return rc;
    }
    if (strcmp(name, "stdin") == 0) return wasi_config_stream(value, &w->stream[0]);
    if (strcmp(name, "stdout") == 0) return wasi_config_stream(value, &w->stream[1]);
    if (strcmp(name, "stderr") == 0) return wasi_config_stream(value, &w->stream[2]);
    if (strcmp(name, "preopens") == 0) return wasi_config_stream(value, &w->cfg_preopens);
    if (strcmp(name, "readonly") == 0) return wasi_config_stream(value, &w->cfg_readonly);
    PyErr_Format(PyExc_TypeError, "wasi: unknown option '%s'", name);
    return -1;
}

static inline wasmext_wasi *wasmext_wasi_new(PyObject *config, PyObject *exit_type, const char *program) {
    wasmext_wasi *w = (wasmext_wasi *)PyMem_Calloc(1, sizeof(wasmext_wasi));
    if (w == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    Py_INCREF(exit_type);
    w->exit_type = exit_type;
    w->nentries = 8;
    w->entries = (wasi_entry *)PyMem_Calloc(w->nentries, sizeof(wasi_entry));
    if (w->entries == NULL) {
        PyErr_NoMemory();
        goto fail;
    }
    for (int i = 0; i < 3; i++) w->entries[i].kind = WASI_K_STD;
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
        int rc = wasi_apply_option(w, PyBytes_AsString(encoded), value);
        Py_DECREF(encoded);
        if (rc < 0) goto fail;
    }
    if (wasi_setup_preopens(w) < 0) goto fail;
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

static inline void wasmext_wasi_free(wasmext_wasi *w) {
    if (w == NULL) return;
    for (uint32_t i = 0; i < w->nentries; i++) wasi_release(&w->entries[i]);
    PyMem_Free(w->entries);
    PyMem_Free(w->args);
    PyMem_Free(w->env);
    PyMem_Free(w);
}

static inline int wasmext_wasi_traverse(wasmext_wasi *w, visitproc visit, void *arg) {
    for (int i = 0; i < 3; i++) Py_VISIT(w->stream[i]);
    Py_VISIT(w->exit_type);
    Py_VISIT(w->time_module);
    Py_VISIT(w->os_module);
    for (uint32_t i = 0; i < w->nentries; i++) Py_VISIT(w->entries[i].listing);
    return 0;
}

static inline void wasmext_wasi_clear(wasmext_wasi *w) {
    for (int i = 0; i < 3; i++) Py_CLEAR(w->stream[i]);
    Py_CLEAR(w->exit_type);
    Py_CLEAR(w->time_module);
    Py_CLEAR(w->os_module);
    Py_CLEAR(w->cfg_preopens);
    Py_CLEAR(w->cfg_readonly);
    for (uint32_t i = 0; i < w->nentries; i++) Py_CLEAR(w->entries[i].listing);
}

static inline void wasmext_wasi_bind(wasmext_wasi *w, wasm_rt_memory_t *memory) { w->memory = memory; }

/* ---- the memory of the instance (little-endian, as WebAssembly says) -------------------------------------------------- */

static inline int wasi_in_memory(const wasmext_wasi *w, uint32_t ptr, uint64_t len) {
    return w->memory != NULL && (uint64_t)ptr + len <= w->memory->size;
}

static inline int wasi_put_u8(wasmext_wasi *w, uint32_t ptr, uint8_t v) {
    if (!wasi_in_memory(w, ptr, 1)) return 0;
    w->memory->data[ptr] = v;
    return 1;
}

static inline int wasi_put_u16(wasmext_wasi *w, uint32_t ptr, uint16_t v) {
    if (!wasi_in_memory(w, ptr, 2)) return 0;
    w->memory->data[ptr] = (uint8_t)v;
    w->memory->data[ptr + 1] = (uint8_t)(v >> 8);
    return 1;
}

static inline int wasi_put_u32(wasmext_wasi *w, uint32_t ptr, uint32_t v) {
    if (!wasi_in_memory(w, ptr, 4)) return 0;
    for (int i = 0; i < 4; i++) w->memory->data[ptr + i] = (uint8_t)(v >> (8 * i));
    return 1;
}

static inline int wasi_put_u64(wasmext_wasi *w, uint32_t ptr, uint64_t v) {
    if (!wasi_in_memory(w, ptr, 8)) return 0;
    for (int i = 0; i < 8; i++) w->memory->data[ptr + i] = (uint8_t)(v >> (8 * i));
    return 1;
}

static inline int wasi_get_u32(const wasmext_wasi *w, uint32_t ptr, uint32_t *v) {
    if (!wasi_in_memory(w, ptr, 4)) return 0;
    *v = 0;
    for (int i = 0; i < 4; i++) *v |= (uint32_t)w->memory->data[ptr + i] << (8 * i);
    return 1;
}

/* ---- errors of Python ------------------------------------------------------------------------------------------------ */

/* An OSError becomes the errno of WASI that its errno says; anything else is a trap of the call, with the exception still set. */
static inline uint32_t wasi_python_error(int *trapped) {
    if (PyErr_ExceptionMatches(PyExc_BrokenPipeError)) {
        PyErr_Clear();
        return WASI_E_PIPE;
    }
    if (PyErr_ExceptionMatches(PyExc_OSError)) {
        PyObject *type, *value, *traceback;
        PyErr_Fetch(&type, &value, &traceback);
        PyErr_NormalizeException(&type, &value, &traceback);
        uint32_t code = WASI_E_IO;
        PyObject *number = value ? PyObject_GetAttrString(value, "errno") : NULL;
        if (number != NULL && PyLong_Check(number)) code = wasi_errno((int)PyLong_AsLong(number));
        PyErr_Clear();
        Py_XDECREF(number);
        Py_XDECREF(type);
        Py_XDECREF(value);
        Py_XDECREF(traceback);
        return code;
    }
    *trapped = 1;
    return 0;
}

#define WASI_STATE(s) wasmext_wasi *w = (wasmext_wasi *)(s)

/* ---- arguments and environment --------------------------------------------------------------------------------------- */

static inline uint32_t wasi_strings_sizes(wasmext_wasi *w, uint32_t count, size_t size, uint32_t count_ptr, uint32_t size_ptr) {
    if (!wasi_put_u32(w, count_ptr, count) || !wasi_put_u32(w, size_ptr, (uint32_t)size)) return WASI_E_FAULT;
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_strings_get(wasmext_wasi *w, const char *buf, size_t size, uint32_t count, uint32_t table, uint32_t out) {
    if (!wasi_in_memory(w, out, size) || !wasi_in_memory(w, table, (uint64_t)count * 4)) return WASI_E_FAULT;
    memcpy(w->memory->data + out, buf, size);
    size_t offset = 0;
    for (uint32_t i = 0; i < count; i++) {
        wasi_put_u32(w, table + 4 * i, out + (uint32_t)offset);
        offset += strlen(buf + offset) + 1;
    }
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_args_sizes_get(void *s, uint32_t argc, uint32_t size, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    return wasi_strings_sizes(w, w->argc, w->args_size, argc, size);
}

static inline uint32_t wasi_args_get(void *s, uint32_t argv, uint32_t buf, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    return wasi_strings_get(w, w->args, w->args_size, w->argc, argv, buf);
}

static inline uint32_t wasi_environ_sizes_get(void *s, uint32_t count, uint32_t size, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    return wasi_strings_sizes(w, w->envc, w->env_size, count, size);
}

static inline uint32_t wasi_environ_get(void *s, uint32_t environ_, uint32_t buf, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    return wasi_strings_get(w, w->env, w->env_size, w->envc, environ_, buf);
}

/* ---- wasi_clocks and random bytes (through Python: the sources differ between systems) --------------------------------------- */

static const struct { const char *function, *info; } wasi_clocks[] = {
    {"time_ns", "time"}, {"monotonic_ns", "monotonic"}, {"process_time_ns", "process_time"}, {"thread_time_ns", "thread_time"},
};

static inline uint32_t wasi_clock_res_get(void *s, uint32_t id, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    if (id > 3) return WASI_E_INVAL;
    PyObject *time = wasi_module_of(&w->time_module, "time");
    PyObject *info = time ? PyObject_CallMethod(time, "get_clock_info", "s", wasi_clocks[id].info) : NULL;
    PyObject *res = info ? PyObject_GetAttrString(info, "resolution") : NULL;
    Py_XDECREF(info);
    double seconds = res ? PyFloat_AsDouble(res) : -1.0;
    Py_XDECREF(res);
    if (seconds < 0 && PyErr_Occurred()) return wasi_python_error(trapped);
    uint64_t ns = seconds * 1e9 < 1.0 ? 1 : (uint64_t)(seconds * 1e9);
    return wasi_put_u64(w, ptr, ns) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

static inline uint32_t wasi_clock_time_get(void *s, uint32_t id, uint64_t precision, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    (void)precision;
    if (id > 3) return WASI_E_INVAL;
    PyObject *time = wasi_module_of(&w->time_module, "time");
    PyObject *value = time ? PyObject_CallMethod(time, wasi_clocks[id].function, NULL) : NULL;
    if (value == NULL) return wasi_python_error(trapped);
    unsigned long long ns = PyLong_AsUnsignedLongLongMask(value);
    Py_DECREF(value);
    return wasi_put_u64(w, ptr, ns) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

static inline uint32_t wasi_random_get(void *s, uint32_t buf, uint32_t size, int *trapped) {
    WASI_STATE(s);
    if (!wasi_in_memory(w, buf, size)) return WASI_E_FAULT;
    if (size == 0) return WASI_E_SUCCESS;
    PyObject *os = wasi_module_of(&w->os_module, "os");
    PyObject *bytes = os ? PyObject_CallMethod(os, "urandom", "I", size) : NULL;
    if (bytes == NULL) return wasi_python_error(trapped);
    char *data;
    Py_ssize_t len;
    if (PyBytes_AsStringAndSize(bytes, &data, &len) < 0 || (uint64_t)len != size) {
        Py_DECREF(bytes);
        return wasi_python_error(trapped);
    }
    memcpy(w->memory->data + buf, data, (size_t)len);
    Py_DECREF(bytes);
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_sched_yield(void *s, int *trapped) {
    (void)s;
    (void)trapped;
    return WASI_E_SUCCESS;
}

static inline void wasi_proc_exit(void *s, uint32_t code, int *trapped) {
    WASI_STATE(s);
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

/* ---- descriptors ----------------------------------------------------------------------------------------------------- */

static inline wasi_entry *wasi_entry_of(wasmext_wasi *w, uint32_t fd) {
    return fd < w->nentries && w->entries[fd].kind != WASI_K_NONE ? &w->entries[fd] : NULL;
}

/* the real path of a directory descriptor: root, or root/rel; new memory */
static inline char *wasi_join(const char *root, const char *rel) {
    size_t a = strlen(root), b = strlen(rel);
    char *out = (char *)PyMem_Malloc(a + b + 2);
    if (out == NULL) return NULL;
    memcpy(out, root, a);
    if (b) {
        out[a] = '/';
        memcpy(out + a + 1, rel, b);
        out[a + 1 + b] = '\0';
    } else {
        out[a] = '\0';
    }
    return out;
}

/* ---- paths: the program's name, below a directory, in the real file system ------------------------------------------- */

/* whether `real` (a path from realpath) is the preopen `root` or below it */
static inline int wasi_contained(wasmext_wasi *w, const char *root, const char *real) {
    PyObject *os = wasi_module_of(&w->os_module, "os");
    PyObject *path = os ? PyObject_GetAttrString(os, "path") : NULL;
    PyObject *a = path ? PyObject_CallMethod(path, "normcase", "y", root) : NULL;
    PyObject *b = path ? PyObject_CallMethod(path, "normcase", "y", real) : NULL;
    Py_XDECREF(path);
    int inside = 0;
    if (a != NULL && b != NULL && PyBytes_Check(a) && PyBytes_Check(b)) {
        Py_ssize_t la = PyBytes_Size(a), lb = PyBytes_Size(b);
        const char *pa = PyBytes_AsString(a), *pb = PyBytes_AsString(b);
        inside = lb >= la && memcmp(pa, pb, (size_t)la) == 0 && (lb == la || pb[la] == '/' || pb[la] == '\\');
    }
    PyErr_Clear();
    Py_XDECREF(a);
    Py_XDECREF(b);
    return inside;
}

/* The path the program gave, below the directory `dir`: its place in the file system. 0, with `*full` and `*newrel` in new memory
   (the caller frees them), or an errno of WASI: a name that leaves the directory ("..", an absolute name, a symbolic link that
   points out) is NOTCAPABLE. The check and the use are two steps, so another process that changes the directory in between
   is not stopped (FEATURES.md, "Design: WASI"). */
static inline uint32_t wasi_resolve(wasmext_wasi *w, wasi_entry *dir, uint32_t ptr, uint32_t len, int follow, char **full,
                                    char **newrel) {
    *full = NULL;
    *newrel = NULL;
    if (dir->kind != WASI_K_DIR) return WASI_E_NOTDIR;
    if (!wasi_in_memory(w, ptr, len)) return WASI_E_FAULT;
    const unsigned char *given = w->memory->data + ptr;
    if (len == 0) return WASI_E_NOENT;
    if (memchr(given, 0, len) != NULL) return WASI_E_INVAL;
    if (given[0] == '/') return WASI_E_NOTCAPABLE;
    size_t rel_len = strlen(dir->rel);
    char *joined = (char *)PyMem_Malloc(rel_len + 1 + len + 1);
    char *out = (char *)PyMem_Malloc(rel_len + 1 + len + 1);
    if (joined == NULL || out == NULL) {
        PyMem_Free(joined);
        PyMem_Free(out);
        return WASI_E_NOMEM;
    }
    memcpy(joined, dir->rel, rel_len);
    joined[rel_len] = '/';
    memcpy(joined + rel_len + 1, given, len);
    joined[rel_len + 1 + len] = '\0';
    size_t n = 0;
    char *cursor = joined;
    int outside = 0;
    for (;;) {
        char *end = strchr(cursor, '/');
        size_t tlen = end ? (size_t)(end - cursor) : strlen(cursor);
        if (tlen == 2 && cursor[0] == '.' && cursor[1] == '.') {
            if (n == 0) {
                outside = 1;
                break;
            }
            while (n > 0 && out[n - 1] != '/') n--;
            if (n > 0) n--;
        } else if (tlen > 0 && !(tlen == 1 && cursor[0] == '.')) {
            if (n) out[n++] = '/';
            memcpy(out + n, cursor, tlen);
            n += tlen;
        }
        if (end == NULL) break;
        cursor = end + 1;
    }
    PyMem_Free(joined);
    if (outside) {
        PyMem_Free(out);
        return WASI_E_NOTCAPABLE;
    }
    out[n] = '\0';
    char *path = wasi_join(dir->root, out);
    if (path == NULL) {
        PyMem_Free(out);
        return WASI_E_NOMEM;
    }
    if (n > 0) {  /* a link in the path may point out of the preopen: the real path of what is used must be inside it */
        char *check = wasi_copy(path, strlen(path));
        if (check != NULL && !follow) {  /* the last name is not followed: its directory is what counts */
            char *slash = strrchr(check, '/');
            if (slash != NULL && slash > check + strlen(dir->root) - 1) *slash = '\0';
            else strcpy(check, dir->root);
        }
        PyObject *os = wasi_module_of(&w->os_module, "os");
        PyObject *ospath = os ? PyObject_GetAttrString(os, "path") : NULL;
        PyObject *real = ospath && check ? PyObject_CallMethod(ospath, "realpath", "y", check) : NULL;
        Py_XDECREF(ospath);
        int inside = 0;
        if (real != NULL && PyBytes_Check(real)) inside = wasi_contained(w, dir->root, PyBytes_AsString(real));
        PyErr_Clear();
        Py_XDECREF(real);
        PyMem_Free(check);
        if (!inside) {
            PyMem_Free(out);
            PyMem_Free(path);
            return WASI_E_NOTCAPABLE;
        }
    }
    *full = path;
    *newrel = out;
    return WASI_E_SUCCESS;
}

/* ---- the standard streams (through Python by default, so that the order against print() and a capture in a notebook or a test
   are right) --------------------------------------------------------------------------------------------------------- */

/* the binary side of sys.stdout (after flushing its text layer), or the object the caller gave */
static inline int wasi_write_bytes(wasmext_wasi *w, uint32_t fd, const char *data, Py_ssize_t size) {
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

static inline uint32_t wasi_write_std(wasmext_wasi *w, uint32_t fd, uint32_t iovs, uint32_t count, uint32_t nwritten,
                                      int *trapped) {
    if (!wasi_in_memory(w, iovs, (uint64_t)count * 8)) return WASI_E_FAULT;
    uint64_t total = 0;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t base = 0, len = 0;
        wasi_get_u32(w, iovs + 8 * i, &base);
        wasi_get_u32(w, iovs + 8 * i + 4, &len);
        if (!wasi_in_memory(w, base, len)) return WASI_E_FAULT;
        if (len == 0) continue;
        if (wasi_write_bytes(w, fd, (const char *)w->memory->data + base, (Py_ssize_t)len) < 0) return wasi_python_error(trapped);
        total += len;
    }
    return wasi_put_u32(w, nwritten, (uint32_t)total) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

/* up to `size` bytes of stdin, a new bytes object (empty at the end), or NULL with an exception */
static inline PyObject *wasi_read_bytes(wasmext_wasi *w, Py_ssize_t size) {
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

static inline uint32_t wasi_read_std(wasmext_wasi *w, uint32_t iovs, uint32_t count, uint32_t nread, int *trapped) {
    if (!wasi_in_memory(w, iovs, (uint64_t)count * 8)) return WASI_E_FAULT;
    uint32_t base = 0, len = 0;
    for (uint32_t i = 0; i < count; i++) {  /* the first buffer that is not empty: a short read is allowed */
        wasi_get_u32(w, iovs + 8 * i, &base);
        wasi_get_u32(w, iovs + 8 * i + 4, &len);
        if (len) break;
    }
    if (!wasi_in_memory(w, base, len)) return WASI_E_FAULT;
    uint32_t got = 0;
    if (len) {
        PyObject *bytes = wasi_read_bytes(w, (Py_ssize_t)len);
        if (bytes == NULL) return wasi_python_error(trapped);
        char *data;
        Py_ssize_t n;
        if (PyBytes_AsStringAndSize(bytes, &data, &n) < 0 || (uint64_t)n > len) {
            Py_DECREF(bytes);
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "stdin gave more bytes than were asked for");
            return wasi_python_error(trapped);
        }
        memcpy(w->memory->data + base, data, (size_t)n);
        got = (uint32_t)n;
        Py_DECREF(bytes);
    }
    return wasi_put_u32(w, nread, got) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

/* ---- reading, seeking, closing ---------------------------------------------------------------------------------------- */

static inline uint32_t wasi_fd_write(void *s, uint32_t fd, uint32_t iovs, uint32_t count, uint32_t nwritten, int *trapped) {
    WASI_STATE(s);
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL || e->kind == WASI_K_DIR) return e == NULL ? WASI_E_BADF : WASI_E_ISDIR;
    if (e->kind == WASI_K_STD) return fd == 0 ? WASI_E_BADF : wasi_write_std(w, fd, iovs, count, nwritten, trapped);
    if (!(e->rights & WASI_R_FD_WRITE)) return WASI_E_NOTCAPABLE;
    return WASI_E_NOSYS;  /* writing to a file: the second stage */
}

static inline uint32_t wasi_fd_read(void *s, uint32_t fd, uint32_t iovs, uint32_t count, uint32_t nread, int *trapped) {
    WASI_STATE(s);
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    if (e->kind == WASI_K_STD) return fd == 0 ? wasi_read_std(w, iovs, count, nread, trapped) : WASI_E_BADF;
    if (e->kind == WASI_K_DIR) return WASI_E_ISDIR;
    if (!(e->rights & WASI_R_FD_READ)) return WASI_E_NOTCAPABLE;
    if (!wasi_in_memory(w, iovs, (uint64_t)count * 8)) return WASI_E_FAULT;
    uint64_t total = 0;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t base = 0, len = 0;
        wasi_get_u32(w, iovs + 8 * i, &base);
        wasi_get_u32(w, iovs + 8 * i + 4, &len);
        if (!wasi_in_memory(w, base, len)) return WASI_E_FAULT;
        if (len == 0) continue;
        long long n = WASI_READ(e->osfd, w->memory->data + base, len);  /* no interpreter: this is the part that moves the data */
        if (n < 0) {
            if (total) break;  /* what was read is reported; the error comes with the next call */
            return wasi_errno(errno);
        }
        total += (uint64_t)n;
        if ((uint32_t)n < len) break;
    }
    return wasi_put_u32(w, nread, (uint32_t)total) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

static inline uint32_t wasi_seek_native(wasmext_wasi *w, uint32_t fd, int64_t offset, int native, uint32_t ptr, uint64_t right) {
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    if (e->kind == WASI_K_STD) return WASI_E_SPIPE;
    if (e->kind != WASI_K_FILE) return WASI_E_BADF;
    if (!(e->rights & right)) return WASI_E_NOTCAPABLE;
    long long pos = WASI_LSEEK(e->osfd, offset, native);
    if (pos < 0) return wasi_errno(errno);
    return wasi_put_u64(w, ptr, (uint64_t)pos) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

/* the order of whence in this snapshot: set, cur, end */
static inline uint32_t wasi_fd_seek(void *s, uint32_t fd, uint64_t offset, uint32_t whence, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    static const int native[3] = {SEEK_SET, SEEK_CUR, SEEK_END};
    if (whence > 2) return WASI_E_INVAL;
    return wasi_seek_native(w, fd, (int64_t)offset, native[whence], ptr, WASI_R_FD_SEEK);
}

static inline uint32_t wasi_fd_tell(void *s, uint32_t fd, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    return wasi_seek_native(w, fd, 0, SEEK_CUR, ptr, WASI_R_FD_TELL);
}

static inline uint32_t wasi_fd_close(void *s, uint32_t fd, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    if (e->kind == WASI_K_STD) return WASI_E_SUCCESS;  /* the standard streams stay */
    return wasi_release(e) == 0 ? WASI_E_SUCCESS : wasi_errno(errno);
}

static inline uint32_t wasi_fd_renumber(void *s, uint32_t from, uint32_t to, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    wasi_entry *a = wasi_entry_of(w, from), *b = wasi_entry_of(w, to);
    if (a == NULL || b == NULL) return WASI_E_BADF;
    if (a->kind == WASI_K_STD || b->kind == WASI_K_STD) return WASI_E_NOTSUP;
    if (from == to) return WASI_E_SUCCESS;
    wasi_release(b);
    *b = *a;
    memset(a, 0, sizeof *a);
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_fd_advise(void *s, uint32_t fd, uint64_t offset, uint64_t length, uint32_t advice, int *trapped) {
    WASI_STATE(s);
    (void)offset;
    (void)length;
    (void)advice;
    (void)trapped;
    wasi_entry *e = wasi_entry_of(w, fd);
    return e != NULL && e->kind == WASI_K_FILE ? WASI_E_SUCCESS : WASI_E_BADF;  /* a hint: nothing is done with it */
}

static inline uint32_t wasi_fd_fdstat_get(void *s, uint32_t fd, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    uint8_t filetype = e->kind == WASI_K_STD ? WASI_FT_CHAR : e->filetype;
    uint64_t base = e->kind == WASI_K_STD ? (fd == 0 ? WASI_RIGHTS_STDIN : WASI_RIGHTS_STDOUT) : e->rights;
    if (!wasi_in_memory(w, ptr, 24)) return WASI_E_FAULT;
    memset(w->memory->data + ptr, 0, 24);
    wasi_put_u8(w, ptr, filetype);
    wasi_put_u16(w, ptr + 2, e->flags);
    wasi_put_u64(w, ptr + 8, base);
    wasi_put_u64(w, ptr + 16, e->inheriting);
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_fd_prestat_get(void *s, uint32_t fd, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL || e->preopen == NULL) return WASI_E_BADF;  /* the end of the list the program walks */
    if (!wasi_in_memory(w, ptr, 8)) return WASI_E_FAULT;
    memset(w->memory->data + ptr, 0, 8);  /* the type of a preopen: a directory, 0 */
    wasi_put_u32(w, ptr + 4, (uint32_t)e->preopen_len);
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_fd_prestat_dir_name(void *s, uint32_t fd, uint32_t path, uint32_t size, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL || e->preopen == NULL) return WASI_E_BADF;
    if (size < e->preopen_len) return WASI_E_NAMETOOLONG;
    if (!wasi_in_memory(w, path, e->preopen_len)) return WASI_E_FAULT;
    memcpy(w->memory->data + path, e->preopen, e->preopen_len);
    return WASI_E_SUCCESS;
}

/* ---- what a file or a directory is (os.stat, through Python) --------------------------------------------------------- */

static inline uint8_t wasi_filetype_of(unsigned long mode) {
    switch (mode & 0170000UL) {  /* the bits of st_mode, the same on every system Python runs on */
    case 0040000UL: return WASI_FT_DIR;
    case 0100000UL: return WASI_FT_REGULAR;
    case 0120000UL: return WASI_FT_SYMLINK;
    case 0020000UL: return WASI_FT_CHAR;
    case 0060000UL: return WASI_FT_BLOCK;
    case 0140000UL: return WASI_FT_SOCKET_STREAM;
    default: return WASI_FT_UNKNOWN;
    }
}

static inline unsigned long long wasi_attr(PyObject *obj, const char *name, int *ok) {
    PyObject *value = PyObject_GetAttrString(obj, name);
    if (value == NULL) {
        *ok = 0;
        return 0;
    }
    unsigned long long out = PyLong_AsUnsignedLongLongMask(value);
    Py_DECREF(value);
    return out;
}

/* the filestat of a stat_result; `legacy` is the first snapshot, which has a 32-bit link count and 56 bytes */
static inline uint32_t wasi_put_filestat(wasmext_wasi *w, uint32_t ptr, PyObject *st, int legacy, int *trapped) {
    int ok = 1;
    unsigned long long dev = wasi_attr(st, "st_dev", &ok), ino = wasi_attr(st, "st_ino", &ok), mode = wasi_attr(st, "st_mode", &ok);
    unsigned long long nlink = wasi_attr(st, "st_nlink", &ok), size = wasi_attr(st, "st_size", &ok);
    unsigned long long atime = wasi_attr(st, "st_atime_ns", &ok), mtime = wasi_attr(st, "st_mtime_ns", &ok);
    unsigned long long ctime = wasi_attr(st, "st_ctime_ns", &ok);
    if (!ok) return wasi_python_error(trapped);
    size_t total = legacy ? 56 : 64;
    if (!wasi_in_memory(w, ptr, total)) return WASI_E_FAULT;
    memset(w->memory->data + ptr, 0, total);
    wasi_put_u64(w, ptr, dev);
    wasi_put_u64(w, ptr + 8, ino);
    wasi_put_u8(w, ptr + 16, wasi_filetype_of((unsigned long)mode));
    if (legacy) {
        wasi_put_u32(w, ptr + 20, (uint32_t)nlink);
        wasi_put_u64(w, ptr + 24, size);
        wasi_put_u64(w, ptr + 32, atime);
        wasi_put_u64(w, ptr + 40, mtime);
        wasi_put_u64(w, ptr + 48, ctime);
    } else {
        wasi_put_u64(w, ptr + 24, nlink);
        wasi_put_u64(w, ptr + 32, size);
        wasi_put_u64(w, ptr + 40, atime);
        wasi_put_u64(w, ptr + 48, mtime);
        wasi_put_u64(w, ptr + 56, ctime);
    }
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_filestat_of_fd(wasmext_wasi *w, uint32_t fd, uint32_t ptr, int legacy, int *trapped) {
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    if (e->kind == WASI_K_STD) {  /* a terminal or a pipe: nothing to say but what it is */
        size_t total = legacy ? 56 : 64;
        if (!wasi_in_memory(w, ptr, total)) return WASI_E_FAULT;
        memset(w->memory->data + ptr, 0, total);
        wasi_put_u8(w, ptr + 16, WASI_FT_CHAR);
        return WASI_E_SUCCESS;
    }
    if (!(e->rights & WASI_R_FD_FILESTAT_GET)) return WASI_E_NOTCAPABLE;
    PyObject *os = wasi_module_of(&w->os_module, "os"), *st;
    if (os == NULL) return wasi_python_error(trapped);
    if (e->kind == WASI_K_FILE) {
        st = PyObject_CallMethod(os, "fstat", "i", e->osfd);
    } else {
        char *path = wasi_join(e->root, e->rel);
        if (path == NULL) return WASI_E_NOMEM;
        st = PyObject_CallMethod(os, "stat", "y", path);
        PyMem_Free(path);
    }
    if (st == NULL) return wasi_python_error(trapped);
    uint32_t rc = wasi_put_filestat(w, ptr, st, legacy, trapped);
    Py_DECREF(st);
    return rc;
}

static inline uint32_t wasi_filestat_of_path(wasmext_wasi *w, uint32_t fd, uint32_t flags, uint32_t path, uint32_t len,
                                             uint32_t ptr, int legacy, int *trapped) {
    wasi_entry *dir = wasi_entry_of(w, fd);
    if (dir == NULL) return WASI_E_BADF;
    if (!(dir->rights & WASI_R_PATH_FILESTAT_GET)) return WASI_E_NOTCAPABLE;
    int follow = (flags & WASI_LOOKUP_FOLLOW) != 0;
    char *full, *rel;
    uint32_t rc = wasi_resolve(w, dir, path, len, follow, &full, &rel);
    if (rc) return rc;
    PyMem_Free(rel);
    PyObject *os = wasi_module_of(&w->os_module, "os");
    PyObject *st = os ? PyObject_CallMethod(os, follow ? "stat" : "lstat", "y", full) : NULL;
    PyMem_Free(full);
    if (st == NULL) return wasi_python_error(trapped);
    rc = wasi_put_filestat(w, ptr, st, legacy, trapped);
    Py_DECREF(st);
    return rc;
}

static inline uint32_t wasi_fd_filestat_get(void *s, uint32_t fd, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    return wasi_filestat_of_fd(w, fd, ptr, 0, trapped);
}

static inline uint32_t wasi_path_filestat_get(void *s, uint32_t fd, uint32_t flags, uint32_t path, uint32_t len, uint32_t ptr,
                                              int *trapped) {
    WASI_STATE(s);
    return wasi_filestat_of_path(w, fd, flags, path, len, ptr, 0, trapped);
}

/* ---- directories ---------------------------------------------------------------------------------------------------- */

/* the entries of a directory, with "." and "..": a list of (name, inode, type); NULL with an exception */
static inline PyObject *wasi_list_dir(wasmext_wasi *w, const char *path) {
    PyObject *os = wasi_module_of(&w->os_module, "os");
    PyObject *names = os ? PyObject_CallMethod(os, "listdir", "y", path) : NULL;
    if (names == NULL) return NULL;
    PyObject *listing = PyList_New(0), *all = PyList_New(0);
    if (listing == NULL || all == NULL || PyList_Sort(names) < 0) goto fail;
    PyObject *dot = PyBytes_FromString("."), *dotdot = PyBytes_FromString("..");
    int ok = dot && dotdot && PyList_Append(all, dot) == 0 && PyList_Append(all, dotdot) == 0;
    Py_XDECREF(dot);
    Py_XDECREF(dotdot);
    if (!ok) goto fail;
    Py_ssize_t count = PyList_Size(names);
    for (Py_ssize_t i = 0; i < count; i++)
        if (PyList_Append(all, PyList_GetItem(names, i)) < 0) goto fail;
    count = PyList_Size(all);
    for (Py_ssize_t i = 0; i < count; i++) {
        PyObject *name = PyList_GetItem(all, i);  /* borrowed */
        char *full = wasi_join(path, PyBytes_AsString(name));
        if (full == NULL) {
            PyErr_NoMemory();
            goto fail;
        }
        PyObject *st = PyObject_CallMethod(os, "lstat", "y", full);
        PyMem_Free(full);
        if (st == NULL) {  /* gone since the listing was made */
            if (!PyErr_ExceptionMatches(PyExc_OSError)) goto fail;
            PyErr_Clear();
            continue;
        }
        int attr_ok = 1;
        unsigned long long ino = wasi_attr(st, "st_ino", &attr_ok), mode = wasi_attr(st, "st_mode", &attr_ok);
        Py_DECREF(st);
        if (!attr_ok) goto fail;
        PyObject *row = Py_BuildValue("(OKi)", name, ino, (int)wasi_filetype_of((unsigned long)mode));
        if (row == NULL || PyList_Append(listing, row) < 0) {
            Py_XDECREF(row);
            goto fail;
        }
        Py_DECREF(row);
    }
    Py_DECREF(names);
    Py_DECREF(all);
    return listing;
fail:
    Py_DECREF(names);
    Py_XDECREF(all);
    Py_XDECREF(listing);
    return NULL;
}

static inline uint32_t wasi_fd_readdir(void *s, uint32_t fd, uint32_t buf, uint32_t size, uint64_t cookie, uint32_t used,
                                       int *trapped) {
    WASI_STATE(s);
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    if (e->kind != WASI_K_DIR) return WASI_E_NOTDIR;
    if (!(e->rights & WASI_R_FD_READDIR)) return WASI_E_NOTCAPABLE;
    if (!wasi_in_memory(w, buf, size)) return WASI_E_FAULT;
    if (cookie == 0 || e->listing == NULL) {
        char *path = wasi_join(e->root, e->rel);
        if (path == NULL) return WASI_E_NOMEM;
        PyObject *listing = wasi_list_dir(w, path);
        PyMem_Free(path);
        if (listing == NULL) return wasi_python_error(trapped);
        PyObject *old = e->listing;
        e->listing = listing;
        Py_XDECREF(old);
    }
    Py_ssize_t count = PyList_Size(e->listing);
    uint32_t at = 0;
    for (Py_ssize_t i = (Py_ssize_t)cookie; i < count && at < size; i++) {
        PyObject *row = PyList_GetItem(e->listing, i);  /* borrowed */
        PyObject *name = PyTuple_GetItem(row, 0);
        unsigned long long ino = PyLong_AsUnsignedLongLongMask(PyTuple_GetItem(row, 1));
        long type = PyLong_AsLong(PyTuple_GetItem(row, 2));
        char *text;
        Py_ssize_t name_len;
        if (PyBytes_AsStringAndSize(name, &text, &name_len) < 0) return wasi_python_error(trapped);
        unsigned char entry[24];
        memset(entry, 0, sizeof entry);
        uint64_t next = (uint64_t)i + 1;
        for (int k = 0; k < 8; k++) entry[k] = (unsigned char)(next >> (8 * k));
        for (int k = 0; k < 8; k++) entry[8 + k] = (unsigned char)(ino >> (8 * k));
        for (int k = 0; k < 4; k++) entry[16 + k] = (unsigned char)((uint32_t)name_len >> (8 * k));
        entry[20] = (unsigned char)type;
        size_t room = size - at, part = room < sizeof entry ? room : sizeof entry;  /* the last entry may be cut short */
        memcpy(w->memory->data + buf + at, entry, part);
        at += (uint32_t)part;
        if (part < sizeof entry) break;
        room = size - at;
        part = room < (size_t)name_len ? room : (size_t)name_len;
        memcpy(w->memory->data + buf + at, text, part);
        at += (uint32_t)part;
    }
    return wasi_put_u32(w, used, at) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

/* ---- opening (reading: the first stage) ------------------------------------------------------------------------------- */

static inline uint32_t wasi_path_open(void *s, uint32_t fd, uint32_t dirflags, uint32_t path, uint32_t len, uint32_t oflags,
                                      uint64_t base, uint64_t inheriting, uint32_t fdflags, uint32_t out, int *trapped) {
    WASI_STATE(s);
    wasi_entry *dir = wasi_entry_of(w, fd);
    if (dir == NULL) return WASI_E_BADF;
    if (dir->kind != WASI_K_DIR) return WASI_E_NOTDIR;
    if ((oflags >> 4) != 0 || (fdflags >> 5) != 0) return WASI_E_INVAL;
    if (!(dir->rights & WASI_R_PATH_OPEN)) return WASI_E_NOTCAPABLE;
    int follow = (dirflags & WASI_LOOKUP_FOLLOW) != 0;
    base &= dir->inheriting & WASI_R_ALL;
    inheriting &= dir->inheriting & WASI_R_ALL;
    if (oflags & (WASI_O_CREAT | WASI_O_EXCL | WASI_O_TRUNC)) return WASI_E_NOSYS;  /* creating: the second stage */
    if (base & WASI_R_FD_WRITE) return WASI_E_NOSYS;                                /* writing: the second stage */
    char *full, *rel;
    uint32_t rc = wasi_resolve(w, dir, path, len, follow, &full, &rel);
    if (rc) return rc;
    PyObject *os = wasi_module_of(&w->os_module, "os");
    PyObject *st = os ? PyObject_CallMethod(os, follow ? "stat" : "lstat", "y", full) : NULL;
    if (st == NULL) {
        PyMem_Free(full);
        PyMem_Free(rel);
        return wasi_python_error(trapped);
    }
    int ok = 1;
    unsigned long long mode = wasi_attr(st, "st_mode", &ok);
    Py_DECREF(st);
    if (!ok) {
        PyMem_Free(full);
        PyMem_Free(rel);
        return wasi_python_error(trapped);
    }
    int64_t number = wasi_new_fd(w);
    if (number < 0) {
        PyMem_Free(full);
        PyMem_Free(rel);
        return WASI_E_NOMEM;
    }
    wasi_entry *e = &w->entries[number];
    memset(e, 0, sizeof *e);
    e->rights = base;
    e->inheriting = inheriting;
    e->flags = (uint16_t)fdflags;
    if (wasi_filetype_of((unsigned long)mode) == WASI_FT_DIR) {
        e->kind = WASI_K_DIR;
        e->filetype = WASI_FT_DIR;
        e->root = wasi_copy(dir->root, strlen(dir->root));
        e->rel = rel;
        PyMem_Free(full);
        if (e->root == NULL) {
            wasi_release(e);
            return WASI_E_NOMEM;
        }
    } else {
        PyMem_Free(rel);
        if (oflags & WASI_O_DIRECTORY) {
            PyMem_Free(full);
            return WASI_E_NOTDIR;
        }
        int flags = O_RDONLY;
#ifdef O_BINARY
        flags |= O_BINARY;
#endif
#ifdef O_NOFOLLOW
        if (!follow) flags |= O_NOFOLLOW;
#endif
        PyObject *opened = PyObject_CallMethod(os, "open", "yi", full, flags);
        PyMem_Free(full);
        if (opened == NULL) return wasi_python_error(trapped);
        long osfd = PyLong_AsLong(opened);
        Py_DECREF(opened);
        e->kind = WASI_K_FILE;
        e->osfd = (int)osfd;
        e->filetype = wasi_filetype_of((unsigned long)mode);
    }
    return wasi_put_u32(w, out, (uint32_t)number) ? WASI_E_SUCCESS : (wasi_release(e), WASI_E_FAULT);
}

/* ---- not yet: ENOSYS, as the specification allows (ENOTSOCK for the sockets, which will not be there) --------------------- */

#define WASI_NOT_YET(name, code, ...) \
    static inline uint32_t wasi_##name(void *s, __VA_ARGS__, int *trapped) { \
        (void)s; \
        (void)trapped; \
        return code; \
    }

WASI_NOT_YET(proc_raise, WASI_E_NOSYS, uint32_t a)
WASI_NOT_YET(poll_oneoff, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d)
WASI_NOT_YET(fd_pread, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint64_t d, uint32_t e)
WASI_NOT_YET(fd_pwrite, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint64_t d, uint32_t e)
WASI_NOT_YET(fd_allocate, WASI_E_NOSYS, uint32_t a, uint64_t b, uint64_t c)
WASI_NOT_YET(fd_datasync, WASI_E_NOSYS, uint32_t a)
WASI_NOT_YET(fd_sync, WASI_E_NOSYS, uint32_t a)
WASI_NOT_YET(fd_fdstat_set_flags, WASI_E_NOSYS, uint32_t a, uint32_t b)
WASI_NOT_YET(fd_fdstat_set_rights, WASI_E_NOSYS, uint32_t a, uint64_t b, uint64_t c)
WASI_NOT_YET(fd_filestat_set_size, WASI_E_NOSYS, uint32_t a, uint64_t b)
WASI_NOT_YET(fd_filestat_set_times, WASI_E_NOSYS, uint32_t a, uint64_t b, uint64_t c, uint32_t d)
WASI_NOT_YET(path_create_directory, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c)
WASI_NOT_YET(path_filestat_set_times, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint64_t e, uint64_t f, uint32_t g)
WASI_NOT_YET(path_link, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f, uint32_t g)
WASI_NOT_YET(path_readlink, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f)
WASI_NOT_YET(path_remove_directory, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c)
WASI_NOT_YET(path_rename, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f)
WASI_NOT_YET(path_symlink, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e)
WASI_NOT_YET(path_unlink_file, WASI_E_NOSYS, uint32_t a, uint32_t b, uint32_t c)
WASI_NOT_YET(sock_accept, WASI_E_NOTSOCK, uint32_t a, uint32_t b, uint32_t c)
WASI_NOT_YET(sock_recv, WASI_E_NOTSOCK, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f)
WASI_NOT_YET(sock_send, WASI_E_NOTSOCK, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e)
WASI_NOT_YET(sock_shutdown, WASI_E_NOTSOCK, uint32_t a, uint32_t b)

#endif
