# A check of the stack pointer instead of a counter of the depth (or a guard page)

How a wasm2c module learns that the native stack is about to run out. Three ways, one module (`ft.wat`: a recursion through a table that the C compiler cannot flatten, `fib` that calls itself through the table, ~7 million calls for `fib(32)`):

| Way | What the code does | Needs |
| --- | --- | --- |
| **guard** (the default of wasm2c) | nothing in the functions; the guard page of the stack faults, a handler on an alternate stack makes the trap | a handler of SIGSEGV, `sigaltstack` in every thread |
| **depth** (`WASM_RT_STACK_DEPTH_COUNT`) | `++depth` in each prologue, `--depth` in each epilogue, a limit of **500 calls** | nothing else; a thread-local counter |
| **sp** (this experiment) | the prologue compares the address of the frame with a limit kept per thread (`wasmext_stack_limit`, the lowest address still safe); no epilogue | the limit set once per thread (from `pthread_getattr_np`) |

`sp` is a patch of the generated C, of the kind in [../../patch_policy.md](../../patch_policy.md): `build.sh` replaces the empty `FUNC_PROLOGUE` of the branch where neither option is on with `if ((uintptr_t)__builtin_frame_address(0) < wasmext_stack_limit) TRAP(EXHAUSTION);`, and builds the runtime with `WASM_RT_NONCONFORMING_UNCHECKED_STACK_EXHAUSTION=1` (the runtime accepts that no option is chosen). Nothing in WABT is changed.

**[run]** 2026-10-22, one cloud VM, gcc 13.3 `-O2`, `fib(32)`, best of 7 calls, 5 runs of each, the range of the 5:

| Build | executable (ms) | shared library (ms), as an extension is |
| --- | ---: | ---: |
| guard | 14.2-20.0 | 15.6-20.9 (16.0-16.7 in the later run) |
| depth | 28.6-30.8 (**2x**) | 52.2-65.2 (**3.3x**) |
| sp | 18.5-21.2 (1.3x) | 29.3-34.7 with the default TLS model, `global-dynamic` (**1.8x**) |
| sp, `-mtls-dialect=gnu2` (TLS descriptors) | | 22.6-23.7 (1.4x); glibc and aarch64 only, not every libc loads it |
| sp, `-ftls-model=initial-exec` | | 15.9-18.8 (**1.0x**), **but it cannot be used, see below** |

The thread-local limit is the cost: in a shared library the default model reaches it through `__tls_get_addr` (a call) in each function. With `initial-exec` it is one load from the thread pointer. The counter of `depth` pays the same for its variable, and pays the epilogue besides.

**`initial-exec` does not survive the real thing.** A shared library with one `initial-exec` access needs the *whole thread-local block of the module* in the static TLS of the process (the limit, `g_wasm_rt_jmp_buf` and the rest, a few hundred bytes), and glibc keeps a surplus of about 1.6 KiB for libraries opened by `dlopen`. In the suite of wasmext, which loads hundreds of modules in one process, the first dozens loaded and the next ones failed with `ImportError: cannot allocate memory in static TLS block`. A few plugins would work, many would not, and the failure is at the import. So the integrated build uses the default model and pays the 1.8x on a program that is all calls; the other costs of the three ways are in the table above.

Behaviour (`./guard`, `./depth`, `./sp`; recursion until the stack runs out, in the main thread and in a thread with a 512 KiB stack):

| | main thread | 512 KiB thread |
| --- | --- | --- |
| guard | trap "Call stack exhausted", 261,649 frames | **trap "Out-of-bounds access"** (wrong code), 16,229 frames |
| depth | trap "Call stack exhausted" after **499** frames | the same, 499 |
| sp | trap "Call stack exhausted", 257,535 frames | trap "Call stack exhausted", 12,131 frames |

So:
- **sp is nearly the speed of the guard page and far better than the counter**, and its limit is in bytes, not in calls: the counter allows 499 nested calls however small the frames and however large the stack; a program with a recursion deeper than that traps under `depth` and runs under `guard` and `sp`.
- **The stock handler classifies a stack overflow in a thread other than the main one as an out-of-bounds access** (`os_signal_handler` takes `si_code == SEGV_ACCERR` for memory; the guard page of a thread stack is `ACCERR`, the growing main stack is `MAPERR`). A wrong trap code, not a crash; to be reported (not yet).
- With `sp` **the alternate stack is not needed for the stack**: no `sigaltstack` per thread to set up and give back (the thread-end capsule of the Python layer, the "alternate stack was modified unexpectedly" of several modules in one thread). What is left of the handler is the memory guard pages, which a handler on the ordinary stack serves.

Risks and what is not done:
- **The margin** (128 KiB here) must cover what a host function can use when the limit is reached (an import that calls Python): `guard` has the same problem and no margin at all; a frame bigger than the margin could skip the check (a wasm2c frame is small; not bounded by the translator).
- **TLS**: `initial-exec` in a library opened by `dlopen` takes static TLS (a few bytes per module; glibc keeps a surplus, but it is finite). macOS reaches thread-locals through a function (`tlv_get_addr`), Windows through the TLS directory: not measured. Emscripten has no such stack at all.
- The limit of a thread is set at its first call (`pthread_getattr_np` on Linux; macOS `pthread_get_stackaddr_np`/`pthread_get_stacksize_np`; Windows `GetCurrentThreadStackLimits`): only Linux is written.
- Not run on a real extension: the Python layer, tail calls (`return_call` is a loop in wasm2c, no stack), exceptions, `--share-tables` are untouched here.

`./build.sh BIN RT` builds all (needs `wabt-package`'s `bin/` and the `wasm2c/` runtime); `./so_*` are the shared-library variants.

## CoreMark in the real extension, against native C

**[run]** 2026-10-22, the same VM, `examples/coremark/src/coremark/_core.wasm` made into an extension by `wasmext natify -i -b` (default flags of the interpreter), once with `WASMEXT_STACK_CHECK=guard` and once with the default (`limit`); the native reference is the same CoreMark of EEMBC (`PORT_DIR=linux`, `-O3 -DPERFORMANCE_RUN=1 -DITERATIONS=0 -DTOTAL_DATA_SIZE=2000`), built with gcc 13.3. Iterations a second, the runs interleaved, 5 runs each (3 for the last row):

| | iterations/s (runs) | mean | of native gcc |
| --- | --- | ---: | ---: |
| native C, gcc -O3 | 21957, 21139, 21733, 21935, 21758 | 21,704 | 100% |
| native C, clang -O3 (the compiler of the wasm) | 17498, 18382 | 17,940 | 83% |
| extension, **guard page** (`WASMEXT_STACK_CHECK=guard`) | 21346, 20287, 21281, 22400, 21499 | 21,363 | **98%** |
| extension, **stack-pointer check**, default TLS (`limit`) | 20031, 19903, 20320, 18777, 19218 | 19,650 | **91%** (8% under the guard page) |
| extension, stack-pointer check, `-mtls-dialect=gnu2`, `CFLAGS=-O2` | 20985, 21011, 19977 | 20,658 | 95% |

The runs of one build differ by up to 5% (a cloud VM), so the 8% of the check is about the size of the noise to two sigma and not far outside it; the direction is the same in every pair. Read it as: **the check costs a few percent on a program that is not all calls (CoreMark), and the guard page keeps the "about 95% of native" of the README; the check with the default thread-local model is below that figure.** `gnu2` (TLS descriptors) brings it back to 95% but a `manylinux2014` (glibc 2.17) loader may not support them on x86-64, so it is not used. The decision of the default (guard page, or the check) is the author's.
