from __future__ import annotations

import subprocess

import pytest
from productsdemo import HELLO, engine_ctypes


def test_the_library_is_called_through_ctypes() -> None:
    said: list[int] = []

    def log(value: int) -> int:
        said.append(value)
        return value + 1

    engine = engine_ctypes.Instance(engine_ctypes.Store(), imports={"env": {"log": log}})
    assert engine.add(2, 3) == 5
    assert engine.twice(7) == (7, 7)
    assert engine.call_log(41) == 42 and said == [41]  # the import is a function of Python
    assert bytes(engine.mem[:2]) == b"hi"


def test_a_trap_and_an_exception_of_webassembly_are_errors_of_python() -> None:
    engine = engine_ctypes.Instance(engine_ctypes.Store(), imports={"env": {"log": lambda value: value}})
    with pytest.raises(engine_ctypes.Trap):
        engine.trap()
    with pytest.raises(engine_ctypes.UncaughtException):
        engine.boom(1)
    assert engine.add(1, 1) == 2  # the instance is usable after a trap


def test_the_program_runs_with_no_python() -> None:
    assert HELLO.is_file()
    done = subprocess.run([HELLO], capture_output=True, check=False)
    assert done.stdout == b"hello, wasi\n"
    assert done.returncode == 3  # proc_exit(3) is the status of the process
