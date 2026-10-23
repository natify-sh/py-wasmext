"""wasi:filesystem (32 imports): `preopens` and `types` (the twin of `c/p2/wasi_p2_filesystem.h`). POSIX (descriptors relative to a directory: `dir_fd`) and Windows (below).

**The paths are confined.** A path the guest gives is walked by name, as `wasi_walk` of WASI 0.1 does: every directory on the way is opened with `O_NOFOLLOW` relative to the
one before it; `..` may not go above the directory the descriptor stands for; an absolute path, and a symbolic link whose target is absolute, is `not-permitted`; a link
is read and its target put in front of the rest of the path (at most 40 links, then `loop`); a link at the end is expanded only if `symlink-follow` is set. This is a walk by
name, not the `openat2(RESOLVE_BENEATH)` of the kernel, and a race with another process that changes the tree under the walk is not closed.

**Rights.** A descriptor has the flags `read`, `write`, `mutate-directory` and the sync flags; what it was not given is `bad-descriptor` (read, write) or `read-only` (changing a
directory, as the WIT says), and a `preopens` entry may be read-only. Directory entries come sorted by name, without `.` and `..`, as a snapshot when `read-directory` is called.

**On Windows** there is no `dir_fd` and a directory cannot be opened as a file: a directory descriptor is a path (the real path, with the `\\\\?\\` prefix so that the system changes no name), a file
descriptor is a C-library descriptor with its path, and the same walk goes below the path by name. A name with `\\` or `:` is `invalid` (a way out, or a stream of a file), and a link is a symbolic
link or a junction. The check and the use are two steps, so another process that changes the tree in between is not stopped (as in the Windows back end of WASI 0.1). An open file cannot be
deleted or renamed, `rename-at` replaces a file, and a symbolic link needs the privilege for it.

Layouts of the results (Canonical ABI), for `retptr`: `result<_, error-code>`: tag at 0, the code at 1; `result<handle, error-code>`: 8 bytes, handle (or code) at 4;
`result<descriptor-flags | descriptor-type>`: 2 bytes, the value at 1; `result<descriptor-stat>`: 104 bytes, the stat at 8 (type 0, link-count 8, size 16, then three
`option<datetime>` of 24 bytes at 24, 48, 72, the datetime inside at +8); `result<tuple<list<u8>, bool>>`: 16 bytes, pointer 4, length 8, end-of-file 12; `result<filesize>`: 16 bytes,
value at 8; `result<string>`: 12 bytes, pointer 4, length 8; `result<metadata-hash-value>`: 24 bytes, lower 8, upper 16; `result<option<directory-entry>>`: 20 bytes, option tag at 4,
type 8, name pointer 12, length 16; `option<error-code>`: tag 0, code 1; the code is the index in `ERROR_CODES`.
"""

from __future__ import annotations

import errno
import os
import stat as stat_module
import sys
from collections.abc import Callable

from .wasi_p2_core import (
    KIND_DESCRIPTOR,
    KIND_DIRECTORY_ENTRY_STREAM,
    KIND_ERROR,
    Host,
    alloc,
    load_bytes,
    store_bytes,
    store_u8,
    store_u32,
    store_u64,
    table_drop,
    table_get,
    table_new,
)
from .wasi_p2_io import (
    READ_CAP,
    Error,
    InputStream,
    OutputStream,
    StreamClosed,
    StreamFailed,
    input_stream_new,
    output_stream_new,
)

ERROR_CODES = [
    "access", "would-block", "already", "bad-descriptor", "busy", "deadlock", "quota", "exist", "file-too-large", "illegal-byte-sequence", "in-progress",
    "interrupted", "invalid", "io", "is-directory", "loop", "too-many-links", "message-size", "name-too-long", "no-device", "no-entry", "no-lock",
    "insufficient-memory", "insufficient-space", "not-directory", "not-empty", "not-recoverable", "unsupported", "no-tty", "no-such-device", "overflow",
    "not-permitted", "pipe", "read-only", "invalid-seek", "text-file-busy", "cross-device",
]  # fmt: skip
_CODE = {name: i for i, name in enumerate(ERROR_CODES)}

_ERRNO_NAMES = {
    "EACCES": "access", "EAGAIN": "would-block", "EALREADY": "already", "EBADF": "bad-descriptor", "EBUSY": "busy", "EDEADLK": "deadlock", "EDQUOT": "quota",
    "EEXIST": "exist", "EFBIG": "file-too-large", "EILSEQ": "illegal-byte-sequence", "EINPROGRESS": "in-progress", "EINTR": "interrupted", "EINVAL": "invalid",
    "EIO": "io", "EISDIR": "is-directory", "ELOOP": "loop", "EMLINK": "too-many-links", "EMSGSIZE": "message-size", "ENAMETOOLONG": "name-too-long",
    "ENODEV": "no-device", "ENOENT": "no-entry", "ENOLCK": "no-lock", "ENOMEM": "insufficient-memory", "ENOSPC": "insufficient-space", "ENOTDIR": "not-directory",
    "ENOTEMPTY": "not-empty", "ENOTRECOVERABLE": "not-recoverable", "ENOSYS": "unsupported", "ENOTSUP": "unsupported", "ENOTTY": "no-tty",
    "ENXIO": "no-such-device", "EOVERFLOW": "overflow", "EPERM": "not-permitted", "EPIPE": "pipe", "EROFS": "read-only", "ESPIPE": "invalid-seek",
    "ETXTBSY": "text-file-busy", "EXDEV": "cross-device",
}  # fmt: skip
_ERRNO = {
    getattr(errno, n): name for n, name in _ERRNO_NAMES.items() if hasattr(errno, n)
}  # (some names are not on every system)

# descriptor-flags (a bit for each, in the order of the WIT), path-flags, open-flags
READ, WRITE, FILE_SYNC, DATA_SYNC, REQUESTED_SYNC, MUTATE = 1, 2, 4, 8, 16, 32
SYMLINK_FOLLOW = 1
CREATE, DIRECTORY, EXCLUSIVE, TRUNCATE = 1, 2, 4, 8

# descriptor-type
_TYPE = {
    "unknown": 0,
    "block-device": 1,
    "character-device": 2,
    "directory": 3,
    "fifo": 4,
    "symbolic-link": 5,
    "regular-file": 6,
    "socket": 7,
}

NAME_MAX = 255
MAX_DEPTH = 128
MAX_LINKS = 40
STREAM_CHUNK = 65536


class FsError(Exception):
    """A failure that is an `error-code`."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.code = _CODE[name]


def _oserror(exc: OSError) -> FsError:
    return FsError(_ERRNO.get(exc.errno or 0, "io"))


class Descriptor:
    __slots__ = ("fd", "flags", "is_dir", "path")

    def __init__(self, fd: int, flags: int, is_dir: bool, path: str = "") -> None:
        self.fd, self.flags, self.is_dir = fd, flags, is_dir
        self.path = path  # Windows: where it is (a directory has no fd there)


class DirectoryEntries:
    __slots__ = ("entries", "pos")

    def __init__(self, entries: list[tuple[int, bytes]]) -> None:
        self.entries, self.pos = entries, 0


def _descriptor(host: Host, handle: int) -> Descriptor:
    return table_get(host, handle, KIND_DESCRIPTOR)  # type: ignore[return-value]


def _need(descriptor: Descriptor, flag: int) -> None:
    if not descriptor.flags & flag:
        raise FsError(
            "read-only" if flag == MUTATE else "bad-descriptor"
        )  # `mutate-directory` unset: read-only (the WIT says so)


def _type_of(mode: int) -> int:
    for test, name in (
        (stat_module.S_ISREG, "regular-file"), (stat_module.S_ISDIR, "directory"), (stat_module.S_ISLNK, "symbolic-link"),
        (stat_module.S_ISCHR, "character-device"), (stat_module.S_ISBLK, "block-device"), (stat_module.S_ISFIFO, "fifo"), (stat_module.S_ISSOCK, "socket"),
    ):  # fmt: skip
        if test(mode):
            return _TYPE[name]
    return 0


# What differs between POSIX and Windows. A `Ref` is what the walk stands on: the descriptor of a directory (POSIX) or its path (Windows); `name` is a name below it.

Ref = int | str

if sys.platform == "win32":
    _REPARSE_MOUNT_POINT = 0xA0000003

    def _is_link(st: os.stat_result) -> bool:
        return stat_module.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) == _REPARSE_MOUNT_POINT

    def _join(parent: Ref, name: bytes) -> str:
        text = os.fsdecode(name)
        if "\\" in text or ":" in text or "/" in text or text in ("", ".", ".."):
            raise FsError("invalid")
        return f"{parent}\\{text}"

    def _target(parent: Ref, name: bytes) -> str:
        """The place a name stands for: the directory itself for `.`, with no trailing slash (a slash after the name of something that is not a directory is `not-directory`, as in POSIX)."""
        bare = name.rstrip(b"/")
        full = str(parent) if bare in (b".", b"") else _join(parent, bare)
        if bare != name:
            try:
                is_dir = stat_module.S_ISDIR(os.stat(full).st_mode)
            except OSError:
                return full
            if not is_dir:
                raise NotADirectoryError(errno.ENOTDIR, "not a directory")
        return full

    def _ref(d: Descriptor) -> Ref:
        return d.path

    def _lstat(parent: Ref, name: bytes) -> os.stat_result:
        return os.lstat(_target(parent, name))

    def _readlink(parent: Ref, name: bytes) -> bytes:
        target = os.readlink(_target(parent, name))
        if target.startswith(("\\\\?\\", "\\??\\")):
            target = target[4:]
        target = target.replace("\\", "/")
        if len(target) > 1 and target[1] == ":" and target[0].isalpha():
            target = "/" + target  # a drive: absolute, so it is refused like a rooted target
        return os.fsencode(target)

    def _enter(parent: Ref, name: bytes) -> tuple[Ref, int | None]:
        full = _join(parent, name)
        st = os.lstat(full)
        if _is_link(st):
            raise OSError(errno.ELOOP, "link")
        if not stat_module.S_ISDIR(st.st_mode):
            raise NotADirectoryError(errno.ENOTDIR, "not a directory")
        return full, None

    def _fstat(d: Descriptor) -> os.stat_result:
        return os.fstat(d.fd) if d.fd >= 0 else os.stat(d.path)

    def _pread(fd: int, n: int, offset: int) -> bytes:
        if fd < 0:
            raise OSError(errno.EISDIR, "a directory")
        os.lseek(fd, offset, os.SEEK_SET)
        return os.read(fd, n)

    def _pwrite(fd: int, data: bytes | memoryview, offset: int) -> int:
        os.lseek(fd, offset, os.SEEK_SET)
        return os.write(fd, data)

    def _mkdir(parent: Ref, name: bytes) -> None:
        os.mkdir(_target(parent, name))

    def _rmdir(parent: Ref, name: bytes) -> None:
        os.rmdir(_target(parent, name))

    def _unlink(parent: Ref, name: bytes) -> None:
        os.unlink(_target(parent, name))

    def _rename(p1: Ref, name1: bytes, p2: Ref, name2: bytes) -> None:
        os.replace(_target(p1, name1), _target(p2, name2))

    def _link(p1: Ref, name1: bytes, p2: Ref, name2: bytes) -> None:
        os.link(_target(p1, name1), _target(p2, name2))

    def _symlink(target: bytes, parent: Ref, name: bytes) -> None:
        text = os.fsdecode(target).replace("/", "\\")
        beside = os.path.normpath(os.path.join(str(parent).removeprefix("\\\\?\\"), text))
        os.symlink(text, _target(parent, name), target_is_directory=os.path.isdir(beside))

    def _utime(parent: Ref, name: bytes, ns: tuple[int, int]) -> None:
        os.utime(_target(parent, name), ns=ns)

    def _utime_d(d: Descriptor, ns: tuple[int, int]) -> None:
        os.utime(d.path, ns=ns)

    def _listdir(d: Descriptor) -> list[bytes]:
        return [os.fsencode(n) for n in os.listdir(d.path)]

    def _open_at(parent: Ref, name: bytes, open_flags: int, flags: int) -> Descriptor:
        full = _target(parent, name)
        try:
            st = os.lstat(full)
        except FileNotFoundError:
            st = None
        if st is not None and _is_link(st):
            raise FsError("loop")  # links are not followed here (O_NOFOLLOW)
        if st is not None and stat_module.S_ISDIR(st.st_mode):
            if open_flags & CREATE and open_flags & EXCLUSIVE:
                raise FsError("exist")
            if flags & WRITE or open_flags & (CREATE | TRUNCATE):
                raise FsError("is-directory")
            return Descriptor(-1, flags, True, full)
        if open_flags & DIRECTORY or name.endswith(b"/"):
            raise FsError("not-directory" if st is not None else "no-entry")
        oflags = getattr(os, "O_BINARY", 0)
        oflags |= os.O_RDWR if flags & READ and flags & WRITE else os.O_WRONLY if flags & WRITE else os.O_RDONLY
        if open_flags & CREATE:
            oflags |= os.O_CREAT
        if open_flags & EXCLUSIVE:
            oflags |= os.O_EXCL
        if open_flags & TRUNCATE:
            oflags |= os.O_TRUNC
        return Descriptor(os.open(full, oflags, 0o666), flags, False, full)

    def _open_directory(path: str, flags: int) -> Descriptor:
        real = os.path.realpath(path).removeprefix("\\\\?\\").rstrip("\\/")
        return Descriptor(-1, flags, True, "\\\\?\\" + real)

else:

    def _ref(d: Descriptor) -> Ref:
        return d.fd

    def _lstat(parent: Ref, name: bytes) -> os.stat_result:
        return os.stat(name, dir_fd=int(parent), follow_symlinks=False)

    def _readlink(parent: Ref, name: bytes) -> bytes:
        return os.fsencode(os.readlink(name, dir_fd=int(parent)))

    def _enter(parent: Ref, name: bytes) -> tuple[Ref, int | None]:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=int(parent))
        return fd, fd

    def _fstat(d: Descriptor) -> os.stat_result:
        return os.fstat(d.fd)

    def _pread(fd: int, n: int, offset: int) -> bytes:
        return os.pread(fd, n, offset)

    def _pwrite(fd: int, data: bytes | memoryview, offset: int) -> int:
        return os.pwrite(fd, data, offset)

    def _mkdir(parent: Ref, name: bytes) -> None:
        os.mkdir(name, 0o777, dir_fd=int(parent))

    def _rmdir(parent: Ref, name: bytes) -> None:
        os.rmdir(name, dir_fd=int(parent))

    def _unlink(parent: Ref, name: bytes) -> None:
        os.unlink(name, dir_fd=int(parent))

    def _rename(p1: Ref, name1: bytes, p2: Ref, name2: bytes) -> None:
        os.rename(name1, name2, src_dir_fd=int(p1), dst_dir_fd=int(p2))

    def _link(p1: Ref, name1: bytes, p2: Ref, name2: bytes) -> None:
        os.link(name1, name2, src_dir_fd=int(p1), dst_dir_fd=int(p2), follow_symlinks=False)

    def _symlink(target: bytes, parent: Ref, name: bytes) -> None:
        os.symlink(target, name, dir_fd=int(parent))

    def _utime(parent: Ref, name: bytes, ns: tuple[int, int]) -> None:
        os.utime(name, ns=ns, dir_fd=int(parent), follow_symlinks=False)

    def _utime_d(d: Descriptor, ns: tuple[int, int]) -> None:
        os.utime(d.fd, ns=ns)

    def _listdir(d: Descriptor) -> list[bytes]:
        return [os.fsencode(n) for n in os.listdir(d.fd)]

    def _open_at(parent: Ref, name: bytes, open_flags: int, flags: int) -> Descriptor:
        oflags = os.O_NOFOLLOW | os.O_CLOEXEC
        oflags |= os.O_RDWR if flags & READ and flags & WRITE else os.O_WRONLY if flags & WRITE else os.O_RDONLY
        if open_flags & CREATE:
            oflags |= os.O_CREAT
        if open_flags & DIRECTORY:
            oflags |= os.O_DIRECTORY
        if open_flags & EXCLUSIVE:
            oflags |= os.O_EXCL
        if open_flags & TRUNCATE:
            oflags |= os.O_TRUNC
        if flags & FILE_SYNC:
            oflags |= os.O_SYNC
        if flags & DATA_SYNC:
            oflags |= os.O_DSYNC
        try:
            fd = os.open(name, oflags, 0o666, dir_fd=int(parent))
        except NotADirectoryError:
            if open_flags & DIRECTORY and not name.endswith(b"/"):
                try:
                    os.readlink(name, dir_fd=int(parent))
                except OSError:
                    pass
                else:
                    raise FsError("loop") from None  # a link is not entered when links are not followed (O_NOFOLLOW)
            raise
        return Descriptor(fd, flags, stat_module.S_ISDIR(os.fstat(fd).st_mode))

    def _open_directory(path: str, flags: int) -> Descriptor:
        return Descriptor(os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC), flags, True)


# the walk of a path


def _walk(base: Ref, path: bytes, follow: bool) -> tuple[Ref, bytes, list[int]]:
    """(directory, name, descriptors to close): the directory that holds the last name of `path` and that name (`.` for none), the walk confined below `base`."""
    if b"\0" in path:
        raise FsError("invalid")
    if not path:
        raise FsError("no-entry")  # an empty name is no name (POSIX; Wasmtime says the same)
    if path.startswith(b"/"):
        raise FsError("not-permitted")
    stack: list[Ref] = [base]
    opened: list[int] = []
    links = 0
    pending = path
    try:
        while True:
            pending = pending.lstrip(b"/")
            if not pending:
                leaf = b"."
                break
            name, sep, rest = pending.partition(b"/")
            rest = rest.lstrip(b"/")
            last = not rest
            slash = last and bool(sep)
            if len(name) > NAME_MAX:
                raise FsError("name-too-long")
            if name == b".":
                if last:
                    leaf = b"."
                    break
                pending = rest
                continue
            if name == b"..":
                if len(stack) == 1:
                    raise FsError("not-permitted")  # out of the directory it was given
                ref = stack.pop()
                if isinstance(ref, int):
                    opened.remove(ref)
                    os.close(ref)
                if last:
                    leaf = b"."
                    break
                pending = rest
                continue
            if last:
                if not follow:
                    is_link = False
                    if slash:
                        # a slash after a name makes the kernel follow a link there whatever O_NOFOLLOW says; the walk follows it itself, below the base
                        try:
                            _readlink(stack[-1], name)
                        except OSError:
                            pass  # not a link
                        else:
                            is_link = True
                    if not is_link:
                        leaf = name + (b"/" if slash else b"")
                        break
                # a link at the end is read before it is used (below)
            else:
                if len(stack) > MAX_DEPTH:
                    raise FsError("name-too-long")
                try:
                    nxt, entered = _enter(stack[-1], name)
                except OSError as exc:
                    if exc.errno not in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
                        raise _oserror(exc) from exc
                    # not a directory we can enter: perhaps a link, which is read below
                else:
                    stack.append(nxt)
                    if entered is not None:
                        opened.append(entered)
                    pending = rest
                    continue
            try:
                target = _readlink(stack[-1], name)
            except OSError as exc:
                if last:  # not a link: this is the last name
                    leaf = name + (b"/" if slash else b"")
                    break
                raise FsError("not-directory") from exc
            links += 1
            if links > MAX_LINKS:
                raise FsError("loop")
            if target.startswith(b"/"):
                raise FsError("not-permitted")
            pending = target + (b"/" + rest if rest else b"/" if slash else b"")
        return stack[-1], leaf, opened
    except BaseException:
        for fd in opened:
            os.close(fd)
        raise


class _Walked:
    """`with _Walked(base, path, follow) as (directory, name):` closes what the walk opened."""

    def __init__(self, base: Ref, path: bytes, follow: bool) -> None:
        self.directory, self.name, self.opened = _walk(base, path, follow)

    def __enter__(self) -> tuple[Ref, bytes]:
        return self.directory, self.name

    def __exit__(self, *exc: object) -> None:
        for fd in self.opened:
            os.close(fd)


# writing results


def _ok(host: Host, comp: int, retptr: int) -> None:
    store_u8(host, comp, retptr, 0)


def _fail(host: Host, comp: int, retptr: int, at: int, exc: FsError) -> None:
    store_u8(host, comp, retptr, 1)
    store_u8(host, comp, at, exc.code)


def _datetime(host: Host, comp: int, ptr: int, ns: int) -> None:
    store_u8(host, comp, ptr, 1)  # some
    store_u64(host, comp, ptr + 8, ns // 1_000_000_000)
    store_u32(host, comp, ptr + 16, ns % 1_000_000_000)


def _write_stat(host: Host, comp: int, ptr: int, st: os.stat_result) -> None:
    store_u8(host, comp, ptr, _type_of(st.st_mode))
    store_u64(host, comp, ptr + 8, st.st_nlink)
    store_u64(host, comp, ptr + 16, st.st_size)
    _datetime(host, comp, ptr + 24, st.st_atime_ns)
    _datetime(host, comp, ptr + 48, st.st_mtime_ns)
    _datetime(host, comp, ptr + 72, st.st_ctime_ns)


def _string(host: Host, comp: int, data: bytes, at: int) -> None:
    ptr = alloc(host, comp, 1, len(data))
    store_bytes(host, comp, ptr, data)
    store_u32(host, comp, at, ptr)
    store_u32(host, comp, at + 4, len(data))


# streams over a file


class FileInput(InputStream):
    def __init__(self, fd: int, offset: int) -> None:
        self.fd, self.pos = (os.dup(fd) if fd >= 0 else -1), offset  # (-1: a directory on Windows)

    def read(self, n: int) -> bytes:
        if n == 0:
            return b""
        try:
            data = _pread(self.fd, n, self.pos)
        except OSError as exc:
            raise StreamFailed(exc.strerror or "read failed", _oserror(exc).code) from exc
        if not data:
            raise StreamClosed
        self.pos += len(data)
        return data

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)


class FileOutput(OutputStream):
    def __init__(self, fd: int, offset: int | None) -> None:
        self.fd, self.pos = (os.dup(fd) if fd >= 0 else -1), offset  # offset None: append

    def check_write(self) -> int:
        return STREAM_CHUNK

    def write(self, data: bytes) -> None:
        try:
            if self.pos is None:
                at = os.fstat(self.fd).st_size
            else:
                at = self.pos
            view = memoryview(data)
            done = 0
            while done < len(view):
                done += _pwrite(self.fd, view[done:], at + done)
            if self.pos is not None:
                self.pos += len(data)
        except OSError as exc:
            raise StreamFailed(exc.strerror or "write failed", _oserror(exc).code) from exc

    def flush(self) -> None:
        pass

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)


# preopens


def wasi_filesystem_preopens_get_directories(host: Host, comp: int, retptr: int) -> None:
    items = host.preopens
    ptr = alloc(host, comp, 4, 12 * len(items))
    for i, (path, name, writable) in enumerate(items):
        handle = table_new(host, KIND_DESCRIPTOR, _open_directory(path, READ | (MUTATE if writable else 0)))
        store_u32(host, comp, ptr + 12 * i, handle)
        _string(host, comp, name.encode(), ptr + 12 * i + 4)
    store_u32(host, comp, retptr, ptr)
    store_u32(host, comp, retptr + 4, len(items))


# the descriptor


def wasi_filesystem_types_descriptor_drop(host: Host, handle: int) -> None:
    descriptor = _descriptor(host, handle)
    table_drop(host, handle, KIND_DESCRIPTOR)
    if descriptor.fd >= 0:
        os.close(descriptor.fd)


def wasi_filesystem_types_directory_entry_stream_drop(host: Host, handle: int) -> None:
    table_drop(host, handle, KIND_DIRECTORY_ENTRY_STREAM)


def _stream_result(host: Host, comp: int, retptr: int, make: Callable[[], int]) -> None:
    try:
        stream = make()
    except FsError as exc:
        _fail(host, comp, retptr, retptr + 4, exc)
        return
    _ok(host, comp, retptr)
    store_u32(host, comp, retptr + 4, stream)


def wasi_filesystem_types_descriptor_read_via_stream(
    host: Host, comp: int, self: int, offset: int, retptr: int
) -> None:
    def make() -> int:
        d = _descriptor(host, self)
        _need(d, READ)
        return input_stream_new(host, FileInput(d.fd, offset))

    _stream_result(host, comp, retptr, make)


def wasi_filesystem_types_descriptor_write_via_stream(
    host: Host, comp: int, self: int, offset: int, retptr: int
) -> None:
    def make() -> int:
        d = _descriptor(host, self)
        _need(d, WRITE)
        return output_stream_new(host, FileOutput(d.fd, offset))

    _stream_result(host, comp, retptr, make)


def wasi_filesystem_types_descriptor_append_via_stream(host: Host, comp: int, self: int, retptr: int) -> None:
    def make() -> int:
        d = _descriptor(host, self)
        _need(d, WRITE)
        return output_stream_new(host, FileOutput(d.fd, None))

    _stream_result(host, comp, retptr, make)


def _status(host: Host, comp: int, retptr: int, action: Callable[[], object]) -> None:
    """For a `result<_, error-code>`: runs `action()`, writes ok or the error."""
    try:
        action()
    except FsError as exc:
        _fail(host, comp, retptr, retptr + 1, exc)
        return
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 1, _oserror(exc))
        return
    _ok(host, comp, retptr)


def wasi_filesystem_types_descriptor_advise(
    host: Host, comp: int, self: int, offset: int, length: int, advice: int, retptr: int
) -> None:
    _status(host, comp, retptr, lambda: _descriptor(host, self))  # advice is only a hint: accepted, and nothing done


def _sync(call: Callable[[int], object], d: Descriptor) -> None:
    if d.fd >= 0:  # (a directory on Windows has nothing to flush)
        call(d.fd)


def wasi_filesystem_types_descriptor_sync_data(host: Host, comp: int, self: int, retptr: int) -> None:
    sync = getattr(os, "fdatasync", os.fsync)  # macOS has no fdatasync
    _status(host, comp, retptr, lambda: _sync(sync, _descriptor(host, self)))


def wasi_filesystem_types_descriptor_sync(host: Host, comp: int, self: int, retptr: int) -> None:
    _status(host, comp, retptr, lambda: _sync(os.fsync, _descriptor(host, self)))


def wasi_filesystem_types_descriptor_get_flags(host: Host, comp: int, self: int, retptr: int) -> None:
    _ok(host, comp, retptr)
    store_u8(host, comp, retptr + 1, _descriptor(host, self).flags)


def wasi_filesystem_types_descriptor_get_type(host: Host, comp: int, self: int, retptr: int) -> None:
    d = _descriptor(host, self)
    try:
        kind = _type_of(_fstat(d).st_mode)
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 1, _oserror(exc))
        return
    _ok(host, comp, retptr)
    store_u8(host, comp, retptr + 1, kind)


def wasi_filesystem_types_descriptor_set_size(host: Host, comp: int, self: int, size: int, retptr: int) -> None:
    def action() -> None:
        d = _descriptor(host, self)
        _need(d, WRITE)
        os.ftruncate(d.fd, size)

    _status(host, comp, retptr, action)


def _new_time(tag: int, seconds: int, nanoseconds: int, current_ns: int, now_ns: int) -> int:
    """new-timestamp: 0 no-change, 1 now, 2 timestamp."""
    if tag == 0:
        return current_ns
    if tag == 1:
        return now_ns
    return seconds * 1_000_000_000 + nanoseconds


def wasi_filesystem_types_descriptor_set_times(
    host: Host,
    comp: int,
    self: int,
    a_tag: int,
    a_seconds: int,
    a_nanos: int,
    m_tag: int,
    m_seconds: int,
    m_nanos: int,
    retptr: int,
) -> None:
    def action() -> None:
        d = _descriptor(host, self)
        _need(d, WRITE if not d.is_dir else MUTATE)
        st = _fstat(d)
        now = host.wall_ns()
        _utime_d(
            d,
            (
                _new_time(a_tag, a_seconds, a_nanos, st.st_atime_ns, now),
                _new_time(m_tag, m_seconds, m_nanos, st.st_mtime_ns, now),
            ),
        )

    _status(host, comp, retptr, action)


def wasi_filesystem_types_descriptor_read(
    host: Host, comp: int, self: int, length: int, offset: int, retptr: int
) -> None:
    try:
        d = _descriptor(host, self)
        _need(d, READ)
        want = min(length, READ_CAP)
        data = _pread(d.fd, want, offset)
    except FsError as exc:
        _fail(host, comp, retptr, retptr + 4, exc)
        return
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 4, _oserror(exc))
        return
    ptr = alloc(host, comp, 1, len(data))
    store_bytes(host, comp, ptr, data)
    _ok(host, comp, retptr)
    store_u32(host, comp, retptr + 4, ptr)
    store_u32(host, comp, retptr + 8, len(data))
    store_u8(host, comp, retptr + 12, int(not data))  # end of file is when nothing was read (as in Wasmtime)


def wasi_filesystem_types_descriptor_write(
    host: Host, comp: int, self: int, ptr: int, length: int, offset: int, retptr: int
) -> None:
    try:
        d = _descriptor(host, self)
        _need(d, WRITE)
        view = memoryview(load_bytes(host, comp, ptr, length))
        done = 0
        while done < len(view):
            done += _pwrite(d.fd, view[done:], offset + done)
    except FsError as exc:
        _fail(host, comp, retptr, retptr + 8, exc)
        return
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 8, _oserror(exc))
        return
    _ok(host, comp, retptr)
    store_u64(host, comp, retptr + 8, length)


def wasi_filesystem_types_descriptor_read_directory(host: Host, comp: int, self: int, retptr: int) -> None:
    def make() -> int:
        d = _descriptor(host, self)
        if not d.is_dir:
            raise FsError("not-directory")
        try:
            names = sorted(_listdir(d))
            entries: list[tuple[int, bytes]] = []
            for name in names:
                try:
                    entries.append((_type_of(_lstat(_ref(d), name).st_mode), name))
                except FileNotFoundError:  # gone since the listing
                    continue
        except OSError as exc:
            raise _oserror(exc) from exc
        return table_new(host, KIND_DIRECTORY_ENTRY_STREAM, DirectoryEntries(entries))

    _stream_result(host, comp, retptr, make)


def wasi_filesystem_types_directory_entry_stream_read_directory_entry(
    host: Host, comp: int, self: int, retptr: int
) -> None:
    stream: DirectoryEntries = table_get(host, self, KIND_DIRECTORY_ENTRY_STREAM)  # type: ignore[assignment]
    _ok(host, comp, retptr)
    if stream.pos >= len(stream.entries):
        store_u8(host, comp, retptr + 4, 0)  # none
        return
    kind, name = stream.entries[stream.pos]
    stream.pos += 1
    store_u8(host, comp, retptr + 4, 1)
    store_u8(host, comp, retptr + 8, kind)
    _string(host, comp, name, retptr + 12)


def wasi_filesystem_types_descriptor_stat(host: Host, comp: int, self: int, retptr: int) -> None:
    try:
        st = _fstat(_descriptor(host, self))
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 8, _oserror(exc))
        return
    _ok(host, comp, retptr)
    _write_stat(host, comp, retptr + 8, st)


def _path(host: Host, comp: int, ptr: int, length: int) -> bytes:
    return load_bytes(host, comp, ptr, length)


def _stat_at(host: Host, self: int, flags: int, path: bytes) -> os.stat_result:
    d = _descriptor(host, self)
    if not d.is_dir:
        raise FsError("not-directory")
    with _Walked(_ref(d), path, bool(flags & SYMLINK_FOLLOW)) as (parent, name):
        return _lstat(parent, name)


def wasi_filesystem_types_descriptor_stat_at(
    host: Host, comp: int, self: int, path_flags: int, ptr: int, length: int, retptr: int
) -> None:
    try:
        st = _stat_at(host, self, path_flags, _path(host, comp, ptr, length))
    except FsError as exc:
        _fail(host, comp, retptr, retptr + 8, exc)
        return
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 8, _oserror(exc))
        return
    _ok(host, comp, retptr)
    _write_stat(host, comp, retptr + 8, st)


def wasi_filesystem_types_descriptor_set_times_at(
    host: Host, comp: int, self: int, path_flags: int, ptr: int, length: int,
    a_tag: int, a_seconds: int, a_nanos: int, m_tag: int, m_seconds: int, m_nanos: int, retptr: int,
) -> None:  # fmt: skip
    def action() -> None:
        d = _descriptor(host, self)
        _need(d, MUTATE)
        with _Walked(_ref(d), _path(host, comp, ptr, length), bool(path_flags & SYMLINK_FOLLOW)) as (parent, name):
            st = _lstat(parent, name)
            now = host.wall_ns()
            _utime(
                parent,
                name,
                (
                    _new_time(a_tag, a_seconds, a_nanos, st.st_atime_ns, now),
                    _new_time(m_tag, m_seconds, m_nanos, st.st_mtime_ns, now),
                ),
            )

    _status(host, comp, retptr, action)


def wasi_filesystem_types_descriptor_link_at(
    host: Host,
    comp: int,
    self: int,
    old_flags: int,
    old_ptr: int,
    old_len: int,
    new_dir: int,
    new_ptr: int,
    new_len: int,
    retptr: int,
) -> None:
    def action() -> None:
        d, n = _descriptor(host, self), _descriptor(host, new_dir)
        _need(d, MUTATE)
        _need(n, MUTATE)
        with (
            _Walked(_ref(d), _path(host, comp, old_ptr, old_len), bool(old_flags & SYMLINK_FOLLOW)) as (p1, name1),
            _Walked(_ref(n), _path(host, comp, new_ptr, new_len), False) as (p2, name2),
        ):
            _link(p1, name1, p2, name2)

    _status(host, comp, retptr, action)


def wasi_filesystem_types_descriptor_open_at(
    host: Host, comp: int, self: int, path_flags: int, ptr: int, length: int, open_flags: int, flags: int, retptr: int
) -> None:
    try:
        d = _descriptor(host, self)
        if not d.is_dir:
            raise FsError("not-directory")
        if flags & (WRITE | MUTATE) and not d.flags & MUTATE:
            raise FsError("read-only")  # a descriptor cannot hand out more than it has (as the WIT says for open-at)
        if flags & READ and not d.flags & READ:
            raise FsError("not-permitted")
        if open_flags & (CREATE | TRUNCATE):
            _need(d, MUTATE)
        with _Walked(_ref(d), _path(host, comp, ptr, length), bool(path_flags & SYMLINK_FOLLOW)) as (parent, name):
            handle = table_new(host, KIND_DESCRIPTOR, _open_at(parent, name, open_flags, flags))
    except FsError as exc:
        _fail(host, comp, retptr, retptr + 4, exc)
        return
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 4, _oserror(exc))
        return
    _ok(host, comp, retptr)
    store_u32(host, comp, retptr + 4, handle)


def wasi_filesystem_types_descriptor_readlink_at(
    host: Host, comp: int, self: int, ptr: int, length: int, retptr: int
) -> None:
    try:
        d = _descriptor(host, self)
        with _Walked(_ref(d), _path(host, comp, ptr, length), False) as (parent, name):
            target = _readlink(parent, name)
        if target.startswith(b"/"):
            raise FsError("not-permitted")  # an absolute or rooted target is not shown
    except FsError as exc:
        _fail(host, comp, retptr, retptr + 4, exc)
        return
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 4, _oserror(exc))
        return
    _ok(host, comp, retptr)
    _string(host, comp, target, retptr + 4)


def _at(
    host: Host, comp: int, retptr: int, self: int, ptr: int, length: int, call: Callable[[Ref, bytes], object]
) -> None:
    def action() -> None:
        d = _descriptor(host, self)
        _need(d, MUTATE)
        with _Walked(_ref(d), _path(host, comp, ptr, length), False) as (parent, name):
            call(parent, name)

    _status(host, comp, retptr, action)


def wasi_filesystem_types_descriptor_create_directory_at(
    host: Host, comp: int, self: int, ptr: int, length: int, retptr: int
) -> None:
    _at(host, comp, retptr, self, ptr, length, _mkdir)


def wasi_filesystem_types_descriptor_remove_directory_at(
    host: Host, comp: int, self: int, ptr: int, length: int, retptr: int
) -> None:
    _at(host, comp, retptr, self, ptr, length, _rmdir)


def wasi_filesystem_types_descriptor_unlink_file_at(
    host: Host, comp: int, self: int, ptr: int, length: int, retptr: int
) -> None:
    def unlink(parent: Ref, name: bytes) -> None:
        try:
            _unlink(parent, name)
        except PermissionError:
            if stat_module.S_ISDIR(_lstat(parent, name).st_mode):
                raise FsError("is-directory") from None  # some systems say EPERM for a directory
            raise

    _at(host, comp, retptr, self, ptr, length, unlink)


def wasi_filesystem_types_descriptor_rename_at(
    host: Host, comp: int, self: int, old_ptr: int, old_len: int, new_dir: int, new_ptr: int, new_len: int, retptr: int
) -> None:
    def action() -> None:
        d, n = _descriptor(host, self), _descriptor(host, new_dir)
        _need(d, MUTATE)
        _need(n, MUTATE)
        with (
            _Walked(_ref(d), _path(host, comp, old_ptr, old_len), False) as (p1, name1),
            _Walked(_ref(n), _path(host, comp, new_ptr, new_len), False) as (p2, name2),
        ):
            _rename(p1, name1, p2, name2)

    _status(host, comp, retptr, action)


def wasi_filesystem_types_descriptor_symlink_at(
    host: Host, comp: int, self: int, old_ptr: int, old_len: int, new_ptr: int, new_len: int, retptr: int
) -> None:
    target = load_bytes(host, comp, old_ptr, old_len)
    if b"\0" in target or target.startswith(b"/"):
        error = FsError("invalid" if b"\0" in target else "not-permitted")

        def refuse() -> None:
            raise error

        _status(host, comp, retptr, refuse)
        return
    _at(host, comp, retptr, self, new_ptr, new_len, lambda parent, name: _symlink(target, parent, name))


def wasi_filesystem_types_descriptor_is_same_object(host: Host, self: int, other: int) -> int:
    a, b = _fstat(_descriptor(host, self)), _fstat(_descriptor(host, other))
    return int((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino))


def _fnv(*values: int) -> int:
    """FNV-1a 64 over the values, each as 8 bytes little-endian (the C twin does the same)."""
    h = 0xCBF29CE484222325
    for v in values:
        for byte in (v & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little"):
            h = ((h ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _hash(host: Host, comp: int, retptr: int, st: os.stat_result) -> None:
    """`upper` names the object (device, inode); `lower` also takes in what changes when the object is modified (size, modification time)."""
    _ok(host, comp, retptr)
    store_u64(host, comp, retptr + 8, _fnv(st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino))
    store_u64(host, comp, retptr + 16, _fnv(st.st_dev, st.st_ino))


def wasi_filesystem_types_descriptor_metadata_hash(host: Host, comp: int, self: int, retptr: int) -> None:
    try:
        st = os.fstat(_descriptor(host, self).fd)
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 8, _oserror(exc))
        return
    _hash(host, comp, retptr, st)


def wasi_filesystem_types_descriptor_metadata_hash_at(
    host: Host, comp: int, self: int, path_flags: int, ptr: int, length: int, retptr: int
) -> None:
    try:
        st = _stat_at(host, self, path_flags, _path(host, comp, ptr, length))
    except FsError as exc:
        _fail(host, comp, retptr, retptr + 8, exc)
        return
    except OSError as exc:
        _fail(host, comp, retptr, retptr + 8, _oserror(exc))
        return
    _hash(host, comp, retptr, st)


def wasi_filesystem_types_filesystem_error_code(host: Host, comp: int, err: int, retptr: int) -> None:
    error: Error = table_get(host, err, KIND_ERROR)  # type: ignore[assignment]
    if error.code is None:
        store_u8(host, comp, retptr, 0)
    else:
        store_u8(host, comp, retptr, 1)
        store_u8(host, comp, retptr + 1, error.code)
