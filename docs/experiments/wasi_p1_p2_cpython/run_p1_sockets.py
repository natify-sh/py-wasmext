import sys; sys.path.insert(0, ".")
import cp_p1 as m
out = []
inst = m.Instance(wasi={"args": ["/py/python.wasm", "-c", "import socket\ntry:\n    socket.socket()\nexcept OSError as e:\n    print(type(e).__name__, e)\ntry:\n    print(socket.getaddrinfo('localhost', 80))\nexcept OSError as e:\n    print('getaddrinfo:', type(e).__name__, e)"],
                        "env": {"PYTHONHOME": "/py"}, "preopens": {"/py": "/home/user/natify-sh/py-wasmhost/examples/cpython"}, "stdout": out.append, "stderr": out.append})
try: inst._start()
except m.WasiExit: pass
print(b"".join(out).decode().split("\n", 1)[-1].strip())
