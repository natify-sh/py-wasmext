"""Examples of pywasm3 (`examples/`), run as native extensions: `00-fibonacci.py` and `01-coremark.py`. The modules are
the ones of the examples (the first is the WAT of `00-fibonacci.py`, the second `coremark-minimal.wasm`, unchanged)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from subprocess import CalledProcessError
from types import ModuleType

import pytest

DATA = Path(__file__).parent / "data" / "pywasm3"
Builder = Callable[..., ModuleType]


def test_fibonacci(build_extension: Builder, tmp_path: Path) -> None:
    wat = tmp_path / "fib.wat"
    wat.write_text(
        """
(module
  (func $fib (export "fib") (param $n i64) (result i64)
    (if (i64.lt_u (local.get $n) (i64.const 2))
      (then (return (local.get $n))))
    (return (i64.add (call $fib (i64.sub (local.get $n) (i64.const 2)))
                     (call $fib (i64.sub (local.get $n) (i64.const 1))))))
)
""",
        encoding="utf-8",
    )
    fib = build_extension(wat, "pw3_fib").Instance()
    assert fib.fib(24) == 46368  # N and the result of the example
    assert [fib.fib(n) for n in range(10)] == [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    assert fib.fib(2**64 + 5) == 5  # an i64 argument wraps, as in the JavaScript API


@pytest.mark.xfail(
    raises=CalledProcessError,
    strict=True,
    reason="the module has return_call in functions with locals, and wasm2c 1.0.42 writes C that does not compile for those",
)
def test_coremark_minimal(build_extension: Builder) -> None:
    # The file name has a hyphen: the module name is given by hand (wasmize() wants a name that can be imported).
    mod = build_extension(DATA / "coremark-minimal.wasm", "pw3_coremark")
    now = 0

    def clock_ms() -> int:
        # CoreMark wants a last pass of 10 s or more and decides its length from the clock it is given: this one jumps
        # 15 s on every reading, so that the run is short and the same on every machine.
        nonlocal now
        now += 15_000
        return now

    score = mod.Instance({"env": {"clock_ms": clock_ms}}).run()
    assert score > 1  # 0.0 is what the module gives for a run it did not validate (the example prints "Error")
