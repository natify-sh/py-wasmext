"""Build every program of the test suite, at the same time, before the test runner runs them (the runner kills a program that is
slower than its timeout, and the first run of a program is a build).

    python prebuild.py /path/to/wasi-testsuite/tests
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RUN = Path(__file__).parent / "run_wasmext.py"


EXE = (
    os.environ.get("WASMEXT_TESTSUITE_EXE") == "1"
)  # native executables (exe_build.py) instead of extensions of Python
EXE_BUILD = Path(__file__).parent / "exe_build.py"


def build(program: Path) -> tuple[Path, int, float]:
    started = time.monotonic()
    if EXE:
        made = subprocess.run(
            [sys.executable, str(EXE_BUILD), "--build", str(program)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if made.returncode:
            print(f"{program}: {made.stderr[-600:]}", file=sys.stderr)
        return program, made.returncode, time.monotonic() - started
    # the module is imported by a process of its own (as the runner does), which builds it; no arguments: it fails to run
    # `_start` at once with a directory the program wants, and that is not what is looked at here
    code = subprocess.run(
        [sys.executable, str(RUN), "--build-only", str(program)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if code.returncode:
        print(f"{program}: {code.stderr[-600:]}", file=sys.stderr)
    return program, code.returncode, time.monotonic() - started


def main(tests: Path) -> int:
    programs = sorted({p for p in tests.rglob("*.wasm") if p.parent.name == "wasm32-wasip1"})
    jobs = max(1, (os.cpu_count() or 2) // 2)
    print(f"building {len(programs)} programs, {jobs} at a time", flush=True)
    failed = 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for program, code, seconds in pool.map(build, programs):
            print(f"{'ok  ' if code == 0 else 'FAIL'} {seconds:5.1f} s  {program.name}", flush=True)
            failed += code != 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
