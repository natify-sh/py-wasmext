# How fast is the interpreter of WABT (`wasm-interp`)?

**[run]** 2026-10-22, one cloud VM, `wasm-interp` of `wabt-package` 1.0.42.0 (the PyPI build: `wasi support not compiled in`, so it has no WASI), modules built by wasi-sdk 34.0 clang `-O3`.

| Workload | `wasm-interp` | wasmext (wasm2c, C compiler `-O2`, in an extension) | native C (gcc -O3) |
| --- | ---: | ---: | ---: |
| `fib(32)` through a table, about 7 million calls | **1.11-1.22 s** | 15.6-16.7 ms (guard page), 29-34 ms (check of the stack pointer) | |
| CoreMark, iterations a second | **131** (115 at 100 iterations, 131 at 1000; the time grows with the iterations) | 21,363 (guard page), 19,650 (check of the stack pointer) | 21,704 |

So on CoreMark the interpreter is about **0.6% of native, 160 times slower than native and than the extension**; on a loop of calls through a table about 40 to 70 times slower than the extension. Nothing in the README of WABT says it is meant to be fast (it describes `wasm-interp` as "a stack-based interpreter", used there to run spec tests); this is a reference tool, not an engine.

How it was measured (and what is not clean):
- `fib`: `fib.wat` with an export that calls `fib(32)`; `wasm-interp f.wasm --run-all-exports`, wall time of three runs.
- CoreMark: the EEMBC sources (`posix` port) compiled by wasi-sdk 34.0 for `wasm32-wasip1` with `-DSEED_METHOD=SEED_VOLATILE -DITERATIONS=N -DPERFORMANCE_RUN=1 -DTOTAL_DATA_SIZE=2000`; because `wasm-interp` of the PyPI wheel cannot run WASI, the module was turned into text (`wasm2wat`), each import of `wasi_snapshot_preview1` was replaced by a function of the same type that returns 0 (`fd_write` returns 8, so that `printf` gives up; `proc_exit` does nothing), and made binary again (`wat2wasm`). The program prints nothing and its own clock reads zero, so **the result of CoreMark was not validated here and the number is the wall time of N iterations divided into N**. With the default `SEED_ARG` and no arguments the program ran no iterations (the time did not grow), which is why `SEED_VOLATILE`.
- One machine, one build of each; the runs differ by a few percent. The module differs a little from the one the extension was measured on (`examples/coremark`, zig cc, barebones port with `wiring` imports): the same sources of CoreMark, another clock and printf.
