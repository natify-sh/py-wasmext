# WAMR (WebAssembly Micro Runtime, `iwasm`): speed, size and WASI support (a reading and a measurement)

Status: **an evaluation, 2026-10-24; WAMR and wasm3 built and run here; nothing in the repository changed except this file (not committed).** How a fact is known: **[read]** read in the sources or pages named, **[run]** run here, **[estimate]** a judgement, **[memory]** from what I knew before the session and not checked. The question: how fast is `iwasm` against native C, against wasmext (the same `.wasm` as a natified CPython extension) and against wasm3; what does it weigh; and what WASI does it have out of the box. The other runtimes already looked at are in [backend_alternatives.md](backend_alternatives.md); the WAMR component-model branches are in [WASI_COMPONENTS.md](WASI_COMPONENTS.md).

## Summary

1. **Speed [run].** CoreMark (`examples/coremark/src/coremark/_core.wasm`), native gcc -O2 = 1.00. Second pass, all programs interleaved in 3 rounds (the one in the table): wasmext **0.86**, WAMR LLVM JIT **0.87**, WAMR AOT **0.95** (0.98 compiled for generic x86-64), WAMR fast JIT **0.55**, wasm3 **0.116**, WAMR fast interpreter **0.10**, WAMR classic interpreter **0.040**. The first pass (one program after another) gave wasmext 0.95, LLVM JIT 0.92, AOT 0.86, fast JIT 0.51, wasm3 0.115, fast 0.080, classic 0.034. The machine changed speed by about 1.5 times between the two passes (absolute figures 31,400 against 20,750 for native), and runs vary by 10 to 15 %: wasmext, LLVM JIT, AOT and native are **not separable**, and the order among them flips between passes. The gaps to the interpreters (7x to 25x) are far outside the noise.
2. **wasm3 is 1.2 to 1.45 times faster than the WAMR fast interpreter and 2.9 to 3.4 times faster than the classic one** [run] (two passes). The WAMR wiki (2020) also has wasm3 ahead of the WAMR interpreters on CoreMark (1.32) [read].
3. **The `iwasm` command line cannot run this module [run]**: it imports `wiring.millis` and `wiring.print`, and the CLI has no way to give host functions. All WAMR numbers come from a small C host (`bench.c`) built with the WAMR runtime sources (and the same idea for wasm3). `wamrc` and the LLVM JIT work here after `apt install llvm-18-dev` (LLVM 18.1.3).
4. **Size [run].** `iwasm` with the product-mini defaults, stripped: 371 KB (classic), 451 KB (fast), 708 KB (fast JIT), 965 KB plus a 123 MB `libLLVM.so` (LLVM JIT), 268 KB (AOT only). The wasmext extension of the same module: 68.6 KB stripped (560 KB as built with `-g`). The `.aot` file is 47.8 KB for a 19.5 KB `.wasm`.
5. **WASI 0.1 [read, run]:** full `wasi_snapshot_preview1` (46 of 46 calls) **and** the older `wasi_unstable` name, plus about 80 non-standard `sock_*` calls and wasi-threads as a build option. A WASI command (`examples/products/.../hello.wasm`) ran in all five modes: `hello, wasi`, exit code 3. wasm3: only `wasi_snapshot_preview1`, 45 calls, no `sock_accept`, no `wasi_unstable` [run].
6. **WASI 0.2 [read, run]:** **not in upstream `main`.** `iwasm` 2.4.3 refuses a component (`unknown binary version`); the unbundled core modules of `examples/wasi2_unbundled` load but 21 and 74 `wasi:*` imports stay unlinked and there is no `_start`. The upstream branch `dev/cm_wasip2` exists (head 2026-03-20) but has **no component-model code in its tree**. The Airbus fork has `dev/cm_wasip2_complete` (not built here).
7. **WASI 0.3 [read]:** nothing in the tree.
8. **Configuration:** `iwasm` has `--dir`, `--map-dir`, `--env`, `--addr-pool`, `--allow-resolve` and arguments after the file; **no** read-only mounts, no stdio redirection, no clock or random override [read]. wasmext's `wasi=` has all of these.
9. **Follow-up (section 4):** an `.aot` needs the WAMR loader and runtime (210-355 KB stripped here); `wamrc --format=object` gives a 49 KB object with only two undefined symbols but **no data, no tables, and a dependency on the private instance layout**, so it cannot run alone; `wamrc` needs LLVM on the build machine; WAMR does not serve Pyodide, ppc64le or s390x; AOT has tail calls, v128 (x86-64/aarch64), extended const and memory64 (runtime options) but **no exceptions and no multi-memory**. WAMR is not a replacement for wasm2c under the autonomy criteria [estimate].

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

### Table (iterations a second, **[run]**, second pass, interleaved)

Programs were run in turn, 3 rounds (`/tmp/claude-0/wamr/rr.sh`; log `rr.out`): per round 5 runs for native and wasm3, 3 for wasmext, AOT, fast JIT, fast and classic, 4 for the LLVM JIT; the median is over all the runs of a program (n in the table).

| Runtime / mode | n | Median | Min - max | Ratio to native (gcc -O2) | Ratio to wasmext |
| --- | ---: | ---: | ---: | ---: | ---: |
| native, gcc 13.3 -O2 | 15 | **31,410** | 30,543 - 33,320 | 1.00 | 1.16 |
| native, clang 18 -O3 | 15 | 28,190 | 26,617 - 30,931 | 0.90 | 1.04 |
| **wasmext** (wasm2c + gcc -O2, CPython extension) | 9 | **27,081** | 26,298 - 29,515 | 0.86 | 1.00 |
| WAMR **AOT** (`wamrc` defaults: host CPU, `-O3`) | 9 | 29,820 | 28,267 - 32,304 | 0.95 | 1.10 |
| WAMR AOT, `--target=x86_64 --cpu=x86-64` (generic) | 9 | 30,794 | 30,119 - 33,478 | 0.98 | 1.14 |
| WAMR **LLVM JIT** (`WAMR_BUILD_JIT=1`) | 12 | 27,327 | 19,802 - 31,443 | 0.87 | 1.01 |
| WAMR **fast JIT** (`WAMR_BUILD_FAST_JIT=1`, SIMD off) | 9 | 17,231 | 15,859 - 19,398 | 0.55 | 0.64 |
| WAMR **fast interpreter** | 9 | 3,158 | 2,926 - 3,395 | 0.10 | 0.117 |
| WAMR **classic interpreter** | 9 | 1,256 | 1,199 - 1,330 | 0.040 | 0.046 |
| **wasm3** 0.9.2 | 15 | 3,653 | 3,538 - 4,030 | 0.116 | 0.135 |

First pass (one program after another, 5 runs each, the machine slower at that time; medians): native gcc -O2 20,750; gcc -O3 19,900; clang -O2 19,423; clang -O3 20,706; wasmext 19,764; AOT 17,859 (generic 18,599; `--bounds-checks=1` 15,287); LLVM JIT 19,118; fast JIT 10,599; fast interpreter 1,650; classic 710; wasm3 2,385. For comparison, WABT `wasm-interp` from [backend_alternatives.md](backend_alternatives.md) (another session and module build): 131.

What it says:
- **AOT, LLVM JIT and wasmext are within about 15 % of native and within the noise of one another**; the order flipped between the two passes. The one clear AOT result is the software bounds check (`--bounds-checks=1`, first pass only): about 15 % slower than the default of guard pages.
- AOT is how WAMR gets to native speed, and it needs `wamrc` (LLVM) at build time. The AOT file is tied to the CPU it was compiled for, unless `--cpu=x86-64` is given.
- **LLVM JIT**: loading the 19 KB module (compiling its functions) took **0.86 s** [run]; the first call was also slower than the later ones (a first trial: 0.30 s against 0.06 s for the same short run). The table is the median of 5 runs after loading.
- The fast JIT is about half of native; the fast interpreter is 10 times and the classic one 25 times slower than native. wasm3 is the faster interpreter (1.16x the WAMR fast one in the second pass, 1.45x in the first).
- **Published [read]**: the WAMR wiki page [Performance](https://github.com/bytecodealliance/wasm-micro-runtime/wiki/Performance) (raw text: <https://raw.githubusercontent.com/wiki/bytecodealliance/wasm-micro-runtime/Performance.md>), test date **2020-09-01**, i7-7700, gcc 7.5 -O3: CoreMark wamr-aot / GCC(O3) = **0.79**; wamr-aot / wasm3 = **8.79**; wasm3 / wamr-interpreter = 1.32; fast / classic interpreters = **2.52**. Here (2026, another CPU, LLVM 18): AOT / native 0.86 and 0.95 (two passes), AOT / wasm3 7.5 and 8.2, fast / classic 2.3 and 2.5. The shape agrees.

### What is not clean
- One shared VM; runs of one binary differ by up to 15 %, and the speed of the machine changed by about 1.5 times between the two passes; five runs give no confidence interval.
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

## 4. Follow-up: AOT without the runtime, platforms, and WAMR in place of wasm2c

Questions of the owner after the first report. Same tags. Judgements are marked **[estimate]**. Work files: `/tmp/claude-0/wamr/obj/` (object files, link tests), `/tmp/claude-0/wamr/feat/` (one-feature modules), `/tmp/claude-0/wamr/build/bench-aotmin/` (a smaller runtime).

### 4.1 Does an AOT module need the WAMR runtime at run time, or can it be embedded?

**(a) A `.aot` file loaded by `iwasm` / `libiwasm`: it needs the runtime, and the runtime is the loader plus the instance code.** A `.aot` is a data file (header, type tables, memory/table/global descriptors, data segments, import and export tables, the machine code and its relocations) that `aot_loader.c` parses and `aot_runtime.c` instantiates **[read]**. Linking the object of the CoreMark module against the AOT-only `libiwasm.a` pulled in these 38 members of the archive **[run, from the linker map]**: `aot_loader`, `aot_runtime`, `aot_intrinsic`, `aot_reloc_x86_64`, `wasm_runtime_common`, `wasm_exec_env`, `wasm_memory`, `wasm_native` (the registry of native functions), `mem_alloc` and `ems_*` (the allocator), `libc_builtin_wrapper` and `libc_wasi_wrapper` with the sandbox (`posix.c`, `blocking_op`, `random`, `str`), the platform layer (`posix_thread`, `posix_file`, `posix_socket`, `posix_memmap`, `posix_clock`, `posix_time`, `posix_malloc`, ...), `wasm_c_api`, `runtime_timer`, `bh_*` utilities. The **thread manager is not in it** (not enabled by default) **[run]**. Sizes, stripped **[run]**: the `iwasm` AOT-only program 268,232 B; my host with the AOT-only runtime (libc-wasi off, libc-builtin on) 228,392 B; the same with libc-builtin, bulk memory and reference types also off 210,216 B (it still ran the module: 12,110 iterations validated). The `.aot` itself is 47,820 B (36,816 B generic x86-64). So **a module is the `.aot` data plus 210 to 270 KB of loader and runtime**, against the 68.6 KB stripped extension of wasmext (module code and a small runtime in one file).
Is that "an engine in every artifact"? **Yes [estimate]**: the module is not self-contained code, it is data for a loader that parses it at run time, allocates the instance, resolves imports and keeps the process-wide state of section 4.3. It is the same shape as the embedded runtime of `wasmer create-exe` in [backend_alternatives.md](backend_alternatives.md) section 1 (smaller: no compiler inside), and it is the thing criterion 1 of that page leaves out.

**(b) `wamrc --format=object` / `llvmir-unopt` / `llvmir-opt`: the object links, but it cannot run without the runtime.** Tried on the CoreMark module **[run]**:
- `wamrc --format=object` gives an ELF object of 49,040 B (35,875 B text with `--bounds-checks=1`; 40,816 B with `--xip`) with 29 functions `aot_func#N` (the name contains `#`) and **only two undefined symbols: `aot_invoke_native` and `aot_set_exception_with_id`**. `--format=llvmir-opt` gives 645 KB of LLVM IR text (not compiled further).
- Linked with a main and two stubs for those symbols (`gcc -no-pie`; a PIE link fails on `R_X86_64_32S` against `.rodata`): 53,632 B (51,136 B stripped). With `libiwasm.a` instead of the stubs it links, and that is the 38 members above: **355,528 B stripped** (a program that does nothing).
- **But the object is not a module.** It has no data segments (the string `Correct operation validated` is in the `.aot` and not in the `.o`: 1 and 0 occurrences), no memory, table, global or import descriptors. Every function takes `exec_env` as its first argument and reads the instance through fixed offsets (the first function starts `mov 0x10(%rdi),%rax; mov 0x178(%rax),%r14`: `exec_env->module_inst`, then a field of the AOT module instance that holds the memory base) **[run, disassembly]**. The layout is that of `AOTModuleInstance` in `aot_runtime.h`, and calls to other functions, to imports and to `call_indirect` go through tables that `aot_runtime.c` builds when it instantiates a `.aot` **[read, estimate for the details]**.
- The repository itself uses the object format only for **debugging** the AOT code in gdb (`test-tools/dynamic-aot-debug/README.md`) **[read]**.
- So the answer is: the object can be linked into an executable or a shared object of ours, **but what runs is only the code; to make it run one must supply an `AOTModuleInstance` of the right version, with the memory, tables, globals, data segments, function pointer tables and the native-symbol table built by hand, or keep the `.aot` file and the loader**. Either is the engine of (a), or a private reimplementation of `aot_runtime.c` tied to one version of WAMR **[estimate]**. What the object calls (memory growth, traps, imports) is also not just the two symbols: the rest goes through the instance and `exec_env` (function pointers filled by the runtime).

**(c) XIP and "AOT as a shared library".** `--xip` (= `--enable-indirect-mode --disable-llvm-intrinsics`) makes an `.aot` with almost no relocations, so that the code can run **in place from flash or ROM**; it still needs the loader and runtime, it only avoids copying and patching the code **[read, `doc/xip.md`]**; the object is 17 % smaller here (40,816 against 49,040 B, **[run]**). A shared library of the AOT output (one `.so` loaded with `dlopen`) **does not exist in the tree**: the AOT loader reads ELF or COFF *object* data inside the `.aot` and does its own relocation, and a search for `dlopen`/shared library in `core/iwasm/aot` and the docs found nothing **[read]**. (`--native-lib` is something else: it registers shared libraries that give the module's *imports*.)

### 4.2 Platforms and architectures

| | WAMR | wasm2c output + a C compiler (wasmext today, README) |
| --- | --- | --- |
| **OS** | Linux, Linux SGX, macOS, Android, Windows (MinGW, MSVC), Zephyr, AliOS-Things, VxWorks, NuttX, RT-Thread, ESP-IDF (README of WAMR); directories of ports also for FreeBSD, iOS, Cosmopolitan, RIOT, EGO **[read]**. **No Emscripten or WASI-hosted port** (`core/shared/platform` has none; the "emscripten" matches in the docs are about compiling wasm *apps*) **[read]** | Linux x86-64 glibc and musl, ARM64; Windows x64, ARM64 (x86 in CI); macOS Apple Silicon and Intel; **Pyodide**; Android x86-64 (run) and arm64-v8a (built); CI also armv7l, i686, ppc64le, riscv64 on Linux **[read, README of wasmext]** |
| **CPU, interpreters** | the C interpreters need a port to the platform; `WAMR_BUILD_TARGET` values: X86_64, X86_32, AARCH64, ARM, THUMB, MIPS, XTENSA, RISCV64, RISCV32 (ARC in the README list) **[read]** | any CPU the C compiler has |
| **CPU, AOT** | relocation code exists for x86-64, x86-32, aarch64, arm, thumb, riscv, mips, xtensa, arc (`core/iwasm/aot/arch/`) **[read]**; `wamrc --target=help` lists xtensa, x86_64, i386, riscv64/32, mips/mipsel, thumb*, arm*, aarch64* **and no ppc64 or s390x** **[run]** | any |
| **CPU, JIT** | LLVM JIT on the same targets as the LLVM backend of the build; fast JIT: x86-64 only (and SIMD off, section 1) **[read, estimate]** | n/a |
| **32-bit** | x86-32, arm, thumb, riscv32, mips, xtensa; software bounds checks (no hardware trap on 32-bit) **[read]** | i686, armv7l (CI) |
| **Big-endian** | the AOT loader knows big-endian ELF (32 and 64) and MIPS BE **[read]**; **s390x is not a target of `wamrc`** **[run]** | s390x built; limits in the README (no `memoryview` of a memory, no `v128` in a signature) |
| **Windows** | MSVC and MinGW builds of `iwasm` **[read]**; `wamrc --target=x86_64-pc-windows-msvc` and `-gnu` make a file (COFF) **[run]**; Windows ARM64 and x86 are not named in the README: **not checked** | x64, ARM64, x86 |
| **macOS arm64** | listed as supported platform **[read]**; `wamrc --target=aarch64-apple-darwin` from Linux fails (`invalid llvm binary bin_type`: the emitter knows ELF and COFF, not Mach-O) **[run]**; how the native wamrc on a Mac avoids that: **not checked** | Apple Silicon and Intel |
| **Android** | yes (`product-mini/platforms/android`); `wamrc --target=aarch64-linux-android` makes a file **[run]** | x86-64, arm64-v8a |
| **musl** | `x86_64-linux-musl` makes a file **[run]**; the runtime on musl: not built here | musllinux |
| **Pyodide / Emscripten / WASI-hosted** | **not served**: no platform port, no wasm32 target in `wamrc` **[read, run]** | Pyodide: tested |

**Which targets of wasmext could WAMR not serve [estimate, from the table]:** Pyodide (and any Emscripten/WASI host), ppc64le, s390x; macOS arm64 and Windows ARM64/x86 are claimed or likely but were **not confirmed** here; the rest (Linux x86-64/aarch64/i686/armv7/riscv64, Android, musl) have a `wamrc` target. The interpreters could serve wherever the platform port exists, at 1/10 to 1/25 of native speed (section 1), which is no replacement for compiled C.

**Build requirements.** **`wamrc` needs LLVM on the build machine [run]**: here `apt install llvm-18-dev` (the installed `/usr/lib/llvm-18` is 970 MB; `libLLVM.so` 123 MB), cmake, and building `wamrc` (1.26 MB binary, built in a few minutes). The user of a wasmext sdist today needs only a C compiler and the `wabt-package` wheel (README of wasmext). Ways around it **[estimate]**: ship `wamrc` as a wheel like `wabt-package` (built for each build platform: LLVM statically linked, big), or do the translation in CI and ship the `.aot` for each target (the sdist would no longer build from the `.wasm` with a C compiler). **Cross-compilation**: one `wamrc` run can make the `.aot` of any target in its list (`--target=<triple>`, tested above for six triples) and so replaces the "compile the C on the target" of `cibuildwheel` by "compile on any host, link the runtime on the target"; but the runtime (C, ~210-270 KB) still has to be compiled for each target, with a C compiler, and the `.aot` is bound to the CPU features it was built for (`--cpu`, default the host's: the AVX-512 of this machine) **[run, estimate]**. wasm2c ships portable C and leaves both to the target's compiler. Time of the translation: `wamrc` 0.64 s for the CoreMark module **[run]** (the compile of the C of wasm2c was not timed here).

### 4.3 Could WAMR replace wasm2c in the path of wasmext?

The path today: `.wasm` -> `wasm2c` -> C (336 KB for CoreMark) + runtime C + glue C -> compiler -> an extension that is complete, owns its state and needs no engine (criteria 1-5 of [backend_alternatives.md](backend_alternatives.md)). With WAMR the path would be: `.wasm` -> `wamrc` -> `.aot` (or object) -> an extension that embeds the `.aot` bytes and links the WAMR runtime (AOT-only, static, symbols hidden). Judgement of each point:

| Point | WAMR AOT | wasm2c today | Simpler or harder with WAMR [estimate] |
| --- | --- | --- | --- |
| **Autonomy** (criterion 1) | an engine (loader + runtime, 210-355 KB) in every artifact, `.aot` as data (4.1) | complete module, runtime of about 1,500 lines | harder, and against the choice made in [WASI_COMPONENTS.md](WASI_COMPONENTS.md) |
| **Process-wide state** (criterion 2) | With the hardware bounds check (the default on 64-bit Linux/macOS/Windows) WAMR installs `SIGSEGV` and `SIGBUS` handlers with `sigaltstack` **per thread** (`os_thread_signal_init`, `posix_thread.c`) and **saves the previous action, to which it forwards** a fault that is not its own; the handler finds the instance through a thread-local `exec_env_tls` **[read]**. So it has the same class of state as wasm2c, but built to **chain**: two copies each with their own `exec_env_tls` would forward to one another **[estimate; not tested]**, which is the fix that the chain of handlers gives wasm2c. It can be turned off: `WAMR_DISABLE_HW_BOUND_CHECK=1` / `WAMR_DISABLE_STACK_HW_BOUND_CHECK=1` in the runtime and `wamrc --bounds-checks=1` (first-pass cost about 15 % on CoreMark **[run]**, WAMR AOT) | handler per copy; the bug of [where_we_stopped_2026-10-22.md](where_we_stopped_2026-10-22.md); signal-free mode 2x on memory loops **[run]** | about the same class; WAMR's chaining is a plus, a runtime that is initialised once per copy (`runtime_ref_count`, `wasm_runtime_full_init`) is a minus if several extensions share one (then they share an engine, against criterion 2) |
| **Multi-instance** | many instances of a loaded module in one runtime, each with its memory; a native registry (`wasm_runtime_register_natives`) is **global to the runtime** (by module name) **[read]** | one `Instance` object per instance, imports passed per instance | harder: per-instance imports (the Python callables of wasmext) need a trampoline that finds the instance from `exec_env` (user data) instead of a C function pointer in the instance |
| **Features of wasm2c 1.0.42** (criterion 3) | see the next table | tail calls, exceptions, multi-memory, memory64, extended constants, funcref/externref, v128 | **worse**: no exceptions, no multi-memory in AOT |
| **Traps as Python exceptions** | `wasm_runtime_call_wasm` returns false and `wasm_runtime_get_exception()` gives the message; host functions can call `wasm_runtime_set_exception` **[read]**; the runtime unwinds by itself | `longjmp`/`sigsetjmp` (`WASMEXT_TRY`), trap code to an exception | **simpler** for the shape of the API (a return value, a string rather than a code: [estimate] mapping of the message to the wasmext exception classes needs a table) |
| **Linking instances** (shared memories, tables, functions between modules) | `WAMR_BUILD_MULTI_MODULE` (off by default): **load-time** linking of imports by module name, with the modules loaded recursively from files or a loader callback; AOT has code for it (11 mentions in `aot_runtime.c`) **[read]**; imported mutable globals are **copied** per instance, not shared **[read, stability_wasm_proposals.md]**; sharing of a memory/table between independent instances by the host: **not checked** | exports and imports of memory, tables, functions between independent modules by the glue and capsules (`wasmext_export`, `--share-tables`) | harder: the model of wasmext (host-made links, a context that decides who exchanges references) would be rebuilt over a different one |
| **C API surface the glue generates** | one generic API: `wasm_runtime_lookup_function` + `wasm_runtime_call_wasm` with 32-bit argument cells, natives registered with signature strings (`"(ii)i"`) **[read]** | typed C functions from wasm2c, a glue generated per module (`_core_py.c`, `_core_glue.h`) with direct calls | **simpler** glue to generate (no per-module typed C), **slower per call** (marshalling in cells, `exec_env`) and a less typed `.pyi`/struct path [estimate; per-call cost not measured] |
| **Build requirements** (criterion 5) | LLVM + `wamrc` at build time (4.2); a C compiler for the runtime | a C compiler | harder |
| **Speed** (criterion 6) | AOT 0.86-0.95 of native (section 1) | 0.86-0.95 | the same within noise [run] |
| **Size** | 47.8 KB `.aot` + 210-355 KB runtime | 68.6 KB | larger [run] |
| **Portability** (criterion 4) | 4.2: no Pyodide, ppc64le, s390x | all of them | harder |

**Features in AOT, tried with `wamrc` on one-feature modules (my build of `wamrc` 2.4.3) [run] and the proposals page [read]:**

| Feature | `wamrc` here | Notes |
| --- | --- | --- |
| tail calls (`return_call`) | compiles with `--enable-tail-call` (without: `unsupported opcode`); ran in AOT: a recursion of 3,000,000 calls returned 7 | on by option |
| exceptions, legacy (`try`/`catch`) and new (`try_table`, `exnref`) | **both fail** (`invalid section id`: the tag section) | legacy EH: "interpreter only"; the new proposal "unimplemented" **[read]** |
| multi-memory | **fails** (`multiple memories`) | "interpreter only" **[read]** |
| memory64 | compiles; the default runtime refuses the file (`invalid limits flags`), so the runtime must be built with `WAMR_BUILD_MEMORY64=1` | software bounds checks, 64-bit targets only **[read]** |
| extended constants | compiles with `--enable-extended-const` (without: `emit global info failed`); the default runtime refuses it (`invalid init expr type`) | runtime option `WAMR_BUILD_EXTENDED_CONST_EXPR` |
| funcref / externref (reference types) | compiles (on by default); not run | |
| v128 (SIMD) | compiles and ran (returned 5) on x86-64; `--target=aarch64` compiles; `riscv64` fails (`SIMD instruction was found, try removing --disable-simd option`) | only x86-64 and aarch64 targets **[read, wamrc help]**; relaxed SIMD unimplemented **[read]** |
| GC, typed function references | `--enable-gc` exists; not tried | wasm2c has neither |

**Honest assessment [estimate].** (1) WAMR cannot replace wasm2c **and** keep the autonomy model: its compiled output is not code that stands alone, it is a data file for a loader, and what runs it is an engine of 210-355 KB that keeps a global registry and, with the default bounds checks, a process-wide signal handler (chaining, which helps, but still the state criterion 2 wants gone). (2) The option "**WAMR object + minimal runtime linked into the extension**" is *technically* possible in two forms: (i) embed the `.aot` bytes and link `libiwasm.a` AOT-only with hidden symbols: realistic, a few hundred lines of glue, but it is the engine-in-every-artifact shape; (ii) link the **object** and write the instance setup ourselves: **not realistic**, since the object has no data and depends on the private layout of `AOTModuleInstance` and on helper tables of one WAMR version. (3) It would lose features (exceptions, multi-memory), the platforms Pyodide/ppc64le/s390x, and the C-compiler-only build. (4) It would be **simpler** in: traps as return values, one generic API instead of generated typed C, no 336 KB of generated C to compile, a 0.64 s translation, and cross-compiling from one machine; and WAMR has features wasm2c lacks (GC, typed function references, branch hinting, threads/shared memory, a wasi-threads, a large native WASI). (5) As **a second backend** for modules that need a WASI-0.1 runtime with sockets or the interpreters on a small target, it is a fair candidate; as a replacement for the translation to C it is not, **on the criteria of this repository**. This reading matches the verdict for the other runtimes in [backend_alternatives.md](backend_alternatives.md): no tool keeps the autonomy and the features at once.

## What is not known

- **Whether the component model reached upstream `main` or a release after 2026-03-20**: the `main` checked here (2026-10-23) has none of it in the tree, but the state of the PRs and issues named in WASI_COMPONENTS.md (#4872, #4889, #2126) could not be read, because the GitHub API was not opened for this repository in this session. The Airbus fork was not built.
- **WASI 0.3 in WAMR**: no source or issue was read; absence from the tree is the only evidence.
- WASI 0.1 was run only for `fd_write` and `proc_exit`; files, the sandbox and sockets were read, not run. `wasi-threads` was not built.
- **Speed**: one shared machine, ~15 % noise; the order among AOT, LLVM JIT, wasmext and native is not established. Not measured: start-up time (only the LLVM JIT's 0.86 s to load), memory use, workloads other than CoreMark, AOT with PGO or other `--opt-level`, other CPUs, SIMD, threads.
- The 85 KB / 50 KB figures of the brief: not found in the current README.
- **Section 4**: the interplay of two copies of WAMR in one process (the chaining of the signal handlers) was **read, not run**; the per-call cost of the WAMR API against the wasm2c glue was not measured; I did not write a loader-less instance for the object (only argued it from the disassembly and the structure); Windows ARM64/x86, macOS arm64 natively, musl at run time, and the sharing of a memory or table between two independent WAMR instances were not checked; the timing of `wasm2c` plus the C compiler for CoreMark was not taken.
- Work files are in `/tmp/claude-0/wamr/` (builds, hosts, logs), outside the repository.
