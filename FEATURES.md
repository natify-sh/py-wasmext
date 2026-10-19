# Features and plan

What wasmext does, what it does not do yet, and what comes next. A line says what is true of the code in this branch;
where a test shows it, the test is named, so the claim can be checked (`tests/test_features.py` runs one small module
for each WebAssembly feature through the whole path: `wat2wasm`, `wasmext natify -i`, import, call).

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
| SIMD (`v128`), inside the module | done | the C of `wasm2c` includes simde; the wabt-package (1.0.42.0 and later) ships the headers (`wabt_package.include_dir()`), and wasmext adds that directory to the include path of the extension when the C includes `simde/` (`_simde_include`; a tree that ships its C and has no SIMD still builds without the wabt-package). `2.0 SIMD, inside the module`, `test_a_module_with_simd_gets_the_include_directory_of_simde`. Native instructions are used only if the compiler flags allow, so a baseline x86-64 wheel runs SIMD in portable code |
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
| WASI 0.1 (`wasi_snapshot_preview1`, `wasi_unstable`) | done | in the module, in C (wasm2c has none): 42 of the 46 calls work, the rest answers as the specification allows; the 72 programs of the official test suite pass (see "Design: WASI"). WASI 0.2 and 0.3 (components): no |

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
| `wasmext natify` and `wasmext inspect`, commands (`wasmext --help`) | done | `natify` writes the C and, with `-i` or `-b`, builds; there is no command by file names alone. A place for the next ones: `natify --shared` (a shared library with no `Python.h`, see "C first") and the bindings for `ctypes` |
| `wasmext inspect` | done | what a module imports and exports and what wasmext makes of it; writes nothing |

## Build and distribution

| Feature | Status | Note |
| --- | --- | --- |
| `natify()` for `setup.py` | done | like `cythonize()` |
| `wasmext` command (`-i`, `-b`, `-f`, `-q`, `-X`, `--build-dir`) | done | |
| Regeneration as `cythonize` does it | done | the first line of the C names the wasmext and the WABT that made it; made again when missing, made by another version, older than the `.wasm`, or forced (`force`, `-f`, `WASMEXT_FORCE_REGEN=1`) |
| abi3 (cp311) and native (free-threaded) wheels | done | chosen by the interpreter that builds; wheel tag set automatically; `--abi3`/`--no-abi3`, `WASMEXT_LIMITED_API` |
| `--no-guard-pages` | done | for processes with a limit on address space; about 30% slower on CoreMark |
| WABT from the wabt-package | done | or a directory in `WASMEXT_WABT` |
| Patch for MSVC on ARM64 and x86 | done | `_addcarry_u64` exists only on x64 (not on ARM64 and 32-bit x86); a regex in `_natify.py`, applied to the shared `_w2c-impl.h` of a module in several files too (it was missed there, and `lua` did not link on Windows x86 and ARM64) (reported: [WABT #2885](https://github.com/WebAssembly/wabt/issues/2885)) |
| Patch for `return_call` in a function with locals | done | wasm2c writes C that does not compile; a regex in `_natify.py` puts the type back, and passes a fixed wasm2c through (reported: [WABT #2884](https://github.com/WebAssembly/wabt/issues/2884)) |
| Large modules in several files | done | `wasm2c --num-outputs`, compiled at the same time; automatic from 1 MiB, `parts=` / `--parts` / `WASMEXT_PARTS`; see "Build time of a large module" |
| Example: CoreMark | done | reference CoreMark of EEMBC, built with `zig cc` by `examples/coremark/build_wasm.py` |
| Example: link | done | two modules that use each other's memory, variable and function (`examples/link`) |
| Example: Lua | done | `lua.wasm`, a WASI program, built in 8 files (`examples/lua`); tests on the wheel, and the wheels, in CI on seven platforms |
| Example: QuickJS | done | `qjs` of QuickJS-ng v0.17.0 (1.1 MB), a WASI program built with `zig cc` from the sources of the tag (`examples/quickjs/build_wasm.py`), in 4 files; a real `proc_exit` for the errors of a script, not a trap as in Lua; 9 tests on the wheel (a module imported from a directory, stdin, writes, a name that leaves the directory refused) |
| simde headers | done | from the wabt-package, see SIMD above |
| Pyodide wheel | done | `cibuildwheel --platform pyodide` on `examples/coremark`, Python 3.13: built and the tests passed inside Pyodide, locally and in CI (the job "coremark on Pyodide"); the `wasm2c` of the Linux x86-64 wheel of the wabt-package did the translation on the host, no Pyodide wheel of the wabt-package is needed |
| Android wheel | built, not run | `cibuildwheel --platform android --archs arm64_v8a`, Python 3.13, NDK 27, in CI (the job "coremark on Android arm64", on an x86-64 runner): the wheel builds with the host wabt-package wheel. The tests do not run: cibuildwheel tests on an emulator of the architecture of the build machine, so an arm64 wheel built on x86-64 is not tested. An x86-64 wheel on the Linux runner (an emulator with KVM, and a `test-command` that is a Python command) would be; not tried. The extension links `libpython3.13.so`, as every Android extension does |
| Import hook, like `pyximport` | done | `import wasmimport; wasmimport.install()`; `import mod` finds `mod.wasm` (working directory, `sys.path`, packages), builds it into `~/.wasmbld` (or `build_dir`) and loads it. Options as in `pyximport`: `build_dir`, `build_in_temp`, `setup_args`, `inplace`, and those of `natify()`; `<module>.wasmbld` with `make_ext`/`make_setup_args`; `uninstall(finder)`, `clean()`. The cache (`<build_dir>/<cache tag>-<platform>/<name>-<hash of the path>/`) holds the extension (`lib/`), the C (`c/`) and a stamp of how it was built (`guard_pages`, `limited_api`, `parts`, the settings of the extension, `CC`/`CFLAGS`/`LDFLAGS`): a change of any of them makes the extension again, and a native file and an abi3 one do not shadow each other. Not taken from `pyximport`: `.pyxdep`, importing `.py` files (`pyimport`), `reload_support`, `load_py_module_on_import_failure`. A development tool: it runs a C compiler on import. `tests/test_importer.py` |
| Configuration in `pyproject.toml` only | done | `[[tool.wasmext.ext-modules]]` (or one table `[tool.wasmext.ext-modules]`): the arguments of `natify()` with dashes (`module-list` is a string or a list) and, added to each extension, `extra-compile-args`, `extra-link-args`, `define-macros`, `undef-macros`, `include-dirs`, `libraries`, `library-dirs`; read by `wasmext._setuptools` (the entry point `setuptools.finalize_distribution_options`, as `setuptools-rust` does it for `[tool.setuptools-rust]`); unknown keys and a missing `module-list` are errors; `natify()` in `setup.py` together with the table is an error, other extensions of `setup.py` go with it. `[tool.wasmext]` has room for other hooks. Used by `examples/quickjs` (no `setup.py`); `tests/test_pyproject_config.py`. Like `cythonize()` and `mypycify()`, the C is made when the hook runs, which setuptools does more than once per build (the second time nothing is made again: the C is up to date) |
| `.wat` as a source (`wasmext natify -i m.wat`, `import m` with `wasmimport`) | not yet (idea) | `wat2wasm` is in the wabt-package already. Small: `Toolchain` learns the path of `wat2wasm` (and `WASMEXT_WABT/bin`), `_prepare` makes the `.wasm` first when the source is a `.wat` (same rule as for the C: made again when older than the `.wat`), the globs and the import hook accept the suffix. Open: where the `.wasm` goes (beside the `.wat` or in the build directory), flags for proposals that `wat2wasm` has off by default (`--enable-…`), and that the `.wasm` stays what is distributed. Not planned yet |
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

The whole suite (`pytest`, 264 tests and 4 expected failures at the time of writing), `ruff` and `pyright`:

| Where | Python | C compiler | Evidence |
| --- | --- | --- | --- |
| Linux x86-64, glibc (local) | 3.11 | gcc 13.3 and clang 18.1 | run by hand |
| ubuntu-latest | 3.11 | gcc | CI, `Pre-commit` runs `pytest` |
| macOS (macos-latest, Apple Silicon) | 3.11 | AppleClang | CI, the same |
| windows-latest (x64) | 3.11 | MSVC | CI, the same |

The official tests of WASI (`WASI test suite`, below) run on three more rows of this table: ubuntu-latest (twice: `openat`, and files through Python),
macOS and Windows, with `wasmext` on Python 3.11 and the runner of the suite on 3.12.

CI at commit `e880ee8` (both workflows green on all of these, 22 checks; the first attempt of that run had no runners, the repository was private
and the 2000 free minutes were used up, and it was run again after it became public). The suite is not run on Linux ARM64, Windows ARM64, macOS
Intel or the free-threaded build; only the example is (below).

### Platforms where a native extension was built and tested

The examples (CoreMark, and Lua from commit `43324a2`) built by cibuildwheel and their tests run on the wheel (`Example wheels`, commit `e880ee8` for CoreMark, `2691854` for both, green on all seven):

| Platform | Evidence |
| --- | --- |
| Linux x86-64 | CI; `manylinux` and `musllinux_1_2` wheels, cp311 abi3 and cp314t, seen in the log of run #23 (commit `0e251d8`) |
| Linux ARM64 | CI job passed (the wheel list was not read) |
| Windows x64, Windows ARM64, Windows x86 (MSVC) | CI jobs passed (the wheel lists were not read) |
| macOS Apple Silicon, macOS Intel | CI jobs passed (the wheel lists were not read) |
| Pyodide 4.0.9 (CPython 3.13, wasm32) | CI (the 2 tests of coremark passed inside Pyodide), and locally |
| Android arm64-v8a (CPython 3.13, NDK 27) | CI: the wheel is built; the tests are not run (see "Android wheel") |
| Linux armv7l (native arm runner), i686 (native), ppc64le and riscv64 (QEMU), `manylinux` and `musllinux_1_2` | CI jobs passed (coremark: the wheel is built and its 2 tests pass; the wheel lists were not read); ppc64le and riscv64 take 10 to 11 minutes |
| `examples/quickjs` on the seven platforms of the desktop matrix | CI jobs passed (9 tests each) |
| Linux armv7l, riscv64, ppc64le, i686: `manylinux` and `musllinux_1_2` | local, `cibuildwheel` in Docker (armv7l, riscv64, ppc64le under QEMU; i686 in a 32-bit userland), the wasmext wheel of this branch and the wabt-package 1.0.42.0b2 wheels from PyPI: the cp311 abi3 wheel was built and the 2 tests of the example passed in each of the eight (not cp314t; now also in CI, see the row above) |
| Linux s390x (big-endian): `manylinux_2_28`, `musllinux_1_2` | local, the same way: the wheel is built, but the example's tests **fail**. Checked with a small module under QEMU: before the fix `i32.load` of the bytes 01 02 03 04 gave 0x01020304 instead of 0x04030201, because nothing defined `WABT_BIG_ENDIAN`; now it is defined and the value is right. The exported memory is refused there (`NotImplementedError`), and the example needs it, so on s390x the example still fails; `v128` in a signature is refused by an `#error` |
| Linux i386, CPython 3.12 | by hand, one abi3 memory64 module (`gcc -m32`), not in the suite |

The cibuildwheel configuration of the example is `build = "cp311-* cp314t-*"`.

### Not confirmed

- PyPy (iOS is not a target).
- The `cp314t` wheels on the Linux architectures other than x86-64 and ARM64 (CI builds `cp311` and `cp314t` there but the wheel lists were not read).
- Big-endian hosts (s390x): a module that exports its memory, or uses `v128` in a signature, does not work there (see above);
  the rest was run only through the example and one small module.
- Clang on Windows; gcc on macOS; Python 3.12 and later with the suite (CI uses 3.11; the official WASI tests use 3.11 for wasmext and 3.12 for the runner of that suite).
- Android: the tests (an arm64 wheel is only built, see "Android wheel"); a run on a real device.
- Ahead-of-time claims about speed are from one machine (see "Speed").

### Examples of other projects

The method (see the Plan) in numbers: the modules of these projects built and run by tests in this repository, all of them without a new feature.

| Source | What | Where | Result |
| --- | --- | --- | --- |
| wasm2mpy `test/` | seven languages (AssemblyScript, C++, Rust, TinyGo, Virgil, WAT, Zig), the blinking program with `wiring` as the board; CoreMark is `examples/coremark` | `tests/test_wasm2mpy.py` | works. Rust's `loop` prints only the line ends (the module's own behaviour). Built by `build_extension`, not by `natify()` |
| pywasm3 `00-fibonacci` | `i64` recursion | `tests/test_pywasm3.py` | works |
| pywasm3 `01-coremark` | `coremark-minimal.wasm`, `env.clock_ms` | `tests/test_pywasm3.py` | works, since the repair of `return_call` (see "Build and distribution"); the file name has a hyphen, so the test names the module by hand (`natify()` refuses such a name with a clear message) |
| pywasm3 `pygame-*` | `fire` (empty module name), `ray`, `maze` | `tests/test_pywasm3.py` | work: the frame is read from the memory, no window; `snake`, `dino`, `match3`, `metaball`, `chip8`, `plop-sim` not added yet (the same shape) |
| pywasm3 `02-metered` | a limit of work for an interpreter | not applicable | AOT code has no such hook |
| pywasm3 `03-asyncified` | a module made pausable by Binaryen (`wasm-opt --asyncify`): the import `sleep` calls the `asyncify_*` exports of the running instance | `tests/test_pywasm3.py` | works (the steps of the example without the event loop). Also tested: a trap of the outer call after a call into the instance from its own import, and a trap of the inner call, which is an exception in the import |
| pywasm3 `04-suspend-resume` | a pause when the gas runs out, a snapshot of the paused call | its module only (`search` and exported globals) | the feature itself is of the wasm3 engine: compiled code cannot pause by gas or save a call, not planned |
| py-wasmhost `imports.py` | several results of a host function, `i64`, an exception from the host | `tests/test_wasmhost.py` | works |
| py-wasmhost `lua.wasm`, `coreutils.wasm` | WASI programs | done | `lua.wasm` is [`examples/lua`](examples/lua) (tests, and wheels in CI); `coreutils.wasm` (10.8 MB, built in 16 files) was run by hand: `cp`, `mv`, `ln`, `mkdir`, `rm`, `touch`, `sleep`, pipes of `sort`/`wc`/`head`, not in the tests |
| py-wasmhost `wasi_sh`, `wasmclang`, `pyodide`, `jslinux` | a shell, a compiler, an engine in an engine | not yet | not tried; `wasi_sh` is the shell over `coreutils`, the others need more than WASI |

### Build time of a large module

`coreutils.wasm` (10.8 MB, from py-wasmhost) gives 137 MB of C (3.1 million lines, 12.7 times the size of the module) from `wasm2c` in seconds;
then one `gcc -O2 -g` process, on one core, works on that one file (1.3 GB of memory). **It was stopped by hand after 33 minutes without
finishing**: not practical as it is. `lua.wasm` (329 KB) takes 44 seconds. For a user this is paid once, by whoever builds the wheel; for
`wasmimport` (a build at import) it hurts. The numbers are of one machine (4 cores, gcc 13). Ideas, not built:

- **Split the C and compile the parts in parallel: built.** `wasm2c --num-outputs=N` writes N files; wasmext has its own `build_ext`
  (`wasmext._setuptools`, put in by the entry point of the hook) that compiles the sources of such an extension in a pool of threads
  (`WASMEXT_JOBS`, else `-j`, else the number of processors) and then links. `natify(..., parts=N)`, `--parts N`, `WASMEXT_PARTS`,
  `wasmimport.install(parts=N)`: None is automatic, 1 turns it off. Automatic: a module under 1 MiB is one file (a split costs the
  inlining of calls between the files: CoreMark 25 848 whole and 24 124 in 4 files, 6.7% slower, one run each), a larger one gets a file for
  each 128 KiB (at most 256). A number asked for has no upper limit and is only warned about (more files than functions, or less than
  4 KiB of the module in a file). A tree with another number of files is made again (the old files are removed); where there is no
  wasm2c, the tree that is there is used.

  **Measured** (4 cores, gcc 13 `-O2 -g`, 4 files compiled at a time, wall time and processor time of the compile and the link, one run for each point):

  | files | `lua.wasm` (329 KB) wall / cpu, s | `coreutils.wasm` (10.8 MB) wall / cpu, s |
  | --- | --- | --- |
  | 1 | 27.1 / 27.4 | not done in 33 min |
  | 2 | 15.1 / 24.4 | |
  | 4 | 9.8 / 24.5 | |
  | 8 | 7.3 / 24.1 | 175.9 / 607 |
  | 16 | 8.1 / 26.1 | 177.5 / 603 |
  | 32 | 7.0 / 24.4 | 183.5 / 585 |
  | 64 | 7.2 / 24.9 | 149.3 / 560 |
  | 128 | 8.5 / 27.4 | 147.8 / 547 |
  | 256 | 10.6 / 33.3 | 150.6 / 553 |

  For `lua` the time falls up to the number of cores, is flat from 8 to 64 files and rises from 128 (2.6 KB of the module in a file; 12% more
  processor time, and 36% at 256). For `coreutils` more files kept helping up to 64 (a better balance of the files among the cores:
  148 s against 177 s at 16) and did not hurt up to 256 (42 KB of the module in a file). So the limit is in the size of a file and not in
  their number: 4 KiB of the module is the line of the warning, 128 KiB is what the automatic choice aims at. The ideal for
  `coreutils` is 553 s / 4 cores = 138 s; the rest is the longest files and the link. These are the numbers of one machine.
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
   riscv64, ppc64le, i686 work; s390x, big-endian, does not for modules with a memory export). Those are in CI now (armv7l, i686, ppc64le, riscv64: coremark only, see "Verified"); s390x is not. Windows x86 is in the matrix and green.
6. Android and Pyodide in the CI matrix of the example: done (Android is built, not tested); `pyproject.toml` configuration (no `setup.py`): done;
   publishing on PyPI (the workflow publishes on a tag; the publisher is not set up yet); `.wat` as a source (an idea, see "Build and distribution").
7. `funcref`/`externref` in signatures (a design is needed first: who owns an `externref`); custom page sizes (`wasm2c` can, with a
   flag); the rest of the examples of other projects (below).
8. ~~**WASI**~~ (`wasi_snapshot_preview1` and `wasi_unstable`): done for WASI 0.1. Part of wasmext, compiled into the native module as a header, `wasi_preview1.h`, the system
   reached through `Python.h`; 42 of 46 calls, the official tests pass on Linux, macOS and Windows; see "Design: WASI". Left: the clocks of the process and the thread in `poll_oneoff`, sockets (the specification allows them, on a socket the host gives to the program; wasmext gives none: its `wasi=` has only directories), WASI 0.2 and 0.3.
9. **A native path to files on Windows** (now through Python; with the split of the layers, below, the core of WASI needs no interpreter). `NtCreateFile` relative to a directory handle, as cap-std does: it would give the safety of `openat` there
   (no gap between a check and a use) and the speed. Not started; first measure what the Python way costs on Windows (it was not measured).
10. **C first** (decided, not started): the core of the glue and the core of WASI as plain C with hooks, the exports and the hooks in a Python layer
   (see "Decisions"). The first step is the split of `wasi_common.h`; a shared library and a C runner for the WASI test suite follow when
   something needs them.

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
function also the `instance` pointer and the `signature` (`"ii>i"`: `i j f d o`); and `runtime`, the fingerprint of the layout of the structs of the wasm2c runtime. For a global `type` is the value type of the binary
format (`0x7F` is i32) and bit 0 of `flags` says it is mutable; for a memory `type` is `sizeof(wasm_rt_memory_t)` and `flags` has memory64
(bit 1) and guard pages (bit 2). A function is called as `result f(void *instance, parameters..., int *trapped)`, which catches the
trap with the jump buffer of the exporter, so each extension handles its own traps. The format is a contract between versions of wasmext,
so it is versioned from the first day; an unknown version, or a `size` smaller than the reader knows, is a `LinkError`, not a guess.

**Keeping the contract still.** Changing it means a new `v2` and every extension built before it fails to link with the new
ones, so it is made to change rarely: the record begins with its own `size`, and new fields are only appended (a reader checks
`size` before it reads one: an old reader ignores the fields it does not know, and a new reader refuses a record smaller than its own
struct with a `LinkError`, as the code does today; it does not guess what an old record would have held); the entries are a
fixed-size record with a `kind` and room for flags; the pointers are those of wasm2c (`u32 *`, `wasm_rt_memory_t *`,
`wasm_rt_funcref_table_t *`), so wasmext adds nothing of its own to what must stay the same. The name `wasmext.export.v1`
changes only if a field is *removed or changes meaning*, which should never be needed.

**Checks, all at instantiation, all `LinkError`**: the export exists; it has the kind the import asks for (a function is not a
global); the types are equal (`i32` ≠ `i64`, mutable ≠ immutable, the signature of a function); for a memory, the limits of the
import are satisfied (initial and maximum pages, memory64 equal). For a table (not built) the element type and limits would be checked too.

**Lifetime.** The importer holds a strong reference to the exporter, so the pointers stay valid as long as it lives. A cycle
(a imports from b and b from a) is not possible at instantiation, because an instance has to exist before it is given; an
instance takes part in the cycle collector already, and the reference is visited in `tp_traverse` and cleared in `tp_clear`.
`wasm2c_<m>_free` of the exporter must not run while an importer lives: guaranteed by the reference.

**Memory.** The memory object is the same, so `a.mem` and `b.mem` are `memoryview`s of the same bytes. A `grow` by either is seen by
both (the struct is shared); a view taken before the grow is the old size, as it is today (a new one after).

**Functions between instances.** The glue of the importer calls `w2c_<provider>_<name>` of the other extension through the table of
the capsule, so the traps cross: a trap in the callee unwinds to the call from Python, as when a Python callable calls back. The
jump buffer is per thread and the call goes on the same stack, so the existing `ENTER_WASM`/save-and-restore applies; a trap in the callee comes
out as the `Trap` of its module through the caller, and both instances go on (`test_instances_call_each_others_functions_directly`).

**Not covered (and why that is fine for now)**: a global, memory or table made by the host with no module behind it (a small
object would be needed; postponed until somebody needs it); `externref` tables; threads and `shared` memory (the pointer is shared,
but not made atomic: that is plan item 4 and changes the layout, so this design must not rely on plain reads of a mutable global
once threads exist); instances from different wasmext *builds* with different wasm2c runtimes (the structs of `wasm-rt.h` have to
match: the record has a fingerprint of their layout, `runtime` (the sizes and offsets of `wasm_rt_memory_t` and the size of the table struct), and an import
from an extension with another one is a `LinkError`: `test_an_export_of_another_wasm2c_runtime_is_not_linked`). It is the layout that is compared, not the version of WABT.

**Order**: 1. imported mutable globals from an exporting instance (smallest: a pointer and a type check; also removes the "refused
when the extension is made" for them); 2. memories; 3. functions: these three are built, in this order; 4. tables: not built.

**Decided**: the forms above; the format of the link table (capsule) is private, documented and
versioned (not a promise to others) until a second user of it exists.

## Design: WASI

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
differs only where Python itself differs. The rule is applied call by call; the table is what was built, and the official tests of WASI
run on it in CI (Linux both ways, macOS, Windows):

| Way | Calls | Why |
| --- | --- | --- |
| direct | `args_*`, `environ_*`, `sched_yield`, `fd_prestat_*`, the bookkeeping of descriptors, `fd_seek`/`fd_tell`, `fd_read`/`fd_write` on the descriptors it opened | data of the instance, or the same call on both |
| plain C (was through Python until the decision on `wasi=`) | `random_get`, `clock_*`, the sleep of `poll_oneoff` | the source differs between systems and none of it needs the interpreter: `/dev/urandom` (`arc4random_buf` on macOS, `BCryptGenRandom` on Windows), `clock_gettime` (`QueryPerformanceCounter`, `GetSystemTimePreciseAsFileTime`, `GetProcessTimes`, `GetThreadTimes` on Windows), `nanosleep` (`Sleep`) in slices of 100 ms with the interpreter released, so that Ctrl+C is seen. A function the caller gives (`clock`, `random`) replaces them |
| directly, where the system has `openat` (decided on a measurement, see below) | `path_open`, `path_filestat_get`, `fd_filestat_get`, `fd_readdir` | a directory is an open descriptor and a path is walked from it one name at a time; no interpreter |
| through Python (Windows; and anywhere with `-DWASMEXT_WASI_PYTHON_FS=1`, for the tests) | the same calls, and the ones of the later stages | Windows has no `openat`; it cannot open a directory with `open`, has its own `stat` (no inode), `FindFirstFile` for a listing, other rules for renaming over a file; symbolic links need a privilege |
| through Python (decided) | `fd_read`/`fd_write` on the standard streams | direct writes to descriptors 1 and 2 bypass the buffer of `sys.stdout` (the order against Python's `print`, a capture in a notebook or a test), so by default they go to `sys.stdout.buffer` after a flush of `sys.stdout` |

**What it covers.** The 46 functions of the specification (`wasi_snapshot_preview1.witx`, the branch `wasi-0.1` of WebAssembly/WASI;
the files are in `tests/data/wasi/` of py-wasmhost, with their licence): arguments, environment, clocks, `random_get`,
`proc_exit`, `sched_yield`, `poll_oneoff`, the `fd_*` calls, the `path_*` calls. Sockets, signals and threads answer as the
specification allows (`ENOTSOCK`, `ENOSYS`). The first snapshot, `wasi_unstable` (what `lua.wasm` imports), has the same
functions but `sock_accept`, and four differences in what it reads and writes: the order of `whence` (cur, end, set), one right less,
`filestat` with a 32-bit link count (which moves its fields), and a clock subscription with an extra `identifier` (56 bytes). So the
two files differ in the few calls that touch those (`fd_seek`, `fd_fdstat_get`, `fd_filestat_get`, `path_filestat_get`, `poll_oneoff`);
the rest is common. A private header holds the common part, which both headers include, so that they cannot drift apart (`wasi_common.h`); the four that differ have a
function of their own in `wasi_unstable.h` (`fd_seek`, `fd_filestat_get`, `path_filestat_get`, `poll_oneoff`), and the rest serves both snapshots. A module gets only the functions it imports, so a module
without WASI contains none of it. The state (file descriptors, preopens) is in the instance, not in globals.

**Staged (all three built).** First what is the same everywhere: standard streams, arguments, environment, clocks, `random_get`, `proc_exit`. Then
files and directories (`fd_*`, `path_*`) with preopens that confine the program to a directory: reading, then writing and creating. Last the links, `pread`/`pwrite`,
renaming and `poll_oneoff`.

**Reference for behaviour.** The witx files give the names and signatures; the oracle is the official test suite (below), not `wasmhost.wasi.preview1`
(plain Python, MIT), which was meant to be run beside it and was not. Its code is not copied: this is written from the specification.

**Decided (the first version).**
- Configuration is a keyword of the instance, `Instance(imports, wasi={"args": [...], "env": {...}, "preopens": {"/": "dir"},
  "stdin": ..., "stdout": ..., "stderr": ...})`.
- Standard streams go to `sys.stdin.buffer`, `sys.stdout.buffer` and `sys.stderr.buffer` by default, so that capturing in a notebook or
  a test works, and an object with `write(bytes)` replaces one.
- `proc_exit(n)` is an exception (`WasiExit`, carrying the code) out of the call that led to it; `proc_raise(signal)` is `WasiSignal` (`.signal`, `.name`); both are a `WasiTerminated`. The program is over: see "The end of a program" in "Decisions".
- The command `_start` is called as an export, as any other (no `run()` helper in the first version).
- Test modules: `lua.wasm` (wasi_unstable, 19 imports) first, then `coreutils.wasm` (preview1, 32 imports, 10.8 MB, which makes a very large
  C file and a long build). Both were built and run: `lua.wasm` is `examples/lua`, `coreutils.wasm` was run by hand (built in 16 files).

**Stages 1, 2 and 3 (built).** `src/wasmext/c/wasi_common.h` with `wasi_preview1.h` and `wasi_unstable.h`, copied beside the C of a module that
imports WASI and included by its glue (the glue calls the functions directly, through the slots that linking instances uses). The calls
that work: `args_*`, `environ_*`, `clock_res_get`, `clock_time_get`, `random_get`, `sched_yield`, `proc_exit` (raises the module's `WasiExit`,
`.code`), the standard streams (`fd_read` on stdin, `fd_write` on stdout and stderr), and for files and directories: preopens
(`wasi={"preopens": {name: directory}, "readonly": ...}`), `path_open` (reading, creating, truncating, writing, append), `fd_read`, `fd_write`, `fd_seek`, `fd_tell`, `fd_close`, `fd_renumber`,
`fd_advise`, `fd_fdstat_get`, `fd_filestat_get`, `path_filestat_get`, `fd_readdir`, `fd_prestat_get`, `fd_prestat_dir_name`, and (stage 2) `fd_sync`, `fd_datasync`,
`fd_allocate`, `fd_filestat_set_size`, `fd_filestat_set_times`, `path_filestat_set_times`, `fd_fdstat_set_flags`, `fd_fdstat_set_rights` (rights can only
be given up), `path_create_directory`, `path_remove_directory`, `path_unlink_file`, and (stage 3) `fd_pread`, `fd_pwrite`, `path_rename`, `path_link`, `path_symlink`, `path_readlink`, `poll_oneoff`, and (stage 4) `proc_raise`: 42 of the 46 calls
and, with the answers the specification allows, all of them: the four `sock_*` are `ENOTSOCK` (`EBADF` for no such descriptor), as in
wasmhost. `poll_oneoff` sleeps in C (the interpreter released, a signal seen every 100 ms) until the first clock; descriptors of files, directories and standard streams are always ready;
the first snapshot has its own (a clock subscription with an identifier, 56 bytes). A symbolic link is made with a relative target only (an absolute one is
`ENOTCAPABLE`), and one that points out is not followed. `pread`/`pwrite` use the system calls; Windows seeks, does it and seeks back; `rename` replaces
a file in the way (`os.replace` on the Python path). On POSIX these go straight to the system (`write`, `mkdirat`, `unlinkat`, `utimensat`, ...) after the same walk that confines a path. Rights are kept per descriptor (`readonly` takes the
mutating ones away), and a directory descriptor is a capability for that directory: `..` out of it, an absolute name, or a link that
leads out are `ENOTCAPABLE` (an absolute link inside is refused too, as in cap-std). Both snapshots are served (`sock_accept` is not a call of the first:
`GenError`); the first has its own `fd_seek` (another order of `whence`) and `fd_filestat_get`/`path_filestat_get` (56 bytes). `Instance()` needs no
imports; `wasi={...}` takes args, env, stdin, stdout, stderr, preopens, readonly. What the caller gives as an import wins, call by call.
**The official tests.** The precompiled programs of [WebAssembly/wasi-testsuite](https://github.com/WebAssembly/wasi-testsuite) (`prod/testsuite-base`, commit
`d552798`, WASI 0.1: AssemblyScript, C and Rust, 72 programs; the 55 of WASI 0.3 are skipped) run on wasmext: `tests/wasi_testsuite/adapter.py` is the
adapter for the runner of the suite, `run_wasmext.py` builds one program into a native extension (without optimizing) and runs it, and `prebuild.py` builds all
of them at the same time first (the runner kills a program after its timeout, and the first run of a program is a build). CI (`.github/workflows/wasi-testsuite.yml`)
runs it with `wasmext` on Python 3.11 and the runner on 3.12 (it needs it): **all 72 pass** on Linux (both ways of reaching files: `openat`, and Python, as a
fourth job), macOS (the suite told to expect the errors of macOS, `ERRNO_MODE_MACOS`) and Windows. On Linux the suite is told `ERRNO_MODE_UNIX`; on Windows it
is not told `ERRNO_MODE_WINDOWS` (that mode asks for the errors of a system that is not POSIX, where wasmext gives those of POSIX, so any error of the systems is
taken) but `NO_RENAME_DIR_TO_EMPTY_DIR`. One test is expected to fail on Windows (`expectations-windows.toml`): `symlink_filestat`, because Python before 3.13 cannot set the
times of a link itself.

What they found, that our tests had not: the same function imported twice (AssemblyScript; a duplicate in the glue); a directory opened with all the rights of its
preopen (a retry as a directory on `EISDIR`); the rights of an opened directory (no seek); a trailing slash (`file/` is `ENOTDIR`, and a name to be made that has one is
`EEXIST`, `ENOTDIR` or `ENOENT`); `fd_renumber` of the standard streams; `pwrite` on a file opened for writing only (no `fd_seek` is asked for); and, on Windows (the Python way),
`os.utime` of a file by its descriptor (it has none: the path is kept), the inode of `.` and `..` in a listing, no `O_NOFOLLOW` (a link is not opened without following it: `ELOOP`, checked by hand), links made with `/`,
`O_APPEND` (it cannot be taken off again: `fd_write` seeks to the end), `os.link` that does not follow a link, and the times of a link (`follow_symlinks=False` only for a link).
It also found that the runner kills a program after 5 s unless the adapter says more, and that what a killed program started goes on on Windows and held the runner for 30 minutes.
Not built: sockets, threads, and the clocks of the process and the thread in `poll_oneoff`. Tests: `tests/test_wasi.py` and `tests/test_wasi_fs.py` (through `build_extension`, not on
Windows; the file tests are run for both ways of reaching the file system), `test_a_wasi_module_is_built_with_the_wasi_header_of_wasmext`
and `test_wasi_files_work_on_every_platform_of_ci` (the whole path, every platform of CI). `lua.wasm` (imports `wasi_unstable`) is built and run by `examples/lua` (its tests, and the wheels of CI).

**The cost of a call, measured** (Linux x86-64, Python 3.11, gcc -O2, medians; a loop in WebAssembly that makes the call). First version,
where every path went through Python (`os.stat`, `os.path.realpath` for the check of the limits): `path_filestat_get` 17.5 us, `path_open` +
`fd_close` 18.9 us, `fd_readdir` of 101 names 224 us; 13 us of the first were the `realpath` of the check alone. After the move to `openat`:
0.87 us, 1.6 us and 30 us (the floor in C for the listing is about 18 us). `fd_read`/`fd_seek` on a file (direct since the beginning) 0.1 us;
`clock_time_get` (measured when it went through Python, `time.time_ns`; it is plain C now and was not measured again) 0.14 us; a call of WebAssembly into a C function 3 ns. The way through Python costs 0.1 to 0.9 us
over the system call itself for a simple call; that was the reason to keep the clocks and the random bytes there, until the decision that what needs no Python is C. (An earlier figure of "190 times"
for the listing came from a wrong baseline and is withdrawn.) Windows is on the Python way and was not measured; a native path for it (`NtCreateFile` relative to a directory handle, as cap-std does) is possible, would be 600 to 900 lines of C that can be tried only in CI, and is not written.

### What the C layer does by itself, and what waits for `wasi=`

How it is now (after the decision "The configuration of WASI" below). "Plain C" needs no interpreter, "C through `Python.h`" calls it; a key of
`wasi=` that is absent has the default of this table, `None` is nothing, and any part can be replaced.

| Part of the program's world | The default, and who gives it | `wasi=` | Built |
| --- | --- | --- | --- |
| Arguments (`args_*`) | `[the name of the program]`; plain C | `args` (`None`: none) | yes |
| Environment (`environ_*`) | empty; plain C | `env` | yes |
| `stdin`, `stdout`, `stderr` | `sys.stdin`, `sys.stdout`, `sys.stderr` of the moment; C through `Python.h`, in the binary layer, after a flush of the text layer | `stdin`, `stdout`, `stderr` (`None`: an empty input, an output thrown away; a text stream given explicitly works the same way) | yes |
| Clocks (`clock_*`) | those of the system; plain C | `clock` (a function: id -> nanoseconds; no `None`) | yes |
| Random bytes (`random_get`) | those of the system; plain C | `random` (a function: how many -> bytes; no `None`) | yes |
| Sleeping in `poll_oneoff` | the interpreter released, slices of 100 ms; plain C | (the call) | yes |
| `proc_exit` | raises `WasiExit` with the code; C through `Python.h`. The program is over: its descriptors are closed at once, a call after it is `WasiTerminated` | (the call) | yes |
| `proc_raise` | `WasiSignal` (`.signal`, `.name`); a signal that nothing ends (none, the child, continue, the stops, urgent data, the window size) is a success and the program goes on | (the call) | yes |
| Files and directories | none (the POSIX walker is plain C, on Windows C through `Python.h`) | `preopens`, `readonly` | yes |
| Sockets | none (`sock_*` give `ENOTSOCK`) | (postponed, see "Decisions") | no |

Whatever is not in `wasi=` can be replaced call by call through `imports`.

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
- WASI is hand-written C in the module (see "Design: WASI"): not a shim in Python, and not an existing C implementation (uvwasi, which WABT uses
  itself for `wasm-interp`, was named here as the option if WASI came back; what was decided instead is header-only C compiled into the module, so
  that a built module needs nothing at run time).
- **The configuration of WASI (`wasi=`).** One rule: every part of the world of the program has a default, given by the extension itself (C,
  compiled into the module), and the user may replace any of it. What needs no Python is plain C (the clocks, the random bytes, sleeping in
  `poll_oneoff`, the arguments, an empty environment, the files of POSIX); what needs the interpreter is C through `Python.h` (`sys.stdout` and
  the other standard streams, the exception of `proc_exit`, the files of Windows); only what cannot be guessed comes from the user (which
  directories, which addresses). Nothing is required of the user, and only the call can configure it (not the build, at least in the alpha).
  The form is a plain `dict`: an absent key is the default, an explicit `None` is *nothing* (arguments: none; output: thrown away; input:
  empty; files: none), so the two never mean the same. The default is worked out in C when it is used (a stream is `sys.stdout` *of that
  moment*, so a capture in a test or a notebook sees it): no Python object, class or factory is part of the built module, and a built module
  needs nothing of wasmext, nor of any other package, when it runs. `wasi=` is typed only in the `.pyi`, as a `TypedDict` with
  `NotRequired[...]` keys, the same for every module that uses WASI whatever it imports (the imports say which calls a module *can* make, not
  what it needs; a key the module does not use is accepted and ignored, an unknown key is a `TypeError`). Streams are typed with
  `_typeshed.SupportsRead[bytes]` and `SupportsWrite[bytes]` (output may also be a `Callable[[bytes], object]`), not with protocols of our own.
  Nothing is `Required`. Every other part of the program's world is replaced the same way: through a key (`clock`: id of the clock ->
  nanoseconds, `random`: how many -> that many bytes; neither takes `None`, which would mean a clock that stands still), or call by call
  through `imports`. A text stream (sys.stdout, a `StringIO`) given explicitly works as the default does: it gets the bytes through its
  binary side, after its text layer is flushed, or as text where it has none.
  *Built:* all of the above, and the end of the program (below).
- **The end of a program.** `proc_exit` and `proc_raise` end it, as on the operating system: the exception carries the code or the signal
  (`WasiExit`, `WasiSignal`, with a common base), the C closes at once every descriptor the program opened (files, directories and, when
  they are there, sockets; not what belongs to the user: `sys.stdout`, a stream the caller gave, the directories of the preopens are
  flushed, not closed), the instance is marked finished, and a call into it afterwards raises an error that says so. A trap ends the
  program too, but only a command (a module that exports `_start`): the trap of a function of a library is a trap, and the instance goes on. (A command
  is called once by the specification; this replaces "the instance stays usable after `proc_exit`".) *Built.* What the exception says of the signal: `.signal` is
  the number in WASI 0.1 and `.name` is `SIGABRT` and so on; the signals that would not end a process (none, the child, continue, stop and the stops of a
  terminal, urgent data, the window size) are answered with success and the program goes on. The stub: `WasiTerminated`, `WasiExit`, `WasiSignal`.
- **Sockets: postponed.** The idea (addresses to listen on in `wasi=`, the sockets made in C, handed to the program as descriptors after the
  preopened directories, for `sock_accept`, `sock_recv`, `sock_send`, `sock_shutdown`; no connecting out, the first snapshot has no call for it) was
  not built, for want of anything to compare it to: the preview1 of today's wasmtime (`crates/wasi/src/p1.rs`) has no sockets ("sockets are not
  currently supported"), `--tcplisten` of its CLI is "experimental, legacy wasip1 implementation only" (how that one numbered the descriptors was not
  found out), and the official test suite has no test of sockets for WASI 0.1 (those it has are for 0.3). The design would be ours alone, and a public
  interface that nothing checks. The four `sock_*` stay `ENOTSOCK`. To be taken up when a program needs them.
- **C first: the layers do not depend on `Python.h`; only the exports of the module and the hooks do (the direction is decided, nothing of
  it is built).** Four layers, each knowing only those below it:
  1. the C of `wasm2c` (already plain C: the instance, the exports as C functions, the imports as C functions, the memory);
  2. the **core of the glue**, plain C: the life of an instance, the traps (`setjmp`), the table of the imports (`h->lf[]`, `h->li[]`), the
     export record of the link (`wasmext_export` is a C struct already: the capsule `wasmext.export.v1` is only how Python carries the
     pointer), memory and tables as C views;
  3. the **core of WASI** (`wasi_core.h`), plain C: the table of descriptors, the walk of paths (`openat`; a native path for Windows),
     arguments, environment, clocks, random bytes, `poll_oneoff`, the end of a program. Whatever needs the world outside it is a **hook**
     (a table of function pointers the host fills in): reading and writing the standard streams, a function that replaces a clock or the random
     bytes, the report of an error, the end of a program (`proc_exit`, `proc_raise`), the check that the host wants to interrupt a sleep;
  4. the **Python layer** (needs `Python.h`): the types `Instance` and `Memory`, the methods of the exports (the conversion of arguments and
     results), the imports given as Python callables, the memory as a `memoryview`, the exceptions (`Trap`, `LinkError`, `WasiExit`,
     `WasiSignal`), the dict `wasi=` turned into the configuration of the core, the capsule, and the **implementation of the hooks** with the
     Python API (`sys.stdout`, an object with `write`, the exceptions, `PyErr_CheckSignals`).
  What it is for: the same layers 1 to 3 give a **shared library** (`.so`/`.dll`: a module with a C API for `ctypes`/`cffi`, Rust, Go, with no
  Python in it) and a **C runner** (`wasmext-run module.wasm`) that runs the official WASI test suite with no Python in between (the suite is
  run through a Python adapter now, which is what made the Windows job slow), as well as the extension for CPython that the project is for.
  Where it stands now: in `wasi_common.h` (2860 lines) 49 of the 135 functions mention Python (stdio through `sys.stdout`, the configuration, the
  exceptions, the files of Windows through `os`, the user functions for the clock and the random bytes); the rest is plain C already. The
  files of Windows are the last place where the core needs the interpreter for data, which is why the native path to files on Windows
  (the plan, item 9) and this split are one piece of work from two sides. The first step is the split of the WASI header, not of the whole
  glue, and it comes when something needs a host that is not Python (the runner, a shared library); the Python layer stays as it is, and the
  hooks are `static inline` so that the split costs no call (to be measured). The contract of the link between two instances keeps its form;
  a C host would carry the same record in its own way.
- `wasmhost` is a different tool (a facade over engines); its API is a guide for names and errors, the reference for behaviour
  is the specification and the JavaScript API.
