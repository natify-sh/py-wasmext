"""The test modules of wasm2mpy (`test/`): the same small program (a blinking LED, with `wiring` as the board) written in
eight languages, each a real compiler's output. Through the whole path: parse, wasm2c, C compiler, import, run."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

DATA = Path(__file__).parent / "data" / "wasm2mpy"
Builder = Callable[..., ModuleType]

# the greeting that `setup` prints, and how many "Blink" lines four calls of `loop` print (Rust's `loop` prints only the
# line ends: the module formats a number and the text of it does not come out; it is the module's own behaviour,
# and the same under any host)
LANGUAGES = {
    "assemblyscript": ("🚀 AssemblyScript is running!", 4),
    "cpp": ("🤩 C++ is running!", 4),
    "rust": ("🦀 Rust is running!", 0),
    "tinygo": ("🤖 TinyGo is running!", 4),
    "virgil": ("✨ Virgil is running", 4),
    "wat": ("⚙️ WAT is running!", 4),
    "zig": ("⚡ Zig is running!", 4),
}


class Board:
    """What the module asks of `wiring`; the strings it prints are read from its own memory."""

    def __init__(self) -> None:
        self.memory: Any = None
        self.log: list[tuple[str, tuple[int, ...]]] = []
        self.text = ""
        self.clock = 0

    def imports(self) -> dict[str, dict[str, Callable[..., Any]]]:
        def print_(ptr: int, length: int) -> None:
            self.text += bytes(self.memory[ptr : ptr + length]).decode()

        def millis() -> int:
            self.clock += 500
            return self.clock

        def note(name: str) -> Callable[..., None]:
            return lambda *args: self.log.append((name, args))

        return {
            "wiring": {
                "print": print_,
                "millis": millis,
                "pinMode": note("pinMode"),
                "digitalWrite": note("digitalWrite"),
                "delay": note("delay"),
            }
        }


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_blink_program_runs(build_extension: Builder, language: str) -> None:
    greeting, blinks = LANGUAGES[language]
    mod = build_extension(DATA / f"{language}.wasm", f"w2m_{language}")
    board = Board()
    inst = mod.Instance(board.imports())
    board.memory = inst.memory  # the strings it prints are in its memory, which the host reads when asked to print
    inst.setup()
    assert board.text.splitlines()[0] == greeting
    assert ("pinMode", (2, 1)) in board.log  # the LED pin is an output
    board.log.clear()
    for _ in range(4):
        inst.loop()
    delays = [args[0] for name, args in board.log if name == "delay"]
    writes = [args for name, args in board.log if name == "digitalWrite"]
    assert sorted(delays) == [100] * 4 + [900] * 4  # 100 ms on, 900 ms off (Zig's loop starts with the off half)
    assert sorted(writes) == [(2, 0)] * 4 + [(2, 1)] * 4
    assert all(a != b for a, b in itertools.pairwise(writes))  # it blinks: on, off, on, off
    assert board.text.count("Blink") == blinks
