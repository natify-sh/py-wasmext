"""Examples of pywasm3 (`examples/`), run as native extensions: `00-fibonacci.py` and `01-coremark.py`. The modules are
the ones of the examples (the first is the WAT of `00-fibonacci.py`, the second `coremark-minimal.wasm`, unchanged)."""

from __future__ import annotations

import math
import struct
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

DATA = Path(__file__).parent / "data" / "pywasm3"
Builder = Callable[..., ModuleType]


@pytest.fixture(params=["extension", "ctypes"])
def build_extension(request: pytest.FixtureRequest) -> Builder:
    """These examples run on both front ends: the extension, and the shared library through ctypes (the name `build_extension` is kept for the tests)."""
    return request.getfixturevalue("build_extension" if request.param == "extension" else "build_ctypes")  # type: ignore[no-any-return]


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
    fib = (_mod2 := build_extension(wat, "pw3_fib")).Instance(_mod2.Store())
    assert fib.fib(24) == 46368  # N and the result of the example
    assert [fib.fib(n) for n in range(10)] == [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    assert fib.fib(2**64 + 5) == 5  # an i64 argument wraps, as in the JavaScript API


def test_coremark_minimal(build_extension: Builder) -> None:
    # The file name has a hyphen: the module name is given by hand (natify() wants a name that can be imported).
    mod = build_extension(DATA / "coremark-minimal.wasm", "pw3_coremark")
    now = 0

    def clock_ms() -> int:
        # CoreMark wants a last pass of 10 s or more and decides its length from the clock it is given: this one jumps
        # 15 s on every reading, so that the run is short and the same on every machine.
        nonlocal now
        now += 15_000
        return now

    score = mod.Instance(mod.Store(), imports={"env": {"clock_ms": clock_ms}}).run()
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
        inst = mod.Instance(mod.Store(), imports={"": {"rand": lambda: 0.5}})
        before = _frame(inst)
        inst.run()
        frames.append(_frame(inst))
        assert frames[-1] != before
    assert frames[0] == frames[1]


def test_ray_tracer_uses_the_sin_of_the_host(build_extension: Builder) -> None:
    mod = build_extension(DATA / "ray.wasm", "pw3_ray")
    inst = mod.Instance(mod.Store(), imports={"Math": {"sin": math.sin}})
    inst.run(0.5)
    first = _frame(inst)
    inst.run(1.5)
    assert any(first) and _frame(inst) != first  # another time, another picture


def test_maze_calls_back_for_random_sin_and_time(build_extension: Builder) -> None:
    mod = build_extension(DATA / "maze.wasm", "pw3_maze")
    ticks: list[int] = []
    inst = mod.Instance(
        mod.Store(), imports={"Math": {"random": lambda: 0.25, "sin": math.sin}, "env": {"t": ticks.append}}
    )
    before = _frame(inst)
    inst.run()
    assert _frame(inst) != before


# `03-asyncified.py`: a module that Binaryen made able to pause (`wasm-opt --asyncify`); to pause it, the import `sleep` calls
# the exports `asyncify_start_unwind` of the module that is running. That is a call into an instance from inside a call
# from it (the module is not finished with its own `main` yet). The same steps as the example, without the event loop.
def test_asyncified_module_pauses_and_resumes_through_its_own_exports(build_extension: Builder) -> None:
    mod = build_extension(DATA / "asyncified.wasm", "pw3_asyncified")
    events: list[str] = []
    state = {"sleeping": False}
    box: dict[str, object] = {}

    def sleep(ms: int) -> None:
        inst = box["inst"]
        if not state["sleeping"]:
            events.append(f"sleep {ms}")
            data_addr = 16
            inst.memory[data_addr : data_addr + 8] = struct.pack("<II", data_addr + 8, 1024)  # type: ignore[attr-defined]
            inst.asyncify_start_unwind(data_addr)  # type: ignore[attr-defined]
            state["sleeping"] = True
        else:
            events.append("resume")
            inst.asyncify_stop_rewind()  # type: ignore[attr-defined]
            state["sleeping"] = False

    inst = mod.Instance(
        mod.Store(),
        imports={
            "env": {"before": lambda: events.append("before"), "sleep": sleep, "after": lambda: events.append("after")}
        },
    )
    box["inst"] = inst
    inst.main()
    events.append("stack unwound")
    inst.asyncify_stop_unwind()
    inst.asyncify_start_rewind(16)
    inst.main()  # the module goes back to where it was, and does what follows `sleep`
    assert events == ["before", "sleep 2000", "stack unwound", "resume", "after"]
    assert inst.asyncify_get_state() == 0  # normal again


def test_a_trap_after_a_call_into_the_instance_from_its_own_import(build_extension: Builder, tmp_path: Path) -> None:
    """What `asyncify` relies on is more general: an import calls an export of the running instance. When that inner call is
    over, a trap of the outer one must still come out of the outer call (not jump to the frame of the inner one), and a
    trap of the inner call is an exception in the import, which can be caught there."""
    wat = tmp_path / "reenter.wat"
    wat.write_text(
        """
(module
  (import "env" "host" (func $host (param i32)))
  (func (export "inner") (param i32) (result i32)
    local.get 0 i32.eqz if unreachable end
    local.get 0 i32.const 1 i32.add)
  (func (export "outer") (param i32) local.get 0 call $host)
  (func (export "outer_then_trap") (param i32) local.get 0 call $host unreachable))
""",
        encoding="utf-8",
    )
    mod = build_extension(wat, "pw3_reenter")
    seen: list[object] = []
    box: dict[str, object] = {}

    def host(x: int) -> None:
        inst = box["inst"]
        seen.append(inst.inner(x))  # type: ignore[attr-defined]

    inst = mod.Instance(mod.Store(), imports={"env": {"host": host}})
    box["inst"] = inst
    inst.outer(4)
    assert seen == [5]
    with pytest.raises(mod.Trap):
        inst.outer_then_trap(4)  # the inner call returned; the outer one traps
    assert seen == [5, 5]
    with pytest.raises(mod.Trap):
        inst.outer(0)  # the inner call traps: an exception out of `host`, and out of `outer`
    assert inst.inner(1) == 2  # still usable


# `04-suspend-resume.py` is about a feature of the wasm3 engine (a pause when the gas runs out, a snapshot of the paused call),
# which compiled code does not have and cannot get. Its module, though, is an ordinary one that keeps its progress in exported
# globals; it is run to the end here.
def test_collatz_search_of_the_suspend_example_runs_to_the_end(build_extension: Builder) -> None:
    inst = (_mod1 := build_extension(DATA / "collatz.wat", "pw3_collatz")).Instance(_mod1.Store())
    assert inst.search(10_000) == 6171  # the number below 10000 with the longest chain
    assert (inst.best_n, inst.best_len, inst.n) == (6171, 261, 10_000)
