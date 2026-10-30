"""Benchmark of the call path of the static core (layer 1): builds tests/c/bench_calls.c with -O2 over real wasm2c modules and prints calls per second.

    uv run python tools/bench_calls.py [--reps 5] [--seconds 1.0]

The modules are built as the product builds them (the fixture `build` of tests/test_instance_core.py): wat -> wasm -> wasm2c -> the repairs of `_natify` ->
descriptor and binding of wasmext -> `compile_c` with the wrappers of the runtime. Nothing is a test: the numbers go to docs/BENCHMARKS.md by hand."""

from __future__ import annotations

import argparse
import datetime
import platform
import shlex
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fusedwasi import get_include

from tests.c_build import compile_c, find_cc
from tests.conftest import _wabt_dir  # pyright: ignore[reportPrivateUsage]
from wasmext import parse
from wasmext._binding import generate_binding
from wasmext._descriptor import generate_descriptor
from wasmext._gen import module_prefix  # pyright: ignore[reportPrivateUsage]
from wasmext._model import build_model
from wasmext._natify import (  # pyright: ignore[reportPrivateUsage]
    _RUNTIME_WRAPPERS,
    _export_tags,
    _portable,
    _repair_imported_elements,
    _repair_tail_calls,
)
from wasmext._toolchain import find_toolchain  # pyright: ignore[reportPrivateUsage]

WASMEXT_C = ROOT / "src" / "wasmext" / "c"
BENCH_C = ROOT / "tests" / "c" / "bench_calls.c"
# the smallest modules that make the six cases (the shapes of LINK_MODULES, TABLE_MODULES and IMPORTS of tests/test_instance_core.py)
MODULES = {
    "ops": '(module (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add))',
    "lib": '(module (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add))',
    "app": """(module
  (import "libx" "add" (func $add (param i32 i32) (result i32)))
  (func (export "call_add") (param i32 i32) (result i32) local.get 0 local.get 1 call $add))""",
    "bench": """(module
  (import "env" "f" (func $f (param i32 i32) (result i32)))
  (func (export "run") (param i32 i32) (result i32) local.get 0 local.get 1 call $f))""",
    "owner": """(module
  (type $t (func (result i32)))
  (table $tab (export "tab") 4 8 funcref)
  (func $seven (export "seven") (result i32) i32.const 7)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t))
  (elem (i32.const 0) $seven))""",
    "user": """(module
  (import "own_u" "tab" (table $tab 2 funcref))
  (func $nine (export "nine") (result i32) i32.const 9)
  (elem (i32.const 1) $nine))""",
}
CASES = {
    1: "wasmext_instance_call, export add (generic adapter, store enter/leave)",
    2: "the same add through a link (typed shim, TRAP_LINKED)",
    3: "wasm calls an import answered by a uniform host function",
    4: "wasm calls an import answered by a typed host function",
    5: "call_indirect through a shared table to a function of another instance",
    6: "reference: w2c_ops_add inside ENTER_PLAIN/LEAVE_PLAIN (no store)",
}


def build(out: Path, cflags: list[str]) -> Path:
    wabt = _wabt_dir()
    if wabt is None or not (wabt / "bin").is_dir():
        sys.exit("no wabt-package: set WASMEXT_WABT to a directory with bin/ and wasm2c/")
    toolchain = find_toolchain()
    simde = [toolchain.include] if toolchain.include is not None and (toolchain.include / "simde").is_dir() else []
    sources = [BENCH_C]
    for module, text in MODULES.items():
        (out / f"{module}.wat").write_text(text, encoding="utf-8")
        wasm = out / f"{module}.wasm"
        subprocess.run([wabt / "bin" / "wat2wasm", out / f"{module}.wat", "-o", wasm], check=True)
        subprocess.run(
            [wabt / "bin" / "wasm2c", wasm, "-o", out / f"{module}_w2c.c", f"--module-name={module}"], check=True
        )
        raw = (out / f"{module}_w2c.c").read_bytes()
        repaired = _repair_imported_elements([raw])[0]
        (out / f"{module}_w2c.c").write_bytes(
            _export_tags(_repair_tail_calls(_portable(repaired)), module_prefix(module))
        )
        model = build_model(parse(wasm.read_bytes()), module, host="wasm32")
        (out / f"{module}_descriptor.c").write_text(generate_descriptor(model), encoding="utf-8")
        (out / f"{module}_binding.c").write_text(generate_binding(model), encoding="utf-8")
        sources += [out / f"{module}_binding.c", out / f"{module}_descriptor.c", out / f"{module}_w2c.c"]
    wrapped: list[Path] = []
    for key in ("impl", "mem", "exceptions"):
        path = out / f"rt_{key}.c"
        path.write_text(_RUNTIME_WRAPPERS[key], encoding="utf-8")
        wrapped.append(path)
    exe = out / "bench_calls"
    compile_c(
        [*sources, *wrapped],
        exe,
        include_dirs=[WASMEXT_C, Path(get_include()), toolchain.runtime, out, *simde],
        flags=cflags,
        strict=False,
        std=None,
        threads=True,
        math=True,
    )
    return exe


def run(exe: Path, case: int, n: int) -> float:
    done = subprocess.run([str(exe), str(case), str(n)], check=False, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"case {case} failed ({done.returncode}): {done.stderr.strip()}")
    return float(done.stdout.split()[3])


def calibrate(exe: Path, case: int, seconds: float) -> int:
    """The number of calls that takes about `seconds`: doubles from 10^4 until a run takes a tenth of it, then scales."""
    n = 10_000
    while True:
        rate = run(exe, case, n)
        if n / rate >= seconds / 10:
            return max(int(rate * seconds), 1000)
        n *= 4


def machine() -> list[str]:
    lscpu = subprocess.run(["lscpu"], capture_output=True, text=True, check=False).stdout
    cpu = [line.strip() for line in lscpu.splitlines() if line.startswith(("Model name", "CPU(s):"))]
    cc = find_cc() or "cc"
    version = subprocess.run([cc, "--version"], capture_output=True, text=True, check=False).stdout.splitlines()[:1]
    return [
        *cpu,
        f"compiler: {cc}: {version[0] if version else '?'}",
        f"python {platform.python_version()}, {platform.platform()}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--seconds", type=float, default=1.0, help="the length of one run")
    args = parser.parse_args()
    cflags = ["-O2", "-DNDEBUG"]
    with tempfile.TemporaryDirectory() as tmp:
        exe = build(Path(tmp), cflags)
        counts = {case: calibrate(exe, case, args.seconds) for case in CASES}
        rates: dict[int, list[float]] = {case: [] for case in CASES}
        for _ in range(args.reps):  # the cases alternate: a slow minute of the machine does not fall on one case
            for case in CASES:
                rates[case].append(run(exe, case, counts[case]))
    print(f"date: {datetime.date.today().isoformat()}")
    print(f"command: {shlex.join(['uv', 'run', 'python', 'tools/bench_calls.py', *sys.argv[1:]])}")
    print(
        f"flags: {' '.join(cflags)} (no sanitizers); {args.reps} runs of about {args.seconds:g} s per case, alternating"
    )
    for line in machine():
        print(line)
    print()
    print("| # | case | calls/s median | min..max | ns/call |")
    print("|---|---|---|---|---|")
    for case, text in CASES.items():
        r = rates[case]
        med = statistics.median(r)
        print(f"| {case} | {text} | {med / 1e6:.2f} M | {min(r) / 1e6:.2f}..{max(r) / 1e6:.2f} M | {1e9 / med:.1f} |")


if __name__ == "__main__":
    main()
