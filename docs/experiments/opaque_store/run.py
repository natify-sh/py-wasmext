"""PROTOTYPE driver (outside the product): builds bench_proto.c in 3 variants over the modules of tools/bench_calls.py and compares cases 1 and 2.
    uv run python docs/experiments/opaque_store/run.py [--reps 5] [--seconds 1.0]
Reuses tools/bench_calls.py (imported, unchanged): its build() is called with compile_c wrapped to add the variant defines, the force-first include of
proto_ops.h in the generated binding files, and the shared library."""

from __future__ import annotations

import argparse
import shlex
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import bench_calls as bc  # noqa: E402

VARIANTS = {"A inline": "", "B table (store ops)": "PROTO_B", "C table (whole call)": "PROTO_C"}
CASES = (1, 2)


def build_variant(out: Path, define: str) -> Path:
    real = bc.compile_c
    bc.BENCH_C = HERE / "bench_proto.c"

    def wrapped(sources, exe, *, include_dirs, flags, **kw):  # pyright: ignore
        inc = [*include_dirs, HERE]
        for src in sources:  # proto_ops.h must come first in the generated bindings (they include wasmext_instance.h)
            if src.name.endswith("_binding.c"):
                src.write_text('#include "proto_ops.h"\n' + src.read_text(encoding="utf-8"), encoding="utf-8")
        extra = [f"-D{define}"] if define else []
        if define:
            lib = out / "libstore.so"
            cc = bc.find_cc() or "cc"
            subprocess.run([cc, "-O2", "-DNDEBUG", "-w", "-fPIC", "-shared", "-fvisibility=hidden", "-pthread",
                            *(f"-I{d}" for d in inc), str(HERE / "store_lib.c"), "-o", str(lib)], check=True)  # fmt: skip
            extra += [f"-Wl,-rpath,{out}", "-rdynamic"]
            sources = [*sources, lib]  # linked after the objects
        real([*sources], exe, include_dirs=inc, flags=[*flags, *extra], **kw)

    bc.compile_c = wrapped
    try:
        return bc.build(out, ["-O2", "-DNDEBUG"])
    finally:
        bc.compile_c = real


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--seconds", type=float, default=1.0)
    args = ap.parse_args()
    print("command:", shlex.join(["uv", "run", "python", "docs/experiments/opaque_store/run.py", *sys.argv[1:]]))
    for line in bc.machine():
        print(line)
    with tempfile.TemporaryDirectory() as tmp:
        exes = {}
        for name, define in VARIANTS.items():
            d = Path(tmp) / name[0]
            d.mkdir()
            exes[name] = build_variant(d, define)
        base = exes["A inline"]
        counts = {c: bc.calibrate(base, c, args.seconds) for c in CASES}  # the same n for every variant
        rates = {(n, c): [] for n in VARIANTS for c in CASES}
        for _ in range(args.reps):
            for c in CASES:
                for n in VARIANTS:
                    rates[n, c].append(bc.run(exes[n], c, counts[c]))
    print("\n| case | variant | calls/s median | min..max | ns/call | % over A |")
    print("|---|---|---|---|---|---|")
    for c in CASES:
        a = statistics.median(rates["A inline", c])
        for n in VARIANTS:
            r = rates[n, c]
            m = statistics.median(r)
            print(
                f"| {c} | {n} | {m / 1e6:.2f} M | {min(r) / 1e6:.2f}..{max(r) / 1e6:.2f} M | {1e9 / m:.1f} | {(a / m - 1) * 100:+.1f} |"
            )


if __name__ == "__main__":
    main()
