/* The system calls of wasi_p2_filesystem.h on POSIX: descriptors relative to a directory (openat and the other *at calls). Included by that file; the Windows twin is
 * wasi_p2_fs_win32.h. Every function returns WASI_P2_OK or an error-code (the confinement of paths is in `wasi_p2_walk_path`, described in the Python twin). */
#ifndef WASI_P2_FS_POSIX_H
#define WASI_P2_FS_POSIX_H

#include <dirent.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

typedef int wasi_p2_dirref; /* the descriptor of the directory */

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

WASI_P2_FN void wasi_p2_stat_from(const struct stat *st, wasi_p2_stat *out) {
    out->type = wasi_p2_type_of(st->st_mode);
    out->nlink = (uint64_t)st->st_nlink;
    out->size = (uint64_t)st->st_size;
    out->dev = (uint64_t)st->st_dev;
    out->ino = (uint64_t)st->st_ino;
    out->atime_ns = wasi_p2_ts_ns(WASI_P2_ATIME(*st));
    out->mtime_ns = wasi_p2_ts_ns(WASI_P2_MTIME(*st));
    out->ctime_ns = wasi_p2_ts_ns(WASI_P2_CTIME(*st));
}

WASI_P2_FN int wasi_p2_sys_lstat(wasi_p2_dirref dir, const char *leaf, wasi_p2_stat *out) {
    struct stat st;
    if (fstatat(dir, leaf, &st, AT_SYMLINK_NOFOLLOW) < 0) return wasi_p2_fail();
    wasi_p2_stat_from(&st, out);
    return WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_fstat(const wasi_p2_descriptor *d, wasi_p2_stat *out) {
    struct stat st;
    if (fstat(d->fd, &st) < 0) return wasi_p2_fail();
    wasi_p2_stat_from(&st, out);
    return WASI_P2_OK;
}

/* the target of a link, NUL-terminated */
WASI_P2_FN int wasi_p2_sys_readlink(wasi_p2_dirref dir, const char *leaf, char *out, size_t cap) {
    ssize_t n = readlinkat(dir, leaf, out, cap - 1);
    if (n < 0) return wasi_p2_fail();
    out[n] = '\0';
    return WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_mkdir(wasi_p2_dirref dir, const char *leaf) { return mkdirat(dir, leaf, 0777) < 0 ? wasi_p2_fail() : WASI_P2_OK; }
WASI_P2_FN int wasi_p2_sys_rmdir(wasi_p2_dirref dir, const char *leaf) { return unlinkat(dir, leaf, AT_REMOVEDIR) < 0 ? wasi_p2_fail() : WASI_P2_OK; }

WASI_P2_FN int wasi_p2_sys_unlink(wasi_p2_dirref dir, const char *leaf) {
    if (unlinkat(dir, leaf, 0) == 0) return WASI_P2_OK;
    int e = errno;
    struct stat st;
    if (e == EPERM && fstatat(dir, leaf, &st, AT_SYMLINK_NOFOLLOW) == 0 && S_ISDIR(st.st_mode)) return WASI_P2_E_IS_DIRECTORY; /* some systems say EPERM */
    return wasi_p2_errno_code(e);
}

WASI_P2_FN int wasi_p2_sys_rename(wasi_p2_dirref d1, const char *l1, wasi_p2_dirref d2, const char *l2) {
    return renameat(d1, l1, d2, l2) < 0 ? wasi_p2_fail() : WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_link(wasi_p2_dirref d1, const char *l1, wasi_p2_dirref d2, const char *l2) {
    return linkat(d1, l1, d2, l2, 0) < 0 ? wasi_p2_fail() : WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_symlink(const char *target, wasi_p2_dirref dir, const char *leaf) { return symlinkat(target, dir, leaf) < 0 ? wasi_p2_fail() : WASI_P2_OK; }

WASI_P2_FN struct timespec wasi_p2_ns_ts(int64_t ns) {
    struct timespec t;
    t.tv_sec = (time_t)(ns / 1000000000LL);
    t.tv_nsec = (long)(ns % 1000000000LL);
    return t;
}

WASI_P2_FN int wasi_p2_sys_set_times(wasi_p2_dirref dir, const char *leaf, int64_t atime_ns, int64_t mtime_ns) {
    struct timespec ts[2] = {wasi_p2_ns_ts(atime_ns), wasi_p2_ns_ts(mtime_ns)};
    return utimensat(dir, leaf, ts, AT_SYMLINK_NOFOLLOW) < 0 ? wasi_p2_fail() : WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_set_times_fd(const wasi_p2_descriptor *d, int64_t atime_ns, int64_t mtime_ns) {
    struct timespec ts[2] = {wasi_p2_ns_ts(atime_ns), wasi_p2_ns_ts(mtime_ns)};
    return futimens(d->fd, ts) < 0 ? wasi_p2_fail() : WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_open_at(wasi_p2_dirref dir, const char *leaf, uint32_t open_flags, uint32_t flags, wasi_p2_descriptor *out) {
    int oflags = O_NOFOLLOW | O_CLOEXEC;
    oflags |= (flags & WASI_P2_READ) && (flags & WASI_P2_WRITE) ? O_RDWR : (flags & WASI_P2_WRITE) ? O_WRONLY : O_RDONLY;
    if (open_flags & WASI_P2_CREATE) oflags |= O_CREAT;
    if (open_flags & WASI_P2_DIRECTORY) oflags |= O_DIRECTORY;
    if (open_flags & WASI_P2_EXCLUSIVE) oflags |= O_EXCL;
    if (open_flags & WASI_P2_TRUNCATE) oflags |= O_TRUNC;
    if (flags & WASI_P2_FILE_SYNC) oflags |= O_SYNC;
    if (flags & WASI_P2_DATA_SYNC) oflags |= O_DSYNC;
    int fd = openat(dir, leaf, oflags, 0666);
    if (fd < 0) {
        int rc = wasi_p2_fail();
        char probe[1];
        size_t leaf_len = strlen(leaf);
        /* a link is not entered when links are not followed (O_NOFOLLOW) */
        if (errno == ENOTDIR && (open_flags & WASI_P2_DIRECTORY) && leaf_len && leaf[leaf_len - 1] != '/' && readlinkat(dir, leaf, probe, sizeof probe) >= 0)
            rc = WASI_P2_E_LOOP;
        return rc;
    }
    struct stat st;
    out->fd = fd;
    out->is_dir = fstat(fd, &st) == 0 && S_ISDIR(st.st_mode);
    out->path = NULL;
    return WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_open_directory(const char *path, wasi_p2_descriptor *out) {
    int fd = open(path, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return wasi_p2_fail();
    out->fd = fd, out->is_dir = 1, out->path = NULL;
    return WASI_P2_OK;
}

WASI_P2_FN void wasi_p2_sys_close(wasi_p2_descriptor *d) {
    if (d->fd >= 0) close(d->fd);
    d->fd = -1;
    free(d->path);
    d->path = NULL;
}

/* file contents by offset, on a descriptor: -1 and the code in *rc for a failure */
WASI_P2_FN int64_t wasi_p2_sys_pread(int fd, void *buf, size_t n, uint64_t off, int *rc) {
    ssize_t r = pread(fd, buf, n, (off_t)off);
    if (r < 0) *rc = wasi_p2_fail();
    return r;
}

WASI_P2_FN int64_t wasi_p2_sys_pwrite(int fd, const void *buf, size_t n, uint64_t off, int *rc) {
    for (;;) {
        ssize_t r = pwrite(fd, buf, n, (off_t)off);
        if (r < 0 && errno == EINTR) continue;
        if (r < 0) *rc = wasi_p2_fail();
        return r;
    }
}

WASI_P2_FN int wasi_p2_sys_size(int fd, uint64_t *size) {
    struct stat sb;
    if (fstat(fd, &sb) < 0) return wasi_p2_fail();
    *size = (uint64_t)sb.st_size;
    return WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_dup(int fd) { return dup(fd); }
WASI_P2_FN void wasi_p2_sys_closefd(int fd) {
    if (fd >= 0) close(fd);
}
WASI_P2_FN int wasi_p2_sys_ftruncate(int fd, uint64_t size) { return ftruncate(fd, (off_t)size) < 0 ? wasi_p2_fail() : WASI_P2_OK; }

WASI_P2_FN int wasi_p2_sys_fsync(const wasi_p2_descriptor *d, int data_only) {
#ifdef __APPLE__
    (void)data_only;
    int r = fsync(d->fd);
#else
    int r = data_only ? fdatasync(d->fd) : fsync(d->fd);
#endif
    return r < 0 ? wasi_p2_fail() : WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_name_cmp(const void *a, const void *b) {
    return strcmp(*(char *const *)a, *(char *const *)b); /* the names are sorted with their types: see below */
}

/* the names of a directory, sorted, without . and .., with their types; the caller frees them */
WASI_P2_FN int wasi_p2_sys_list(const wasi_p2_descriptor *d, char ***names_out, uint8_t **types_out, uint32_t *count_out, wasi_p2_state *s) {
    int dupfd = dup(d->fd);
    DIR *dir = dupfd < 0 ? NULL : fdopendir(dupfd);
    if (!dir) {
        int rc = wasi_p2_fail();
        if (dupfd >= 0) close(dupfd);
        return rc;
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
    uint8_t *types = (uint8_t *)malloc(count ? count : 1);
    if (!types) s->trap(s, "out of memory");
    uint32_t kept = 0;
    for (uint32_t i = 0; i < count; i++) {
        wasi_p2_stat st;
        if (wasi_p2_sys_lstat(d->fd, names[i], &st) != WASI_P2_OK) { /* gone since the listing */
            free(names[i]);
            continue;
        }
        names[kept] = names[i];
        types[kept++] = st.type;
    }
    *names_out = names, *types_out = types, *count_out = kept;
    return WASI_P2_OK;
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

WASI_P2_FN int wasi_p2_walk_path(wasi_p2_walk *w, const wasi_p2_descriptor *base_d, const uint8_t *path, uint32_t len, int follow) {
    int base = base_d->fd;
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

#endif /* WASI_P2_FS_POSIX_H */
