"""`python -m coremark`: run the benchmark.

python -m coremark               # ~20 s, the real clock
python -m coremark --scale 100   # the clock runs 100 times too fast: ~0.2 s, the score is not a score
python -m coremark -v            # also say which extension ran, with what compiler, and what the clock told
"""

from __future__ import annotations

import argparse
import platform
import sys
import sysconfig
import time

from . import _core, _monotonic_ms, run  # pyright: ignore[reportPrivateUsage]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m coremark", description="Run CoreMark (WebAssembly -> native extension)."
    )
    parser.add_argument("--scale", type=float, default=1.0, help="run the module's clock this many times too fast")
    parser.add_argument("-v", "--verbose", action="store_true", help="say what ran and what the clock told the module")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    samples: list[int] = []

    def clock() -> int:
        value = _monotonic_ms() if args.scale == 1.0 else int((time.perf_counter() - t0) * 1000 * args.scale)
        value &= 0xFFFFFFFF
        samples.append(value)
        return value

    output = run(clock)
    took = time.perf_counter() - t0
    print(output.rstrip("\n"))
    if args.scale == 1.0 and "Result: 0.000" in output:
        print(
            "\nCoreMark only reports a score for a timed run of at least 10 s; this one was shorter\n"
            "(the module extrapolates its length from a calibration run, which is noisy on a CPU that changes speed).\n"
            "Run it again, or use --scale to run the module's clock faster than real time.",
            file=sys.stderr,
        )
    if args.verbose:
        pairs = [(samples[i], samples[i + 1]) for i in range(0, len(samples) - 1, 2)]
        print(f"\nextension : {_core.__file__}")
        print(
            f"python    : {sys.version.split()[0]} ({platform.python_implementation()}, {platform.python_compiler()})"
        )
        print(f"machine   : {platform.machine()} {platform.system()} {platform.release()}")
        print(f"cc        : {sysconfig.get_config_var('CC')}; CFLAGS: {sysconfig.get_config_var('CFLAGS')}")
        print(f"took      : {took:.2f} s real; the clock was asked {len(samples)} times")
        print(f"runs (ms) : {[b - a for a, b in pairs]}   (start, stop) = {pairs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
