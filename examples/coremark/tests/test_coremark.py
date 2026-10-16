from __future__ import annotations

import time

import coremark


def test_the_benchmark_runs_and_scores() -> None:
    # The benchmark times itself for 10 s with the clock it is given: this one runs 600 times too fast.
    out = coremark.run(lambda: int(time.monotonic() * 600_000) & 0xFFFFFFFF)
    assert "Running CoreMark" in out
    result = [line for line in out.splitlines() if line.startswith("Result:")]
    assert result and float(result[0].split()[1]) > 0, out
