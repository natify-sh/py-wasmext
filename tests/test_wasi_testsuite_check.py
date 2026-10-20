"""The check of the report of the WASI test suite (tests/wasi_testsuite/check_results.py) notices a lost test as well as a failed one."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / "wasi_testsuite"))
from check_results import PROGRAMS, check  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]


def _suite(passed: int, failed: int = 0, skipped: int = 0, xfailed: int = 0, xpassed: int = 0) -> dict[str, Any]:
    names = passed + failed + skipped + xfailed + xpassed
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "xfailed": xfailed,
        "xpassed": xpassed,
        "tests": [{"name": f"t{i}"} for i in range(names)],
    }


def _report(*suites: dict[str, Any]) -> dict[str, Any]:
    return {"results": list(suites)}


def test_all_the_programs_passing_is_nothing_to_say() -> None:
    assert check(_report(_suite(12), _suite(14), _suite(46))) == []
    assert PROGRAMS == 72


def test_one_expected_failure_is_fine() -> None:
    assert (
        check(_report(_suite(12), _suite(14), _suite(45, xfailed=1))) == []
    )  # symlink_filestat on Windows, files through Python


def test_a_lost_test_is_noticed() -> None:
    problems = check(_report(_suite(12), _suite(14), _suite(45)))
    assert problems == ["71 tests ran, the suite has 72 programs"]
    assert check(_report()) == ["0 tests ran, the suite has 72 programs"]


def test_a_failed_a_skipped_and_a_stale_expectation_are_noticed() -> None:
    problems = check(_report(_suite(12), _suite(13, failed=1), _suite(44, skipped=1, xpassed=1)))
    assert "1 tests failed" in problems
    assert "1 tests were skipped" in problems
    assert "1 tests passed that were expected to fail" in problems


def test_counts_that_do_not_add_up_are_noticed() -> None:
    broken = _suite(46)
    broken["passed"] = 40
    assert any("add up" in p for p in check(_report(_suite(12), _suite(14), broken)))
