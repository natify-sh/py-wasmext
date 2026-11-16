#!/usr/bin/env python3
"""Boot the JSLinux x86_64 VM (Alpine) on one engine and measure it.

    python run_vm.py --engine wasmext|wasmtime [--stage boot|info|coremark] [--coremark FILE]

The same module (x86_64emu_big.wasm: the JSLinux module with the initial memory raised to 384 MiB, so that the VM's 256 MiB of RAM
fits without growing it) and the same host (jsl_host.py) on every engine; the engine only runs the module.
"""

from __future__ import annotations

import argparse
import re
import sys
import time

sys.path.insert(0, "/tmp/claude-0/jsl_exp")
from jsl_host import Exited, Host  # noqa: E402

CFG = "https://bellard.org/jslinux/alpine-x86_64.cfg"
BUILD = "/tmp/claude-0/jsl_build/src/build/lib.linux-x86_64-cpython-311"
WASM = "/tmp/claude-0/jsl_x64/x86_64emu_big.wasm"
WASM_CI = "/tmp/claude-0/jsl_x64/x86_64emu_big_ci.wasm"
RAM_MB = 256


def wasmext_engine(host):
    sys.path.insert(0, BUILD)
    import x86_64emu as X  # type: ignore

    store = X.Store()
    inst = X.Instance(store, imports={"a": host.imports()})
    table = inst["G"]
    host.bind(inst.B, lambda idx, *a: table.get(idx)(*a), inst.N, inst.M)
    return lambda name: getattr(inst, name)


def wasmtime_engine(host):
    import ctypes

    from wasmtime import Engine, Linker, Module, Store

    engine = Engine()
    store = Store(engine)
    module = Module(engine, open(WASM, "rb").read())
    linker = Linker(engine)
    fns = host.imports()
    for imp in module.imports:
        linker.define_func("a", imp.name, imp.type, fns[imp.name])
    inst = linker.instantiate(store, module)
    ex = inst.exports(store)
    mem = ex["B"]
    ptr = mem.data_ptr(store)
    n = mem.data_len(store)
    view = memoryview((ctypes.c_ubyte * n).from_address(ctypes.cast(ptr, ctypes.c_void_p).value)).cast("B")
    table = ex["G"]

    def call(idx, *a):
        return table.get(store, idx)(store, *a)

    host.bind(view, call, lambda n: ex["N"](store, n), lambda p: ex["M"](store, p))
    return lambda name: (lambda *a: ex[name](store, *a))


def jsc_engine(host):
    """wasmhost: `jsc` (system JavaScriptCore through its C API; JSC_useJIT=false for no JIT) or `wasm3` (set WASMHOST_BACKEND).

    wasm3 has no table access, so for it the module has two exported trampolines (ci1, ci4: call_indirect of the table) and the
    host calls the callbacks through them."""
    import os

    import wasmhost

    wasm3 = os.environ.get("WASMHOST_BACKEND") == "wasm3"
    module = wasmhost.Module(open(WASM_CI if wasm3 else WASM, "rb").read())
    inst = wasmhost.Instance(module, {"a": host.imports()})
    ex = inst.exports
    mem = ex.B
    if wasm3:
        # the callbacks of the host: a timer takes (arg); a download's onload and onerror take four values
        def call(idx, *a):
            return ex.ci1(idx, *a) if len(a) == 1 else ex.ci4(idx, *a)
    else:
        table = ex.G

        def call(idx, *a):
            return table.get(idx)(*a)

    host.bind(
        None,
        call,
        ex.N,
        ex.M,
        rd=lambda a, n: bytes(mem.read(a, n)),
        wr=lambda a, d: mem.write(a, d),
        size=len(mem),
    )
    return lambda name: getattr(ex, name)


ENGINES = {"wasmext": wasmext_engine, "wasmtime": wasmtime_engine, "jsc": jsc_engine, "wasm3": jsc_engine}  # jsc, wasm3: wasmhost; WASMHOST_BACKEND picks the engine


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def clean(raw):
    return ANSI.sub("", raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw).replace("\r", "")


T0 = time.perf_counter()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=list(ENGINES), required=True)
    ap.add_argument("--stage", choices=["boot", "info", "coremark"], default="info")
    ap.add_argument("--coremark", default="/tmp/claude-0/jsl_exp/coremark_static")
    ap.add_argument("--boot-timeout", type=float, default=240)
    ap.add_argument("--cmd-timeout", type=float, default=120)
    ap.add_argument("--iterations", type=int, default=6000, help="CoreMark iterations (explicit: no calibration)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--show-console", action="store_true")
    args = ap.parse_args()

    host = Host(verbose=args.verbose)
    host.heartbeat = True
    t = time.perf_counter()
    export = ENGINES[args.engine](host)
    print(f"[{args.engine}] instantiated in {time.perf_counter() - t:.2f} s", flush=True)
    export("C")()  # the constructors

    url = host.put_cstr(CFG)
    cmd = host.put_cstr("")
    t_boot = time.perf_counter()
    export("L")(url, RAM_MB, cmd, 0, 0, 0, 0)  # vm_start(url, ram MB, cmdline, pwd, width, height, net)

    host.send = export("D")
    prompt = re.compile(r"localhost:~# $")
    t_prompt = []

    def at_prompt():
        if prompt.search(clean(host.console)):
            t_prompt.append(time.perf_counter())
            return True
        return False

    try:
        ok = host.pump(until=at_prompt, seconds=args.boot_timeout)
    except Exited as e:
        print("exit", e)
        ok = False
    boot_s = (t_prompt[0] if t_prompt else time.perf_counter()) - t_boot
    print(f"[{args.engine}] prompt: {ok}, boot {boot_s:.1f} s, timer callbacks {host.timer_calls}, downloads {len(host.fetched)}", flush=True)
    if args.show_console or not ok:
        print("---- console ----")
        print(host.console_text()[-3000:])
        print("---- stdio ----")
        print(host.stdio.decode("utf-8", "replace")[-1500:])
    if not ok or args.stage == "boot":
        return 0 if ok else 1

    def run(command, timeout=None, echo=True):
        """Type a command, wait for its end, return the output."""
        marker = "__DO" + '""' + "NE__"
        start = len(host.console)
        text = f"{command}; echo {marker}\r"
        send = export("D")
        for ch in text:
            send(ord(ch))
        done = re.compile(r"__DONE__")  # the echo of the typed line has __DO""NE__, which does not match
        host.pump(until=lambda: bool(done.search(clean(host.console[start:]))), seconds=timeout or args.cmd_timeout)
        out = clean(host.console[start:])
        out = out.split("__DONE__")[0] if "__DONE__" in out else out
        # drop the echoed command line
        lines = out.replace("\r", "").split("\n")
        body = "\n".join(lines[1:]).strip()
        if echo:
            print(f"[{time.perf_counter() - T0:7.1f} s] $ {command}\n{body}", flush=True)
        return body

    run("uname -a")
    run("grep -m1 'model name' /proc/cpuinfo")
    run("grep -m1 flags /proc/cpuinfo | tr ' ' '\\n' | grep -E 'avx|apx|sse4|bmi' | tr '\\n' ' '")
    run("free -m | head -2")
    if args.stage == "info":
        return 0

    # the guest's clock against the host's: a sleep of 3 s in the guest, timed here
    t = time.perf_counter()
    gl = run("t1=$(date +%s); sleep 3; t2=$(date +%s); echo guest-seconds $((t2-t1))", echo=False)
    print(f"[{args.engine}] clock check: host {time.perf_counter() - t:.1f} s for `sleep 3` ({gl.strip()})", flush=True)

    # CoreMark: a static x86_64 binary, taken into the guest by the module's fs_import_file
    data = open(args.coremark, "rb").read()
    name = host.put_cstr("coremark")
    buf = host.malloc(len(data))
    host.wr(buf, data)
    t = time.perf_counter()
    export("O")(name, buf, len(data))  # the buffer is freed by the function
    host.pump(seconds=2)
    print(f"[{args.engine}] import of {len(data)} bytes: {time.perf_counter() - t:.1f} s", flush=True)
    run("chmod +x ~/coremark", echo=False)
    n = args.iterations
    for i in range(args.repeat):
        t_cm = time.perf_counter()
        out = run(f"~/coremark 0x0 0x0 0x66 {n} 7 1 2000 2>&1", timeout=3600, echo=False)
        wall = time.perf_counter() - t_cm
        ok = "Correct operation validated" in out
        gt = re.search(r"Total time \(secs\):\s*([0-9.]+)", out)
        gi = re.search(r"Iterations/Sec\s*:\s*([0-9.]+)", out)
        print(
            f"[{args.engine}] run {i + 1}: {n} iterations, host wall {wall:.1f} s -> {n / wall:.1f} it/s by the host clock;"
            f" guest clock says {gt.group(1) if gt else '?'} s -> {gi.group(1) if gi else '?'} it/s; validated: {ok}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
