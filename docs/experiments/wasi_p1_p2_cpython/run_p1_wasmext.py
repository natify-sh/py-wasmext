import os, sys, importlib
sys.path.insert(0, ".")
m = importlib.import_module("cp_p1")
HOME = "/home/user/natify-sh/py-wasmhost/examples/cpython"   # lib/python315.zip is here
def py(*args):
    out = []
    inst = m.Instance(wasi={"args": ["/py/python.wasm", *args], "env": {"PYTHONHOME": "/py"}, "preopens": {"/py": HOME}, "stdout": out.append, "stderr": out.append})
    try:
        inst._start(); code = 0
    except m.WasiExit as e:
        code = e.code
    print(f"  python {' '.join(args)[:60]!r} -> exit {code}: {b''.join(out).decode(errors='replace').strip()[:150]!r}")
py("--version")
py("-c", "import sys, platform; print(sys.version.split()[0], sys.platform, platform.machine())")
py("-c", "import json, re, hashlib, zlib, decimal; print(json.dumps({'sum': sum(range(10))}), hashlib.sha256(b'x').hexdigest()[:8], len(zlib.compress(b'a'*1000)))")
py("-c", "import socket; s = socket.socket(); print('socket ok')")
