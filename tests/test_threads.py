"""The extension in threads other than the one that imported it: the runtime of wasm2c has to be set up for each thread that runs WebAssembly code.

Without the alternate stack for the handler of the signals, the stack of a thread running out was a SIGSEGV that killed the process, and not a `Trap`.
Each scenario runs in a subprocess, so that a crash is a failed test and not the end of the run.
"""

import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

# two calls of itself, or the C compiler turns the recursion into a loop that never ends
_WAT = """(module
  (func $rec (export "rec") (result i32) call $rec call $rec i32.add)
  (func (export "five") (result i32) i32.const 5))
"""

_WORKERS = """
import sys, threading
sys.path.insert(0, {path!r})
import {mod}

def worker(out):
    inst = {mod}.Instance({mod}.Store())
    try:
        inst.rec()
    except {mod}.Trap as exc:
        out.append("trap")
    out.append(inst.five())

# many threads in a row: each gets the stack at its first call and gives it back when it ends
results = []
for _ in range(40):
    out = []
    t = threading.Thread(target=worker, args=(out,))
    t.start()
    t.join()
    results.append(out)
print("workers:", all(r == ["trap", 5] for r in results))

# several at once
outs = [[] for _ in range(6)]
threads = [threading.Thread(target=worker, args=(o,)) for o in outs]
for t in threads:
    t.start()
for t in threads:
    t.join()
print("together:", all(o == ["trap", 5] for o in outs))

# the main thread, which imported the module
inst = {mod}.Instance({mod}.Store())
try:
    inst.rec()
except {mod}.Trap:
    print("main: trap")
"""

_IMPORT_IN_A_THREAD = """
import sys, threading
sys.path.insert(0, {path!r})
out = []

def go():
    import {mod}
    inst = {mod}.Instance({mod}.Store())
    try:
        inst.rec()
    except {mod}.Trap:
        out.append("trap")
    out.append(inst.five())

t = threading.Thread(target=go)
t.start()
t.join()
print("importing thread:", out == ["trap", 5])
"""


def _run(script: str, what: str) -> str:
    ran = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=180)
    if ran.returncode != 0 and platform.system() == "Darwin":
        # see _run_exhaustion in test_tables.py: on macOS a trap by a signal from the alternate stack is not settled
        pytest.xfail(f"{what}: the process ended with {ran.returncode} on macOS: {ran.stderr.strip()[-200:]}")
    assert ran.returncode == 0, f"{what}: the process ended with {ran.returncode}\n{ran.stderr[-500:]}"
    return ran.stdout


@pytest.fixture(scope="module")
def threads_mod(build_extension: Callable[..., ModuleType], tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    source = tmp_path_factory.mktemp("threads") / "threads_rec.wat"
    source.write_text(_WAT, encoding="utf-8")
    return build_extension(source, "threads_rec")


def test_a_stack_overflow_in_a_worker_thread_is_a_trap_and_not_a_crash(threads_mod: ModuleType) -> None:
    assert threads_mod.__file__ is not None
    out = _run(_WORKERS.format(path=str(Path(threads_mod.__file__).parent), mod=threads_mod.__name__), "workers")
    assert "workers: True" in out and "together: True" in out and "main: trap" in out, out


def test_a_stack_overflow_in_the_thread_that_imported_the_module_is_a_trap(threads_mod: ModuleType) -> None:
    assert threads_mod.__file__ is not None
    out = _run(
        _IMPORT_IN_A_THREAD.format(path=str(Path(threads_mod.__file__).parent), mod=threads_mod.__name__),
        "the importing thread",
    )
    assert "importing thread: True" in out, out


_SMALL_STACK = """
import sys, threading
sys.path.insert(0, {path!r})
import {mod}
threading.stack_size(512 * 1024)
out = []

def go():
    inst = {mod}.Instance({mod}.Store())
    try:
        inst.rec()
    except {mod}.Trap as exc:
        out.append(str(exc))

t = threading.Thread(target=go)
t.start()
t.join()
main = {mod}.Instance({mod}.Store())
try:
    main.rec()
except {mod}.Trap as exc:
    out.append(str(exc))
print("messages:", out)
"""


def test_a_stack_overflow_is_called_so_in_a_thread_with_a_small_stack_and_in_the_main_thread(
    threads_mod: ModuleType,
) -> None:
    """The handler of the guard page would call an overflow in a thread other than the main one an out-of-bounds access; the check of the stack pointer says what it is."""
    assert threads_mod.__file__ is not None
    out = _run(
        _SMALL_STACK.format(path=str(Path(threads_mod.__file__).parent), mod=threads_mod.__name__), "small stack"
    )
    line = next(row for row in out.splitlines() if row.startswith("messages:"))
    assert line.lower().count("stack") == 2 and "out-of-bounds" not in line.lower(), line
