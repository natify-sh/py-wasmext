# Micro-benchmark for the context (docs/context_concept.md, "Overhead")

`bench.c` measures the two things the concept puts on the hot paths. **[run]** on one machine: Intel Xeon @ 2.10 GHz (a shared cloud VM, 4 cores), gcc 13.3 `-O2`, 2026-10-22; two runs
(`results.txt`, `results_run2.txt`), numbers within about 10-20 % of each other except where noted. A VM is noisy; read the orders of magnitude, not the digits.

```sh
cc -O2 -pthread bench.c -o bench && ./bench
```

"Threads" are **threads of the host** (Python threads on a free-threaded build, or `pthread`s of a C host) calling into members of the context at the same time; they are not WebAssembly threads. "One" context: all of them share its
lock and counter. "Each": every thread has a context of its own. On a CPython with the GIL a call into wasm holds the GIL (it is released in one place only, `wasi_python.h`, around some WASI I/O), so one thread at a time
reaches the registry and the 1-thread numbers are the ones that apply.

## 1. The registry: the owner of a `funcref` by pointer (ns per lookup)

Open addressing, a lookup by `module_instance`, random keys.

| Members | 1 thread, no lock | 1 thread, mutex | 4 threads, one context, mutex | 4 threads, one context each, mutex |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 4 | 25 | 300 | 60 |
| 1 000 | 10 | 22 | 390 | 26 |
| 100 000 | 17 | 31-44 | 470-480 | 38-46 |
| 1 000 000 | 37 | 66-106 | 850-950 | 94 |

- **A lock costs about 15-20 ns** when nobody else wants it (a `pthread_mutex` pair); the lookup itself is 4-17 ns while the table fits the cache, and 37 ns at a million members (cache misses).
- **One lock under threads is the problem, not the lock**: 4 threads on one context pay 300-950 ns per lookup (20-30 times), and a `pthread_rwlock` is no better (170-400 ns; its read lock is an atomic on a shared cache line, too).
  A context each costs the same as one thread.
- The members only grow and never leave (the concept), so **a read with no lock is possible** (the column "no lock" is its cost: 4-37 ns, and it scales as it touches no shared line) **[estimate]**:
  slots written once and published with a release store, a resize that swaps a pointer and frees the old table after a grace period. **Not built or measured with a writer.**

## 2. The entry of a call: "active calls" counter and "closed" check (ns per call)

| | 1 thread | 4 threads, **same** counter | 4 threads, **own** counter |
| --- | ---: | ---: | ---: |
| a bare indirect call | 3.1-3.5 | 3.0-3.6 | 3.3-4.6 |
| plain counter + check | 4.5-4.7 | not safe | not safe |
| atomic (seq_cst) counter + check | 15.7-16.2 | **222-227** | 25-29 |
| atomic (acquire/release) counter + check | 15.7-18.1 | **218-229** | 19 |

- **Plain counter + check adds about 1.5 ns.** It is enough where one thread at a time is in the context (the GIL).
- **An atomic counter adds about 12-14 ns** (two `lock`ed operations; acquire/release is the same as seq_cst on x86). For comparison the entry that guards a reentrant call costs about 5 ns, 13 % of a Python call, in an earlier measurement.
- **One counter shared by 4 threads costs 60-70 times more** (222 ns) than a bare call: the cache line moves between the cores. A counter on a cache line of its own for each member (not for the context) comes back to 19-29 ns.

## What it says for the design **[estimate]**

1. The registry lookup is **cheap alone and expensive under contention**; because members never leave, the read path can be lock-free, and a lock stays only for adding a member.
2. **The active-call counter should not be one per context** (or atomic on the hot path where there is a GIL): per member (a line of its own), or plain under the GIL with an atomic only in a build that has no GIL (a macro, as `WASMEXT_LOCK`).
   Or no counter at all: `close` refuses while any call is in flight, which a counter per thread (or the "closing" flag plus a wait for the threads to leave) can tell without touching a shared line on every call.
3. None of this changes the answer for the common case (one thread, the GIL): about 1.5 ns for a plain counter and a check, and 15-20 ns for a lock when a lookup is made.
4. **Not measured:** a registry with a writer; many contexts; macOS/Windows/ARM; Python (see 3 below for the C side of a real call, and the open work on free-threaded builds).

## 3. The same, around real calls into a module (no Python): `real.c`

The guard of section 2 and a registry lookup, put around real calls through the C API of a wasmext **shared library** (`wasmext natify --shared`, the module `bm.wat`: `add` and a loop `work(n)`), called from `pthread`s of a C host.
Build: `wasmext natify --shared -b --build-dir DIR bm.wasm`, then the line at the top of `real.c`. Two runs (`real_results_run1.txt` has the plain counter shared by the threads, an invalid row; `real_results_run2.txt` is the second run
with that row left out); one machine as above; the runs of 100 us differ by 10-20 % from each other, read them as "no difference".

ns per call, per thread, run 2:

| Around the call | `add`, 1 thread | `add`, 4 threads, own instances | `add`, 4 threads, one instance | `work(1000)` (about 650 ns), 4 threads, one instance |
| --- | ---: | ---: | ---: | ---: |
| nothing (a call through the library) | 23 | 27 | 25 | 710 |
| plain counter + check (one thread only) | 21 | - | - | - |
| atomic counter, **one per thread** (own line) | 31-35 | 35 | 35 | 840-890 (the run was noisy: bare 886) |
| atomic counter, **one per instance** | 34 | 34 | **292** | 800 |
| atomic counter, **one per context** | 30-31 | **330** | **334** | 740-820 |
| mutex + registry lookup **on every call** | 34-36 | **435** | **423** | 860-890 |

- **A call through the library costs about 23 ns for a function that does nothing** (the entry that sets up the trap guard and the lookup of the thread's state), not the 3 ns of a bare indirect call. A guard that adds 4-12 ns is 20-50 % of *that*; at about 650 ns of work it is
  invisible on one thread (the differences are inside the noise), and at 100 us nothing is visible.
- **Threads of the host scale**: 4 threads on their own instances, or all on one instance (a function with no state), take the same time per call as one thread (23, 27, 25 ns): **the runtime has no lock of its own on this path.**
- **Contention is the cost, as in section 2:** a counter per context (one cache line for all threads) or a lock per call makes a `add` 13-18 times slower on 4 threads (330-435 ns) and adds 10-25 % to a call of about 650 ns. A counter on a line of its own **for each thread** is as cheap as with one thread (31-35 ns). **A counter per instance is cheap only while one thread calls the instance** (34 ns); when 4 threads call the same instance it
  is as bad as one per context (292 ns): the cache line moves between the cores. (An earlier version of this README called the per-thread row "per instance" in the one-instance column; `real.c` is corrected and `real_results_run3.txt` is the run with both rows.)
- The registry lookup is needed only to turn a bare `funcref` into its owner, **not on every call**; the row "on every call" is the worst case, to show what a lock costs if it were.

So for the design: **the counter of active calls is split by thread (a few cache lines in the instance, a thread uses one), and `close` adds them up**; never one per context, and not one per instance if several threads may call it; the lock of the registry only where a `funcref` is turned into a `Function`; the plain counter is for a single thread under the GIL.
