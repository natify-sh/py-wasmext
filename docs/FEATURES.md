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
| Import/export of mutable globals | done | exported: as attributes (see below); imported: an export of another instance (see the Python side below) |

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
| Reference types in a signature (`funcref`, `externref`) | partly | `funcref` in an **exported** function: a parameter takes None, a `Function`, or a function of an instance of a module that shares tables (`instance.name`, `instance['name']`); a result is a `Function` or None; in the extension, the wrapper for ctypes, the C API (`const void *` in, `void **` out, freed with `funcref_free`) and the `.pyi`; the instance keeps the owners of the functions it was given; a module with a `funcref` in a signature shares tables (has the class `Table` and `Function`). `test_a_funcref_is_a_parameter_and_a_result`. **Not done:** a `funcref` in the signature of an *import* (the module is refused: the Function made for the host would have no instance to keep alive), a `Function` called with a `funcref` parameter, and `externref` (the function is left out / the module is refused) |
| SIMD (`v128`), inside the module | done | the C of `wasm2c` includes simde; the wabt-package (1.0.42.0 and later) ships the headers (`wabt_package.include_dir()`), and wasmext adds that directory to the include path of the extension when the C includes `simde/`. `2.0 SIMD, inside the module`, `test_a_module_with_simd_gets_the_include_directory_of_simde`. Native instructions are used only if the compiler flags allow, so a baseline x86-64 wheel runs SIMD in portable code |
| `v128` in a signature | done | 16 bytes in the order of WebAssembly memory: `bytes` (or any bytes-like object of 16 bytes) in, `bytes` out; a wrong length is a `ValueError`, another type a `TypeError`. In exported and imported functions, multi-value, exported globals and imported immutable globals. Not on big-endian hosts (`#error`; the byte order of a v128 there is not checked). `test_v128_in_signatures_globals_and_imports` **Added since:** in the shared library the same functions (exports, imports, multi-value) take and give a v128 as 16 bytes behind a pointer (`const uint8_t *` in, `uint8_t *` out, the same order); the wrapper for ctypes turns them into `bytes` as the extension does (`test_v128_in_signatures_is_16_bytes_in_each_front_end`, on both). Left out of the library: a global of that type and the link of such a function to another instance |
| JavaScript BigInt to i64 | n/a | a part of the JavaScript API; here an `i64` is a Python `int` |

### 3.0

| Feature | Status | Note / test |
| --- | --- | --- |
| Tail calls | done | `3.0 tail calls`, and with locals `3.0 tail calls in a function with locals` (wasm2c 1.0.42 writes C that does not compile for a function that has locals and a `return_call`: wasmext repairs it, the pattern matches only that shape; `coremark-minimal.wasm` of pywasm3 needs it). A `return_call_indirect` to a function that itself does `return_call_indirect` to a function with no tail variant gave a wrong value with wasm2c 1.0.42 (255 instead of 5; the result was not put into the tail-call stack): wasmext repairs it (`3.0 tail calls, a return_call_indirect chain`) |
| Extended constants | done | `3.0 extended constants` |
| Multi-memory | done | `3.0 multi-memory` |
| memory64 | done | inside the module, exported as a `memoryview`, addresses above 4 GiB (Linux): `3.0 memory64`, `test_an_exported_memory64_is_a_memoryview_too`, `test_memory64_addresses_above_4_gib` |
| 64-bit tables (the address type of tables, with memory64) | done inside the module | `3.0 memory64, a 64-bit table`; a table is not exported yet (**deferred** with the tables: they are alpha until the context changes the way instances are linked) |
| Exception handling, legacy `try`/`catch` | done | `3.0 exceptions`; an exception nobody catches is `UncaughtException`, a `Trap` with `.tag` (the index of the tag in the module) and `.values` (a tuple of Python numbers; empty for a tag with none): `test_an_exception_that_nothing_catches_is_an_uncaught_exception_with_its_tag_and_values`, and through `natify` in one file or in several: `test_uncaught_exceptions_are_told_apart_by_the_whole_path_in_one_file_or_several`. This form is not in the specification, but compilers still make it. Not done: the name of an exported tag, the tag of another module (`.tag` is `None`, no values), the values of a tag with a reference type (none), importing a tag from the host |
| Exception handling, `try_table`, `throw_ref`, `exnref` | done | the form of the specification: `3.0 exceptions, try_table`, `3.0 exceptions, exnref (catch_all_ref and throw_ref)`; `exnref` in a signature and exported tags: not yet |
| Relaxed SIMD | no (wasm2c) | `wasm2c` 1.0.42 itself aborts (signal 6, no message) on `i32x4.relaxed_trunc_f32x4_s`, `f32x4.relaxed_madd`, `i8x16.relaxed_swizzle` and `i32x4.relaxed_laneselect` (the others were not tried; reported: [WABT #2886](https://github.com/WebAssembly/wabt/issues/2886), and with wide arithmetic [#2895](https://github.com/WebAssembly/wabt/issues/2895)), so it is not a matter of headers; strict xfail `3.0 relaxed SIMD…`. Its README says the same: wasm2c is not ticked for relaxed SIMD; **a way round that wasmext could do itself (an idea, not tried):** the specification lets an engine give the result of a relaxed operation as that of the strict one, so a step before `wasm2c` could replace `relaxed_swizzle` by `swizzle`, `relaxed_trunc` by `trunc_sat`, `relaxed_laneselect` by `bitselect` and `relaxed_madd` by a multiply and an add (the result would be the same on every host); it needs the opcodes of the function bodies rewritten (`wasm-tools print`, a substitution and `parse`, or our own parser) |
| Typed function references | no (wasm2c) | `wat2wasm --enable-function-references` makes the binary, `wasm2c` stops at `call_ref` (unexpected opcode 0x14); the README of WABT does not tick wasm2c for it; strict xfail `3.0 typed function references`; the options are in [typed_function_references_concept.md](typed_function_references_concept.md) |
| Garbage collection | no (WABT) | WABT 1.0.42 does not read the instructions (`wat2wasm --enable-gc`: unexpected token `struct.get`), and `wasm2c --enable-gc` says it supports a limited set of features; strict xfail `3.0 garbage collection`. wasmext refuses the GC types in a module as well |
| Branch hinting | done | a hint is a custom section; the text annotation `(@metadata.code.branch_hint …)` builds and runs, `wasm2c` ignores the hint: `3.0 branch hinting` |
| Custom annotation syntax | n/a | the text format only; `wat2wasm` takes it, nothing is left in the binary to run |
| JS String Builtins | n/a | a part of the JavaScript API |
| Deterministic profile | n/a | a profile of the specification (a subset to run in), not something a translator implements |

### Not in 2.0 or 3.0

| Feature | Status | Note / test |
| --- | --- | --- |
| Threads, shared memory, atomics | not yet | `wasm2c --enable-threads` translates a module with a shared memory and atomics (checked, although its README does not tick wasm2c for threads), with C11 atomics and `wasm_rt_init_thread`; wasmext does not pass the flag (strict xfail `threads`); wasmext can do this itself: pass the flag and build the runtime with its threads; `wasm2c` does not translate `memory.atomic.wait/notify`; reading of `wasm2c` and WASIX: [threads_wasm2c_wasix_concept.md](threads_wasm2c_wasix_concept.md) |
| Custom page sizes | not yet | `wasm2c` supports it with `--enable-custom-page-sizes` (checked: it reads a module with `(pagesize 1)` only with the flag); wasmext does not pass the flag, and its `memoryview` assumes 64 KiB pages; a module with a custom page size is refused when it is read (`WasmError`); wasmext can do this itself: pass the flag and give the `memoryview` the size of the page. **Decided how the page size is told** (it is a property of the type of the memory of a module, known when the C is made, not of an instance): a `#define <NAME>_MEMORY_<MEM>_PAGE_SIZE` in `<name>_api.h` for C; a constant of the module in Python, `module.__memory_page_sizes__ = {"mem": 65536}` (a dunder name, which cannot clash with an export, as `__exports__` does not), typed in the `.pyi` and the same in the wrapper for ctypes; linking a memory with another page size is a `LinkError`. Not built. The options and the facts from the proposal are in [custom_page_sizes_concept.md](custom_page_sizes_concept.md) |
| Wide arithmetic | no (wasm2c) | `wasm2c --enable-wide-arithmetic`: "currently only supports a limited set of features" (checked), as its README says; a way round is possible but large (the 128-bit operations as several `i64` ones in the bodies of the functions): not planned until a module needs it |
| Compact imports | done | both forms of the import section (0x7F: a module, then a name and a type for each import; 0x7E: a module, one type, then a name for each import; the number in front counts entries, and a group may have no imports), read as the [proposal](https://github.com/WebAssembly/compact-import-section) says: `Overview.md`, the decoder of its interpreter and its `binary-compact-imports.wast` agree (the valid modules of that file are read, the `assert_malformed` ones refused; checked by hand, the file is not in this repository). `wasm2c` is **not** given them: WABT 1.0.42 (and `main`) reads 0x7E with a type for each name ([WABT #2897](https://github.com/WebAssembly/wabt/issues/2897)), and 1.0.42 counted imports where the proposal counts entries, so wasmext writes the import section with ordinary imports (`expand_compact_imports`, into a temporary file) and the C is the same as that of the module with ordinary imports. In the extension, the library, the program and `wasmimport`: `tests/test_compact_imports.py` (written byte by byte: `wat2wasm` does not read the text form yet). A proposal, not part of 3.0: the encoding may still change |
| WASI 0.1 (`wasi_snapshot_preview1`, `wasi_unstable`) | done | in the module, in C (wasm2c has none): 42 of the 46 calls work, the rest answers as the specification allows; the 72 programs of the official test suite pass (see "Design: WASI"). WASI 0.2 and 0.3 (components): not supported; what was tried (the core module of a component goes through `wasm2c`, a host and the canonical ABI are what is missing) is in [WASI_COMPONENTS.md](WASI_COMPONENTS.md) |

## The Python side

| Feature | Status | Note / test |
| --- | --- | --- |
| Exported functions (`i32`, `i64`, `f32`, `f64`) | done | methods of `Instance`, positional-only, `METH_FASTCALL` |
| Integers | done | results signed, arguments wrapped (as the JavaScript API, wasmtime, wasm3); `test_integers_wrap_as_webassembly_does` |
| Exported memory | done | a read-write `memoryview` attribute; a new one after the memory grows |
| Exported globals | done | attributes, read-only if immutable: `test_exported_globals_are_attributes` |
| Exported tables | done | a `funcref` table the module defines: `instance["name"]` is a `Table` that stands for it, for another instance to import (not an attribute), in the extension, the wrapper for ctypes and the C API of the library (`<name>_export_find`); see [TABLES_PLAN.md](TABLES_PLAN.md). The program has no imports to share; `externref`, 64-bit and shared tables, and an imported table exported again: left out and reported |
| Exported tags | not yet | left out and reported. **Decided to build it now, without waiting for the context** (checked in the C of `wasm2c` 1.0.42): a tag is static data of the module (`const wasm_rt_tag_t w2c_e_e = &w2c_e_e_0;`), not a field of an instance, so its life is that of the loaded module and no keep-alive is needed; an *imported* tag is `extern const wasm_rt_tag_t w2c_env_e;`, a symbol the linker resolves, which separately built extensions cannot share, so it needs a patch of the generated C in the style of the other patches (a macro that makes the name a variable that is filled when the instances are linked). Not built |
| Imported functions | done | `Instance({module: {name: callable}})`; Python exceptions come out of the call of the module; calling back into the module works |
| Imported immutable globals | done | a number in the imports; `test_an_imported_immutable_global_is_a_number` |
| Imported mutable globals | done | an export of another instance: `Instance({"env": a})` or `a["name"]`; the variable is shared; a number is a `LinkError`; type and mutability are checked: `test_instances_share_a_mutable_global_and_an_instance_is_a_mapping`, `test_linking_a_global_checks_what_it_is` |
| Imported memories | done | the memory of another instance: `Instance({"env": a})`, `{"memory": a.memory}` (the memoryview stands for its memory) or `a["memory"]`; one buffer, `grow` is seen by both; checked: size (at least the minimum, at most the maximum), memory64, guard pages on both sides or neither (`LinkError`): `test_instances_share_a_memory`, `test_linking_a_memory_checks_its_size_and_kind`. A shared (threads) memory is refused |
| Imported tables | done | a `funcref` table of another instance (an extension, a wrapper for ctypes or a library, in any pair), `Instance({"env": a})` or `a["name"]`, or `<name>_link_table_import<j>` in the C API; one table: a write or `table.grow` by one is seen by the other; the size and the maximum are checked (`LinkError`), an element of the wrong type is a trap, a trap in a function of the other instance is a trap of the caller; the libraries that share tables share one stack of entries for traps (`<name>_traps`, `<name>_traps_use`); the owner of a table keeps the instances that import it (a C host unlinks with `<name>_unlink_tables`) (`tests/test_tables.py`) |
| `Table` | done | a class made by the glue of a module that imports or exports a `funcref` table, in the extension and in the wrapper for ctypes with the same members and the same `.pyi`: `Table(initial, maximum=None)` (no module behind it), `size`, `maximum`, `grow(delta)`, `get(i)` (a `Function`), `set(i, function)`, `len()`; the class `Function` (`name`, `signature`, `__call__`, equality by function and instance), also with the same members in the extension, the wrapper and the `.pyi`; imported by any module of either front end (the capsule is what they share); in the C API of the library `<name>_table_new/free/size/maximum/grow/export/is_null/is/set`. A function can be put in a table only if its module shares tables (has a `funcref` table, or is built with `share_tables`: `natify(share_tables=True)`, `share-tables` of `pyproject.toml`, `--share-tables`, `wasmimport.install(share_tables=)`); A `Function` is called if its type is one the module of the class declares (found by the hash of the type); another type is told (`signature` is None, a call is a `TypeError`). `tests/test_table_class.py`, `examples/plugins` |
| Shared global between instances | done | one variable used by several instances, through the exports of an instance (DESIGN.md); a global with no code behind it is a module that only declares it (built ahead of time like any other; `test_a_table_a_memory_and_a_global_with_no_code_behind_them_are_a_module_that_only_declares_them`), not an object made while wasmext runs |
| Shared memory between instances | done | one buffer used by several instances (see "Imported memories"); a memory with no code behind it is a module that only declares it, as for the global (a table with no code behind it is a `Table`, see "Imported tables") |
| Recognising the objects of another extension | done | a public capsule `wasmext.export.v<X>` with a record that has `size`, `abi` and `floor` (see "Public interface" in the README), DESIGN.md, "Recognising an instance of another extension" |
| Imported functions from another instance | done | `Instance({"env": a})`, `{"add": a.add}` (a bound method stands for its export) or `a["add"]`: the call is direct, in C, without Python in between; the signature is checked (`LinkError`); a trap inside the called function is the `Trap` of its module, raised through the caller, and both instances go on: `test_instances_call_each_others_functions_directly`, `test_linking_a_function_checks_its_signature` |
| `instance["name"]`, `instance.__exports__` | done | the references to the exports, for linking to another instance (a capsule `wasmext.export.v<X>`; from the wrapper for ctypes an object that gives one as `__wasmext_ref__`); `{"env": a}` gives a whole shelf. See DESIGN.md, "How the imports are given" |
| Traps | done | `Trap` (a `RuntimeError`), the instance stays usable; `LinkError` for bad imports |
| GC and weak references | done | `Instance` takes part in the cycle collector and can be weakly referenced |
| Type stubs | done | `<module>.pyi`, made with the C and put by the build beside the extension (`build/lib.*`, the wheel, or in place), with `# fmt: off` and `# ruff: noqa` |
| Parameter names in the stub | done | The parameters of an exported function are named as the "name" section of the module names them (`wat2wasm --debug-names`; compilers write it in a build with debug info), as `add(self, left: int, right: int, /)`; else `arg0, arg1, ...`. The name section is only a hint, and a module with a broken one is read as one without. The names are used all or none: if one parameter has no name, is not an ASCII identifier, is a keyword, `self` or starts with `__`, or two are the same, all of the function get `argN`. They are positional-only (`/`), so the names are for the reader and the editor: a call by keyword is not possible |
| `wasmext natify` and `wasmext inspect`, commands (`wasmext --help`) | done | `natify` writes the C and, with `-i` or `-b`, builds; there is no command by file names alone. |
| `wasmext inspect` | done | what a module imports and exports and what wasmext makes of it; writes nothing |

## Build and distribution

Where the files are made and put: [build_model.md](build_model.md). In short: the generated C (and `<name>_api.h`) is one
platform-independent copy per project in `build/wasmext/<module name>/`; objects are in `build/temp.*`; products (with their
stub, or ctypes wrapper) go to `build/lib.*`, the wheel, or in place. Nothing generated is in the sources or in an sdist.

| Feature | Status | Note |
| --- | --- | --- |
| `natify()` for `setup.py` | done | like `cythonize()` |
| `wasmext` command (`-i`, `-b`, `-f`, `-q`, `-X`, `--build-dir`, `--parts`, `--limited-api`, `--guard-pages-for`, `--shared`, `--exe`) | done | `-q` also silences the warnings of the compiler for the C of wasm2c; `--shared` / `--exe` are exclusive, one product for each run; without `-i` or `-b` they only write the C. `-i` and `-b` say where the product goes (in place, or `build/lib.*`); the C is in `build/wasmext/` either way |
| The build model | done | generation covers every target at once (`generate_c`: the C of wasm2c, the glue and the wrappers of the runtime are common, each target has a front end: `<name>_py.c`, `<name>_api.h` + `<name>_shared.c`, `<name>_main.c` for a WASI command) and the build chooses the sources; the C is in `build/wasmext/<module name>/`, written whole or not at all; `build_dir` changes only that directory. `tests/test_natify.py`, `tests/test_products.py` |
| Regeneration by content | done | the head of every file of the C is macros: `WASMEXT_GENERATED_SOURCES` (a fingerprint of the sources of wasmext itself: its Python and the C it ships), `_WABT`, `_PARTS`, `_WASM` (the SHA-256 of the `.wasm`) and `_VERSION` (for people, not compared). The C is made again when it is missing, has no such macros, differs in any of them, or is forced (`force`, `-f`, `WASMEXT_FORCE_REGEN=1`). Not by time (a copy, an archive or a cache keeps old times) and not by the version of the package (a development tree is not rebuilt by every commit). A library or a program has a stamp (`<name>.<product>.stamp`: the digest, the versions, the number of files, the flags) in its work folder and is built again when it differs. `test_other_sources_of_wasmext_generate_the_c_again`, `test_the_version_of_the_package_does_not_decide_whether_the_c_is_current`, `test_a_wasm_of_other_content_makes_the_c_again_whatever_its_time` |
| Source distribution | done | the `.wasm` and the project files, not the generated C (distutils leaves `build/` out); a build from it needs `wasm2c`, which `wabt-package` brings as a build requirement. **Decided against**: building generated C with no wasmext (a C compiler alone): the C is a step of the build, not a format of distribution. `test_a_source_distribution_has_no_generated_c_and_a_wheel_can_be_built_from_it` |
| Runtime of wasm2c, not copied | done | three wrapper files in the C directory include the runtime of the toolchain (`-I`); the only change, `abort()` of `wasm_rt_allocate_memory` as the trap `NO_MEMORY` (a `MemoryError`), is a macro in `<name>_rt_mem.c`, so the original sources stay as they are. Checked on Linux, macOS and Windows in CI |
| Products: shared library with a C API, program (`product=`) | done | `natify(product="shared"\|"exe")`, the `product` key, `--shared`, `--exe`; the `build_ext` of `wasmext._setuptools` makes the file where an extension would go (`lib<name>.so`/`.dylib`/`<name>.dll`, `<name>`/`<name>.exe`). A library has `<name>_api.h` (stays in `build/wasmext/`, see build_model.md) and a `<name>_ctypes.py` wrapper with `.pyi` beside it, with the interface of the extension; a program has `--env`, `--dir HOST::GUEST[:ro]`, `--argv0`, `--help`, `--version`, UTF-8 arguments on Windows, exit 134 on a trap. `tests/test_products.py`, `test_shared.py`, `test_exe.py` |
| Wheel tag of a package with no Python extension | done | libraries and programs only: `py3-none-<platform>`, tested with a real `bdist_wheel`; a mix keeps the tag of the extensions |
| abi3 (cp311) and native wheels | done | chosen by the interpreter that builds: `abi3_possible()` asks its extension suffixes; Emscripten, Android and iOS are native by decision; free-threaded and PyPy are native. One setting for the whole wheel (`[tool.wasmext] limited-api`, `natify(limited_api=)`, `--limited-api`/`--no-limited-api`, `WASMEXT_LIMITED_API`); the wheel is tagged abi3 only if every Python extension in it is. Measured on one machine (CPython 3.11, gcc -O2): calls and wasm code are the same as native, a host callback is about 5% slower. abi3t (3.15t) is not built, see below |
| `share_tables` | done | builds the modules with the stack of entries for traps that modules with a `funcref` table share, whether or not they have one, so that their functions can be put in a table (`Table.set`) and a trap in them comes back to the caller: `natify(share_tables=True)`, `share-tables` in `[[tool.wasmext.ext-modules]]`, `--share-tables`, `wasmimport.install(share_tables=)`; an input of the C (a change makes it again); the module gets the class `Table`, and its library the `<name>_table_*` API. `tests/test_natify.py`, `tests/test_cli.py`, `tests/test_pyproject_config.py`, `tests/test_table_class.py` |
| Guard pages, by architecture | done | decided when the C is compiled, for the target (`sysconfig.get_platform()`): a bool or `{"x86": false, "default": true}` in `natify(guard_pages=)`, `guard-pages` of `pyproject.toml`, `--guard-pages-for x86=off,...`, `WASMEXT_GUARD_PAGES`; off is for processes with a limit on address space and 32-bit targets, about 30% slower on CoreMark |
| WABT from the wabt-package | done | or a directory in `WASMEXT_WABT` (`bin/wasm2c`, `wasm2c/` with the runtime, `include/` with `simde/`); each part by its variable: `WASMEXT_WASM2C`, `WASMEXT_WASM2C_RUNTIME` (needs `wasm-rt.h`, `wasm-rt-impl.c`, `wasm-rt-mem-impl.c`, `wasm-rt-mem-impl-helper.inc`, `wasm-rt-exceptions-impl.c`), `WASMEXT_WASM2C_INCLUDE` (`simde/`). **WABT 1.0.42 or later**: Debian/Ubuntu `wabt` 1.0.34 splits its runtime and has no `wasm-rt-mem-impl*`. Not checked: that the runtime is of the version of the executable |
| Patch for MSVC on ARM64 and x86 | done | `_addcarry_u64` exists only on x64 (ARM64 and Win32 fail to link; confirmed upstream); a regex in `_natify.py`, also on the shared `_w2c-impl.h` of a module in several files (reported: [WABT #2885](https://github.com/WebAssembly/wabt/issues/2885)) |
| Patch for `return_call` in a function with locals | done | wasm2c writes C that does not compile; a regex puts the type back and passes a fixed wasm2c through (reported: [WABT #2884](https://github.com/WebAssembly/wabt/issues/2884)) |
| Patch for the result of a chain of `return_call_indirect` | done | wasm2c 1.0.42 calls a function with no tail variant as a plain one and returns without putting the result in the tail-call stack; the patch goes to the label that does (`goto var_Bfunc`), and matches only that shape, so a fixed wasm2c passes through. `main` of WABT (58ddc9c, built from source) still has it and the patch matches its C and fixes it; there the locals bug above (#2884) is already fixed (the repair does not touch its C). Reported: [WABT #2893](https://github.com/WebAssembly/wabt/issues/2893) (waiting for a decision upstream) |
| Patch for an imported function in an element segment | done | wasm2c 1.0.42 and `main` give an imported function that an element segment puts into a table the address of a field of the module instance instead of the pointer to the import's instance, so a `call_indirect` of it hands the wrapper of the import a wrong pointer (a crash in a host that uses it; the output of `meld fuse` is built so: it holds the WASI imports in a table of thunks). The repair gives the imports a kind of entry of their own (`RefImportFunc`) that reads the pointer, in the template (`funcref_table_init`) and the entries, in all the files of the module; it is made only if the template has the broken shape. `tests/test_natify.py`, `tests/test_extension.py`. Reported: [WABT #2896](https://github.com/WebAssembly/wabt/issues/2896) |
| Large modules in several files | done | `wasm2c --num-outputs`, compiled at the same time; automatic from 1 MiB, `parts=` / `--parts` / `WASMEXT_PARTS`; see "Build time of a large module" |
| Paths on Windows | done | a path of the build over 259 characters fails the build with the reason (`check_path_lengths`; `test_a_path_too_long_for_windows_fails_the_build_and_says_why`). Whether the mirrored object paths (`build/temp.<tag>/build/wasmext/...`) bite in CI is open |
| A memory that moves does not move under a `memoryview` | done | where the runtime reallocates a memory (no guard pages, memory64) `memory.grow` answers -1 while a view of it is alive (extension and ctypes; `<name>_memory_*_pin` for a C host) |
| Import hook, like `pyximport` | done | `import wasmimport; wasmimport.install()`; `import mod` finds `mod.wasm`, builds it into `~/.wasmbld` (or `build_dir`) and loads it. Options as in `pyximport`: `build_dir`, `build_in_temp` (False: the C in `build/wasmext/` beside the `.wasm`), `setup_args`, `inplace`, and those of `natify()`; `<module>.wasmbld`; `uninstall(finder)`, `clean()`. The cache holds the extension, the C and a stamp of how it was built. Not taken from `pyximport`: `.pyxdep`, `.py` files, `reload_support`. A development tool: it runs a C compiler on import. `tests/test_importer.py` |
| Configuration in `pyproject.toml` only | done | `[[tool.wasmext.ext-modules]]`: the arguments of `natify()` with dashes and, added to each extension, `extra-compile-args`, `extra-link-args`, `define-macros`, `undef-macros`, `include-dirs`, `libraries`, `library-dirs`; read by `wasmext._setuptools` (the entry point `setuptools.finalize_distribution_options`). Every value is type-checked and a wrong one names its key; unknown keys and a missing `module-list` are errors; `natify()` in `setup.py` together with the table is an error. `limited-api` is one setting for the project, in `[tool.wasmext]`. `tests/test_pyproject_config.py` |
| The tests of the extension on Windows | done | `build_extension` builds by setuptools (as a user does) on Windows, and with `WASMEXT_TEST_SETUPTOOLS=1` anywhere |
| Pyodide wheel | done | `cibuildwheel --platform pyodide` on `examples/coremark`, Python 3.13, built and tested inside Pyodide, in CI; the `wasm2c` of the Linux wheel of the wabt-package does the translation on the host |
| Android wheel | x86-64 tested, arm64 built | `cibuildwheel --platform android` in CI, Python 3.13, NDK 27, with the host wabt-package wheel. x86-64: built and tested in an emulator with KVM. arm64-v8a: built, not run (cibuildwheel tests on an emulator of the architecture of the build machine) |
| `.wat` as a source (`wasmext natify -i m.wat`) | no (declined until asked) | not built, on purpose: `wasmext` takes a `.wasm`. A project whose source is a `.wat` makes the `.wasm` itself, in a custom `build_ext` or a hook of its build, with `wat2wasm` from the wabt-package (which `wasmext` already needs); that is the choice of the user and not a duty of `wasmext`. Taken up again on a request. The open points then: where the `.wasm` goes, the flags of proposals that `wat2wasm` has off by default, `--debug-names` (the names of parameters in the stub), and what the source distribution holds (the `.wat`) |
| Other build backends | partly | setuptools is the backend wasmext is built for (`setuptools>=84` is a dependency; public `distutils` and `setuptools.modified` only). hatchling works through a hook that runs `wasmext natify -i` (tried on `examples/coremark` and `examples/products`, not in CI). meson-python and scikit-build-core are not supported. Details: `build_model.md`, "Build backends" |
| Published on PyPI | done | `0.0.1a1` (a pre-release: `pip install --pre wasmext`), one `py3-none-any` wheel and an sdist, uploaded on 2026-10-21 (read from the PyPI JSON on 2026-10-22); the numbering of the ABI is in [abi_policy.md](abi_policy.md). The examples in CI are still built with `--find-links` to the wheel of the commit under test (see `example-wheels.yml`), so that they test the code of the branch and not the release |

### Examples

| Example | State | What |
| --- | --- | --- |
| `examples/coremark` | done | reference CoreMark of EEMBC, built with `zig cc` by `build_wasm.py` |
| `examples/link` | done | two modules that use each other's memory, variable and function |
| `examples/plugins` | done (locally, and in CI on the seven platforms of the desktop matrix: green at `ca35834`) | a host and two plugins (`wat/`) that share one table: the plugins put functions in the table of the host, a trap in a plugin comes back to the caller, and a `Table` that no module owns with a function put in it by `Table.set`; 7 tests |
| `examples/lua` | done | `lua.wasm`, a WASI program, built in 8 files; tests on the wheel, and the wheels, in CI on seven platforms |
| `examples/quickjs` | done | `qjs` of QuickJS-ng v0.17.0 (1.1 MB), a WASI program in 4 files, configured in `pyproject.toml` only; 9 tests on the wheel |
| `examples/products` | done | one wheel (`py3-none-<platform>`) with a shared library (`product = "shared"`, used through its `engine_ctypes` wrapper) and a WASI program (`product = "exe"`), from two `.wat` files; 3 tests on the wheel; `auditwheel` repairs it with no change |
| `examples/wabt` | done (locally; not in CI) | WABT 1.0.42 built with `zig c++` as WASI programs, turned into extensions in 8 files each; `wabtwasm.wat2wasm()` and `wasm2c()`; the output is the same bytes as the native tools'; `python -m wabtwasm toolchain DIR` makes a directory for `WASMEXT_WABT` whose `bin/wasm2c` runs the extension (POSIX). 7 tests |
| `examples/wasi2_unbundled` | done (locally; not in CI) | two C programs as WASI 0.2 components (`clang --target=wasm32-wasip2`), the core module of each taken out with `wasm-tools component unbundle`, run as extensions with a host of WASI 0.2 in Python (`Host`: stdout and stderr, clocks, `poll`, a TCP client socket; the rest raises `NotImplementedError`); 3 tests and a doctest; what was run is in [WASI_COMPONENTS.md](WASI_COMPONENTS.md) |

## Speed

Compiled ahead of time (wasm2c, then the C compiler), so there is no engine and no JIT at run time. CoreMark (reference CoreMark
of EEMBC, 2K performance run), one machine, runs alternated, gcc 13 for the native C and for the extension: the extension was
about the same as the native C, +4% to +13% on three alternating runs (clang 18: the extension about 5% slower than the native gcc
and 3% faster than the native clang). That the extension should be faster than the C it comes from is not explained; read it as
"on a par with". With `--no-guard-pages` (checks in code, not by the MMU) the same benchmark was about 30% slower. The cost of
a call from Python and of a call back into Python was not measured.

## Verified, and not

### Where the suite ran

The whole suite (`pytest`: 772 passed, 10 skipped and 4 expected failures, Linux x86-64 locally on Python 3.11 at `ca35834` on 2026-10-22; and the three systems in CI), `ruff` and `pyright`:

| Where | Python | C compiler | Evidence |
| --- | --- | --- | --- |
| Linux x86-64, glibc (local) | 3.11 | gcc 13.3 and clang 18.1 | run by hand |
| ubuntu-latest | 3.11 | gcc | CI, `Pre-commit` runs `pytest` |
| macOS (macos-latest, Apple Silicon) | 3.11 | AppleClang | CI, the same |
| windows-latest (x64) | 3.11 | MSVC | CI, the same |

The official tests of WASI (`WASI test suite`, below) run in 8 jobs: three systems with native file access, Linux and Windows through Python, and three systems as native executables (ubuntu-latest, macOS and Windows), with `wasmext` on Python 3.11 and the runner of the suite on 3.12.

CI at commit `ca35834` (branch `dev`, 2026-10-22): `Pre-commit`, `Coverage`, `Python versions`, `WASI test suite` and `Example wheels` (47 jobs) all succeeded, read from the runs
of the workflows, not from their logs. The release tag `v0.0.1a1` (commit `17f83c2`) had the same workflows green, and `Core without Python` and the release workflow too. The suite is not run on Linux ARM64, Windows ARM64, macOS
Intel or the free-threaded build; only the examples are (below).

### Platforms where a native extension was built and tested

The examples (CoreMark, and Lua from commit `43324a2`) built by cibuildwheel and their tests run on the wheel (`Example wheels`, run #484 at `ca35834`, 47 of 47 jobs green: CoreMark, Lua, QuickJS, plugins and products on the desktop matrix, CoreMark also on Pyodide, Android and the other Linux architectures, and the abi3 wheel of CoreMark on Python 3.12 to 3.15; `link` and `wabt` are not in that workflow):

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

The cibuildwheel configuration of the example is `build = "cp311-* cp314t-* cp315t-*"` (`cp314t` and `cp315t` are native free-threaded wheels).

### Not confirmed

- PyPy (iOS is not a target).
- The `cp314t` wheels on the Linux architectures other than x86-64 and ARM64 (CI builds `cp311` and `cp314t` there but the wheel lists were not read).
- Big-endian hosts (s390x): a module that exports its memory, or uses `v128` in a signature, does not work there (see above);
  the rest was run only through the example and one small module.
- Clang on Windows; gcc on macOS; Python 3.12 to 3.14 with the suite (CI uses 3.11, and `python-versions.yml` 3.15 and 3.15t, which passed on the three systems; the official WASI tests use 3.11 for wasmext and 3.12 for the runner of that suite).
- Android: the tests of an arm64 wheel (it is only built, see "Android wheel"); a run on a real device.
- Tables between instances, the classes `Table` and `Function`, `share_tables` and `funcref` in the signature of an export: run locally on Linux x86-64 with gcc, and with the whole test suite in CI on Linux, macOS and Windows (job `Pre-commit`, `uv run pytest`; the test of a C host over two libraries is skipped on Windows); not run with threads, with a runtime that counts the depth of the stack (`WASM_RT_STACK_DEPTH_COUNT`), or with a `catch` in one instance of an exception thrown in another (tags are not linked).
- Ahead-of-time claims about speed are from one machine (see "Speed").

### Examples of other projects

The method (see "How to choose the next features") in numbers: the modules of these projects built and run by tests in this repository, all of them without a new feature.

| Source | What | Where | Result |
| --- | --- | --- | --- |
| wasm2mpy `test/` | seven languages (AssemblyScript, C++, Rust, TinyGo, Virgil, WAT, Zig), the blinking program with `wiring` as the board; CoreMark is `examples/coremark` | `tests/test_wasm2mpy.py` | works. Rust's `loop` prints only the line ends (the module's own behaviour). Built by `build_extension`, not by `natify()` |
| pywasm3 `00-fibonacci` | `i64` recursion | `tests/test_pywasm3.py` | works |
| pywasm3 `01-coremark` | `coremark-minimal.wasm`, `env.clock_ms` | `tests/test_pywasm3.py` | works, since the repair of `return_call` (see "Build and distribution"); the file name has a hyphen, so the test names the module by hand (`natify()` refuses such a name with a clear message) |
| pywasm3 `pygame-*` | `fire` (empty module name), `ray`, `maze` | `tests/test_pywasm3.py` | work: the frame is read from the memory, no window; `snake`, `dino`, `match3`, `metaball`, `chip8`, `plop-sim` not added yet (the same shape) |
| pywasm3 `02-metered` | a limit of work for an interpreter | not yet (see "Fuel" in "What is open") | the function entry has a hook (`FUNC_PROLOGUE`), the back edges of loops do not: it would be built, not just used |
| pywasm3 `03-asyncified` | a module made pausable by Binaryen (`wasm-opt --asyncify`): the import `sleep` calls the `asyncify_*` exports of the running instance | `tests/test_pywasm3.py` | works (the steps of the example without the event loop). Also tested: a trap of the outer call after a call into the instance from its own import, and a trap of the inner call, which is an exception in the import |
| pywasm3 `04-suspend-resume` | a pause when the gas runs out, a snapshot of the paused call | its module only (`search` and exported globals) | the feature itself is of the wasm3 engine: compiled code cannot pause by gas or save a call as it is; a pause by fuel with asyncify is the idea under "Fuel" in "What is open", not planned |
| py-wasmhost `imports.py` | several results of a host function, `i64`, an exception from the host | `tests/test_wasmhost.py` | works |
| py-wasmhost `lua.wasm`, `coreutils.wasm` | WASI programs | done | `lua.wasm` is [`examples/lua`](../examples/lua) (tests, and wheels in CI); `coreutils.wasm` (10.8 MB, built in 16 files) was run by hand: `cp`, `mv`, `ln`, `mkdir`, `rm`, `touch`, `sleep`, pipes of `sort`/`wc`/`head`, not in the tests |
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
- A cache of objects (ccache or one by the hash of the C): a rebuild costs nothing, the first build is as long. **Deferred**: the split into files is what was built and what helps; the cache is not planned now.
- A smaller module before the translation (`wasm-opt`, dropping what is not used): depends on the module, not general.
- `wasmimport` to warn when the C is larger than some size.

## Known gaps

- A memory that cannot be allocated when the instance is made (too big, or with guard pages in a process limited in address
  space, which each memory reserves about 8 GiB of) is a `MemoryError`; guard pages off (`--no-guard-pages`, or by architecture) avoids the second case, and it is a decision of the build, not a fallback while it runs. Other `abort()`
  of the runtime (the locks, the signal handlers) are left as they are. A memory that fails to *grow* returns -1, as WebAssembly says.
- Big-endian hosts (s390x): wasm2c keeps the memory reversed there, so the exported memory cannot be a `memoryview` (it raises
  `NotImplementedError`) and `v128` in a signature is refused; a module that does not use them runs (checked on one small module). A copy-based view
  or conversion would be needed.
- **Two modules in one process: a chain of handlers of signals (fixed off Windows 2026-10-22).** Every runtime of wasm2c installs the handler of SIGSEGV/SIGBUS at `wasm_rt_init` without chaining to the one before, so with two modules a trap from a signal (an access past the guard pages, a stack overflow) was raised in the runtime of the module imported last and the process aborted if the call was in the other. Now an extension built off Windows (`WASMEXT_CHAIN`) has a runtime that installs no handler (`sigaction` is a no-op in its file, the alternate stack of the thread is still set up) and a handler of its own that is a link of a chain: a fault in a call of the module (marked by the entry of the call, a thread-local) is its trap, any other fault is given to the handler that was before, so a real crash stays a crash. Tests: `tests/test_two_modules.py` (both orders, a real SIGSEGV outside a call). On Linux the extension is linked with `-z now` (a handler must not resolve `__tls_get_addr` lazily). The same chain is in the **shared library** (`build_shared`: installed once at the first call of the API, `tests/test_shared.py`, two libraries in one process). An **executable** has one module and one runtime, so it keeps the handler of the runtime. Windows calls every vectored handler and needs nothing. Open: a fault in a call of module B made from inside a call of module A (through Python) is taken by the module that is first in the chain; macOS is not checked yet; see [shared_runtime_concept.md](shared_runtime_concept.md). Modules that **share tables** keep their shared stack of entries (`wasmext_traps`). Policy of the changes to what wasm2c gives us: [patch_policy.md](patch_policy.md).
- **The stack running out is seen by a comparison of the stack pointer (in `0.0.1a2`, not released; alpha, nothing of it is promised yet).** Off Windows, Emscripten and WASI an extension and a shared library are built with `WASMEXT_STACK_LIMIT`: the prologue of each function compares the address of its frame with the lowest safe address of the thread (a thread-local, set at the thread's first call from the real size of its stack, with a margin of a quarter of the stack, 32 to 256 KiB, for the functions of the host), so the runtime needs neither the counter of the depth (500 calls, 3.3 times slower in a library) nor the handler on an alternate stack (no `sigaltstack` to set up and give back per thread, no capsule at the end of the thread), and the overflow in a thread other than the main one is called what it is and not an out-of-bounds access. **Cost, measured on a program that is all calls (`fib` through a table), in a shared library: 1.8 times the guard page** (the thread-local is reached through `__tls_get_addr`; `initial-exec` is as fast as the guard page but a library that has it needs its whole thread-local block in the static TLS, and a process that loads a few dozen of them fails at the import, so it is not used); `WASMEXT_STACK_CHECK=guard` in the environment of the build keeps the chain and uses the guard page, with a warning that says what is given up (CoreMark in the real extension: 98% of native with the guard page, 91% with the check; [experiments/stack_limit/](experiments/stack_limit/README.md)); any other value is an error. A patch of the generated C (`_stack_limit_prologue` in `_natify.py`, per [patch_policy.md](patch_policy.md)) and `signal_build_flags()`; experiment: [experiments/stack_limit/](experiments/stack_limit/README.md). Known: a library that moves stacks inside a thread (greenlet) would confuse the limit; macOS and Windows are not measured (Windows keeps the counter); the stock handler calls an overflow in a non-main thread an out-of-bounds access (not reported to WABT yet).
- Attributes and methods of `Instance` take the names of the exports; a name that is not an identifier is reachable with `getattr`.

## What is open

The state at the end of the working session of 2026-10-22 (what is done, what is not, the ideas, and what waits for a decision): [where_we_stopped_2026-10-22.md](where_we_stopped_2026-10-22.md).

One table for the whole plan. **done** = built and tested; **partly** = built, with what is left named; **open** = not built.
Design and history of each item: [DESIGN.md](DESIGN.md).

| Item | What | State | What is left |
| --- | --- | --- | --- |
| Linking instances | globals, memories, functions and funcref tables between instances | done | what is left is not a gap of this row: who owns what when a reference outlives its owner (below, "References"; the idea is in [context_concept.md](context_concept.md)). The elements of a table are read from Python (`Table.get`/`set`, `Function`) |
| Threads | shared memory, atomics | open | all of it (`--enable-threads`, C11 atomics, `wasm_rt_init_thread`); after tables |
| References | `funcref`/`externref` in signatures | partly | `funcref` in the signature of an **export** is built (the instance keeps the owners of the functions it was given). **Not built, on purpose, and refused with a message:** a `funcref` in an import, a `Function` called with a `funcref` parameter, and an `externref` (decision in [TABLES_PLAN.md](TABLES_PLAN.md), "Not built"). The design that would allow them, for a later version, is [context_concept.md](context_concept.md): a context that instances are bound to when they are made, which keeps its members until it is closed (an arena); an `externref` is the plain pointer to an object that the context keeps. The table of handles with `retain`/`release` that was the idea before is not taken. A switch `--unsafe-refs` stays possible on a request |
| Custom page sizes | `wasm2c` can, with a flag | open | the flag; the `memoryview` assumes 64 KiB pages; the way the page size is told is decided (the row above); see [custom_page_sizes_concept.md](custom_page_sizes_concept.md) |
| WASI 0.1 | `wasi_snapshot_preview1`, `wasi_unstable`, in C in the module | done | WASI 0.2 and 0.3 (components: tried, see [WASI_COMPONENTS.md](WASI_COMPONENTS.md)); sockets and the CPU clocks of `poll_oneoff` are decided against for now |
| Recognising what a file is (`wasi_flavor`) | a function of the bytes that tells core WASI 0.1, core 0.2, core 0.3 or a component, used by `inspect` and `natify` | done | `wasmext.wasi_flavor(data)` returns `component`, `fused`, `core-0.1`, `core-0.2`, `core-0.3`, `none` or `unknown`. A component (bytes 4 to 7 `0d 00 01 00`) is refused with what to do (`wasm-tools component unbundle`, or `meld fuse` for a composed one) instead of `unsupported WebAssembly binary version`; imports (or exports) of `wasi:*@0.2.x` / `@0.3.x` mean a core module of 0.2 or 0.3, custom sections `meld.*`, or the attestation that `meld fuse` writes in every module (`wsc.transformation.attestation`, JSON with `transformation_type` `fusion` and `tool.name` `meld`; the sections `meld.*` come only with `--emit-manifest`), a fused module. `inspect` prints a `wasi:` line; `natify` only warns on stderr for 0.2 and 0.3, and for a fused module that imports one of them (silenced by `-q`), the module is built as before. Changes nothing in the ABI or the build. `tests/test_wasi_flavor.py`. The other steps towards WASI 0.2 and 0.3 are in "Ways" of [WASI_COMPONENTS.md](WASI_COMPONENTS.md) and are not decided |
| Native files on Windows | stage 3 of "C first" | partly | 3a (`portable`) is built; **3b (`nt`, handle-relative open) is not started** |
| C first: the products | the glue and the core as plain C; extension, shared library + ctypes wrapper, executable | done | deviations from the plan, listed in DESIGN.md; the file of `main` is `<name>_main.c`; the backend is chosen by `_WIN32` and `WASMEXT_WASI_PYTHON_FS` |
| The build model | generated files in `build/wasmext/`, products where the build puts them | done, merged (PR #2) | Windows (paths) and cross builds in CI; `README.md` and this file follow it |
| CI | desktop matrix, other architectures, Pyodide, Android | partly | s390x (big-endian) is not in CI; the official WASI tests and the native backend run on Windows x64 only |
| Publishing | PyPI | done | `0.0.1a1` is on PyPI (see "Published on PyPI"); `publish.yml` publishes on a tag `v*` (trusted publishing, TestPyPI by `workflow_dispatch`). Open: what the release was built from and checked against was not read here |
| The ABI between built modules | the record `wasmext_export` (the last field, `funcref`, is the funcref of a function; the flag bit 4 says the function may be put in a table) and the capsule `wasmext.export.v<X>` | done | `WASMEXT_ABI` (`0xXXYYZZLS`, like `PY_VERSION_HEX`) in `wasmext_glue.h`; the capsule name has only x, and the check at link time is: the same x, the reader not below the `floor` of the record, `size`; a record grows only at its end; the layout of the runtime is checked when a module is built (`WASMEXT_LAYOUT`), not when linked; `tests/test_abi.py` fingerprints all the files of `wasmext/c/` and fails when one changes. `abi/current.json` declares the public surface (constants, structs, signatures of the C API) and `tests/test_abi_declaration.py` fails on any difference with the code and says what version a change needs ([abi_policy.md](abi_policy.md)). `tests/test_abi_declaration.py` also builds the shared library of the fixtures and checks that each declared function is an exported symbol and that the library shows no other. Open: the layout check (`WASMEXT_LAYOUT`) covers the memory, the funcref table and `wasm_rt_funcref_t`, not `wasm_rt_externref_table_t` and `wasm_rt_shared_memory_t` (references or threads in the link would need them) (`<name>_export` stays in the public `<name>_api.h`: decided; `tests/test_abi.py` checks that its fields are those of `wasmext_export`) |
| Elements of a table | done | `Table.get`/`set` and the class `Function` (step 6 of [TABLES_PLAN.md](TABLES_PLAN.md)); a function of a module that does not share tables cannot be put in a table (the way round: `share_tables`). `funcref` in the signature of an export (step 7) is built; in an import it is not | step 7 done for exports |
| Sanitizers in CI | ASan + UBSan on the test suite | done (job added, not yet run in CI) | `.github/workflows/sanitizers.yml`: the extensions built with `-fsanitize=address,undefined -fno-sanitize-recover=all` (`WASMEXT_TEST_CFLAGS`, `tests/conftest.py`), the interpreter run with `LD_PRELOAD=libasan.so`; the shape is that of the ASan job of o-murphy/rp2040py. Run by hand on `test_threads`, `test_extension`, `test_tables`, `test_table_class`, `test_linking`: 250 passed, no report. `tests/test_sanitizers.py` is a canary that fails the job if the sanitizer is not really in effect. **Open:** TSan (the interpreter is not instrumented, so the run would be noisy: the C layer, the shared library and the program, with threads is the place), macOS/Windows, the full suite under the sanitizers (about 10 minutes) not yet run |
| Not tested | | open | PyPy; 3.15.1 and later; the behaviour of the published release `0.0.1a1` on the three systems from PyPI (the suite runs on the checkout) |
| Fuel (gas), and optionally pause and resume | an idea | open | not decided, not measured; to be written down in full when its turn comes. Two levels: (1) **fuel with a trap**: a counter at the entry of every function (`FUNC_PROLOGUE` of the C of `wasm2c` is a macro that is already there for the depth of the stack) and at the back edges of loops (a `goto var_L<k>` to a label above it, which has no macro: a patch of the generated C, as the other patches of `wasm2c` are, or a rewrite of the module before it); out of fuel is a `Trap`, the call cannot go on (the `longjmp` drops the C stack), the instance stays usable; the units are coarse (calls and loop turns, not instructions); the cost of the counter is not measured. (2) **optional: pause and resume**: fuel with asyncify of Binaryen (`wasm-opt --asyncify`; `wasm-opt` is not in the wabt-package, so it would be a tool of the build to install, and `pywasm3` `03-asyncified` already goes through the same transformation here): out of fuel unwinds the stack into the memory, the host refuels and rewinds. **A snapshot of the state is not wanted** and is not planned. See also the budget per context in [context_concept.md](context_concept.md) |

### Python versions

3.11 is the oldest; abi3 wheels are `cp311-abi3`. The whole suite runs on 3.11 (Pre-commit, Coverage) and on 3.15 and 3.15t on Linux, Windows and macOS (`python-versions.yml`), all green.
- **3.15t** (free-threaded): no abi3, so the extension is native (`cp315-cp315t`); the tests of abi3 are skipped (`needs_abi3`). The extension does not declare that it runs without the GIL, so importing it turns the GIL on. **Measured 2026-10-22 ([experiments/free_threading/](experiments/free_threading/)): with the declaration added by hand a module with no state runs 3.7-4.0x faster on 4 threads; not declared in wasmext until the Python side of an instance is audited. **Stack overflow in a thread: fixed** (the entry sets the thread up, `src/wasmext/_gen.py`, `tests/test_threads.py`); compared with `WASM_RT_STACK_DEPTH_COUNT` (section 4 of the same README): the count removes the setup but is about 4 times slower on calls inside a module and its limit counts frames, not bytes. Found on the way, with the GIL too: a stack overflow in a thread other than the one that imported the extension kills the process (no `wasm_rt_init_thread` in the extension).** **To be declared** (for 3.14t and 3.15t) once the use of one instance from several threads is audited, and **after the context** ([context_concept.md](context_concept.md)) so that the audit is not done twice; not done.
- **3.15** names an abi3 file with the platform (`add.abi3-x86_64-linux-gnu.so`); `abi3_possible()` and the tests accept `.abi3.` and `.abi3-<platform>.`, and not `.abi3t.so`.
- **abi3t** (the stable ABI of 3.15t, PEP 803) is **not built**: cibuildwheel does not tag it yet, and the glue would have to lose `PyObject_HEAD`. On a free-threaded 3.15, `Py_LIMITED_API=0x030B0000` turns abi3t on by itself and the generated C does not compile, so the resolver keeps saying "native" there.
- **Examples**: `build = "cp311-* cp314t-* cp315t-*"` in coremark, link, lua, quickjs, plugins and wabt (`products` is `py3-none`, so `cp311-*` only); all 47 jobs of `example-wheels.yml` passed at `ca35834`.
- **The abi3 wheel on newer Pythons**: the `cp311-abi3` wheel of coremark, built on 3.11, passes its tests on 3.12 to 3.15 (the job `abi3-wheel-on-newer-pythons`).

### How to choose the next features

On demand, not in advance. The examples of [wasm2mpy](https://github.com/vshymanskyy/wasm2mpy) and [pywasm3](https://github.com/wasm3/pywasm3) are taken one by one, the simplest first, and added as examples or tests; a feature is built when the next example needs it. The examples of [py-wasmhost](https://github.com/ballistics-lab/py-wasmhost) are more complex and come after those.
