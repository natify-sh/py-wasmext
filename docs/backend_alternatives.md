# Other ways to translate and run: wasmer, w2c2, llc (a reading and a measurement)

Status: **an evaluation, 2026-10-22; nothing built.** How a fact is known: **[read]** read in the sources or pages named, **[run]** run here, **[estimate]** a judgement, **[memory]** from what I knew before the session and not checked. The question: the embedded runtime of `wasm2c` brought the problems of the traps by signals (see [where_we_stopped_2026-10-22.md](where_we_stopped_2026-10-22.md),
[shared_runtime_concept.md](shared_runtime_concept.md)); is there another way to do the translation or the running that would avoid them, and keep the autonomy of a module?

## What the project asks of a way (the criteria)

1. **Autonomy:** a module is complete, the host installs nothing, no engine in every artifact (the choice made in [WASI_COMPONENTS.md](WASI_COMPONENTS.md)).
2. **No process-wide state** that two modules fight for (the handler of signals, the alternate stacks).
3. **Features:** what `wasm2c` 1.0.42 gives now (tail calls, exceptions, multi-memory, memory64, extended constants, funcref and externref, v128; not GC, typed references, relaxed SIMD).
4. **Portability:** CPython on Linux, macOS, Windows (x64, arm64, x86), manylinux/musllinux, big-endian s390x.
5. **Build needs:** a C compiler, not more.
6. **Speed.**

## 1. wasmer: `wasmer compile` and `wasmer create-exe`

**[read]** The article of Wasmer on native executables (wasmer.io, `wasm-as-universal-binary-format-part-1-native-executables`, release 3.0.0-beta, 2022; the pages of the current documentation could not be read from here, so **the flags of today, including `-m native`, are not checked**):
`create-exe` produces a **static object compiled from the `.wasm`**, and links it with **a minimal `libwasmer.a` (headless, no compilers) and the WASI glue**, with a C compiler/linker (Zig or Clang is needed). The result is one binary, "completely sandboxed with minimal runtime overhead", that needs no Wasmer installed.
`wasmer compile` makes an artifact that is loaded by Wasmer in headless mode (the page does not say more).

- **Autonomy:** what is "no runtime dependency" for a user is **the runtime inside every artifact** (a headless Wasmer: the engine that loads and traps). That is the thing the project left out on purpose, and it is the same shape as an embedded `wasm-rt`, only larger and in Rust.
- **Process-wide state:** an engine of this class turns traps into signals, so two artifacts with an engine each in one process would meet the same fight for the handler **[estimate]**; Wasmtime has a setting to make traps with no signals (`signals_based_traps`) **[memory]**, Wasmer's was not looked at. Not checked either way.
- **Features:** the widest of the ways here (GC, relaxed SIMD and others, depending on the compiler of the engine) **[memory]**.
- **Build:** Zig or Clang plus `libwasmer.a` (megabytes) for each target; no way to use it as a C file that `setuptools` compiles.
- **Verdict:** not an alternative to the translation to C for the extension model. It could be a **fallback for modules that `wasm2c` cannot translate** (GC, typed references, relaxed SIMD), at the price of two worlds in one tool.

## 2. w2c2

**[read]** `turbolent/w2c2` (MIT, the checkout of 2026-09-21): "translates WebAssembly modules to portable C", inspired by `wasm2c`.

- **Autonomy and process-wide state: the best of all of them.** There is **no handler of signals and no runtime file with state**: a trap is a call of `extern void trap(Trap)`, **a function that the embedder defines** (eleven kinds), and every access to the memory is an **explicit bounds check** (`trap(trapMemoryOutOfBounds)` in the macros of `w2c2_base.h`).
  It "supports multiple modules and instances". Nothing is shared by name between two modules except the symbol `trap`, which each extension would define for itself (a shared object is loaded with its own scope): the class of problems of this session does not exist. That is also how `WASM_RT_TRAP_HANDLER` already lets wasmext do the traps of `wasm2c`.
- **Portable:** C89, old and new compilers, big-endian, many systems (the README names Mac OS 9, DOS, Windows XP...), streaming translation with low memory, separate and parallel compilation of a module (like `--parts` here).
- **Speed (the claim of the README, not run here):** Coremark about 7 % slower than native. Our own measure of explicit checks in the other tool: 2 times on a loop of nothing but memory (below).
- **Gaps against what wasmext has [read, not run]:** the README lists the core 1.0, **threads and atomics, bulk memory, sign extension, non-trapping conversions** and nothing else; the translator (`w2c2/*.c`, `opcode.h`) has no prefix of SIMD (`0xFD`), no `return_call`, no `try_table` or `exnref`, no memory64, no multi-memory (a search for them found nothing). **So tail calls, exceptions, multi-memory, memory64, v128 and references in signatures, which wasmext has, would be lost** unless it has them under a form I did not find.
  There is **no trap for the stack running out** in the list of kinds (`Trap` has no exhaustion), so an infinite recursion would be a crash of the host stack, not a trap: a gap against the specification and against what `tests/test_two_modules.py` and `test_threads.py` ask here.
  Its own WASI (of the host, in C) overlaps with the one in wasmext's C.
- **Measured afterwards** ([experiments/w2c2/](experiments/w2c2/), 17 one-feature modules): it translates and compiles core, multi-memory, bulk memory, sign extension, saturating conversions and atomics **with** `memory.atomic.wait/notify`; it **fails on tail calls, exceptions (legacy, `try_table`, `exnref`), memory64, multi-value, reference types, SIMD, custom page sizes, extended constants and passive element segments**. The owner stopped this line (a dead end for the project).
- **Verdict:** the closest in spirit and **the best answer to the autonomy**; the price is the features and the stack. Worth keeping as **a backend to consider for the modules that need nothing of the newer features and want no signals at all** (and for platforms where wasm2c's handler is a trouble), and as a **reading for the design of a signal-free mode**. Not a replacement of `wasm2c` for the project as it is.

## 3. llc (LLVM) instead of wasm2c

`llc` compiles **LLVM IR** to machine code; it does not read WebAssembly **[memory]**. A route `wasm -> LLVM IR -> llc -> object` needs **a lifter** from WebAssembly to IR; the ones I know of (the LLVM compiler inside Wasmer, WAVM) are runtimes or libraries and **were not checked here** **[memory]**. `wasm2c` plus a C compiler is, in that picture, the same step with the C compiler in the place of `llc`, with the difference that every platform
of the project already has a C compiler and not all have LLVM. Gains one could hope for (a proper stack probe, `musttail`, landing pads, finer control of traps) are real but are **a backend to write**, not a tool to switch to. **Verdict: not an alternative today; nothing to try before there is a lifter that is worth the weight.**

## 4. What already exists inside `wasm2c`: the mode with no signals

`wasm-rt` has the two switches that make the same design as `w2c2` (no handler): **bounds checks for memory** (`--no-guard-pages`, `WASM_RT_USE_MMAP=0`) and **a depth counter for the stack** (`WASM_RT_STACK_DEPTH_COUNT`). Measured **[run]**:

| Part | Cost | Where |
| --- | --- | --- |
| bounds check of every access | **about 2 times** on a loop that does only memory (30.5 ms against 61.6-65.0 ms) | [experiments/signal_free/](experiments/signal_free/) |
| depth counter | **about 4 times** on calls inside a module (115 against 450 million calls a second); a limit counted in frames, not bytes | [experiments/free_threading/](experiments/free_threading/), section 4 |

Both together on one workload was not measured. So a signal-free `wasm2c` is **possible today and costs speed**; it keeps all the features of `wasm2c`, which `w2c2` does not.

## Comparison

| | wasm2c, handler per module (now) | **wasm2c, a chain of handlers** (tried) | wasm2c, signal-free (switches) | w2c2 | wasmer (`create-exe`) | llc |
| --- | --- | --- | --- | --- | --- | --- |
| Autonomy | yes | **yes** | **yes** | **yes** | **no** (engine inside) | n/a (needs a lifter) |
| No process-wide state | no (the bug) | per module, chained | **yes** | **yes** | engine's own | n/a |
| Features of wasm2c 1.0.42 | yes | yes | yes | **no** (core 1.0, threads, bulk, sign-ext, non-trapping) | more | n/a |
| Stack overflow trap | yes (alt stack) | yes | yes (counter) | **no** [read] | yes [memory] | n/a |
| Build needs | C compiler | C compiler | C compiler | C compiler | Zig or Clang + libwasmer | LLVM + a lifter |
| Speed | best (guard pages) | best | **2x memory, 4x calls** [run] | ~7 % slower than native (claim) | not measured | not measured |

## What it says

- **No other tool is a replacement for the translation to C with the autonomy kept and the features of today.** Wasmer gives up the autonomy; `w2c2` gives up features and the stack trap and gives the cleanest autonomy; `llc` has no reader of WebAssembly.
- The answer to the class of problems is **in `wasm2c` itself**: a chain of handlers (best speed, tried), or the signal-free switches (all features, slower, tried here for the cost). `w2c2` is a useful **reference** for the second, and **an option to test** as a backend for modules that need only the core.
- **To find out, if `w2c2` is to be taken seriously:** which of the features above it really lacks (translate the test modules of this repository with it and see what fails), what the stack does on an infinite recursion, its speed against `wasm2c` on Coremark and on the loops of the experiments here, and how its `trap` is written for an extension (a `longjmp` in the glue, as `WASM_RT_TRAP_HANDLER` does now).

## An own translator, and WABT being slow (a note, 2026-10-22)

The question was whether to give up `wasm2c` as the middle step and translate WebAssembly to C (or to machine code) ourselves, with a runtime of our own. What was concluded, as an opinion and not as a measurement:

- The runtime of `wasm2c` is the small part (about 1,500 lines of C) and is where the problems found are; it can be replaced or patched without touching the translator. The translator (`c-writer.cc`) is the large part: every opcode, SIMD, exceptions, tail calls, memory64, multi-memory, and the proposals that come (GC, stack switching). A wrong translation of one opcode is a wrong result, not a crash, and a wrong check of the bounds is a hole in the sandbox; the tests of the specification and the comparison with WABT are what is lost.
- The defects of the translator found so far are small and are repaired on the generated C or reported (the table in [wasm2c_limits.md](wasm2c_limits.md)); the reviews of WABT are slow, which means **the repairs have to live in wasmext and be exact and few** ([patch_policy.md](patch_policy.md)), not that a translator has to be written.
- A middle way if the repairs of the translator grow: patch `c-writer.cc` in a build of WABT that the `wabt-package` publishes. **Not done, and `.patch` files and a vendored copy of WABT are a decision not to do now** (the owner, 2026-10-22).
- Other roads were looked at above: LLVM (`llc`), Wasmer, `w2c2`, Cranelift/wasmtime (`.cwasm`): none keeps the autonomy and the features at once.
- **Reasons to go back to the question:** upstream stops following the proposals that matter, the patches to `c-writer.cc` grow to dozens, or a model of the code is wanted that a patch cannot give (a register of the base of the memory per instance, a different model of the traps). A small spike (a generator for a subset of the opcodes, tested against `wasm2c` and wasmtime on the same modules) would put numbers on the cost; not done.
