"""wasi:filesystem for the host of examples/wasi2_unbundled, over Python's `os` (the example host has none).

`FsHost` adds `preopens`, `wasi:filesystem/types` (descriptors, the streams of a file, directory listing, stat, rename, ...), `wasi:cli/environment`,
`wasi:cli/exit`, `wasi:random` and the two clock resolutions to `wasi2demo.host.Host`. The layouts are those of the canonical ABI of WASI 0.2.12:
a `result<T, error-code>` has its tag at 0 and `T` or the code at the alignment of `T` (1, 4 or 8).
Not a sandbox: a path with `..` can leave a preopened directory.
"""

import errno
import fcntl
import os
import stat as st
import time

from wasi2demo.host import Host, _Pollable, _Std


class Exit(Exception):
    def __init__(self, code):
        self.code = code


class _Fd:
    def __init__(self, fd):
        self.fd = fd


class _FileIn:
    def __init__(self, fd, offset):
        self.fd, self.offset = fd, offset


class _FileOut:
    def __init__(self, fd, offset):
        self.fd, self.offset = fd, offset  # offset None: append


class _Dir:
    def __init__(self, entries):
        self.entries = iter(entries)


# the error-code enum of wasi:filesystem, in order
_CODES = [
    "access",
    "would-block",
    "already",
    "bad-descriptor",
    "busy",
    "deadlock",
    "quota",
    "exist",
    "file-too-large",
    "illegal-byte-sequence",
    "in-progress",
    "interrupted",
    "invalid",
    "io",
    "is-directory",
    "loop",
    "too-many-links",
    "message-size",
    "name-too-long",
    "no-device",
    "no-entry",
    "no-lock",
    "insufficient-memory",
    "insufficient-space",
    "not-directory",
    "not-empty",
    "not-recoverable",
    "unsupported",
    "no-tty",
    "no-such-device",
    "overflow",
    "not-permitted",
    "pipe",
    "read-only",
    "invalid-seek",
    "text-file-busy",
    "cross-device",
]
_ERRNO = {
    errno.EACCES: "access",
    errno.EAGAIN: "would-block",
    errno.EBADF: "bad-descriptor",
    errno.EBUSY: "busy",
    errno.EEXIST: "exist",
    errno.EFBIG: "file-too-large",
    errno.EINTR: "interrupted",
    errno.EINVAL: "invalid",
    errno.EIO: "io",
    errno.EISDIR: "is-directory",
    errno.ELOOP: "loop",
    errno.EMLINK: "too-many-links",
    errno.ENAMETOOLONG: "name-too-long",
    errno.ENOENT: "no-entry",
    errno.ENOMEM: "insufficient-memory",
    errno.ENOSPC: "insufficient-space",
    errno.ENOTDIR: "not-directory",
    errno.ENOTEMPTY: "not-empty",
    errno.ENOSYS: "unsupported",
    errno.EPERM: "not-permitted",
    errno.EPIPE: "pipe",
    errno.EROFS: "read-only",
    errno.ESPIPE: "invalid-seek",
    errno.EXDEV: "cross-device",
    errno.ENODEV: "no-such-device",
    errno.ENOTSUP: "unsupported",
}


def _code(e):
    return _CODES.index(_ERRNO.get(e.errno, "io"))


def _type(mode):
    for test, n in (
        (st.S_ISBLK, 1),
        (st.S_ISCHR, 2),
        (st.S_ISDIR, 3),
        (st.S_ISFIFO, 4),
        (st.S_ISLNK, 5),
        (st.S_ISREG, 6),
        (st.S_ISSOCK, 7),
    ):
        if test(mode):
            return n
    return 0


def fs(offset):
    """The method returns normally -> ok (tag 0); an OSError -> err with its code at `offset` of the result (the last argument)."""

    def deco(f):
        def call(self, *a):
            result = a[-1]
            try:
                f(self, *a)
                self._byte(result, 0)
            except OSError as e:
                self._byte(result, 1)
                self._byte(result + offset, _code(e))

        return call

    return deco


_FS = {
    "[method]descriptor.read-via-stream": "read_via_stream",
    "[method]descriptor.write-via-stream": "write_via_stream",
    "[method]descriptor.append-via-stream": "append_via_stream",
    "[method]descriptor.advise": "ok1",
    "[method]descriptor.sync-data": "ok1",
    "[method]descriptor.sync": "ok1",
    "[method]descriptor.get-flags": "get_flags",
    "[method]descriptor.set-size": "set_size",
    "[method]descriptor.set-times": "ok1",
    "[method]descriptor.set-times-at": "ok1",
    "[method]descriptor.read": "dread",
    "[method]descriptor.write": "dwrite",
    "[method]descriptor.read-directory": "read_directory",
    "[method]descriptor.create-directory-at": "create_directory_at",
    "[method]descriptor.stat": "stat",
    "[method]descriptor.stat-at": "stat_at",
    "[method]descriptor.link-at": "link_at",
    "[method]descriptor.open-at": "open_at",
    "[method]descriptor.readlink-at": "readlink_at",
    "[method]descriptor.remove-directory-at": "remove_directory_at",
    "[method]descriptor.rename-at": "rename_at",
    "[method]descriptor.symlink-at": "symlink_at",
    "[method]descriptor.unlink-file-at": "unlink_file_at",
    "[method]descriptor.metadata-hash": "metadata_hash",
    "[method]descriptor.metadata-hash-at": "metadata_hash_at",
    "[method]directory-entry-stream.read-directory-entry": "read_directory_entry",
}


class FsHost(Host):
    def __init__(self, args, env, preopens, **kw):
        super().__init__(**kw)
        self.args, self.env, self.preopens = (
            args,
            env,
            preopens,
        )  # preopens: [(directory of the host, name for the program)]

    def table(self):
        """(module without version, import name) -> function, for everything written here."""
        t = {
            (m, n): getattr(self, f)
            for (m, n), f in {
                ("wasi:cli/environment", "get-arguments"): "get_arguments",
                ("wasi:cli/environment", "get-environment"): "get_environment",
                ("wasi:cli/exit", "exit"): "exit_",
                ("wasi:cli/exit", "exit-with-code"): "exit_code",
                ("wasi:filesystem/preopens", "get-directories"): "get_directories",
                ("wasi:random/random", "get-random-bytes"): "random_bytes",
                ("wasi:clocks/monotonic-clock", "resolution"): "resolution_i64",
                ("wasi:clocks/monotonic-clock", "subscribe-instant"): "subscribe_instant",
                ("wasi:clocks/wall-clock", "resolution"): "wall_resolution",
                ("wasi:io/streams", "[method]input-stream.read"): "read",
                ("wasi:io/streams", "[method]input-stream.subscribe"): "subscribe_input",
                ("wasi:io/streams", "[method]output-stream.write"): "write",
                ("wasi:io/streams", "[method]output-stream.check-write"): "check_write",
            }.items()
        }
        for n, f in _FS.items():
            t[("wasi:filesystem/types", n)] = getattr(self, f)
        return t

    # ---- helpers
    def _string(self, ptr, n):
        return bytes(self._memory()[ptr : ptr + n]).decode()

    def _path(self, ptr, n):
        return self._string(ptr, n) or "."  # a preopened directory itself arrives as an empty path

    def _put_string(self, s, at):
        b = s.encode() if isinstance(s, str) else s
        p = self._instance.cabi_realloc(0, 0, 1, max(len(b), 1))
        self._memory()[p : p + len(b)] = b
        self._u32(at, p)
        self._u32(at + 4, len(b))

    def _fd(self, h):
        return self._handles[h].fd

    # ---- cli, random, clocks
    def _str_list(self, items, result, pair=False):
        size = 16 if pair else 8
        base = self._instance.cabi_realloc(0, 0, 4, max(size * len(items), 1))
        for k, it in enumerate(items):
            for j, s in enumerate(it if pair else (it,)):
                self._put_string(s, base + k * size + 8 * j)
        self._u32(result, base)
        self._u32(result + 4, len(items))

    def get_arguments(self, result):
        self._str_list(self.args, result)

    def get_environment(self, result):
        self._str_list(list(self.env.items()), result, pair=True)

    def exit_(self, status):
        raise Exit(status)

    def exit_code(self, code):
        raise Exit(code)

    def random_bytes(self, n, result):
        b = os.urandom(n)
        self._put_string(b, result)

    def resolution_i64(self):
        return 1

    def wall_resolution(self, result):
        self._u64(result, 0)
        self._u32(result + 8, 1)

    def subscribe_instant(self, instant):
        return self._new(_Pollable(lambda: time.monotonic_ns() >= instant))

    def get_directories(self, result):
        base = self._instance.cabi_realloc(0, 0, 4, max(12 * len(self.preopens), 1))
        for k, (path, name) in enumerate(self.preopens):
            self._u32(base + 12 * k, self._new(_Fd(os.open(path, os.O_RDONLY | os.O_DIRECTORY))))
            self._put_string(name, base + 12 * k + 4)
        self._u32(result, base)
        self._u32(result + 4, len(self.preopens))

    # ---- streams: the std ones from Host, plus the files
    def read(self, stream, length, result):
        s = self._handles[stream]
        if isinstance(s, (_Std, _FileIn)):
            data = b""
            if isinstance(s, _FileIn):
                data = os.pread(s.fd, min(length, 65536), s.offset)
                s.offset += len(data)
            if isinstance(s, _Std) or (data == b"" and length > 0):
                self._byte(result, 1)
                self._byte(result + 4, 1)  # err(closed)
                return
            p = self._instance.cabi_realloc(0, 0, 1, max(len(data), 1))
            self._memory()[p : p + len(data)] = data
            self._byte(result, 0)
            self._u32(result + 4, p)
            self._u32(result + 8, len(data))
        else:
            super().read(stream, length, result)

    def subscribe_input(self, stream):
        if isinstance(self._handles[stream], (_FileIn, _Std)):
            return self._new(_Pollable(lambda: True))
        return super().subscribe_input(stream)

    def write(self, stream, pointer, length, result):
        s = self._handles[stream]
        if isinstance(s, _FileOut):
            data = bytes(self._memory()[pointer : pointer + length])
            if s.offset is None:
                os.write(s.fd, data)
            else:
                os.pwrite(s.fd, data, s.offset)
                s.offset += len(data)
            self._byte(result, 0)
        else:
            super().write(stream, pointer, length, result)

    @fs(4)
    def read_via_stream(self, d, offset, result):
        self._u32(result + 4, self._new(_FileIn(self._fd(d), offset)))

    @fs(4)
    def write_via_stream(self, d, offset, result):
        self._u32(result + 4, self._new(_FileOut(self._fd(d), offset)))

    @fs(4)
    def append_via_stream(self, d, result):
        self._u32(result + 4, self._new(_FileOut(self._fd(d), None)))

    def ok1(self, *a):
        self._byte(a[-1], 0)

    @fs(1)
    def get_flags(self, d, result):
        mode = fcntl.fcntl(self._fd(d), fcntl.F_GETFL) & os.O_ACCMODE
        self._byte(
            result + 1, {os.O_RDONLY: 1, os.O_WRONLY: 2, os.O_RDWR: 3}[mode]
        )  # descriptor-flags: read = 1, write = 2

    @fs(1)
    def set_size(self, d, size, result):
        os.ftruncate(self._fd(d), size)

    @fs(4)
    def dread(self, d, length, offset, result):
        data = os.pread(self._fd(d), length, offset)
        self._put_string(data, result + 4)
        self._byte(result + 12, 1 if len(data) < length else 0)

    @fs(8)
    def dwrite(self, d, ptr, n, offset, result):
        self._u64(result + 8, os.pwrite(self._fd(d), bytes(self._memory()[ptr : ptr + n]), offset))

    @fs(4)
    def read_directory(self, d, result):
        entries = [(e.name, _type(e.stat(follow_symlinks=False).st_mode)) for e in os.scandir(self._fd(d))]
        self._u32(result + 4, self._new(_Dir(entries)))

    def read_directory_entry(self, stream, result):
        try:
            entry = next(self._handles[stream].entries, None)
        except OSError as e:
            self._byte(result, 1)
            self._byte(result + 4, _code(e))
            return
        self._byte(result, 0)
        if entry is None:
            self._byte(result + 4, 0)
        else:
            self._byte(result + 4, 1)
            self._byte(result + 8, entry[1])
            self._put_string(entry[0], result + 12)

    @fs(1)
    def create_directory_at(self, d, p, n, result):
        os.mkdir(self._path(p, n), dir_fd=self._fd(d))

    def _put_stat(self, s, result):
        self._byte(result + 8, _type(s.st_mode))
        self._u64(result + 16, s.st_nlink)
        self._u64(result + 24, s.st_size)
        for k, ns in enumerate((s.st_atime_ns, s.st_mtime_ns, s.st_ctime_ns)):
            o = result + 32 + 24 * k
            self._byte(o, 1)
            self._u64(o + 8, ns // 10**9)
            self._u32(o + 16, ns % 10**9)

    @fs(8)
    def stat(self, d, result):
        self._put_stat(os.fstat(self._fd(d)), result)

    @fs(8)
    def stat_at(self, d, flags, p, n, result):
        self._put_stat(os.stat(self._path(p, n), dir_fd=self._fd(d), follow_symlinks=bool(flags & 1)), result)

    @fs(4)
    def open_at(self, d, pflags, p, n, oflags, dflags, result):
        f = os.O_RDWR if dflags & 2 and dflags & 1 else os.O_WRONLY if dflags & 2 else os.O_RDONLY
        f |= (
            (os.O_CREAT if oflags & 1 else 0)
            | (os.O_DIRECTORY if oflags & 2 else 0)
            | (os.O_EXCL if oflags & 4 else 0)
            | (os.O_TRUNC if oflags & 8 else 0)
        )
        f |= 0 if pflags & 1 else os.O_NOFOLLOW
        self._u32(result + 4, self._new(_Fd(os.open(self._path(p, n), f | os.O_CLOEXEC, 0o666, dir_fd=self._fd(d)))))

    @fs(4)
    def readlink_at(self, d, p, n, result):
        self._put_string(os.readlink(self._path(p, n), dir_fd=self._fd(d)), result + 4)

    @fs(1)
    def remove_directory_at(self, d, p, n, result):
        os.rmdir(self._path(p, n), dir_fd=self._fd(d))

    @fs(1)
    def unlink_file_at(self, d, p, n, result):
        os.unlink(self._path(p, n), dir_fd=self._fd(d))

    @fs(1)
    def rename_at(self, d, p, n, d2, p2, n2, result):
        os.rename(self._path(p, n), self._path(p2, n2), src_dir_fd=self._fd(d), dst_dir_fd=self._fd(d2))

    @fs(1)
    def symlink_at(self, d, p, n, p2, n2, result):
        os.symlink(self._path(p, n), self._path(p2, n2), dir_fd=self._fd(d))

    @fs(1)
    def link_at(self, d, flags, p, n, d2, p2, n2, result):
        os.link(
            self._path(p, n),
            self._path(p2, n2),
            src_dir_fd=self._fd(d),
            dst_dir_fd=self._fd(d2),
            follow_symlinks=bool(flags & 1),
        )

    def _hash(self, s, result):
        self._u64(result + 8, s.st_ino)
        self._u64(result + 16, s.st_dev)

    @fs(8)
    def metadata_hash(self, d, result):
        self._hash(os.fstat(self._fd(d)), result)

    @fs(8)
    def metadata_hash_at(self, d, flags, p, n, result):
        self._hash(os.stat(self._path(p, n), dir_fd=self._fd(d), follow_symlinks=bool(flags & 1)), result)
