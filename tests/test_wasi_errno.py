"""The errno of WASI that the C library's errno becomes (`wasi_errno` in wasi_core.h): the whole list of the specification, not only the common ones.

Found by comparing with uvwasi, which maps 56 errnos; there were 27, and everything else was EIO.
"""

import errno
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from wasmext._toolchain import find_toolchain

C_DIR = Path(__file__).parent.parent / "src" / "wasmext" / "c"
CHECK = Path(__file__).parent / "data" / "wasi_errno_check.c"
CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

# the errno enum of preview1 (witx), by name: the number a program sees
WASI = {
    "E2BIG": 1, "EACCES": 2, "EADDRINUSE": 3, "EADDRNOTAVAIL": 4, "EAFNOSUPPORT": 5, "EAGAIN": 6, "EALREADY": 7, "EBADF": 8, "EBADMSG": 9,
    "EBUSY": 10, "ECANCELED": 11, "ECHILD": 12, "ECONNABORTED": 13, "ECONNREFUSED": 14, "ECONNRESET": 15, "EDEADLK": 16, "EDESTADDRREQ": 17,
    "EDOM": 18, "EDQUOT": 19, "EEXIST": 20, "EFAULT": 21, "EFBIG": 22, "EHOSTUNREACH": 23, "EIDRM": 24, "EILSEQ": 25, "EINPROGRESS": 26,
    "EINTR": 27, "EINVAL": 28, "EIO": 29, "EISCONN": 30, "EISDIR": 31, "ELOOP": 32, "EMFILE": 33, "EMLINK": 34, "EMSGSIZE": 35,
    "EMULTIHOP": 36, "ENAMETOOLONG": 37, "ENETDOWN": 38, "ENETRESET": 39, "ENETUNREACH": 40, "ENFILE": 41, "ENOBUFS": 42, "ENODEV": 43,
    "ENOENT": 44, "ENOEXEC": 45, "ENOLCK": 46, "ENOLINK": 47, "ENOMEM": 48, "ENOMSG": 49, "ENOPROTOOPT": 50, "ENOSPC": 51, "ENOSYS": 52,
    "ENOTCONN": 53, "ENOTDIR": 54, "ENOTEMPTY": 55, "ENOTRECOVERABLE": 56, "ENOTSOCK": 57, "ENOTSUP": 58, "ENOTTY": 59, "ENXIO": 60,
    "EOVERFLOW": 61, "EOWNERDEAD": 62, "EPERM": 63, "EPIPE": 64, "EPROTO": 65, "EPROTONOSUPPORT": 66, "EPROTOTYPE": 67, "ERANGE": 68,
    "EROFS": 69, "ESPIPE": 70, "ESRCH": 71, "ESTALE": 72, "ETIMEDOUT": 73, "ETXTBSY": 74, "EXDEV": 75,
}  # fmt: skip


@pytest.mark.skipif(sys.platform == "win32" or CC is None, reason="POSIX with a C compiler")
def test_every_errno_of_the_specification_has_its_own_number(tmp_path: Path) -> None:
    binary = tmp_path / "check"
    subprocess.run(
        [
            CC or "cc",
            "-std=gnu11",
            "-Wall",
            "-I",
            str(find_toolchain().runtime),
            "-I",
            str(C_DIR),
            str(CHECK),
            "-o",
            str(binary),
        ],
        check=True,
    )
    known = {name: getattr(errno, name) for name in WASI if hasattr(errno, name)}
    out = subprocess.run([str(binary), *map(str, known.values())], capture_output=True, text=True, check=True).stdout
    got = {int(a): int(b) for a, b in (line.split() for line in out.splitlines())}
    for name, value in known.items():
        assert got[value] == WASI[name], f"{name} ({value}) should be {WASI[name]}, is {got[value]}"
    # the names that are other names for the same number are not a case of their own
    assert got[errno.EWOULDBLOCK] == WASI["EAGAIN"]
    # an errno that has no number in the specification is an I/O error, as before
    assert subprocess.run([str(binary), "99999"], capture_output=True, text=True, check=True).stdout.split()[1] == str(
        WASI["EIO"]
    )
    assert len(known) >= 60  # the platform has nearly all of them
