"""WASI for files and directories: the preopens, path_open, fd_read, fd_write, fd_seek, fd_filestat_get, fd_readdir, the
calls that create, change and remove, and the confinement of a program to the directories it was given."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

DATA = Path(__file__).parent / "data"
Builder = Callable[..., ModuleType]

E_BADF, E_EXIST, E_INVAL, E_ISDIR, E_NOENT, E_NOTDIR = 8, 20, 28, 31, 44, 54
E_NOTEMPTY, E_NOTCAPABLE, E_NAMETOOLONG, E_SPIPE = 55, 76, 37, 70
# the rights the way wasi-libc asks for them to read a file
FILE_RIGHTS = (1 << 1) | (1 << 2) | (1 << 5) | (1 << 21)  # fd_read, fd_seek, fd_tell, fd_filestat_get
# fd_datasync, fd_fdstat_set_flags, fd_sync, fd_write, fd_allocate, fd_filestat_set_size, fd_filestat_set_times
WRITE_RIGHTS = FILE_RIGHTS | (1 << 0) | (1 << 3) | (1 << 4) | (1 << 6) | (1 << 8) | (1 << 22) | (1 << 23)
DIR_RIGHTS = (1 << 13) | (1 << 14) | (1 << 18) | (1 << 21)  # path_open, fd_readdir, path_filestat_get, fd_filestat_get


@pytest.fixture
def world(tmp_path: Path) -> Path:
    root = tmp_path / "world"
    (root / "sub").mkdir(parents=True)
    (root / "hello.txt").write_bytes(b"hello, files\n")
    (root / "sub" / "deep.txt").write_bytes(b"deep")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    return root


class Fs:
    """A probe module with a preopen, and the memory calls around it."""

    def __init__(self, mod: Any, root: Path, **options: Any) -> None:
        self.inst = mod.Instance(wasi={"preopens": {"/": str(root)}, **options})
        self.mem = self.inst.memory
        self.cursor = 1100

    def put(self, at: int, data: bytes) -> None:
        self.mem[at : at + len(data)] = data

    def u32(self, at: int) -> int:
        return int.from_bytes(self.mem[at : at + 4], "little")

    def u64(self, at: int) -> int:
        return int.from_bytes(self.mem[at : at + 8], "little")

    def open(
        self,
        name: str,
        *,
        fd: int = 3,
        flags: int = 1,
        oflags: int = 0,
        rights: int = FILE_RIGHTS,
        inheriting: int = 0,
        fdflags: int = 0,
    ) -> tuple[int, int]:
        self.put(1000, name.encode())
        code = self.inst.path_open(fd, flags, 1000, len(name.encode()), oflags, rights, inheriting, fdflags, 900)
        return code, self.u32(900)

    def write(self, fd: int, data: bytes) -> tuple[int, int]:
        self.put(3000, data)
        self.put(0, (3000).to_bytes(4, "little") + len(data).to_bytes(4, "little"))
        code = self.inst.fd_write(fd, 0, 1, 8)
        return code, self.u32(8)

    def path(self, name: str) -> tuple[int, int]:
        """Put a name in memory, each one in a place of its own (a call can take two), and give where and how long."""
        data = name.encode()
        if self.cursor + len(data) > 1900:
            self.cursor = 1100
        at = self.cursor
        self.cursor += len(data) + 1
        self.put(at, data)
        return at, len(data)

    def read(self, fd: int, size: int) -> tuple[int, bytes]:
        self.put(0, (2000).to_bytes(4, "little") + size.to_bytes(4, "little"))
        code = self.inst.fd_read(fd, 0, 1, 8)
        return code, bytes(self.mem[2000 : 2000 + self.u32(8)])


@pytest.fixture(params=["openat", "python"])
def probe(request: pytest.FixtureRequest, build_extension: Builder) -> Any:
    """The probe module built for each way the file system is reached: the system (openat), and Python (what Windows uses)."""
    defines = ("WASMEXT_WASI_PYTHON_FS=1",) if request.param == "python" else ()
    return build_extension(DATA / "wasi_fs_probe.wat", f"wasi_fs_probe_{request.param}", defines=defines)


def test_a_preopen_is_a_descriptor_with_a_name(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    assert fs.inst.fd_prestat_get(3, 40) == 0
    assert fs.mem[40] == 0 and fs.u32(44) == 1  # a directory, whose name "/" is one byte long
    assert fs.inst.fd_prestat_dir_name(3, 60, 1) == 0 and bytes(fs.mem[60:61]) == b"/"
    assert fs.inst.fd_prestat_dir_name(3, 60, 0) == E_NAMETOOLONG
    assert fs.inst.fd_prestat_get(4, 40) == E_BADF  # the end of the list the program walks
    assert fs.inst.fd_fdstat_get(3, 80) == 0 and fs.mem[80] == 3  # a directory


def test_a_file_is_read_in_pieces_and_sought(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    code, fd = fs.open("hello.txt")
    assert code == 0 and fd == 4
    assert fs.read(fd, 5) == (0, b"hello")
    assert fs.inst.fd_tell(fd, 100) == 0 and fs.u64(100) == 5
    assert fs.inst.fd_seek(fd, 7, 0, 100) == 0 and fs.u64(100) == 7  # set
    assert fs.read(fd, 100) == (0, b"files\n")
    assert fs.read(fd, 100) == (0, b"")  # the end
    assert fs.inst.fd_seek(fd, (-6) & (2**64 - 1), 2, 100) == 0 and fs.u64(100) == 7  # end
    assert fs.inst.fd_seek(fd, 0, 7, 100) == 28  # EINVAL: no such whence
    assert fs.inst.fd_advise(fd, 0, 0, 0) == 0
    assert fs.inst.fd_close(fd) == 0
    assert fs.inst.fd_close(fd) == E_BADF
    assert fs.read(fd, 1)[0] == E_BADF


def test_filestat_says_what_a_file_and_a_directory_are(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    _, fd = fs.open("hello.txt")
    assert fs.inst.fd_filestat_get(fd, 120) == 0
    assert fs.mem[120 + 16] == 4 and fs.u64(120 + 32) == len("hello, files\n")  # regular file, size
    assert fs.u64(120 + 24) >= 1  # link count
    assert fs.inst.fd_filestat_get(3, 120) == 0 and fs.mem[120 + 16] == 3  # the preopen: a directory
    fs.put(1000, b"sub")
    assert fs.inst.path_filestat_get(3, 1, 1000, 3, 120) == 0 and fs.mem[120 + 16] == 3
    fs.put(1000, b"missing")
    assert fs.inst.path_filestat_get(3, 1, 1000, 7, 120) == E_NOENT


def test_a_directory_is_listed_and_opened_below(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)

    def listing(fd: int) -> list[str]:
        assert fs.inst.fd_readdir(fd, 3000, 1000, 0, 100) == 0
        names: list[str] = []
        used, at = fs.u32(100), 0
        while at + 24 <= used:
            length = fs.u32(3000 + at + 16)
            names.append(bytes(fs.mem[3000 + at + 24 : 3000 + at + 24 + length]).decode())
            at += 24 + length
        return names

    assert listing(3) == [".", "..", "hello.txt", "sub"]
    code, sub = fs.open("sub", rights=DIR_RIGHTS, inheriting=FILE_RIGHTS | DIR_RIGHTS)
    assert code == 0 and fs.inst.fd_fdstat_get(sub, 80) == 0 and fs.mem[80] == 3
    assert listing(sub) == [".", "..", "deep.txt"]
    code, deep = fs.open("deep.txt", fd=sub)
    assert code == 0 and fs.read(deep, 10) == (0, b"deep")
    # a small buffer gets the beginning of the list, and the program asks again from the cookie it was given
    assert fs.inst.fd_readdir(3, 3000, 30, 0, 100) == 0 and fs.u32(100) == 30
    assert fs.read(sub, 1)[0] == E_ISDIR
    assert fs.inst.fd_readdir(deep, 3000, 100, 0, 100) == E_NOTDIR
    assert fs.inst.fd_seek(sub, 0, 0, 100) == E_BADF  # a directory is not seekable


def test_what_is_not_there_or_is_not_a_directory_is_refused_by_name(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    assert fs.open("missing.txt")[0] == E_NOENT
    assert fs.open("hello.txt", oflags=2)[0] == E_NOTDIR  # asked for a directory
    assert fs.open("hello.txt", fd=9)[0] == E_BADF
    assert fs.open("hello.txt", fd=0)[0] == E_NOTDIR  # not a directory descriptor


def test_a_program_cannot_leave_the_directory_it_was_given(probe: Any, world: Path, tmp_path: Path) -> None:
    fs = Fs(probe, world)
    for name in ("../outside.txt", "sub/../../outside.txt", "/etc/passwd", ".."):
        assert fs.open(name)[0] == E_NOTCAPABLE, name
    assert fs.open("sub/../hello.txt")[0] == 0  # coming back is fine
    assert fs.open("./hello.txt")[0] == 0
    _, sub = fs.open("sub", rights=DIR_RIGHTS, inheriting=FILE_RIGHTS | DIR_RIGHTS)
    # a directory descriptor is a capability for that directory: it does not reach what is above it, though that is inside the preopen
    assert fs.open("../hello.txt", fd=sub)[0] == E_NOTCAPABLE
    assert fs.open("../../outside.txt", fd=sub)[0] == E_NOTCAPABLE


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need a privilege on Windows")
def test_a_symbolic_link_that_points_out_is_not_followed(probe: Any, world: Path, tmp_path: Path) -> None:
    os.symlink(tmp_path / "outside.txt", world / "link_out.txt")
    os.symlink("hello.txt", world / "link_in.txt")
    os.symlink(tmp_path, world / "dir_out")
    fs = Fs(probe, world)
    assert fs.open("link_out.txt")[0] == E_NOTCAPABLE
    assert fs.open("dir_out/outside.txt")[0] == E_NOTCAPABLE
    code, fd = fs.open("link_in.txt")
    assert code == 0 and fs.read(fd, 5) == (0, b"hello")
    # without symlink_follow a link is not followed at all
    assert fs.open("link_in.txt", flags=0)[0] != 0


def test_the_rights_of_a_directory_are_kept_and_readonly_takes_the_writing_ones_away(probe: Any, world: Path) -> None:
    fs = Fs(probe, world, readonly=True)
    assert fs.inst.fd_fdstat_get(3, 80) == 0
    mutating = (1 << 6) | (1 << 9) | (1 << 10) | (1 << 25) | (1 << 26)  # fd_write, create, remove, unlink
    assert fs.u64(88) & mutating == 0 and fs.u64(88) & (1 << 13)  # path_open stays
    open_fs = Fs(probe, world)
    assert open_fs.inst.fd_fdstat_get(3, 80) == 0 and open_fs.u64(88) & mutating == mutating


def test_a_bad_preopens_config_is_refused(probe: Any, world: Path, tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError, match="is not a directory"):
        probe.Instance(wasi={"preopens": {"/": str(world / "hello.txt")}})
    with pytest.raises(ValueError, match="no preopen of that name"):
        probe.Instance(wasi={"preopens": {"/": str(world)}, "readonly": ["data"]})
    with pytest.raises(ValueError, match="readonly without preopens"):
        probe.Instance(wasi={"readonly": True})
    with pytest.raises(TypeError, match="preopens must be a dict"):
        probe.Instance(wasi={"preopens": [str(world)]})
    two = probe.Instance(wasi={"preopens": {"/": str(world), "data": str(tmp_path)}, "readonly": "data"})
    assert two.fd_prestat_get(4, 40) == 0 and two.fd_prestat_get(5, 40) == E_BADF


def test_descriptors_are_renumbered(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    _, a = fs.open("hello.txt")
    _, b = fs.open("sub/deep.txt")
    assert fs.inst.fd_renumber(a, b) == 0  # a replaces b: b is now hello.txt, a is free
    assert fs.read(b, 5) == (0, b"hello")
    assert fs.read(a, 1)[0] == E_BADF
    assert fs.open("hello.txt")[1] == a  # the lowest free number is used again
    _, c = fs.open("hello.txt")
    assert (
        fs.inst.fd_renumber(1, c) == 0
    )  # a standard stream can be moved onto another descriptor, and then it is not where it was
    assert (
        fs.inst.fd_fdstat_get(1, 80) == E_BADF and fs.inst.fd_fdstat_get(c, 80) == 0 and fs.mem[80] == 2
    )  # a character device


def test_the_first_snapshot_reads_with_its_own_whence_and_filestat(
    build_extension: Builder, world: Path, tmp_path: Path
) -> None:
    wat = tmp_path / "unstable_fs_probe.wat"
    wat.write_text(
        (DATA / "wasi_fs_probe.wat").read_text("utf-8").replace("wasi_snapshot_preview1", "wasi_unstable"), "utf-8"
    )
    fs = Fs(build_extension(wat, "wasi_unstable_fs_probe"), world)
    _, fd = fs.open("hello.txt")
    assert fs.read(fd, 5) == (0, b"hello")
    assert fs.inst.fd_seek(fd, 0, 2, 100) == 0 and fs.u64(100) == 0  # whence 2 is "set" here
    assert fs.inst.fd_seek(fd, 0, 1, 100) == 0 and fs.u64(100) == len("hello, files\n")  # 1 is "end"
    assert fs.inst.fd_filestat_get(fd, 120) == 0
    assert (
        fs.mem[120 + 16] == 4 and fs.u32(120 + 20) >= 1 and fs.u64(120 + 24) == len("hello, files\n")
    )  # the 56-byte layout


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need a privilege on Windows")
def test_links_inside_the_directory_are_followed_and_a_loop_is_an_error(probe: Any, world: Path) -> None:
    os.symlink("sub", world / "link_dir")  # a link to a directory, used in the middle of a path
    os.symlink("link_dir", world / "link_of_link")  # and a link to that link
    os.symlink("b", world / "a")
    os.symlink("a", world / "b")
    fs = Fs(probe, world)
    code, fd = fs.open("link_dir/deep.txt")
    assert code == 0 and fs.read(fd, 10) == (0, b"deep")
    code, fd = fs.open("link_of_link/deep.txt")
    assert code == 0 and fs.read(fd, 10) == (0, b"deep")
    assert fs.open("link_dir/../hello.txt")[0] == 0  # the link is expanded before the ".." is applied
    fs.put(1000, b"a")
    assert fs.inst.path_filestat_get(3, 1, 1000, 1, 120) == 32  # ELOOP
    assert fs.open("a")[0] == 32
    fs.put(1000, b"link_dir")  # without symlink_follow the link itself is what is described
    assert fs.inst.path_filestat_get(3, 0, 1000, 8, 120) == 0 and fs.mem[120 + 16] == 7
    assert fs.inst.path_filestat_get(3, 1, 1000, 8, 120) == 0 and fs.mem[120 + 16] == 3


def test_a_name_that_is_too_long_is_refused(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    assert fs.open("x" * 300)[0] == E_NAMETOOLONG


ALL_RIGHTS = (1 << 30) - 1


def test_a_file_is_created_written_and_truncated(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    code, fd = fs.open("new.txt", oflags=1, rights=WRITE_RIGHTS)  # creat
    assert code == 0
    assert fs.write(fd, b"first ") == (0, 6) and fs.write(fd, b"second") == (0, 6)
    assert fs.inst.fd_sync(fd) == 0 and fs.inst.fd_datasync(fd) == 0
    assert (world / "new.txt").read_bytes() == b"first second"
    assert fs.read(fd, 3)[0] == 0  # the same descriptor reads too when it was given the right
    assert fs.inst.fd_close(fd) == 0
    assert fs.open("new.txt", oflags=1 | 4, rights=WRITE_RIGHTS)[0] == E_EXIST  # creat + excl
    code, fd = fs.open("new.txt", oflags=8, rights=WRITE_RIGHTS)  # trunc
    assert code == 0 and (world / "new.txt").read_bytes() == b""
    assert fs.write(fd, b"x")[0] == 0
    fs.inst.fd_close(fd)
    assert fs.open("missing/new.txt", oflags=1, rights=WRITE_RIGHTS)[0] == E_NOENT
    assert fs.open("sub", oflags=1 | 2, rights=WRITE_RIGHTS)[0] == E_INVAL  # a directory cannot be created this way
    assert fs.open("sub", rights=WRITE_RIGHTS)[0] == E_ISDIR  # nor opened for writing
    code, sub = fs.open(
        "sub", rights=WRITE_RIGHTS | DIR_RIGHTS
    )  # unless it is asked for as a directory (rights of one)
    assert code == 0 and fs.write(sub, b"x")[0] == E_ISDIR  # which is not written to
    assert fs.inst.fd_fdstat_get(sub, 80) == 0 and fs.u64(88) & ((1 << 2) | (1 << 5)) == 0  # and has no seek or tell
    assert fs.open("sub", oflags=8, rights=WRITE_RIGHTS)[0] == E_ISDIR  # nor truncated
    assert fs.open("../new2.txt", oflags=1, rights=WRITE_RIGHTS)[0] == E_NOTCAPABLE


def test_writing_needs_the_right_and_a_directory_is_not_written(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    _, ro = fs.open("hello.txt")
    assert fs.write(ro, b"x")[0] == E_NOTCAPABLE  # opened without fd_write
    _, rw = fs.open("hello.txt", rights=WRITE_RIGHTS)
    assert fs.write(3, b"x")[0] == E_ISDIR
    assert fs.inst.fd_fdstat_set_rights(rw, ALL_RIGHTS, 0) == E_NOTCAPABLE  # rights are never gained
    assert fs.inst.fd_fdstat_set_rights(rw, FILE_RIGHTS, 0) == 0  # only given up
    assert fs.write(rw, b"x")[0] == E_NOTCAPABLE
    assert fs.inst.fd_fdstat_get(rw, 80) == 0 and fs.u64(88) == FILE_RIGHTS
    assert (world / "hello.txt").read_bytes() == b"hello, files\n"


def test_append_is_kept_and_can_be_changed(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    _, fd = fs.open("hello.txt", rights=WRITE_RIGHTS, fdflags=1)  # append
    assert fs.write(fd, b"more")[0] == 0
    assert (world / "hello.txt").read_bytes() == b"hello, files\nmore"
    assert fs.inst.fd_fdstat_get(fd, 80) == 0 and fs.mem[82] == 1
    assert fs.inst.fd_fdstat_set_flags(fd, 0) == 0
    assert fs.inst.fd_fdstat_get(fd, 80) == 0 and fs.mem[82] == 0
    assert fs.inst.fd_fdstat_set_flags(fd, 99) == E_INVAL


def test_the_size_of_a_file_is_set_and_allocated(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    _, fd = fs.open("hello.txt", rights=WRITE_RIGHTS)
    size = (world / "hello.txt").stat().st_size
    assert fs.inst.fd_filestat_set_size(fd, 5) == 0 and (world / "hello.txt").read_bytes() == b"hello"
    assert fs.inst.fd_allocate(fd, 0, 3) == 0 and (world / "hello.txt").stat().st_size == 5  # already that long
    assert fs.inst.fd_allocate(fd, 4, size) == 0 and (world / "hello.txt").stat().st_size == size + 4
    assert fs.inst.fd_filestat_set_size(3, 0) == E_ISDIR
    _, ro = fs.open("sub/deep.txt")
    assert fs.inst.fd_filestat_set_size(ro, 0) == E_NOTCAPABLE and fs.inst.fd_allocate(ro, 0, 9) == E_NOTCAPABLE


def test_times_are_set_for_a_descriptor_and_for_a_path(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    _, fd = fs.open("hello.txt", rights=WRITE_RIGHTS)
    before = (world / "hello.txt").stat()
    a, m = 1_500_000_000 * 10**9, 1_600_000_000 * 10**9
    assert fs.inst.fd_filestat_set_times(fd, a, m, 1 | 4) == 0  # atim and mtim set
    now = (world / "hello.txt").stat()
    assert (now.st_atime_ns, now.st_mtime_ns) == (a, m)
    assert fs.inst.fd_filestat_set_times(fd, 0, m + 10**9, 4) == 0  # only mtim: atim stays
    now = (world / "hello.txt").stat()
    assert (now.st_atime_ns, now.st_mtime_ns) == (a, m + 10**9)
    assert (
        fs.inst.fd_filestat_set_times(fd, 0, 0, 1 | 2) == E_INVAL
        and fs.inst.fd_filestat_set_times(fd, 0, 0, 16) == E_INVAL
    )
    ptr, length = fs.path("hello.txt")
    assert fs.inst.path_filestat_set_times(3, 1, ptr, length, 0, 0, 8) == 0  # mtim now
    assert (world / "hello.txt").stat().st_mtime_ns > m + 10**9 and (world / "hello.txt").stat().st_atime_ns == a
    ptr, length = fs.path("missing.txt")
    assert fs.inst.path_filestat_set_times(3, 1, ptr, length, 0, 0, 8) == E_NOENT
    assert before.st_size == (world / "hello.txt").stat().st_size


def test_directories_are_created_and_removed_and_files_unlinked(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    assert fs.inst.path_create_directory(3, *fs.path("made")) == 0 and (world / "made").is_dir()
    assert fs.inst.path_create_directory(3, *fs.path("made")) == E_EXIST
    assert fs.inst.path_create_directory(3, *fs.path("sub/inner")) == 0
    assert fs.inst.path_create_directory(3, *fs.path("nothing/inner")) == E_NOENT
    assert fs.inst.path_create_directory(3, *fs.path(".")) == E_EXIST
    assert fs.inst.path_create_directory(3, *fs.path("../outside_dir")) == E_NOTCAPABLE
    assert fs.inst.path_remove_directory(3, *fs.path("sub")) == E_NOTEMPTY
    assert fs.inst.path_remove_directory(3, *fs.path("sub/inner")) == 0 and not (world / "sub" / "inner").exists()
    assert fs.inst.path_remove_directory(3, *fs.path("hello.txt")) == E_NOTDIR
    assert fs.inst.path_remove_directory(3, *fs.path(".")) == E_INVAL
    assert fs.inst.path_unlink_file(3, *fs.path("sub")) in (E_ISDIR, 63) and (world / "sub").is_dir()  # EPERM on macOS
    assert fs.inst.path_unlink_file(3, *fs.path("hello.txt")) == 0 and not (world / "hello.txt").exists()
    assert fs.inst.path_unlink_file(3, *fs.path("hello.txt")) == E_NOENT
    assert fs.inst.path_unlink_file(3, *fs.path("../outside.txt")) == E_NOTCAPABLE
    assert fs.inst.path_unlink_file(4, *fs.path("x")) == E_BADF


def test_a_file_that_is_removed_while_open_is_still_there_to_read(probe: Any, world: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("Windows does not remove a file that is open")
    fs = Fs(probe, world)
    _, fd = fs.open("hello.txt")
    assert fs.inst.path_unlink_file(3, *fs.path("hello.txt")) == 0
    assert fs.read(fd, 5) == (0, b"hello")


def test_a_readonly_preopen_refuses_every_change(probe: Any, world: Path) -> None:
    fs = Fs(probe, world, readonly=True)
    assert fs.open("new.txt", oflags=1, rights=WRITE_RIGHTS)[0] == E_NOTCAPABLE
    _, fd = fs.open("hello.txt", rights=WRITE_RIGHTS)  # the write rights are taken away, not the open
    assert fs.write(fd, b"x")[0] == E_NOTCAPABLE
    assert fs.open("hello.txt", oflags=8)[0] == E_NOTCAPABLE  # trunc
    assert fs.inst.path_create_directory(3, *fs.path("made")) == E_NOTCAPABLE
    assert fs.inst.path_remove_directory(3, *fs.path("sub")) == E_NOTCAPABLE
    assert fs.inst.path_unlink_file(3, *fs.path("hello.txt")) == E_NOTCAPABLE
    assert fs.inst.path_filestat_set_times(3, 1, *fs.path("hello.txt"), 0, 0, 8) == E_NOTCAPABLE
    assert (world / "hello.txt").read_bytes() == b"hello, files\n" and not (world / "made").exists()


def test_pread_and_pwrite_leave_the_position_where_it_was(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    _, fd = fs.open("hello.txt", rights=WRITE_RIGHTS)
    assert fs.read(fd, 2) == (0, b"he")  # the position is 2
    fs.put(0, (2000).to_bytes(4, "little") + (5).to_bytes(4, "little"))
    assert fs.inst.fd_pread(fd, 0, 1, 7, 8) == 0 and fs.u32(8) == 5 and bytes(fs.mem[2000:2005]) == b"files"
    assert fs.inst.fd_tell(fd, 100) == 0 and fs.u64(100) == 2
    assert fs.inst.fd_pread(fd, 0, 1, 1000, 8) == 0 and fs.u32(8) == 0  # past the end
    fs.put(3000, b"HELLO")
    fs.put(0, (3000).to_bytes(4, "little") + (5).to_bytes(4, "little"))
    assert fs.inst.fd_pwrite(fd, 0, 1, 0, 8) == 0 and fs.u32(8) == 5
    assert (world / "hello.txt").read_bytes() == b"HELLO, files\n"
    assert fs.inst.fd_tell(fd, 100) == 0 and fs.u64(100) == 2
    assert fs.read(fd, 3) == (0, b"LLO")  # reading goes on from where it was
    _, ro = fs.open("hello.txt")
    assert fs.inst.fd_pwrite(ro, 0, 1, 0, 8) == E_NOTCAPABLE
    assert fs.inst.fd_pread(3, 0, 1, 0, 8) == E_ISDIR and fs.inst.fd_pread(1, 0, 1, 0, 8) == E_SPIPE
    assert fs.inst.fd_pread(99, 0, 1, 0, 8) == E_BADF


def test_a_file_is_renamed_moved_and_replaced(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    old, new = fs.path("hello.txt"), fs.path("renamed.txt")
    assert fs.inst.path_rename(3, *old, 3, *new) == 0
    assert not (world / "hello.txt").exists() and (world / "renamed.txt").read_bytes() == b"hello, files\n"
    (world / "other.txt").write_bytes(b"other")
    assert fs.inst.path_rename(3, *fs.path("renamed.txt"), 3, *fs.path("other.txt")) == 0  # replaces
    assert (world / "other.txt").read_bytes() == b"hello, files\n"
    assert fs.inst.path_rename(3, *fs.path("other.txt"), 3, *fs.path("sub/moved.txt")) == 0
    assert (world / "sub" / "moved.txt").is_file()
    assert fs.inst.path_rename(3, *fs.path("sub"), 3, *fs.path("renamed_dir")) == 0
    assert (world / "renamed_dir" / "moved.txt").is_file()
    assert fs.inst.path_rename(3, *fs.path("missing"), 3, *fs.path("x")) == E_NOENT
    assert fs.inst.path_rename(3, *fs.path("renamed_dir"), 3, *fs.path("../escaped")) == E_NOTCAPABLE
    assert fs.inst.path_rename(3, *fs.path("../outside.txt"), 3, *fs.path("x")) == E_NOTCAPABLE
    assert fs.inst.path_rename(3, *fs.path("."), 3, *fs.path("x")) == E_INVAL
    assert fs.inst.path_rename(9, *fs.path("renamed_dir"), 3, *fs.path("y")) == E_BADF


def test_a_hard_link_shares_the_file(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    assert fs.inst.path_link(3, 1, *fs.path("hello.txt"), 3, *fs.path("again.txt")) == 0
    assert (world / "again.txt").read_bytes() == b"hello, files\n"
    assert os.stat(world / "hello.txt").st_nlink == 2
    assert fs.inst.path_link(3, 1, *fs.path("hello.txt"), 3, *fs.path("again.txt")) == E_EXIST
    assert fs.inst.path_link(3, 1, *fs.path("missing"), 3, *fs.path("z")) == E_NOENT
    assert fs.inst.path_link(3, 1, *fs.path("../outside.txt"), 3, *fs.path("z")) == E_NOTCAPABLE
    assert fs.inst.path_link(3, 1, *fs.path("hello.txt"), 3, *fs.path("../z")) == E_NOTCAPABLE


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need a privilege on Windows")
def test_symbolic_links_are_made_and_read_and_never_lead_out(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    assert fs.inst.path_symlink(*fs.path("hello.txt"), 3, *fs.path("link.txt")) == 0
    assert os.readlink(world / "link.txt") == "hello.txt"
    ptr, length = fs.path("link.txt")
    assert fs.inst.path_readlink(3, ptr, length, 4000, 100, 120) == 0
    assert fs.u32(120) == 9 and bytes(fs.mem[4000:4009]) == b"hello.txt"
    assert fs.inst.path_readlink(3, ptr, length, 4000, 5, 120) == 0 and fs.u32(120) == 5  # cut short
    code, fd = fs.open("link.txt")  # and it is followed
    assert code == 0 and fs.read(fd, 5) == (0, b"hello")
    assert fs.inst.path_readlink(3, *fs.path("hello.txt"), 4000, 100, 120) == E_INVAL  # not a link
    assert fs.inst.path_readlink(3, *fs.path("missing"), 4000, 100, 120) == E_NOENT
    assert fs.inst.path_symlink(*fs.path("/etc/passwd"), 3, *fs.path("abs")) == E_NOTCAPABLE
    assert fs.inst.path_symlink(*fs.path("x"), 3, *fs.path("link.txt")) == E_EXIST
    assert fs.inst.path_symlink(*fs.path(""), 3, *fs.path("empty")) == E_NOENT
    assert fs.inst.path_symlink(*fs.path("x"), 3, *fs.path("../escaped")) == E_NOTCAPABLE
    # a link that points out may be made, but it is not followed
    assert fs.inst.path_symlink(*fs.path("../outside.txt"), 3, *fs.path("out")) == 0
    assert fs.open("out")[0] == E_NOTCAPABLE


def _clock(user: int, timeout: int, *, flags: int = 0, clock: int = 1, legacy: bool = False) -> bytes:
    """A subscription to a clock: 48 bytes, or 56 in the first snapshot (whose clock starts with an identifier)."""
    sub = bytearray(56 if legacy else 48)
    sub[0:8] = user.to_bytes(8, "little")  # userdata; the tag at 8 is 0 for a clock
    at = 16
    if legacy:
        sub[16:24] = user.to_bytes(8, "little")
        at = 24
    sub[at : at + 4] = clock.to_bytes(4, "little")
    sub[at + 8 : at + 16] = timeout.to_bytes(8, "little")
    sub[at + 24 : at + 26] = flags.to_bytes(2, "little")
    return bytes(sub)


def _fd_sub(user: int, fd: int, tag: int, *, legacy: bool = False) -> bytes:
    sub = bytearray(56 if legacy else 48)
    sub[0:8] = user.to_bytes(8, "little")
    sub[8] = tag
    sub[16:20] = fd.to_bytes(4, "little")
    return bytes(sub)


def _events(fs: Fs, out: int, count: int) -> list[tuple[int, int, int, int]]:
    """(userdata, error, type, nbytes) of the events at `out`."""
    return [
        (
            int.from_bytes(fs.mem[out + 32 * i : out + 32 * i + 8], "little"),
            int.from_bytes(fs.mem[out + 32 * i + 8 : out + 32 * i + 10], "little"),
            fs.mem[out + 32 * i + 10],
            fs.u64(out + 32 * i + 16),
        )
        for i in range(count)
    ]


def _poll(fs: Fs, subs: list[bytes]) -> tuple[int, list[tuple[int, int, int, int]]]:
    blob = b"".join(subs)
    fs.put(5000, blob)
    code = fs.inst.poll_oneoff(5000, 7000, len(subs), 100)
    return code, _events(fs, 7000, fs.u32(100)) if code == 0 else []


def test_poll_oneoff_sleeps_until_a_clock_and_reports_what_is_ready(probe: Any, world: Path) -> None:
    import time

    fs = Fs(probe, world)
    started = time.monotonic()
    code, events = _poll(fs, [_clock(7, 60_000_000)])  # 60 ms from now
    assert code == 0 and events == [(7, 0, 0, 0)]
    assert time.monotonic() - started >= 0.05
    started = time.monotonic()
    assert _poll(fs, [_clock(8, 1, flags=1)])[1] == [(8, 0, 0, 0)]  # an absolute time that has passed
    assert time.monotonic() - started < 0.05
    _, fd = fs.open("hello.txt")
    started = time.monotonic()
    code, events = _poll(
        fs, [_clock(1, 5_000_000_000), _fd_sub(2, fd, 1), _fd_sub(3, 1, 2)]
    )  # a file and stdout are ready
    assert code == 0 and time.monotonic() - started < 1
    assert events == [(2, 0, 1, len("hello, files\n")), (3, 0, 2, 0)]  # no event for the clock that has not run out
    assert _poll(fs, [_fd_sub(4, 99, 1)])[1] == [(4, E_BADF, 1, 0)]
    assert _poll(fs, [_clock(5, 10, clock=2)])[1] == [
        (5, E_INVAL, 0, 0)
    ]  # the clock of the process: nothing to wait for
    assert _poll(fs, [])[0] == E_INVAL
    fs.put(5000, bytes(48))
    fs.mem[5008] = 9  # not a type of subscription
    assert fs.inst.poll_oneoff(5000, 7000, 1, 100) == E_INVAL


def test_the_first_snapshot_polls_with_its_own_subscription(
    build_extension: Builder, world: Path, tmp_path: Path
) -> None:
    wat = tmp_path / "unstable_fs_probe2.wat"
    wat.write_text(
        (DATA / "wasi_fs_probe.wat").read_text("utf-8").replace("wasi_snapshot_preview1", "wasi_unstable"), "utf-8"
    )
    fs = Fs(build_extension(wat, "wasi_unstable_fs_probe2"), world)
    code, events = _poll(fs, [_clock(7, 20_000_000, legacy=True), _fd_sub(9, 3, 2, legacy=True)])
    assert code == 0 and events == [(9, 0, 2, 0)]  # the directory is ready; the clock has not run out
    assert fs.inst.poll_oneoff(5000, 7000, 1, 100) == 0
    code, events = _poll(fs, [_clock(7, 20_000_000, legacy=True)])
    assert code == 0 and events == [(7, 0, 0, 0)]


def test_a_descriptor_is_never_a_socket(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    assert fs.inst.sock_shutdown(3, 0) == 57  # ENOTSOCK
    _, fd = fs.open("hello.txt")
    assert fs.inst.sock_shutdown(fd, 0) == 57
    assert fs.inst.sock_shutdown(99, 0) == E_BADF
