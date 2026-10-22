"""Two modules in one process, each with a runtime of wasm2c of its own: a trap that comes from a signal (a memory access past the guard pages, the stack running out).

The handler of SIGSEGV/SIGBUS is one for the process. The runtime of wasm2c would install its own at `wasm_rt_init` without chaining to the one before it, so the handler
would be the one of the module imported last, which turns the signal into a trap of ITS runtime and not of the call that is running in the other module. So off Windows
the runtime installs none and every module installs a link of a chain (WASMEXT_CHAIN, see _gen.py): a fault in a call of the module is its trap, any other is given
to the handler that was before. Windows calls every vectored handler, so it needs nothing.
"""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from .conftest import SANITIZED

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


def test_a_signal_trap_works_in_both_modules_whatever_the_order(two_mods: tuple[ModuleType, ModuleType]) -> None:
    a, b = two_mods
    for mods in (
        (a, b),
        (b, a),
    ):  # the module that is called first is the one imported first, and then the one imported last
        ran = _run(mods)
        assert ran.returncode == 0 and "oob trap" in ran.stdout and "alive" in ran.stdout, (
            ran.returncode,
            ran.stderr[-300:],
        )


@pytest.mark.skipif(
    sys.platform == "win32", reason="ctypes turns the access violation into an OSError, and Windows has no chain"
)
@pytest.mark.skipif(SANITIZED, reason="the handler of ASan ends the process by itself, with another status")
def test_a_real_crash_outside_a_call_is_still_a_crash(two_mods: tuple[ModuleType, ModuleType]) -> None:
    """The handler is given the faults that are not of a call of its module: the process dies of SIGSEGV as it would without wasmext, not of a trap."""
    a, b = two_mods
    assert a.__file__ is not None
    script = f"import sys, ctypes; sys.path.insert(0, {str(Path(a.__file__).parent)!r}); import {a.__name__}, {b.__name__}; ctypes.string_at(0)"
    ran = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=30)
    assert ran.returncode in (-11, 139, -7), (ran.returncode, ran.stderr[-300:])
