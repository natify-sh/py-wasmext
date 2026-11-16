"""The host of the JSLinux (TinyEMU, Emscripten) x86_64 module, written for engines that are driven from Python.

It replaces what `x86_64emu-wasm.js` and `jslinux.js` do around the module: the 27 imports (named `a.a` .. `a.A` in
the minified module), the timers that drive the emulator (`emscripten_async_call`), and the downloads of the files of
the VM (`emscripten_async_wget3_data`: the config, the kernel, the files of the root file system). The semantics are read
from that JavaScript. Only GET is performed; a POST (what a VFsync account would upload) is refused, so nothing is
ever written to a server. Answers are cached on disk, so that a run does not depend on the network.
"""

from __future__ import annotations

import hashlib
import heapq
import os
import random
import struct
import sys
import time
import urllib.request
from collections import deque

CACHE = os.environ.get("JSL_CACHE", "/tmp/claude-0/jsl_exp/cache")

# the minified names of the imports (a.<name>), in the order of the module, and what they are
NAMES = {
    "a": "assert_fail", "b": "exit", "c": "file_buffer_write", "d": "file_buffer_read", "e": "random",
    "f": "wget_update_downloading", "g": "file_buffer_resize", "h": "file_buffer_init", "i": "file_buffer_reset",
    "j": "wget3_data", "k": "fd_write", "l": "async_call", "m": "date_now", "n": "fs_export_file",
    "o": "net_recv_packet", "p": "console_write", "q": "fb_refresh", "r": "resize_heap", "s": "fd_seek",
    "t": "fd_close", "u": "gmtime_js", "v": "localtime_js", "w": "tzset_js", "x": "clock_time_get",
    "y": "abort_js", "z": "file_buffer_set", "A": "console_get_size",
}  # fmt: skip


def clean_tail(raw, n=80):
    import re

    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", bytes(raw[-400:]).decode("utf-8", "replace")).replace("\r", "")[-n:]


class Exited(Exception):
    pass


class Host:
    """The state of the VM's environment; `imports()` gives the functions of the module's import `a`."""

    def __init__(self, *, verbose=False):
        self.m = None
        self.call = self.malloc = self.free = None
        self.verbose = verbose
        self.timers: list[tuple[float, int, int, int]] = []
        self.events: deque = deque()
        self.seq = 0
        self.fbuf: dict[int, bytearray] = {}
        self.fbuf_next = 1
        self.wget_next = 1
        self.console = bytearray()
        self.stdio = bytearray()
        self.exit_code: int | None = None
        self.fetched: list[tuple[str, int, float]] = []
        self.zone_ptr = 0
        self.timer_calls = 0
        self.pending_input = bytearray()
        self.heartbeat = False
        self.t_start = time.monotonic()
        self.send = None  # set by the driver: sends one character to the console of the guest

    def bind(self, memory, call, malloc, free, *, rd=None, wr=None, size=None):
        """After the instance exists: `memory` is a writable memoryview of the guest memory (the module never grows it), or None
        with `rd(address, n) -> bytes` and `wr(address, data)` for an engine whose memory is not in this process;
        `call(index, *args)` calls the function of the table at `index`, `malloc` and `free` are the module's."""
        self.m = memory
        self.call, self.malloc, self.free = call, malloc, free
        self.size = size if size is not None else len(memory)
        if rd is not None:
            self.rd, self.wr = rd, wr

    # --- memory helpers ---
    def rd(self, a, n):
        return bytes(self.m[a : a + n])

    def wr(self, a, data):
        self.m[a : a + len(data)] = data

    def u32(self, a):
        return struct.unpack("<I", self.rd(a, 4))[0]

    def w32(self, a, v):
        self.wr(a, struct.pack("<I", v & 0xFFFFFFFF))

    def cstr(self, a):
        if not a:
            return ""
        out = b""
        while True:
            chunk = self.rd(a + len(out), 64)
            if b"\0" in chunk:
                return (out + chunk.split(b"\0")[0]).decode("utf-8", "replace")
            out += chunk

    def put_cstr(self, text):
        raw = text.encode() + b"\0"
        p = self.malloc(len(raw))
        self.wr(p, raw)
        return p

    # --- the imports ---
    def imports(self):
        h = self
        c = {}

        def assert_fail(cond, file, line, func):
            raise RuntimeError(f"assert: {h.cstr(cond)} at {h.cstr(file)}:{line} {h.cstr(func)}")

        def exit_(code):
            h.exit_code = code
            raise Exited(code)

        def abort_js():
            raise RuntimeError("abort()")

        def fb_write(bs, offset, buf, size):
            hd = h.u32(bs)
            if hd:
                h.fbuf[hd][offset : offset + size] = h.rd(buf, size)

        def fb_read(bs, offset, buf, size):
            hd = h.u32(bs)
            if hd:
                h.wr(buf, bytes(h.fbuf[hd][offset : offset + size]))

        def fb_set(bs, offset, val, size):
            hd = h.u32(bs)
            if hd:
                h.fbuf[hd][offset : offset + size] = bytes([val & 255]) * size

        def fb_init(bs):
            h.w32(bs, 0)
            h.w32(bs + 4, 0)

        def fb_resize(bs, new_size):
            hd, size = h.u32(bs), h.u32(bs + 4)
            if new_size == 0:
                if hd:
                    del h.fbuf[hd]
                    hd = 0
            elif size == 0:
                hd = h.fbuf_next
                h.fbuf_next += 1
                h.fbuf[hd] = bytearray(new_size)
            elif size != new_size:
                data = h.fbuf[hd]
                if new_size > size:
                    data.extend(bytes(new_size - size))
                else:
                    del data[new_size:]
            h.w32(bs, hd)
            h.w32(bs + 4, new_size)
            return 0

        def fb_reset(bs):
            fb_resize(bs, 0)
            fb_init(bs)

        def async_call(func, arg, millis):
            h.seq += 1
            due = time.monotonic() + (millis / 1000.0 if millis > 0 else 0.0)
            heapq.heappush(h.timers, (due, h.seq, func, arg))

        def wget3(url, request, user, password, post, post_len, arg, free, onload, onerror, onprogress):
            u, req = h.cstr(url), h.cstr(request)
            handle = h.wget_next
            h.wget_next += 1
            h.events.append(lambda: h._finish_wget(u, req, handle, arg, free, onload, onerror))
            return handle

        def fd_write(fd, iov, n, pnum):
            total = 0
            for i in range(n):
                p, ln = h.u32(iov + 8 * i), h.u32(iov + 8 * i + 4)
                h.stdio += h.rd(p, ln)
                total += ln
            h.w32(pnum, total)
            return 0

        def console_write(opaque, buf, ln):
            data = h.rd(buf, ln)
            h.console += data
            if b"\x1b[6n" in data:  # the shell asks where the cursor is: answer, as a terminal does
                h.pending_input += b"\x1b[1;1R"

        def console_get_size(pw, ph):
            h.w32(pw, 80)
            h.w32(ph, 25)

        def resize_heap(size):
            return 1 if (size & 0xFFFFFFFF) <= h.size else 0

        def tm_fill(t, tm, local):
            g = time.gmtime(t)
            vals = (g.tm_sec, g.tm_min, g.tm_hour, g.tm_mday, g.tm_mon - 1, g.tm_year - 1900, (g.tm_wday + 1) % 7, g.tm_yday - 1)
            h.wr(tm, struct.pack("<8i", *vals))
            if local:
                if not h.zone_ptr:
                    h.zone_ptr = h.put_cstr("UTC")
                h.w32(tm + 32, 0)
                h.w32(tm + 36, 0)
                h.w32(tm + 40, h.zone_ptr)

        def gmtime_js(t, tm):
            tm_fill(t, tm, False)

        def localtime_js(t, tm):
            tm_fill(t, tm, True)

        def tzset_js(timezone, daylight, std, dst):
            h.w32(timezone, 0)
            h.w32(daylight, 0)
            for p in (std, dst):
                h.wr(p, b"UTC\0")

        def clock_time_get(cid, prec, ptime):
            if cid == 0:
                ns = int(time.time() * 1e9)
            elif cid == 1:
                ns = int(time.monotonic() * 1e9)
            else:
                return 28
            h.wr(ptime, struct.pack("<Q", ns))
            return 0

        table = {
            "a": assert_fail, "b": exit_, "c": fb_write, "d": fb_read, "e": lambda: random.random(),
            "f": lambda flag: None, "g": fb_resize, "h": fb_init, "i": fb_reset, "j": wget3, "k": fd_write,
            "l": async_call, "m": lambda: time.time() * 1000.0, "n": lambda fn, buf, ln: None,
            "o": lambda bs, buf, ln: None, "p": console_write, "q": lambda *a: None, "r": resize_heap,
            "s": lambda fd, off, whence, new: 70, "t": lambda fd: 52, "u": gmtime_js, "v": localtime_js,
            "w": tzset_js, "x": clock_time_get, "y": abort_js, "z": fb_set, "A": console_get_size,
        }  # fmt: skip
        c.update(table)
        return c

    # --- downloads ---
    def _fetch(self, url):
        os.makedirs(CACHE, exist_ok=True)
        path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest())
        if os.path.exists(path):
            with open(path, "rb") as f:
                return 200, f.read()
        t = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jsl-host-experiment"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            return e.code, b""
        except Exception as e:  # noqa: BLE001
            print(f"[host] fetch failed {url}: {e}", file=sys.stderr)
            return 0, b""
        if status == 200:
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
        self.fetched.append((url, len(data), time.monotonic() - t))
        return status, data

    def _finish_wget(self, url, req, handle, arg, free, onload, onerror):
        if req != "GET":  # never write to a server
            status, data = 403, b""
        else:
            status, data = self._fetch(url)
        if self.verbose:
            print(f"[host] {req} {url} -> {status} {len(data)}", file=sys.stderr)
        if status == 200 or not url.startswith("http"):
            buf = self.malloc(max(len(data), 1))
            self.wr(buf, data)
            if onload:
                self.call(onload, handle, arg, buf, len(data))
            if free:
                self.free(buf)
        elif onerror:
            self.call(onerror, handle, arg, status, 0)

    # --- the loop ---
    def pump(self, until=None, seconds=60.0):
        """Run the events and the timers until `until()` is true or `seconds` pass; True if until() was true."""
        deadline = time.monotonic() + seconds
        timers, events = self.timers, self.events
        next_hb = time.monotonic() + 30
        while True:
            if self.heartbeat and time.monotonic() >= next_hb:
                next_hb += 30
                tail = clean_tail(self.console)
                print(f"[hb] {time.monotonic() - self.t_start:7.1f} s, timer callbacks {self.timer_calls}, console tail: {tail!r}", file=sys.stderr, flush=True)
            if until is not None and until():
                return True
            now = time.monotonic()
            if now > deadline:
                return False
            if self.pending_input and self.send:
                data, self.pending_input = bytes(self.pending_input), bytearray()
                for ch in data:
                    self.send(ch)
                continue
            if events:
                events.popleft()()
                continue
            if timers:
                due, _, func, arg = timers[0]
                if due > now:
                    time.sleep(min(due - now, 0.005))
                    continue
                heapq.heappop(timers)
                self.timer_calls += 1
                self.call(func, arg)
                continue
            time.sleep(0.001)

    def console_text(self):
        return self.console.decode("utf-8", "replace")
