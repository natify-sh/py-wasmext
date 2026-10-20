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
| `v128` in a signature | done | 16 bytes in the order of WebAssembly memory: `bytes` (or any bytes-like object of 16 bytes) in, `bytes` out; a wrong length is a `ValueError`, another type a `TypeError`. In exported and imported functions, multi-value, exported globals and imported immutable globals. Not on big-endian hosts (`#error`; the byte order of a v128 there is not checked). `test_v128_in_signatures_globals_and_imports` **Added since:** in the shared library the same functions (exports, imports, multi-value) take and give a v128 as 16 bytes behind a pointer (`const uint8_t *` in, `uint8_t *` out, the same order); the wrapper for ctypes turns them into `bytes` as the extension does (`test_v128_in_signatures_is_16_bytes_in_each_front_end`, on both). Left out of the library: a global of that type and the link of such a function to another instance |
| JavaScript BigInt to i64 | n/a | a part of the JavaScript API; here an `i64` is a Python `int` |

### 3.0

| Feature | Status | Note / test |
| --- | --- | --- |
| Tail calls | done | `3.0 tail calls`, and with locals `3.0 tail calls in a function with locals` (wasm2c 1.0.42 writes C that does not compile for a function that has locals and a `return_call`: wasmext repairs it, the pattern matches only that shape; `coremark-minimal.wasm` of pywasm3 needs it) |
| Extended constants | done | `3.0 extended constants` |
| Multi-memory | done | `3.0 multi-memory` |
| memory64 | done | inside the module, exported as a `memoryview`, addresses above 4 GiB (Linux): `3.0 memory64`, `test_an_exported_memory64_is_a_memoryview_too`, `test_memory64_addresses_above_4_gib` |
| 64-bit tables (the address type of tables, with memory64) | done inside the module | `3.0 memory64, a 64-bit table`; a table is not exported yet |
| Exception handling, legacy `try`/`catch` | done | `3.0 exceptions`; an exception nobody catches is `UncaughtException`, a `Trap` with `.tag` (the index of the tag in the module) and `.values` (a tuple of Python numbers; empty for a tag with none): `test_an_exception_that_nothing_catches_is_an_uncaught_exception_with_its_tag_and_values`, and through `natify` in one file or in several: `test_uncaught_exceptions_are_told_apart_by_the_whole_path_in_one_file_or_several`. This form is not in the specification, but compilers still make it. Not done: the name of an exported tag, the tag of another module (`.tag` is `None`, no values), the values of a tag with a reference type (none), importing a tag from the host |
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
| Parameter names in the stub | done | The parameters of an exported function are named as the "name" section of the module names them (`wat2wasm --debug-names`; compilers write it in a build with debug info), as `add(self, left: int, right: int, /)`; else `arg0, arg1, ...`. The name section is only a hint, and a module with a broken one is read as one without. The names are used all or none: if one parameter has no name, is not an ASCII identifier, is a keyword, `self` or starts with `__`, or two are the same, all of the function get `argN`. They are positional-only (`/`), so the names are for the reader and the editor: a call by keyword is not possible |
| `wasmext natify` and `wasmext inspect`, commands (`wasmext --help`) | done | `natify` writes the C and, with `-i` or `-b`, builds; there is no command by file names alone. A place for the next ones: `natify --shared` (a shared library with no `Python.h`, see "C first") and the bindings for `ctypes` |
| `wasmext inspect` | done | what a module imports and exports and what wasmext makes of it; writes nothing |

## Build and distribution

| Feature | Status | Note |
| --- | --- | --- |
| `natify()` for `setup.py` | done | like `cythonize()` |
| `wasmext` command (`-i`, `-b`, `-f`, `-q`, `-X`, `--build-dir`, `--parts`, `--limited-api`, `--guard-pages-for`, `--shared`, `--exe`) | done | `-q` also silences the warnings of the compiler for the C of wasm2c; `--shared` / `--exe` are exclusive, one product for each run, and imply `-i` |
| Regeneration as `cythonize` does it | done | the first line of the C names the wasmext and the WABT that made it; made again when missing, made by another version, older than the `.wasm`, or forced (`force`, `-f`, `WASMEXT_FORCE_REGEN=1`) |
| abi3 (cp311) and native wheels | done | chosen by the interpreter that builds: `abi3_possible()` asks its extension suffixes (as setuptools does) and keeps Emscripten, Android and iOS native by decision; free-threaded and PyPy are native. **One setting for the whole wheel** (`[tool.wasmext] limited-api`, `natify(limited_api=)`, `--limited-api`/`--no-limited-api`, `WASMEXT_LIMITED_API`): the modules of wasmext follow a hand-written extension that is not abi3, settings that contradict each other are an error; the wheel is tagged abi3 only if every Python extension in it is. Measured on one machine (CPython 3.11, gcc -O2): calls and wasm code are the same as native, a host callback is about 5% slower |
| Guard pages, by architecture | done | decided when the C is compiled, for the architecture of the target (`sysconfig.get_platform()`, so a cross build is right): a bool or `{"x86": false, "default": true}` in `natify(guard_pages=)`, `guard-pages` of `pyproject.toml`, `--guard-pages-for x86=off,...`, `WASMEXT_GUARD_PAGES`; off is for processes with a limit on address space and 32-bit targets, about 30% slower on CoreMark; no switch while it runs (that would need both versions of the code) |
| WABT from the wabt-package | done | or a directory in `WASMEXT_WABT` (`bin/wasm2c`, `wasm2c/` with the runtime, `include/` with `simde/`) |
| Each part of the toolchain by its variable | done | `WASMEXT_WASM2C` (the executable), `WASMEXT_WASM2C_RUNTIME` (the directory with `wasm-rt.h`), `WASMEXT_WASM2C_INCLUDE` (the directory with `simde/`, for SIMD modules). Each is taken from its variable, else from `WASMEXT_WABT`, else from the wabt-package; with the executable and the runtime given, the wabt-package is not needed. The version (in the first line of the C and in `wasmext --version`) is what `wasm2c --version` says, `unknown` if it does not run. The runtime directory must have `wasm-rt.h`, `wasm-rt-impl.c`, `wasm-rt-mem-impl.c`, `wasm-rt-mem-impl-helper.inc` and `wasm-rt-exceptions-impl.c` (else an error that names what is missing). Tried: the three variables with the wabt-package made unimportable (`natify -i`, the extension runs; the first line of the C says `WABT 1.0.42`, from `wasm2c --version`); only `WASMEXT_WASM2C` without a runtime is the error that says what to set. **Debian/Ubuntu `wabt` 1.0.34 does not work**: it splits the runtime (headers in `/usr/include`, sources in `/usr/share/wabt/wasm2c`; copied into one directory they were refused) and has no `wasm-rt-mem-impl*` at all, so wasmext needs WABT 1.0.42 or later, as the wabt-package. Not checked: that the runtime is of the version of the executable: the 1.0.34 executable with the 1.0.42 runtime built an extension that ran (`add(40, 2) = 42`) with compiler warnings; that is luck, not a promise. Windows and macOS system packages not tried. 3 tests |
| Patch for MSVC on ARM64 and x86 | done | `_addcarry_u64` exists only on x64 (not on ARM64 and 32-bit x86); a regex in `_natify.py`, applied to the shared `_w2c-impl.h` of a module in several files too (it was missed there, and `lua` did not link on Windows x86 and ARM64) (reported: [WABT #2885](https://github.com/WebAssembly/wabt/issues/2885)) |
| Patch for `return_call` in a function with locals | done | wasm2c writes C that does not compile; a regex in `_natify.py` puts the type back, and passes a fixed wasm2c through (reported: [WABT #2884](https://github.com/WebAssembly/wabt/issues/2884)) |
| Large modules in several files | done | `wasm2c --num-outputs`, compiled at the same time; automatic from 1 MiB, `parts=` / `--parts` / `WASMEXT_PARTS`; see "Build time of a large module" |
| Example: CoreMark | done | reference CoreMark of EEMBC, built with `zig cc` by `examples/coremark/build_wasm.py` |
| Example: link | done | two modules that use each other's memory, variable and function (`examples/link`) |
| Example: Lua | done | `lua.wasm`, a WASI program, built in 8 files (`examples/lua`); tests on the wheel, and the wheels, in CI on seven platforms |
| Example: WABT (`wat2wasm`, `wasm2c`) | done (locally; not in CI) | `examples/wabt`: WABT 1.0.42 built with `zig c++` as WASI programs (1.3 MB each), turned into extensions by wasmext in 8 files each; `wabtwasm.wat2wasm()` and `wasm2c()`; the output is the same bytes as the native tools' (the C of `qjs.wasm`, 17.3 MB, compared byte by byte; 0.42 s against 0.24 s for the native `wasm2c`). `python -m wabtwasm toolchain DIR` makes a directory for `WASMEXT_WABT` whose `bin/wasm2c` runs the extension: `wasmext natify` then translates with a `wasm2c` that wasmext built (checked on `coremark-minimal.wasm`; POSIX, because `bin/wasm2c` is a shell script). One copy was changed to build it: `picosha2.h` without its function for `std::ifstream`. 7 tests |
| Example: QuickJS | done | `qjs` of QuickJS-ng v0.17.0 (1.1 MB), a WASI program built with `zig cc` from the sources of the tag (`examples/quickjs/build_wasm.py`), in 4 files; a real `proc_exit` for the errors of a script, not a trap as in Lua; 9 tests on the wheel (a module imported from a directory, stdin, writes, a name that leaves the directory refused) |
| Example: products | done (CI: the seven platforms of the desktop matrix passed, run 289 on `a29d68f`, 3 tests each; also the same package built and tested locally by `cibuildwheel` on Linux i686 in `manylinux_2_28`) | `examples/products`: one wheel (`py3-none-<platform>`) with a shared library (`product = "shared"`, used through its `engine_ctypes` wrapper) and a WASI program (`product = "exe"`), from two `.wat` files; 3 tests on the wheel. `auditwheel` repairs it with no change (only `libc`/`libpthread`, `manylinux_2_5`) and the program, run from the repaired wheel, answers `hello, wasi` and status 3 |
| simde headers | done | from the wabt-package, see SIMD above |
| Pyodide wheel | done | `cibuildwheel --platform pyodide` on `examples/coremark`, Python 3.13: built and the tests passed inside Pyodide, locally and in CI (the job "coremark on Pyodide"); the `wasm2c` of the Linux x86-64 wheel of the wabt-package did the translation on the host, no Pyodide wheel of the wabt-package is needed |
| Android wheel | x86-64 tested, arm64 built | `cibuildwheel --platform android` in CI, Python 3.13, NDK 27, with the host wabt-package wheel. **x86-64**: built and its tests run (the job "coremark on Android x86_64": an emulator with KVM on the Linux runner, `test-sources = ["tests"]`, `test-command = "python -m pytest tests"`); it passed in CI (one earlier run failed in `sdkmanager` downloading the system image, a corrupt zip, and passed when run again). **arm64-v8a**: the wheel is built but its tests do not run: cibuildwheel tests on an emulator of the architecture of the build machine, so an arm64 wheel built on x86-64 is not tested. The extension links `libpython3.13.so`, as every Android extension does |
| Import hook, like `pyximport` | done | `import wasmimport; wasmimport.install()`; `import mod` finds `mod.wasm` (working directory, `sys.path`, packages), builds it into `~/.wasmbld` (or `build_dir`) and loads it. Options as in `pyximport`: `build_dir`, `build_in_temp`, `setup_args`, `inplace`, and those of `natify()`; `<module>.wasmbld` with `make_ext`/`make_setup_args`; `uninstall(finder)`, `clean()`. The cache (`<build_dir>/<cache tag>-<platform>/<name>-<hash of the path>/`) holds the extension (`lib/`), the C (`c/`) and a stamp of how it was built (`guard_pages`, `limited_api`, `parts`, the settings of the extension, `CC`/`CFLAGS`/`LDFLAGS`): a change of any of them makes the extension again, and a native file and an abi3 one do not shadow each other. Not taken from `pyximport`: `.pyxdep`, importing `.py` files (`pyimport`), `reload_support`, `load_py_module_on_import_failure`. A development tool: it runs a C compiler on import. `tests/test_importer.py` Where `import` is run from is not part of what makes a cached extension stale (for a few commits it was: `natify()` gives its include directories relative to the current directory, so a program imported from another directory was built again; the WASI test suite showed it, ten times slower on every system and a hang on Windows). |
| Configuration in `pyproject.toml` only | done | `[[tool.wasmext.ext-modules]]` (or one table `[tool.wasmext.ext-modules]`): the arguments of `natify()` with dashes (`module-list` is a string or a list) and, added to each extension, `extra-compile-args`, `extra-link-args`, `define-macros`, `undef-macros`, `include-dirs`, `libraries`, `library-dirs`; read by `wasmext._setuptools` (the entry point `setuptools.finalize_distribution_options`, as `setuptools-rust` does it for `[tool.setuptools-rust]`); unknown keys and a missing `module-list` are errors; `natify()` in `setup.py` together with the table is an error, other extensions of `setup.py` go with it. `[tool.wasmext]` has room for other hooks. Used by `examples/quickjs` (no `setup.py`); `tests/test_pyproject_config.py`. Like `cythonize()` and `mypycify()`, the C is made when the hook runs, which setuptools does more than once per build (the second time nothing is made again: the C is up to date) **Added since:** every value is type-checked and a wrong one names its key; `product` (`extension`, `shared`, `exe`); `guard-pages` is a bool or a table of architectures; `limited-api` is one setting for the project, in `[tool.wasmext]`, not in an entry. |
| Shared library with a C API, and a program (`product=`) | done | `natify(product="shared")` or `natify(product="exe")`, the `product` key, `--shared`, `--exe`; the `build_ext` of `wasmext._setuptools` makes the file where an extension would go (`lib<name>.so`/`.dylib`/`<name>.dll`, `<name>`/`<name>.exe`). A library has the header `<name>_api.h` and a `<name>_ctypes.py` wrapper with the interface of the extension; a program has `--env`, `--dir HOST::GUEST[:ro]`, `--argv0`, `--help`, `--version`, UTF-8 arguments on Windows, exit 134 on a trap. `tests/test_products.py`, `test_shared.py`, `test_exe.py`. **How it is made:** `natify()` writes every layer for any product (`_w2c.c/.h`, `_glue.h` with typed functions and no Python, `_py.c` for CPython); a library or a program leaves `_py.c` out of the sources and compiles `_shared.c` (with `_api.h`) or `_main.c` in its place, so the C of the extension is written but not built. A library is refused only where the C API has no type for it (nothing at present: a `v128` in a signature is 16 bytes behind a pointer). Not in the wheel by itself: `<name>_api.h` (use `package-data`); the library, the program and the wrapper are, and such a wheel is `py3-none-<platform>` (`examples/products`) |
| Wheel tag of a package with no Python extension | done | libraries and programs only: `py3-none-<platform>`, tested with a real `bdist_wheel`; a mix keeps the tag of the extensions |
| A memory that moves does not move under a `memoryview` | done | where the runtime reallocates a memory (no guard pages, memory64, another page size) `memory.grow` answers -1 while a view of it is alive (extension and ctypes; `<name>_memory_*_pin` for a C host) |
| The tests of the extension on Windows | done | `build_extension` builds by setuptools (as a user does) on Windows, and with `WASMEXT_TEST_SETUPTOOLS=1` anywhere; before, the whole extension front end was skipped there |
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

The whole suite (`pytest`, 531 tests and 4 expected failures at the time of writing: Linux locally, and the three systems in CI), `ruff` and `pyright`:

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
| Android x86-64 (CPython 3.13, NDK 27) | CI: the wheel is built and the tests run in an emulator (see "Android wheel") |
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
- Android: the tests of an arm64 wheel (it is only built, see "Android wheel"); a run on a real device.
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
  space, which each memory reserves about 8 GiB of) is a `MemoryError`; guard pages off (`--no-guard-pages`, or by architecture) avoids the second case, and it is a decision of the build, not a fallback while it runs. Other `abort()`
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
6. Android and Pyodide in the CI matrix of the example: done (Android x86-64 is built and tested, arm64 only built); `pyproject.toml` configuration (no `setup.py`): done;
   publishing on PyPI (the workflow publishes on a tag; the publisher is not set up yet); `.wat` as a source (an idea, see "Build and distribution").
7. `funcref`/`externref` in signatures (a design is needed first: who owns an `externref`); custom page sizes (`wasm2c` can, with a
   flag); the rest of the examples of other projects (below).
8. ~~**WASI**~~ (`wasi_snapshot_preview1` and `wasi_unstable`): done for WASI 0.1. Part of wasmext, compiled into the native module as a header, `wasi_preview1.h`, the system
   reached through `Python.h`; 42 of 46 calls, the official tests pass on Linux, macOS and Windows; see "Design: WASI". Not built **on purpose** (see "Decisions"): sockets (`sock_*` stay `ENOTSOCK`: nothing to compare a design to) and the clocks of the process and the thread in `poll_oneoff` (the specification leaves them without a use). Left: WASI 0.2 and 0.3.
9. **A native path to files on Windows** (stage 3 of the single work in item 10: **3a is built, 3b (`nt`) is not started**). The aim is portability: the core of WASI as plain C that needs no interpreter and no toolchain
   beyond a C compiler, so that the layers can be split (item 10) and a shared library or an executable (`--shared`, `--exe`) can be built with MSVC, MinGW or `zig cc`. Linux and macOS are confirmed; Windows
   is the one place that still goes through Python. Safety is not the aim: the walk that confines a path stays because the official tests and the behaviour of POSIX ask for it, not as a promise of a
   race-free sandbox (the way uvwasi and wasm3 resolve a path as a string, not as wasmtime does with a handle). How: the same walk, with its primitive (open one component) behind one small interface; the primitives
   are documented Win32 with wide-character functions (UTF-8 to UTF-16, never the ANSI ones): `CreateFileW` with `FILE_FLAG_BACKUP_SEMANTICS` and `FILE_FLAG_OPEN_REPARSE_POINT`, `FindFirstFileW`, `MoveFileExW`,
   `CreateSymbolicLinkW`, `SetFileInformationByHandle`; no `ntdll`, no `GetProcAddress`, the same headers in MSVC and MinGW. Two variants of that primitive, chosen by a define and not by the compiler (ntdll is a matter of the system, not of the compiler):
   **`portable`** (stage 3a, the default): the Win32 above, path by path with the walk of the components, no race-free guarantee; and **`nt`** (stage
   3b): a handle-relative open, `NtCreateFile` with `RootDirectory` as cap-std does, which closes the gap between a check and a use that `portable`
   has. `-DWASMEXT_WASI_WIN=nt` selects it; `portable` stays the default. The `nt` variant has declarations of its own (names of its own, such
   as `wasi_nt_*`, so that no header of MSVC, MinGW or `zig cc` collides) and takes the functions of `ntdll.dll` once with `GetProcAddress`: no import
   library, no flag of the linker, the same source in the three compilers. It is an addition, not the aim: the aim (portability) is met by `portable`.
   CI runs both on Windows, as it runs the Python path of the files on Linux (`WASMEXT_WASI_PYTHON_FS`). Checked by the official tests on Windows
   (x64, ARM64, x86); Windows cannot be run here, so only CI tells. Not measured: what the Python way costs.
10. **C first** (**stages 1 to 7 are built, the plan is not closed**: what is open is listed after the stages, under "Open in item 10"; the plan below is the text as decided). One work, of which item 9 (the native path to files on Windows) and the glue as files (see
   "Decisions") are parts: the core of the glue and the core of WASI become plain C with hooks, and everything that uses them is a front end: the
   extension for CPython, the shared library with its ctypes wrapper, the executable, the C runner of the test suite. The shared library and the
   executable are meant for any host, not only for Python, so the work is **checked against a front end that has no Python**, or it would be a
   refactor for the extension alone. Two checks hold the layers in place, both in CI: (a) the core headers compile with **no Python on the include
   path**, on Linux, macOS and Windows (MSVC; MinGW or `zig cc` where it is at hand), from stage 2 on; (b) the C runner runs the official WASI tests
   with no interpreter in between, from stage 5 on. At a glance: 1 seams on paper; 2 the core of WASI cut; 3 native files on Windows; 4 the glue as
   files; 5 the C runner on the three systems; 6 the shared library, then the ctypes wrapper; 7 the executable and the documentation. Each stage
   leaves the repository green (the 303 tests, the 72 official tests on the three systems), is its own commit(s), and changes nothing of what the
   extension does:
   1. **Inventory and the seams, on paper** (done: see "Design: C first, the seams"). Sort the 49 functions of `wasi_common.h` that mention Python (stdio, the configuration `wasi=`, the
      exceptions, the files of Windows, the user functions for the clock and the random bytes); fix the table of hooks (names, signatures, who owns
      the state), the interface of the file backend (open one component, stat, list, rename, link; shaped by POSIX and by Win32, see stage 3), the protocol of errors of host functions (below) and the three outcomes of a call (a value, a trap, an uncaught exception with its tag and values), the names of the files, and what
      the shared library and the executable need from the core (the entry points, `_start` and the exports of a reactor, the instance). Output: this
      document, no code. The cheap stage that stops later ones from being done twice.
   2. **The core of WASI, cut** (done: see "Stage 2, as built" in the design below; `wasi_core.h`, no `Python.h`) and the hooks of Python (`wasi_python.h`). POSIX files stay in the core (`openat`).
      Files of Windows stay through Python, as the backend of `wasi_python.h` (`WASMEXT_WASI_PYTHON_FS` is that backend; it stays as a way to test
      the interface on Linux). Green on the three systems before the next stage starts, so that a failure of stage 3 is not taken for one of the cut.
      Check (a) begins here, on the core of WASI (on Windows it is incomplete until stage 3: no file backend without Python).
   3. **The native path to files on Windows** (item 9; 3a written, see "Stage 3a, as built" below), straight after, **before the glue is touched**: the Win32 backend of the interface of stage 1,
      in the core. It goes here and not later because the core of WASI is not free of the interpreter on Windows without it, and because the interface
      of the backend should be shaped by both systems and not by `openat` alone. Two parts:
      a. **`portable`** (the default): documented Win32, wide-character functions. Verified by the official tests through the extension. After it the
         files of Windows are in `wasi_core.h` too, `wasi_python.h` keeps its Python backend only for tests, and check (a) is complete on Windows
         (MSVC; the compile with MinGW or `zig cc` where it is at hand).
      b. **`nt`** (`-DWASMEXT_WASI_WIN=nt`): the same primitive done with `NtCreateFile` and `RootDirectory`, handle-relative; own declarations and
         `GetProcAddress`, so that it builds in every compiler. CI runs the official tests with both variants. It comes after 3a is green and does not
         block the next stage.
   4. **The glue as files** (first half built, see "Stage 4 ... as built"; the tags and the uncaught exception are the second half): `wasmext_glue.h` (the same for every module), `<name>_glue.h` (the module: typed C functions, the tables), `<name>_py.c`
      (the Python layer) — see "Decisions". The record `wasmext_export` and the fingerprint do not change. Check (a) covers them. **With it, the uncaught exception of WebAssembly**:
       the reader of modules (`_wasm.py`) reads the tag section (it checks its framing only now), `<name>_glue.h` gets a table of the tags of the
       module (the types of their values, the name when the tag is exported) and a function that decodes the payload of the runtime by those
       types; the Python layer raises `UncaughtException`, a subclass of `Trap`, with `.tag` and `.values` (so that code that catches `Trap` goes on
       working), the `.pyi` names it, and a test with a module that has a tag (a `throw` that is caught inside and one that is not) is the proof;
       the C API of the shared library gives the same three outcomes. The WASI half
      (2 and 3) and the glue half (4) do not depend on each other; the WASI half goes first because the blocker (Windows) is there.
   5. **The first front end that is not Python, on the three systems** (written; Linux checked, the other two in CI, see "Stage 5 ... as built"): the C runner (`wasmext-run module.wasm`, the idea of `natify --exe`):
      `main()`, the hooks of WASI in plain C, `_start`. It needs 2 to 4 (the core of WASI complete on every system, the core of the glue). It runs
      the official tests without the Python adapter (the cause of the slow Windows job) and is check (b). If the cut is wrong, it shows here.
   6. **The shared library and the ctypes wrapper**, both in the plan (the wrapper is the second half of this stage, on the first).
      a. The shared library (`natify --shared`): the fixed `.c` that exports the functions of `<name>_glue.h` and a **generated C header of the API**
         (create and release an instance, call an export, the pointer and size of a memory, register an import with the status of the protocol above,
         the configuration of WASI, the code of a trap and its message). For any host language; no Python in it. The error protocol is checked here
         with a host in C.
      b. The ctypes wrapper (`<name>_ctypes.py` and the `.pyi` shared with `Instance`), a front end on the C API of 6a, with the same interface as
         `Instance` (decided above). The protocol above is the one wasmtime-py uses over ctypes, so the error of a host function is not a block.
         Its open points, settled while it is built: the interruption of a sleep, the link between instances, the GIL, the lifetime of the callbacks.
   7. **The executable** (`natify --exe`) on all three systems; the documentation, the README and the table of products brought up to date; the
      alpha-level decisions about names (`--shared`, `--exe`, the files shipped in the wheel).
   **The protocol of errors of host functions (decided in its form; part of the interface of the core, stage 1).** A C ABI has no exception that can
   cross it, and a `longjmp` through the frames of another language (ctypes, libffi, cgo, JNI, a Rust `extern "C"`) is not safe. So a host function
   (an import given by the host, a hook of WASI) **reports failure by its return value and never unwinds through the core**; the core then raises the
   trap itself, so that only the frames of WebAssembly and of the core are unwound. This is the protocol of the others: wasmtime (the callback
   `wasmtime_func_callback_t` returns a `wasm_trap_t *`, `NULL` is success; `wasmtime_func_call` gives the trap back in an output parameter) and wasm3
   (a host function returns an `M3Result`, `NULL` is success; `m3ApiTrap(VALUE)` is `return VALUE`; the error rides up as a value, no `longjmp` in the
   API) — read in their headers, not tried here. For us: an import of the host returns a status (and the results through pointers); on a failure the
   core traps with a code for "error of the host" and the call of the export reports `trapped` and the code. A language that has exceptions does what
   wasmtime-py (ctypes, over the C API of wasmtime) does: the callback catches `BaseException` inside, keeps the object, returns the status of failure;
   after the call returns the wrapper sees the trap and raises the kept object (the original exception, not a copy). Why it is needed: tried on a model, a
   ctypes callback that raises does **not** pass the exception on; ctypes prints `Exception ignored on calling ctypes callback function`, gives the C code
   an undefined value, and the C code goes on. The extension for CPython needs none of this (its callbacks are called with Python frames above them and
   `PY_ERROR_TRAP` unwinds C frames only), and the executable has no imports of the host but WASI. An exception of WebAssembly (the proposal of
   exception handling; `wasm-rt-exceptions-impl.c`) is not a trap: a module made from C++ with exceptions, or from Rust with unwinding, may `throw`
   and `catch` inside itself. If a `throw` reaches the edge of the module and nothing in it catches, the call of the export ends with an exception
   that carries a tag and values, which would be a result of its own for the host (wasm3 has it: `m3Err_trapUncaughtException`, with
   `m3_GetExceptionTag` and `m3_GetExceptionArgs`). Today (tried on a module with a tag, a `throw` that is caught inside it and one that is not): the one
   caught inside returns its value, the other raises `Trap('Uncaught exception')` and the instance stays usable; the tag and the values are lost,
   though the runtime keeps them (`wasm_rt_exception_tag()`, `wasm_rt_exception_size()` and `wasm_rt_exception()`, the payload at most
   `WASM_EXN_MAX_SIZE` = 256 bytes). So **the result of a call has three outcomes in the protocol: a value, a trap (a code), an uncaught exception
   (a tag and values)**, and it goes in the plan (stages 1 and 4), not "later".
   What does not wait for any of it: the alpha of the extension, as it is. The public interface (`Instance`, `natify`, `wasi=`) does not change in
   stages 1 to 5; the files that a built extension carries do (the headers beside its C), which the cache of `wasmimport` and the stamp of the
   build already follow. Order and why: 1 before everything (the seams are the part that is expensive to redo); 2 and 3 (3a, then 3b) together and first,
   because the core of WASI is the larger and the more tested piece and its one gap, the files of Windows, is what keeps it from being free of the
   interpreter; 4 after them, being the other half; 5 once both halves are complete, so that the cut is proved on all three systems with a second
   front end; 6 (the shared library, then the ctypes wrapper) and 7 last, because they add products, not structure.
   **Sizes (an estimate from the size of the code and from the pace of CI seen so far; not a promise).** S is a document or a few commits with one
   round of CI, M is several commits and a few rounds, L is many rounds. A round on Windows (the build of the programs, 3 minutes, and the tests) is
   about 5 to 6 minutes.
   1. **S**: a document, no CI.
   2. **M**: about 1 850 of the 2 860 lines of `wasi_common.h` move as they are; the 49 functions that touch Python become calls of hooks. The risk
      is a hook with the wrong signature found late. 3 to 5 commits, 2 to 3 rounds on the three systems.
   3. **3a L, the largest and the most uncertain**: the Python path to files is about 1 000 lines (the block `WASMEXT_WASI_PYTHON_FS`, a third of the
      header) to be replaced by Win32, about twenty calls (`path_open`, `path_filestat_get`, `fd_readdir`, `path_rename`, `path_link`,
      `path_symlink`, `path_readlink`, `path_unlink_file`, `path_remove_directory`, `path_create_directory`, the times, `pread`/`pwrite`, ...). Windows
      cannot be run here, so every step is a round of CI: expect 8 to 15 rounds, 45 to 90 minutes of waiting in all, apart from the writing.
      Symbolic links: creating one needs a privilege on Windows (an administrator, or Developer Mode); the runners of GitHub are administrators, as
      far as is known here (the tests of links pass there now). `symlink_filestat` is expected to fail only because Python before 3.13 cannot set the
      times of a link itself; natively `SetFileTime` on a handle opened with `FILE_FLAG_OPEN_REPARSE_POINT` can, so the expectation may go.
      **3b M**: the primitive is one small interface, so the variant is the part that opens, lists and renames by handle (a few hundred lines);
      the risk is the semantics of `NtCreateFile` (flags, reparse points, the sharing of the file), found by CI rounds, 4 to 8 of them.
   4. **M**: the generator (1 459 lines) gives about 230 generic lines to a header and the typed functions to `<name>_glue.h`; the 303 tests run
      locally and fast, so few rounds of CI: 4 to 6 commits, 2 to 3 rounds.
   5. **M**: a `main()`, the hooks in C, the way the test runner starts a program (a build of each program by `wasm2c` and the compiler of the machine,
      on three systems). 4 to 6 commits, 4 to 6 rounds.
   6. **6a M to L**, the generator of the C header of the API, the fixed `.c`, a host in C that tests the protocol of errors; **6b M**, the
      generator of the wrapper and the proof that it is the same interface (the existing tests run against both front ends would be the proof).
   7. **S to M**.
   Not decided: whether stages 6 and 7 are one release or two; the hooks being `static inline` or function pointers (to be measured at stage 2 on a
   call that is on a hot path, the standard streams).

   **Open in item 10 (and item 9), as of stage 7 built:**
   - **Stage 3b (`nt`)** is not started: the handle-relative open (`NtCreateFile` with `RootDirectory`); `portable` (3a) is the default and the one in CI.
   - **The file backend kept its form**, not the plan's: guest pointers and `trapped` in the `wasi_be_*` functions (the plan wanted `const char *`, no `trapped`, a handle).
   - **Selection of the backend** is `_WIN32` and `WASMEXT_WASI_PYTHON_FS`, not `WASMEXT_WASI_FILES=posix|win32|nt|python` with a file for each (`wasi_files_nt.h`, `wasi_files_python.h` do not exist as planned).
   - **Hooks as pointers or `static inline`** was never measured (nor what the Python way of files costs on Windows).
   - **Names**: the file of `main` is `<name>_main.c`, not `<name>_exe.c`; `wasmext-run` is not a command.
   - **CI coverage**: the official tests, the native backend and the executable run on Windows x64 only (ARM64 and x86 build the example wheels); `build_extension` skips Windows, so the tests of the extension front end do not run there (the way to close it: build with the compiler of setuptools).
   - **Stage 7, still open**: where `<name>_api.h` goes in the wheel (today the project ships it with `package-data`), and how a package finds its own binary at run time (a helper; `examples/products` does it by hand).
   - **abi3** was tested with Python 3.11 only; 3.15 and 3.15t are being brought in (a free-threaded build is native, `cp315t`: abi3t is not built, as cibuildwheel does not tag it yet).
11. **Suspend, resume and snapshot** (an idea, later; nothing decided). wasm3 has it: `m3_SetSuspendable` (before the code is compiled, because only
    code made that way has the pause checks), `m3_RequestSuspend` (it takes effect at the next point of a pause: the back edge of a loop or the
    start of a function), `m3_IsSuspended`, `m3_ResumeRuntime`, and snapshots of a paused call (`m3_SaveSnapshot`/`m3_LoadSnapshot`, to a buffer,
    or embedded in the module: `m3_SaveSnapshotToModule`), with hooks for the state of the host — read in its header, not tried. The example
    `04-suspend-resume` of pywasm3 (a pause when the gas runs out, a snapshot of the paused call) is in the table of examples. **It does not carry
    over as it is**: wasm3 is an interpreter with a stack of its own that it can stop and write down, while the C of `wasm2c` runs on the stack of
    the machine. The ways that exist for us, to be weighed when it is taken up: (a) a pass of Binaryen before `wasm2c` (`wasm-opt --asyncify`, the
    example `03-asyncified` of pywasm3 is made that way): the module saves and rebuilds its own stack, at a cost in speed and size; (b) a snapshot
    only between calls, of the linear memory, the globals and the tables, with no stack (simple; it cannot stop a call in the middle); (c) a
    thread or a switch of stacks for each instance, to pause a call without writing it down (no snapshot). A pause also has to cross the layers of
    "C first": a hook of the host that asks for it, and the state of WASI (the table of descriptors) in the snapshot.

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
"preview0"), which share `wasi_core.h`. The headers are copied into `<name>_wasmext/` and included by the glue of the module (both, if it
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
the rest is common. A private header holds the common part, which both headers include, so that they cannot drift apart (`wasi_core.h`); the four that differ have a
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

**Stages 1, 2 and 3 (built).** `src/wasmext/c/wasi_core.h` with `wasi_preview1.h` and `wasi_unstable.h`, copied beside the C of a module that
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
taken) but `NO_RENAME_DIR_TO_EMPTY_DIR`. One test is expected to fail on Windows when the files go through Python (`expectations-windows-python-fs.toml`): `symlink_filestat`, because Python before 3.13 cannot set the
times of a link itself.

What they found, that our tests had not: the same function imported twice (AssemblyScript; a duplicate in the glue); a directory opened with all the rights of its
preopen (a retry as a directory on `EISDIR`); the rights of an opened directory (no seek); a trailing slash (`file/` is `ENOTDIR`, and a name to be made that has one is
`EEXIST`, `ENOTDIR` or `ENOENT`); `fd_renumber` of the standard streams; `pwrite` on a file opened for writing only (no `fd_seek` is asked for); and, on Windows (the Python way),
`os.utime` of a file by its descriptor (it has none: the path is kept), the inode of `.` and `..` in a listing, no `O_NOFOLLOW` (a link is not opened without following it: `ELOOP`, checked by hand), links made with `/`,
`O_APPEND` (it cannot be taken off again: `fd_write` seeks to the end), `os.link` that does not follow a link, and the times of a link (`follow_symlinks=False` only for a link).
It also found that the runner kills a program after 5 s unless the adapter says more, and that what a killed program started goes on on Windows and held the runner for 30 minutes.
Not built: threads; sockets and the clocks of the process and the thread in `poll_oneoff` are decided against for now (see "Decisions"). Tests: `tests/test_wasi.py` and `tests/test_wasi_fs.py` (through `build_extension`, not on
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

## Design: C first, the seams (stage 1 of item 10)

Written from a reading of `wasi_common.h` (2860 lines; the name it had before stage 2 cut it into `wasi_core.h` and `wasi_python.h`) and `_gen.py`; nothing here is built yet. The figure "49 of 135 functions mention
Python" came from a rough search; the groups below are what the reading found and are the figures to trust.

### Where Python is in the core of WASI today

| Group | Functions | Why it needs Python now | Where it goes |
| --- | --- | --- | --- |
| Configuration | `wasi_pack_strings`, `wasi_config_*`, `wasi_apply_option`, `wasi_setup_preopens`, `wasmext_wasi_new` | reads the dict `wasi=` (`os.path.realpath`, `isdir`, `fsencode`, `PyDict_*`) | front end: `wasi_python.h` fills a plain-C `wasmext_wasi_config` (args, env, preopens `{name, host path, readonly}`, hooks, `user`); the core takes that |
| Python objects in the state | `stream[3]`, `stdin_pos`, `exit_type`, `signal_type`, `ended_type`, `time_module`, `os_module`, `text_base`, `clock_fn`, `random_fn`, `cfg_*`; `wasmext_wasi_traverse`/`_clear` | the state holds references | out of the core state: the core has `void *user`, and the Python front end keeps these in the structure `user` points to (and does the GC traversal) |
| Standard streams | `wasi_is_text`, `wasi_write_text_stream`, `wasi_write_bytes`, `wasi_write_std`, `wasi_read_bytes`, `wasi_read_std` | text or binary stream, `sys.stdout` as it is now, bytes as stdin | hooks `stdin_read`, `stdout_write`; without hooks the core reads and writes descriptors 0, 1, 2 itself (what the executable needs) |
| Clock, random | `wasi_clock_ns`, `wasi_random_get` | a function the caller gave | optional hooks `clock`, `random`; the system's own is already plain C |
| Sleep | `wasi_sleep_ns` | releases the interpreter and checks `PyErr_CheckSignals` between slices | hook `sleep`; the default (slices of 100 ms, `nanosleep`/`Sleep`) stays in the core |
| End of the program | `wasi_proc_exit`, `wasi_proc_raise`, `wasmext_wasi_finish`, `wasmext_wasi_check` | builds `WasiExit`, `WasiSignal` and raises them in the call | the core records the end (`finished`, `end_value`) and reports a trap; the front end makes the exception from that record when the call returns (`wasmext_wasi_check` is already there) |
| Errors of Python | `wasi_python_error` and every `return wasi_python_error(trapped)` | an `OSError` becomes a WASI errno, anything else a trap | disappears from the core; becomes the protocol of hooks (below) |
| Files of Windows | the block `#if WASMEXT_WASI_PYTHON_FS` of `wasi_common.h`, lines 1349–1930 (about 580 lines; the whole `#if … #else … #endif` with the POSIX half is 1005 lines) | `os.stat`, `os.open`, `os.listdir`, `normcase`, times through `os.utime` | stage 3: replaced by a native backend; until then a backend of `wasi_python.h` |
| Two small `#if` | `wasi_fill_preopen`, `wasi_sync_entry` | the same switch | go with the backend |

Everything else in the file (memory access, rights, descriptors, the walk of a path, `openat` and its kin, the translation of errno)
has no Python in it; the POSIX half is plain C already, and its only link to the interpreter is `wasmext_wasi *w` and the argument
`trapped`.

### The hooks

One structure given at creation, in the configuration; every hook is optional, and a missing one means the default of the core.
`user` is the host's own state; the core never frees it, and the front end owns its lifetime (it must outlive the instance).

| Hook | Signature | Default of the core |
| --- | --- | --- |
| `stdin_read` | `int (*)(void *user, uint8_t *buf, size_t cap, size_t *got)` | `read(0, …)` |
| `stdout_write` | `int (*)(void *user, int fd, const uint8_t *buf, size_t n)` (`fd` 1 or 2) | `write(fd, …)` |
| `clock` | `int (*)(void *user, uint32_t id, uint64_t *ns)` | the system's clock |
| `random` | `int (*)(void *user, uint8_t *buf, size_t n)` | the system's source |
| `sleep` | `int (*)(void *user, uint64_t ns)` | slices of 100 ms |

Return of every hook: `0` is success; a positive number is an errno of WASI (`WASI_E_*`) that the core hands to the program
unchanged (a broken pipe is `WASI_E_PIPE`, an unreadable stream is `WASI_E_IO`); `WASI_HOOK_TRAP` (a value outside the errnos) is a
trap of the call. The host keeps what it needs for the report (the Python layer keeps the exception it caught, see the protocol).
The text-or-binary logic of `stdout_write` is the Python layer's, not the core's.

Whether hooks are `static inline` functions chosen by a define or pointers in this structure is **not decided here** (stage 2 measures
it); the table is written for pointers because that is the case the other front ends (shared library, executable) need.

### The interface of a file backend

`wasi_be_*` already is that interface: there are two implementations of the same 12 functions (the Python one at 1349–1930, the POSIX
one at 1931–2353) and the code after them calls only the names. What changes is how they are shaped:

- `stat_fd`, `stat_path`, `open`, `mkdir`, `remove`, `times_fd`, `times_path`, `rename`, `link`, `symlink`, `readlink`, `list`
  (that is the whole set; `sync` and `seek` use the descriptor directly).
- They no longer take guest pointers (`uint32_t path, len`) or `trapped`: the core copies the name out of the memory of the module,
  checks it, and gives `const char *` and its length; the result is a WASI errno. A backend does not know the module has a memory.
- A directory is an `wasi_entry`; what it keeps in it (a POSIX descriptor, a Windows handle, a root and a relative path) is the
  backend's business, so `osfd` becomes `uintptr_t handle` plus the backend's own fields. The POSIX and the Win32 backend are shaped
  by that: Win32 has no `openat`, so the portable one holds a handle of the directory and the path below it and checks that the real
  path stays inside the preopen; the `nt` one opens relative to the handle.
- Selection is by define at build time (`WASMEXT_WASI_FILES=posix|win32|nt|python`), not by compiler.

### The protocol of errors of host functions

The same for the hooks of WASI and for the functions the host gives through `imports`: **the status is the return value, and the
exception, if there is one, is the host's own object.**

- A host function in a language with exceptions catches everything inside its callback, keeps the exception object, and returns
  `WASI_HOOK_TRAP` (for `imports`: the same, a trap code of the call).
- The core raises a trap in the module with `trapped` set; the call ends, and the export reports `trapped` and a code.
- The front end that made the call looks at what it kept and raises that, so Python raises the very object its function raised.
  Nothing crosses the C frames of the module as an exception; this is the pattern of wasmtime, wasm3 and wasmtime-py.

Known from reading the headers of wasm3 and wasmtime only; checked against the real behaviour of neither.

### The three outcomes of a call

A call to an export ends in one of these, and the C interface has to carry all three (today the third is `Trap('Uncaught exception')`):

1. **A value** (or none).
2. **A trap**: the code of `wasm_rt_trap_t`, and for a host trap the object the front end kept.
3. **An uncaught exception of WebAssembly**: the tag and the values (`wasm_rt_exception_tag`, `_size`, `_exception`; up to 256
   bytes). The front end of Python makes `UncaughtException(Trap)` with `.tag` and `.values`; the C interface gives the tag index,
   the number of bytes and a pointer valid until the next call. Tags of the module are read from the tag section when the glue is made
   (stage 4); importing a tag from the host is not supported.

### Names of the files

| File | Layer | Python.h |
| --- | --- | --- |
| `wasmext_glue.h` | universal glue: instance of the runtime, link record, the three outcomes | no |
| `<name>_glue.h` | glue of the module: typed functions (`link_call0` …), tables | no |
| `<name>_py.c` | the extension: types, methods, the stubs of the capsule | yes |
| `<name>_shared.c` and `<name>_api.h` (stage 6) | the stub of the shared library and its C header | no |
| `<name>_exe.c` (stage 7) | `main()` | no |
| `wasi_core.h` | WASI without the host | no |
| `wasi_preview1.h`, `wasi_unstable.h` | the two interfaces (stay as they are) | no |
| `wasi_python.h` | hooks and configuration of Python | yes |
| `wasi_files_posix.h`, `wasi_files_win32.h`, `wasi_files_nt.h` | file backends | no |
| `wasi_files_python.h` | the Python backend; leaves when 3a is green on Windows, unless the Linux job that tests the Python path is worth keeping | yes |

### What the shared library and the executable need from the core

- **Entry points**: create an instance with a configuration (arguments, environment, preopens, hooks); call an export (by index, with
  typed arguments and results, or a `uint64_t` array); read and write the linear memory; free; the link record, for linking instances.
- **Commands and reactors**: the executable calls `_start`, ends on `proc_exit` with its code, and takes `args` from `argv`, `env`
  from the environment and the preopens from `--dir` options; a library calls `_initialize` (if the module has it) and then the
  exports.
- **Nothing of Python**: no hook of the core may need the interpreter to finish; this is the check (a) of the plan.

### Not decided at this stage

Hooks as pointers or `static inline` (stage 2 measures); one release for stages 6 and 7 or two; whether `wasi_files_python.h` stays;
the exact errno for a host function that cannot report one; the interruption of a sleep in a library that has no signals.

### Stage 2, as built

`wasi_common.h` is now `wasi_core.h` (1959 lines, no Python) and `wasi_python.h` (1193 lines). Checked: the 303 tests and 4 expected
failures as before (the tests of the files run the POSIX backend and the Python one); the core with `wasi_preview1.h` and
`wasi_unstable.h` compiles with gcc and clang (`-std=c11 -Wall -Wextra`) with **no Python on the include path** (check (a), Linux).
CI: the official WASI tests on the three systems pass on this stage (`1c5a8b8`). Check (a) is its own workflow, `core-without-python.yml`: the
core with the two snapshots compiled by gcc and clang on Linux and by clang on macOS with only the runtime of wasm2c on the include path, and
a search that the core files do not name the Python C API. Windows (MSVC) joins at stage 3: until the file backend there is native, the core
there takes the one of `wasi_python.h`.

What differs from the table of stage 1:

- **One more hook, `end`** (`proc_exit`, `proc_raise`), called before the program is marked as over. The plan said the core would only
  record the end and the front end would make the exception later; the hook keeps the glue as it was (the exception is set at the
  moment of the call, as before) and costs one pointer. Python's `end` raises `WasiExit` / `WasiSignal`.
- **`wasmext_wasi_create(config, &err, &bad)`** is the plain-C constructor; it copies the configuration (the host may free it at once).
  `wasmext_wasi_new` (the dict) stays for the glue and lives in `wasi_python.h`, with `_free`, `_clear`, `_traverse`, `_check`; the
  core's own freeing is `wasmext_wasi_destroy`.
- **The Python objects are in `wasmext_wasi_py`**, which the core sees only as `user`. A failed hook leaves its exception in the state
  of the thread and returns `WASI_HOOK_TRAP`; an `OSError` becomes an errno of WASI (`wasi_python_status`).
- **The file backend kept its form** (guest pointers and `trapped` in the `wasi_be_*` functions). Cleaning that up is left to stage 3,
  where a second backend shows what the interface needs; for now the core declares the twelve functions and either its own POSIX half
  or the Python half of `wasi_python.h` defines them (`WASMEXT_WASI_PYTHON_FS`, which is the default on Windows).
- **Memory** is `malloc`/`free` (macros `WASI_MALLOC`…), not `PyMem_*`, so a host without Python links nothing else.
- **Without hooks** the core reads descriptor 0 and writes 1 and 2 itself, sleeps in slices of 100 ms, and uses the system's clock and
  random source; that is what the executable of stage 7 will run on.
- **The glue** includes `wasi_python.h` after the header of the snapshot; `wasi_core.h` and `wasi_python.h` are copied beside the glue
  (`WASI_SHARED` in `_natify.py`).
- Still open (stage 2 was to measure it): hooks as pointers or `static inline`. They are pointers now; nothing was measured.

### Stage 3a, as built

`wasi_files_win32.h` (about 880 lines, Win32 only, no Python, no POSIX layer) is the file backend of the core on Windows; it is chosen by
`_WIN32` and replaced by the backend of Python with `-DWASMEXT_WASI_PYTHON_FS=1`. It has the twelve `wasi_be_*` functions of the interface
and keeps the model of the Python backend (a directory is a path; a file is a descriptor of the C library made with `_open_osfhandle`, with its
path kept), so `fd_read`, `fd_write`, seek, truncate and sync of the core are the same code on every system. The calls are the documented
wide-character ones: `CreateFileW` (with the same sharing as the C library, read and write), `GetFileInformationByHandle` and `...Ex`
(identity, size, times, link count, reparse tag), `FindFirstFileExW`, `MoveFileExW`, `CreateHardLinkW`, `CreateSymbolicLinkW`,
`DeviceIoControl(FSCTL_GET_REPARSE_POINT)` for `readlink`, `SetFileTime`. Paths go as UTF-16 with the `\\?\` prefix. A name is resolved by
hand below the directory; a link that leads out is found by comparing `GetFinalPathNameByHandleW` of what is used and of the directory (so the
check and the use are two steps: what `openat` does not have, and what the `nt` variant of 3b is for). A link that leads nowhere is refused
when a name is to be made through it (where it would lead is not known).

What was checked, and what was not:

- The same C test (`/tmp` scratch, not in the repository yet: about 100 calls of `path_open`, `fd_*`, `path_*` on a directory, the answers
  printed) was run on POSIX and on Windows under wine (the C compiled by `zig cc -target x86_64-windows-gnu`, run by wine 9). The answers are
  the same for creating, reading, writing, truncating, appending, `stat` with and without a trailing slash, `readdir`, `rename` (a file
  over a file, a directory over an empty directory, the refusals), `unlink`, `rmdir`, hard links, `..` out of the directory, an absolute
  name. They differ in the link count and size of a directory (Windows says 1 and 0), and in `a/../d1` where `a` does not exist (the name is
  resolved without looking at the disk, as in the Python backend).
- **Symbolic links and `atim` of `path_filestat_set_times`** could not be checked under wine (it does not do the reparse points of Windows and ignores the access time), so the CI was the first test:
  **it is green** (the 72 official tests on `windows-latest` with this backend, and as a second job with the Python one). On x64 only: ARM64 and x86 are not run for the suite.
- The official tests expected `symlink_filestat` to fail on Windows with Python before 3.13; with this backend it should pass, so the
  expectation file now belongs to the job of the Python backend only (`expectations-windows-python-fs.toml`), and the job of the native
  backend has none. Whatever fails there is read from the first run.
- Check (a) now includes MSVC on Windows (`core-without-python.yml`).

### Stage 4 (the glue as files), first half: as built

`generate()` makes three layers where it made one file. **Written and tested** (303 tests, 4 expected failures at the time, plus a test that the glue of a module
compiles with no path to `Python.h`); **run in CI since, green on the three systems**.

- `wasmext_glue.h` (static, no Python, copied beside every module): the trap codes that are not the runtime's (`WASMEXT_TRAP_HOST`,
  `_NO_MEMORY`, `_ENDED`), the fingerprint `WASMEXT_RUNTIME`, how a call of WebAssembly code is guarded (`WASMEXT_ENTER` / `LEAVE`, the
  jump buffer, the signals of a trap by guard pages).
- `<name>_glue.h` (generated, no Python): what each import module holds (`fn[]`, `user[]`: the function to call and its first argument,
  the values of imported globals, the pointers of imported memories), the instance `<name>_instance`, the functions the module imports in
  the form the runtime wants (over `fn`/`user`), `<name>_instantiate`, `<name>_free`, and for each export a typed function
  `<name>_call<i>(void *instance, parameters..., int *trapped)`: `*trapped` is the code of the trap, or 0.
- `<name>_py.c` (generated, was `<name>_glue.c`): the Python layer: `Instance`, the conversion of arguments and results, `py_import<k>`
  (a callable of the caller as a host function whose `user` is the callable), the capsule `wasmext.export.v1` (its record and fingerprint are
  as they were), the memories and globals as attributes. `py_link<i>` is what a capsule gives another Python extension: the typed function,
  with a trap turned into an exception of **this** extension before it is answered (so that `a.Trap` is still the exception of a trap in `a`).

Notes: a call across two instances is now a call of a function pointer with `user`, the same for a function of another instance, one of WASI
and a Python callable (the old `lf`/`li` and `fn` fork is gone). The protocol of errors is what the glue does: a host function answers
nonzero through `trapped`, the frames of the module are unwound with `WASMEXT_TRAP_HOST`, and the Python layer finds its exception where Python
keeps it. The check (a) in CI (`core-without-python.yml`) does not cover the new headers; `test_the_glue_of_a_module_compiles_with_no_python`
does it on systems with a `cc`, and the tests of the shared library and of the executable compile the glue with no path to Python on all three systems (MSVC included). **Second half of stage 4: built** (the tags, below). Still to do for the C API: stage 6.

### Stage 4, second half: the uncaught exception of WebAssembly, as built

`_wasm.py` reads the tag section (`Module.tags`, `all_tags`; the check of the indices of exported tags is real now). The glue of a module that has tags
(`<name>_glue.h`, no Python) gets `<name>_tag_of(tag)` (the index of the tag of the exception the runtime keeps, or -1 for the tag of another module) and
`<name>_tag_values(tag, payload, size, out)`, which decodes the bytes the runtime keeps by the types of the tag into `wasmext_value` (a type number and a
union; `wasmext_glue.h`). The Python layer makes `UncaughtException(Trap)` with `.tag` and `.values` from them when a call ends with
`WASM_RT_TRAP_UNCAUGHT_EXCEPTION`, before any other code of WebAssembly runs (the runtime keeps one exception per thread); the stub names it.

How the glue finds the tag: wasm2c makes the tags of a module `static` (in one file) or gives them names that depend on the export, so natify adds to the
C of wasm2c, in the first (or the only) file, a table `wasmext_tags_<prefix>[]` of their addresses in the order of the tags (`_export_tags` in
`_natify.py`; it reads the declarations `const wasm_tag_placeholder_t NAME;` that wasm2c writes, in that order). The payload is the value itself for a tag with
one value and a struct of them for more (wasm2c's own `struct wasm_multi_<codes>` is not in the header, so the glue declares the same members in the
same order). Limits: the runtime keeps at most 256 bytes of an exception; a tag with a reference type in its values is told by its index with no values.

### Stage 5, the C runner (check (b)), as built

`wasmext._exe` makes a native program from a WASI command: the C of wasm2c (by `_prepare` of natify, so the same repairs), `<name>_glue.h`, the core of WASI
and a generated `main()` (`<name>_main.c`), compiled and linked by the compiler of `setuptools` (MSVC on Windows, `cc` elsewhere). No Python is in the program. The program takes
`--env NAME=VALUE`, `--dir HOST::GUEST` (both repeated), the path of the module and its arguments, and ends with the code of `proc_exit` or 134 on a trap. Only the imports of
WASI are served (`<name>_wasi_bind` in the glue); a module with any other import, or with no `_start`, is refused when it is made. On Windows the standard streams are put in
binary mode and the host path of a directory is made whole (`_fullpath`).

**Checked**: on Linux the 72 official tests of the suite pass with these programs (all built in 80 s, run in 1.5 s, against about 7 s through Python); three tests in `tests/test_exe.py`
(exit code and bytes, a trap, the refusals). **Then run on macOS and Windows** by the CI jobs `(native executables)` of `wasi-testsuite.yml`: Windows passed at once; macOS failed three tests (`path_link`, `stdio`, `path_open_preopen`, `NOTDIR` for `ISDIR`), which valgrind on Linux traced to
`wasi_path_open` using the entry of the directory after `wasi_new_fd` had grown (reallocated) the table of descriptors; fixed, and all 72 programs are clean under valgrind. Green on the three systems.
This is the tool of the test suite, not yet a command (`natify --exe` is stage 7).

### Stage 6a, the shared library with a C API: built and closed

`wasmext._shared` makes, from the same typed glue, a public header `<name>_api.h` (plain C types, no wasm2c types) and `<name>_shared.c` that exports it; `_exe.build_shared` compiles and
links them into a shared library (the sources of wasm2c, the glue and the core of WASI; no Python, and no `main`). The life of an instance: `<name>_new(&config, &error)` (WASI is made and
bound there), `<name>_set_import<k>(m, f, user)` for each import that is not WASI's (a host function `result f(void *user, params..., int *trapped)`, the protocol of errors above),
`<name>_instantiate(m)` (0 or the code of a trap), each export as `int <name>_<export>(m, params..., results...)` (0 or the code of a trap; `<name>_trap_message(code)` is its text), `<name>_free(m)`.
A module that imports a global or a memory, or has several results in an import, is served now (see "Then built" in the audit below); `v128` in an import was refused with a clear message (served now, as 16 bytes behind a pointer; see the row `v128` in a signature).
Checked by `tests/test_shared.py` with a host written in C, on Linux, macOS and Windows (MSVC) in CI. What was open when 6a was written is closed: Windows runs it, the configuration of WASI has the
hooks of the clock, random bytes, sleep and the end of the program, a reactor is initialized by `_instantiate`, the globals have accessors, the link record for linking instances is in the API.

**The products, decided** (for stage 7): `--extension` (the default when no product is named), `--shared` and `--exe` are *one product for each run*, not combinable: a library must not hold a
`main`, and an executable has its own, so they are separate builds of the same C (the C of wasm2c and the glue are shared by the work directory and not made twice). Naming `--shared` or `--exe`
builds only that; the extension is built only when it is the default or asked for. `--exe` needs a `_start` (a command). A reactor (WASI module with `_initialize` and no `_start`) is a
`--shared` product: done, in every front end: one function of the glue (`<name>_glue_initialize`) runs `_initialize` of a reactor once after the instantiation, the extension, the library and the ctypes wrapper call it, and a later explicit call of `_initialize` does nothing; a trap in it is the error of making the instance. A module with a `_start` is a command and is not initialized.

### Stage 7, how the products are asked for (built, with the wheel tag)

A package may ship a shared library (a dll) or an executable instead of, or beside, a Python extension, so the product is a setting of **both** doors, not only of the command line:

- `natify(..., product="extension" | "shared" | "exe")` (default `"extension"`) and, with the same name, a key `product` in `[[tool.wasmext.ext-modules]]` of `pyproject.toml` (the hook reads the table and calls `natify()`); `natify()` keeps returning `Extension` objects.
- One product for each entry: several products of one `.wasm` are several entries (an array of tables), each with its own output name. The command line says the same with `--shared` and `--exe` (`--extension` is the default when none is named), one product for each run, since a library holds no `main`.
- A product that is not an extension is an `Extension` with a mark that `wasmext._setuptools` (the `build_ext` it already puts in) knows: it compiles `<name>_shared.c` or `<name>_main.c` in place of the Python layer, links a library (`lib<name>.so`, `lib<name>.dylib`, `<name>.dll` with its import library) or an executable (`<name>`, `<name>.exe`) and puts the file where an extension would go, so `package-data`, `inplace` and wheels work as they do for an extension.
- **Built:** `natify(product=)`, the `product` key of the table (type-checked), `--extension`/`--shared`/`--exe` (exclusive; a product other than the extension implies `-i`), the `build_ext` of `wasmext._setuptools` (`get_ext_filename`, `build_extension`, the wrapper copied to the source folder with `-i`), `tests/test_products.py`. The C of a product is made when it is built, not when `natify()` is called; the CLI ignores the table of the project it runs in (`WASMEXT_NO_PYPROJECT`).
- **Done:** the tag of a wheel that has no Python extension (`py3-none-<platform>`). **Still open:** where the header `<name>_api.h` goes in the wheel (it is beside the C in `<name>_wasmext/`; the project ships it with `package-data`); how a package finds its own binary at run time (a small helper, not a path written by hand).

### Stage 6b, the wrapper for ctypes, as built

`build_shared` also writes `<name>_ctypes.py` and `<name>_ctypes.pyi` beside the library (`wasmext._ctypes_gen`; the stub is the one of the extension). The module is Python only, needs nothing of wasmext, finds the library beside itself
(or at `$WASMEXT_<NAME>_LIBRARY`) and has `Instance`, `Trap`, `LinkError`, `UncaughtException`, `WasiTerminated`, `WasiExit`, `WasiSignal` as the extension has them: methods with their signature as the docstring, the same type errors and wrapping of
integers, `imports` as callables (the exception of an import comes out of the call as the very object, by the protocol of errors: the callback keeps it and answers `trapped`), the memory as a `memoryview` that keeps the instance alive, globals as attributes,
`wasi={...}` with the same keys and the same errors, a call of WASI replaced through `imports`, `__exports__` and `__getitem__`, and the linking of instances.

**Linking is C in the core, not Python.** The record of an export (`wasmext_export`, in `wasmext_glue.h`; the extension wraps it in a capsule `wasmext.export.v1`) and the checks that link an import to it live in `<name>_glue.h`
(`<name>_link_func<k>`, `_link_global<j>`, `_set_global<j>` for a number, `_link_memory<j>`; the messages are the ones the extension always gave). The extension, the C API (`<name>_link_import<k>`, `_link_global_import<j>`, `_set_global_import<j>`,
`_link_memory_import<j>`, `<name>_export_find`) and the wrapper all use them, so the front ends link **with each other**: a wrapper takes the memory, a global or a function of an extension, and the other way (tests: `tests/test_linking.py`, the pairs
extension/extension, ctypes/ctypes, extension/ctypes, ctypes/extension). A function of a library is linked as a C function, with no Python in between (flag 8 of the record: it needs no GIL), and a trap of the callee goes through as it is
(`WASMEXT_TRAP_LINKED` + its code, see `wasmext_glue.h`); a function of an extension needs Python (its `py_link` raises exceptions), so a wrapper calls it through Python. A host function that fails in an instance that is called through a link: the
instance that was called keeps the exception (`_pending`) and the caller raises that very object. The capsule of a wrapper keeps the instance alive and owns its record, as the capsule of an extension does.
**Two libraries in one process** each have a runtime of wasm2c of their own: the library shows its API and no other symbol, which is fixed by the **linker** and not by a flag of the compiler (a version script, or `-exported_symbols_list` on macOS; MSVC exports what is
`dllexport`; the list is written beside the C as `<name>.map` / `<name>.exports`, for a build system of one's own). Without it the two share the buffer of `longjmp` and a trap through a link aborts.
**Flags of the user**: `BuildFlags` (`extra_compile_args`, `extra_link_args`, `define_macros`, `undef_macros`, `include_dirs`, `libraries`, `library_dirs`: the names of `setuptools.Extension`) go to `build_shared` and `build` after the flags of wasmext, so they win; the environment
is read as setuptools reads it (`CC`, `CFLAGS`, `CPPFLAGS`, `LDFLAGS`; `_CL_` for MSVC).
What the C API got for it: `set_import` for the calls of WASI too, imports with several results (through pointers), imports of globals and memories, `dirs_readonly`, `args` non-NULL with `nargs` 0 for "no arguments", and the export records.
**The proof**: the tests of the interface run on both front ends and pass: `test_extension.py`, `test_wasi.py`, `test_wasi_fs.py` (the files of the system), `test_linking.py`, and the examples of pywasm3, wasm2mpy and wasmhost.
**Differences that stay**: a trap that goes through a link out of a library is the `Trap` of the instance that called, not that of the callee; a function of a wrapper that is given to an extension is called by it directly (no Python), one of an extension that is given to a wrapper
goes through Python; the interruption of a sleep by Ctrl-C (the core sleeps in C); PyPy and GraalPy (not tried); where the library is shipped (stage 7).

### Audit of stages 1 to 6a against the plan (after 6a; probes run by hand, not yet tests)

**Bugs found by running the shared library** (the four are fixed, each with a test in `tests/test_shared.py` or `tests/test_exe.py`; the fixes: `_new`, `_instantiate` and every export set the runtime up for the calling thread by `api_enter()`, with `<name>_thread_free()` to give it back; the end of a WASI program answers `TRAP_ENDED`; an export left out is said in the header (`not here:`) and on stderr; an executable of a module with no WASI import is refused in words):
- The library never calls `wasm_rt_init()` (the extension does it in `PyInit_`, the executable in `main`): an out-of-bounds access in a module **crashes the host with SIGSEGV** instead of
  answering a trap (the only trap the test uses is `unreachable`); a build without `NDEBUG` (a Windows build by `zig cc`) stops at `assert(wasm_rt_is_initialized())`. `_new` must call it (it is idempotent), and a
  host thread other than the one that created the instance needs `wasm_rt_init_thread()`.
- The call in which a WASI program ends (`proc_exit`) answers `TRAP_HOST` ("a host function failed"); only later calls answer `TRAP_ENDED`, which is what the header documents for the end.
- An executable of a command that imports nothing from WASI stops in a C `#error` of the generated `main` instead of running or being refused in words.
- An export with `funcref`/`externref` in its signature is left out of the header without a word (a v128 one was said; it is in the header now), and a table export is accepted where the extension refuses it.

**Then built** (tests in `tests/test_shared.py`): the configuration of the library has the hooks `clock`, `random` and `sleep` as well as stdin and stdout; `_instantiate` runs `_initialize` of a reactor (a module that has it and no `_start`) after the instantiation, so that
the first export already sees its effects (the extension does the same now, through the same function of the glue; see "Stage 7"); every exported global
of type i32, i64, f32 or f64 has `<name>_global_<g>(m)` and, when mutable, `<name>_set_global_<g>(m, value)`. The tests run on Windows too: the host is compiled by the compiler of setuptools (MSVC) against the import library that `build_shared` copies beside the dll
(`libm.lib`), so the CI of the three systems ran it on MSVC: **green** (02a841e; the first run found that a path of an object past 260 characters broke `cl`, now the objects are named by the stem); checked by hand before: the library cross-built by `zig cc` (MinGW) and run under wine answers an out-of-bounds trap, the end of a WASI program and a reactor.
Because these tests compile `<name>_glue.h`, `<name>_api.h` and the core with no path to Python on each system, they are check (a) for those headers too (the dedicated workflow `core-without-python.yml` compiles them strictly too now: the glue, the C API and the `main()` of a few modules, made by `.github/scripts/glue_without_python.py`, with gcc, clang, macOS clang, MSVC and MinGW by `zig cc`; the strict build found `#pragma comment(lib)` of MSVC unknown to MinGW, and static functions of the glue header that clang warned of as unused, now `static inline`).

**Left from the list below** (still open): the file-backend and naming deviations, 3b (`nt`) and the measure of hooks, ARM64 and x86 for the suite. Closed since: the link record is in the API, 6b and stage 7 are built, the 'as built' texts of 3a, 4 and 5 are refreshed.

**In the plan and not there (as found; the hooks, `_initialize` and the globals are now there, see above)**: a reactor's `_initialize` is not called by `_instantiate`; the configuration has the hooks of stdin and stdout only (the core also has `clock`, `random`, `sleep`; the `wasi=` of Python has the user
functions for the clock and the random bytes, so 6b needs them); exported globals have no accessor (the extension has them as attributes); the link record for linking instances is not in the API; Windows (MSVC)
had never built the library at that time (cross-built by `zig cc` as a MinGW dll, it exported and linked, and ran under wine up to the missing `wasm_rt_init`; MSVC has built and run it since, see above); the proof is two tests and one host.

**Plan deviations not written down before**: the file backend kept its form (guest pointers and `trapped` in the `wasi_be_*` functions; the plan wanted `const char *`, no `trapped`, a handle); the selection by
`WASMEXT_WASI_FILES=posix|win32|nt|python` and the files `wasi_files_posix.h`, `wasi_files_nt.h`, `wasi_files_python.h` do not exist (it is `_WIN32` and `WASMEXT_WASI_PYTHON_FS`); the file of `main` is
`<name>_main.c`, not `<name>_exe.c`, and `wasmext-run` is not a command; stage 3b (`nt`) is not started; hooks as pointers or `static inline` was never measured. Check (a) in CI
(`core-without-python.yml`) does not compile `wasmext_glue.h`, `<name>_glue.h` or `<name>_api.h` (a test of pytest does it on Linux and macOS, skipped on Windows; MinGW or `zig cc` is not in CI). Item 9 says the
official tests were checked on Windows x64, ARM64 and x86: the suite, the native backend and the executable run in CI on x64 only (ARM64 and x86 build the example wheels).
The text of "Stage 3a", "Stage 4 first half" and "Stage 5, as built" above still says the CI had not run; it has, and is green on Linux, macOS and Windows (the suite on the extension, on the Python files, on the executables).

**Checked and sound**: no Python in the core files (grep, and CI with gcc, clang, macOS clang and MSVC); the 72 official tests pass on the extension, with files through Python and as native executables, on the three systems, and
all 72 executables run clean under valgrind (this found the use of a freed table in `path_open`, now fixed); an out-of-bounds trap in an executable and in the extension (also from another thread) is a trap; the library
passes the probes for WASI with and without hooks, a preopened directory (a file is written), i64/f32/f64, several results, two instances, a growing memory, a free of NULL, and a clean valgrind.
Built since this audit: 6b (ctypes), stage 7 (`product`, `--shared`/`--exe`), the README section on products.

### Audit, second round: what was fixed, and what is still not covered

**Fixed, each with a test**: a half-made instance is freed when `instantiate` traps (a start function that traps, a data segment out of range), but **not after `NO_MEMORY`**: the memory that
could not be had has a size and no data, and the runtime frees it with `munmap(NULL, 8 GiB)`, which unmapped the interpreter itself (found by `test_a_limit_on_address_space`; a memory of the module made
before the failed one leaks then, which is rare and harmless next to a dead process); a table that cannot be allocated is a `MemoryError` (the glue tries the same `calloc` first); names with a NUL, with `*/` or a newline cannot
break the C or its comments; imports are bound by the name of the import module, as wasm2c orders them; an exception tag with a payload of more than 256 bytes (what the runtime keeps) is reported when the extension is made; `wasi_python.h` used
`Py_SETREF` and the `GET_SIZE` macros, which an abi3 build does not have (an `undefined symbol` at import; now only limited-API calls); the executable has `--help`, `--version`, `--argv0`, `--`, `HOST::GUEST:ro`, a validated `--env`,
the errno in its errors, the number of the signal, UTF-8 arguments on Windows (checked under wine with `zig cc`) and a refusal of a `_start` that is not `() -> ()` in words; the table of `pyproject.toml` checks the type of each value and
names the key; `wasmext inspect` takes the list of what is left out from the generator, so it cannot call a method what the generator does not expose; a module with GC types or a custom page size is refused with the name of the proposal; `-q` silences the
warnings of the compiler for the C of wasm2c too; the release workflow does not publish a commit on which `pre-commit.yml` (pytest on three systems) has no successful run.

**Not covered, and said so**:
- The fixtures `build_extension` skips on Windows (it uses a `cc` and the build line of gcc/clang), so **the tests of the Python extension front end do not run on Windows**; there run the ctypes front end, the shared library, the executable, the official WASI suite and the example wheels
  (all of them build the extension with MSVC). Turning `build_extension` into a build by the compiler of setuptools is the way to close this, and needs CI rounds on Windows.
- abi3 is tested with Python 3.11 only (the wheels are tagged `cp311-abi3`; 3.12 and later run them without a test of ours).
- The patches of the copy of the C that wasm2c writes are four: `_memory_error_not_abort` (the allocation of a memory traps, it does not `abort()`), `_export_tags` (the table of tags), `_tail_call_locals` (fixed in WABT master by `6c7af19`, not in a release),
  `_portable_on_arm64` (`_addcarry_u64`, WABT #2885). Nothing in the runtime or the sources of wabt-package is changed; when WABT has a release with the fixes the patches go.
- **Fixed:** an exported `memoryview` of a memory that the runtime moves when it grows (no guard pages, memory64) used to be able to outlive the buffer. Now `memory.grow` answers -1 while such a view is alive (the maximum is made the present size; `Py_bf_releasebuffer` puts it back), in the extension and in the ctypes wrapper (`<name>_memory_*_pin` of the C API, a finalizer of the view); `test_a_memory_that_can_move_does_not_grow_while_a_memoryview_of_it_is_alive`.

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
- **`poll_oneoff` waits on the realtime and the monotonic clock only.** The clocks of the process and of the thread (CPU time) are not built: the specification of the first snapshot does not say what it means to wait for a CPU clock, which does not advance while the program waits, so there is no behaviour to implement or to check against (the official tests do not ask for one). A subscription to them is answered at once with `EINVAL` in its event (`wasi_subscription_wait`), not a hang. To be taken up if the specification or a program gives a meaning.
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
  A third product of the same layers, no Python at all: a **native executable** of a WASI program (`wasmext natify --exe` is the idea): the C of
  `wasm2c`, the core of the glue, the core of WASI with the hooks filled in plain C (the standard streams are descriptors 0, 1, 2; `proc_exit`
  is `exit`; a signal is `raise`), and a `main()` that gives the arguments and the environment of the process to the program and calls
  `_start`. With it `lua.wasm`, `qjs.wasm` or `coreutils.wasm` become ordinary command line programs, built by the C compiler of the machine;
  the C runner of the test suite is the same thing with a path to the file in place of a built-in module.
  Where it stands now: in `wasi_common.h` (2860 lines) 49 of the 135 functions mention Python (stdio through `sys.stdout`, the configuration, the
  exceptions, the files of Windows through `os`, the user functions for the clock and the random bytes); the rest is plain C already. The
  files of Windows are the last place where the core needs the interpreter for data, which is why the native path to files on Windows
  (the plan, item 9) and this split are one piece of work from two sides. The first step is the split of the WASI header, not of the whole
  glue, and it comes when something needs a host that is not Python (the runner, a shared library); the Python layer stays as it is, and the
  hooks are `static inline` so that the split costs no call (to be measured). The contract of the link between two instances keeps its form;
  a C host would carry the same record in its own way.
  **The layers of the glue and of WASI, as files (a proposal, not decided; nothing built).** Today the generator (`_gen.py`) writes the glue of a
  module as one `.c`, from Python string templates; of the 245 lines it writes for `simple.wasm`, 16 mention the module or the export, the other 230
  are the same for every module (the traps, `set_trap_error`, the `wasmext_export` record and its layout fingerprint, the signals, the machinery of
  `Instance`). The files that the layers of "C first" would become, the inner ones nested and the outer ones side by side on the same core:
  1. `wasmext_glue.h`, the glue that is the same for every module, **no `Python.h`**: the traps, the export record and its fingerprint, the
     signals, the table of hooks. Shipped and copied beside the C of the module, as `wasi_core.h` is.
  2. `<name>_glue.h`, the glue of the module, generated, **no `Python.h`**: for each export a typed C function (as `link_call0` in the glue
     today: `result f(void *instance, parameters..., int *trapped)`), the tables of exports, imports, memories and globals with their signature strings,
     the instantiation and the release.
  3. The front ends, each on 1 and 2:
     a. `<name>_py.c`, generated, **with `Python.h`**: the type `Instance`, the wrappers of the exports (they parse the Python arguments and call
        the typed function of 2 in the same translation unit: no packing of values), the table of methods, the init of the module. It is the one
        `.c` that the build compiles for the extension for CPython (so no fixed stub is needed);
     b. a shared library: a fixed `.c` that exports the functions of 2 as symbols, **and a generated ctypes wrapper** (`<name>_ctypes.py`, with a
        `.pyi`): it loads the `.so`/`.dll`, sets `argtypes`/`restype` from the signature strings, and gives a class `Instance` with the same
        methods. **The wrapper has the same interface as `Instance` of the extension** (decided): the same methods and attributes, the same arguments,
        `imports` as Python callables, `wasi={...}` as the same dict, `__exports__`, the memory as a `memoryview`, the same exceptions (`Trap`,
        `LinkError`, `WasiExit`, `WasiSignal`), so that code and the `.pyi` are the same for both (one stub, not two). The wheel then depends on the
        platform and not on the version of Python; it may serve interpreters with no CPython extensions (PyPy, GraalPy: **not tried**). A call through
        ctypes costs much more than a call of the extension: an alternative, not a replacement. **The error of a host function is settled by the protocol
        below** (it was the one that looked like a block). Still open when it is built: the interruption of a sleep (`PyErr_CheckSignals` has no
        place in the core: a hook; a `KeyboardInterrupt` that comes while a callback runs is caught inside it, like any exception); the link between
        two instances (the capsule `wasmext.export.v1` is a CPython object: a pointer to the record would be carried by the wrapper in its own way,
        and whether an extension and a ctypes instance can link with each other is open); the GIL (ctypes releases it during a call of a function of
        a `CDLL`); the `CFUNCTYPE` objects of the imports kept alive as long as the instance;
     c. an executable: a `.c` with `main()` that gives the arguments and the environment of the process to the program, the hooks of WASI in plain C
        (standard streams are descriptors 0, 1, 2; `proc_exit` is `exit`; a signal is `raise`), and calls `_start` (`natify --exe`).
  WASI follows the same cut: `wasi_core.h` (plain C: descriptors, the walk of paths, arguments, environment, clocks, random bytes, `poll_oneoff`, the
  end of a program; whatever needs the world outside it is a hook, a table of function pointers) and, for each host, its hooks: `wasi_python.h`
  (with `Python.h`: `sys.stdout` and objects with `write`, the dict `wasi=` turned into the configuration, the exceptions `WasiExit` and `WasiSignal`,
  the user functions for the clock and the random bytes), the hooks in plain C of the executable, and for the shared library the hooks that the
  ctypes wrapper gives as callbacks. The native path to files on Windows (the plan, item 9) is the last thing that keeps the core from being free of
  the interpreter.
  *A uniform thunk instead of the typed wrapper* (a function of one form that the Python layer calls with the values packed by the signature
  string) was thought of and measured with a prototype: +4.2 ns on a call of 40 ns (median), +5 % by the best rounds, within the noise. It is not
  needed in this scheme (3a calls the typed function of 2 directly) and is kept here only as the measurement.

- `wasmhost` is a different tool (a facade over engines); its API is a guide for names and errors, the reference for behaviour
  is the specification and the JavaScript API.
