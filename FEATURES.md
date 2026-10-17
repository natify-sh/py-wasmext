# Features and plan

What wasmext does, what it does not do yet, and what comes next. A line says what is true of the code in this branch;
where a test shows it, the test is named, so the claim can be checked (`tests/test_features.py` runs one small module
for each WebAssembly feature through the whole path: `wat2wasm`, `wasmext -i`, import, call).

Status: **done** (works, tested) · **partly** (see the note) · **not yet** (planned or open) · **no** (decided against).

## WebAssembly features

| Feature | Status | Note / test |
| --- | --- | --- |
| 1.0 (MVP) | done | `1.0 mvp` |
| Sign extension | done | `2.0 sign-extension` |
| Saturating float-to-int | done | `2.0 saturating float-to-int` |
| Multi-value, inside the module | done | `2.0 multi-value, inside the module` |
| Multi-value, exported function | done | comes back as a tuple; `2.0 multi-value, an exported function`, `…all number types and a parameter` |
| Multi-value, imported function | done | the callable returns a tuple; `test_an_imported_function_returns_several_results_as_a_tuple` |
| Bulk memory | done | `2.0 bulk memory` |
| Reference types, inside the module | done | `2.0 reference types, inside the module` |
| Reference types in a signature (`funcref`, `externref`) | not yet | the function is left out (export) or the module is refused (import) |
| Mutable globals | done | exported as attributes, see below |
| SIMD (`v128`), inside the module | not yet | the C of wasm2c includes `simde/wasm/simd128.h`, which nothing provides (strict xfail `2.0 SIMD…`) |
| `v128` in a signature | not yet | needs the simde headers and a Python type (proposal: `bytes` of 16) |
| Relaxed SIMD | not yet | same as SIMD (strict xfail) |
| Tail calls | done | `3.0 tail calls` |
| Extended constants | done | `3.0 extended constants` |
| memory64 | done | inside the module, exported as a `memoryview`, addresses above 4 GiB (Linux): `3.0 memory64`, `test_an_exported_memory64_is_a_memoryview_too`, `test_memory64_addresses_above_4_gib` |
| Multi-memory | done | `3.0 multi-memory` |
| Exceptions (legacy `try`/`catch`) | done | `3.0 exceptions`; an exception nobody catches is a `Trap`: `test_an_exception_nobody_catches_is_a_trap`. `try_table`/`exnref` are not tested |
| Threads, shared memory, atomics | not yet | wasm2c can do it (`--enable-threads`, C11 atomics, `wasm_rt_init_thread`); wasmext does not pass the flag (strict xfail `threads`) |
| GC, function references, custom page sizes, compact imports, wide arithmetic | not yet | off in wasm2c by default; the parser refuses GC types; not tried |
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
| Imported mutable globals | not yet | refused when the extension is made; needs a shared `Global` object |
| Imported memories, tables | not yet | refused when the extension is made |
| `Memory`, `Table`, `Global` objects shared by instances | not yet | the design problem: every extension has its own types |
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
| Patch for MSVC on ARM64 | done | `_addcarry_u64` exists only on x64; a regex in `_wasmize.py` |
| Example: CoreMark | done | reference CoreMark of EEMBC, built with `zig cc` by `examples/coremark/build_wasm.py` |
| simde headers | not yet | see the plan |
| Android, Pyodide wheels | not yet | not tried |
| Configuration in `pyproject.toml` only | not yet | |
| Published on PyPI | not yet | until then the example is built with `--find-links` to the wheel of wasmext (see `example-wheels.yml`) |

## Verified, and not

Run locally on Linux x86-64, Python 3.11: the whole suite with gcc 13.3 and with clang 18.1 (`pytest`), `ruff`, `pyright`.
By hand, not in the suite: an abi3 build for a 32-bit CPython 3.12 (`gcc -m32`) of a memory64 module.

**Not confirmed**: the CI matrix (cp311 abi3 and cp314t on Linux, macOS, Windows, x86-64 and ARM64) for the recent
changes — the runners were out of minutes — and MSVC, AppleClang, free-threaded builds.

## Known gaps

- `abort()` in the runtime of wasm2c when the first allocation of a memory fails (strict xfail
  `test_a_memory_that_cannot_be_allocated_is_a_memory_error`). With guard pages every memory reserves about 8 GiB of address
  space, so a process limited to less dies with `os_mmap failed`; `--no-guard-pages` avoids that case, not a memory too big to allocate at all.
- Attributes and methods of `Instance` take the names of the exports; a name that is not an identifier is reachable with `getattr`.

## Plan

In this order (the first ones are small):

1. **The `abort()` of the runtime** → `MemoryError`: replace the four `abort()` of `wasm_rt_allocate_memory` in the copy of the runtime
   by a trap that the glue turns into `MemoryError` (a regex on the copy, like the ARM64 one, that fails loudly if the pattern is gone).
2. **SIMD**: the simde headers (pinned to the commit WABT 1.0.42 uses, `71fd833d…`; from the wabt-package or bundled in wasmext), then
   `v128` ↔ `bytes` of 16 in signatures. Note: simde uses native instructions only if the compiler flags allow, so wheels for the baseline
   x86-64 run SIMD in portable code.
3. **Shared objects**: `Global` (mutable imports and exports as objects), then `Memory`, then `Table` (`funcref`; functions of
   other instances first, Python callables need a native trampoline). Needs a way for extensions to recognise each other's objects.
4. **Threads**: `--enable-threads`, C11 atomics (and MSVC), a shared `Memory`, `wasm_rt_init_thread` per thread.
5. **CI**: the matrix above, once there are minutes; MSVC and macOS problems are expected.
6. Android and Pyodide wheels; `pyproject.toml` configuration; PyPI; reporting `_addcarry_u64` to WABT.
7. Compatibility with the wasm3/pywasm3 examples; WASI (deferred).

## Decisions

- The glue is plain CPython C API, not nanobind, pybind11 or Cython: it is generated, targets abi3 from 3.11 (nanobind's linked mode needs 3.12 for
  that) and needs no C++ or extra build dependency.
- No WASI shim in Python. If WASI comes back, it is an existing C implementation (uvwasi, which WABT uses itself for `wasm-interp`).
- `wasmhost` is a different tool (a facade over engines); its API is a guide for names and errors, the reference for behaviour
  is the specification and the JavaScript API.
