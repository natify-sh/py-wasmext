"""Examples of pywasm3 (`examples/`), run as native extensions: `00-fibonacci.py` and `01-coremark.py`. The modules are
the ones of the examples (the first is the WAT of `00-fibonacci.py`, the second `coremark-minimal.wasm`, unchanged)."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
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
    # The module has return_call in functions with locals: wasm2c 1.0.42 writes C that does not compile for those, and
    # wasmext repairs it. 10 passes in the 15 s of the clock above; a run that is not valid scores 0.0.
    assert score == pytest.approx(10 / 15, rel=1e-6)


# The pygame examples (`pygame-*.py`): a module draws a frame into its memory when `run()` is called, and the host reads the
# pixels from there. Here the host gives a fixed "random" and the frame is read without a window.
def _frame(inst: object) -> bytes:
    return bytes(inst.mem)  # type: ignore[attr-defined]


def test_fire_draws_a_frame_into_its_memory(build_extension: Builder) -> None:
    mod = build_extension(DATA / "fire.wasm", "pw3_fire")
    frames: list[bytes] = []
    for _ in range(2):  # the same "random" gives the same frame
        inst = mod.Instance({"": {"rand": lambda: 0.5}})
        before = _frame(inst)
        inst.run()
        frames.append(_frame(inst))
        assert frames[-1] != before
    assert frames[0] == frames[1]


def test_ray_tracer_uses_the_sin_of_the_host(build_extension: Builder) -> None:
    mod = build_extension(DATA / "ray.wasm", "pw3_ray")
    inst = mod.Instance({"Math": {"sin": math.sin}})
    inst.run(0.5)
    first = _frame(inst)
    inst.run(1.5)
    assert any(first) and _frame(inst) != first  # another time, another picture


def test_maze_calls_back_for_random_sin_and_time(build_extension: Builder) -> None:
    mod = build_extension(DATA / "maze.wasm", "pw3_maze")
    ticks: list[int] = []
    inst = mod.Instance({"Math": {"random": lambda: 0.25, "sin": math.sin}, "env": {"t": ticks.append}})
    before = _frame(inst)
    inst.run()
    assert _frame(inst) != before
