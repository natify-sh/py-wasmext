"""Build src/productsdemo/engine.wasm and hello.wasm from the .wat files with `wat2wasm` (from the wabt-package).

python build_wasm.py
"""

from __future__ import annotations

from pathlib import Path

import wabt_package

HERE = Path(__file__).resolve().parent


def main() -> None:
    for wat in sorted((HERE / "wat").glob("*.wat")):
        out = HERE / "src" / "productsdemo" / f"{wat.stem}.wasm"
        wabt_package.run("wat2wasm", str(wat), "-o", str(out))
        print(f"{wat.name} -> {out.relative_to(HERE)} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
