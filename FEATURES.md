# Features and plan

What wasmext does, what it does not do yet, and what comes next. A line says what is true of the code in this branch;
where a test shows it, the test is named, so the claim can be checked (`tests/test_features.py` runs one small module
for each WebAssembly feature through the whole path: `wat2wasm`, `wasmext -i`, import, call).

Status: **done** (works, tested) · **partly** (see the note) · **not yet** (planned or open) · **no** (decided against).

## WebAssembly features

The list follows the specification: the proposals that are finished (phase 4) and the release of the specification that
took them in, from the list of finished proposals of the WebAssembly CG and the release notes of the specification
(2.0: 2022, 3.0: 2025; both read on 2026-10-18), and what `wasm2c` of WABT 1.0.42 supports, from the table of its README.
What each line says is tested (`tests/test_features.py`), not read from those documents, unless it says otherwise.

### 1.0

| Feature | Status | Note / test |
| --- | --- | --- |
| MVP | done | `1.0 mvp` |
| Import/export of mutable globals | done | exported: as attributes (see below); imported: an export of another instance (see "Imported mutable globals") |

### 2.0

| Feature | Status | Note / test |
| --- | --- | --- |
| Sign extension | done | `2.0 sign-extension` |
| Saturating float-to-int | done | `2.0 saturating float-to-int` |
| Multi-value, inside the module | done | `2.0 multi-value, inside the module` |
| Multi-value, exported function | done | comes back as a tuple; `2.0 multi-value, an exported function`, `…all number types and a parameter` |
| Multi-value, imported function | done | the callable returns a tuple; `test_an_imported_function_returns_several_results_as_a_tuple` |
| Bulk memory | done | `2.0 bulk memory` |
| Reference types, inside the module | done | `2.0 reference types, inside the module` |
| Reference types in a signature (`funcref`, `externref`) | not yet | the function is left out (export) or the module is refused (import) |
| SIMD (`v128`), inside the module | done | the C of `wasm2c` includes simde; the wabt-package (1.0.42.0b2 and later) ships the headers (`wabt_package.include_dir()`), and wasmext adds that directory to the include path of the extension when the C includes `simde/` (`_simde_include`; a tree that ships its C and has no SIMD still builds without the wabt-package). `2.0 SIMD, inside the module`, `test_a_module_with_simd_gets_the_include_directory_of_simde`. Native instructions are used only if the compiler flags allow, so a baseline x86-64 wheel runs SIMD in portable code |
| `v128` in a signature | done | 16 bytes in the order of WebAssembly memory: `bytes` (or any bytes-like object of 16 bytes) in, `bytes` out; a wrong length is a `ValueError`, another type a `TypeError`. In exported and imported functions, multi-value, exported globals and imported immutable globals. Not on big-endian hosts (`#error`; the byte order of a v128 there is not checked). `test_v128_in_signatures_globals_and_imports` |
| JavaScript BigInt to i64 | n/a | a part of the JavaScript API; here an `i64` is a Python `int` |

### 3.0

| Feature | Status | Note / test |
| --- | --- | --- |
| Tail calls | done | `3.0 tail calls`, and with locals `3.0 tail calls in a function with locals` (wasm2c 1.0.42 writes C that does not compile for a function that has locals and a `return_call`: wasmext repairs it, the pattern matches only that shape; `coremark-minimal.wasm` of pywasm3 needs it) |
| Extended constants | done | `3.0 extended constants` |
| Multi-memory | done | `3.0 multi-memory` |
| memory64 | done | inside the module, exported as a `memoryview`, addresses above 4 GiB (Linux): `3.0 memory64`, `test_an_exported_memory64_is_a_memoryview_too`, `test_memory64_addresses_above_4_gib` |
| 64-bit tables (the address type of tables, with memory64) | done inside the module | `3.0 memory64, a 64-bit table`; a table is not exported yet |
| Exception handling, legacy `try`/`catch` | done | `3.0 exceptions`; an exception nobody catches is a `Trap`: `test_an_exception_nobody_catches_is_a_trap`. This form is not in the specification, but compilers still make it |
| Exception handling, `try_table`, `throw_ref`, `exnref` | done | the form of the specification: `3.0 exceptions, try_table`, `3.0 exceptions, exnref (catch_all_ref and throw_ref)`; `exnref` in a signature and exported tags: not yet |
| Relaxed SIMD | no (wasm2c) | `wasm2c` 1.0.42 itself aborts (signal 6, no message) on `i32x4.relaxed_trunc_f32x4_s`, `f32x4.relaxed_madd`, `i8x16.relaxed_swizzle` and `i32x4.relaxed_laneselect` (the others were not tried; reported: [WABT #2886](https://github.com/WebAssembly/wabt/issues/2886)), so it is not a matter of headers; strict xfail `3.0 relaxed SIMD…`. Its README says the same: wasm2c is not ticked for relaxed SIMD |
| Typed function references | no (wasm2c) | `wat2wasm --enable-function-references` makes the binary, `wasm2c` stops at `call_ref` (unexpected opcode 0x14); the README of WABT does not tick wasm2c for it; strict xfail `3.0 typed function references` |
| Garbage collection | no (WABT) | WABT 1.0.42 does not read the instructions (`wat2wasm --enable-gc`: unexpected token `struct.get`), and `wasm2c --enable-gc` says it supports a limited set of features; strict xfail `3.0 garbage collection`. wasmext refuses the GC types in a module as well |
| Branch hinting | done | a hint is a custom section; the text annotation `(@metadata.code.branch_hint …)` builds and runs, `wasm2c` ignores the hint: `3.0 branch hinting` |
| Custom annotation syntax | n/a | the text format only; `wat2wasm` takes it, nothing is left in the binary to run |
| JS String Builtins | n/a | a part of the JavaScript API |
| Deterministic profile | n/a | a profile of the specification (a subset to run in), not something a translator implements |

### Not in 2.0 or 3.0

| Feature | Status | Note / test |
| --- | --- | --- |
| Threads, shared memory, atomics | not yet | `wasm2c --enable-threads` translates a module with a shared memory and atomics (checked, although its README does not tick wasm2c for threads), with C11 atomics and `wasm_rt_init_thread`; wasmext does not pass the flag (strict xfail `threads`) |
| Custom page sizes | not yet | `wasm2c` supports it with `--enable-custom-page-sizes` (checked: it reads a module with `(pagesize 1)` only with the flag); wasmext does not pass the flag, and its `memoryview` assumes 64 KiB pages; not tried through wasmext |
| Wide arithmetic | no (wasm2c) | `wasm2c --enable-wide-arithmetic`: "currently only supports a limited set of features" (checked), as its README says |
| Compact imports | not yet | the README of WABT: `wasm2c` is not ticked; not tried |
| WASI | not yet | deferred; the module builds, but the host has to provide every `wasi_snapshot_preview1` import, and there is no shim (wasm2c has none) |

## The Python side

| Feature | Status | Note / test |
| --- | --- | --- |
| Exported functions (`i32`, `i64`, `f32`, `f64`) | done | methods of `Instance`, positional-only, `METH_FASTCALL` |
| Integers | done | results signed, arguments wrapped (as the JavaScript API, wasmtime, wasm3); `test_integers_wrap_as_webassembly_does` |
| Exported memory | done | a read-write `memoryview` attribute; a new one after the memory grows |
| Exported globals | done | attributes, read-only if immutable: `test_exported_globals_are_attributes` |
| Exported tables, tags | not yet | left out and reported |
| Imported functions | done | `Instance({module: {name: callable}})`; Python exceptions come out of the call of the module; calling back into the module works |
| Imported immutable globals | done | a number in the imports; `test_an_imported_immutable_global_is_a_number` |
| Imported mutable globals | done | an export of another instance: `Instance({"env": a})` or `a["name"]`; the variable is shared; a number is a `LinkError`; type and mutability are checked: `test_instances_share_a_mutable_global_and_an_instance_is_a_mapping`, `test_linking_a_global_checks_what_it_is` |
| Imported memories | done | the memory of another instance: `Instance({"env": a})`, `{"memory": a.memory}` (the memoryview stands for its memory) or `a["memory"]`; one buffer, `grow` is seen by both; checked: size (at least the minimum, at most the maximum), memory64, guard pages on both sides or neither (`LinkError`): `test_instances_share_a_memory`, `test_linking_a_memory_checks_its_size_and_kind`. A shared (threads) memory is refused |
| Imported tables | not yet | refused when the extension is made |
| Shared global between instances | done | one variable used by several instances, through the exports of an instance (design below); a global made by the host with no module behind it: not yet |
| Shared memory between instances | done | one buffer used by several instances (see "Imported memories"); a memory made by the host with no module behind it, and a table: not yet |
| Recognising the objects of another extension | done | a private capsule `wasmext.export.v1` with a versioned struct, see "Recognising an instance of another extension" |
| Imported functions from another instance | done | `Instance({"env": a})`, `{"add": a.add}` (a bound method stands for its export) or `a["add"]`: the call is direct, in C, without Python in between; the signature is checked (`LinkError`); a trap inside the called function is the `Trap` of its module, raised through the caller, and both instances go on: `test_instances_call_each_others_functions_directly`, `test_linking_a_function_checks_its_signature` |
| `instance["name"]`, `instance.__exports__` | done | the references to the exports, for linking to another instance (a private capsule `wasmext.export.v1`); `{"env": a}` gives a whole shelf. See "How the imports are given" |
| Traps | done | `Trap` (a `RuntimeError`), the instance stays usable; `LinkError` for bad imports |
| GC and weak references | done | `Instance` takes part in the cycle collector and can be weakly referenced |
| Type stubs | done | `<module>.pyi` written beside the `.wasm`, with `# fmt: off` and `# ruff: noqa` |
| `wasmext inspect` | done | what a module imports and exports and what wasmext makes of it; writes nothing |

## Build and distribution

| Feature | Status | Note |
| --- | --- | --- |
| `wasmize()` for `setup.py` | done | like `cythonize()` |
| `wasmext` command (`-i`, `-b`, `-f`, `-q`, `-X`, `--build-dir`) | done | |
| Regeneration as `cythonize` does it | done | the first line of the C names the wasmext and the WABT that made it; made again when missing, made by another version, older than the `.wasm`, or forced (`force`, `-f`, `WASMEXT_FORCE_REGEN=1`) |
| abi3 (cp311) and native (free-threaded) wheels | done | chosen by the interpreter that builds; wheel tag set automatically; `--abi3`/`--no-abi3`, `WASMEXT_LIMITED_API` |
| `--no-guard-pages` | done | for processes with a limit on address space; about 30% slower on CoreMark |
| WABT from the wabt-package | done | or a directory in `WASMEXT_WABT` |
| Patch for MSVC on ARM64 | done | `_addcarry_u64` exists only on x64; a regex in `_wasmize.py` (reported: [WABT #2885](https://github.com/WebAssembly/wabt/issues/2885)) |
| Patch for `return_call` in a function with locals | done | wasm2c writes C that does not compile; a regex in `_wasmize.py` puts the type back, and passes a fixed wasm2c through (reported: [WABT #2884](https://github.com/WebAssembly/wabt/issues/2884)) |
| Example: CoreMark | done | reference CoreMark of EEMBC, built with `zig cc` by `examples/coremark/build_wasm.py` |
| simde headers | done | from the wabt-package, see SIMD above |
| Pyodide wheel | done (locally) | `cibuildwheel --platform pyodide` on `examples/coremark`, Python 3.13: built (`…pyemscripten_2025_0_wasm32.whl`, 83 KB) and the 2 tests passed inside Pyodide; the `wasm2c` of the Linux x86-64 wheel of the wabt-package did the translation on the host, no Pyodide wheel of the wabt-package is needed |
| Android wheel | partly | `cibuildwheel --platform android --archs arm64_v8a`, Python 3.13, NDK 27: the wheel (`…android_24_arm64_v8a.whl`) builds with the same host wabt-package wheel; the tests were skipped (the machine cannot run an arm64 emulator), so it was not run on Android; the extension links `libpython3.13.so`, as every Android extension does |
| Import hook, like `pyximport` | done | `import wasmimport; wasmimport.install()`; `import mod` finds `mod.wasm` (working directory, `sys.path`, packages), builds it into `~/.wasmbld` (or `build_dir`) and loads it. Options as in `pyximport`: `build_dir`, `build_in_temp`, `setup_args`, `inplace`, and those of `wasmize()`; `<module>.wasmbld` with `make_ext`/`make_setup_args`; `uninstall(finder)`, `clean()`. Not taken from `pyximport`: `.pyxdep`, importing `.py` files (`pyimport`), `reload_support`, `load_py_module_on_import_failure`. A development tool: it runs a C compiler on import. `tests/test_importer.py` |
| Configuration in `pyproject.toml` only | not yet | |
| `.wat` as a source (`wasmext -i m.wat`, `import m` with `wasmimport`) | not yet (idea) | `wat2wasm` is in the wabt-package already. Small: `Toolchain` learns the path of `wat2wasm` (and `WASMEXT_WABT/bin`), `_prepare` makes the `.wasm` first when the source is a `.wat` (same rule as for the C: made again when older than the `.wat`), the globs and the import hook accept the suffix. Open: where the `.wasm` goes (beside the `.wat` or in the build directory), flags for proposals that `wat2wasm` has off by default (`--enable-…`), and that the `.wasm` stays what is distributed. Not planned yet |
| Published on PyPI | not yet | until then the example is built with `--find-links` to the wheel of wasmext (see `example-wheels.yml`) |

## Speed

Compiled ahead of time (wasm2c, then the C compiler), so there is no engine and no JIT at run time. CoreMark (reference CoreMark
of EEMBC, 2K performance run), one machine, runs alternated, gcc 13 for the native C and for the extension: the extension was
about the same as the native C, +4% to +13% on three alternating runs (clang 18: the extension about 5% slower than the native gcc
and 3% faster than the native clang). That the extension should be faster than the C it comes from is not explained; read it as
"on a par with". With `--no-guard-pages` (checks in code, not by the MMU) the same benchmark was about 30% slower. The cost of
a call from Python and of a call back into Python was not measured.

## Verified, and not

### Where the suite ran

The whole suite (`pytest`, 183 tests and 4 expected failures at the time of writing), `ruff` and `pyright`:

| Where | Python | C compiler | Evidence |
| --- | --- | --- | --- |
| Linux x86-64, glibc (local) | 3.11 | gcc 13.3 and clang 18.1 | run by hand |
| ubuntu-latest | 3.11 | gcc | CI, `Pre-commit` runs `pytest` |
| macOS (macos-latest, Apple Silicon) | 3.11 | AppleClang | CI, the same |
| windows-latest (x64) | 3.11 | MSVC | CI, the same |

CI at commit `e880ee8` (both workflows green on all of these, 22 checks; the first attempt of that run had no runners, the repository was private
and the 2000 free minutes were used up, and it was run again after it became public). The suite is not run on Linux ARM64, Windows ARM64, macOS
Intel or the free-threaded build; only the example is (below).

### Platforms where a native extension was built and tested

The example (CoreMark) built by cibuildwheel and its tests run on the wheel (`Example wheels`, commit `e880ee8`, green on all seven):

| Platform | Evidence |
| --- | --- |
| Linux x86-64 | CI; `manylinux` and `musllinux_1_2` wheels, cp311 abi3 and cp314t, seen in the log of run #23 (commit `0e251d8`) |
| Linux ARM64 | CI job passed (the wheel list was not read) |
| Windows x64, Windows ARM64, Windows x86 (MSVC) | CI jobs passed (the wheel lists were not read) |
| macOS Apple Silicon, macOS Intel | CI jobs passed (the wheel lists were not read) |
| Pyodide 4.0.9 (CPython 3.13, wasm32) | local, `cibuildwheel --platform pyodide`: the 2 tests passed inside Pyodide (not in CI) |
| Android arm64-v8a (CPython 3.13, NDK 27) | local: the wheel is built, the tests were skipped, **not run** (not in CI) |
| Linux armv7l, riscv64, ppc64le, i686: `manylinux` and `musllinux_1_2` | local, `cibuildwheel` in Docker (armv7l, riscv64, ppc64le under QEMU; i686 in a 32-bit userland), the wasmext wheel of this branch and the wabt-package 1.0.42.0b2 wheels from PyPI: the cp311 abi3 wheel was built and the 2 tests of the example passed in each of the eight (not cp314t; not in CI) |
| Linux s390x (big-endian): `manylinux_2_28`, `musllinux_1_2` | local, the same way: the wheel is built, but the example's tests **fail**. Checked with a small module under QEMU: before the fix `i32.load` of the bytes 01 02 03 04 gave 0x01020304 instead of 0x04030201, because nothing defined `WABT_BIG_ENDIAN`; now it is defined and the value is right. The exported memory is refused there (`NotImplementedError`), and the example needs it, so on s390x the example still fails; `v128` in a signature is refused by an `#error` |
| Linux i386, CPython 3.12 | by hand, one abi3 memory64 module (`gcc -m32`), not in the suite |

The cibuildwheel configuration of the example is `build = "cp311-* cp314t-*"`.

### Not confirmed

- PyPy, iOS.
- The Linux architectures above in CI (they were built by hand under QEMU, not in a workflow), the `cp314t` wheels on them, and
  `musllinux_1_2` x86-64 locally (the disk of the machine was full; CI built it in run #23, commit `0e251d8`).
- Big-endian hosts (s390x): a module that exports its memory, or uses `v128` in a signature, does not work there (see above);
  the rest was run only through the example and one small module.
- Clang on Windows; gcc on macOS; Python 3.12 and later with the suite (CI uses 3.11).
- Android and Pyodide in CI.
- Ahead-of-time claims about speed are from one machine (see "Speed").

### Examples of other projects

The method (see the Plan) in numbers: the modules of these projects built and run by tests in this repository, all of them without a new feature.

| Source | What | Where | Result |
| --- | --- | --- | --- |
| wasm2mpy `test/` | seven languages (AssemblyScript, C++, Rust, TinyGo, Virgil, WAT, Zig), the blinking program with `wiring` as the board; CoreMark is `examples/coremark` | `tests/test_wasm2mpy.py` | works. Rust's `loop` prints only the line ends (the module's own behaviour). Built by `build_extension`, not by `wasmize()` |
| pywasm3 `00-fibonacci` | `i64` recursion | `tests/test_pywasm3.py` | works |
| pywasm3 `01-coremark` | `coremark-minimal.wasm`, `env.clock_ms` | `tests/test_pywasm3.py` | works, since the repair of `return_call` (see "Build and distribution"); the file name has a hyphen, so the test names the module by hand (`wasmize()` refuses such a name with a clear message) |
| pywasm3 `pygame-*` | `fire` (empty module name), `ray`, `maze` | `tests/test_pywasm3.py` | work: the frame is read from the memory, no window; `snake`, `dino`, `match3`, `metaball`, `chip8`, `plop-sim` not added yet (the same shape) |
| pywasm3 `02-metered` | a limit of work for an interpreter | not applicable | AOT code has no such hook |
| pywasm3 `03-asyncified` | a module made pausable by Binaryen (`wasm-opt --asyncify`): the import `sleep` calls the `asyncify_*` exports of the running instance | `tests/test_pywasm3.py` | works (the steps of the example without the event loop). Also tested: a trap of the outer call after a call into the instance from its own import, and a trap of the inner call, which is an exception in the import |
| pywasm3 `04-suspend-resume` | a pause when the gas runs out, a snapshot of the paused call | its module only (`search` and exported globals) | the feature itself is of the wasm3 engine: compiled code cannot pause by gas or save a call, not planned |
| py-wasmhost `imports.py` | several results of a host function, `i64`, an exception from the host | `tests/test_wasmhost.py` | works |
| py-wasmhost `lua.wasm`, `coreutils.wasm`, `wasi_sh`, `wasmclang`, `pyodide`, `jslinux` | WASI programs, an engine in an engine | not yet | need WASI (19 and 32 imports); `coreutils.wasm` is 10.8 MB, which makes a very large C file |

### Build time of a large module

`coreutils.wasm` (10.8 MB, from py-wasmhost) gives 137 MB of C (3.1 million lines, 12.7 times the size of the module) from `wasm2c` in seconds;
then one `gcc -O2 -g` process, on one core, works on that one file (1.3 GB of memory). **It was stopped by hand after 33 minutes without
finishing**: not practical as it is. `lua.wasm` (329 KB) takes 44 seconds. For a user this is paid once, by whoever builds the wheel; for
`wasmimport` (a build at import) it hurts. The numbers are of one machine (4 cores, gcc 13). Ideas, not built:

- **Split the C and compile the parts in parallel** (the one to try first). `wasm2c --num-outputs=N` writes N files. setuptools compiles the
  sources of one extension one after the other, so wasmext would need its own `build_ext` that compiles the objects with a pool (as NumPy
  does), with care for MSVC. About N times faster on N cores, if the parts are of an even size.
- Lower optimization for a very large module (`-O1`), and `-g0` for the generated C. Judged worse than the split: the first costs speed of
  the result, and neither is a big enough step; they can be measured when the split is there.
- Another compiler (clang may be faster on a file of this size): to be measured, not assumed.
- A cache of objects (ccache or one by the hash of the C): a rebuild costs nothing, the first build is as long.
- A smaller module before the translation (`wasm-opt`, dropping what is not used): depends on the module, not general.
- `wasmimport` to warn when the C is larger than some size.

## Known gaps

- A memory that cannot be allocated when the instance is made (too big, or with guard pages in a process limited in address
  space, which each memory reserves about 8 GiB of) is a `MemoryError`; `--no-guard-pages` avoids the second case. Other `abort()`
  of the runtime (the locks, the signal handlers) are left as they are. A memory that fails to *grow* returns -1, as WebAssembly says.
- Big-endian hosts (s390x): wasm2c keeps the memory reversed there, so the exported memory cannot be a `memoryview` (it raises
  `NotImplementedError`) and `v128` in a signature is refused; a module that does not use them runs (checked on one small module). A copy-based view
  or conversion would be needed.
- Attributes and methods of `Instance` take the names of the exports; a name that is not an identifier is reachable with `getattr`.

## Plan

In this order (the first ones are small):

1. ~~The `abort()` of the runtime~~ → `MemoryError`: done. The copy of `wasm-rt-mem-impl-helper.inc` gets a trap (code `0x7001`) in place of the
   four `abort()` of `wasm_rt_allocate_memory` (and loses the `perror` lines); the glue raises `MemoryError`. The patch fails loudly if
   the function is not what it expects, and is part of the recipe that makes the C be generated again.
2. ~~**SIMD**~~: done, including `v128` ↔ `bytes` of 16 in signatures. Relaxed SIMD stays out (wasm2c aborts).
3. **Linking instances**: done for globals, memories and functions (the design below; [`examples/link`](examples/link) shows them). Left: tables
   (they first have to be exposed as an object, then linked: imported and exported tables are both refused now). A global, memory or
   table made by the host with no module behind it is postponed.
4. **Threads**: `--enable-threads`, C11 atomics (and MSVC), a shared memory, `wasm_rt_init_thread` per thread. After 3, since the
   shared memory is a memory given to several instances, and the link table must not rely on plain reads of a mutable global.
5. ~~**CI**~~: the desktop matrix is green (see "Verified"). The other Linux architectures were checked by hand under QEMU (armv7l,
   riscv64, ppc64le, i686 work; s390x, big-endian, does not for modules with a memory export). Left: those in CI (a QEMU job). Windows x86 is in the matrix and green.
6. Android and Pyodide in the CI matrix of the example (they build locally, see above); `pyproject.toml` configuration (no `setup.py`);
   publishing on PyPI; `.wat` as a source (an idea, see "Build and distribution").
7. `funcref`/`externref` in signatures (a design is needed first: who owns an `externref`); custom page sizes (`wasm2c` can, with a
   flag); the rest of the examples of other projects (below).
8. **WASI** (`wasi_snapshot_preview1` and `wasi_unstable`): part of wasmext, compiled into the native module as a header, `wasi_preview1.h`, the system
   reached through `Python.h`. Not started; see "Design: WASI".

How to choose the next features: **on demand, not in advance**. The examples of [wasm2mpy](https://github.com/vshymanskyy/wasm2mpy)
and [pywasm3](https://github.com/wasm3/pywasm3) are taken one by one, the simplest first, and added to this project as examples
(or tests); a feature is built when the next example needs it, and not before. The examples of
[py-wasmhost](https://github.com/ballistics-lab/py-wasmhost) are more complex: they come after those.

## Design: linking instances (globals, functions and memories are built; tables are not)

The goal is the "shared objects" of the plan: an instance uses a global, a memory, a table or a function of another instance.
wasmext stays native: no `Global`/`Memory`/`Table` classes copied from the JavaScript API (as `wasmhost` has, because there an
engine owns the objects), but the exports of one instance given as the imports of another.

```python
a = A.Instance()
b = B.Instance({"env": a})  # imports of module "env" are taken, by name, from the exports of a
```

**What wasm2c gives.** The C of a module that imports a global, a memory or a table keeps a *pointer* to it (`u32 *w2c_env_g`,
`wasm_rt_memory_t *w2c_env_mem`, `wasm_rt_funcref_table_t *w2c_env_tab`), taken at instantiation from the accessors
`w2c_env_g(struct w2c_env *)` that the host defines; an exported one has the same shape (`u32 *w2c_m_eg(w2c_m *)`,
`wasm_rt_memory_t *w2c_m_em(w2c_m *)`, `wasm_rt_funcref_table_t *w2c_m_et(w2c_m *)`). So linking is handing the pointer
of the exporter to the importer: one value, one memory, one table, no copy, no Python in between. An imported function is
`w2c_env_f(struct w2c_env *, args)`: the glue can call the exported function of the other module itself (its instance pointer is
the first argument) instead of a Python callable.

**How the imports are given (decided).** A shelf is a dict, and a value in it can be a reference to an export of another instance.
There are two kinds of access on an instance, with different jobs:

| | | |
| --- | --- | --- |
| attributes | **use** the module from Python | `a.add(2, 3)` calls; `a.counter` is the number, `a.counter = 5` sets it; `a.mem` is a memoryview |
| items | **link** it to another module | `a["counter"]` is the reference to the export; `a.__exports__` is the dict of all of them |

```python
B.Instance({"env": a})  # a shelf from an instance: all of it
B.Instance({"env": {"log": print}})  # a dict: by keys, as now
B.Instance({"env": {**a.__exports__, "log": print}})  # everything of a, and log from Python (the later key wins)
B.Instance({"env": {"counter": a["counter"], "log": print}})  # one export of a, and log from Python
```

There is no `export()` and no `keys()` on the instance: the instance has no names of its own, only the double-underscore ones
(`__exports__`, `__getitem__`, ...), and an export called like that is not an attribute (it is in `__exports__`), so a name of an
export never clashes with one of the instance. `**a` does not work (it needs `keys()`), `**a.__exports__` does. Write the dict as a
literal or `dict(a.__exports__, log=print)`: `dict(**a.__exports__, log=print)` is a `TypeError` of Python (a duplicate keyword).
Almost every compiler puts all its imports on one shelf, `env`, the host functions (print, clock) and the ones another module could
give, so the dict forms are the common ones for real modules. Beware that `{"env": a}` matches by name: if both `a` and the host
could give `log`, `a` wins silently when the types agree; the dict with the explicit key shows what is meant.
Left out for now: a list of sources (`{"env": [a, {"log": print}]}`); a wrapper object for a function that is both callable and a
reference (it cannot be done for a global or a memory, whose attribute has to be the value, and costs a type and a cache); instead,
when functions are linked, a bound method of an instance (`{"add": a.add}`) can be accepted as the reference at no cost on a call.
Names of exports that the module does not import are ignored. Built: globals (also immutable ones), functions, memories, `a["name"]`,
`__exports__` and the shelf from an instance. Tables are not (they first have to be exposed as an object).

**Recognising an instance of another extension.** The types are not the same objects in two extensions, so `isinstance` cannot
tell. What `instance['name']` and `instance.__exports__` hold is a capsule (a `PyCapsule`, usable in the limited API) named
`wasmext.export.v1`, one for each export, that points to a record `wasmext_export`: `size`, `version` (1), `kind` (function, table,
memory, global), `type`, `flags`, the owner (the instance, which a reader that keeps the address keeps alive) and `address`; for a
function also the `instance` pointer and the `signature` (`"ii>i"`: `i j f d o`). For a global `type` is the value type of the binary
format (`0x7F` is i32) and bit 0 of `flags` says it is mutable; for a memory `type` is `sizeof(wasm_rt_memory_t)` and `flags` has memory64
(bit 1) and guard pages (bit 2). A function is called as `result f(void *instance, parameters..., int *trapped)`, which catches the
trap with the jump buffer of the exporter, so each extension handles its own traps. The format is a contract between versions of wasmext,
so it is versioned from the first day; an unknown version, or a `size` smaller than the reader knows, is a `LinkError`, not a guess.

**Keeping the contract still.** Changing it means a new `v2` and every extension built before it fails to link with the new
ones, so it is made to change rarely: the record begins with its own `size`, and new fields are only appended (a reader checks
`size` before it reads one, so an old reader ignores them and a new one knows an old table has not got them); the entries are a
fixed-size record with a `kind` and room for flags; the pointers are those of wasm2c (`u32 *`, `wasm_rt_memory_t *`,
`wasm_rt_funcref_table_t *`), so wasmext adds nothing of its own to what must stay the same. The name `wasmext.export.v1`
changes only if a field is *removed or changes meaning*, which should never be needed.

**Checks, all at instantiation, all `LinkError`**: the export exists; it has the kind the import asks for (a function is not a
global); the types are equal (`i32` ≠ `i64`, mutable ≠ immutable, the signature of a function); for a memory, the limits of the
import are satisfied (initial and maximum pages, memory64 equal); for a table, the element type and limits.

**Lifetime.** The importer holds a strong reference to the exporter, so the pointers stay valid as long as it lives. A cycle
(a imports from b and b from a) is not possible at instantiation, because an instance has to exist before it is given; an
instance takes part in the cycle collector already, and the reference is visited in `tp_traverse` and cleared in `tp_clear`.
`wasm2c_<m>_free` of the exporter must not run while an importer lives: guaranteed by the reference.

**Memory.** The memory object is the same, so `a.mem` and `b.mem` are `memoryview`s of the same bytes. A `grow` by either is seen by
both (the struct is shared); a view taken before the grow is the old size, as it is today (a new one after).

**Functions between instances.** The glue of the importer calls `w2c_<provider>_<name>` of the other extension through the table of
the capsule, so the traps cross: a trap in the callee unwinds to the call from Python, as when a Python callable calls back. The
jump buffer is per thread and the call goes on the same stack, so the existing `ENTER_WASM`/save-and-restore applies; to be checked
with a test of a trap two instances deep.

**Not covered (and why that is fine for now)**: a global, memory or table made by the host with no module behind it (a small
object would be needed; postponed until somebody needs it); `externref` tables; threads and `shared` memory (the pointer is shared,
but not made atomic: that is plan item 4 and changes the layout, so this design must not rely on plain reads of a mutable global
once threads exist); instances from different wasmext *builds* with different wasm2c runtimes (the structs of `wasm-rt.h` have to
match: the capsule carries the version of the runtime and compares it).

**Order**: 1. imported mutable globals from an exporting instance (smallest: a pointer and a type check; also removes the "refused
when the extension is made" for them); 2. memories; 3. functions; 4. tables.

**Decided**: the forms above; the format of the link table (capsule) is private, documented and
versioned (not a promise to others) until a second user of it exists.

## Design: WASI (decided; stage 1 is built, see the end of this section)

**Decided.** WASI is part of wasmext and is compiled into the native module; a built module needs nothing at run time (not wasmext
either), so a shared library that modules call into was rejected. The code is hand-written C, **header only**, one header for each interface the module
imports: `wasi_preview1.h` for `wasi_snapshot_preview1` and `wasi_unstable.h` for `wasi_unstable` (the first snapshot,
"preview0"), which share `wasi_common.h`. The headers are copied into `<name>_wasmext/` and included by the glue of the module (both, if it
imports both), so there is no second source file to build. Its functions are `static inline`: the glue names the ones the module imports, and the compiler drops
the others, so a module has only the calls it imports. It is not generated each time, so it can be read, tested and fixed as ordinary C.
`wasi_unstable` is not folded into `wasi_preview1`: the day a call differs between them, it gets its own function there.
WASI 0.2 and 0.3 are not another header of this kind: see "WASI 0.2 and 0.3" below. A call that WASI does not have, or that
a module imports with another signature, is refused when the glue is made (`GenError`).

**Portability: direct where it is the same, through `Python.h` where it is not.** A call is made in plain C when the C library behaves the
same on POSIX and on Windows (the CRT), with no interpreter in between. A call that can differ on Windows (non-POSIX) goes through
CPython instead (the `os`, `io`, `time` and `sys` modules, called from C with the limited API, so an abi3 module can use it), and then
differs only where Python itself differs. The rule is applied call by call, and the table below is a draft to be confirmed by the
tests on Windows (CI has Windows x64, x86 and ARM64), not a finding:

| Way | Calls (draft) | Why |
| --- | --- | --- |
| direct | `args_*`, `environ_*`, `sched_yield`, `fd_prestat_*`, the bookkeeping of descriptors, `fd_seek`/`fd_tell`, `fd_read`/`fd_write` on the descriptors it opened | data of the instance, or the same call on both |
| through Python | `random_get`, `clock_*` | the source differs (`getrandom`, `BCryptGenRandom`, `clock_gettime`, `QueryPerformanceCounter`); `os.urandom`, `time.time_ns`, `time.monotonic_ns` are cheap |
| through Python | `path_open`, `fd_readdir`, `fd_filestat_*`, `path_filestat_*`, `path_rename`, `path_unlink_file`, `path_remove_directory`, `path_symlink`, `path_readlink`, `path_link`, `fd_filestat_set_times`, `fd_allocate`, `fd_advise`, `fd_datasync`, `fd_sync`, `fd_pread`, `fd_pwrite`, `poll_oneoff` | Windows has no `pread`, cannot open a directory with `open`, has its own `stat` (no inode, link count), `FindFirstFile` for a listing, other rules for renaming over a file, symbolic links need a privilege, `select` works on sockets only |
| through Python (decided) | `fd_read`/`fd_write` on the standard streams | direct writes to descriptors 1 and 2 bypass the buffer of `sys.stdout` (the order against Python's `print`, a capture in a notebook or a test), so by default they go to `sys.stdout.buffer` after a flush of `sys.stdout` |

**What it covers.** The 46 functions of the specification (`wasi_snapshot_preview1.witx`, the branch `wasi-0.1` of WebAssembly/WASI;
the files are in `tests/data/wasi/` of py-wasmhost, with their licence): arguments, environment, clocks, `random_get`,
`proc_exit`, `sched_yield`, `poll_oneoff`, the `fd_*` calls, the `path_*` calls. Sockets, signals and threads answer as the
specification allows (`ENOTSOCK`, `ENOSYS`). The first snapshot, `wasi_unstable` (what `lua.wasm` imports), has the same
functions but `sock_accept`, and four differences in what it reads and writes: the order of `whence` (cur, end, set), one right less,
`filestat` with a 32-bit link count (which moves its fields), and a clock subscription with an extra `identifier` (56 bytes). So the
two files differ in the few calls that touch those (`fd_seek`, `fd_fdstat_get`, `fd_filestat_get`, `path_filestat_get`, `poll_oneoff`);
the rest is common. A private header holds the common part, which both headers include, so that they cannot drift apart (`wasi_common.h`; the calls built so far read and write none of the four, so the same function serves both snapshots). A module gets only the functions it imports, so a module
without WASI contains none of it. The state (file descriptors, preopens) is in the instance, not in globals.

**Staged.** First what is the same everywhere: standard streams, arguments, environment, clocks, `random_get`, `proc_exit`. Then
files and directories (`fd_*`, `path_*`) with preopens that confine the program to a directory. Last `poll_oneoff`.

**Reference for behaviour.** `wasmhost.wasi.preview1` (plain Python, MIT) is run beside it as the oracle in tests, and the witx files
give the names and signatures. Its code is not copied: this is written from the specification.

**Decided (the first version).**
- Configuration is a keyword of the instance, `Instance(imports, wasi={"args": [...], "env": {...}, "preopens": {"/": "dir"},
  "stdin": ..., "stdout": ..., "stderr": ...})`.
- Standard streams go to `sys.stdin.buffer`, `sys.stdout.buffer` and `sys.stderr.buffer` by default, so that capturing in a notebook or
  a test works, and an object with `write(bytes)` replaces one.
- `proc_exit(n)` is an exception (`WasiExit`, carrying the code) out of the call that led to it; the instance stays usable.
- The command `_start` is called as an export, as any other (no `run()` helper in the first version).
- Test modules: `lua.wasm` (wasi_unstable, 19 imports) first, then `coreutils.wasm` (preview1, 32 imports, 10.8 MB, which makes a very large
  C file and a long build).

**Stage 1 (built, `wasi_snapshot_preview1` only).** `src/wasmext/c/wasi_preview1.h`, copied beside the C of a module that imports
`wasi_snapshot_preview1` and included by its glue (the glue calls the functions directly, through the slots that linking instances uses). The calls
that work: `args_*`, `environ_*`, `clock_res_get`, `clock_time_get`, `random_get`, `sched_yield`, `proc_exit` (raises the module's `WasiExit`,
`.code`), `fd_read` (stdin), `fd_write` (stdout, stderr), `fd_close`, `fd_fdstat_get`, `fd_prestat_get` (always `EBADF`: nothing is
preopened), `fd_seek`, `fd_tell` (`ESPIPE` on the standard streams). Every other call of the 46 answers `ENOSYS` (the sockets
`ENOTSOCK`). `Instance()` needs no imports; `wasi={...}` takes args, env, stdin, stdout, stderr; `preopens` raises `NotImplementedError`.
What the caller gives as an import wins, call by call. Both snapshots are served (`wasi_unstable.h`; `sock_accept` is not a call of the first one: `GenError`). Not built: the files and directories, `poll_oneoff`. Tests:
`tests/test_wasi.py` (through `build_extension`, not on Windows) and `test_a_wasi_module_is_built_with_the_wasi_header_of_wasmext` (the whole
path, every platform of CI). `lua.wasm` (imports `wasi_unstable`) is not run in the tests yet.

**WASI 0.2 and 0.3 (preview2, preview3): not planned yet, and not just one more header.** The WASI above is a set of ordinary imports of a core
module, which is what `wasm2c` translates. 0.2 and 0.3 are defined over the Component Model: what the toolchain gives (Rust `wasm32-wasip2`,
`wasm-tools component new` on the output of wasi-sdk) is a *component*, a package of core modules with typed interfaces (WIT), resources (handles)
and the canonical ABI that lifts and lowers strings, lists and records between them. `wasm2c` reads core modules only. To run a component,
wasmext would first have to take it apart at build time (the core modules inside go to `wasm2c`, the way `jco transpile` does it for
JavaScript) and write the canonical ABI and the host side of the interfaces (`wasi:cli`, `wasi:io` streams, `wasi:filesystem`, `wasi:clocks`,
`wasi:random`) itself. 0.3 (ratified in June 2026 by the official pages; the toolchains are still arriving) adds native async to the
canonical ABI (`stream<T>`, `future<T>`, async functions): a scheduler of tasks on top. That is a separate large feature ("component model"),
to be decided on its own after preview1 is finished, not a continuation of `wasi_preview1.h`. Until then a component is out of reach, and the way
around it is to build for `wasm32-wasip1` (or to take the core module before it was made a component), which the toolchains still offer.

## Decisions

- **Platforms.** `wasmext` is a pure Python wheel (`py3-none-any`) that depends on the wabt-package, so it installs wherever the
  wabt-package has a wheel (or builds from its sdist with a C++20 compiler): the platforms of `wasmext` are the platforms of the
  wabt-package, and nothing else limits them. Both packages cover the desktop platforms of `cibuildwheel` and nothing outside them
  (no Android, Pyodide or iOS wheels of the tools: `wasm2c` runs on the machine that builds, and an extension for Android or
  Pyodide is built with the wheel of the host, checked on `examples/coremark`). For the wabt-package the wanted set is Linux
  (manylinux and musllinux: x86_64, aarch64 as the core; i686, armv7l, ppc64le, s390x, riscv64 as well), Windows (x64, ARM64; x86 as well)
  and macOS (arm64, x86_64; universal2 as well). Every wheel is linked statically against the C++ runtime (a test checks it on every platform).
  `zig cc` is not a requirement of anyone: it only builds `_core.wasm` of the example (the `wasm` dependency group of this repository, not installed by default); the user of
  wasmext brings a `.wasm` made by whatever they like. The platforms of the packages that are built *with* wasmext (like `coremark`)
  can be more than these, Pyodide and Android among them.

- The glue is plain CPython C API, not nanobind, pybind11 or Cython: it is generated, targets abi3 from 3.11 (nanobind's linked mode needs 3.12 for
  that) and needs no C++ or extra build dependency.
- No WASI shim in Python. If WASI comes back, it is an existing C implementation (uvwasi, which WABT uses itself for `wasm-interp`).
- `wasmhost` is a different tool (a facade over engines); its API is a guide for names and errors, the reference for behaviour
  is the specification and the JavaScript API.
