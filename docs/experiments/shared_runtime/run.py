"""The checks of the experiment: run in the folder with ft (master), ft2 and ex (slaves): python run.py"""

import subprocess
import sys
import threading
import time

import ex  # a slave, with memory growth, tables and exceptions
import ft  # the master: it has the runtime and publishes it
import ft2  # a slave: no runtime of its own


def check(label, fn):
    try:
        print(f"  {label:<58}{fn()}")
    except Exception as e:  # noqa: BLE001
        print(f"  {label:<58}FAILED: {type(e).__name__}: {e}")


def raises(module, call):
    try:
        call()
    except module.Trap as e:
        return f"Trap: {e}"
    return "NO TRAP"


print(
    "1. the slaves run: values, memory and tables, exceptions (surface of about 23 functions of the runtime, all forwarded)"
)
check("ft2.add(2, 3)", lambda: ft2.Instance().add(2, 3))
i = ex.Instance()
check("ex.grow(1)  (memory.grow: wasm_rt_grow_memory of the master)", lambda: i.grow(1))
check("ex.tgrow(), tgrowf()  (externref and funcref table.grow)", lambda: (i.tgrow(), i.tgrowf()))
check("ex.catcher(7)  (throw and catch: exception functions)", lambda: i.catcher(7))
check("ex.thrower(5)  (uncaught: reaches Python)", lambda: raises(ex, lambda: i.thrower(5))[:60])

print("\n2. traps by signals, in the master and in each slave (before: only the module imported last survived)")
for mod, name in ((ft, "ft  (master)"), (ft2, "ft2 (slave)"), (ex, "ex  (slave)")):
    inst = mod.Instance()
    if hasattr(inst, "oob"):
        check(f"{name}: out of bounds (guard pages, SIGSEGV)", lambda inst=inst, mod=mod: raises(mod, inst.oob))
    if hasattr(inst, "recurse"):
        check(
            f"{name}: stack overflow (alternate stack, SIGSEGV)",
            lambda inst=inst, mod=mod: raises(mod, lambda: inst.recurse(0)),
        )
    if hasattr(inst, "trap"):
        check(f"{name}: unreachable (no signal)", lambda inst=inst, mod=mod: raises(mod, inst.trap))

print("\n3. a worker thread that uses the slaves and the master (each thread set up once, by the master)")
out = []


def worker():
    r = []
    for mod in (ft2, ft, ex):
        inst = mod.Instance()
        if hasattr(inst, "recurse"):
            r.append(raises(mod, lambda inst=inst: inst.recurse(0))[:5])
        r.append(raises(mod, inst.oob)[:5])
    out.append(r)


ts = [threading.Thread(target=worker) for _ in range(6)]
for t in ts:
    t.start()
for t in ts:
    t.join()
print(
    f"  6 threads, each: overflow + OOB in ft2, ft, ex   {'all Trap' if all(x == 'Trap:' for r in out for x in r) and len(out) == 6 else out}"
)

print(
    "\n4. speed: calls a second from Python (the same code runs; only the runtime functions are forwarded, and they are not on the hot path)"
)
for mod, name in ((ft, "ft  (master)"), (ft2, "ft2 (slave) ")):
    inst = mod.Instance()
    best = {}
    for label, call, n in (
        ("add", lambda inst=inst: inst.add(1, 2), 1_000_000),
        ("work(1000)", lambda inst=inst: inst.work(1000), 200_000),
    ):
        rates = []
        for _ in range(3):
            t0 = time.perf_counter()
            for _ in range(n):
                call()
            rates.append(n / (time.perf_counter() - t0) / 1e6)
        best[label] = max(rates)
    print(f"  {name}: add {best['add']:.1f}M/s   work(1000) {best['work(1000)']:.2f}M/s")

print("\n5. a slave with no master (a fresh interpreter, only the slave imported)")
p = subprocess.run([sys.executable, "-c", "import ft2"], capture_output=True, text=True, check=False)
print("  " + (p.stderr.strip().splitlines()[-1] if p.stderr else "imported without a master?!"))
