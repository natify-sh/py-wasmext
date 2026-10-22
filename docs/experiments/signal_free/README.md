# The cost of a signal-free wasm2c: bounds checks for memory

`mem.wat`: a loop that stores a word and loads it back (a dependent chain, 16384 words, 2000 rounds: 65.5 million accesses), the worst case for the check of the memory, built twice with `wasmext natify`, **[run]** 2026-10-22, one cloud VM, CPython 3.11, gcc `-O2`, three runs each:

| Build | Time | Memory operations a second |
| --- | ---: | ---: |
| default: **guard pages** (a handler of signals turns the fault into a trap) | 30.3-31.0 ms | 2.12-2.16 G |
| `--no-guard-pages`: **explicit bounds check on each access**, no signal | 61.6-65.0 ms | 1.01-1.06 G |

So the check of the bounds costs **about 2 times on a loop that does nothing but memory** (an upper bound for real programs, which also compute). Together with the depth counter for the stack ([../free_threading/](../free_threading/), section 4: about 4 times on calls inside a module) this is the price of a runtime with **no handler and no process-wide state**;
the two together on one workload were not measured. `build`: `CFLAGS=-O2 wasmext natify -i -b mg.wasm` and `... --no-guard-pages ... mb.wasm` (the same module under two names).
