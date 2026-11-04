"""Step 8b-3a of docs/specs/S0008-shared-store.md: the stack limit and the chain handler of signals in the layer-1 core. One copy of the runtime, a host in plain C (tests/c/test_signals.c): no
Python front end, no layer 3. The C is built as the product builds it (fixture `build`, with the macros of the mode of the stack check: `core_build_macros(mode)`).

Modes: `limit` (the product's default), `guard` (the guard page, the chain handler on an alternate stack) and `stock` (the runtime installs its own handler: one copy, so only the single-copy cases;
a fault outside a call is not chained there, because the handler of the runtime replaces the test's). Each case runs in a child process, so that a signal that nothing turned into a trap is a
verdict ("not trapped") and not the end of the test run."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from .c_build import supports_flag
from .conftest import SANITIZED
from .test_instance_core import build  # noqa: F401  # pyright: ignore[reportUnusedImport]  (a fixture is found by name in the module that imports it)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the chain handler is POSIX; Windows has its own mechanism (the header is empty there)",
)

# `ld` loads a byte (past the 64 KiB of the memory it reaches a guard page), `deep` recurses with no end (two calls of itself, or the C compiler may turn it into a loop)
SIG = """(module
  (memory (export "mem") 1 1)
  (func (export "ld") (param i32) (result i32) local.get 0 i32.load8_u)
  (func $deep (export "deep") (param i32) (result i32) local.get 0 call $deep local.get 0 call $deep i32.add)
  (func (export "ok") (param i32) (result i32) i32.const 7))"""

CASES = ["recursion_thread", "recursion_main", "oob", "after", "threads"]


def _run_case(exe: Path, case: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(exe), case], capture_output=True, text=True, timeout=120, check=False, env={**os.environ, **(env or {})}
    )


_ALTSTACK = (
    "under a sanitizer for the whole run the `guard` and `stock` modes cannot run a signal: the runtime of wasm2c installs an alternate stack of 8 KiB (SIGSTKSZ) in each thread, "
    "and the sanitizer's `__asan_handle_no_return`, called before the trap in the handler, needs more than that and overflows it (a second SIGSEGV inside the handler; seen in gdb). "
    "Not a defect of the core: the modes are for builds without a sanitizer, and `limit` (no alternate stack) passes"
)


def _no_altstack_under_sanitizer(mode: str) -> None:
    if SANITIZED and mode != "limit":
        pytest.skip(_ALTSTACK)


def _verdict(case: str, result: subprocess.CompletedProcess[str]) -> str:
    """What the run says: ok, a check that failed, or the signal that ended the process (a fault that was not turned into a trap)."""
    if result.returncode < 0:
        died = signal.Signals(-result.returncode)
        what = (
            "not trapped: the fault ended the process" if died.name in ("SIGSEGV", "SIGBUS") else "the process aborted"
        )
        return f"{case}: {what} ({died.name}); stderr: {result.stderr.strip()[-300:]}"
    return f"{case}: exit {result.returncode}; stderr: {result.stderr.strip()[-600:]}"


@pytest.mark.parametrize("mode", ["limit", "guard", "stock"])
@pytest.mark.parametrize("case", CASES)
def test_a_signal_in_a_call_is_a_trap(build: Callable[..., Path], mode: str, case: str) -> None:  # noqa: F811
    """EXHAUSTION from a recursion and OOB from a guard-page access, on a fresh thread and on the main thread, and the next call works (`tls.rt` and `tls.top` clean)."""
    _no_altstack_under_sanitizer(mode)
    result = _run_case(build(SIG, "sig", "test_signals.c", mode=mode), case)
    assert result.returncode == 0 and result.stdout.strip() == "ok", _verdict(case, result)


@pytest.mark.parametrize("mode", ["limit", "guard"])
@pytest.mark.parametrize("case", ["chain", "chain_bus"])
def test_a_fault_outside_a_call_reaches_the_handler_that_was_before(
    build: Callable[..., Path],  # noqa: F811
    mode: str,
    case: str,
) -> None:
    """A deliberate SIGSEGV (and a SIGBUS) in host code (no call in flight) goes to the handler that the test installed before the core's, a different one for each signal: it jumps back, and the core's link still works for the calls around it."""
    _no_altstack_under_sanitizer(mode)
    exe = build(SIG, "sig", "test_signals.c", mode=mode)
    result = _run_case(exe, case)
    assert result.returncode == 0 and result.stdout.strip() == "ok", _verdict(case, result)
    assert "the handler of the test ran" in result.stderr


@pytest.mark.parametrize("mode", ["limit", "guard"])
@pytest.mark.parametrize(("case", "status"), [("chain_exit", 42), ("chain_bus_exit", 43)])
def test_the_process_behaves_as_the_handler_before_says(
    build: Callable[..., Path],  # noqa: F811
    mode: str,
    case: str,
    status: int,
) -> None:
    """The handler before ends the process with its own status (42 for SIGSEGV, 43 for SIGBUS): the fault is not a trap, and it is not swallowed."""
    _no_altstack_under_sanitizer(mode)
    exe = build(SIG, "sig", "test_signals.c", mode=mode)
    result = _run_case(exe, case, {"CHAIN_EXIT": "1"})
    assert result.returncode == status and "the handler of the test ran" in result.stderr, _verdict(case, result)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the size of the main stack is read from glibc here")
def test_a_main_stack_of_unlimited_size_is_capped(build: Callable[..., Path]) -> None:  # noqa: F811
    """Under `ulimit -s unlimited` glibc reports the main thread's stack as the gap to the previous mapping (tens of TiB); the limit of the `limit` mode is measured over at most 64 MiB, so the recursion on the main thread
    is EXHAUSTION and not a run until memory ends (`guard` and `stock` are not covered by the cap: they see the guard page). Without the cap the child stacks memory until the timeout (4 s, short on purpose: a recursion over an unlimited stack grows memory at the speed of the machine), reported as "not trapped within". An RLIMIT_AS would stop it sooner but also forbids the reservation of the 4 GiB guard region of a module."""
    if sys.platform == "win32":
        pytest.skip("POSIX only")
    import resource

    _, hard = resource.getrlimit(resource.RLIMIT_STACK)
    if hard != resource.RLIM_INFINITY:
        pytest.skip("the hard limit of the stack is not unlimited here")
    exe = build(SIG, "sig", "test_signals.c")

    def unlimited() -> None:
        if sys.platform == "win32":
            return
        resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))

    try:
        result = subprocess.run(
            [str(exe), "recursion_main"], capture_output=True, text=True, timeout=4, check=False, preexec_fn=unlimited
        )
    except subprocess.TimeoutExpired:
        pytest.fail("recursion_main: not trapped within 4 s (the stack of unlimited size is not capped)")
    assert result.returncode == 0 and result.stdout.strip() == "ok", _verdict("recursion_main", result)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
@pytest.mark.parametrize("sanitizer", ["address,undefined", "thread"])
@pytest.mark.parametrize("case", ["oob", "after", "threads", "recursion_thread", "recursion_main", "threads_oob"])
def test_signals_under_sanitizers(build: Callable[..., Path], sanitizer: str, case: str) -> None:  # noqa: F811
    """The same in the default mode where the sanitizers can run it: a sanitizer installs handlers of SIGSEGV of its own, and the chain of the core goes on top of them. ThreadSanitizer does not run the
    recursions (found, not fixed: a stack that runs out ends in a fault inside its own handler, `nested bug in the same thread`, in 5 runs of 6 on the main thread; the access past a guard page runs
    1000 times in a row; the reason is probably the shadow call stack of TSan overflowing on a deep recursion, not verified), so there the cases without recursion run."""
    if SANITIZED or not supports_flag(f"-fsanitize={sanitizer}"):
        pytest.skip("no such sanitizer, or one is on for the whole run")
    recursive = case in ("after", "threads", "recursion_thread", "recursion_main")
    if sanitizer == "thread" and recursive:
        pytest.skip(
            "ThreadSanitizer faults in its own handler when a stack runs out (it cannot run a recursion to EXHAUSTION)"
        )
    flags = [f"-fsanitize={sanitizer}", "-g", *(["-fno-sanitize-recover=all"] if sanitizer != "thread" else [])]
    result = _run_case(build(SIG, "sig", "test_signals.c", flags=flags), case)
    assert result.returncode == 0 and result.stdout.strip() == "ok", _verdict(case, result)
