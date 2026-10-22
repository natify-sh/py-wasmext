"""CPython 3.15 for WASI 0.2 (unbundled module through wasmext) on the host of examples/wasi2_unbundled plus fshost.py (filesystem).

Usage: run_p2_fs.py MODULE_NAME MODULE.wasm PYROOT [-- python arguments]    PYROOT has lib/python3.15 (the standard library) and is the program's /py.
"""
import collections, importlib, io, sys
sys.path.insert(0, "."); sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from fshost import FsHost, Exit
from wasmext import parse

name, wasm, root = sys.argv[1:4]
args = ["python"] + (sys.argv[5:] if len(sys.argv) > 4 else ["-c", "print(1 + 1)"])
m = importlib.import_module(name)
out, err = io.BytesIO(), io.BytesIO()
host = FsHost(args, {"PYTHONHOME": "/py", "PYTHONDONTWRITEBYTECODE": "1"}, [(root, "/py")], stdout=out, stderr=err)
given, table, calls = host.imports(), host.table(), collections.Counter()
def rec(n, f):
    def w(*a):
        calls[n] += 1
        return f(*a)
    return w
def refuse(n):
    def w(*a):
        calls[n] += 1; raise NotImplementedError(n)
    return w
imports = {}
for i in parse(open(wasm, "rb").read()).imports:
    key = (i.module.split("@")[0], i.name); label = f"{key[0].split(':')[1]}.{i.name}"
    f = table.get(key) or given.get(i.module, {}).get(i.name)
    if i.name.startswith("[resource-drop]"): f = host.drop
    if f is not None and f.__name__ == "call" and False: pass
    imports.setdefault(i.module, {})[i.name] = rec(label, f) if f else refuse(label)
inst = m.Instance(imports); host.bind(inst)
try:
    how = f"returned {getattr(inst, 'wasi:cli/run@0.2.12#run')()}"
except Exit as e: how = f"exit({e.code})"
except NotImplementedError as e: how = f"STOPPED at {e}"
except Exception as e: how = f"{type(e).__name__}: {e}"
print(f"python {' '.join(args[1:])}: {how}\nstdout: {out.getvalue()[:400]!r}\nstderr: {err.getvalue()[:600]!r}\n{len(calls)} imports called: {sorted(calls)}")
