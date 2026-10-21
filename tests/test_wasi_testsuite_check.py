"""The check of the report of the WASI test suite (tests/wasi_testsuite/check_results.py) notices a lost test as well as a failed one."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / "wasi_testsuite"))
_module: Any = importlib.import_module(
    "check_results"
)  # the script is beside the adapter of the suite, not in the package
check: Callable[..., list[str]] = _module.check
PROGRAMS: int = _module.PROGRAMS


def _suite(
    passed: int,
    failed: int = 0,
    skipped: int = 0,
    xfailed: int = 0,
    xpassed: int = 0,
    name: str = "WASI tests [wasm32-wasip1]",
) -> dict[str, Any]:
    """A suite as the runner reports it: an expected failure is in `passed` as well as in `xfailed`, and each test says how it ended."""
    outcomes = ["pass"] * passed + ["fail"] * failed + ["skip"] * skipped + ["xfail"] * xfailed + ["xpass"] * xpassed
    return {
        "name": name,
        "passed": passed + xfailed,
        "failed": failed,
        "skipped": skipped,
        "xfailed": xfailed,
        "xpassed": xpassed,
        "tests": [{"name": f"t{i}", "outcome": outcome} for i, outcome in enumerate(outcomes)],
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


def test_a_test_that_ended_in_some_other_way_is_noticed() -> None:
    broken = _suite(46)
    broken["tests"][0]["outcome"] = "error"
    assert check(_report(_suite(12), _suite(14), broken)) == ["tests ended as error"]


def test_the_tests_of_wasi_0_3_that_are_skipped_on_purpose_do_not_count() -> None:
    wasip3 = _suite(0, skipped=55, name="WASI Rust tests [wasm32-wasip3]")
    assert check(_report(_suite(12), _suite(14), _suite(46), wasip3)) == []
    assert check(_report(_suite(12), _suite(14), wasip3)) == [
        "26 tests ran, the suite has 72 programs"
    ]  # the Rust ones are gone
