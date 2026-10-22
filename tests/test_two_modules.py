"""Two modules in one process, each with a runtime of wasm2c of its own: a trap that comes from a signal (a memory access past the guard pages, the stack running out).

The signal handler is one for the process, and every runtime installs its own at `wasm_rt_init` without chaining to the one before it, so the handler is the one of
the module that was imported last; it turns the signal into a trap of ITS runtime (`g_wasm_rt_jmp_buf` of its copy), which is not the entry of the call that is running
in the other module, and the process aborts. A trap that is not a signal (`unreachable`) is not affected. Known, not fixed: see "Known gaps" in docs/FEATURES.md and
docs/context_concept.md. The test is `xfail(strict=True)`: it fails the run when the problem is fixed, so that the mark is taken off.
"""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

_WAT = """(module
  (memory (export "memory") 1)
  (func (export "oob") (result i32) (i32.load (i32.const 0x7ffffff0)))
  (func (export "boom") (result i32) unreachable))
"""

_SCRIPT = """
import sys
sys.path.insert(0, {path!r})
import {first}, {second}   # {second} is imported last: its runtime owns the handler of the signals
for fn in ("boom", "oob"):
    try:
        getattr({first}.Instance(), fn)()
    except {first}.Trap:
        print(fn, "trap", flush=True)
print("alive", flush=True)
"""


@pytest.fixture(scope="module")
def two_mods(
    build_extension: Callable[..., ModuleType], tmp_path_factory: pytest.TempPathFactory
) -> tuple[ModuleType, ModuleType]:
    source = tmp_path_factory.mktemp("two") / "two_src.wat"
    source.write_text(_WAT, encoding="utf-8")
    return build_extension(source, "two_a"), build_extension(source, "two_b")


def _run(mods: tuple[ModuleType, ModuleType]) -> subprocess.CompletedProcess[str]:
    a, b = mods
    assert a.__file__ is not None
    script = _SCRIPT.format(path=str(Path(a.__file__).parent), first=a.__name__, second=b.__name__)
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=120)


def test_a_trap_that_is_not_a_signal_works_in_the_module_imported_first(
    two_mods: tuple[ModuleType, ModuleType],
) -> None:
    a, b = two_mods
    assert a.__file__ is not None
    script = _SCRIPT.format(path=str(Path(a.__file__).parent), first=a.__name__, second=b.__name__).replace(
        '("boom", "oob")', '("boom",)'
    )
    ran = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=120)
    assert ran.returncode == 0 and "boom trap" in ran.stdout and "alive" in ran.stdout, ran.stderr[-300:]


@pytest.mark.xfail(
    sys.platform != "win32",  # Windows handles the faults by a vectored handler per runtime, and all of them are called
    strict=True,
    reason="the handler of the signals is the one of the module imported last; the other aborts the process (known gap)",
)
def test_a_signal_trap_works_in_the_module_imported_first(two_mods: tuple[ModuleType, ModuleType]) -> None:
    ran = _run(two_mods)
    assert ran.returncode == 0 and "oob trap" in ran.stdout and "alive" in ran.stdout, (
        ran.returncode,
        ran.stderr[-300:],
    )
