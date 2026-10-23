/* wasi:filesystem (32 imports): preopens and types (the twin of p2/wasi_p2_filesystem.py, where the confinement of paths, the rights and the layouts are described).
 * POSIX only (openat and the rest of the *at calls). The state keeps the preopens: `s->preopens`, a list of {path, name, writable} owned by the caller.
 * Every function that can fail with an error-code writes it in the result; a bad handle or a pointer outside the memory is a trap. */
#ifndef WASI_P2_FILESYSTEM_H
#define WASI_P2_FILESYSTEM_H

#ifdef _WIN32
#error "wasi_p2_filesystem.h needs POSIX"
#endif

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "wasi_p2_io.h"

/* error-code, in the order of the WIT */
enum {
    WASI_P2_E_ACCESS, WASI_P2_E_WOULD_BLOCK, WASI_P2_E_ALREADY, WASI_P2_E_BAD_DESCRIPTOR, WASI_P2_E_BUSY, WASI_P2_E_DEADLOCK, WASI_P2_E_QUOTA,
    WASI_P2_E_EXIST, WASI_P2_E_FILE_TOO_LARGE, WASI_P2_E_ILLEGAL_BYTE_SEQUENCE, WASI_P2_E_IN_PROGRESS, WASI_P2_E_INTERRUPTED, WASI_P2_E_INVALID,
    WASI_P2_E_IO, WASI_P2_E_IS_DIRECTORY, WASI_P2_E_LOOP, WASI_P2_E_TOO_MANY_LINKS, WASI_P2_E_MESSAGE_SIZE, WASI_P2_E_NAME_TOO_LONG,
    WASI_P2_E_NO_DEVICE, WASI_P2_E_NO_ENTRY, WASI_P2_E_NO_LOCK, WASI_P2_E_INSUFFICIENT_MEMORY, WASI_P2_E_INSUFFICIENT_SPACE, WASI_P2_E_NOT_DIRECTORY,
    WASI_P2_E_NOT_EMPTY, WASI_P2_E_NOT_RECOVERABLE, WASI_P2_E_UNSUPPORTED, WASI_P2_E_NO_TTY, WASI_P2_E_NO_SUCH_DEVICE, WASI_P2_E_OVERFLOW,
    WASI_P2_E_NOT_PERMITTED, WASI_P2_E_PIPE, WASI_P2_E_READ_ONLY, WASI_P2_E_INVALID_SEEK, WASI_P2_E_TEXT_FILE_BUSY, WASI_P2_E_CROSS_DEVICE
};
#define WASI_P2_OK (-1) /* what the functions of this file return when nothing failed; an error-code otherwise */

/* descriptor-flags, path-flags, open-flags */
enum { WASI_P2_READ = 1, WASI_P2_WRITE = 2, WASI_P2_FILE_SYNC = 4, WASI_P2_DATA_SYNC = 8, WASI_P2_REQUESTED_SYNC = 16, WASI_P2_MUTATE = 32 };
enum { WASI_P2_SYMLINK_FOLLOW = 1 };
enum { WASI_P2_CREATE = 1, WASI_P2_DIRECTORY = 2, WASI_P2_EXCLUSIVE = 4, WASI_P2_TRUNCATE = 8 };
/* descriptor-type */
enum { WASI_P2_T_UNKNOWN, WASI_P2_T_BLOCK, WASI_P2_T_CHAR, WASI_P2_T_DIRECTORY, WASI_P2_T_FIFO, WASI_P2_T_SYMLINK, WASI_P2_T_REGULAR, WASI_P2_T_SOCKET };

#define WASI_P2_NAME_MAX 255
#define WASI_P2_MAX_DEPTH 128
#define WASI_P2_MAX_LINKS 40
#define WASI_P2_PATH_MAX 8192
#define WASI_P2_STREAM_CHUNK 65536u

typedef struct {
    int fd;
    uint32_t flags;
    int is_dir;
} wasi_p2_descriptor;

typedef struct {
    uint32_t count, pos;
    uint8_t *types;
    char **names;
} wasi_p2_dir_entries;

WASI_P2_FN int wasi_p2_errno_code(int e) {
    switch (e) {
    case EACCES: return WASI_P2_E_ACCESS;
    case EAGAIN: return WASI_P2_E_WOULD_BLOCK;
    case EALREADY: return WASI_P2_E_ALREADY;
    case EBADF: return WASI_P2_E_BAD_DESCRIPTOR;
    case EBUSY: return WASI_P2_E_BUSY;
    case EDEADLK: return WASI_P2_E_DEADLOCK;
    case EDQUOT: return WASI_P2_E_QUOTA;
    case EEXIST: return WASI_P2_E_EXIST;
    case EFBIG: return WASI_P2_E_FILE_TOO_LARGE;
    case EILSEQ: return WASI_P2_E_ILLEGAL_BYTE_SEQUENCE;
    case EINPROGRESS: return WASI_P2_E_IN_PROGRESS;
    case EINTR: return WASI_P2_E_INTERRUPTED;
    case EINVAL: return WASI_P2_E_INVALID;
    case EIO: return WASI_P2_E_IO;
    case EISDIR: return WASI_P2_E_IS_DIRECTORY;
    case ELOOP: return WASI_P2_E_LOOP;
    case EMLINK: return WASI_P2_E_TOO_MANY_LINKS;
    case EMSGSIZE: return WASI_P2_E_MESSAGE_SIZE;
    case ENAMETOOLONG: return WASI_P2_E_NAME_TOO_LONG;
    case ENODEV: return WASI_P2_E_NO_DEVICE;
    case ENOENT: return WASI_P2_E_NO_ENTRY;
    case ENOLCK: return WASI_P2_E_NO_LOCK;
    case ENOMEM: return WASI_P2_E_INSUFFICIENT_MEMORY;
    case ENOSPC: return WASI_P2_E_INSUFFICIENT_SPACE;
    case ENOTDIR: return WASI_P2_E_NOT_DIRECTORY;
    case ENOTEMPTY: return WASI_P2_E_NOT_EMPTY;
    case ENOTRECOVERABLE: return WASI_P2_E_NOT_RECOVERABLE;
    case ENOSYS: return WASI_P2_E_UNSUPPORTED;
#if defined(ENOTSUP) && ENOTSUP != EOPNOTSUPP
    case ENOTSUP: return WASI_P2_E_UNSUPPORTED;
#endif
    case ENOTTY: return WASI_P2_E_NO_TTY;
    case ENXIO: return WASI_P2_E_NO_SUCH_DEVICE;
    case EOVERFLOW: return WASI_P2_E_OVERFLOW;
    case EPERM: return WASI_P2_E_NOT_PERMITTED;
    case EPIPE: return WASI_P2_E_PIPE;
    case EROFS: return WASI_P2_E_READ_ONLY;
    case ESPIPE: return WASI_P2_E_INVALID_SEEK;
    case ETXTBSY: return WASI_P2_E_TEXT_FILE_BUSY;
    case EXDEV: return WASI_P2_E_CROSS_DEVICE;
    default: return WASI_P2_E_IO;
    }
}

/* the code for the last failed call */
WASI_P2_FN int wasi_p2_fail(void) { return wasi_p2_errno_code(errno); }

WASI_P2_FN uint8_t wasi_p2_type_of(mode_t m) {
    if (S_ISREG(m)) return WASI_P2_T_REGULAR;
    if (S_ISDIR(m)) return WASI_P2_T_DIRECTORY;
    if (S_ISLNK(m)) return WASI_P2_T_SYMLINK;
    if (S_ISCHR(m)) return WASI_P2_T_CHAR;
    if (S_ISBLK(m)) return WASI_P2_T_BLOCK;
    if (S_ISFIFO(m)) return WASI_P2_T_FIFO;
    if (S_ISSOCK(m)) return WASI_P2_T_SOCKET;
    return WASI_P2_T_UNKNOWN;
}

#ifdef __APPLE__
#define WASI_P2_ATIME(st) ((st).st_atimespec)
#define WASI_P2_MTIME(st) ((st).st_mtimespec)
#define WASI_P2_CTIME(st) ((st).st_ctimespec)
#else
#define WASI_P2_ATIME(st) ((st).st_atim)
#define WASI_P2_MTIME(st) ((st).st_mtim)
#define WASI_P2_CTIME(st) ((st).st_ctim)
#endif

WASI_P2_FN int64_t wasi_p2_ts_ns(struct timespec t) { return (int64_t)t.tv_sec * 1000000000LL + t.tv_nsec; }

/* the descriptors and what they stand for */

WASI_P2_FN void wasi_p2_descriptor_destroy(wasi_p2_state *s, void *obj) {
    wasi_p2_descriptor *d = (wasi_p2_descriptor *)obj;
    (void)s;
    close(d->fd);
    free(d);
}

WASI_P2_FN void wasi_p2_dir_entries_destroy(wasi_p2_state *s, void *obj) {
    wasi_p2_dir_entries *e = (wasi_p2_dir_entries *)obj;
    (void)s;
    for (uint32_t i = 0; i < e->count; i++) free(e->names[i]);
    free(e->names);
    free(e->types);
    free(e);
}

WASI_P2_FN wasi_p2_descriptor *wasi_p2_descriptor_get(wasi_p2_state *s, uint32_t handle) {
    return (wasi_p2_descriptor *)wasi_p2_table_get(s, handle, WASI_P2_KIND_DESCRIPTOR)->obj;
}

/* the rights: WASI_P2_OK, or the error-code that the absence of the flag is */
WASI_P2_FN int wasi_p2_need(const wasi_p2_descriptor *d, uint32_t flag) {
    if (d->flags & flag) return WASI_P2_OK;
    return flag == WASI_P2_MUTATE ? WASI_P2_E_READ_ONLY : WASI_P2_E_BAD_DESCRIPTOR; /* `mutate-directory` unset: read-only (the WIT says so) */
}

WASI_P2_FN uint32_t wasi_p2_descriptor_new(wasi_p2_state *s, int fd, uint32_t flags, int is_dir) {
    wasi_p2_descriptor *d = (wasi_p2_descriptor *)malloc(sizeof *d);
    if (!d) s->trap(s, "out of memory");
    d->fd = fd, d->flags = flags, d->is_dir = is_dir;
    return wasi_p2_table_new(s, WASI_P2_KIND_DESCRIPTOR, d, wasi_p2_descriptor_destroy);
}

/* the walk of a path, confined below a directory (see the Python twin): `dir` and `leaf` are the directory that holds the last name and that name ("." for none);
   `wasi_p2_walk_close` closes what the walk opened. */
typedef struct {
    int dir;
    char leaf[WASI_P2_NAME_MAX + 2];
    int fds[WASI_P2_MAX_DEPTH + 2]; /* [0] is the base, the others are opened by the walk */
    int depth;
} wasi_p2_walk;

WASI_P2_FN void wasi_p2_walk_close(wasi_p2_walk *w) {
    for (int i = 1; i <= w->depth; i++) close(w->fds[i]);
    w->depth = 0;
}

WASI_P2_FN int wasi_p2_walk_path(wasi_p2_walk *w, int base, const uint8_t *path, uint32_t len, int follow) {
    char work[WASI_P2_PATH_MAX], name[WASI_P2_NAME_MAX + 2], target[WASI_P2_PATH_MAX];
    int links = 0, rc = WASI_P2_OK;
    w->depth = 0;
    w->fds[0] = base;
    if (memchr(path, 0, len)) return WASI_P2_E_INVALID;
    if (len == 0) return WASI_P2_E_NO_ENTRY; /* an empty name is no name (POSIX; Wasmtime says the same) */
    if (len && path[0] == '/') return WASI_P2_E_NOT_PERMITTED;
    if (len >= sizeof work) return WASI_P2_E_NAME_TOO_LONG;
    memcpy(work, path, len);
    work[len] = '\0';
    char *cur = work;
    for (;;) {
        while (*cur == '/') cur++;
        if (*cur == '\0') {
            strcpy(w->leaf, ".");
            break;
        }
        char *end = strchr(cur, '/');
        size_t clen = end ? (size_t)(end - cur) : strlen(cur);
        char *rest = cur + clen;
        while (*rest == '/') rest++;
        int last = (*rest == '\0');
        int slash = last && end != NULL;
        if (clen > WASI_P2_NAME_MAX) {
            rc = WASI_P2_E_NAME_TOO_LONG;
            goto done;
        }
        memcpy(name, cur, clen);
        name[clen] = '\0';
        if (clen == 1 && name[0] == '.') {
            if (last) {
                strcpy(w->leaf, ".");
                break;
            }
            cur = rest;
            continue;
        }
        if (clen == 2 && name[0] == '.' && name[1] == '.') {
            if (w->depth == 0) {
                rc = WASI_P2_E_NOT_PERMITTED;
                goto done;
            }
            close(w->fds[w->depth--]);
            if (last) {
                strcpy(w->leaf, ".");
                break;
            }
            cur = rest;
            continue;
        }
        if (last) {
            if (!follow) {
                /* a slash after a name makes the kernel follow a link there whatever O_NOFOLLOW says; the walk follows it itself, below the base */
                char probe[1];
                if (!(slash && readlinkat(w->fds[w->depth], name, probe, sizeof probe) >= 0)) {
                    strcpy(w->leaf, name);
                    if (slash) strcat(w->leaf, "/");
                    break;
                }
            }
        } else {
            if (w->depth > WASI_P2_MAX_DEPTH) {
                rc = WASI_P2_E_NAME_TOO_LONG;
                goto done;
            }
            int next = openat(w->fds[w->depth], name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            if (next >= 0) {
                w->fds[++w->depth] = next;
                cur = rest;
                continue;
            }
            if (errno != ELOOP && errno != ENOTDIR && errno != EMLINK) {
                rc = wasi_p2_fail();
                goto done;
            }
        }
        ssize_t n = readlinkat(w->fds[w->depth], name, target, sizeof target - 1);
        if (n < 0) {
            if (last) { /* not a link: this is the last name */
                strcpy(w->leaf, name);
                if (slash) strcat(w->leaf, "/");
                break;
            }
            rc = WASI_P2_E_NOT_DIRECTORY;
            goto done;
        }
        target[n] = '\0';
        if (++links > WASI_P2_MAX_LINKS) {
            rc = WASI_P2_E_LOOP;
            goto done;
        }
        if (target[0] == '/') {
            rc = WASI_P2_E_NOT_PERMITTED;
            goto done;
        }
        size_t rest_len = strlen(rest);
        if ((size_t)n + 1 + rest_len >= sizeof work) {
            rc = WASI_P2_E_NAME_TOO_LONG;
            goto done;
        }
        memmove(work + n + 1, rest, rest_len + 1); /* rest may lie inside work */
        memcpy(work, target, (size_t)n);
        work[n] = '/';
        if (rest_len == 0 && !slash) work[n] = '\0';
        cur = work;
    }
    w->dir = w->fds[w->depth];
    return WASI_P2_OK;
done:
    wasi_p2_walk_close(w);
    return rc;
}

/* results */

WASI_P2_FN void wasi_p2_fs_fail(wasi_p2_state *s, uint32_t comp, uint32_t retptr, uint32_t at, int code) {
    wasi_p2_store_u8(s, comp, retptr, 1);
    wasi_p2_store_u8(s, comp, at, (uint8_t)code);
}

/* result<_, error-code> from a code */
WASI_P2_FN void wasi_p2_status(wasi_p2_state *s, uint32_t comp, uint32_t retptr, int rc) {
    if (rc != WASI_P2_OK) {
        wasi_p2_fs_fail(s, comp, retptr, retptr + 1, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
}

WASI_P2_FN void wasi_p2_datetime_some(wasi_p2_state *s, uint32_t comp, uint32_t ptr, int64_t ns) {
    wasi_p2_store_u8(s, comp, ptr, 1);
    wasi_p2_store_u64(s, comp, ptr + 8, (uint64_t)ns / 1000000000ULL);
    wasi_p2_store_u32(s, comp, ptr + 16, (uint32_t)((uint64_t)ns % 1000000000ULL));
}

WASI_P2_FN void wasi_p2_write_stat(wasi_p2_state *s, uint32_t comp, uint32_t ptr, const struct stat *st) {
    wasi_p2_store_u8(s, comp, ptr, wasi_p2_type_of(st->st_mode));
    wasi_p2_store_u64(s, comp, ptr + 8, (uint64_t)st->st_nlink);
    wasi_p2_store_u64(s, comp, ptr + 16, (uint64_t)st->st_size);
    wasi_p2_datetime_some(s, comp, ptr + 24, wasi_p2_ts_ns(WASI_P2_ATIME(*st)));
    wasi_p2_datetime_some(s, comp, ptr + 48, wasi_p2_ts_ns(WASI_P2_MTIME(*st)));
    wasi_p2_datetime_some(s, comp, ptr + 72, wasi_p2_ts_ns(WASI_P2_CTIME(*st)));
}

/* streams over a file: the descriptor is duplicated, so the stream outlives the handle */
typedef struct {
    wasi_p2_stream base;
    int fd;
    uint64_t pos;
    int append;
} wasi_p2_file_stream;

WASI_P2_FN void wasi_p2_file_stream_set_failure(wasi_p2_stream *st, int e, const char *what) {
    st->failure = what;
    st->failure_has_code = 1;
    st->failure_code = wasi_p2_errno_code(e);
}

WASI_P2_FN int wasi_p2_file_read(wasi_p2_state *s, wasi_p2_stream *st, uint8_t *buf, uint64_t len, uint64_t *got) {
    wasi_p2_file_stream *f = (wasi_p2_file_stream *)st;
    (void)s;
    *got = 0;
    if (len == 0) return WASI_P2_STREAM_OK;
    ssize_t n = pread(f->fd, buf, (size_t)len, (off_t)f->pos);
    if (n < 0) {
        wasi_p2_file_stream_set_failure(st, errno, "read failed");
        return WASI_P2_STREAM_FAILED;
    }
    if (n == 0) return WASI_P2_STREAM_CLOSED;
    f->pos += (uint64_t)n;
    *got = (uint64_t)n;
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN uint64_t wasi_p2_file_check_write(wasi_p2_state *s, wasi_p2_stream *st, int *status) {
    (void)s, (void)st;
    *status = WASI_P2_STREAM_OK;
    return WASI_P2_STREAM_CHUNK;
}

WASI_P2_FN int wasi_p2_file_write(wasi_p2_state *s, wasi_p2_stream *st, const uint8_t *data, uint64_t len) {
    wasi_p2_file_stream *f = (wasi_p2_file_stream *)st;
    (void)s;
    uint64_t at = f->pos;
    if (f->append) {
        struct stat sb;
        if (fstat(f->fd, &sb) < 0) {
            wasi_p2_file_stream_set_failure(st, errno, "write failed");
            return WASI_P2_STREAM_FAILED;
        }
        at = (uint64_t)sb.st_size;
    }
    uint64_t done = 0;
    while (done < len) {
        ssize_t n = pwrite(f->fd, data + done, (size_t)(len - done), (off_t)(at + done));
        if (n < 0) {
            if (errno == EINTR) continue;
            wasi_p2_file_stream_set_failure(st, errno, "write failed");
            return WASI_P2_STREAM_FAILED;
        }
        done += (uint64_t)n;
    }
    if (!f->append) f->pos += len;
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN int wasi_p2_file_flush(wasi_p2_state *s, wasi_p2_stream *st) {
    (void)s, (void)st;
    return WASI_P2_STREAM_OK;
}

WASI_P2_FN void wasi_p2_file_stream_destroy(wasi_p2_state *s, wasi_p2_stream *st) {
    close(((wasi_p2_file_stream *)st)->fd);
    wasi_p2_stream_free(s, st);
}

/* a handle on a new stream over `fd` (dup-ed); `output`: 0 reads from `pos`, 1 writes at `pos`, 2 appends */
WASI_P2_FN uint32_t wasi_p2_file_stream_new(wasi_p2_state *s, int fd, uint64_t pos, int output) {
    wasi_p2_file_stream *f = (wasi_p2_file_stream *)calloc(1, sizeof *f);
    if (!f) s->trap(s, "out of memory");
    f->fd = dup(fd);
    f->pos = pos;
    f->append = output == 2;
    f->base.ready = wasi_p2_always_ready;
    f->base.destroy = wasi_p2_file_stream_destroy;
    if (output) {
        f->base.check_write = wasi_p2_file_check_write;
        f->base.write = wasi_p2_file_write;
        f->base.flush = wasi_p2_file_flush;
        return wasi_p2_output_stream_new(s, &f->base);
    }
    f->base.read = wasi_p2_file_read;
    return wasi_p2_input_stream_new(s, &f->base);
}

/* preopens */

WASI_P2_FN void wasi_filesystem_preopens_get_directories(wasi_p2_state *s, uint32_t comp, uint32_t retptr) {
    uint32_t ptr = wasi_p2_alloc(s, comp, 4, 12 * s->preopen_count);
    for (uint32_t i = 0; i < s->preopen_count; i++) {
        int fd = open(s->preopens[i].path, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
        if (fd < 0) s->trap(s, "cannot open a preopened directory");
        uint32_t handle = wasi_p2_descriptor_new(s, fd, WASI_P2_READ | (s->preopens[i].writable ? WASI_P2_MUTATE : 0), 1);
        wasi_p2_store_u32(s, comp, ptr + 12 * i, handle);
        wasi_p2_string(s, comp, s->preopens[i].name, ptr + 12 * i + 4);
    }
    wasi_p2_store_u32(s, comp, retptr, ptr);
    wasi_p2_store_u32(s, comp, retptr + 4, s->preopen_count);
}

/* the descriptor */

WASI_P2_FN void wasi_filesystem_types_descriptor_drop(wasi_p2_state *s, uint32_t handle) {
    wasi_p2_descriptor_get(s, handle);
    wasi_p2_table_drop(s, handle, WASI_P2_KIND_DESCRIPTOR);
}

WASI_P2_FN void wasi_filesystem_types_directory_entry_stream_drop(wasi_p2_state *s, uint32_t handle) {
    wasi_p2_table_get(s, handle, WASI_P2_KIND_DIRECTORY_ENTRY_STREAM);
    wasi_p2_table_drop(s, handle, WASI_P2_KIND_DIRECTORY_ENTRY_STREAM);
}

/* result<handle, error-code>: a code, or a handle */
WASI_P2_FN void wasi_p2_handle_result(wasi_p2_state *s, uint32_t comp, uint32_t retptr, int rc, uint32_t handle) {
    if (rc != WASI_P2_OK) {
        wasi_p2_fs_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u32(s, comp, retptr + 4, handle);
}

WASI_P2_FN void wasi_p2_stream_of(wasi_p2_state *s, uint32_t comp, uint32_t retptr, uint32_t self, uint64_t pos, int output) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    int rc = wasi_p2_need(d, output ? WASI_P2_WRITE : WASI_P2_READ);
    wasi_p2_handle_result(s, comp, retptr, rc, rc == WASI_P2_OK ? wasi_p2_file_stream_new(s, d->fd, pos, output) : 0);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_read_via_stream(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t offset, uint32_t retptr) {
    wasi_p2_stream_of(s, comp, retptr, self, offset, 0);
}
WASI_P2_FN void wasi_filesystem_types_descriptor_write_via_stream(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t offset, uint32_t retptr) {
    wasi_p2_stream_of(s, comp, retptr, self, offset, 1);
}
WASI_P2_FN void wasi_filesystem_types_descriptor_append_via_stream(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_stream_of(s, comp, retptr, self, 0, 2);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_advise(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t offset, uint64_t length, uint32_t advice,
                                                        uint32_t retptr) {
    (void)offset, (void)length, (void)advice;
    wasi_p2_descriptor_get(s, self); /* only a hint: accepted, and nothing done */
    wasi_p2_status(s, comp, retptr, WASI_P2_OK);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_sync_data(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
#ifdef __APPLE__
    int r = fsync(d->fd);
#else
    int r = fdatasync(d->fd);
#endif
    wasi_p2_status(s, comp, retptr, r < 0 ? wasi_p2_fail() : WASI_P2_OK);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_sync(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    wasi_p2_status(s, comp, retptr, fsync(d->fd) < 0 ? wasi_p2_fail() : WASI_P2_OK);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_get_flags(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u8(s, comp, retptr + 1, (uint8_t)d->flags);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_get_type(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    struct stat st;
    if (fstat(d->fd, &st) < 0) {
        wasi_p2_fs_fail(s, comp, retptr, retptr + 1, wasi_p2_fail());
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u8(s, comp, retptr + 1, wasi_p2_type_of(st.st_mode));
}

WASI_P2_FN void wasi_filesystem_types_descriptor_set_size(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t size, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    int rc = wasi_p2_need(d, WASI_P2_WRITE);
    if (rc == WASI_P2_OK && ftruncate(d->fd, (off_t)size) < 0) rc = wasi_p2_fail();
    wasi_p2_status(s, comp, retptr, rc);
}

/* new-timestamp: 0 no-change, 1 now, 2 timestamp */
WASI_P2_FN int64_t wasi_p2_new_time(uint32_t tag, uint64_t seconds, uint32_t nanos, int64_t current_ns, int64_t now_ns) {
    if (tag == 0) return current_ns;
    if (tag == 1) return now_ns;
    return (int64_t)seconds * 1000000000LL + nanos;
}

WASI_P2_FN struct timespec wasi_p2_ns_ts(int64_t ns) {
    struct timespec t;
    t.tv_sec = (time_t)(ns / 1000000000LL);
    t.tv_nsec = (long)(ns % 1000000000LL);
    return t;
}

WASI_P2_FN void wasi_filesystem_types_descriptor_set_times(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t a_tag, uint64_t a_seconds, uint32_t a_nanos,
                                                           uint32_t m_tag, uint64_t m_seconds, uint32_t m_nanos, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    int rc = wasi_p2_need(d, d->is_dir ? WASI_P2_MUTATE : WASI_P2_WRITE);
    if (rc == WASI_P2_OK) {
        struct stat st;
        if (fstat(d->fd, &st) < 0) {
            rc = wasi_p2_fail();
        } else {
            int64_t now = (int64_t)s->wall_ns(s);
            struct timespec ts[2] = {wasi_p2_ns_ts(wasi_p2_new_time(a_tag, a_seconds, a_nanos, wasi_p2_ts_ns(WASI_P2_ATIME(st)), now)),
                                     wasi_p2_ns_ts(wasi_p2_new_time(m_tag, m_seconds, m_nanos, wasi_p2_ts_ns(WASI_P2_MTIME(st)), now))};
            if (futimens(d->fd, ts) < 0) rc = wasi_p2_fail();
        }
    }
    wasi_p2_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_read(wasi_p2_state *s, uint32_t comp, uint32_t self, uint64_t length, uint64_t offset, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    int rc = wasi_p2_need(d, WASI_P2_READ);
    uint64_t want = length < WASI_P2_READ_CAP ? length : WASI_P2_READ_CAP;
    uint8_t *buf = (uint8_t *)malloc(want ? (size_t)want : 1);
    if (!buf) s->trap(s, "out of memory");
    ssize_t n = 0;
    if (rc == WASI_P2_OK) {
        n = pread(d->fd, buf, (size_t)want, (off_t)offset);
        if (n < 0) rc = wasi_p2_fail();
    }
    if (rc != WASI_P2_OK) {
        free(buf);
        wasi_p2_fs_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    uint32_t ptr = wasi_p2_alloc(s, comp, 1, (uint32_t)n);
    if (n) memcpy(wasi_p2_mem(s, comp, ptr, (uint32_t)n), buf, (size_t)n);
    free(buf);
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u32(s, comp, retptr + 4, ptr);
    wasi_p2_store_u32(s, comp, retptr + 8, (uint32_t)n);
    wasi_p2_store_u8(s, comp, retptr + 12, (uint8_t)(n == 0)); /* end of file is when nothing was read (as in Wasmtime) */
}

WASI_P2_FN void wasi_filesystem_types_descriptor_write(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t ptr, uint32_t length, uint64_t offset,
                                                       uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    const uint8_t *data = wasi_p2_mem(s, comp, ptr, length);
    int rc = wasi_p2_need(d, WASI_P2_WRITE);
    uint32_t done = 0;
    while (rc == WASI_P2_OK && done < length) {
        ssize_t n = pwrite(d->fd, data + done, length - done, (off_t)(offset + done));
        if (n < 0) {
            if (errno == EINTR) continue;
            rc = wasi_p2_fail();
        } else {
            done += (uint32_t)n;
        }
    }
    if (rc != WASI_P2_OK) {
        wasi_p2_fs_fail(s, comp, retptr, retptr + 8, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_store_u64(s, comp, retptr + 8, length);
}

WASI_P2_FN int wasi_p2_name_cmp(const void *a, const void *b) {
    return strcmp(*(char *const *)a, *(char *const *)b); /* the names are sorted with their types: see below */
}

WASI_P2_FN void wasi_filesystem_types_descriptor_read_directory(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    if (!d->is_dir) {
        wasi_p2_handle_result(s, comp, retptr, WASI_P2_E_NOT_DIRECTORY, 0);
        return;
    }
    int dupfd = dup(d->fd);
    DIR *dir = dupfd < 0 ? NULL : fdopendir(dupfd);
    if (!dir) {
        int rc = wasi_p2_fail();
        if (dupfd >= 0) close(dupfd);
        wasi_p2_handle_result(s, comp, retptr, rc, 0);
        return;
    }
    rewinddir(dir);
    uint32_t count = 0, capacity = 16;
    char **names = (char **)malloc(capacity * sizeof *names);
    if (!names) s->trap(s, "out of memory");
    struct dirent *e;
    while ((e = readdir(dir)) != NULL) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        if (count == capacity) {
            capacity *= 2;
            names = (char **)realloc(names, capacity * sizeof *names);
            if (!names) s->trap(s, "out of memory");
        }
        names[count] = strdup(e->d_name);
        if (!names[count]) s->trap(s, "out of memory");
        count++;
    }
    closedir(dir);
    qsort(names, count, sizeof *names, wasi_p2_name_cmp);
    wasi_p2_dir_entries *ent = (wasi_p2_dir_entries *)calloc(1, sizeof *ent);
    uint8_t *types = (uint8_t *)malloc(count ? count : 1);
    if (!ent || !types) s->trap(s, "out of memory");
    uint32_t kept = 0;
    for (uint32_t i = 0; i < count; i++) {
        struct stat st;
        if (fstatat(d->fd, names[i], &st, AT_SYMLINK_NOFOLLOW) < 0) { /* gone since the listing */
            free(names[i]);
            continue;
        }
        names[kept] = names[i];
        types[kept++] = wasi_p2_type_of(st.st_mode);
    }
    ent->count = kept, ent->names = names, ent->types = types;
    wasi_p2_handle_result(s, comp, retptr, WASI_P2_OK, wasi_p2_table_new(s, WASI_P2_KIND_DIRECTORY_ENTRY_STREAM, ent, wasi_p2_dir_entries_destroy));
}

WASI_P2_FN void wasi_filesystem_types_directory_entry_stream_read_directory_entry(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_dir_entries *e = (wasi_p2_dir_entries *)wasi_p2_table_get(s, self, WASI_P2_KIND_DIRECTORY_ENTRY_STREAM)->obj;
    wasi_p2_ok(s, comp, retptr);
    if (e->pos >= e->count) {
        wasi_p2_store_u8(s, comp, retptr + 4, 0);
        return;
    }
    uint32_t i = e->pos++;
    wasi_p2_store_u8(s, comp, retptr + 4, 1);
    wasi_p2_store_u8(s, comp, retptr + 8, e->types[i]);
    wasi_p2_string(s, comp, e->names[i], retptr + 12);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_stat(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    struct stat st;
    if (fstat(d->fd, &st) < 0) {
        wasi_p2_fs_fail(s, comp, retptr, retptr + 8, wasi_p2_fail());
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_write_stat(s, comp, retptr + 8, &st);
}

/* the directory descriptor `self` and the path, walked: WASI_P2_OK or the code */
WASI_P2_FN int wasi_p2_begin(wasi_p2_state *s, uint32_t comp, wasi_p2_walk *w, uint32_t self, uint32_t ptr, uint32_t length, int follow, uint32_t need,
                             wasi_p2_descriptor **out) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    const uint8_t *path = wasi_p2_mem(s, comp, ptr, length);
    *out = d;
    if (need) {
        int rc = wasi_p2_need(d, need);
        if (rc != WASI_P2_OK) return rc;
    }
    if (!d->is_dir) return WASI_P2_E_NOT_DIRECTORY;
    return wasi_p2_walk_path(w, d->fd, path, length, follow);
}

WASI_P2_FN int wasi_p2_stat_at_rc(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t path_flags, uint32_t ptr, uint32_t length, struct stat *st) {
    wasi_p2_walk w;
    wasi_p2_descriptor *d;
    int rc = wasi_p2_begin(s, comp, &w, self, ptr, length, path_flags & WASI_P2_SYMLINK_FOLLOW, 0, &d);
    if (rc != WASI_P2_OK) return rc;
    rc = fstatat(w.dir, w.leaf, st, AT_SYMLINK_NOFOLLOW) < 0 ? wasi_p2_fail() : WASI_P2_OK;
    wasi_p2_walk_close(&w);
    return rc;
}

WASI_P2_FN void wasi_filesystem_types_descriptor_stat_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t path_flags, uint32_t ptr, uint32_t length,
                                                         uint32_t retptr) {
    struct stat st;
    int rc = wasi_p2_stat_at_rc(s, comp, self, path_flags, ptr, length, &st);
    if (rc != WASI_P2_OK) {
        wasi_p2_fs_fail(s, comp, retptr, retptr + 8, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_write_stat(s, comp, retptr + 8, &st);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_set_times_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t path_flags, uint32_t ptr, uint32_t length,
                                                              uint32_t a_tag, uint64_t a_seconds, uint32_t a_nanos, uint32_t m_tag, uint64_t m_seconds,
                                                              uint32_t m_nanos, uint32_t retptr) {
    wasi_p2_walk w;
    wasi_p2_descriptor *d;
    int rc = wasi_p2_begin(s, comp, &w, self, ptr, length, path_flags & WASI_P2_SYMLINK_FOLLOW, WASI_P2_MUTATE, &d);
    if (rc == WASI_P2_OK) {
        struct stat st;
        if (fstatat(w.dir, w.leaf, &st, AT_SYMLINK_NOFOLLOW) < 0) {
            rc = wasi_p2_fail();
        } else {
            int64_t now = (int64_t)s->wall_ns(s);
            struct timespec ts[2] = {wasi_p2_ns_ts(wasi_p2_new_time(a_tag, a_seconds, a_nanos, wasi_p2_ts_ns(WASI_P2_ATIME(st)), now)),
                                     wasi_p2_ns_ts(wasi_p2_new_time(m_tag, m_seconds, m_nanos, wasi_p2_ts_ns(WASI_P2_MTIME(st)), now))};
            if (utimensat(w.dir, w.leaf, ts, AT_SYMLINK_NOFOLLOW) < 0) rc = wasi_p2_fail();
        }
        wasi_p2_walk_close(&w);
    }
    wasi_p2_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_link_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t old_flags, uint32_t old_ptr, uint32_t old_len,
                                                         uint32_t new_dir, uint32_t new_ptr, uint32_t new_len, uint32_t retptr) {
    wasi_p2_walk w1, w2;
    wasi_p2_descriptor *d, *n = wasi_p2_descriptor_get(s, new_dir);
    int rc = wasi_p2_begin(s, comp, &w1, self, old_ptr, old_len, old_flags & WASI_P2_SYMLINK_FOLLOW, WASI_P2_MUTATE, &d);
    if (rc == WASI_P2_OK) {
        rc = wasi_p2_need(n, WASI_P2_MUTATE);
        if (rc == WASI_P2_OK) rc = wasi_p2_begin(s, comp, &w2, new_dir, new_ptr, new_len, 0, WASI_P2_MUTATE, &n);
        if (rc == WASI_P2_OK) {
            if (linkat(w1.dir, w1.leaf, w2.dir, w2.leaf, 0) < 0) rc = wasi_p2_fail();
            wasi_p2_walk_close(&w2);
        }
        wasi_p2_walk_close(&w1);
    }
    wasi_p2_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_open_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t path_flags, uint32_t ptr, uint32_t length,
                                                         uint32_t open_flags, uint32_t flags, uint32_t retptr) {
    wasi_p2_descriptor *d = wasi_p2_descriptor_get(s, self);
    const uint8_t *path = wasi_p2_mem(s, comp, ptr, length);
    int rc = WASI_P2_OK;
    uint32_t handle = 0;
    if (!d->is_dir) {
        rc = WASI_P2_E_NOT_DIRECTORY;
    } else if ((flags & (WASI_P2_WRITE | WASI_P2_MUTATE)) && !(d->flags & WASI_P2_MUTATE)) {
        rc = WASI_P2_E_READ_ONLY; /* a descriptor cannot hand out more than it has (as the WIT says for open-at) */
    } else if ((flags & WASI_P2_READ) && !(d->flags & WASI_P2_READ)) {
        rc = WASI_P2_E_NOT_PERMITTED;
    } else if ((open_flags & (WASI_P2_CREATE | WASI_P2_TRUNCATE)) && !(d->flags & WASI_P2_MUTATE)) {
        rc = WASI_P2_E_READ_ONLY;
    } else {
        int oflags = O_NOFOLLOW | O_CLOEXEC;
        oflags |= (flags & WASI_P2_READ) && (flags & WASI_P2_WRITE) ? O_RDWR : (flags & WASI_P2_WRITE) ? O_WRONLY : O_RDONLY;
        if (open_flags & WASI_P2_CREATE) oflags |= O_CREAT;
        if (open_flags & WASI_P2_DIRECTORY) oflags |= O_DIRECTORY;
        if (open_flags & WASI_P2_EXCLUSIVE) oflags |= O_EXCL;
        if (open_flags & WASI_P2_TRUNCATE) oflags |= O_TRUNC;
        if (flags & WASI_P2_FILE_SYNC) oflags |= O_SYNC;
        if (flags & WASI_P2_DATA_SYNC) oflags |= O_DSYNC;
        wasi_p2_walk w;
        rc = wasi_p2_walk_path(&w, d->fd, path, length, path_flags & WASI_P2_SYMLINK_FOLLOW);
        if (rc == WASI_P2_OK) {
            int fd = openat(w.dir, w.leaf, oflags, 0666);
            if (fd < 0) {
                rc = wasi_p2_fail();
                char probe[1];
                size_t leaf_len = strlen(w.leaf);
                /* a link is not entered when links are not followed (O_NOFOLLOW) */
                if (errno == ENOTDIR && (open_flags & WASI_P2_DIRECTORY) && leaf_len && w.leaf[leaf_len - 1] != '/' && readlinkat(w.dir, w.leaf, probe, sizeof probe) >= 0)
                    rc = WASI_P2_E_LOOP;
            } else {
                struct stat st;
                int is_dir = fstat(fd, &st) == 0 && S_ISDIR(st.st_mode);
                handle = wasi_p2_descriptor_new(s, fd, flags, is_dir);
            }
            wasi_p2_walk_close(&w);
        }
    }
    wasi_p2_handle_result(s, comp, retptr, rc, handle);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_readlink_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t ptr, uint32_t length, uint32_t retptr) {
    wasi_p2_walk w;
    wasi_p2_descriptor *d;
    char target[WASI_P2_PATH_MAX];
    int rc = wasi_p2_begin(s, comp, &w, self, ptr, length, 0, 0, &d);
    ssize_t n = 0;
    if (rc == WASI_P2_OK) {
        n = readlinkat(w.dir, w.leaf, target, sizeof target - 1);
        if (n < 0) rc = wasi_p2_fail();
        wasi_p2_walk_close(&w);
    }
    if (rc != WASI_P2_OK) {
        wasi_p2_fs_fail(s, comp, retptr, retptr + 4, rc);
        return;
    }
    target[n] = '\0';
    if (target[0] == '/') { /* an absolute or rooted target is not shown */
        wasi_p2_fs_fail(s, comp, retptr, retptr + 4, WASI_P2_E_NOT_PERMITTED);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    wasi_p2_string(s, comp, target, retptr + 4);
}

typedef int (*wasi_p2_name_op)(int dir, const char *leaf, const void *arg);

WASI_P2_FN void wasi_p2_at(wasi_p2_state *s, uint32_t comp, uint32_t retptr, uint32_t self, uint32_t ptr, uint32_t length, wasi_p2_name_op op, const void *arg) {
    wasi_p2_walk w;
    wasi_p2_descriptor *d;
    int rc = wasi_p2_begin(s, comp, &w, self, ptr, length, 0, WASI_P2_MUTATE, &d);
    if (rc == WASI_P2_OK) {
        rc = op(w.dir, w.leaf, arg);
        wasi_p2_walk_close(&w);
    }
    wasi_p2_status(s, comp, retptr, rc);
}

WASI_P2_FN int wasi_p2_op_mkdir(int dir, const char *leaf, const void *arg) {
    (void)arg;
    return mkdirat(dir, leaf, 0777) < 0 ? wasi_p2_fail() : WASI_P2_OK;
}
WASI_P2_FN int wasi_p2_op_rmdir(int dir, const char *leaf, const void *arg) {
    (void)arg;
    return unlinkat(dir, leaf, AT_REMOVEDIR) < 0 ? wasi_p2_fail() : WASI_P2_OK;
}
WASI_P2_FN int wasi_p2_op_unlink(int dir, const char *leaf, const void *arg) {
    (void)arg;
    if (unlinkat(dir, leaf, 0) == 0) return WASI_P2_OK;
    int e = errno;
    struct stat st;
    if (e == EPERM && fstatat(dir, leaf, &st, AT_SYMLINK_NOFOLLOW) == 0 && S_ISDIR(st.st_mode)) return WASI_P2_E_IS_DIRECTORY; /* some systems say EPERM */
    return wasi_p2_errno_code(e);
}
WASI_P2_FN int wasi_p2_op_symlink(int dir, const char *leaf, const void *arg) {
    return symlinkat((const char *)arg, dir, leaf) < 0 ? wasi_p2_fail() : WASI_P2_OK;
}

WASI_P2_FN void wasi_filesystem_types_descriptor_create_directory_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t ptr, uint32_t length,
                                                                     uint32_t retptr) {
    wasi_p2_at(s, comp, retptr, self, ptr, length, wasi_p2_op_mkdir, NULL);
}
WASI_P2_FN void wasi_filesystem_types_descriptor_remove_directory_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t ptr, uint32_t length,
                                                                     uint32_t retptr) {
    wasi_p2_at(s, comp, retptr, self, ptr, length, wasi_p2_op_rmdir, NULL);
}
WASI_P2_FN void wasi_filesystem_types_descriptor_unlink_file_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t ptr, uint32_t length, uint32_t retptr) {
    wasi_p2_at(s, comp, retptr, self, ptr, length, wasi_p2_op_unlink, NULL);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_rename_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t old_ptr, uint32_t old_len, uint32_t new_dir,
                                                           uint32_t new_ptr, uint32_t new_len, uint32_t retptr) {
    wasi_p2_walk w1, w2;
    wasi_p2_descriptor *d, *n = wasi_p2_descriptor_get(s, new_dir);
    int rc = wasi_p2_begin(s, comp, &w1, self, old_ptr, old_len, 0, WASI_P2_MUTATE, &d);
    if (rc == WASI_P2_OK) {
        rc = wasi_p2_need(n, WASI_P2_MUTATE);
        if (rc == WASI_P2_OK) rc = wasi_p2_begin(s, comp, &w2, new_dir, new_ptr, new_len, 0, WASI_P2_MUTATE, &n);
        if (rc == WASI_P2_OK) {
            if (renameat(w1.dir, w1.leaf, w2.dir, w2.leaf) < 0) rc = wasi_p2_fail();
            wasi_p2_walk_close(&w2);
        }
        wasi_p2_walk_close(&w1);
    }
    wasi_p2_status(s, comp, retptr, rc);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_symlink_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t old_ptr, uint32_t old_len, uint32_t new_ptr,
                                                            uint32_t new_len, uint32_t retptr) {
    const uint8_t *target = wasi_p2_mem(s, comp, old_ptr, old_len);
    if (memchr(target, 0, old_len) || (old_len && target[0] == '/')) {
        wasi_p2_descriptor_get(s, self);
        wasi_p2_status(s, comp, retptr, memchr(target, 0, old_len) ? WASI_P2_E_INVALID : WASI_P2_E_NOT_PERMITTED);
        return;
    }
    char *copy = (char *)malloc((size_t)old_len + 1);
    if (!copy) s->trap(s, "out of memory");
    memcpy(copy, target, old_len);
    copy[old_len] = '\0';
    wasi_p2_at(s, comp, retptr, self, new_ptr, new_len, wasi_p2_op_symlink, copy);
    free(copy);
}

WASI_P2_FN uint32_t wasi_filesystem_types_descriptor_is_same_object(wasi_p2_state *s, uint32_t self, uint32_t other) {
    struct stat a, b;
    int r1 = fstat(wasi_p2_descriptor_get(s, self)->fd, &a), r2 = fstat(wasi_p2_descriptor_get(s, other)->fd, &b);
    return (uint32_t)(r1 == 0 && r2 == 0 && a.st_dev == b.st_dev && a.st_ino == b.st_ino);
}

WASI_P2_FN uint64_t wasi_p2_fnv(const uint64_t *values, int n) {
    uint64_t h = 0xCBF29CE484222325ULL;
    for (int i = 0; i < n; i++)
        for (int b = 0; b < 8; b++) h = (h ^ ((values[i] >> (8 * b)) & 0xFF)) * 0x100000001B3ULL;
    return h;
}

WASI_P2_FN void wasi_p2_hash_result(wasi_p2_state *s, uint32_t comp, uint32_t retptr, int rc, const struct stat *st) {
    if (rc != WASI_P2_OK) {
        wasi_p2_fs_fail(s, comp, retptr, retptr + 8, rc);
        return;
    }
    wasi_p2_ok(s, comp, retptr);
    /* `upper` names the object (device, inode); `lower` also takes in what changes when it is modified (size, modification time): FNV-1a 64 as the Python twin */
    uint64_t lower[4] = {(uint64_t)st->st_size, (uint64_t)wasi_p2_ts_ns(WASI_P2_MTIME(*st)), (uint64_t)st->st_dev, (uint64_t)st->st_ino};
    uint64_t upper[2] = {(uint64_t)st->st_dev, (uint64_t)st->st_ino};
    wasi_p2_store_u64(s, comp, retptr + 8, wasi_p2_fnv(lower, 4));
    wasi_p2_store_u64(s, comp, retptr + 16, wasi_p2_fnv(upper, 2));
}

WASI_P2_FN void wasi_filesystem_types_descriptor_metadata_hash(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t retptr) {
    struct stat st;
    wasi_p2_hash_result(s, comp, retptr, fstat(wasi_p2_descriptor_get(s, self)->fd, &st) < 0 ? wasi_p2_fail() : WASI_P2_OK, &st);
}

WASI_P2_FN void wasi_filesystem_types_descriptor_metadata_hash_at(wasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t path_flags, uint32_t ptr,
                                                                  uint32_t length, uint32_t retptr) {
    struct stat st;
    wasi_p2_hash_result(s, comp, retptr, wasi_p2_stat_at_rc(s, comp, self, path_flags, ptr, length, &st), &st);
}

WASI_P2_FN void wasi_filesystem_types_filesystem_error_code(wasi_p2_state *s, uint32_t comp, uint32_t err, uint32_t retptr) {
    wasi_p2_error *e = (wasi_p2_error *)wasi_p2_table_get(s, err, WASI_P2_KIND_ERROR)->obj;
    if (e->code < 0) {
        wasi_p2_store_u8(s, comp, retptr, 0);
        return;
    }
    wasi_p2_store_u8(s, comp, retptr, 1);
    wasi_p2_store_u8(s, comp, retptr + 1, (uint8_t)e->code);
}

#endif /* WASI_P2_FILESYSTEM_H */
