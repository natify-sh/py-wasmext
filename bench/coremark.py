"""CoreMark (wasm/coremark.wasm): the extension made from it against wasmhost (if installed). Each run takes ~20 s.

    python bench/coremark.py [backend ...]     (default backends: wasmtime node bun)

The score is printed by the module itself, from its own clock (`wiring.millis`).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))


def main(backends: list[str]) -> None:
    import coremark_ext

    t0 = time.perf_counter()
    coremark_ext.setup()
    dt = time.perf_counter() - t0
    print(f"{'native extension (wasm2c)':26} {dt:5.1f}s  {coremark_ext.output().decode().strip()!r}")
    try:
        import wasmhost
    except ImportError:
        print("(wasmhost is not installed: no comparison)")
        return
    wasm = (ROOT / "wasm" / "coremark.wasm").read_bytes()
    for name in backends:
        out: list[bytes] = []
        try:
            backend = wasmhost.get_backend(name)
            box: dict[str, object] = {}
            imports = {
                "wiring": {
                    "millis": lambda: int(time.monotonic() * 1000) & 0xFFFFFFFF,
                    "delay": lambda ms: None,
                    "stopWdt": lambda: None,
                    "print": lambda off, n: out.append(box["inst"].exports.memory.read(off, n)),  # type: ignore[attr-defined]
                }
            }
            inst = wasmhost.Instance(wasmhost.Module(wasm, backend=backend), imports)
            box["inst"] = inst
            t0 = time.perf_counter()
            inst.exports.setup()
            dt = time.perf_counter() - t0
            print(f"{'wasmhost / ' + name:26} {dt:5.1f}s  {b''.join(out).decode().strip()!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"{'wasmhost / ' + name:26} n/a ({type(exc).__name__})")


if __name__ == "__main__":
    main(sys.argv[1:] or ["wasmtime", "node", "bun"])
