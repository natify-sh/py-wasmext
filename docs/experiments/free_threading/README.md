# Threads calling into a wasmext extension: with the GIL, without it

Answers, from Python, open question 7 of [context_concept.md](../../context_concept.md) (the cost and the behaviour of calls from several threads) and what happens on a free-threaded build, which wasmext has never run without the GIL.
**[run]** 2026-10-22, one cloud VM (Intel Xeon 2.1 GHz, 4 cores), CPython 3.14.6 and 3.14.6t from `uv`, wasmext at the checkout of this repository, wasm2c 1.0.42; one run each, so read the orders of magnitude.

`ft.wat` is a small module (`add`; `work(n)`, a xorshift loop of about 1 ns a step, so the C compiler cannot fold it into a formula; `trap`; `oob`; `recurse`, an infinite recursion through a table, so it cannot become a loop). `bench.py` has three parts.
Three builds of the same module:

| Build | Python | What |
| --- | --- | --- |
| `gil` | 3.14, with the GIL | the extension as wasmext makes it (abi3) |
| `ft, GIL on` | 3.14t | the extension as wasmext makes it (native). The import turns the GIL **on** (`RuntimeWarning: The global interpreter lock (GIL) has been enabled to load module 'ft'`) because the module does not declare that it can run without it |
| `ft, no GIL` | 3.14t | the same C with one line added to `PyInit_ft` in the generated `ft_py.c` (done by hand for this test, **not in wasmext**): `PyUnstable_Module_SetGIL(m, Py_MOD_GIL_NOT_USED)` |

```sh
wat2wasm ft.wat -o ft.wasm
uv run --python 3.14 wasmext natify -i -b ft.wasm                  # gil
uv run --python 3.14t wasmext natify -i -b ft.wasm                 # ft, GIL on
# ft, no GIL: wasmext natify ft.wasm (only the C), add the SetGIL line after PyModule_Create in build/wasmext/ft/ft_py.c, then natify -i -b again
python bench.py                                                    # in the folder with ft; ONLY=1|2|3 for one part
```

Results: `results_gil.txt`, `results_ft_gil_on.txt`, `results_ft_nogil.txt`.

## 1. Throughput (calls per second, all threads together; speed-up over one thread)

| Call | threads | GIL | free-threaded, GIL on | **free-threaded, no GIL** (own instances / one instance) |
| --- | ---: | ---: | ---: | ---: |
| `add` (a few ns of work) | 1 | 20.8M | 23.1M | 23.6M |
| | 2 | 1.0x | 0.9x | 1.6x / 1.8x |
| | 4 | 1.0x | 0.8-0.9x | **2.3x / 1.9x** |
| `work(1000)` (about 2 us) | 4 | 0.9-1.0x | 0.9x | **3.8x / 4.0x** |
| `work(100000)` (about 200 us) | 4 | 0.9x | 0.9x | **3.7x / 3.9x** |

- **With the GIL there is no gain from threads, as expected** (1.0x, and a little under it from the switching), and a free-threaded build that turns the GIL back on is the same.
- **Without the GIL the speed-up is close to the number of cores** (3.7-4.0x on 4 cores) as soon as a call does real work, **also when all threads call the same instance** (a function with no state). A call of a few ns is limited by what is
  around it (Python's call, the reference counting): 2.3x.
- One thread is not slower without the GIL (23.6M against 20.8-23.1M calls per second): **declaring the module free of the GIL costs nothing here.**

## 2. A short call while another thread is in a long call

Thread A calls `work(500000000)` (about 1.05 s here); thread B calls `add`, sleeps 1 ms, in a loop.

| | long call | short calls done while it ran | the first one done after |
| --- | ---: | ---: | ---: |
| GIL | 1,050 ms | **1** (the one that waited) | **1,049 ms** |
| free-threaded, GIL on | 1,088 ms | **0** | **1,088 ms** |
| free-threaded, no GIL | 1,068 ms | **944** | **0 ms** (longest pause 4.1 ms) |

**A call into wasm holds the GIL for as long as it lasts**: nothing in the generated C gives the GIL back (the switch interval of Python, 5 ms, only works between bytecodes, never inside a C call), so a thread that wants to run Python waits for the whole call. That is
what a long wasm call costs every other thread of a program with the GIL; without it, the other threads run.

## 3. Traps in worker threads

A trap in a thread, in a subprocess each (a crash is a result):

| | GIL | free-threaded, GIL on | free-threaded, no GIL |
| --- | --- | --- | --- |
| `unreachable`, in a worker thread / the main thread | `Trap` / `Trap` | the same | the same |
| memory out of bounds, worker / main | `Trap` / `Trap` | the same | the same |
| **stack overflow (`recurse`), main thread** | `Trap: Call stack exhausted` | the same | the same |
| **stack overflow, a worker thread** | **crash, exit code -11 (SIGSEGV)** | **crash** | **crash** |

**A finding that has nothing to do with the GIL: a stack overflow in any thread other than the one that imported the module kills the process**, on every build here. The cause (checked by one more test) is that the extension calls `wasm_rt_init()` once, at import, and never
`wasm_rt_init_thread()` for another thread: the thread has no alternate stack for the signal handler that turns the overflow into a trap. A thread that did the import itself (the module imported inside the worker) gets a trap (`Out-of-bounds access`: on a thread's
stack the overflow is reported like an out-of-bounds access, as the comment of the `wasm2c` example says). The shared library does it right (`api_enter` sets a thread up at its first call); **the Python extension does not**. The fix is the same few lines: a thread-local flag in the entry
and `wasm_rt_init_thread()` when it is not set (and `wasm_rt_free_thread()` when the thread ends), which `FEATURES.md` lists with threads. Not done here.

## What it says

1. **Declaring `Py_MOD_GIL_NOT_USED` works for a module with no state** and gives near-linear speed-up on 4 cores; without the declaration a free-threaded Python turns the GIL on (with a warning), and nothing is gained. The declaration is one line for single-phase init
   (`PyUnstable_Module_SetGIL`, 3.13+) and `Py_mod_gil` in the slots of multi-phase init.
2. **Not audited, so not declared in wasmext:** the Python side of an `Instance` (its `refs`, host callables, exported `memoryview`, `Table` and `Function`, the keep-alive chains) was **not** exercised from several threads; this test calls a function with no state and no imports. Creating and freeing
   instances from several threads, calling through an import, `grow` of a memory under a view, and the GC were not tried. The context ([context_concept.md](../../context_concept.md)) is where that audit belongs, as `FEATURES.md` already says.
3. **For the context and the counter of active calls:** under the GIL the plain counter is enough (and the call already serializes all threads); the atomic, per-thread-striped form is for a free-threaded build, where the C benchmark applies:
   [../context_bench/](../context_bench/).
4. **Two things to fix whatever is decided about the context:** the thread setup above (a crash on a stack overflow in a worker thread, with the GIL too), and, when threads matter, the declaration.
5. Not measured: macOS/Windows/ARM, 3.15t, a module that keeps state or calls Python from wasm, many instances.
