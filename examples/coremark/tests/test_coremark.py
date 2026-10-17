from __future__ import annotations

import time

import coremark
import pytest


def test_the_benchmark_runs_and_scores() -> None:
    # The benchmark times itself for 10 s with the clock it is given: this one runs 600 times too fast (perf_counter:
    # the monotonic clock of Windows ticks every 15 ms, too coarsely for a run that takes 20).
    seen: list[int] = []

    def clock() -> int:
        seen.append(int(time.perf_counter() * 600_000) & 0xFFFFFFFF)
        return seen[-1]

    t0 = time.perf_counter()
    out = coremark.run(clock)
    took = time.perf_counter() - t0
    score = [line for line in out.splitlines() if line.startswith("CoreMark 1.0 :")]
    # the CRCs of the run are checked by the benchmark itself: "validated" means the module computed the right thing
    assert "Correct operation validated" in out and score, f"{out!r} after {took:.3f} s, clock: {seen}"
    assert float(score[0].split()[3]) > 0


def test_python_dash_m_runs_it(capsys: pytest.CaptureFixture[str]) -> None:
    from coremark.__main__ import main

    assert main(["--scale", "600", "-v"]) == 0
    out = capsys.readouterr().out
    assert "CoreMark Size" in out and "extension :" in out and "runs (ms) :" in out
