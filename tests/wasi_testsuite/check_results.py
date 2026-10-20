"""Checks the JSON report of the test runner of the WASI test suite (`--json-output-location`): the suite ran *all* of its programs and none was lost.

The runner itself fails the job when a test fails; it does not notice a test that is gone (a program that was not built, a directory that moved with a new
commit of the suite). This does: the programs of WASI 0.1 in the suite are 72 (12 AssemblyScript, 14 C, 46 Rust), none is skipped, none failed, and a test that
was expected to fail and passes (`xpassed`) is an out-of-date expectation. Only the suites of `wasm32-wasip1` count: the runner lists the tests of WASI 0.3 too
(55 of them) and wasmext, which is WASI 0.1, skips them on purpose. `python check_results.py report.json [count]`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROGRAMS = 72  # the programs of wasm32-wasip1 in the commit of the suite that WASI_TESTSUITE_REF names


def check(report: dict[str, Any], expected: int = PROGRAMS) -> list[str]:
    """What is wrong with the report, as a list of sentences (empty: nothing)."""
    problems: list[str] = []
    suites: list[dict[str, Any]] = [s for s in report.get("results", []) if "[wasm32-wasip1]" in str(s.get("name", ""))]
    total = sum(len(suite.get("tests", [])) for suite in suites)
    if total != expected:
        problems.append(f"{total} tests ran, the suite has {expected} programs")
    for key, what in (
        ("failed", "failed"),
        ("skipped", "were skipped"),
        ("xpassed", "passed that were expected to fail"),
    ):
        count = sum(int(suite.get(key, 0)) for suite in suites)
        if count:
            problems.append(f"{count} tests {what}")
    counted = sum(
        int(suite.get(key, 0)) for suite in suites for key in ("passed", "failed", "skipped", "xfailed", "xpassed")
    )
    if counted != total:
        problems.append(f"the counts add up to {counted}, the tests listed are {total}")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    report = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    problems = check(report, int(argv[1]) if len(argv) > 1 else PROGRAMS)
    for problem in problems:
        print(f"WASI test suite: {problem}", file=sys.stderr)
    if not problems:
        print(f"WASI test suite: all {PROGRAMS} programs ran, none failed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
