"""WASI for files and directories, the first stage (reading): the preopens, path_open, fd_read, fd_seek, fd_filestat_get,
fd_readdir, and the confinement of a program to the directories it was given."""

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

E_BADF, E_ISDIR, E_NOENT, E_NOSYS, E_NOTDIR, E_NOTCAPABLE, E_NAMETOOLONG, E_SPIPE = 8, 31, 44, 52, 54, 76, 37, 70
# the rights the way wasi-libc asks for them to read a file
FILE_RIGHTS = (1 << 1) | (1 << 2) | (1 << 5) | (1 << 21)  # fd_read, fd_seek, fd_tell, fd_filestat_get
DIR_RIGHTS = (1 << 13) | (1 << 14) | (1 << 18) | (1 << 21)  # path_open, fd_readdir, path_filestat_get, fd_filestat_get


@pytest.fixture
def world(tmp_path: Path) -> Path:
    root = tmp_path / "world"
    (root / "sub").mkdir(parents=True)
    (root / "hello.txt").write_text("hello, files\n", encoding="utf-8")
    (root / "sub" / "deep.txt").write_text("deep", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    return root


class Fs:
    """A probe module with a preopen, and the memory calls around it."""

    def __init__(self, mod: Any, root: Path, **options: Any) -> None:
        self.inst = mod.Instance(wasi={"preopens": {"/": str(root)}, **options})
        self.mem = self.inst.memory

    def put(self, at: int, data: bytes) -> None:
        self.mem[at : at + len(data)] = data

    def u32(self, at: int) -> int:
        return int.from_bytes(self.mem[at : at + 4], "little")

    def u64(self, at: int) -> int:
        return int.from_bytes(self.mem[at : at + 8], "little")

    def open(
        self, name: str, *, fd: int = 3, flags: int = 1, oflags: int = 0, rights: int = FILE_RIGHTS, inheriting: int = 0
    ) -> tuple[int, int]:
        self.put(1000, name.encode())
        code = self.inst.path_open(fd, flags, 1000, len(name.encode()), oflags, rights, inheriting, 0, 900)
        return code, self.u32(900)

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


def test_what_is_not_there_or_not_yet_there_is_refused_by_name(probe: Any, world: Path) -> None:
    fs = Fs(probe, world)
    assert fs.open("missing.txt")[0] == E_NOENT
    assert fs.open("hello.txt", oflags=2)[0] == E_NOTDIR  # asked for a directory
    assert fs.open("hello.txt", oflags=1)[0] == E_NOSYS  # creating: the second stage
    assert fs.open("hello.txt", rights=FILE_RIGHTS | (1 << 6))[0] == E_NOSYS  # writing: the second stage
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
    assert fs.inst.fd_renumber(1, 5) == 58  # the standard streams stay where they are (ENOTSUP)


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
