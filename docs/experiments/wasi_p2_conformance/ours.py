"""Runs a script of operations (see script_fs.txt) on the Python host of wasmext, and returns the lines that the guest of Wasmtime prints for the same script."""

from __future__ import annotations

from pathlib import Path

from wasmext.p2 import wasi_p2_filesystem as fs
from wasmext.p2 import wasi_p2_io as io
from wasmext.p2.wasi_p2_core import Host, load_u32

R = 256
KINDS = ["unknown", "block-device", "character-device", "directory", "fifo", "symbolic-link", "regular-file", "socket"]
FLAG_LETTERS = "rwfdqm"


def text(token: str) -> str:
    return "" if token == "''" else token.replace("\\n", "\n")


class Ours:
    def __init__(self, preopens: list[tuple[str, str, bool]]) -> None:
        self.memory = bytearray(1 << 20)
        self.free = 0x80000
        self.inp = 0x1000

        def bump(comp: int, old_ptr: int, old_size: int, align: int, new_size: int) -> int:
            ptr = (self.free + align - 1) // align * align
            self.free = ptr + new_size
            return ptr

        self.host = Host([self.memory], realloc=bump, preopens=preopens)
        self.h: dict[str, int] = {}

    # memory helpers
    def u32(self, off: int) -> int:
        return load_u32(self.host, 0, off)

    def u64(self, off: int) -> int:
        return int.from_bytes(self.memory[off : off + 8], "little")

    def put(self, data: bytes) -> tuple[int, int]:
        ptr = self.inp
        self.memory[ptr : ptr + len(data)] = data
        self.inp = (ptr + len(data) + 8) // 8 * 8
        return ptr, len(data)

    def clear(self) -> None:
        self.memory[R : R + 128] = bytes(128)

    def err(self, at: int) -> str:
        return "err=" + fs.ERROR_CODES[self.memory[R + at]]

    def failed(self, at: int) -> bool:
        return self.memory[R] == 1

    def call(self, name: str, *args: int) -> None:
        self.clear()
        getattr(fs, "wasi_filesystem_types_descriptor_" + name)(self.host, 0, *args, R)

    def string(self, off: int) -> str:
        return bytes(self.memory[self.u32(off) : self.u32(off) + self.u32(off + 4)]).decode("latin-1")

    @staticmethod
    def pflags(s: str) -> int:
        return 1 if "f" in s else 0

    @staticmethod
    def oflags(s: str) -> int:
        return sum(bit for letter, bit in (("c", 1), ("d", 2), ("e", 4), ("t", 8)) if letter in s)

    @staticmethod
    def dflags(s: str) -> int:
        return sum(1 << FLAG_LETTERS.index(c) for c in s if c in FLAG_LETTERS)

    def stat_text(self, at: int) -> str:
        return f"type={KINDS[self.memory[at]]} size={self.u64(at + 16)} links={self.u64(at + 8)}"

    def stream_error(self) -> str:
        return "stream-failed" if self.memory[R + 4] == 0 else "stream-closed"

    def op(self, t: list[str]) -> str:
        h, o = self.h, t[0]
        used = {"preopen": [], "open": [2], "rename": [1, 3], "link": [1, 4], "same": [1, 2]}.get(o, [1])
        if any(t[i] not in h for i in used):
            return "no-handle"

        def d(i: int) -> int:
            return h[t[i]]

        def path(i: int) -> tuple[int, int]:
            return self.put(text(t[i]).encode())

        if o == "preopen":
            self.clear()
            fs.wasi_filesystem_preopens_get_directories(self.host, 0, R)
            ptr, n = self.u32(R), self.u32(R + 4)
            i = int(t[2])
            h[t[1]] = self.u32(ptr + 12 * i)
            return "name=" + self.string(ptr + 12 * i + 4)
        if o == "open":
            p, n = path(3)
            self.call("open_at", d(2), self.pflags(t[4]), p, n, self.oflags(t[5]), self.dflags(t[6]))
            if self.failed(4):
                return self.err(4)
            h[t[1]] = self.u32(R + 4)
            return "ok"
        if o == "stat":
            self.call("stat", d(1))
            return self.err(8) if self.failed(8) else self.stat_text(R + 8)
        if o == "stat-at":
            p, n = path(3)
            self.call("stat_at", d(1), self.pflags(t[2]), p, n)
            return self.err(8) if self.failed(8) else self.stat_text(R + 8)
        if o == "type":
            self.call("get_type", d(1))
            return self.err(1) if self.failed(1) else KINDS[self.memory[R + 1]]
        if o == "flags":
            self.call("get_flags", d(1))
            if self.failed(1):
                return self.err(1)
            bits = self.memory[R + 1]
            return "".join(c for i, c in enumerate(FLAG_LETTERS) if bits >> i & 1) or "-"
        if o == "read":
            self.call("read", d(1), int(t[3]), int(t[2]))
            if self.failed(4):
                return self.err(4)
            data = bytes(self.memory[self.u32(R + 4) : self.u32(R + 4) + self.u32(R + 8)])
            return f"{data.hex()} eof={str(bool(self.memory[R + 12])).lower()}"
        if o == "write":
            p, n = self.put(text(t[3]).encode())
            self.call("write", d(1), p, n, int(t[2]))
            return self.err(8) if self.failed(8) else f"written={self.u64(R + 8)}"
        if o == "read-stream":
            self.call("read_via_stream", d(1), int(t[2]))
            if self.failed(4):
                return self.err(4)
            s = self.u32(R + 4)
            self.clear()
            io.wasi_io_streams_input_stream_blocking_read(self.host, 0, s, int(t[3]), R)
            out = (
                self.stream_error()
                if self.memory[R] == 1
                else bytes(self.memory[self.u32(R + 4) : self.u32(R + 4) + self.u32(R + 8)]).hex()
            )
            io.wasi_io_streams_input_stream_drop(self.host, s)
            return out
        if o in ("write-stream", "append-stream"):
            data = text(t[3] if o == "write-stream" else t[2]).encode()
            if o == "write-stream":
                self.call("write_via_stream", d(1), int(t[2]))
            else:
                self.call("append_via_stream", d(1))
            if self.failed(4):
                return self.err(4)
            s = self.u32(R + 4)
            p, n = self.put(data)
            self.clear()
            io.wasi_io_streams_output_stream_blocking_write_and_flush(self.host, 0, s, p, n, R)
            out = self.stream_error() if self.memory[R] == 1 else "ok"
            io.wasi_io_streams_output_stream_drop(self.host, s)
            return out
        if o == "readdir":
            self.call("read_directory", d(1))
            if self.failed(4):
                return self.err(4)
            s = self.u32(R + 4)
            names = []
            while True:
                self.clear()
                fs.wasi_filesystem_types_directory_entry_stream_read_directory_entry(self.host, 0, s, R)
                if self.memory[R] == 1:
                    names.append(self.err(4))
                    break
                if not self.memory[R + 4]:
                    break
                names.append(f"{self.string(R + 12)}:{KINDS[self.memory[R + 8]]}")
            fs.wasi_filesystem_types_directory_entry_stream_drop(self.host, s)
            return ",".join(sorted(names))
        if o in ("mkdir", "rmdir", "unlink"):
            p, n = path(2)
            name = {"mkdir": "create_directory_at", "rmdir": "remove_directory_at", "unlink": "unlink_file_at"}[o]
            self.call(name, d(1), p, n)
            return self.err(1) if self.failed(1) else "ok"
        if o == "rename":
            p, n = path(2)
            q, m = path(4)
            self.call("rename_at", d(1), p, n, d(3), q, m)
            return self.err(1) if self.failed(1) else "ok"
        if o == "symlink":
            p, n = path(2)
            q, m = path(3)
            self.call("symlink_at", d(1), p, n, q, m)
            return self.err(1) if self.failed(1) else "ok"
        if o == "link":
            p, n = path(3)
            q, m = path(5)
            self.call("link_at", d(1), self.pflags(t[2]), p, n, d(4), q, m)
            return self.err(1) if self.failed(1) else "ok"
        if o == "readlink":
            p, n = path(2)
            self.call("readlink_at", d(1), p, n)
            return self.err(4) if self.failed(4) else "target=" + self.string(R + 4)
        if o == "set-size":
            self.call("set_size", d(1), int(t[2]))
            return self.err(1) if self.failed(1) else "ok"
        if o in ("sync", "sync-data"):
            self.call(o.replace("-", "_"), d(1))
            return self.err(1) if self.failed(1) else "ok"
        if o == "advise":
            self.call("advise", d(1), int(t[2]), int(t[3]), 0)
            return self.err(1) if self.failed(1) else "ok"
        if o == "same":
            return str(bool(fs.wasi_filesystem_types_descriptor_is_same_object(self.host, d(1), d(2)))).lower()
        if o == "hash":
            self.call("metadata_hash", d(1))
            if self.failed(8):
                return self.err(8)
            first = bytes(self.memory[R + 8 : R + 24])
            self.call("metadata_hash", d(1))
            return f"stable={str(first == bytes(self.memory[R + 8 : R + 24])).lower()}"
        if o == "hash-at":
            p, n = path(3)
            self.call("metadata_hash_at", d(1), self.pflags(t[2]), p, n)
            if self.failed(8):
                return self.err(8)
            first = bytes(self.memory[R + 8 : R + 24])
            self.call("metadata_hash_at", d(1), self.pflags(t[2]), p, n)
            return f"stable={str(first == bytes(self.memory[R + 8 : R + 24])).lower()}"
        if o == "drop":
            fs.wasi_filesystem_types_descriptor_drop(self.host, h.pop(t[1]))
            return "ok"
        raise SystemExit(f"unknown op {o}")


def run(script: Path, preopens: list[tuple[str, str, bool]]) -> list[str]:
    ours = Ours(preopens)
    lines = []
    n = 0
    for line in script.read_text().splitlines():
        line = line.split("#~")[0].strip()
        if not line or line.startswith("#"):
            continue
        n += 1
        t = line.split()
        lines.append(f"{n} {t[0]}: {ours.op(t)}")
    return lines
