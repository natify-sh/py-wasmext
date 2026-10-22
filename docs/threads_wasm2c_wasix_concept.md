# Threads: what wasm2c can do, what WASIX asks for (a reading, nothing is built)

Status: **a reading of sources; nothing was run or built.** Written on 2026-10-22 from shallow clones of `WebAssembly/wabt` (commit `0086e24`, 2026-10-21) and `wasix-org/wasix-libc` (commit `2025b44`,
2026-10-02). How a fact is known: **[read]** read in those sources, **[estimate]** a judgement. The question: does `wasm2c` support threads, and would it work with WASIX?

## Short answer

1. **`wasm2c` translates the data side of threads and not the waiting side, and it creates no threads itself.** Shared memory and the atomic loads, stores, read-modify-write operations,
   compare-exchange and `atomic.fence` are translated (flag `--enable-threads`, C11 atomics). **`memory.atomic.wait32/64` and `memory.atomic.notify` are `UNIMPLEMENTED`** in the C writer **[read]**.
   Threads are the embedder's job: its own `pthread`s, `wasm_rt_init_thread()` in each.
2. **WASIX does not need those two instructions.** Its libc replaces them with imports (`futex_wait`, `futex_wake`) on purpose. **It does need a runtime that spawns a thread** (`thread_spawn_v2`),
   which is a wasmext host's job, not `wasm2c`'s. So it can work **in principle**, with three pieces that wasmext does not have (below); it is **not tried**.

## wasm2c and threads **[read]**

- README of WABT: the table of proposals has no tick for `wasm2c` on *threads*; the README of `wasm2c` says only that the generated code targets C11 "if the module uses Wasm threads/atomics"
  (the earlier note in [wasm2c_limits.md](wasm2c_limits.md) agrees: it translates although the table does not tick).
- Done in `c-writer.cc`: `AtomicLoad`, `AtomicStore`, `AtomicRmw`, `AtomicRmwCmpxchg` (all widths) and `AtomicFence` (`atomic_thread_fence(seq_cst)`).
  **Not done: `AtomicWait`, `AtomicNotify`** (they fall in the same `UNIMPLEMENTED("...")` case as `call_ref`). A module that uses `memory.atomic.wait32` stops `wasm2c`.
- Shared memory: `wasm_rt_shared_memory_t` (`_Atomic volatile uint8_t* data`, and `mem_lock`, a mutex taken by `wasm_rt_grow_memory_shared`); `wasm_rt_allocate_memory_shared`, `..._grow_memory_shared`,
  `..._free_memory_shared`. It is not an "unshared default 32-bit single memory", so the fast path of one memory with guard pages is not used.
- Threads: `wasm_rt_init_thread()` / `wasm_rt_free_thread()` give each embedder thread its alternate signal stack and trap state (`WASM_RT_THREAD_LOCAL` variables such as the call depth). The example
  `wasm2c/examples/threads` starts 1024 `pthread`s, **each instantiating the module itself** (`wasm2c_sample_instantiate(&inst)`) and trapping on its own stack; there is no example of **several threads sharing one memory**.
- Tests: a single spec file for threads in `test/wasm2c/spec/threads/atomic.txt` (a subset of the threads proposal, a `(memory 1 1 shared)`); I did not find a test for wait/notify or for threads sharing a memory.
- Imported shared memory: an imported memory is a pointer to the memory struct in the generated C, so two instances can point to one `wasm_rt_shared_memory_t` **[estimate]**; whether the generated code does it correctly for the shared kind
  was not checked.

## wasmext today

- The reader knows the shared bit of `limits` (`Limits.shared`), and linking a shared memory is **refused** (FEATURES.md, "Imported memories").
- `--enable-threads` is **not passed** to `wasm2c`; the runtime is built without its threads; `WASMEXT_LAYOUT` does not cover `wasm_rt_shared_memory_t`. FEATURES.md lists threads as open ("after tables").
- The extension does not call `wasm_rt_init_thread` for a Python thread that enters it (`wasm_rt_init` is called once). **[read]**

## WASIX **[read]**

WASIX is wasi-libc forked by `wasix-org` (`wasix-libc`, musl-based), with its own import module `wasix_32v1` next to `wasi_snapshot_preview1` (the header `api_wasix.h` has 89 functions on top of WASI).

- **Threads are real.** `pthread_create` calls `__wasi_thread_spawn_v2` and the module **must export `wasi_thread_start(tid, arg)`**; the runtime starts a new thread, which gets **its own instance of the same module sharing the memory**
  and calls that export. The structure passed holds the stack and `tls_base`; `__wasm_init_tls` runs in the new thread. Same model as the `wasi-threads` proposal, extended (joins, signals, `getpid`).
- **Waiting is an import, not an instruction.** `__wait`, `__timedwait` and `__wake` use `__wasilibc_futex_wait_wasix` / `__wasilibc_futex_wake_wasix`, which call `wasix_32v1.futex_wait`, `futex_wake`, `futex_wake_all`. The source says why:
  the wait is "fed to a syscall rather than use atomics so that the asyncify and journaling can work properly"; the `memory.atomic.wait32` / `notify` lines are present and commented out or used only for the non-WASIX path (`__wasilibc_futex_wait`).
  So **musl-level locks, condition variables, joins** need nothing that `wasm2c` lacks. Code that does not go through libc (hand-written atomics with `wait`, Rust's `std` on some targets) can still emit the instructions.
- The module needs: a **shared, imported memory**, atomics and bulk memory (`-mbulk-memory`, `-pthread`, `-mthread-model posix`), and in the README an explicit note: "memory mapping is currently not compatible with threads".
- Other WASIX features that appear with threads: `setjmp`/`longjmp` through WASM exceptions **or asyncify**, `fork`/`vfork`/`exec`, signals as callbacks (`callback_signal`), TTY, sockets in the libc (`socket`, `bind`, `resolve`). Threads alone do not need them, but a program built for WASIX imports a large part of `wasix_32v1` and the host has to answer all of the imports it names (or refuse them).

## What would be needed in wasmext to run a WASIX program with threads **[estimate]**

1. **Pass `--enable-threads`** and build the runtime with its C11/pthread parts; declare the memory shared and allow **linking a shared memory** (the refusal in FEATURES.md goes; the layout check learns `wasm_rt_shared_memory_t`).
2. **A host for `wasix_32v1`:** at least `thread_spawn_v2`, `futex_wait`, `futex_wake`, `futex_wake_all`, `thread_exit`, `thread_join`, `thread_sleep`, `thread_id`, besides the WASI 0.1 calls (those are inside the module, in C, for `wasi_snapshot_preview1`; the `wasix_32v1` ones are not).
   `thread_spawn_v2` has to: start an OS thread, call `wasm_rt_init_thread()`, **instantiate the same module again, with its memory import pointing at the first instance's shared memory**, and call `wasi_thread_start(tid, arg)`; `futex_*` need a table keyed by address with a condition variable.
3. **Python-side rules:** a thread that runs wasm needs `wasm_rt_init_thread`; instances, traps and the GIL (the call into the instance should release the GIL, as a long call is today? not checked) and the free-threaded builds, which FEATURES.md says are not audited.
4. **Per-instance state is not shared by design:** globals (`__stack_pointer`) and tables are per instance, as in the `wasi-threads` model; the tests would need to confirm that a funcref table and an element segment do not clash between instances.

## Open questions (to find out before choosing)

- Does the generated code for an **imported shared memory** use the shared struct correctly? A two-instance test is the answer, also for the plain `grow` under a lock.
- A WASIX module is built with the target of `wasix-libc` and wasi-sdk's clang does not know it: which toolchain makes such a module in a reproducible way (the sysroot is released in the repository)? Without one the whole line cannot be tried.
- Which threaded modules exist that do not use `wait`/`notify` instructions at all? Emscripten/wasi-threads builds of musl use the instruction (`__wasilibc_futex_wait` of wasi-libc), so for them `wasm2c` stops, and a small patch to WABT (translating wait/notify to a futex-like runtime function) would be the missing part.
- Is there an upstream issue for `memory.atomic.wait/notify` in `wasm2c`? (not looked for: the session cannot read other repositories' issues.)

## Options

- **A. Do nothing** (as now): threads stay "not yet".
- **B. Pass the flag, support threads in the embedder only** (the C example's model): a module with shared memory and atomics, no wait/notify, threads started by the user's C or Python code, each with `wasm_rt_init_thread`. The smallest step; it covers what `wasm2c` can already do.
- **C. B plus wait/notify** in `wasm2c` (a patch carried in `wabt-package`, as for other `wasm2c` gaps) and a futex table in the runtime: wasi-threads/Emscripten modules, and WASIX's too.
- **D. A host for WASIX** (point 2 above) on top of C or B: the WASIX line; the largest, and only worth it for a program that needs it (a threaded program that cannot be built for WASI 0.1 or 0.2 without threads).
- **E. Another backend** (a runtime with threads): rejected as for typed function references, see [WASI_COMPONENTS.md](WASI_COMPONENTS.md).

Recommendation (not a decision): do **a test of B first** (flag, two instances on one shared memory, a thread each), because it answers the first open question and costs a day; C and D only after it.
