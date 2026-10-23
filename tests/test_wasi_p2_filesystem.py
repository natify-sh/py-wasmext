"""wasi:filesystem of the host of WASI 0.2 (`wasmext.p2.wasi_p2_filesystem`, `c/p2/wasi_p2_filesystem.h`): the same scenario in Python and in C on a real tree of files.

The tree is made by the test (two identical ones, one for each host). What is compared is the memory the calls write, decoded where it holds inodes or times of the system.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import wasmext
from wasmext.p2 import wasi_p2_filesystem as fs
from wasmext.p2 import wasi_p2_io as io
from wasmext.p2.wasi_p2_core import Host, Trap, load_u32

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the host of the filesystem is POSIX only")

C_P2 = Path(wasmext.__file__).parent / "c" / "p2"
DRIVER = Path(__file__).parent / "data" / "wasi_p2_filesystem_driver.c"
CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

SCENARIOS = ["main", "bad_handle", "outside"]


def make_tree(root: Path) -> None:
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "f").write_text("data")
    (root / "sub" / "g").write_text("")
    os.symlink("sub", root / "ln")
    os.symlink("/etc", root / "abs")
    os.symlink("../x", root / "up")
    os.symlink("loop2", root / "loop1")
    os.symlink("loop1", root / "loop2")
    os.symlink("sub/../sub", root / "deep")


class Run:
    """The calls of the scenario, with the output lines that the C driver prints."""

    def __init__(self, root: Path) -> None:
        self.memory = bytearray(4096)
        self.next_free = [1600]
        self.lines: list[str] = []

        def bump(comp: int, old_ptr: int, old_size: int, align: int, new_size: int) -> int:
            ptr = (self.next_free[0] + align - 1) // align * align
            self.next_free[0] = ptr + new_size
            return ptr

        self.host = Host(
            [self.memory],
            realloc=bump,
            wall_ns=lambda: 1700000000123456789,
            preopens=[(str(root), "/"), (str(root), "/ro", False)],
        )
        self.memory[1500:1505] = b"hello"
        self.memory[1510:1516] = b" world"

    def show(self, label: str, off: int, n: int) -> None:
        self.lines.append(f"{label} {off}:{bytes(self.memory[off : off + n]).hex()}")

    def u32(self, off: int) -> int:
        return load_u32(self.host, 0, off)

    def u64(self, off: int) -> int:
        return self.u32(off) | self.u32(off + 4) << 32

    def clear(self, off: int, n: int) -> None:
        self.memory[off : off + n] = bytes(n)

    def path(self, text: bytes, at: int = 1000) -> int:
        self.memory[at : at + len(text)] = text
        return len(text)

    def statline(self, label: str, r: int) -> None:
        m = self.memory
        if m[r]:
            self.lines.append(f"{label} err {m[r + 8]}")
        else:
            self.lines.append(f"{label} type {m[r + 8]} nlink {self.u64(r + 16)} size {self.u64(r + 24)}")

    def times(self, label: str, r: int) -> None:
        self.lines.append(
            f"{label} atime {self.u64(r + 40)}.{self.u32(r + 48)} mtime {self.u64(r + 64)}.{self.u32(r + 72)}"
        )

    def read_all(self, label: str, h: int, length: int, off: int) -> None:
        self.clear(220, 16)
        fs.wasi_filesystem_types_descriptor_read(self.host, 0, h, length, off, 220)
        self.show(label, 220, 16)
        if not self.memory[220]:
            self.show("  data", self.u32(224), self.u32(228))


def python_output(scenario: str, root: Path) -> str:
    r = Run(root)
    host, m = r.host, r.memory
    T = "wasi_filesystem_types_"
    F = {name[len(T) :]: getattr(fs, name) for name in dir(fs) if name.startswith(T)}

    def fsc(name: str, *args: int) -> None:
        F[name](host, 0, *args)

    def ioc(name: str, *args: int) -> None:
        getattr(io, "wasi_io_streams_" + name)(host, 0, *args)

    try:
        if scenario == "main":
            fs.wasi_filesystem_preopens_get_directories(host, 0, 0)
            lp = r.u32(0)
            hd, ro = r.u32(lp), r.u32(lp + 12)
            r.show("dirs", 0, 8)
            r.show("dirs", lp, 24)
            r.show("names", r.u32(lp + 4), 1)
            r.show("names", r.u32(lp + 16), 3)
            r.lines.append(f"handles {hd} {ro}")
            cases = [
                (b"sub/f", 1), (b"ln/f", 1), (b"abs/passwd", 1), (b"up", 1), (b"../x", 1), (b"sub/../sub/f", 1), (b"/etc", 1), (b"loop1", 1),
                (b"deep/f", 1), (b"nope", 1), (b"sub/f/x", 1), (b"", 1), (b"sub/", 1), (b"sub/f/", 1), (b"ln", 0), (b"ln", 1), (b"ln/", 0),
                (b"sub/..", 1), (b"sub/../..", 1),
            ]  # fmt: skip
            for text, flags in cases:
                n = r.path(text)
                r.clear(200, 120)
                fsc("descriptor_stat_at", hd, flags, 1000, n, 200)
                r.lines.append(f"[{text.decode()}] " + _stat(r, 200))
            n = r.path(b"a" * 300)
            r.clear(200, 120)
            fsc("descriptor_stat_at", hd, 1, 1000, n, 200)
            r.lines.append("[long] " + _stat(r, 200, "[long] stat"))
            # open, read
            n = r.path(b"sub/f")
            fsc("descriptor_open_at", hd, 1, 1000, n, 0, 1, 200)
            r.show("open", 200, 8)
            h = r.u32(204)
            r.read_all("read", h, 10, 0)
            r.read_all("read", h, 10, 2)
            r.read_all("read", h, 10, 4)
            r.read_all("read", h, 2, 0)
            fsc("descriptor_get_type", h, 240)
            r.show("type", 240, 2)
            fsc("descriptor_get_flags", h, 242)
            r.show("flags", 242, 2)
            r.clear(300, 120)
            fsc("descriptor_stat", h, 300)
            r.statline("fstat", 300)
            fsc("descriptor_read_via_stream", h, 1, 250)
            r.show("read_via_stream", 250, 8)
            hs = r.u32(254)
            ioc("input_stream_read", hs, 100, 260)
            r.show("stream read", 260, 12)
            r.show("  data", r.u32(264), r.u32(268))
            ioc("input_stream_read", hs, 100, 260)
            r.show("stream read at the end", 260, 12)
            io.wasi_io_streams_input_stream_drop(host, hs)
            fsc("descriptor_write", h, 1500, 3, 0, 270)
            r.show("write on read-only", 270, 16)
            fsc("descriptor_set_size", h, 1, 290)
            r.show("set_size on read-only", 290, 2)
            fs.wasi_filesystem_types_descriptor_drop(host, h)
            # create and write
            n = r.path(b"sub/new")
            fsc("descriptor_open_at", hd, 1, 1000, n, 1, 3, 200)
            r.show("create", 200, 8)
            hn = r.u32(204)
            fsc("descriptor_write", hn, 1500, 5, 0, 220)
            r.show("write", 220, 16)
            fsc("descriptor_write_via_stream", hn, 5, 250)
            hw = r.u32(254)
            ioc("output_stream_blocking_write_and_flush", hw, 1510, 6, 260)
            r.show("stream write", 260, 8)
            io.wasi_io_streams_output_stream_drop(host, hw)
            r.read_all("read back", hn, 100, 0)
            fsc("descriptor_append_via_stream", hn, 250)
            ha = r.u32(254)
            ioc("output_stream_write", ha, 1500, 5, 260)
            r.show("append", 260, 8)
            io.wasi_io_streams_output_stream_drop(host, ha)
            r.read_all("read appended", hn, 100, 0)
            fsc("descriptor_set_size", hn, 3, 270)
            r.show("set_size", 270, 2)
            r.read_all("read truncated", hn, 100, 0)
            fsc("descriptor_sync", hn, 280)
            fsc("descriptor_sync_data", hn, 284)
            fsc("descriptor_advise", hn, 0, 0, 0, 288)
            r.show("sync", 280, 10)
            fs.wasi_filesystem_types_descriptor_drop(host, hn)
            fsc("descriptor_open_at", hd, 1, 1000, n, 5, 3, 200)
            r.show("exclusive create of an existing file", 200, 8)
            fsc("descriptor_open_at", ro, 1, 1000, n, 8, 2, 200)
            r.show("truncate on a read-only preopen", 200, 8)
            fsc("descriptor_open_at", ro, 1, 1000, n, 1, 1, 200)
            r.show("create on a read-only preopen", 200, 8)
            fsc("descriptor_open_at", ro, 1, 1000, n, 0, 3, 200)
            r.show("write on a read-only preopen", 200, 8)
            fsc("descriptor_open_at", ro, 1, 1000, n, 0, 1, 200)
            r.show("read on a read-only preopen", 200, 8)
            fs.wasi_filesystem_types_descriptor_drop(host, r.u32(204))
            fsc("descriptor_get_flags", ro, 240)
            fsc("descriptor_get_flags", hd, 242)
            r.show("preopen flags", 240, 4)
            # directories
            n = r.path(b"sub")
            fsc("descriptor_open_at", hd, 1, 1000, n, 2, 1, 200)
            r.show("open a directory", 200, 8)
            hdir = r.u32(204)
            fsc("descriptor_read_directory", hdir, 220)
            r.show("read_directory", 220, 8)
            he = r.u32(224)
            for _ in range(5):
                r.clear(240, 20)
                fsc("directory_entry_stream_read_directory_entry", he, 240)
                r.show("entry", 240, 20)
                if m[244]:
                    r.show("  name", r.u32(252), r.u32(256))
                else:
                    break
            fs.wasi_filesystem_types_directory_entry_stream_drop(host, he)
            fs.wasi_filesystem_types_descriptor_drop(host, hdir)
            n = r.path(b"sub/f")
            fsc("descriptor_open_at", hd, 1, 1000, n, 0, 1, 200)
            h = r.u32(204)
            fsc("descriptor_read_directory", h, 220)
            r.show("read_directory of a file", 220, 8)
            fs.wasi_filesystem_types_descriptor_drop(host, h)
            # changes
            n = r.path(b"sub/d")
            fsc("descriptor_create_directory_at", hd, 1000, n, 300)
            fsc("descriptor_create_directory_at", hd, 1000, n, 302)
            fsc("descriptor_create_directory_at", ro, 1000, n, 304)
            fsc("descriptor_remove_directory_at", hd, 1000, n, 306)
            fsc("descriptor_remove_directory_at", hd, 1000, n, 308)
            r.show("mkdir mkdir mkdir(ro) rmdir rmdir", 300, 10)
            n = r.path(b"sub/new")
            fsc("descriptor_unlink_file_at", hd, 1000, n, 300)
            fsc("descriptor_unlink_file_at", hd, 1000, n, 302)
            r.show("unlink unlink", 300, 4)
            n2 = r.path(b"sub/g")
            r.path(b"sub/g2", 1100)
            fsc("descriptor_rename_at", hd, 1000, n2, hd, 1100, 6, 310)
            r.show("rename", 310, 2)
            r.path(b"sub/f2", 1200)
            n = r.path(b"sub/f")
            fsc("descriptor_link_at", hd, 0, 1000, n, hd, 1200, 6, 312)
            r.show("link", 312, 2)
            r.clear(320, 120)
            fsc("descriptor_stat_at", hd, 1, 1000, n, 320)
            r.statline("sub/f after link", 320)
            r.path(b"f", 1300)
            r.path(b"sub/sl", 1310)
            fsc("descriptor_symlink_at", hd, 1300, 1, 1310, 6, 314)
            r.show("symlink", 314, 2)
            fsc("descriptor_readlink_at", hd, 1310, 6, 330)
            r.show("readlink", 330, 12)
            r.show("  target", r.u32(334), r.u32(338))
            fsc("descriptor_readlink_at", hd, 1000, n, 330)
            r.show("readlink of a file", 330, 8)
            # identity
            fsc("descriptor_open_at", hd, 1, 1000, n, 0, 1, 200)
            a = r.u32(204)
            fsc("descriptor_open_at", hd, 1, 1200, 6, 0, 1, 200)
            b = r.u32(204)
            fsc("descriptor_open_at", hd, 1, 1100, 6, 0, 1, 200)
            c = r.u32(204)
            same = fs.wasi_filesystem_types_descriptor_is_same_object
            r.lines.append(f"same {same(host, a, b)} {same(host, a, c)}")
            fsc("descriptor_metadata_hash", a, 400)
            fsc("descriptor_metadata_hash", b, 430)
            fsc("descriptor_metadata_hash", c, 460)
            fsc("descriptor_metadata_hash_at", hd, 1, 1000, n, 490)
            r.lines.append(
                f"hash a==b {int(m[408:424] == m[438:454])} a==c {int(m[408:424] == m[468:484])} a==at {int(m[408:424] == m[498:514])}"
            )
            # times
            fsc("descriptor_set_times_at", hd, 1, 1000, n, 2, 1000, 0, 2, 2000, 5, 520)
            r.show("set_times_at", 520, 2)
            r.clear(530, 120)
            fsc("descriptor_stat_at", hd, 1, 1000, n, 530)
            r.times("times", 530)
            fsc("descriptor_set_times", a, 0, 0, 0, 1, 0, 0, 540)
            r.show("set_times on a read-only file", 540, 2)
            fsc("descriptor_open_at", hd, 1, 1000, n, 0, 3, 200)
            h = r.u32(204)
            fsc("descriptor_set_times", h, 0, 0, 0, 1, 0, 0, 542)
            r.show("set_times", 542, 2)
            r.clear(530, 120)
            fsc("descriptor_stat", h, 530)
            r.times("no-change, now", 530)
            # the rules of the WIT: absolute links, a directory to unlink, the hash follows the contents
            r.path(b"abs", 1400)
            fsc("descriptor_readlink_at", hd, 1400, 3, 600)
            r.show("readlink of an absolute link", 600, 8)
            r.path(b"/etc", 1410)
            r.path(b"sub/sl2", 1420)
            fsc("descriptor_symlink_at", hd, 1410, 4, 1420, 7, 610)
            r.show("symlink to an absolute path", 610, 2)
            fsc("descriptor_symlink_at", ro, 1300, 1, 1420, 7, 612)
            r.show("symlink on a read-only preopen", 612, 2)
            r.path(b"sub", 1430)
            fsc("descriptor_unlink_file_at", hd, 1430, 3, 620)
            r.show("unlink of a directory", 620, 2)
            fsc("descriptor_metadata_hash_at", hd, 1, 1000, n, 640)
            fsc("descriptor_open_at", hd, 1, 1000, n, 0, 2, 200)
            h = r.u32(204)
            fsc("descriptor_write", h, 1500, 1, 100, 670)
            r.show("write past the end", 670, 16)
            fs.wasi_filesystem_types_descriptor_drop(host, h)
            fsc("descriptor_metadata_hash_at", hd, 1, 1000, n, 700)
            r.lines.append(f"hash after a write: same {int(m[648:664] == m[708:724])}")
            # an error with a code
            fsc("descriptor_read_via_stream", hd, 0, 250)
            hs = r.u32(254)
            ioc("input_stream_read", hs, 10, 260)
            r.show("read of a directory", 260, 12)
            fs.wasi_filesystem_types_filesystem_error_code(host, 0, r.u32(268), 280)
            r.show("error code", 280, 2)
        elif scenario == "bad_handle":
            fsc("descriptor_get_flags", 12345, 0)
        elif scenario == "outside":
            fsc("descriptor_stat_at", 1048577, 1, 4090, 100, 0)
    except Trap:
        r.lines.append("TRAP")
    return "\n".join(r.lines) + "\n"


def _stat(r: Run, at: int, label: str = "stat") -> str:
    m = r.memory
    if m[at]:
        return f"stat err {m[at + 8]}"
    return f"stat type {m[at + 8]} nlink {r.u64(at + 16)} size {r.u64(at + 24)}"


def c_output(scenario: str, binary: Path, root: Path) -> str:
    out = subprocess.run(
        [str(binary), scenario, str(root)], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    return "\n".join("TRAP" if line.startswith("TRAP") else line for line in out.splitlines()) + "\n"


@pytest.fixture(scope="module")
def driver(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if CC is None:
        pytest.skip("no C compiler")
    binary = tmp_path_factory.mktemp("p2fs") / "driver"
    subprocess.run(
        [CC, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-I", str(C_P2), str(DRIVER), "-o", str(binary)], check=True
    )
    return binary


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_c_and_python_agree(driver: Path, scenario: str, tmp_path: Path) -> None:
    py_root, c_root = tmp_path / "py", tmp_path / "c"
    make_tree(py_root)
    make_tree(c_root)
    assert python_output(scenario, py_root) == c_output(scenario, driver, c_root)


def test_values(tmp_path: Path) -> None:
    make_tree(tmp_path)
    lines = python_output("main", tmp_path).splitlines()
    got = {line.split("] ")[0] + "]": line.split("] ")[1] for line in lines if line.startswith("[")}
    assert got["[sub/f]"].startswith("stat type 6 nlink 1 size 4")  # a regular file of 4 bytes
    assert got["[ln/f]"] == got["[sub/f]"]  # through a link to a directory inside the tree
    for escape in ("[abs/passwd]", "[up]", "[../x]", "[/etc]", "[sub/../..]"):
        assert got[escape] == f"stat err {fs.ERROR_CODES.index('not-permitted')}", escape  # nothing leaves the tree
    assert got["[loop1]"] == f"stat err {fs.ERROR_CODES.index('loop')}"
    assert got["[nope]"] == f"stat err {fs.ERROR_CODES.index('no-entry')}"
    assert got["[sub/f/x]"] == f"stat err {fs.ERROR_CODES.index('not-directory')}"
    assert got["[long]"] == f"stat err {fs.ERROR_CODES.index('name-too-long')}"
    code = fs.ERROR_CODES.index

    def result(label: str, offset: int, at: int = 1) -> int:
        """The error-code byte of an `err` result that the scenario shows (at 1 in `result<_, error-code>`, at 4 in `result<string, error-code>`)."""
        line = next(line for line in lines if line.startswith(f"{label} {offset}:"))
        data = bytes.fromhex(line.split(":")[1])
        assert data[0] == 1, line  # an error
        return data[at]

    assert result("unlink of a directory", 620) == code("is-directory")
    assert result("symlink to an absolute path", 610) == code("not-permitted")
    assert result("symlink on a read-only preopen", 612) == code("read-only")
    assert result("readlink of an absolute link", 600, 4) == code("not-permitted")
    assert "hash after a write: same 0" in lines  # the hash follows size and modification time
    # open-at on a read-only preopen with write: the code is at 4 in the 8 bytes of result<descriptor, error-code>
    ro_write = bytes.fromhex(
        next(line for line in lines if line.startswith("write on a read-only preopen 200:")).split(":")[1]
    )
    assert ro_write[0] == 1 and ro_write[4] == code("read-only")
    assert "same 1 0" in lines and "hash a==b 1 a==c 0 a==at 1" in lines
    assert any(line.startswith("times atime 1000.0 mtime 2000.5") for line in lines)
    assert any(line.startswith("no-change, now atime 1000.0 mtime 1700000000.123456789") for line in lines)
    assert any(line.startswith("error code") and line.endswith("010e") for line in lines)  # some(is-directory)
    assert (
        (tmp_path / "sub" / "g2").exists()
        and (tmp_path / "sub" / "f2").exists()
        and not (tmp_path / "sub" / "g").exists()
    )
    assert os.readlink(tmp_path / "sub" / "sl") == "f"


def test_walk_stays_below_the_directory(tmp_path: Path) -> None:
    """A direct check of the walk, with a link that points up through a name that is allowed to be entered."""
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "secret").write_text("x")
    os.symlink("../out", tmp_path / "in" / "esc")
    fd = os.open(tmp_path / "in", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for path in (b"esc/secret", b"esc", b"./esc/../secret", b"a/../../out/secret"):
            with pytest.raises(fs.FsError) as caught:
                fs._walk(fd, path, True)  # pyright: ignore[reportPrivateUsage]
            assert fs.ERROR_CODES[caught.value.code] in ("not-permitted", "no-entry"), path
    finally:
        os.close(fd)
