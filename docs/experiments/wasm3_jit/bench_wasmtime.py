import sys, time
from wasmtime import Engine, Store, Module, Instance
e = Engine(); s = Store(e); m = Module(e, open("kernel.wasm", "rb").read()); i = Instance(s, m, [])
k = i.exports(s)["kernel"]; n = int(sys.argv[1])
for _ in range(3):
    t = time.perf_counter(); r = k(s, n); d = time.perf_counter() - t
    print(f"result {r & 0xFFFFFFFF}  {d:.3f} s  {n / d / 1e6:.1f} M iterations/s")
