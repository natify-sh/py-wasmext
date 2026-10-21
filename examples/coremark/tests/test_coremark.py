from __future__ import annotations

import coremark
import pytest


def test_the_benchmark_runs_and_scores() -> None:
    # The benchmark decides how long to run from the clock it is given, and wants a last run of 10 s or more to call the
    # result valid. This clock does not depend on the machine (a real one, however fast, has a resolution that some
    # platforms, Pyodide among them, make too coarse): the first timed run lasts 1.5 s, the next one 15 s, whatever
    # they really took, so the benchmark does very little work and the report is the same everywhere.
    calls: list[int] = []
    now = 1_000_000

    def clock() -> int:
        nonlocal now
        calls.append(now)
        if len(calls) % 2 == 0:  # the end of a run
            now += 1500 if len(calls) <= 2 else 15000
        return now

    out = coremark.run(clock)
    score = [line for line in out.splitlines() if line.startswith("CoreMark 1.0 :")]
    # the CRCs of the run are checked by the benchmark itself: "validated" means the module computed the right thing
    assert "Correct operation validated" in out and score, f"{out!r}, clock: {calls}"
    assert float(score[0].split()[3]) > 0
    # and these are the values CoreMark gives for this run, whatever the machine
    for line in ("[0]crclist       : 0xe714", "[0]crcmatrix     : 0x1fd7", "[0]crcstate      : 0x8e3a"):
        assert line in out


def test_python_dash_m_runs_it(capsys: pytest.CaptureFixture[str]) -> None:
    from coremark.__main__ import main

    # 0 if the run was long enough to be valid, 1 if not (a coarse clock may make it too short): the report is there either way
    assert main(["--scale", "600", "-v"]) in (0, 1)
    out = capsys.readouterr().out
    assert "CoreMark Size" in out and "extension :" in out and "runs (ms) :" in out
