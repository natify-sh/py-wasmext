/* The core of WASI 0.1 that `wasi_snapshot_preview1` and `wasi_unstable` (the first snapshot) share: the state of an instance and a
   function `wasi_<name>` for each call of the specification. Header only, included by wasi_preview1.h and wasi_unstable.h; the
   functions are `static inline`, so those the module does not import are not in the object. A module needs nothing of wasmext
   when it runs. See "Design: WASI" and "Design: C first, the seams" in FEATURES.md.

   There is no Python in this file: what the host decides (the standard streams, the clocks, the random bytes, the sleep, the end of
   the program) comes through the hooks of `wasmext_wasi_config`, and where a hook is absent the system's own is used. The host that
   has Python is wasi_python.h. Only the files of Windows, until they are native (stage 3 of the plan), come through Python:
   on Windows the file backend is wasi_files_win32.h (Win32 only); with WASMEXT_WASI_PYTHON_FS it is that of wasi_python.h, which must then be included as well.

   First stage: arguments, environment, clocks, random bytes, the standard streams, proc_exit. The calls of the file system answer
   ENOSYS (the descriptors beyond 2 are not open, so BADF where the specification asks for it). Written from the specification
   (the witx files of the wasi-0.1 branch of WebAssembly/WASI).

   A WASI call is `uint32_t wasi_<name>(void *state, parameters..., int *trapped)` (proc_exit returns nothing): a trap is reported
   through `trapped`, and the host knows what it was (Python: the exception it set). `wasmext_wasi_create` makes the state.

   The two snapshots differ in four things (the order of `whence`, one right less, a 32-bit link count in `filestat`, an extra
   `identifier` in a clock subscription) and in `sock_accept`, which the first one has not. None of the calls built so far reads or
   writes them, so the same function serves both; the day one does, wasi_unstable.h defines `wasi_unstable_<name>`, which the glue
   then calls for it. */
#ifndef WASMEXT_WASI_CORE_H
#define WASMEXT_WASI_CORE_H

#ifndef _WIN32
#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1  /* what the headers of Python set, for a host that does not include them */
#endif
#ifndef _DARWIN_C_SOURCE
#define _DARWIN_C_SOURCE 1
#endif
#endif
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#ifdef _WIN32
#include <io.h>
#define WASI_READ(fd, buf, n) _read((fd), (buf), (unsigned int)(n))
#define WASI_WRITE(fd, buf, n) _write((fd), (buf), (unsigned int)(n))
#define WASI_SYNC(fd) _commit(fd)
#define WASI_LSEEK(fd, off, whence) _lseeki64((fd), (off), (whence))
#define WASI_CLOSE(fd) _close(fd)
#else
#include <unistd.h>
#define WASI_READ(fd, buf, n) read((fd), (buf), (n))
#define WASI_WRITE(fd, buf, n) write((fd), (buf), (n))
#define WASI_SYNC(fd) fsync(fd)
#define WASI_LSEEK(fd, off, whence) lseek((fd), (off), (whence))
#define WASI_CLOSE(fd) close(fd)
#endif
#ifndef WASMEXT_WASI_PYTHON_FS
#define WASMEXT_WASI_PYTHON_FS 0  /* 1: the file backend of wasi_python.h (os.stat, os.open ...); on Windows the default is wasi_files_win32.h */
#endif
/* Windows has no openat and cannot open a directory: there (and with the backend of Python, which is made for it) a directory is a path */
#if WASMEXT_WASI_PYTHON_FS || defined(_WIN32)
#define WASI_DIRS_ARE_PATHS 1
#else
#define WASI_DIRS_ARE_PATHS 0
#endif
#include <stdlib.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#pragma comment(lib, "bcrypt")
#endif
#if !WASI_DIRS_ARE_PATHS
#include <dirent.h>
#include <sys/stat.h>
#endif
#include "wasm-rt.h"

/* the memory of the state: the C library's, so that a host without Python has nothing else to link */
#define WASI_MALLOC malloc
#define WASI_CALLOC calloc
#define WASI_REALLOC realloc
#define WASI_FREE free

#define WASI_LINK_MAX 4096  /* the most that path_readlink reads of a link */

typedef struct wasmext_wasi wasmext_wasi;

enum { WASI_END_NONE = 0, WASI_END_EXIT, WASI_END_SIGNAL, WASI_END_TRAP };


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
enum { WASI_FD_APPEND = 1, WASI_FD_DSYNC = 2, WASI_FD_NONBLOCK = 4, WASI_FD_RSYNC = 8, WASI_FD_SYNC = 16 };
/* the flags of the times: which of the two are set, to a value or to now */
enum { WASI_T_ATIM = 1, WASI_T_ATIM_NOW = 2, WASI_T_MTIM = 4, WASI_T_MTIM_NOW = 8 };
/* the rights: one bit each, in the order of the specification */
#define WASI_R(n) (UINT64_C(1) << (n))
#define WASI_R_FD_DATASYNC WASI_R(0)
#define WASI_R_FD_READ WASI_R(1)
#define WASI_R_FD_SEEK WASI_R(2)
#define WASI_R_FD_FDSTAT_SET_FLAGS WASI_R(3)
#define WASI_R_FD_SYNC WASI_R(4)
#define WASI_R_FD_TELL WASI_R(5)
#define WASI_R_FD_WRITE WASI_R(6)
#define WASI_R_FD_ALLOCATE WASI_R(8)
#define WASI_R_PATH_CREATE_DIRECTORY WASI_R(9)
#define WASI_R_PATH_CREATE_FILE WASI_R(10)
#define WASI_R_PATH_OPEN WASI_R(13)
#define WASI_R_FD_READDIR WASI_R(14)
#define WASI_R_PATH_FILESTAT_GET WASI_R(18)
#define WASI_R_PATH_FILESTAT_SET_SIZE WASI_R(19)
#define WASI_R_PATH_FILESTAT_SET_TIMES WASI_R(20)
#define WASI_R_FD_FILESTAT_GET WASI_R(21)
#define WASI_R_FD_FILESTAT_SET_SIZE WASI_R(22)
#define WASI_R_FD_FILESTAT_SET_TIMES WASI_R(23)
#define WASI_R_PATH_REMOVE_DIRECTORY WASI_R(25)
#define WASI_R_PATH_UNLINK_FILE WASI_R(26)
#define WASI_R_ALL ((UINT64_C(1) << 30) - 1)
/* the rights only a directory has: a program that asks for one of them along with the right to write (wasi-libc asks for all the
   rights there are, and so does the scratch directory of the test suite) may mean a directory, and then writing is not what is meant */
#define WASI_R_OF_DIRECTORY \
    (WASI_R(9) | WASI_R(10) | WASI_R(11) | WASI_R(12) | WASI_R(13) | WASI_R(14) | WASI_R(15) | WASI_R(16) | WASI_R(17) | WASI_R(18) | \
     WASI_R(19) | WASI_R(20) | WASI_R(24) | WASI_R(25) | WASI_R(26))
/* what changes something: taken away from a preopen that is read-only */
#define WASI_R_MUTATING \
    (WASI_R(0) | WASI_R(4) | WASI_R(6) | WASI_R(8) | WASI_R(9) | WASI_R(10) | WASI_R(11) | WASI_R(12) | WASI_R(16) | WASI_R(17) | \
     WASI_R(19) | WASI_R(20) | WASI_R(22) | WASI_R(23) | WASI_R(24) | WASI_R(25) | WASI_R(26))
/* the rights of the standard streams: fd_read, fd_fdstat_set_flags, fd_filestat_get, poll_fd_readwrite / fd_write, fd_sync ... */
#define WASI_RIGHTS_STDIN UINT64_C(0x820000a)
#define WASI_RIGHTS_STDOUT UINT64_C(0x8200058)

/* the names of a directory, as fd_readdir gives them */
typedef struct {
    uint64_t ino;
    uint32_t namelen;
    uint8_t type;
    char *name;
} wasi_dirent;
typedef struct {
    wasi_dirent *items;
    size_t count, capacity;
} wasi_dirlist;

/* an open descriptor: a standard stream, a file (an operating system descriptor) or a directory (a path: Windows cannot open one) */
enum { WASI_K_NONE = 0, WASI_K_STD, WASI_K_FILE, WASI_K_DIR };
typedef struct {
    uint8_t kind;
    uint8_t filetype;
    uint16_t flags;      /* fdflags */
    int osfd;            /* a file, or a directory when the system has openat (an operating system descriptor) */
    uint8_t owns_fd;     /* ... which is closed with the descriptor */
    uint64_t rights, inheriting;
    char *root;          /* a directory when the file system goes through Python: the real path of the preopen it is under */
    char *rel;           /* ... and its place below it, '/' between names, "" at the root */
    char *preopen;       /* the name the program sees, for a preopen */
    size_t preopen_len;
    wasi_dirlist *list;  /* fd_readdir: the names of the directory, made at cookie 0 */
} wasi_entry;


/* ---- what the host gives: the configuration and the hooks ---------------------------------------------------------------- */

/* The return of a hook: 0 is success; a positive number is an errno of WASI (WASI_E_*) that the program is given as it is;
   WASI_HOOK_TRAP is a trap of the call (the host keeps what it needs to report it: Python keeps its exception). */
#define WASI_HOOK_TRAP 0x10000

typedef struct {
    int (*stdin_read)(void *user, uint8_t *buf, size_t cap, size_t *got);
    int (*stdout_write)(void *user, int fd, const uint8_t *buf, size_t n);  /* fd 1 or 2 */
    int (*clock)(void *user, uint32_t id, uint64_t *ns);
    int (*random)(void *user, uint8_t *buf, size_t n);
    int (*sleep)(void *user, uint64_t ns);
    void (*end)(void *user, int how, uint32_t value);  /* proc_exit, proc_raise: told before the program is marked as over */
} wasmext_wasi_hooks;

typedef struct {
    const char *name;  /* what the program sees */
    size_t name_len;
    const char *host;  /* the real path of the directory */
    int readonly;
} wasmext_wasi_preopen;

typedef struct {
    const char *args;  /* each ended by a NUL; NULL: the program's name alone */
    size_t args_size;
    uint32_t argc;
    const char *env;  /* "NAME=value", each ended by a NUL */
    size_t env_size;
    uint32_t envc;
    const wasmext_wasi_preopen *preopens;
    size_t npreopens;
    const char *program;  /* argv[0] when args is NULL */
    wasmext_wasi_hooks hooks;
    void *user;  /* the host's own state, given to every hook; never freed by the core */
} wasmext_wasi_config;

struct wasmext_wasi {
    char *args;       /* the arguments, each ended by a NUL */
    size_t args_size;
    uint32_t argc;
    char *env;        /* "NAME=value", each ended by a NUL */
    size_t env_size;
    uint32_t envc;
    wasmext_wasi_hooks hooks;
    void *user;           /* the host's own state */
    int finished;         /* the program is over: 0, or how it ended (WASI_END_*) */
    uint32_t end_value;   /* ... the code of proc_exit, or the signal of proc_raise */
    wasm_rt_memory_t *memory;
    wasi_entry *entries;  /* the descriptors, by number */
    uint32_t nentries;
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

static inline char *wasi_copy(const char *text, size_t len) {
    char *out = (char *)WASI_MALLOC(len + 1);
    if (out != NULL) {
        memcpy(out, text, len);
        out[len] = '\0';
    }
    return out;
}

static inline void wasi_dirlist_free(wasi_dirlist *list) {
    if (list == NULL) return;
    for (size_t i = 0; i < list->count; i++) WASI_FREE(list->items[i].name);
    WASI_FREE(list->items);
    WASI_FREE(list);
}

/* closes what the descriptor holds; 0, or -1 with errno from the close of a file */
static inline int wasi_release(wasi_entry *e) {
    int rc = 0;
    if (e->owns_fd) rc = WASI_CLOSE(e->osfd);
    WASI_FREE(e->root);
    WASI_FREE(e->rel);
    WASI_FREE(e->preopen);
    wasi_dirlist_free(e->list);
    memset(e, 0, sizeof *e);
    return rc;
}

/* the directory of a preopen, from its real path: an open descriptor, or (through Python) the path */
static inline int wasi_fill_preopen(wasi_entry *e, const char *root) {
#if WASI_DIRS_ARE_PATHS
    e->root = wasi_copy(root, strlen(root));
    e->rel = wasi_copy("", 0);
    if (e->root == NULL || e->rel == NULL) {
        errno = ENOMEM;
        return -1;
    }
    return 0;
#else
    int fd = open(root, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return -1;
    e->osfd = fd;
    e->owns_fd = 1;
    return 0;
#endif
}

/* the lowest free number from 3 on; -1 when there is no memory */
static inline int64_t wasi_new_fd(wasmext_wasi *w) {
    for (uint32_t i = 3; i < w->nentries; i++)
        if (w->entries[i].kind == WASI_K_NONE) return i;
    uint32_t n = w->nentries * 2;
    wasi_entry *bigger = (wasi_entry *)WASI_REALLOC(w->entries, (size_t)n * sizeof(wasi_entry));
    if (bigger == NULL) return -1;
    memset(bigger + w->nentries, 0, (size_t)(n - w->nentries) * sizeof(wasi_entry));
    uint32_t first = w->nentries;
    w->entries = bigger;
    w->nentries = n;
    return first;
}

static inline void wasmext_wasi_destroy(wasmext_wasi *w);

/* The state from a configuration (which it copies: the host may free it at once). NULL on failure with *err an errno; when it is
   the directory of a preopen that could not be opened, *bad is its number in the configuration, otherwise (size_t)-1. */
static inline wasmext_wasi *wasmext_wasi_create(const wasmext_wasi_config *cfg, int *err, size_t *bad) {
    *bad = (size_t)-1;
    wasmext_wasi *w = (wasmext_wasi *)WASI_CALLOC(1, sizeof(wasmext_wasi));
    if (w == NULL) {
        *err = ENOMEM;
        return NULL;
    }
    w->hooks = cfg->hooks;
    w->user = cfg->user;
    w->nentries = 8;
    w->entries = (wasi_entry *)WASI_CALLOC(w->nentries, sizeof(wasi_entry));
    if (w->entries == NULL) goto nomem;
    for (int i = 0; i < 3; i++) {
        w->entries[i].kind = WASI_K_STD;
        w->entries[i].osfd = i;  /* which stream it is, wherever it is renumbered to */
    }
    if (cfg->args != NULL) {
        w->args = wasi_copy(cfg->args, cfg->args_size);
        if (w->args == NULL) goto nomem;
        w->args_size = cfg->args_size;
        w->argc = cfg->argc;
    } else {
        size_t len = strlen(cfg->program);  /* no args given: the program's own name */
        w->args = wasi_copy(cfg->program, len);
        if (w->args == NULL) goto nomem;
        w->args_size = len + 1;
        w->argc = 1;
    }
    if (cfg->env != NULL && cfg->env_size > 0) {
        w->env = wasi_copy(cfg->env, cfg->env_size);
        if (w->env == NULL) goto nomem;
        w->env_size = cfg->env_size;
        w->envc = cfg->envc;
    }
    for (size_t i = 0; i < cfg->npreopens; i++) {
        const wasmext_wasi_preopen *p = &cfg->preopens[i];
        int64_t number = wasi_new_fd(w);
        if (number < 0) goto nomem;
        wasi_entry *e = &w->entries[number];
        memset(e, 0, sizeof *e);
        e->kind = WASI_K_DIR;
        e->filetype = WASI_FT_DIR;
        e->rights = e->inheriting = p->readonly ? (WASI_R_ALL & ~WASI_R_MUTATING) : WASI_R_ALL;
        e->preopen = wasi_copy(p->name, p->name_len);
        e->preopen_len = p->name_len;
        if (e->preopen == NULL) {
            wasi_release(e);
            goto nomem;
        }
        if (wasi_fill_preopen(e, p->host) < 0) {
            *err = errno;
            *bad = i;
            wasi_release(e);
            wasmext_wasi_destroy(w);
            return NULL;
        }
    }
    return w;
nomem:
    *err = ENOMEM;
    wasmext_wasi_destroy(w);
    return NULL;
}

static inline void wasmext_wasi_destroy(wasmext_wasi *w) {
    if (w == NULL) return;
    for (uint32_t i = 0; i < w->nentries; i++) wasi_release(&w->entries[i]);
    WASI_FREE(w->entries);
    WASI_FREE(w->args);
    WASI_FREE(w->env);
    WASI_FREE(w);
}

static inline void wasmext_wasi_bind(wasmext_wasi *w, wasm_rt_memory_t *memory) { w->memory = memory; }

/* The program is over (proc_exit, proc_raise, or a trap of a command): as on an operating system, what it opened is closed at once, and
   the instance says so to any call afterwards. What the caller gave is not closed: the streams, and the directories of the host. */
static inline void wasmext_wasi_finish(wasmext_wasi *w, int how, uint32_t value) {
    if (w == NULL || w->finished) return;
    w->finished = how;
    w->end_value = value;
    for (uint32_t i = 0; i < w->nentries; i++) wasi_release(&w->entries[i]);
}

/* the status of a hook as the result of a call: a trap is not an errno */
static inline uint32_t wasi_hook_status(int rc, int *trapped) {
    if (rc == WASI_HOOK_TRAP) {
        *trapped = 1;
        return 0;
    }
    return (uint32_t)rc;
}

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

/* ---- clocks and random bytes (plain C: the system's own; a function given by the caller takes the place of either) ---------- */

/* the clock `id` of WASI (0 real time, 1 monotonic, 2 of the process, 3 of the thread) in nanoseconds; 0 on success */
#ifdef _WIN32
static inline uint64_t wasi_filetime_ns(FILETIME t) {
    return ((((uint64_t)t.dwHighDateTime << 32) | t.dwLowDateTime)) * 100u;
}

static inline int wasi_clock_system(uint32_t id, uint64_t *ns) {
    FILETIME created, exited, kernel, user, now;
    LARGE_INTEGER counter, frequency;
    switch (id) {
    case 0:
        GetSystemTimePreciseAsFileTime(&now);
        *ns = wasi_filetime_ns(now) - 11644473600ull * 1000000000ull;  /* from 1601 to 1970 */
        return 0;
    case 1:
        if (!QueryPerformanceFrequency(&frequency) || !QueryPerformanceCounter(&counter)) return -1;
        *ns = (uint64_t)(counter.QuadPart / frequency.QuadPart) * 1000000000ull +
              (uint64_t)(counter.QuadPart % frequency.QuadPart) * 1000000000ull / (uint64_t)frequency.QuadPart;
        return 0;
    case 2:
        if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) return -1;
        *ns = wasi_filetime_ns(kernel) + wasi_filetime_ns(user);
        return 0;
    case 3:
        if (!GetThreadTimes(GetCurrentThread(), &created, &exited, &kernel, &user)) return -1;
        *ns = wasi_filetime_ns(kernel) + wasi_filetime_ns(user);
        return 0;
    default: return -1;
    }
}

static inline int wasi_clock_resolution(uint32_t id, uint64_t *ns) {
    LARGE_INTEGER frequency;
    if (id == 1) {
        if (!QueryPerformanceFrequency(&frequency)) return -1;
        *ns = (1000000000ull + (uint64_t)frequency.QuadPart - 1) / (uint64_t)frequency.QuadPart;
        return 0;
    }
    *ns = 100;  /* the unit of a FILETIME */
    return id > 3 ? -1 : 0;
}
#else
static inline clockid_t wasi_clock_id(uint32_t id) {
    switch (id) {
    case 0: return CLOCK_REALTIME;
    case 1: return CLOCK_MONOTONIC;
    case 2: return CLOCK_PROCESS_CPUTIME_ID;
    default: return CLOCK_THREAD_CPUTIME_ID;
    }
}

static inline int wasi_clock_system(uint32_t id, uint64_t *ns) {
    struct timespec t;
    if (id > 3 || clock_gettime(wasi_clock_id(id), &t) != 0) return -1;
    *ns = (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
    return 0;
}

static inline int wasi_clock_resolution(uint32_t id, uint64_t *ns) {
    struct timespec t;
    if (id > 3 || clock_getres(wasi_clock_id(id), &t) != 0) return -1;
    *ns = (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
    if (*ns == 0) *ns = 1;
    return 0;
}
#endif

/* the time of a clock: the hook of the host or the system's */
static inline uint32_t wasi_clock_ns(wasmext_wasi *w, uint32_t id, uint64_t *ns, int *trapped) {
    if (id > 3) return WASI_E_INVAL;
    if (w->hooks.clock != NULL) return wasi_hook_status(w->hooks.clock(w->user, id, ns), trapped);
    return wasi_clock_system(id, ns) == 0 ? WASI_E_SUCCESS : WASI_E_NOTSUP;
}

static inline uint32_t wasi_clock_res_get(void *s, uint32_t id, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    uint64_t ns;
    if (id > 3) return WASI_E_INVAL;
    if (wasi_clock_resolution(id, &ns) != 0) return WASI_E_NOTSUP;
    return wasi_put_u64(w, ptr, ns) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

static inline uint32_t wasi_clock_time_get(void *s, uint32_t id, uint64_t precision, uint32_t ptr, int *trapped) {
    WASI_STATE(s);
    (void)precision;
    uint64_t ns = 0;
    uint32_t rc = wasi_clock_ns(w, id, &ns, trapped);
    if (rc != WASI_E_SUCCESS) return rc;
    return wasi_put_u64(w, ptr, ns) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

/* `size` random bytes from the system; 0 on success */
static inline int wasi_random_system(unsigned char *buf, size_t size) {
#if defined(_WIN32)
    return BCryptGenRandom(NULL, buf, (ULONG)size, BCRYPT_USE_SYSTEM_PREFERRED_RNG) == 0 ? 0 : -1;
#elif defined(__APPLE__)
    arc4random_buf(buf, size);
    return 0;
#else
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    size_t done = 0;
    while (done < size) {
        ssize_t n = read(fd, buf + done, size - done);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) {
            close(fd);
            return -1;
        }
        done += (size_t)n;
    }
    close(fd);
    return 0;
#endif
}

static inline uint32_t wasi_random_get(void *s, uint32_t buf, uint32_t size, int *trapped) {
    WASI_STATE(s);
    if (!wasi_in_memory(w, buf, size)) return WASI_E_FAULT;
    if (size == 0) return WASI_E_SUCCESS;
    if (w->hooks.random != NULL) return wasi_hook_status(w->hooks.random(w->user, w->memory->data + buf, size), trapped);
    return wasi_random_system(w->memory->data + buf, size) == 0 ? WASI_E_SUCCESS : WASI_E_IO;
}

/* waits `ns` nanoseconds on the monotonic clock: the hook of the host (the interpreter released, a signal seen) or, without one, the
   system's sleep in slices of 100 ms; 0, or an errno / WASI_HOOK_TRAP */
static inline int wasi_sleep_ns(wasmext_wasi *w, uint64_t ns) {
    if (w->hooks.sleep != NULL) return w->hooks.sleep(w->user, ns);
    uint64_t start;
    if (wasi_clock_system(1, &start) != 0) return WASI_E_NOTSUP;
    for (;;) {
        uint64_t now;
        if (wasi_clock_system(1, &now) != 0) return 0;
        uint64_t spent = now - start;
        if (spent >= ns) return 0;
        uint64_t left = ns - spent, slice = left < 100000000ull ? left : 100000000ull;
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
    }
}

static inline uint32_t wasi_sched_yield(void *s, int *trapped) {
    (void)s;
    (void)trapped;
    return WASI_E_SUCCESS;
}

static inline void wasi_proc_exit(void *s, uint32_t code, int *trapped) {
    WASI_STATE(s);
    if (w->hooks.end != NULL) w->hooks.end(w->user, WASI_END_EXIT, code);
    wasmext_wasi_finish(w, WASI_END_EXIT, code);
    *trapped = 1;
}

/* proc_raise: the signals of WASI 0.1 by number. A signal that is ignored when nothing handles it (the child, continue, urgent data, the
   size of the window) or that stops a process (stop, and the ones of a terminal) is answered with success and the program goes on;
   any other ends it, as it would end a process: the host is told (Python: WasiSignal, with the number and the name). 0 is no signal. */
static inline uint32_t wasi_proc_raise(void *s, uint32_t sig, int *trapped) {
    WASI_STATE(s);
    if (sig > 30) return WASI_E_INVAL;
    if (sig == 0 || (sig >= 16 && sig <= 22) || sig == 27) return WASI_E_SUCCESS;  /* nothing ends */
    if (w->hooks.end != NULL) w->hooks.end(w->user, WASI_END_SIGNAL, sig);
    wasmext_wasi_finish(w, WASI_END_SIGNAL, sig);
    *trapped = 1;
    return WASI_E_SUCCESS;
}

/* ---- descriptors ----------------------------------------------------------------------------------------------------- */

static inline wasi_entry *wasi_entry_of(wasmext_wasi *w, uint32_t fd) {
    return fd < w->nentries && w->entries[fd].kind != WASI_K_NONE ? &w->entries[fd] : NULL;
}

/* the real path of a directory descriptor: root, or root/rel; new memory */
static inline char *wasi_join(const char *root, const char *rel) {
    size_t a = strlen(root), b = strlen(rel);
    char *out = (char *)WASI_MALLOC(a + b + 2);
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

/* ---- the standard streams (the hooks of the host; without them descriptors 0, 1 and 2) --------------------------------- */

static inline uint32_t wasi_write_std(wasmext_wasi *w, uint32_t fd, uint32_t iovs, uint32_t count, uint32_t nwritten, int *trapped) {
    if (!wasi_in_memory(w, iovs, (uint64_t)count * 8)) return WASI_E_FAULT;
    uint64_t total = 0;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t base = 0, len = 0;
        wasi_get_u32(w, iovs + 8 * i, &base);
        wasi_get_u32(w, iovs + 8 * i + 4, &len);
        if (!wasi_in_memory(w, base, len)) return WASI_E_FAULT;
        if (len == 0) continue;
        if (w->hooks.stdout_write != NULL) {
            int rc = w->hooks.stdout_write(w->user, (int)fd, w->memory->data + base, len);
            if (rc) return wasi_hook_status(rc, trapped);
        } else {
            long long done = 0;
            while (done < (long long)len) {  /* all of it: a short write of a pipe is not the end of the iovec */
                long long n = WASI_WRITE((int)fd, w->memory->data + base + done, len - done);
                if (n < 0) {
                    if (errno == EINTR) continue;
                    return wasi_errno(errno);
                }
                done += n;
            }
        }
        total += len;
    }
    return wasi_put_u32(w, nwritten, (uint32_t)total) ? WASI_E_SUCCESS : WASI_E_FAULT;
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
    size_t got = 0;
    if (len) {
        if (w->hooks.stdin_read != NULL) {
            int rc = w->hooks.stdin_read(w->user, w->memory->data + base, len, &got);
            if (rc) return wasi_hook_status(rc, trapped);
            if (got > len) return WASI_E_IO;
        } else {
            long long n;
            do n = WASI_READ(0, w->memory->data + base, len);
            while (n < 0 && errno == EINTR);
            if (n < 0) return wasi_errno(errno);
            got = (size_t)n;
        }
    }
    return wasi_put_u32(w, nread, (uint32_t)got) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

/* ---- reading, seeking, closing ---------------------------------------------------------------------------------------- */

static inline uint32_t wasi_fd_write(void *s, uint32_t fd, uint32_t iovs, uint32_t count, uint32_t nwritten, int *trapped) {
    WASI_STATE(s);
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL || e->kind == WASI_K_DIR) return e == NULL ? WASI_E_BADF : WASI_E_ISDIR;
    if (e->kind == WASI_K_STD) return e->osfd == 0 ? WASI_E_BADF : wasi_write_std(w, (uint32_t)e->osfd, iovs, count, nwritten, trapped);
    if (!(e->rights & WASI_R_FD_WRITE)) return WASI_E_NOTCAPABLE;
    if (!wasi_in_memory(w, iovs, (uint64_t)count * 8)) return WASI_E_FAULT;
    uint64_t total = 0;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t base = 0, len = 0;
        wasi_get_u32(w, iovs + 8 * i, &base);
        wasi_get_u32(w, iovs + 8 * i + 4, &len);
        if (!wasi_in_memory(w, base, len)) return WASI_E_FAULT;
        if (len == 0) continue;
#ifdef _WIN32
        if (e->flags & WASI_FD_APPEND) WASI_LSEEK(e->osfd, 0, SEEK_END);
#endif
        long long n = WASI_WRITE(e->osfd, w->memory->data + base, len);  /* straight from the memory of the module */
        if (n < 0) {
            if (total) break;
            return wasi_errno(errno);
        }
        total += (uint64_t)n;
        if ((uint32_t)n < len) break;
    }
    return wasi_put_u32(w, nwritten, (uint32_t)total) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

static inline uint32_t wasi_fd_read(void *s, uint32_t fd, uint32_t iovs, uint32_t count, uint32_t nread, int *trapped) {
    WASI_STATE(s);
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    if (e->kind == WASI_K_STD) return e->osfd == 0 ? wasi_read_std(w, iovs, count, nread, trapped) : WASI_E_BADF;
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
    uint64_t base = e->kind == WASI_K_STD ? (e->osfd == 0 ? WASI_RIGHTS_STDIN : WASI_RIGHTS_STDOUT) : e->rights;
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

/* ---- what a file or a directory is ----------------------------------------------------------------------------------- */

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

/* what the specification calls filestat, the same for both ways of getting it */
typedef struct {
    uint64_t dev, ino, nlink, size, atim, mtim, ctim;
    uint8_t filetype;
} wasi_stat;

/* the filestat of the first snapshot has a 32-bit link count and 56 bytes */
static inline uint32_t wasi_put_filestat(wasmext_wasi *w, uint32_t ptr, const wasi_stat *st, int legacy) {
    size_t total = legacy ? 56 : 64;
    if (!wasi_in_memory(w, ptr, total)) return WASI_E_FAULT;
    memset(w->memory->data + ptr, 0, total);
    wasi_put_u64(w, ptr, st->dev);
    wasi_put_u64(w, ptr + 8, st->ino);
    wasi_put_u8(w, ptr + 16, st->filetype);
    if (legacy) {
        wasi_put_u32(w, ptr + 20, (uint32_t)st->nlink);
        wasi_put_u64(w, ptr + 24, st->size);
        wasi_put_u64(w, ptr + 32, st->atim);
        wasi_put_u64(w, ptr + 40, st->mtim);
        wasi_put_u64(w, ptr + 48, st->ctim);
    } else {
        wasi_put_u64(w, ptr + 24, st->nlink);
        wasi_put_u64(w, ptr + 32, st->size);
        wasi_put_u64(w, ptr + 40, st->atim);
        wasi_put_u64(w, ptr + 48, st->mtim);
        wasi_put_u64(w, ptr + 56, st->ctim);
    }
    return WASI_E_SUCCESS;
}

/* ---- the directory listing, as the specification wants it: "." and "..", then the names in order ------------------------ */

static inline int wasi_dirent_order(const void *a, const void *b) {
    const wasi_dirent *x = (const wasi_dirent *)a, *y = (const wasi_dirent *)b;
    int rx = strcmp(x->name, ".") == 0 ? 0 : strcmp(x->name, "..") == 0 ? 1 : 2;
    int ry = strcmp(y->name, ".") == 0 ? 0 : strcmp(y->name, "..") == 0 ? 1 : 2;
    return rx != ry ? rx - ry : strcmp(x->name, y->name);
}

static inline int wasi_dirlist_add(wasi_dirlist *list, const char *name, uint64_t ino, uint8_t type) {
    if (list->count == list->capacity) {  /* the room doubles: a directory of many names is not copied again and again */
        size_t room = list->capacity ? list->capacity * 2 : 128;
        wasi_dirent *bigger = (wasi_dirent *)WASI_REALLOC(list->items, room * sizeof(wasi_dirent));
        if (bigger == NULL) return -1;
        list->items = bigger;
        list->capacity = room;
    }
    char *copy = wasi_copy(name, strlen(name));
    if (copy == NULL) return -1;
    wasi_dirent *item = &list->items[list->count++];
    item->name = copy;
    item->namelen = (uint32_t)strlen(name);
    item->ino = ino;
    item->type = type;
    return 0;
}

/* the fdflags as flags of the system (the ones it has) */
static inline int wasi_native_fdflags(uint32_t fdflags) {
    int flags = 0;
#ifndef _WIN32  /* the C library of Windows cannot take it off again: fd_write does it by seeking to the end */
    if (fdflags & WASI_FD_APPEND) flags |= O_APPEND;
#endif
#ifdef O_DSYNC
    if (fdflags & WASI_FD_DSYNC) flags |= O_DSYNC;
#endif
#ifdef O_RSYNC
    if (fdflags & WASI_FD_RSYNC) flags |= O_RSYNC;
#endif
#ifdef O_SYNC
    if (fdflags & WASI_FD_SYNC) flags |= O_SYNC;
#endif
#ifdef O_NONBLOCK
    if (fdflags & WASI_FD_NONBLOCK) flags |= O_NONBLOCK;
#endif
    return flags;
}

/* the flags of open(2) that a path_open asks for */
static inline int wasi_open_flags(uint64_t base, uint32_t oflags, uint32_t fdflags) {
    int writable = (base & WASI_R_FD_WRITE) != 0 || (oflags & WASI_O_TRUNC) != 0, readable = (base & WASI_R_FD_READ) != 0;
    int flags = writable ? (readable ? O_RDWR : O_WRONLY) : O_RDONLY;
    if (oflags & WASI_O_CREAT) flags |= O_CREAT;
    if (oflags & WASI_O_EXCL) flags |= O_EXCL;
    if (oflags & WASI_O_TRUNC) flags |= O_TRUNC;
#ifdef O_BINARY
    flags |= O_BINARY;
#endif
    return flags | wasi_native_fdflags(fdflags);
}

#if WASMEXT_WASI_PYTHON_FS
/* the file backend is that of wasi_python.h (included after this header by whoever sets WASMEXT_WASI_PYTHON_FS) */
static inline uint32_t wasi_be_stat_fd(wasmext_wasi *w, wasi_entry *e, wasi_stat *out, int *trapped);
static inline uint32_t wasi_be_stat_path(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int follow,
                                         wasi_stat *out, int *trapped);
static inline uint32_t wasi_be_open(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int follow, uint32_t oflags,
                                    uint64_t base, uint32_t fdflags, wasi_entry *e, int *trapped);
static inline uint32_t wasi_be_mkdir(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int *trapped);
static inline uint32_t wasi_be_remove(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int isdir, int *trapped);
static inline uint32_t wasi_be_times_fd(wasmext_wasi *w, wasi_entry *e, uint64_t atim, uint64_t mtim, uint32_t flags, int *trapped);
static inline uint32_t wasi_be_times_path(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int follow, uint64_t atim,
                                          uint64_t mtim, uint32_t flags, int *trapped);
static inline uint32_t wasi_be_rename(wasmext_wasi *w, wasi_entry *d1, uint32_t p1, uint32_t l1, wasi_entry *d2, uint32_t p2,
                                      uint32_t l2, int *trapped);
static inline uint32_t wasi_be_link(wasmext_wasi *w, wasi_entry *d1, uint32_t p1, uint32_t l1, int follow, wasi_entry *d2,
                                    uint32_t p2, uint32_t l2, int *trapped);
static inline uint32_t wasi_be_symlink(wasmext_wasi *w, const unsigned char *target, uint32_t tlen, wasi_entry *dir, uint32_t path,
                                       uint32_t len, int *trapped);
static inline uint32_t wasi_be_readlink(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, char *out, size_t cap,
                                        size_t *used, int *trapped);
static inline uint32_t wasi_be_list(wasmext_wasi *w, wasi_entry *e, wasi_dirlist *list, int *trapped);
#elif defined(_WIN32)
#include "wasi_files_win32.h"
#else
/* ---- the file system through the system: openat and its kin (POSIX) ----------------------------------------------------
   A directory is an open descriptor, a path is walked from it one name at a time, and a symbolic link met on the way is read
   and its target put in front of the rest of the path (never an absolute one): nothing can lead out of the preopen, and there is
   no gap between a check and a use. No interpreter is involved. */

/* renameat is declared by <stdio.h> only when the feature macros were set before it was first included, which a build on an old
   glibc (manylinux) does not always have: the same prototype again is harmless where it is declared */
int renameat(int, const char *, int, const char *);

#define WASI_PATH_MAX 4096
#define WASI_NAME_MAX 255
#define WASI_LEAF_MAX (WASI_NAME_MAX + 2)  /* a name, a slash that ended the path, and the NUL */
#define WASI_MAX_DEPTH 64

/* Walks `given` (len bytes) from the directory `base`. 0, with the directory that holds the last name in `*parent` (a new
   descriptor, to close, when `*owned`; else `base` itself) and that name in `leaf` ("." for a path that names a directory itself).
   When `follow` is set a last name that is a link is expanded too. Otherwise an errno of WASI. */
static inline uint32_t wasi_walk(int base, const unsigned char *given, uint32_t len, int follow, int *parent, int *owned,
                                 char leaf[WASI_LEAF_MAX]) {
    char work[WASI_PATH_MAX], target[WASI_PATH_MAX], name[WASI_NAME_MAX + 1];
    int fds[WASI_MAX_DEPTH + 1];
    int depth = 0, links = 0;
    uint32_t rc = WASI_E_SUCCESS;
    if (len == 0) return WASI_E_NOENT;
    if (len >= sizeof work) return WASI_E_NAMETOOLONG;
    if (memchr(given, 0, len) != NULL) return WASI_E_INVAL;
    if (given[0] == '/') return WASI_E_NOTCAPABLE;
    memcpy(work, given, len);
    work[len] = '\0';
    fds[0] = base;
    char *cur = work;
    for (;;) {
        while (*cur == '/') cur++;
        if (*cur == '\0') {  /* nothing left: the path named a directory (it ended with a slash) */
            strcpy(leaf, ".");
            break;
        }
        char *end = strchr(cur, '/');
        size_t clen = end ? (size_t)(end - cur) : strlen(cur);
        char *rest = cur + clen;
        while (*rest == '/') rest++;
        int last = (*rest == '\0');
        int slash = last && end != NULL;  /* the path ended with a slash: what it names has to be a directory */
        if (clen > WASI_NAME_MAX) {
            rc = WASI_E_NAMETOOLONG;
            goto done;
        }
        memcpy(name, cur, clen);
        name[clen] = '\0';
        if (clen == 1 && name[0] == '.') {
            if (last) {
                strcpy(leaf, ".");
                break;
            }
            cur = rest;
            continue;
        }
        if (clen == 2 && name[0] == '.' && name[1] == '.') {
            if (depth == 0) {  /* out of the directory it was given */
                rc = WASI_E_NOTCAPABLE;
                goto done;
            }
            close(fds[depth--]);
            if (last) {
                strcpy(leaf, ".");
                break;
            }
            cur = rest;
            continue;
        }
        int expand = 0;
        if (last) {
            if (!follow) {
                strcpy(leaf, name);
                if (slash) strcat(leaf, "/");
                break;
            }
            expand = 1;  /* a link at the end is read before it is used */
        } else {
            if (depth >= WASI_MAX_DEPTH) {
                rc = WASI_E_NAMETOOLONG;
                goto done;
            }
            int next = openat(fds[depth], name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            if (next >= 0) {
                fds[++depth] = next;
                cur = rest;
                continue;
            }
            if (errno != ELOOP && errno != ENOTDIR && errno != EMLINK) {
                rc = wasi_errno(errno);
                goto done;
            }
            expand = 1;  /* not a directory we can enter: perhaps a link */
        }
        if (expand) {
            ssize_t n = readlinkat(fds[depth], name, target, sizeof target - 1);
            if (n < 0) {
                if (last) {  /* not a link: this is the last name */
                    strcpy(leaf, name);
                if (slash) strcat(leaf, "/");
                    break;
                }
                rc = WASI_E_NOTDIR;  /* a name in the middle that is not a directory, nor a link */
                goto done;
            }
            target[n] = '\0';
            if (++links > 40) {
                rc = WASI_E_LOOP;
                goto done;
            }
            if (target[0] == '/') {
                rc = WASI_E_NOTCAPABLE;
                goto done;
            }
            size_t rest_len = strlen(rest);
            if ((size_t)n + 1 + rest_len >= sizeof work) {
                rc = WASI_E_NAMETOOLONG;
                goto done;
            }
            memmove(work + n + 1, rest, rest_len + 1);  /* rest may lie inside work */
            memcpy(work, target, (size_t)n);
            work[n] = '/';
            if (rest_len == 0 && !slash) work[n] = '\0';  /* a slash only where the path had one */
            cur = work;
        }
    }
    for (int i = 1; i < depth; i++) close(fds[i]);
    *parent = fds[depth];
    *owned = depth > 0;
    return WASI_E_SUCCESS;
done:
    for (int i = 1; i <= depth; i++) close(fds[i]);
    return rc;
}

/* a time of a file in nanoseconds since 1970 as WASI has it (unsigned): before 1970 is 0, and past the year 2262 it saturates (the product would overflow) */
static inline int64_t wasi_ns(const struct timespec *t) {
    if (t->tv_sec < 0) return 0;
    if ((int64_t)t->tv_sec > INT64_MAX / 1000000000LL - 1) return INT64_MAX;
    return (int64_t)t->tv_sec * 1000000000LL + t->tv_nsec;
}

static inline void wasi_stat_of_native(const struct stat *st, wasi_stat *out) {
    out->dev = (uint64_t)st->st_dev;
    out->ino = (uint64_t)st->st_ino;
    out->nlink = (uint64_t)st->st_nlink;
    out->size = (uint64_t)st->st_size;
#ifdef __APPLE__
    out->atim = (uint64_t)wasi_ns(&st->st_atimespec);
    out->mtim = (uint64_t)wasi_ns(&st->st_mtimespec);
    out->ctim = (uint64_t)wasi_ns(&st->st_ctimespec);
#else
    out->atim = (uint64_t)wasi_ns(&st->st_atim);
    out->mtim = (uint64_t)wasi_ns(&st->st_mtim);
    out->ctim = (uint64_t)wasi_ns(&st->st_ctim);
#endif
    out->filetype = wasi_filetype_of((unsigned long)st->st_mode);
}

static inline uint32_t wasi_be_stat_fd(wasmext_wasi *w, wasi_entry *e, wasi_stat *out, int *trapped) {
    (void)w;
    (void)trapped;
    struct stat st;
    if (fstat(e->osfd, &st) < 0) return wasi_errno(errno);
    wasi_stat_of_native(&st, out);
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_be_stat_path(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int follow,
                                         wasi_stat *out, int *trapped) {
    (void)trapped;
    if (dir->kind != WASI_K_DIR) return WASI_E_NOTDIR;
    if (!wasi_in_memory(w, path, len)) return WASI_E_FAULT;
    int parent, owned;
    char leaf[WASI_LEAF_MAX];
    uint32_t rc = wasi_walk(dir->osfd, w->memory->data + path, len, follow, &parent, &owned, leaf);
    if (rc) return rc;
    struct stat st;
    int failed = fstatat(parent, leaf, &st, AT_SYMLINK_NOFOLLOW);  /* a link at the end was expanded by the walk if it was to be */
    int saved = errno;
    if (owned) close(parent);
    if (failed < 0) return wasi_errno(saved);
    wasi_stat_of_native(&st, out);
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_be_open(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int follow, uint32_t oflags,
                                    uint64_t base, uint32_t fdflags, wasi_entry *e, int *trapped) {
    (void)trapped;
    if (dir->kind != WASI_K_DIR) return WASI_E_NOTDIR;
    if (!wasi_in_memory(w, path, len)) return WASI_E_FAULT;
    int parent, owned;
    char leaf[WASI_LEAF_MAX];
    uint32_t rc = wasi_walk(dir->osfd, w->memory->data + path, len, follow, &parent, &owned, leaf);
    if (rc) return rc;
    int flags = wasi_open_flags(base, oflags, fdflags) | O_NOFOLLOW | O_CLOEXEC;
    if (oflags & WASI_O_DIRECTORY) flags |= O_DIRECTORY;
    int fd = openat(parent, leaf, flags, 0666);
    if (fd < 0 && errno == EISDIR && (base & WASI_R_OF_DIRECTORY) && !(oflags & (WASI_O_CREAT | WASI_O_TRUNC))) {
        fd = openat(parent, leaf, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_DIRECTORY, 0);  /* it was a directory, and asked for as one */
    }
    int saved = errno;
    if (owned) close(parent);
    if (fd < 0) return wasi_errno(saved);
    struct stat st;
    if (fstat(fd, &st) < 0) {
        saved = errno;
        close(fd);
        return wasi_errno(saved);
    }
    e->kind = wasi_filetype_of((unsigned long)st.st_mode) == WASI_FT_DIR ? WASI_K_DIR : WASI_K_FILE;
    e->filetype = wasi_filetype_of((unsigned long)st.st_mode);
    e->osfd = fd;
    e->owns_fd = 1;
    return WASI_E_SUCCESS;
}

/* the directory that holds the last name of a path (a link at the end is expanded when `follow`), and that name; "." (the directory itself) is `itself` */
static inline uint32_t wasi_be_parent(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int follow, int *parent,
                                      int *owned, char leaf[WASI_LEAF_MAX], int *itself) {
    if (dir->kind != WASI_K_DIR) return WASI_E_NOTDIR;
    if (!wasi_in_memory(w, path, len)) return WASI_E_FAULT;
    uint32_t rc = wasi_walk(dir->osfd, w->memory->data + path, len, follow, parent, owned, leaf);
    *itself = rc == WASI_E_SUCCESS && strcmp(leaf, ".") == 0;
    return rc;
}

/* A name to be made that has a slash after it (a link): 1, with errno set, when it can only be an error; 0 when it has none */
static inline int wasi_leaf_slash(int parent, const char *leaf) {
    size_t n = strlen(leaf);
    if (n == 0 || leaf[n - 1] != '/') return 0;
    char bare[WASI_LEAF_MAX];
    memcpy(bare, leaf, n - 1);
    bare[n - 1] = '\0';
    struct stat st;
    if (fstatat(parent, bare, &st, AT_SYMLINK_NOFOLLOW) < 0) errno = errno == ENOENT ? ENOENT : errno;
    else errno = S_ISDIR(st.st_mode) ? EEXIST : ENOTDIR;
    return 1;
}

static inline uint32_t wasi_be_mkdir(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int *trapped) {
    (void)trapped;
    int parent, owned, itself;
    char leaf[WASI_LEAF_MAX];
    uint32_t rc = wasi_be_parent(w, dir, path, len, 0, &parent, &owned, leaf, &itself);
    if (rc) return rc;
    int failed = -1;
    if (itself) errno = EEXIST;
    else failed = mkdirat(parent, leaf, 0777);
    int saved = errno;
    if (owned) close(parent);
    return failed < 0 ? wasi_errno(saved) : WASI_E_SUCCESS;
}

static inline uint32_t wasi_be_remove(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int isdir, int *trapped) {
    (void)trapped;
    int parent, owned, itself;
    char leaf[WASI_LEAF_MAX];
    uint32_t rc = wasi_be_parent(w, dir, path, len, 0, &parent, &owned, leaf, &itself);
    if (rc) return rc;
    int failed = -1;
    if (itself) errno = EINVAL;
    else failed = unlinkat(parent, leaf, isdir ? AT_REMOVEDIR : 0);
    int saved = errno;
    /* unlink of a directory: EISDIR on Linux, EPERM on macOS; the system's own answer is what is given */
    if (owned) close(parent);
    return failed < 0 ? wasi_errno(saved) : WASI_E_SUCCESS;
}

static inline void wasi_timespecs(uint64_t atim, uint64_t mtim, uint32_t flags, struct timespec ts[2]) {
    for (int i = 0; i < 2; i++) {
        uint32_t set = i == 0 ? WASI_T_ATIM : WASI_T_MTIM, now = i == 0 ? WASI_T_ATIM_NOW : WASI_T_MTIM_NOW;
        uint64_t value = i == 0 ? atim : mtim;
        memset(&ts[i], 0, sizeof ts[i]);
        if (flags & set) {
            ts[i].tv_sec = (time_t)(value / 1000000000u);
            ts[i].tv_nsec = (long)(value % 1000000000u);
        } else {
            ts[i].tv_nsec = (flags & now) ? UTIME_NOW : UTIME_OMIT;
        }
    }
}

static inline uint32_t wasi_be_times_fd(wasmext_wasi *w, wasi_entry *e, uint64_t atim, uint64_t mtim, uint32_t flags, int *trapped) {
    (void)w;
    (void)trapped;
    struct timespec ts[2];
    wasi_timespecs(atim, mtim, flags, ts);
    return futimens(e->osfd, ts) < 0 ? wasi_errno(errno) : WASI_E_SUCCESS;
}

static inline uint32_t wasi_be_times_path(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, int follow, uint64_t atim,
                                          uint64_t mtim, uint32_t flags, int *trapped) {
    (void)trapped;
    if (dir->kind != WASI_K_DIR) return WASI_E_NOTDIR;
    if (!wasi_in_memory(w, path, len)) return WASI_E_FAULT;
    int parent, owned;
    char leaf[WASI_LEAF_MAX];
    uint32_t rc = wasi_walk(dir->osfd, w->memory->data + path, len, follow, &parent, &owned, leaf);
    if (rc) return rc;
    struct timespec ts[2];
    wasi_timespecs(atim, mtim, flags, ts);
    int failed = utimensat(parent, leaf, ts, AT_SYMLINK_NOFOLLOW);  /* a link at the end was expanded by the walk if it was to be */
    int saved = errno;
    if (owned) close(parent);
    return failed < 0 ? wasi_errno(saved) : WASI_E_SUCCESS;
}

/* the two directories and names of rename and link; both descriptors have to be closed by the caller (`owned`) */
static inline uint32_t wasi_be_pair(wasmext_wasi *w, wasi_entry *d1, uint32_t p1, uint32_t l1, int follow, wasi_entry *d2,
                                    uint32_t p2, uint32_t l2, int *parent1, int *owned1, char leaf1[WASI_LEAF_MAX],
                                    int *parent2, int *owned2, char leaf2[WASI_LEAF_MAX]) {
    int itself1, itself2;
    uint32_t rc = wasi_be_parent(w, d1, p1, l1, follow, parent1, owned1, leaf1, &itself1);
    if (rc) return rc;
    rc = wasi_be_parent(w, d2, p2, l2, 0, parent2, owned2, leaf2, &itself2);
    if (rc) {
        if (*owned1) close(*parent1);
        return rc;
    }
    if (itself1 || itself2) {  /* a directory itself is neither moved nor made a link */
        if (*owned1) close(*parent1);
        if (*owned2) close(*parent2);
        return itself2 ? WASI_E_EXIST : WASI_E_INVAL;
    }
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_be_rename(wasmext_wasi *w, wasi_entry *d1, uint32_t p1, uint32_t l1, wasi_entry *d2, uint32_t p2,
                                      uint32_t l2, int *trapped) {
    (void)trapped;
    int parent1, owned1, parent2, owned2;
    char leaf1[WASI_LEAF_MAX], leaf2[WASI_LEAF_MAX];
    uint32_t rc = wasi_be_pair(w, d1, p1, l1, 0, d2, p2, l2, &parent1, &owned1, leaf1, &parent2, &owned2, leaf2);
    if (rc) return rc;
    int failed = renameat(parent1, leaf1, parent2, leaf2);
    int saved = errno;
    if (owned1) close(parent1);
    if (owned2) close(parent2);
    return failed < 0 ? wasi_errno(saved) : WASI_E_SUCCESS;
}

static inline uint32_t wasi_be_link(wasmext_wasi *w, wasi_entry *d1, uint32_t p1, uint32_t l1, int follow, wasi_entry *d2,
                                    uint32_t p2, uint32_t l2, int *trapped) {
    (void)trapped;
    int parent1, owned1, parent2, owned2;
    char leaf1[WASI_LEAF_MAX], leaf2[WASI_LEAF_MAX];
    uint32_t rc = wasi_be_pair(w, d1, p1, l1, follow, d2, p2, l2, &parent1, &owned1, leaf1, &parent2, &owned2, leaf2);
    if (rc) return rc;
    int failed = wasi_leaf_slash(parent2, leaf2) ? -1 : linkat(parent1, leaf1, parent2, leaf2, 0);  /* (the walk expanded a link at the end if it was to be followed) */
    int saved = errno;
    if (owned1) close(parent1);
    if (owned2) close(parent2);
    return failed < 0 ? wasi_errno(saved) : WASI_E_SUCCESS;
}

static inline uint32_t wasi_be_symlink(wasmext_wasi *w, const unsigned char *target, uint32_t tlen, wasi_entry *dir, uint32_t path,
                                       uint32_t len, int *trapped) {
    (void)trapped;
    char text[WASI_PATH_MAX];
    if (tlen >= sizeof text) return WASI_E_NAMETOOLONG;
    memcpy(text, target, tlen);
    text[tlen] = '\0';
    int parent, owned, itself;
    char leaf[WASI_LEAF_MAX];
    uint32_t rc = wasi_be_parent(w, dir, path, len, 0, &parent, &owned, leaf, &itself);
    if (rc) return rc;
    int failed = -1;
    if (itself) errno = EEXIST;
    else if (wasi_leaf_slash(parent, leaf)) failed = -1;  /* errno is set */
    else failed = symlinkat(text, parent, leaf);
    int saved = errno;
    if (owned) close(parent);
    return failed < 0 ? wasi_errno(saved) : WASI_E_SUCCESS;
}

static inline uint32_t wasi_be_readlink(wasmext_wasi *w, wasi_entry *dir, uint32_t path, uint32_t len, char *out, size_t cap,
                                        size_t *used, int *trapped) {
    (void)trapped;
    int parent, owned, itself;
    char leaf[WASI_LEAF_MAX];
    uint32_t rc = wasi_be_parent(w, dir, path, len, 0, &parent, &owned, leaf, &itself);
    if (rc) return rc;
    ssize_t n = -1;
    if (itself) errno = EINVAL;
    else n = readlinkat(parent, leaf, out, cap);
    int saved = errno;
    if (owned) close(parent);
    if (n < 0) return wasi_errno(saved);
    *used = (size_t)n;
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_be_list(wasmext_wasi *w, wasi_entry *e, wasi_dirlist *list, int *trapped) {
    (void)w;
    (void)trapped;
    int copy = dup(e->osfd);  /* closedir closes its descriptor */
    if (copy < 0) return wasi_errno(errno);
    DIR *d = fdopendir(copy);
    if (d == NULL) {
        int saved = errno;
        close(copy);
        return wasi_errno(saved);
    }
    rewinddir(d);
    uint32_t rc = WASI_E_SUCCESS;
    struct dirent *entry;
    while (rc == WASI_E_SUCCESS && (entry = readdir(d)) != NULL) {
        uint8_t type = WASI_FT_UNKNOWN;
        switch (entry->d_type) {
        case DT_DIR: type = WASI_FT_DIR; break;
        case DT_REG: type = WASI_FT_REGULAR; break;
        case DT_LNK: type = WASI_FT_SYMLINK; break;
        case DT_CHR: type = WASI_FT_CHAR; break;
        case DT_BLK: type = WASI_FT_BLOCK; break;
        case DT_SOCK: type = WASI_FT_SOCKET_STREAM; break;
        default: {  /* the file system does not say: ask */
            struct stat st;
            if (fstatat(e->osfd, entry->d_name, &st, AT_SYMLINK_NOFOLLOW) == 0) type = wasi_filetype_of((unsigned long)st.st_mode);
        }
        }
        if (wasi_dirlist_add(list, entry->d_name, (uint64_t)entry->d_ino, type) < 0) rc = WASI_E_NOMEM;
    }
    closedir(d);
    return rc;
}
#endif

/* ---- the calls that use them ------------------------------------------------------------------------------------------- */

static inline uint32_t wasi_filestat_of_fd(wasmext_wasi *w, uint32_t fd, uint32_t ptr, int legacy, int *trapped) {
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    wasi_stat st;
    if (e->kind == WASI_K_STD) {  /* a terminal or a pipe: nothing to say but what it is */
        memset(&st, 0, sizeof st);
        st.filetype = WASI_FT_CHAR;
        return wasi_put_filestat(w, ptr, &st, legacy);
    }
    if (!(e->rights & WASI_R_FD_FILESTAT_GET)) return WASI_E_NOTCAPABLE;
    uint32_t rc = wasi_be_stat_fd(w, e, &st, trapped);
    return rc ? rc : wasi_put_filestat(w, ptr, &st, legacy);
}

static inline uint32_t wasi_filestat_of_path(wasmext_wasi *w, uint32_t fd, uint32_t flags, uint32_t path, uint32_t len,
                                             uint32_t ptr, int legacy, int *trapped) {
    wasi_entry *dir = wasi_entry_of(w, fd);
    if (dir == NULL) return WASI_E_BADF;
    if (!(dir->rights & WASI_R_PATH_FILESTAT_GET)) return WASI_E_NOTCAPABLE;
    wasi_stat st;
    uint32_t rc = wasi_be_stat_path(w, dir, path, len, (flags & WASI_LOOKUP_FOLLOW) != 0, &st, trapped);
    return rc ? rc : wasi_put_filestat(w, ptr, &st, legacy);
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

static inline uint32_t wasi_fd_readdir(void *s, uint32_t fd, uint32_t buf, uint32_t size, uint64_t cookie, uint32_t used,
                                       int *trapped) {
    WASI_STATE(s);
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    if (e->kind != WASI_K_DIR) return WASI_E_NOTDIR;
    if (!(e->rights & WASI_R_FD_READDIR)) return WASI_E_NOTCAPABLE;
    if (!wasi_in_memory(w, buf, size)) return WASI_E_FAULT;
    if (cookie == 0 || e->list == NULL) {  /* the listing is made again when the program starts from the beginning */
        wasi_dirlist *list = (wasi_dirlist *)WASI_CALLOC(1, sizeof(wasi_dirlist));
        if (list == NULL) return WASI_E_NOMEM;
        uint32_t rc = wasi_be_list(w, e, list, trapped);
        if (rc) {
            wasi_dirlist_free(list);
            return rc;
        }
        if (list->count > 1) qsort(list->items, list->count, sizeof(wasi_dirent), wasi_dirent_order);  /* the same order for both ways */
        wasi_dirlist_free(e->list);
        e->list = list;
    }
    uint32_t at = 0;
    for (uint64_t i = cookie; i < e->list->count && at < size; i++) {
        const wasi_dirent *item = &e->list->items[i];
        unsigned char head[24];
        memset(head, 0, sizeof head);
        uint64_t next = i + 1;
        for (int k = 0; k < 8; k++) head[k] = (unsigned char)(next >> (8 * k));
        for (int k = 0; k < 8; k++) head[8 + k] = (unsigned char)(item->ino >> (8 * k));
        for (int k = 0; k < 4; k++) head[16 + k] = (unsigned char)(item->namelen >> (8 * k));
        head[20] = item->type;
        size_t room = size - at, part = room < sizeof head ? room : sizeof head;  /* the last entry may be cut short */
        memcpy(w->memory->data + buf + at, head, part);
        at += (uint32_t)part;
        if (part < sizeof head) break;
        room = size - at;
        part = room < item->namelen ? room : item->namelen;
        memcpy(w->memory->data + buf + at, item->name, part);
        at += (uint32_t)part;
    }
    return wasi_put_u32(w, used, at) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

static inline uint32_t wasi_path_open(void *s, uint32_t fd, uint32_t dirflags, uint32_t path, uint32_t len, uint32_t oflags,
                                      uint64_t base, uint64_t inheriting, uint32_t fdflags, uint32_t out, int *trapped) {
    WASI_STATE(s);
    wasi_entry *dir = wasi_entry_of(w, fd);
    if (dir == NULL) return WASI_E_BADF;
    if (dir->kind != WASI_K_DIR) return WASI_E_NOTDIR;
    if ((oflags >> 4) != 0 || (fdflags >> 5) != 0) return WASI_E_INVAL;
    if (!(dir->rights & WASI_R_PATH_OPEN)) return WASI_E_NOTCAPABLE;
    base &= dir->inheriting & WASI_R_ALL;
    inheriting &= dir->inheriting & WASI_R_ALL;
    if (oflags & WASI_O_CREAT) {
        if (oflags & WASI_O_DIRECTORY) return WASI_E_INVAL;
        if (!(dir->rights & WASI_R_PATH_CREATE_FILE)) return WASI_E_NOTCAPABLE;
    }
    if ((oflags & WASI_O_TRUNC) && !(dir->rights & WASI_R_PATH_FILESTAT_SET_SIZE)) return WASI_E_NOTCAPABLE;
    int64_t number = wasi_new_fd(w);
    if (number < 0) return WASI_E_NOMEM;
    dir = &w->entries[fd];  /* the table may have moved when it grew */
    wasi_entry *e = &w->entries[number];
    memset(e, 0, sizeof *e);
    uint32_t rc = wasi_be_open(w, dir, path, len, (dirflags & WASI_LOOKUP_FOLLOW) != 0, oflags, base, fdflags, e, trapped);
    if (rc) {
        wasi_release(e);
        return rc;
    }
    e->rights = base;
    if (e->kind == WASI_K_DIR) e->rights &= ~(WASI_R_FD_SEEK | WASI_R_FD_TELL);  /* a directory is not seeked */
    e->inheriting = inheriting;
    e->flags = (uint16_t)fdflags;
    if (!wasi_put_u32(w, out, (uint32_t)number)) {
        wasi_release(e);
        return WASI_E_FAULT;
    }
    return WASI_E_SUCCESS;
}

/* ---- writing, creating, removing ---------------------------------------------------------------------------------------- */

/* the entry of a file descriptor that has the right, or an errno of WASI */
static inline uint32_t wasi_entry_with(wasmext_wasi *w, uint32_t fd, uint64_t right, wasi_entry **out) {
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    *out = e;
    if (e->kind != WASI_K_STD && !(e->rights & right)) return WASI_E_NOTCAPABLE;
    return WASI_E_SUCCESS;
}

/* the directory of a call on a path: it has to be one and to have the right */
static inline uint32_t wasi_dir_with(wasmext_wasi *w, uint32_t fd, uint64_t right, wasi_entry **out) {
    uint32_t rc = wasi_entry_with(w, fd, right, out);
    if (rc) return rc;
    return (*out)->kind == WASI_K_DIR ? WASI_E_SUCCESS : WASI_E_NOTDIR;
}

static inline uint32_t wasi_sync_entry(wasmext_wasi *w, uint32_t fd, uint64_t right, int data_only) {
    wasi_entry *e;
    uint32_t rc = wasi_entry_with(w, fd, right, &e);
    if (rc) return rc;
    if (e->kind == WASI_K_STD) return WASI_E_SUCCESS;  /* the stream is Python's: it flushes when it wants */
#if WASI_DIRS_ARE_PATHS
    (void)data_only;
    if (e->kind == WASI_K_DIR) return WASI_E_SUCCESS;  /* not an open descriptor: nothing to flush */
    return WASI_SYNC(e->osfd) < 0 ? wasi_errno(errno) : WASI_E_SUCCESS;
#else
#ifdef __linux__
    int failed = data_only ? fdatasync(e->osfd) : WASI_SYNC(e->osfd);
#else
    (void)data_only;
    int failed = WASI_SYNC(e->osfd);
#endif
    return failed < 0 ? wasi_errno(errno) : WASI_E_SUCCESS;
#endif
}

static inline uint32_t wasi_fd_datasync(void *s, uint32_t fd, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    return wasi_sync_entry(w, fd, WASI_R_FD_DATASYNC, 1);
}

static inline uint32_t wasi_fd_sync(void *s, uint32_t fd, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    return wasi_sync_entry(w, fd, WASI_R_FD_SYNC, 0);
}

static inline int wasi_truncate_native(int osfd, uint64_t size) {
#ifdef _WIN32
    return _chsize_s(osfd, (__int64)size);  /* the error itself, not -1 */
#else
    return ftruncate(osfd, (off_t)size) < 0 ? errno : 0;
#endif
}

static inline uint32_t wasi_set_size(wasi_entry *e, uint64_t size) {
    if (e->kind == WASI_K_DIR) return WASI_E_ISDIR;
    if (e->kind != WASI_K_FILE) return WASI_E_BADF;
    if (size > (uint64_t)INT64_MAX) return WASI_E_FBIG;
    return wasi_errno(wasi_truncate_native(e->osfd, size));
}

static inline uint32_t wasi_fd_filestat_set_size(void *s, uint32_t fd, uint64_t size, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    wasi_entry *e;
    uint32_t rc = wasi_entry_with(w, fd, WASI_R_FD_FILESTAT_SET_SIZE, &e);
    return rc ? rc : wasi_set_size(e, size);
}

/* makes the file at least offset + length long (the file system may not reserve the room, but it is as long) */
static inline uint32_t wasi_fd_allocate(void *s, uint32_t fd, uint64_t offset, uint64_t length, int *trapped) {
    WASI_STATE(s);
    wasi_entry *e;
    uint32_t rc = wasi_entry_with(w, fd, WASI_R_FD_ALLOCATE, &e);
    if (rc) return rc;
    if (e->kind == WASI_K_DIR) return WASI_E_ISDIR;
    if (e->kind != WASI_K_FILE) return WASI_E_BADF;
    if (offset > (uint64_t)INT64_MAX || length > (uint64_t)INT64_MAX - offset) return WASI_E_FBIG;
    wasi_stat st;
    memset(&st, 0, sizeof st);
    rc = wasi_be_stat_fd(w, e, &st, trapped);
    if (rc || *trapped) return rc;
    return st.size >= offset + length ? WASI_E_SUCCESS : wasi_set_size(e, offset + length);
}

static inline uint32_t wasi_times_flags_ok(uint32_t flags) {
    return flags > 15 || ((flags & WASI_T_ATIM) && (flags & WASI_T_ATIM_NOW)) || ((flags & WASI_T_MTIM) && (flags & WASI_T_MTIM_NOW))
               ? WASI_E_INVAL
               : WASI_E_SUCCESS;
}

static inline uint32_t wasi_fd_filestat_set_times(void *s, uint32_t fd, uint64_t atim, uint64_t mtim, uint32_t flags, int *trapped) {
    WASI_STATE(s);
    wasi_entry *e;
    uint32_t rc = wasi_entry_with(w, fd, WASI_R_FD_FILESTAT_SET_TIMES, &e);
    if (rc) return rc;
    if (e->kind == WASI_K_STD) return WASI_E_BADF;
    rc = wasi_times_flags_ok(flags);
    return rc ? rc : wasi_be_times_fd(w, e, atim, mtim, flags, trapped);
}

static inline uint32_t wasi_path_filestat_set_times(void *s, uint32_t fd, uint32_t lookup, uint32_t path, uint32_t len, uint64_t atim,
                                                    uint64_t mtim, uint32_t flags, int *trapped) {
    WASI_STATE(s);
    wasi_entry *dir;
    uint32_t rc = wasi_dir_with(w, fd, WASI_R_PATH_FILESTAT_SET_TIMES, &dir);
    if (rc) return rc;
    rc = wasi_times_flags_ok(flags);
    return rc ? rc : wasi_be_times_path(w, dir, path, len, (lookup & WASI_LOOKUP_FOLLOW) != 0, atim, mtim, flags, trapped);
}

static inline uint32_t wasi_fd_fdstat_set_flags(void *s, uint32_t fd, uint32_t flags, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    wasi_entry *e;
    uint32_t rc = wasi_entry_with(w, fd, WASI_R_FD_FDSTAT_SET_FLAGS, &e);
    if (rc) return rc;
    if (flags > 31) return WASI_E_INVAL;
    if (e->kind != WASI_K_FILE) return e->kind == WASI_K_STD ? WASI_E_SUCCESS : WASI_E_BADF;
#ifndef _WIN32
    int current = fcntl(e->osfd, F_GETFL);
    if (current < 0) return wasi_errno(errno);
    int all = wasi_native_fdflags(WASI_FD_APPEND | WASI_FD_DSYNC | WASI_FD_NONBLOCK | WASI_FD_RSYNC | WASI_FD_SYNC);
    if (fcntl(e->osfd, F_SETFL, (current & ~all) | wasi_native_fdflags(flags)) < 0) return wasi_errno(errno);
#endif
    e->flags = (uint16_t)flags;
    return WASI_E_SUCCESS;
}

/* the rights can only be given up, never gained */
static inline uint32_t wasi_fd_fdstat_set_rights(void *s, uint32_t fd, uint64_t base, uint64_t inheriting, int *trapped) {
    WASI_STATE(s);
    (void)trapped;
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    if (e->kind == WASI_K_STD) return WASI_E_NOTCAPABLE;
    if ((base & ~e->rights) != 0 || (inheriting & ~e->inheriting) != 0) return WASI_E_NOTCAPABLE;
    e->rights = base;
    e->inheriting = inheriting;
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_path_create_directory(void *s, uint32_t fd, uint32_t path, uint32_t len, int *trapped) {
    WASI_STATE(s);
    wasi_entry *dir;
    uint32_t rc = wasi_dir_with(w, fd, WASI_R_PATH_CREATE_DIRECTORY, &dir);
    return rc ? rc : wasi_be_mkdir(w, dir, path, len, trapped);
}

static inline uint32_t wasi_path_remove_directory(void *s, uint32_t fd, uint32_t path, uint32_t len, int *trapped) {
    WASI_STATE(s);
    wasi_entry *dir;
    uint32_t rc = wasi_dir_with(w, fd, WASI_R_PATH_REMOVE_DIRECTORY, &dir);
    return rc ? rc : wasi_be_remove(w, dir, path, len, 1, trapped);
}

static inline uint32_t wasi_path_unlink_file(void *s, uint32_t fd, uint32_t path, uint32_t len, int *trapped) {
    WASI_STATE(s);
    wasi_entry *dir;
    uint32_t rc = wasi_dir_with(w, fd, WASI_R_PATH_UNLINK_FILE, &dir);
    return rc ? rc : wasi_be_remove(w, dir, path, len, 0, trapped);
}

/* ---- positions, renaming, links, waiting ---------------------------------------------------------------------------------- */

/* read or write at a position, leaving the position of the descriptor where it was */
static inline long long wasi_at_position(int osfd, void *buf, size_t n, uint64_t offset, int writing) {
#ifdef _WIN32
    long long saved = _lseeki64(osfd, 0, SEEK_CUR);  /* Windows has no pread: seek, do it, seek back */
    if (saved < 0 || _lseeki64(osfd, (long long)offset, SEEK_SET) < 0) return -1;
    int count = (int)(n < 0x7fffffff ? n : 0x7fffffff);
    long long done = writing ? _write(osfd, buf, (unsigned int)count) : _read(osfd, buf, (unsigned int)count);
    int err = errno;
    _lseeki64(osfd, saved, SEEK_SET);
    errno = err;
    return done;
#else
    return writing ? pwrite(osfd, buf, n, (off_t)offset) : pread(osfd, buf, n, (off_t)offset);
#endif
}

static inline uint32_t wasi_fd_at(void *s, uint32_t fd, uint32_t iovs, uint32_t count, uint64_t offset, uint32_t out, int writing) {
    WASI_STATE(s);
    wasi_entry *e = wasi_entry_of(w, fd);
    if (e == NULL) return WASI_E_BADF;
    if (e->kind == WASI_K_STD) return WASI_E_SPIPE;
    if (e->kind == WASI_K_DIR) return WASI_E_ISDIR;
    /* the specification asks for fd_seek as well; wasi-libc opens a file for writing without it and calls pwrite all the same */
    uint64_t needed = writing ? WASI_R_FD_WRITE : WASI_R_FD_READ;
    if (!(e->rights & needed)) return WASI_E_NOTCAPABLE;
    if (offset > (uint64_t)INT64_MAX) return WASI_E_INVAL;
    if (!wasi_in_memory(w, iovs, (uint64_t)count * 8)) return WASI_E_FAULT;
    uint64_t total = 0;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t base = 0, len = 0;
        wasi_get_u32(w, iovs + 8 * i, &base);
        wasi_get_u32(w, iovs + 8 * i + 4, &len);
        if (!wasi_in_memory(w, base, len)) return WASI_E_FAULT;
        if (len == 0) continue;
        long long n = wasi_at_position(e->osfd, w->memory->data + base, len, offset + total, writing);
        if (n < 0) {
            if (total) break;
            return wasi_errno(errno);
        }
        total += (uint64_t)n;
        if ((uint32_t)n < len) break;
    }
    return wasi_put_u32(w, out, (uint32_t)total) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

static inline uint32_t wasi_fd_pread(void *s, uint32_t fd, uint32_t iovs, uint32_t count, uint64_t offset, uint32_t nread,
                                     int *trapped) {
    (void)trapped;
    return wasi_fd_at(s, fd, iovs, count, offset, nread, 0);
}

static inline uint32_t wasi_fd_pwrite(void *s, uint32_t fd, uint32_t iovs, uint32_t count, uint64_t offset, uint32_t nwritten,
                                      int *trapped) {
    (void)trapped;
    return wasi_fd_at(s, fd, iovs, count, offset, nwritten, 1);
}

static inline uint32_t wasi_path_rename(void *s, uint32_t fd, uint32_t old, uint32_t old_len, uint32_t new_fd, uint32_t new_,
                                        uint32_t new_len, int *trapped) {
    WASI_STATE(s);
    wasi_entry *from, *to;
    uint32_t rc = wasi_dir_with(w, fd, WASI_R(16), &from);  /* path_rename_source */
    if (rc) return rc;
    rc = wasi_dir_with(w, new_fd, WASI_R(17), &to);  /* path_rename_target */
    return rc ? rc : wasi_be_rename(w, from, old, old_len, to, new_, new_len, trapped);
}

static inline uint32_t wasi_path_link(void *s, uint32_t fd, uint32_t flags, uint32_t old, uint32_t old_len, uint32_t new_fd,
                                      uint32_t new_, uint32_t new_len, int *trapped) {
    WASI_STATE(s);
    wasi_entry *from, *to;
    uint32_t rc = wasi_dir_with(w, fd, WASI_R(11), &from);  /* path_link_source */
    if (rc) return rc;
    rc = wasi_dir_with(w, new_fd, WASI_R(12), &to);  /* path_link_target */
    return rc ? rc : wasi_be_link(w, from, old, old_len, (flags & WASI_LOOKUP_FOLLOW) != 0, to, new_, new_len, trapped);
}

/* A link that leads out cannot be followed, and one that is absolute could not be anywhere else than outside: neither is made. */
static inline uint32_t wasi_path_symlink(void *s, uint32_t target, uint32_t target_len, uint32_t fd, uint32_t path, uint32_t len,
                                         int *trapped) {
    WASI_STATE(s);
    wasi_entry *dir;
    uint32_t rc = wasi_dir_with(w, fd, WASI_R(24), &dir);  /* path_symlink */
    if (rc) return rc;
    if (!wasi_in_memory(w, target, target_len)) return WASI_E_FAULT;
    if (target_len == 0) return WASI_E_NOENT;
    if (memchr(w->memory->data + target, 0, target_len) != NULL) return WASI_E_INVAL;
    if (w->memory->data[target] == '/') return WASI_E_NOTCAPABLE;
    return wasi_be_symlink(w, w->memory->data + target, target_len, dir, path, len, trapped);
}

static inline uint32_t wasi_path_readlink(void *s, uint32_t fd, uint32_t path, uint32_t len, uint32_t buf, uint32_t buf_len,
                                          uint32_t used, int *trapped) {
    WASI_STATE(s);
    wasi_entry *dir;
    uint32_t rc = wasi_dir_with(w, fd, WASI_R(15), &dir);  /* path_readlink */
    if (rc) return rc;
    if (!wasi_in_memory(w, buf, buf_len)) return WASI_E_FAULT;
    char text[WASI_LINK_MAX];
    size_t n = 0;
    rc = wasi_be_readlink(w, dir, path, len, text, buf_len < sizeof text ? buf_len : sizeof text, &n, trapped);
    if (rc || *trapped) return rc;
    memcpy(w->memory->data + buf, text, n);
    return wasi_put_u32(w, used, (uint32_t)n) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

/* poll_oneoff: the descriptors of files are always ready; what makes the program wait is a clock, and it sleeps (in C, without the
   interpreter, so that other threads run) until the first one. `legacy`: the first snapshot, whose clock subscription starts with an identifier. */
/* how long a clock subscription still has to wait (0: it is due), or an errno of WASI */
static inline uint32_t wasi_subscription_wait(wasmext_wasi *w, uint32_t sub, int legacy, uint64_t entry_now[2], int have[2],
                                              uint64_t *wait, int *trapped) {
    uint32_t shift = legacy ? 8 : 0;
    uint32_t id = 0, flags16 = 0;
    uint64_t timeout = 0;
    wasi_get_u32(w, sub + 16 + shift, &id);
    uint32_t lo = 0, hi = 0;
    wasi_get_u32(w, sub + 24 + shift, &lo);
    wasi_get_u32(w, sub + 28 + shift, &hi);
    timeout = ((uint64_t)hi << 32) | lo;
    flags16 = w->memory->data[sub + 40 + shift] | ((uint32_t)w->memory->data[sub + 41 + shift] << 8);
    if (id > 1) return WASI_E_INVAL;  /* the clocks of the process and the thread are not something to wait for */
    if (flags16 & ~1u) return WASI_E_INVAL;  /* subclockflags has one flag, abstime */
    if (!(flags16 & 1)) {
        *wait = timeout;
        return WASI_E_SUCCESS;
    }
    if (!have[id]) {
        uint32_t rc = wasi_clock_ns(w, id, &entry_now[id], trapped);
        if (rc || *trapped) return rc;
        have[id] = 1;
    }
    *wait = timeout > entry_now[id] ? timeout - entry_now[id] : 0;
    return WASI_E_SUCCESS;
}

static inline uint32_t wasi_poll(wasmext_wasi *w, uint32_t in, uint32_t out, uint32_t count, uint32_t nevents, int legacy,
                                 int *trapped) {
    uint32_t stride = legacy ? 56 : 48;
    if (count == 0) return WASI_E_INVAL;
    if (!wasi_in_memory(w, in, (uint64_t)count * stride) || !wasi_in_memory(w, out, (uint64_t)count * 32)) return WASI_E_FAULT;
    uint64_t entry_now[2] = {0, 0}, shortest = 0;
    int have[2] = {0, 0}, immediate = 0, timed = 0;  /* timed: a clock was subscribed, so `shortest` is a time (it may be UINT64_MAX: forever) */
    for (uint32_t i = 0; i < count; i++) {  /* first, what is ready and how long the clocks wait */
        uint32_t sub = in + i * stride;
        uint8_t tag = w->memory->data[sub + 8];
        if (tag == 0) {
            uint64_t wait;
            uint32_t rc = wasi_subscription_wait(w, sub, legacy, entry_now, have, &wait, trapped);
            if (rc == WASI_E_SUCCESS && !*trapped && (!timed || wait < shortest)) {
                shortest = wait;
                timed = 1;
            }
            if (rc == WASI_E_INVAL) immediate = 1;
            else if (rc || *trapped) return rc;
        } else if (tag == 1 || tag == 2) {
            immediate = 1;
        } else {
            return WASI_E_INVAL;
        }
    }
    uint64_t waited = 0;
    if (!immediate && timed && shortest > 0) {
        int slept = wasi_sleep_ns(w, shortest);
        if (slept) return wasi_hook_status(slept, trapped);
        waited = shortest;
    }
    uint32_t made = 0;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t sub = in + i * stride, event = out + made * 32;
        uint8_t tag = w->memory->data[sub + 8];
        uint32_t error = WASI_E_SUCCESS;
        uint64_t nbytes = 0;
        if (tag == 0) {
            uint64_t wait;
            error = wasi_subscription_wait(w, sub, legacy, entry_now, have, &wait, trapped);
            if (*trapped) return 0;
            if (error == WASI_E_SUCCESS && wait > waited) continue;  /* not yet */
        } else {
            uint32_t fd = 0;
            wasi_get_u32(w, sub + 16, &fd);
            wasi_entry *e = wasi_entry_of(w, fd);
            if (e == NULL) error = WASI_E_BADF;
            else if (e->kind == WASI_K_FILE && tag == 1) {
                wasi_stat st;
                memset(&st, 0, sizeof st);
                long long at = WASI_LSEEK(e->osfd, 0, SEEK_CUR);
                if (at >= 0 && wasi_be_stat_fd(w, e, &st, trapped) == WASI_E_SUCCESS && st.size > (uint64_t)at) nbytes = st.size - (uint64_t)at;
                *trapped = 0;
            }
        }
        memset(w->memory->data + event, 0, 32);
        memcpy(w->memory->data + event, w->memory->data + sub, 8);  /* userdata */
        wasi_put_u16(w, event + 8, (uint16_t)error);
        w->memory->data[event + 10] = tag;
        if (tag != 0) wasi_put_u64(w, event + 16, nbytes);
        made++;
    }
    return wasi_put_u32(w, nevents, made) ? WASI_E_SUCCESS : WASI_E_FAULT;
}

static inline uint32_t wasi_poll_oneoff(void *s, uint32_t in, uint32_t out, uint32_t count, uint32_t nevents, int *trapped) {
    WASI_STATE(s);
    return wasi_poll(w, in, out, count, nevents, 0, trapped);
}

/* ---- not yet: ENOSYS, as the specification allows (ENOTSOCK for the sockets, which will not be there) --------------------- */

#define WASI_NOT_PROVIDED(name, code, ...) \
    static inline uint32_t wasi_##name(void *s, __VA_ARGS__, int *trapped) { \
        (void)s; \
        (void)trapped; \
        return code; \
    }

/* a descriptor is never a socket (a program cannot make one): the call says so, or that there is no such descriptor */
#define WASI_SOCKET(name, ...) \
    static inline uint32_t wasi_##name(void *s, uint32_t fd, __VA_ARGS__, int *trapped) { \
        WASI_STATE(s); \
        (void)trapped; \
        return wasi_entry_of(w, fd) == NULL ? WASI_E_BADF : WASI_E_NOTSOCK; \
    }

WASI_SOCKET(sock_accept, uint32_t b, uint32_t c)
WASI_SOCKET(sock_recv, uint32_t b, uint32_t c, uint32_t d, uint32_t e, uint32_t f)
WASI_SOCKET(sock_send, uint32_t b, uint32_t c, uint32_t d, uint32_t e)
WASI_SOCKET(sock_shutdown, uint32_t b)

#endif
