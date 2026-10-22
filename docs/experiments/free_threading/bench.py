"""Threads calling into a wasmext extension: throughput, the latency of a short call beside a long one, and traps in worker threads.

    python bench.py          # in a folder where `ft` (the extension made from ft.wat) can be imported

Prints one block; `README.md` has the three builds it was run on (GIL, free-threaded with the GIL turned back on by the import, free-threaded with Py_MOD_GIL_NOT_USED).
"""
import statistics
import subprocess
import sys
import sysconfig
import threading
import time

import ft

print(f"python {sys.version.split()[0]}  free-threaded build: {bool(sysconfig.get_config_var('Py_GIL_DISABLED'))}  GIL enabled after import: "
      f"{sys._is_gil_enabled() if hasattr(sys, '_is_gil_enabled') else True}")


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
    dt = time.perf_counter() - t0
    return threads * calls / dt   # calls per second, all threads together


print("\n1. throughput: calls per second, all threads together (higher is better); speed-up over 1 thread in brackets")
print(f"{'call':<20}{'threads':>8}{'own instance':>22}{'same instance':>22}")
for call, calls in ((("add", 1, 2), 300000), (("work", 1000), 30000), (("work", 100000), 600)):
    base = None
    for threads in (1, 2, 4):
        own = run(threads, False, call, calls)
        same = run(threads, True, call, calls) if threads > 1 else own
        base = base or own
        print(f"{call[0] + str(call[1:]):<20}{threads:>8}{own:>14,.0f} ({own / base:4.1f}x){same:>14,.0f} ({same / base:4.1f}x)")

print("\n2. a short call (add, then a 1 ms sleep, in a loop) in one thread while another thread is inside a long call (work(300000000), about 0.4 s)")
inst_long, inst_short = ft.Instance(), ft.Instance()
stamps = []
stop = threading.Event()
started = threading.Event()


def long_call():
    started.set()
    t0 = time.perf_counter()
    inst_long.work(300_000_000)
    long_call.seconds = time.perf_counter() - t0
    time.sleep(0.05)
    stop.set()


def short_calls():
    started.wait()
    while not stop.is_set():
        inst_short.add(1, 2)
        stamps.append(time.perf_counter())
        time.sleep(0.001)


t1, t2 = threading.Thread(target=long_call), threading.Thread(target=short_calls)
t2.start(); t1.start(); t1.join(); t2.join()
gaps = [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]
print(f"   the long call took {long_call.seconds * 1000:,.0f} ms; {len(stamps)} short calls ran; the longest pause between two short calls: {max(gaps):,.1f} ms "
      f"(median {statistics.median(gaps):.2f} ms)")

print("\n3. traps in worker threads (each in a subprocess: a crash is a result)")
for what in ("trap", "oob", "recurse"):
    code = f"""
import threading, ft
result = []
def go():
    i = ft.Instance()
    try:
        getattr(i, {what!r})({'0' if what == 'recurse' else ''})
    except ft.Trap as e:
        result.append('Trap: %s' % e)
    except Exception as e:
        result.append(type(e).__name__)
t = threading.Thread(target=go); t.start(); t.join()
print(result[0] if result else 'no result')
"""
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    out = p.stdout.strip() or (f"CRASH, exit code {p.returncode}" if p.returncode else "no output")
    print(f"   {what:<8} in a thread other than the one that imported: {out}")
    code_main = code.replace("t = threading.Thread(target=go); t.start(); t.join()", "go()")
    p = subprocess.run([sys.executable, "-c", code_main], capture_output=True, text=True, timeout=30)
    out = p.stdout.strip() or (f"CRASH, exit code {p.returncode}" if p.returncode else "no output")
    print(f"   {what:<8} in the main thread:                           {out}")
