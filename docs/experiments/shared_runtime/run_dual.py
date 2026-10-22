"""Import the modules named on the command line, in that order, and make each of them trap by signals; then a worker thread does it for all.

python run_dual.py d1 d2        # d1 has the runtime and is the master, d2 attaches
python run_dual.py d2 d1        # the other way round
python run_dual.py d1 ft2 ex    # a dual master and two slaves with no runtime of their own
python run_dual.py d1 d3        # d3 was built for another runtime: it must not attach
"""

import importlib
import sys
import threading

mods = []
for name in sys.argv[1:]:
    try:
        mods.append(importlib.import_module(name))
        print(f"  import {name}: ok")
    except ImportError as e:
        print(f"  import {name}: ImportError: {e}")


def trap(mod, fn, *args):
    try:
        getattr(mod.Instance(), fn)(*args)
    except mod.Trap:
        return "Trap"
    return "NO TRAP"


for mod in mods:
    r = [trap(mod, "oob"), trap(mod, "recurse", 0)] if hasattr(mod.Instance(), "recurse") else [trap(mod, "oob")]
    print(f"  {mod.__name__}: oob, overflow -> {r}")
res = []
t = threading.Thread(
    target=lambda: (
        res.extend(trap(m, "oob") for m in mods)
        or res.extend(trap(m, "recurse", 0) for m in mods if hasattr(m.Instance(), "recurse"))
    )
)
t.start()
t.join()
print(f"  worker thread, every module: {res}")
