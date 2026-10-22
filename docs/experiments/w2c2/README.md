# w2c2 against one feature at a time (a dead end for this project: stopped)

`turbolent/w2c2` (checkout of 2026-09-21, built with CMake) translated 17 small modules, one feature each (`probes/`, made with `wat2wasm --enable-all`), and `matrix.py` compiled the C with `gcc -c -DWASM_THREADS_PTHREADS`. **[run]** 2026-10-22.

| Translates and compiles | Fails in the translator |
| --- | --- |
| core (`call_indirect`), **multi-memory**, bulk memory (`memory.fill/copy/init`, `data.drop`), sign extension, saturating conversions, **atomics with `memory.atomic.wait/notify`** (the C needs `-DWASM_THREADS_PTHREADS`), an infinite recursion (it translates; what it does when run was not tried) | **tail calls** (`return_call*`), **exceptions** (legacy `try`, `try_table`, `exnref`), **memory64**, **multi-value** ("unsupported function type ... with 2 result values"), **reference types** (`externref`, `table.get/set`: "invalid value type"), **SIMD** (v128), **custom page sizes**, extended constants, **passive element segments** (`table.init`, `elem.drop`) |

It supports two things that `wasm2c` 1.0.42 does not: `memory.atomic.wait/notify` (an `UNIMPLEMENTED` in the C writer of WABT) and, with its own conditions, shared memory. It lacks tail calls, exceptions, memory64, multi-value, references and SIMD, which wasmext has.

**The run on the modules of this repository (`tests/data`, `examples`) is not reported:** the first pass used `wat2wasm --enable-all`, which writes the imports in the compact form (the binary that WABT 1.0.42 emits with that flag), and `w2c2` refuses it ("invalid import section import kind"), so most test modules failed for that reason and not for a missing feature; a rerun with the default flags was cut short. The binaries that were built by real toolchains
(Rust, C++, Zig, TinyGo, AssemblyScript, a coremark, `ray`, `maze`, `fire`) did translate and compile in that pass, except one with `return_call` (`coremark-minimal.wasm`) and one with two results (`imports.wasm`).
