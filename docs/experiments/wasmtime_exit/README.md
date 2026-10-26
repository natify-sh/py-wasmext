# What Wasmtime does at the end of a program (2026-10-26)

Two scripts, run with `wasmtime` 49.0.0 (the Python package) on Linux; **[run]**.

- `core_exit.py`: two instances of one core module in one store (preview1), one calls `proc_exit(7)`. Result: `ExitTrap` with code 7; the other instance, **the same instance** and a file the other had opened all work afterwards; the instance can exit again. (The line `A.write_fd` with errno 8 proves nothing: A reads the descriptor from its own memory, where there is none.)
- `component_trap.py`: a component (written in WAT) whose export traps (`unreachable`). Result: the next call of that instance, of another instance of the component and of **another component** in the same store, all fail with `cannot enter component instance`; a new store works. (A trap, not `wasi:cli/exit`.)

What follows for wasmext is in `docs/fusedwasi_p1_over_p2.md`, stage C: the end is what the call leaves, as for core modules.
