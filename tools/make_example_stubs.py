"""Make again the `.pyi` committed beside the `.wasm` of each example (`examples/*/src/*/*.pyi`).

    python tools/make_example_stubs.py          # write them
    python tools/make_example_stubs.py --check  # say which are stale

The host of a stub is the one it already says (`__host__`); a new stub has to be made by `wasmext natify` once.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from wasmext._gen import generate  # pyright: ignore[reportPrivateUsage]
from wasmext._wasm import parse  # pyright: ignore[reportPrivateUsage]

ROOT = Path(__file__).parent.parent


def stub_of(pyi: Path) -> str:
    """The stub the generator makes now for the module beside `pyi`, for the host the stub has."""
    host = re.search(r"__host__: Literal\['([^']+)'\]", pyi.read_text(encoding="utf-8"))
    assert host is not None, f"{pyi} says no host"
    module = parse(pyi.with_suffix(".wasm").read_bytes())
    return generate(module, f"{pyi.parent.name}.{pyi.stem}", host=host.group(1)).stub


def main(argv: list[str]) -> int:
    stale = [
        p for p in sorted((ROOT / "examples").glob("*/src/*/*.pyi")) if p.read_text(encoding="utf-8") != stub_of(p)
    ]
    for pyi in stale:
        print(("stale: " if "--check" in argv else "made: ") + str(pyi.relative_to(ROOT)))
        if "--check" not in argv:
            pyi.write_text(stub_of(pyi), encoding="utf-8")
    return 1 if stale and "--check" in argv else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
