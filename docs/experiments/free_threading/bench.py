"""Threads calling into a wasmext extension: throughput, a short call beside a long one, and traps in worker threads.

    python bench.py            # in a folder where `ft` (the extension made from ft.wat) can be imported
    ONLY=1|2|3 python bench.py # one part only

README.md has the three builds it was run on (GIL; free-threaded, with the GIL turned back on by the import; free-threaded, with Py_MOD_GIL_NOT_USED).
"""

import itertools
import os
import subprocess
import sys
import sysconfig
import threading
import time

import ft

ONLY = os.environ.get("ONLY", "")
print(
    f"python {sys.version.split()[0]}  free-threaded build: {bool(sysconfig.get_config_var('Py_GIL_DISABLED'))}  "
    f"GIL enabled after import: {sys._is_gil_enabled() if hasattr(sys, '_is_gil_enabled') else True}"
)


def run(threads, same_instance, call, calls):
    shared = ft.Instance()
    instances = [shared if same_instance else ft.Instance() for _ in range(threads)]
    barrier = threading.Barrier(threads + 1)

    def worker(inst):
        fn = getattr(inst, call[0])
        args = call[1:]
        barrier.wait()
        for _ in range(calls):
            fn(*args)

    pool = [threading.Thread(target=worker, args=(i,)) for i in instances]
    for t in pool:
        t.start()
    barrier.wait()
    t0 = time.perf_counter()
    for t in pool:
        t.join()
    return threads * calls / (time.perf_counter() - t0)  # calls per second, all threads together


def throughput():
    print(
        "\n1. throughput: calls per second, all threads together (higher is better); speed-up over 1 thread in brackets"
    )
    print(f"{'call':<20}{'threads':>8}{'own instance':>22}{'same instance':>22}")
    for call, calls in ((("add", 1, 2), 300000), (("work", 1000), 100000), (("work", 100000), 1500)):
        base = None
        for threads in (1, 2, 4):
            own = run(threads, False, call, calls)
            same = run(threads, True, call, calls) if threads > 1 else own
            base = base or own
            label = f"{call[0]}{call[1:]}"
            print(f"{label:<20}{threads:>8}{own:>14,.0f} ({own / base:4.1f}x){same:>14,.0f} ({same / base:4.1f}x)")


def latency():
    print(
        "\n2. a short call (add, then a 1 ms sleep, in a loop) in one thread while another thread is inside a long call (work(500000000), about 0.5 s)"
    )
    inst_long, inst_short = ft.Instance(), ft.Instance()
    stamps, marks = [], {}
    stop, started = threading.Event(), threading.Event()

    def long_call():
        marks["start"] = time.perf_counter()
        started.set()
        inst_long.work(500_000_000)
        marks["end"] = time.perf_counter()
        time.sleep(0.05)
        stop.set()

    def short_calls():
        started.wait()
        while not stop.is_set():
            inst_short.add(1, 2)
            stamps.append(time.perf_counter())
            time.sleep(0.001)

    t1, t2 = threading.Thread(target=long_call), threading.Thread(target=short_calls)
    t2.start()
    t1.start()
    t1.join()
    t2.join()
    during = [s for s in stamps if s < marks["end"]]
    gaps = [(b - a) * 1000 for a, b in itertools.pairwise(during)]
    print(
        f"   the long call took {(marks['end'] - marks['start']) * 1000:,.0f} ms; short calls completed while it ran: {len(during)}; "
        f"the first one after {((stamps[0] - marks['start']) * 1000):,.0f} ms"
        + (f"; longest pause between two of them {max(gaps):.1f} ms" if gaps else "")
    )


def traps():
    print("\n3. traps in worker threads (each in a subprocess: a crash is a result)")
    for what in ("trap", "oob", "recurse"):
        code = f"""
import threading, ft
result = []
def go():
    i = ft.Instance()
    try:
        getattr(i, {what!r})({"0" if what == "recurse" else ""})
    except ft.Trap as e:
        result.append('Trap: %s' % e)
    except Exception as e:
        result.append(type(e).__name__)
t = threading.Thread(target=go); t.start(); t.join()
print(result[0] if result else 'no result')
"""
        for where, source in (
            ("a thread other than the one that imported", code),
            ("the main thread", code.replace("t = threading.Thread(target=go); t.start(); t.join()", "go()")),
        ):
            p = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, timeout=30, check=False)
            out = p.stdout.strip() or (f"CRASH, exit code {p.returncode}" if p.returncode else "no output")
            print(f"   {what:<8} in {where + ':':<44}{out}")


if ONLY in ("", "1"):
    throughput()
if ONLY in ("", "2"):
    latency()


def depth_and_small_stack():
    print("\n4. how deep the recursion goes before the trap, and a thread with a small stack")
    inst = ft.Instance()
    try:
        inst.recurse_count(0)
    except ft.Trap as e:
        print(
            f"   depth reached before the trap (main thread): {int.from_bytes(bytes(inst.memory[:4]), 'little'):,}  ({e})"
        )
    for kb in (32, 64, 256, 1024):
        code = f"""
import threading, ft
threading.stack_size({kb} * 1024)
out = []
def go():
    i = ft.Instance()
    try:
        i.recurse_count(0)
    except ft.Trap as e:
        out.append(int.from_bytes(bytes(i.memory[:4]), 'little'))
t = threading.Thread(target=go); t.start(); t.join()
print(out[0] if out else 'no trap')
"""
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
        out = p.stdout.strip() or (f"CRASH, exit code {p.returncode}" if p.returncode else "no output")
        print(f"   thread with a {kb:>4} KiB stack: {out}")


def calls_inside():
    print("\n5. calls inside the module: fib(32), about 7 million calls (best of 5, ms)")
    inst = ft.Instance()
    best = min((lambda t0: (inst.fib(32), time.perf_counter() - t0)[1])(time.perf_counter()) for _ in range(5))
    print(f"   {best * 1000:.0f} ms, {7_049_155 / best / 1e6:.0f} million calls a second")


if ONLY in ("", "3"):
    traps()
if ONLY in ("", "4"):
    depth_and_small_stack()
if ONLY in ("", "5"):
    calls_inside()
