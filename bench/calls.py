"""Cost of one call of `add(i32, i32)`: the extension made from simple.wasm against wasmhost (if installed).

    python bench/calls.py [backend ...]     (default backends: wasmtime node bun)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "poc_out"))


def per_call(fn, n: int) -> float:
    fn(1, 2)
    best = float("inf")
    for _ in range(5):
        t0 = time.perf_counter()
        for i in range(n):
            fn(i, 2)
        best = min(best, (time.perf_counter() - t0) / n)
    return best


def main(backends: list[str]) -> None:
    import simple_ext

    print(f"{'native extension (wasm2c)':32} {per_call(simple_ext.add, 500_000) * 1e9:10.0f} ns/call")
    try:
        import wasmhost
    except ImportError:
        print("(wasmhost is not installed: no comparison)")
        return
    wasm = (ROOT / "wasm" / "simple.wasm").read_bytes()
    for name in backends:
        try:
            backend = wasmhost.get_backend(name)
            add = wasmhost.Instance(wasmhost.Module(wasm, backend=backend)).exports.add
            print(f"{'wasmhost / ' + name:32} {per_call(add, 5_000) * 1e9:10.0f} ns/call")
        except Exception as exc:  # noqa: BLE001 -- a backend that does not start here is just not measured
            print(f"{'wasmhost / ' + name:32}  n/a ({type(exc).__name__})")


if __name__ == "__main__":
    main(sys.argv[1:] or ["wasmtime", "node", "bun"])
