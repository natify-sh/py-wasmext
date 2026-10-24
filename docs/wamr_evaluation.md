# WAMR (WebAssembly Micro Runtime, `iwasm`): speed, size and WASI support (a reading and a measurement)

Status: **an evaluation, 2026-10-24; WAMR and wasm3 built and run here; nothing in the repository changed except this file (not committed).** How a fact is known: **[read]** read in the sources or pages named, **[run]** run here, **[estimate]** a judgement, **[memory]** from what I knew before the session and not checked. The question: how fast is `iwasm` against native C, against wasmext (the same `.wasm` as a natified CPython extension) and against wasm3; what does it weigh; and what WASI does it have out of the box. The other runtimes already looked at are in [backend_alternatives.md](backend_alternatives.md); the WAMR component-model branches are in [WASI_COMPONENTS.md](WASI_COMPONENTS.md).

## Summary

1. **Speed [run].** CoreMark (`examples/coremark/src/coremark/_core.wasm`), median of 5 runs, native gcc -O2 = 1.00: wasmext **0.95**, WAMR LLVM JIT **0.92**, WAMR AOT **0.86** (0.90 compiled for generic x86-64), WAMR fast JIT **0.51**, wasm3 **0.115**, WAMR fast interpreter **0.080**, WAMR classic interpreter **0.034**. The machine is noisy (the same binary varies up to 15 %), so wasmext, LLVM JIT, AOT and native are **not separable** here; the gaps to the interpreters (8x to 30x) are far outside the noise.
2. **wasm3 is 1.45 times faster than the WAMR fast interpreter and 3.4 times faster than the classic one** [run]. The WAMR wiki (2020) also has wasm3 ahead of the WAMR interpreters on CoreMark (1.32) [read].
3. **The `iwasm` command line cannot run this module [run]**: it imports `wiring.millis` and `wiring.print`, and the CLI has no way to give host functions. All WAMR numbers come from a small C host (`bench.c`) built with the WAMR runtime sources (and the same idea for wasm3). `wamrc` and the LLVM JIT work here after `apt install llvm-18-dev` (LLVM 18.1.3).
4. **Size [run].** `iwasm` with the product-mini defaults, stripped: 371 KB (classic), 451 KB (fast), 708 KB (fast JIT), 965 KB plus a 123 MB `libLLVM.so` (LLVM JIT), 268 KB (AOT only). The wasmext extension of the same module: 68.6 KB stripped (560 KB as built with `-g`). The `.aot` file is 47.8 KB for a 19.5 KB `.wasm`.
5. **WASI 0.1 [read, run]:** full `wasi_snapshot_preview1` (46 of 46 calls) **and** the older `wasi_unstable` name, plus about 80 non-standard `sock_*` calls and wasi-threads as a build option. A WASI command (`examples/products/.../hello.wasm`) ran in all five modes: `hello, wasi`, exit code 3. wasm3: only `wasi_snapshot_preview1`, 45 calls, no `sock_accept`, no `wasi_unstable` [run].
6. **WASI 0.2 [read, run]:** **not in upstream `main`.** `iwasm` 2.4.3 refuses a component (`unknown binary version`); the unbundled core modules of `examples/wasi2_unbundled` load but 21 and 74 `wasi:*` imports stay unlinked and there is no `_start`. The upstream branch `dev/cm_wasip2` exists (head 2026-03-20) but has **no component-model code in its tree**. The Airbus fork has `dev/cm_wasip2_complete` (not built here).
7. **WASI 0.3 [read]:** nothing in the tree.
8. **Configuration:** `iwasm` has `--dir`, `--map-dir`, `--env`, `--addr-pool`, `--allow-resolve` and arguments after the file; **no** read-only mounts, no stdio redirection, no clock or random override [read]. wasmext's `wasi=` has all of these.

## Machine and tools [run]

- 4 vCPU `Intel(R) Xeon(R) Processor @ 2.80GHz` (`wamrc` names the CPU cascadelake), 15 GB, Linux 6.18, a cloud VM that is shared (timing noise).
- gcc 13.3.0, clang 18.1.3, LLVM 18.1.3 (apt), cmake 3.28.3, Python 3.11.17 (the venv of the repository, used only to build and run the extension from a copy in `/tmp/claude-0/wamr/wx/`).
- WAMR `main` at `f5324c182fae0a6eaa14aa23ec886f0ba40d40e1` (2026-10-23), `core/version.h` = 2.4.3, from <https://github.com/bytecodealliance/wasm-micro-runtime>. Release builds (`-O3`).
- wasm3 0.9.2 (the `external/wasm3` of the pywasm3 checkout in the uv cache), `gcc -O3 -flto`.
- wasmext: the repository's build of `examples/coremark` (`setup.py build_ext`: `gcc -O2 -g -fPIC`, `-DWASMEXT_CHAIN=1 -DWASMEXT_STACK_LIMIT=1`, abi3).

## 1. Speed

### Method [run]

- The module has `ITERATIONS=0`: it picks the number of iterations from the clock it is given. A real clock would give each runtime another count, so every host gives the **same scripted clock** (the idea of `examples/coremark/tests/test_coremark.py`): the runs of 10 and 100 iterations last "100 ms", the run of 1,000 "1.5 s", the final one "15 s". The work is then fixed at **12,110 iterations (10 + 100 + 1,000 + 11,000)** in every runtime. The figure is `12110 / wall time of setup()` in iterations a second; **it is not the score CoreMark prints** (that one comes from the scripted clock and means nothing). Every run printed "Correct operation validated" (the CRCs `0xe714`, `0x1fd7`, `0x8e3a` are those of the test).
- 5 runs in one process, median given. Load and instantiation are not in the time.
- Native: the same CoreMark C files (EEMBC, cloned at the session) with the port of the repository (`port/core_portme.*`; the two imports defined in C; `ee_ptr_int` widened to 64 bits), `-DPERFORMANCE_RUN=1 -DITERATIONS=0 -DTOTAL_DATA_SIZE=2000`. The `.wasm` was made by `zig cc -O3`, so the compiler is not the same.
- Sources and logs: `/tmp/claude-0/wamr/host/bench.c` (WAMR), `bench_m3.c` (wasm3), `native/host.c`, `wx/coremark/bench_wx.py`.

### Table (iterations a second, **[run]**)

| Runtime / mode | Median | Min - max | Ratio to native (gcc -O2) | Ratio to wasmext |
| --- | ---: | ---: | ---: | ---: |
| native, gcc 13.3 -O2 | **20,750** | 19,003 - 22,248 | 1.00 | 1.05 |
| native, gcc -O3 | 19,900 | 18,170 - 22,418 | 0.96 | 1.01 |
| native, clang 18 -O2 | 19,423 | 18,208 - 20,698 | 0.94 | 0.98 |
| native, clang 18 -O3 | 20,706 | 20,617 - 20,839 | 1.00 | 1.05 |
| **wasmext** (wasm2c + gcc -O2, CPython extension) | **19,764** | 16,738 - 20,155 | 0.95 | 1.00 |
| WAMR **AOT** (`wamrc` defaults: host CPU, `-O3`) | 17,859 | 17,307 - 19,325 | 0.86 | 0.90 |
| WAMR AOT, `--target=x86_64 --cpu=x86-64` (generic) | 18,599 | 18,116 - 19,892 | 0.90 | 0.94 |
| WAMR AOT, `--bounds-checks=1` (software checks) | 15,287 | 13,847 - 15,704 | 0.74 | 0.77 |
| WAMR **LLVM JIT** (`WAMR_BUILD_JIT=1`) | 19,118 | 15,155 - 20,535 | 0.92 | 0.97 |
| WAMR **fast JIT** (`WAMR_BUILD_FAST_JIT=1`, SIMD off) | 10,599 | 9,684 - 11,148 | 0.51 | 0.54 |
| WAMR **fast interpreter** | 1,650 | 1,515 - 1,727 | 0.080 | 0.083 |
| WAMR **classic interpreter** | 710 | 685 - 723 | 0.034 | 0.036 |
| **wasm3** 0.9.2 | 2,385 | 2,311 - 2,472 | 0.115 | 0.121 |
| for comparison, WABT `wasm-interp` (from [backend_alternatives.md](backend_alternatives.md), another session and module build) | 131 | | 0.006 | 0.006 |

What it says:
- **AOT, LLVM JIT and wasmext are within about 15 % of native and within the noise of one another**; no order among them should be read from one session. The one clear AOT result is the software bounds check (`--bounds-checks=1`): about 15 % slower than the default of guard pages.
- AOT is how WAMR gets to native speed, and it needs `wamrc` (LLVM) at build time. The AOT file is tied to the CPU it was compiled for, unless `--cpu=x86-64` is given.
- **LLVM JIT**: loading the 19 KB module (compiling its functions) took **0.86 s** [run]; the first call was also slower than the later ones (a first trial: 0.30 s against 0.06 s for the same short run). The table is the median of 5 runs after loading.
- The fast JIT is about half of native; the fast interpreter is 12 times and the classic one 29 times slower than native. wasm3 is the faster interpreter.
- **Published [read]**: the WAMR wiki page [Performance](https://github.com/bytecodealliance/wasm-micro-runtime/wiki/Performance) (raw text: <https://raw.githubusercontent.com/wiki/bytecodealliance/wasm-micro-runtime/Performance.md>), test date **2020-09-01**, i7-7700, gcc 7.5 -O3: CoreMark wamr-aot / GCC(O3) = **0.79**; wamr-aot / wasm3 = **8.79**; wasm3 / wamr-interpreter = 1.32; fast / classic interpreters = **2.52**. Here (2026, another CPU, LLVM 18): AOT / native 0.86, AOT / wasm3 7.5, fast / classic 2.3. The shape agrees.

### What is not clean
- One shared VM; runs of one binary differ by up to 15 %; five runs give no confidence interval.
- The native binary is not from the compiler of the `.wasm`. The AOT variants differ in CPU features (the default uses the AVX-512 of this CPU).
- The fast JIT would not build with the default options of product-mini: **SIMD + FAST_JIT is an unsupported combination** (`build-scripts/unsupported_combination.cmake`); SIMD was switched off [run]. The module has no SIMD.
- The WAMR timings are the runtime as an embedded library in my host (libc-builtin on, WASI off). The `iwasm` programs of the size table were built separately with the product-mini defaults. The LLVM-JIT `iwasm` could not be linked by cmake as generated (the Debian LLVM exports list OpenMP and Polly files that do not exist); it was linked by hand against `libLLVM-18.so`.
- The time of `setup()` includes 8 clock reads and the print calls; negligible. For wasmext they are Python callables.

## 2. Size

### Measured **[run]** (bytes)

| What | Unstripped | Stripped | `size`: text / data / bss |
| --- | ---: | ---: | --- |
| `iwasm` classic interpreter (with AOT loader, libc-wasi, libc-builtin) | 421,728 | 370,632 | 349,898 / 11,928 / 720 |
| `iwasm` fast interpreter | 502,768 | 450,504 | 427,507 / 11,960 / 736 |
| `iwasm` fast JIT (SIMD off) | 797,048 | 708,056 | 681,786 / 14,952 / 928 |
| `iwasm` LLVM JIT (with AOT; links `libLLVM.so.18.1` dynamically) | 1,110,680 | 964,648 | 937,089 / 19,008 / 1,164 |
| `iwasm` AOT only (`WAMR_BUILD_INTERP=0`) | 316,128 | 268,232 | 248,614 / 9,864 / 720 |
| `libLLVM.so.18.1` (needed by the LLVM JIT and `wamrc`) | 123,215,144 | | |
| `wamrc` | 1,118,072 | | |
| `libiwasm.a` (static): classic / fast / fast JIT / LLVM JIT / AOT only | 1,111,778 / 1,234,186 / 1,934,378 / 2,194,918 / 916,292 | | |
| wasm3 CLI (with its WASI) | 638,880 | 527,152 | 504,267 / 15,884 / 80,088 |
| wasm3 core with my host (no WASI, no CLI) | 358,712 | 305,440 | |
| wasmext extension `coremark/_core.abi3.so` (as built, `-g`) | 560,216 | **68,600** | 56,246 / 2,288 / 920 |
| `_core.wasm` | 19,463 | | |
| `core.aot`: host CPU / generic x86-64 / bounds-checks=1 | 47,820 / 36,816 / 45,456 | | |

`libiwasm` as a shared library was not built (product-mini makes `iwasm` and the static `libiwasm.a`). The `iwasm` numbers include the command line, libc-wasi and the other libraries that product-mini turns on, so they are larger than the core runtime.

### Published **[read]**
- README of WAMR, "Key features" (text size from bloaty of the core vmlib on cortex-m4f): **~58.9 K fast interpreter, ~56.3 K classic interpreter, ~29.4 K AOT runtime, ~21.4 K libc-wasi, ~3.7 K libc-builtin**. The "about 85 KB for the runtime and 50 KB AOT-only" of the brief are **not in the README of this commit** (an older one may have had them; **[memory]**, not checked).
- Wiki Performance page, CoreMark under valgrind massif, **peak memory**: classic 365 KB, fast 485 KB, wasm3 514 KB (2020). CoreMark at -Os: native 23,120 B, wasm 10,457 B, iwasm AOT 17,348 B (ratio 1.7). Here (zig -O3): wasm 19,463 B, AOT 47,820 B (ratio 2.5).

Reading: a stripped `iwasm` is 4 to 14 times the 68.6 KB of the wasmext extension, which has the module's code and a small runtime but no loader or compiler (the translation was done at build time); the LLVM-JIT `iwasm` needs a 123 MB LLVM library. [estimate] On a PC the size is not a deciding point; it matters for the embedded targets WAMR is made for.

## 3. Built-in WASI

| | iwasm (upstream `main`, 2.4.3) | wasm3 0.9.2 | wasmext |
| --- | --- | --- | --- |
| **WASI 0.1, `wasi_snapshot_preview1`** | **Full: all 46 functions of the specification** are registered in `core/iwasm/libraries/libc-wasi/libc_wasi_wrapper.c` (args, environ, clock, fd_*, path_*, poll_oneoff, proc_exit/raise, random_get, sched_yield, sock_accept/recv/send/shutdown) **[read]**. The sandbox is the "sandboxed-system-primitives" code (`posix.c`) with rights and preopened directories **[read]**. `hello.wasm` of `examples/products` printed `hello, wasi`, exit 3, in classic, fast, fast JIT, LLVM JIT and (after `wamrc`) AOT **[run]** | `wasi_snapshot_preview1` only, 45 functions, **no `sock_accept`** (`m3_api_wasi.c`) **[read]**; `hello.wasm` ran, exit 3 **[run]** | built in (fusedwasi) |
| **`wasi_unstable`** (older name) | **Yes**: `wasm_native.c` registers the same table under both names **[read]**; a copy of `hello.wasm` with the imports renamed ran, exit 3 **[run]** | **No**: `missing imported function ('wasi_unstable.fd_write')` **[run]** | |
| **Sockets** | A large non-standard set under `wasi_snapshot_preview1` (`sock_open`, `sock_bind`, `sock_listen`, `sock_connect`, `sock_send_to`, `sock_recv_from`, `sock_addr_resolve` and about 40 get/set options) **[read]**, see `doc/socket_api.md`; they need `--addr-pool` and `--allow-resolve`. The wrapper's `sock_close` returns `ENOSYS` (`fd_close` is the way) **[read]**. Not run. | no | |
| **Threads** | `wasi-threads` (`thread_spawn`, `lib-wasi-threads`) and the pthread library, as build options (`WAMR_BUILD_WASI_THREADS`, `WAMR_BUILD_LIB_PTHREAD`), **not in the default build** **[read]**. Not run. | no | see [threads_wasm2c_wasix_concept.md](threads_wasm2c_wasix_concept.md) |
| **WASI 0.2 / component model** | **No, in main.** `iwasm` on a component (a minimal one from `wasm-tools parse`): `WASM module load failed: unknown binary version` (fast, classic) and `magic header not detected` (AOT only) **[run]**. The unbundled core modules of `examples/wasi2_unbundled`: they load, but **every `wasi:...@0.2.12` import is "failed to link import function"** (21 in `_hello.wasm`, 74 in `_sock.wasm`) and the run ends with `lookup the entry point symbol ... failed`, exit 1 **[run]**. No `wasi:cli`, `wasi:io`, `wasi:filesystem`, `wasi:sockets` or `wasi:http` in `core/iwasm/libraries` (`libc-wasi`, `libc-uvwasi`, `lib-socket`, `wasi-nn`, ...) **[read]**. The branch `dev/cm_wasip2` of the upstream repository exists (head `fcec30e`, 2026-03-20, "Fix/branch hint parse issue (#4878)"); its tree has **no `component-model` directory and no `libc-wasi-p2`** **[run: cloned and listed]**. The Airbus fork has the branches `dev/cm_wasip2` (`70a7bbb`) and `dev/cm_wasip2_complete` (`2815b69`) **[read: git ls-remote]**; what is in them (`libc-wasi-p2`, component parser, canonical ABI; no async, no wasi:http) is in [WASI_COMPONENTS.md](WASI_COMPONENTS.md), read there and not rebuilt here | no (core modules only) | a Python host for 0.2 (`examples/wasi2_unbundled`) on the core module taken out of the component |
| **WASI 0.3 (async, streams, futures)** | **Nothing found** in the tree (`README.md`, `doc/roadmap.md`, `core/iwasm`) **[read]**. The issues and PRs could not be read (see below) | no | no |

### Configuration of a WASI 0.1 program, against wasmext's `wasi=`

| wasmext `wasi=` key | iwasm command line (`iwasm --help`) **[read, run]** | embedding API (`wasm_export.h`) **[read]** |
| --- | --- | --- |
| `args` | the arguments after the file name | `wasm_runtime_set_wasi_args_ex(module, dir_list, ..., env, ..., argv, argc, stdinfd, stdoutfd, stderrfd)` |
| `env` | `--env="key=value"` (repeatable) | the same call |
| `preopens` | `--dir=<dir>` (the host path as the guest path), `--map-dir=<guest::host>` | `dir_list`, `map_dir_list` |
| `readonly` | **nothing** | not in the call |
| `stdin`, `stdout`, `stderr` | **nothing** (the process's own 0, 1, 2) | the embedder can give the three file descriptors |
| `clock`, `random` | **nothing** (host clock, host `random_get`) | not found |
| (network) | `--addr-pool=<addr/mask>`, `--allow-resolve=<domain>` | `wasm_runtime_set_wasi_addr_pool`, `..._ns_lookup_pool` |

The CLI is a thin configuration (args, env, directories, network allow-lists). Of the finer keys of wasmext, WAMR has the streams at the level of the embedding API only, and no read-only mounts, clock or random override.

## What is not known

- **Whether the component model reached upstream `main` or a release after 2026-03-20**: the `main` checked here (2026-10-23) has none of it in the tree, but the state of the PRs and issues named in WASI_COMPONENTS.md (#4872, #4889, #2126) could not be read, because the GitHub API was not opened for this repository in this session. The Airbus fork was not built.
- **WASI 0.3 in WAMR**: no source or issue was read; absence from the tree is the only evidence.
- WASI 0.1 was run only for `fd_write` and `proc_exit`; files, the sandbox and sockets were read, not run. `wasi-threads` was not built.
- **Speed**: one shared machine, ~15 % noise; the order among AOT, LLVM JIT, wasmext and native is not established. Not measured: start-up time (only the LLVM JIT's 0.86 s to load), memory use, workloads other than CoreMark, AOT with PGO or other `--opt-level`, other CPUs, SIMD, threads.
- The 85 KB / 50 KB figures of the brief: not found in the current README.
- Work files are in `/tmp/claude-0/wamr/` (builds, hosts, logs), outside the repository.
