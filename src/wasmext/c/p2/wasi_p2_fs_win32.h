/* The system calls of wasi_p2_filesystem.h on Windows, in Win32 and the C library (the twin of the Windows branch of p2/wasi_p2_filesystem.py, where it is described).
 * Included by that file. There is no openat: a directory is its path (UTF-8, with the \\?\ prefix so that the system changes no name), a file is a C-library descriptor with
 * its path, and the walk goes below the path by name; a link is a symbolic link or a junction. The check and the use are two steps, so another process that changes the
 * tree in between is not stopped. Link with nothing else (bcrypt is for the random bytes of the core). */
#ifndef WASI_P2_FS_WIN32_H
#define WASI_P2_FS_WIN32_H

#include <fcntl.h>
#include <io.h>
#include <winioctl.h>

typedef const char *wasi_p2_dirref; /* the path of the directory */

#ifndef IO_REPARSE_TAG_SYMLINK
#define IO_REPARSE_TAG_SYMLINK 0xA000000CL
#endif
#ifndef IO_REPARSE_TAG_MOUNT_POINT
#define IO_REPARSE_TAG_MOUNT_POINT 0xA0000003L
#endif
#ifndef SYMBOLIC_LINK_FLAG_DIRECTORY
#define SYMBOLIC_LINK_FLAG_DIRECTORY 0x1
#endif
#ifndef SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE
#define SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE 0x2
#endif
#define WASI_P2_SHARE (FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
#define WASI_P2_EPOCH 116444736000000000ULL /* FILETIME (100 ns since 1601) of 1970 */

/* UTF-8 and UTF-16 */

WASI_P2_FN wchar_t *wasi_p2_wide(const char *text) {
    int n = MultiByteToWideChar(CP_UTF8, 0, text, -1, NULL, 0);
    if (n <= 0) return NULL;
    wchar_t *w = (wchar_t *)malloc((size_t)n * sizeof *w);
    if (w && MultiByteToWideChar(CP_UTF8, 0, text, -1, w, n) <= 0) {
        free(w);
        return NULL;
    }
    return w;
}

/* UTF-16 of `n` units to UTF-8 in `out` (NUL-terminated); returns 0 if it does not fit */
WASI_P2_FN int wasi_p2_utf8(const wchar_t *w, int n, char *out, size_t cap) {
    int k = WideCharToMultiByte(CP_UTF8, 0, w, n, out, (int)cap - 1, NULL, NULL);
    if (k <= 0 && n > 0) return 0;
    out[k] = '\0';
    return 1;
}

/* the error-code of a Win32 error */
WASI_P2_FN int wasi_p2_win_code(DWORD e) {
    switch (e) {
    case ERROR_FILE_NOT_FOUND: case ERROR_PATH_NOT_FOUND: case ERROR_INVALID_DRIVE: case ERROR_BAD_NETPATH: case ERROR_BAD_NET_NAME: return WASI_P2_E_NO_ENTRY;
    case ERROR_ACCESS_DENIED: case ERROR_SHARING_VIOLATION: case ERROR_LOCK_VIOLATION: case ERROR_NETWORK_ACCESS_DENIED: return WASI_P2_E_ACCESS;
    case ERROR_ALREADY_EXISTS: case ERROR_FILE_EXISTS: return WASI_P2_E_EXIST;
    case ERROR_DIR_NOT_EMPTY: return WASI_P2_E_NOT_EMPTY;
    case ERROR_DIRECTORY: return WASI_P2_E_NOT_DIRECTORY;
    case ERROR_NOT_SAME_DEVICE: return WASI_P2_E_CROSS_DEVICE;
    case ERROR_PRIVILEGE_NOT_HELD: return WASI_P2_E_NOT_PERMITTED;
    case ERROR_TOO_MANY_LINKS: return WASI_P2_E_TOO_MANY_LINKS;
    case ERROR_DISK_FULL: case ERROR_HANDLE_DISK_FULL: return WASI_P2_E_INSUFFICIENT_SPACE;
    case ERROR_FILENAME_EXCED_RANGE: return WASI_P2_E_NAME_TOO_LONG;
    case ERROR_NOT_ENOUGH_MEMORY: case ERROR_OUTOFMEMORY: return WASI_P2_E_INSUFFICIENT_MEMORY;
    case ERROR_INVALID_HANDLE: return WASI_P2_E_BAD_DESCRIPTOR;
    case ERROR_WRITE_PROTECT: return WASI_P2_E_READ_ONLY;
    case ERROR_CANT_RESOLVE_FILENAME: return WASI_P2_E_LOOP;
    case ERROR_NOT_A_REPARSE_POINT: case ERROR_INVALID_NAME: case ERROR_BAD_PATHNAME: case ERROR_INVALID_PARAMETER: case ERROR_NO_UNICODE_TRANSLATION:
        return WASI_P2_E_INVALID;
    case ERROR_BROKEN_PIPE: case ERROR_NO_DATA: return WASI_P2_E_PIPE;
    default: return WASI_P2_E_IO;
    }
}

WASI_P2_FN int wasi_p2_win_last(void) { return wasi_p2_win_code(GetLastError()); }

WASI_P2_FN int64_t wasi_p2_ft_ns(FILETIME t) {
    uint64_t ticks = ((uint64_t)t.dwHighDateTime << 32) | t.dwLowDateTime;
    return ticks > WASI_P2_EPOCH ? (int64_t)((ticks - WASI_P2_EPOCH) * 100u) : 0;
}

WASI_P2_FN FILETIME wasi_p2_ns_ft(int64_t ns) {
    uint64_t ticks = (uint64_t)(ns < 0 ? 0 : ns) / 100u + WASI_P2_EPOCH;
    FILETIME t;
    t.dwLowDateTime = (DWORD)(ticks & 0xffffffffu);
    t.dwHighDateTime = (DWORD)(ticks >> 32);
    return t;
}

/* paths */

/* a name that is one name: no separator and no colon (a drive, or a stream of a file) */
WASI_P2_FN int wasi_p2_name_ok(const char *name) { return name[0] != '\0' && !strpbrk(name, "\\/:"); }

/* the place a name stands for: the directory itself for ".", with no trailing slash; a slash after something that is not a directory is `not-directory` */
WASI_P2_FN int wasi_p2_win_stat_path(const char *path, int follow, wasi_p2_stat *out);

WASI_P2_FN int wasi_p2_target(const char *dir, const char *leaf, char *out, size_t cap) {
    size_t n = strlen(leaf);
    int slash = 0;
    while (n && leaf[n - 1] == '/') n--, slash = 1;
    if (n == 0 || (n == 1 && leaf[0] == '.')) {
        if (strlen(dir) >= cap) return WASI_P2_E_NAME_TOO_LONG;
        strcpy(out, dir);
    } else {
        char bare[WASI_P2_NAME_MAX + 2];
        if (n > WASI_P2_NAME_MAX) return WASI_P2_E_NAME_TOO_LONG;
        memcpy(bare, leaf, n);
        bare[n] = '\0';
        if (!wasi_p2_name_ok(bare)) return WASI_P2_E_INVALID;
        if (strlen(dir) + 1 + n >= cap) return WASI_P2_E_NAME_TOO_LONG;
        snprintf(out, cap, "%s\\%s", dir, bare);
    }
    if (slash) {
        wasi_p2_stat st;
        if (wasi_p2_win_stat_path(out, 1, &st) == WASI_P2_OK && st.type != WASI_P2_T_DIRECTORY) return WASI_P2_E_NOT_DIRECTORY;
    }
    return WASI_P2_OK;
}

/* stat */

WASI_P2_FN int wasi_p2_win_stat_handle(HANDLE h, wasi_p2_stat *out) {
    BY_HANDLE_FILE_INFORMATION bi;
    FILE_ATTRIBUTE_TAG_INFO ti;
    if (!GetFileInformationByHandle(h, &bi)) return wasi_p2_win_last();
    ti.FileAttributes = 0, ti.ReparseTag = 0;
    GetFileInformationByHandleEx(h, FileAttributeTagInfo, &ti, sizeof ti);
    if ((bi.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) && ti.ReparseTag == IO_REPARSE_TAG_SYMLINK) {
        out->type = WASI_P2_T_SYMLINK;
    } else if (bi.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
        out->type = WASI_P2_T_DIRECTORY;
    } else {
        switch (GetFileType(h)) {
        case FILE_TYPE_DISK: out->type = WASI_P2_T_REGULAR; break;
        case FILE_TYPE_CHAR: out->type = WASI_P2_T_CHAR; break;
        case FILE_TYPE_PIPE: out->type = WASI_P2_T_FIFO; break;
        default: out->type = WASI_P2_T_UNKNOWN; break;
        }
    }
    out->nlink = bi.nNumberOfLinks;
    out->size = ((uint64_t)bi.nFileSizeHigh << 32) | bi.nFileSizeLow;
    out->dev = bi.dwVolumeSerialNumber;
    out->ino = ((uint64_t)bi.nFileIndexHigh << 32) | bi.nFileIndexLow;
    out->atime_ns = wasi_p2_ft_ns(bi.ftLastAccessTime);
    out->mtime_ns = wasi_p2_ft_ns(bi.ftLastWriteTime);
    out->ctime_ns = wasi_p2_ft_ns(bi.ftCreationTime);
    return WASI_P2_OK;
}

WASI_P2_FN HANDLE wasi_p2_win_open(const char *path, DWORD access, int follow, int *rc) {
    wchar_t *w = wasi_p2_wide(path);
    if (!w) {
        *rc = WASI_P2_E_INVALID;
        return INVALID_HANDLE_VALUE;
    }
    HANDLE h = CreateFileW(w, access, WASI_P2_SHARE, NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | (follow ? 0 : FILE_FLAG_OPEN_REPARSE_POINT), NULL);
    if (h == INVALID_HANDLE_VALUE) *rc = wasi_p2_win_last();
    free(w);
    return h;
}

WASI_P2_FN int wasi_p2_win_stat_path(const char *path, int follow, wasi_p2_stat *out) {
    int rc = WASI_P2_OK;
    HANDLE h = wasi_p2_win_open(path, FILE_READ_ATTRIBUTES, follow, &rc);
    if (h == INVALID_HANDLE_VALUE) return rc;
    rc = wasi_p2_win_stat_handle(h, out);
    CloseHandle(h);
    return rc;
}

/* a symbolic link or a junction */
WASI_P2_FN int wasi_p2_win_is_link(const char *path) {
    int rc = WASI_P2_OK;
    HANDLE h = wasi_p2_win_open(path, FILE_READ_ATTRIBUTES, 0, &rc);
    if (h == INVALID_HANDLE_VALUE) return 0;
    FILE_ATTRIBUTE_TAG_INFO ti;
    ti.FileAttributes = 0, ti.ReparseTag = 0;
    int link = GetFileInformationByHandleEx(h, FileAttributeTagInfo, &ti, sizeof ti) && (ti.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) &&
               (ti.ReparseTag == IO_REPARSE_TAG_SYMLINK || ti.ReparseTag == IO_REPARSE_TAG_MOUNT_POINT);
    CloseHandle(h);
    return link;
}

WASI_P2_FN int wasi_p2_sys_lstat(wasi_p2_dirref dir, const char *leaf, wasi_p2_stat *out) {
    char full[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(dir, leaf, full, sizeof full);
    return rc != WASI_P2_OK ? rc : wasi_p2_win_stat_path(full, 0, out);
}

WASI_P2_FN int wasi_p2_sys_fstat(const wasi_p2_descriptor *d, wasi_p2_stat *out) {
    if (d->fd >= 0) {
        HANDLE h = (HANDLE)_get_osfhandle(d->fd);
        return h == INVALID_HANDLE_VALUE ? WASI_P2_E_BAD_DESCRIPTOR : wasi_p2_win_stat_handle(h, out);
    }
    return wasi_p2_win_stat_path(d->path, 1, out);
}

/* links */

typedef struct {
    ULONG tag;
    USHORT data_length, reserved;
    USHORT substitute_offset, substitute_length, print_offset, print_length;
    union {
        struct {
            ULONG flags;
            WCHAR path[1];
        } symlink;
        struct {
            WCHAR path[1];
        } mount;
    } u;
} wasi_p2_reparse;

/* the target of a link as the Python twin shows it: '/' for separators, a leading '/' for a drive or a rooted target (which the callers refuse) */
WASI_P2_FN int wasi_p2_sys_readlink(wasi_p2_dirref dir, const char *leaf, char *out, size_t cap) {
    char full[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(dir, leaf, full, sizeof full);
    if (rc != WASI_P2_OK) return rc;
    HANDLE h = wasi_p2_win_open(full, FILE_READ_ATTRIBUTES, 0, &rc);
    if (h == INVALID_HANDLE_VALUE) return rc;
    union {
        wasi_p2_reparse r;
        BYTE raw[MAXIMUM_REPARSE_DATA_BUFFER_SIZE];
    } buf;
    DWORD got = 0;
    BOOL ok = DeviceIoControl(h, FSCTL_GET_REPARSE_POINT, NULL, 0, buf.raw, sizeof buf.raw, &got, NULL);
    CloseHandle(h);
    if (!ok) return wasi_p2_win_last();
    const WCHAR *path;
    if (buf.r.tag == IO_REPARSE_TAG_SYMLINK) path = buf.r.u.symlink.path;
    else if (buf.r.tag == IO_REPARSE_TAG_MOUNT_POINT) path = buf.r.u.mount.path;
    else return WASI_P2_E_INVALID;
    const WCHAR *name = path + buf.r.substitute_offset / sizeof(WCHAR);
    int n = buf.r.substitute_length / (int)sizeof(WCHAR);
    if (n >= 4 && name[0] == L'\\' && name[1] == L'?' && name[2] == L'?' && name[3] == L'\\') name += 4, n -= 4;
    char text[WASI_P2_PATH_MAX];
    if (!wasi_p2_utf8(name, n, text, sizeof text)) return WASI_P2_E_NAME_TOO_LONG;
    for (char *p = text; *p; p++)
        if (*p == '\\') *p = '/';
    int drive = text[0] && text[1] == ':' && ((text[0] >= 'a' && text[0] <= 'z') || (text[0] >= 'A' && text[0] <= 'Z'));
    if (strlen(text) + (drive ? 1 : 0) >= cap) return WASI_P2_E_NAME_TOO_LONG;
    snprintf(out, cap, "%s%s", drive ? "/" : "", text);
    return WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_mkdir(wasi_p2_dirref dir, const char *leaf) {
    char full[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(dir, leaf, full, sizeof full);
    if (rc != WASI_P2_OK) return rc;
    wchar_t *w = wasi_p2_wide(full);
    if (!w) return WASI_P2_E_INVALID;
    rc = CreateDirectoryW(w, NULL) ? WASI_P2_OK : wasi_p2_win_last();
    free(w);
    return rc;
}

WASI_P2_FN int wasi_p2_sys_rmdir(wasi_p2_dirref dir, const char *leaf) {
    char full[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(dir, leaf, full, sizeof full);
    if (rc != WASI_P2_OK) return rc;
    wchar_t *w = wasi_p2_wide(full);
    if (!w) return WASI_P2_E_INVALID;
    rc = RemoveDirectoryW(w) ? WASI_P2_OK : wasi_p2_win_last();
    free(w);
    return rc;
}

WASI_P2_FN int wasi_p2_sys_unlink(wasi_p2_dirref dir, const char *leaf) {
    char full[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(dir, leaf, full, sizeof full);
    if (rc != WASI_P2_OK) return rc;
    wchar_t *w = wasi_p2_wide(full);
    if (!w) return WASI_P2_E_INVALID;
    if (DeleteFileW(w)) {
        rc = WASI_P2_OK;
    } else {
        DWORD e = GetLastError();
        rc = wasi_p2_win_code(e);
        if (e == ERROR_ACCESS_DENIED) {
            DWORD attrs = GetFileAttributesW(w);
            if (attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY)) {
                if ((attrs & FILE_ATTRIBUTE_REPARSE_POINT) && RemoveDirectoryW(w)) rc = WASI_P2_OK; /* a link to a directory is removed as a file is */
                else if (!(attrs & FILE_ATTRIBUTE_REPARSE_POINT)) rc = WASI_P2_E_IS_DIRECTORY;
            }
        }
    }
    free(w);
    return rc;
}

WASI_P2_FN int wasi_p2_sys_rename(wasi_p2_dirref d1, const char *l1, wasi_p2_dirref d2, const char *l2) {
    char a[WASI_P2_PATH_MAX], b[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(d1, l1, a, sizeof a);
    if (rc == WASI_P2_OK) rc = wasi_p2_target(d2, l2, b, sizeof b);
    if (rc != WASI_P2_OK) return rc;
    wchar_t *wa = wasi_p2_wide(a), *wb = wasi_p2_wide(b);
    rc = wa && wb ? (MoveFileExW(wa, wb, MOVEFILE_REPLACE_EXISTING) ? WASI_P2_OK : wasi_p2_win_last()) : WASI_P2_E_INVALID;
    free(wa), free(wb);
    return rc;
}

WASI_P2_FN int wasi_p2_sys_link(wasi_p2_dirref d1, const char *l1, wasi_p2_dirref d2, const char *l2) {
    char a[WASI_P2_PATH_MAX], b[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(d1, l1, a, sizeof a);
    if (rc == WASI_P2_OK) rc = wasi_p2_target(d2, l2, b, sizeof b);
    if (rc != WASI_P2_OK) return rc;
    wchar_t *wa = wasi_p2_wide(a), *wb = wasi_p2_wide(b);
    rc = wa && wb ? (CreateHardLinkW(wb, wa, NULL) ? WASI_P2_OK : wasi_p2_win_last()) : WASI_P2_E_INVALID;
    free(wa), free(wb);
    return rc;
}

/* where `target` (with '\') leads, below `dir`, as a path without . and ..: to tell a link to a directory from a link to a file */
WASI_P2_FN int wasi_p2_target_is_dir(const char *dir, const char *target) {
    char joined[WASI_P2_PATH_MAX], out[WASI_P2_PATH_MAX];
    const char *base = strncmp(dir, "\\\\?\\", 4) == 0 ? dir + 4 : dir;
    if (strlen(base) + 1 + strlen(target) >= sizeof joined) return 0;
    snprintf(joined, sizeof joined, "%s\\%s", base, target);
    size_t len = 0;
    char *save = NULL;
    (void)save;
    /* normalize: split at '\' and drop "." and ".." */
    const char *p = joined;
    size_t root = 0;
    if (p[0] && p[1] == ':') {
        out[0] = p[0], out[1] = ':', out[2] = '\0';
        len = root = 2;
        p += 2;
    }
    while (*p) {
        while (*p == '\\') p++;
        const char *e = p;
        while (*e && *e != '\\') e++;
        size_t n = (size_t)(e - p);
        if (n == 0) break;
        if (n == 1 && p[0] == '.') {
        } else if (n == 2 && p[0] == '.' && p[1] == '.') {
            while (len > root && out[len - 1] != '\\') len--;
            if (len > root) len--;
            out[len] = '\0';
        } else if (len + 1 + n < sizeof out) {
            out[len++] = '\\';
            memcpy(out + len, p, n);
            len += n;
            out[len] = '\0';
        }
        p = e;
    }
    char full[WASI_P2_PATH_MAX + 8];  /* the prefix and what is in `out` */
    snprintf(full, sizeof full, "\\\\?\\%s", out);
    wchar_t *w = wasi_p2_wide(full);
    DWORD attrs = w ? GetFileAttributesW(w) : INVALID_FILE_ATTRIBUTES;
    free(w);
    return attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY);
}

WASI_P2_FN int wasi_p2_sys_symlink(const char *target, wasi_p2_dirref dir, const char *leaf) {
    char full[WASI_P2_PATH_MAX], text[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(dir, leaf, full, sizeof full);
    if (rc != WASI_P2_OK) return rc;
    if (strlen(target) >= sizeof text) return WASI_P2_E_NAME_TOO_LONG;
    strcpy(text, target);
    for (char *p = text; *p; p++)
        if (*p == '/') *p = '\\';
    wchar_t *wf = wasi_p2_wide(full), *wt = wasi_p2_wide(text);
    DWORD flags = SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE | (wasi_p2_target_is_dir(dir, text) ? SYMBOLIC_LINK_FLAG_DIRECTORY : 0);
    rc = WASI_P2_OK;
    if (!wf || !wt) rc = WASI_P2_E_INVALID;
    else if (!CreateSymbolicLinkW(wf, wt, flags)) rc = wasi_p2_win_last();
    free(wf), free(wt);
    return rc;
}

/* times (a link is followed, as os.utime does on Windows) */

WASI_P2_FN int wasi_p2_win_set_times_path(const char *path, int64_t atime_ns, int64_t mtime_ns) {
    int rc = WASI_P2_OK;
    HANDLE h = wasi_p2_win_open(path, FILE_WRITE_ATTRIBUTES, 1, &rc);
    if (h == INVALID_HANDLE_VALUE) return rc;
    FILETIME a = wasi_p2_ns_ft(atime_ns), m = wasi_p2_ns_ft(mtime_ns);
    rc = SetFileTime(h, NULL, &a, &m) ? WASI_P2_OK : wasi_p2_win_last();
    CloseHandle(h);
    return rc;
}

WASI_P2_FN int wasi_p2_sys_set_times(wasi_p2_dirref dir, const char *leaf, int64_t atime_ns, int64_t mtime_ns) {
    char full[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(dir, leaf, full, sizeof full);
    return rc != WASI_P2_OK ? rc : wasi_p2_win_set_times_path(full, atime_ns, mtime_ns);
}

WASI_P2_FN int wasi_p2_sys_set_times_fd(const wasi_p2_descriptor *d, int64_t atime_ns, int64_t mtime_ns) {
    return wasi_p2_win_set_times_path(d->path, atime_ns, mtime_ns);
}

/* open */

WASI_P2_FN int wasi_p2_sys_open_at(wasi_p2_dirref dir, const char *leaf, uint32_t open_flags, uint32_t flags, wasi_p2_descriptor *out) {
    char full[WASI_P2_PATH_MAX];
    int rc = wasi_p2_target(dir, leaf, full, sizeof full);
    if (rc != WASI_P2_OK) return rc;
    wasi_p2_stat st;
    int have = wasi_p2_win_stat_path(full, 0, &st);
    if (have != WASI_P2_OK && have != WASI_P2_E_NO_ENTRY) return have;
    int exists = have == WASI_P2_OK;
    size_t leaf_len = strlen(leaf);
    if (exists && (st.type == WASI_P2_T_SYMLINK || wasi_p2_win_is_link(full))) return WASI_P2_E_LOOP; /* links are not followed here (O_NOFOLLOW) */
    if (exists && st.type == WASI_P2_T_DIRECTORY) {
        if ((open_flags & WASI_P2_CREATE) && (open_flags & WASI_P2_EXCLUSIVE)) return WASI_P2_E_EXIST;
        if ((flags & WASI_P2_WRITE) || (open_flags & (WASI_P2_CREATE | WASI_P2_TRUNCATE))) return WASI_P2_E_IS_DIRECTORY;
        out->fd = -1, out->is_dir = 1;
        out->path = (char *)malloc(strlen(full) + 1);
        if (!out->path) return WASI_P2_E_INSUFFICIENT_MEMORY;
        strcpy(out->path, full);
        return WASI_P2_OK;
    }
    if ((open_flags & WASI_P2_DIRECTORY) || (leaf_len && leaf[leaf_len - 1] == '/')) return exists ? WASI_P2_E_NOT_DIRECTORY : WASI_P2_E_NO_ENTRY;
    int oflags = _O_BINARY;
    oflags |= (flags & WASI_P2_READ) && (flags & WASI_P2_WRITE) ? _O_RDWR : (flags & WASI_P2_WRITE) ? _O_WRONLY : _O_RDONLY;
    if (open_flags & WASI_P2_CREATE) oflags |= _O_CREAT;
    if (open_flags & WASI_P2_EXCLUSIVE) oflags |= _O_EXCL;
    if (open_flags & WASI_P2_TRUNCATE) oflags |= _O_TRUNC;
    wchar_t *w = wasi_p2_wide(full);
    if (!w) return WASI_P2_E_INVALID;
    int fd = _wopen(w, oflags, _S_IREAD | _S_IWRITE);
    free(w);
    if (fd < 0) return wasi_p2_fail();
    out->fd = fd, out->is_dir = 0;
    out->path = (char *)malloc(strlen(full) + 1);
    if (!out->path) {
        _close(fd);
        return WASI_P2_E_INSUFFICIENT_MEMORY;
    }
    strcpy(out->path, full);
    return WASI_P2_OK;
}

/* the real path of a directory, as UTF-8 with the \\?\ prefix and no trailing separator */
WASI_P2_FN int wasi_p2_sys_open_directory(const char *path, wasi_p2_descriptor *out) {
    int rc = WASI_P2_OK;
    HANDLE h = wasi_p2_win_open(path, FILE_READ_ATTRIBUTES, 1, &rc);
    if (h == INVALID_HANDLE_VALUE) return rc;
    wchar_t wide[WASI_P2_PATH_MAX];
    DWORD n = GetFinalPathNameByHandleW(h, wide, WASI_P2_PATH_MAX, VOLUME_NAME_DOS);
    CloseHandle(h);
    if (n == 0 || n >= WASI_P2_PATH_MAX) return n ? WASI_P2_E_NAME_TOO_LONG : wasi_p2_win_last();
    while (n > 3 && (wide[n - 1] == L'\\' || wide[n - 1] == L'/')) n--;
    char text[WASI_P2_PATH_MAX];
    if (!wasi_p2_utf8(wide, (int)n, text, sizeof text)) return WASI_P2_E_NAME_TOO_LONG;
    out->path = (char *)malloc(strlen(text) + 1);
    if (!out->path) return WASI_P2_E_INSUFFICIENT_MEMORY;
    strcpy(out->path, text);
    out->fd = -1, out->is_dir = 1;
    return WASI_P2_OK;
}

WASI_P2_FN void wasi_p2_sys_close(wasi_p2_descriptor *d) {
    if (d->fd >= 0) _close(d->fd);
    d->fd = -1;
    free(d->path);
    d->path = NULL;
}

/* file contents by offset */

WASI_P2_FN int64_t wasi_p2_sys_pread(int fd, void *buf, size_t n, uint64_t off, int *rc) {
    if (fd < 0) {
        *rc = WASI_P2_E_IS_DIRECTORY;
        return -1;
    }
    if (_lseeki64(fd, (__int64)off, SEEK_SET) < 0) {
        *rc = wasi_p2_fail();
        return -1;
    }
    int r = _read(fd, buf, (unsigned)(n > 0x40000000u ? 0x40000000u : n));
    if (r < 0) *rc = wasi_p2_fail();
    return r;
}

WASI_P2_FN int64_t wasi_p2_sys_pwrite(int fd, const void *buf, size_t n, uint64_t off, int *rc) {
    if (fd < 0) {
        *rc = WASI_P2_E_IS_DIRECTORY;
        return -1;
    }
    if (_lseeki64(fd, (__int64)off, SEEK_SET) < 0) {
        *rc = wasi_p2_fail();
        return -1;
    }
    int r = _write(fd, buf, (unsigned)(n > 0x40000000u ? 0x40000000u : n));
    if (r < 0) *rc = wasi_p2_fail();
    return r;
}

WASI_P2_FN int wasi_p2_sys_size(int fd, uint64_t *size) {
    __int64 n = fd < 0 ? -1 : _filelengthi64(fd);
    if (n < 0) return fd < 0 ? WASI_P2_E_BAD_DESCRIPTOR : wasi_p2_fail();
    *size = (uint64_t)n;
    return WASI_P2_OK;
}

WASI_P2_FN int wasi_p2_sys_dup(int fd) { return _dup(fd); }
WASI_P2_FN void wasi_p2_sys_closefd(int fd) {
    if (fd >= 0) _close(fd);
}
WASI_P2_FN int wasi_p2_sys_ftruncate(int fd, uint64_t size) {
    if (fd < 0) return WASI_P2_E_BAD_DESCRIPTOR;
    errno_t e = _chsize_s(fd, (__int64)size);
    return e ? wasi_p2_errno_code((int)e) : WASI_P2_OK;
}
WASI_P2_FN int wasi_p2_sys_fsync(const wasi_p2_descriptor *d, int data_only) {
    (void)data_only;
    return d->fd < 0 || _commit(d->fd) == 0 ? WASI_P2_OK : wasi_p2_fail(); /* a directory on Windows has nothing to flush */
}

WASI_P2_FN int wasi_p2_name_cmp(const void *a, const void *b) { return strcmp(*(char *const *)a, *(char *const *)b); }

/* the names of a directory, sorted, without . and .., with their types; the caller frees them */
WASI_P2_FN int wasi_p2_sys_list(const wasi_p2_descriptor *d, char ***names_out, uint8_t **types_out, uint32_t *count_out, wasi_p2_state *s) {
    char pattern[WASI_P2_PATH_MAX];
    if (strlen(d->path) + 3 >= sizeof pattern) return WASI_P2_E_NAME_TOO_LONG;
    snprintf(pattern, sizeof pattern, "%s\\*", d->path);
    wchar_t *w = wasi_p2_wide(pattern);
    if (!w) return WASI_P2_E_INVALID;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileExW(w, FindExInfoBasic, &fd, FindExSearchNameMatch, NULL, 0);
    free(w);
    if (h == INVALID_HANDLE_VALUE) return wasi_p2_win_last();
    uint32_t count = 0, capacity = 16;
    char **names = (char **)malloc(capacity * sizeof *names);
    if (!names) s->trap(s, "out of memory");
    do {
        if (!wcscmp(fd.cFileName, L".") || !wcscmp(fd.cFileName, L"..")) continue;
        char text[WASI_P2_NAME_MAX * 4 + 4];
        if (!wasi_p2_utf8(fd.cFileName, (int)wcslen(fd.cFileName), text, sizeof text)) continue;
        if (count == capacity) {
            capacity *= 2;
            names = (char **)realloc(names, capacity * sizeof *names);
            if (!names) s->trap(s, "out of memory");
        }
        names[count] = (char *)malloc(strlen(text) + 1);
        if (!names[count]) s->trap(s, "out of memory");
        strcpy(names[count++], text);
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    qsort(names, count, sizeof *names, wasi_p2_name_cmp);
    uint8_t *types = (uint8_t *)malloc(count ? count : 1);
    if (!types) s->trap(s, "out of memory");
    uint32_t kept = 0;
    for (uint32_t i = 0; i < count; i++) {
        wasi_p2_stat st;
        if (wasi_p2_sys_lstat(d->path, names[i], &st) != WASI_P2_OK) { /* gone since the listing */
            free(names[i]);
            continue;
        }
        names[kept] = names[i];
        types[kept++] = st.type;
    }
    *names_out = names, *types_out = types, *count_out = kept;
    return WASI_P2_OK;
}

/* the walk of a path, confined below a directory (see the Python twin): `dir` and `leaf` are the path of the directory that holds the last name and that name ("." for none) */
typedef struct {
    const char *dir; /* points into buf */
    char leaf[WASI_P2_NAME_MAX + 2];
    char buf[WASI_P2_PATH_MAX];
    size_t lens[WASI_P2_MAX_DEPTH + 2]; /* the length of the path at each depth */
    int depth;
} wasi_p2_walk;

WASI_P2_FN void wasi_p2_walk_close(wasi_p2_walk *w) { w->depth = 0; }

WASI_P2_FN int wasi_p2_walk_path(wasi_p2_walk *w, const wasi_p2_descriptor *base_d, const uint8_t *path, uint32_t len, int follow) {
    char work[WASI_P2_PATH_MAX], name[WASI_P2_NAME_MAX + 2], target[WASI_P2_PATH_MAX];
    int links = 0;
    w->depth = 0;
    w->dir = w->buf;
    if (strlen(base_d->path) >= sizeof w->buf) return WASI_P2_E_NAME_TOO_LONG;
    strcpy(w->buf, base_d->path);
    w->lens[0] = strlen(w->buf);
    if (memchr(path, 0, len)) return WASI_P2_E_INVALID;
    if (len == 0) return WASI_P2_E_NO_ENTRY; /* an empty name is no name (POSIX; Wasmtime says the same) */
    if (path[0] == '/') return WASI_P2_E_NOT_PERMITTED;
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
        if (clen > WASI_P2_NAME_MAX) return WASI_P2_E_NAME_TOO_LONG;
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
            if (w->depth == 0) return WASI_P2_E_NOT_PERMITTED;
            w->depth--;
            w->buf[w->lens[w->depth]] = '\0';
            if (last) {
                strcpy(w->leaf, ".");
                break;
            }
            cur = rest;
            continue;
        }
        if (!wasi_p2_name_ok(name)) return WASI_P2_E_INVALID;
        if (last) {
            if (!follow) {
                /* a slash after a name makes a link there followed: the walk follows it itself, below the base */
                /* (the whole target: this readlink says "too long" and not a cut, as readlinkat does) */
                if (!(slash && wasi_p2_sys_readlink(w->buf, name, target, sizeof target) == WASI_P2_OK)) {
                    strcpy(w->leaf, name);
                    if (slash) strcat(w->leaf, "/");
                    break;
                }
            }
        } else {
            if (w->depth > WASI_P2_MAX_DEPTH) return WASI_P2_E_NAME_TOO_LONG;
            char full[WASI_P2_PATH_MAX];
            int rc = wasi_p2_target(w->buf, name, full, sizeof full);
            if (rc != WASI_P2_OK) return rc;
            wasi_p2_stat st;
            rc = wasi_p2_win_stat_path(full, 0, &st);
            if (rc != WASI_P2_OK) return rc; /* it is not there, or cannot be seen */
            if (st.type == WASI_P2_T_DIRECTORY && !wasi_p2_win_is_link(full)) {
                size_t n = strlen(full);
                if (n >= sizeof w->buf) return WASI_P2_E_NAME_TOO_LONG;
                memcpy(w->buf, full, n + 1);
                w->lens[++w->depth] = n;
                cur = rest;
                continue;
            }
            /* not a directory we can enter: perhaps a link, which is read below */
        }
        int rc = wasi_p2_sys_readlink(w->buf, name, target, sizeof target);
        if (rc != WASI_P2_OK) {
            if (last) { /* not a link: this is the last name */
                strcpy(w->leaf, name);
                if (slash) strcat(w->leaf, "/");
                break;
            }
            return WASI_P2_E_NOT_DIRECTORY;
        }
        size_t n = strlen(target);
        if (++links > WASI_P2_MAX_LINKS) return WASI_P2_E_LOOP;
        if (target[0] == '/') return WASI_P2_E_NOT_PERMITTED;
        size_t rest_len = strlen(rest);
        if (n + 1 + rest_len >= sizeof work) return WASI_P2_E_NAME_TOO_LONG;
        memmove(work + n + 1, rest, rest_len + 1); /* rest may lie inside work */
        memcpy(work, target, n);
        work[n] = '/';
        if (rest_len == 0 && !slash) work[n] = '\0';
        cur = work;
    }
    return WASI_P2_OK;
}

#endif /* WASI_P2_FS_WIN32_H */
