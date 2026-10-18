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
| SIMD (`v128`), inside the module | partly | works when the headers of simde are on the include path (checked with gcc and clang: the SIMD case passes with `-I<simde>`); the plan is that the wabt-package ships them (`wabt_package.include_dir()`, in the open branch `ci/more-wheel-platforms`) and wasmext adds the directory when the C includes `simde/`. Strict xfail `2.0 SIMD…` until then |
| `v128` in a signature | not yet | needs the simde headers and a Python type (proposal: `bytes` of 16) |
| Relaxed SIMD | no (wasm2c) | `wasm2c` 1.0.42 itself aborts (signal 6, no message) on `i32x4.relaxed_trunc_f32x4_s`, so it is not a matter of headers; strict xfail `3.0 relaxed SIMD…` |
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
| Shared `Global`: one mutable global used by several instances | not yet | both ways: a `Global` object that is imported by an instance, and an exported global that is passed on to another instance. The value would live in the object, and wasm2c gets a pointer to it |
| Shared `Memory` and `Table` objects | not yet | the same design problem as for `Global` |
| Recognising the objects of another extension | not yet | the design problem: every extension has its own types, so an instance of one cannot take a `Global` made by another unless there is a common way to tell them apart (a capsule with a tag and the type, for example) |
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

Run locally on Linux x86-64, Python 3.11: the whole suite with gcc 13.3 and with clang 18.1 (`pytest`), `ruff`, `pyright`.
By hand, not in the suite: an abi3 build for a 32-bit CPython 3.12 (`gcc -m32`) of a memory64 module.

### Platforms where a native extension was built and tested

| Platform | What was built | Evidence |
|---|---|---|
| Linux x86-64, glibc | cp311 abi3 and cp314t, gcc 13.3 and clang 18.1 | local, whole suite; CI |
| Linux x86-64, musl | cp311 abi3 and cp314t (`musllinux_1_2`) | CI, the coremark example |
| Linux ARM64 | cp311 abi3 and cp314t | CI job passed (wheel list not inspected) |
| Windows x64 (MSVC) | cp311 abi3 and cp314t | CI job passed (wheel list not inspected) |
| Windows ARM64 (MSVC) | cp311 abi3 and cp314t | CI job passed (wheel list not inspected) |
| macOS Apple Silicon, macOS Intel | cp311 abi3 and cp314t | CI jobs passed (wheel lists not inspected) |
| Linux i386, CPython 3.12 | one abi3 memory64 module, by hand | local, not in the suite |
| Pyodide 4.0.9 (CPython 3.13, wasm32) | the coremark example; its 2 tests passed | local, `cibuildwheel --platform pyodide` |
| Android arm64-v8a (CPython 3.13, NDK 27) | the coremark example wheel is built; tests are skipped | local; **not run** |

The CI rows are from the last green run of `example-wheels.yml` (commit `0e251d8`, cibuildwheel, the example's tests
run on each wheel). Everything added after that commit (signed results, multi-value, exceptions, globals, guard pages,
`wasmimport`, the reference CoreMark) was checked only locally on Linux x86-64 and, for the example, on Pyodide.

**Not confirmed**: the CI matrix for the changes after `0e251d8` — the runners were out of minutes — and PyPy, iOS,
Linux armv7l/ppc64le/s390x/riscv64 and Windows x86 for wasmext itself (the wabt-package wheels for some of them are
a separate matter, see its README).

## Known gaps

- A memory that cannot be allocated when the instance is made (too big, or with guard pages in a process limited in address
  space, which each memory reserves about 8 GiB of) is a `MemoryError`; `--no-guard-pages` avoids the second case. Other `abort()`
  of the runtime (the locks, the signal handlers) are left as they are. A memory that fails to *grow* returns -1, as WebAssembly says.
- Attributes and methods of `Instance` take the names of the exports; a name that is not an identifier is reachable with `getattr`.

## Plan

In this order (the first ones are small):

1. ~~The `abort()` of the runtime~~ → `MemoryError`: done. The copy of `wasm-rt-mem-impl-helper.inc` gets a trap (code `0x7001`) in place of the
   four `abort()` of `wasm_rt_allocate_memory` (and loses the `perror` lines); the glue raises `MemoryError`. The patch fails loudly if
   the function is not what it expects, and is part of the recipe that makes the C be generated again.
2. **SIMD**: the wabt-package ships the simde headers of the commit WABT 1.0.42 pins (`71fd833d…`; `include_dir()`, `simde_commit()`), wasmext adds that directory to the build when the C includes `simde/` (a hook for the dependencies of the C, like the one for the runtime), then
   `v128` ↔ `bytes` of 16 in signatures. Note: simde uses native instructions only if the compiler flags allow, so wheels for the baseline
   x86-64 run SIMD in portable code.
   **Postponed**: it waits for a release of the wabt-package that carries simde (PR #2, `ci/more-wheel-platforms`), which is not
   possible yet. Nothing of it is implemented in wasmext. When the release is out: raise the minimum in `wabt-package>=…`,
   write the hook, turn the strict xfail `2.0 SIMD…` into a normal test, then `v128`. Relaxed SIMD stays out (wasm2c aborts).
3. **Shared objects**, in this order:
   1. `Global`: an object with `value` (read-write if mutable) that an instance imports, and exported globals that can be passed on.
      This is the first because the runtime of wasm2c already asks the host for a pointer to the value of an imported global, so the
      object only has to keep the value alive and say its type and mutability; a mismatch is a `LinkError`.
   2. `Memory`: a memory made by the host or taken from one instance and given to another.
   3. `Table` (`funcref`): functions of other instances first; Python callables need a native trampoline.

   All three need a way for extensions to recognise each other's objects.
4. **Threads**: `--enable-threads`, C11 atomics (and MSVC), a shared `Memory`, `wasm_rt_init_thread` per thread.
5. **CI**: the matrix above, once there are minutes; MSVC and macOS problems are expected.
6. Android and Pyodide in the CI matrix of the example (they build locally, see above); `pyproject.toml` configuration; PyPI; reporting `_addcarry_u64` to WABT.
7. Compatibility with the wasm3/pywasm3 examples; WASI (deferred).

## Design: linking instances (draft, nothing of it is built)

The goal is the "shared objects" of the plan: an instance uses a global, a memory, a table or a function of another instance.
wasmext stays native: no `Global`/`Memory`/`Table` classes copied from the JavaScript API (as `wasmhost` has, because there an
engine owns the objects), but the exports of one instance given as the imports of another.

```python
a = A.Instance()
b = B.Instance({"env": a})        # imports of module "env" are taken, by name, from the exports of a
```

**What wasm2c gives.** The C of a module that imports a global, a memory or a table keeps a *pointer* to it (`u32 *w2c_env_g`,
`wasm_rt_memory_t *w2c_env_mem`, `wasm_rt_funcref_table_t *w2c_env_tab`), taken at instantiation from the accessors
`w2c_env_g(struct w2c_env *)` that the host defines; an exported one has the same shape (`u32 *w2c_m_eg(w2c_m *)`,
`wasm_rt_memory_t *w2c_m_em(w2c_m *)`, `wasm_rt_funcref_table_t *w2c_m_et(w2c_m *)`). So linking is handing the pointer
of the exporter to the importer: one value, one memory, one table, no copy, no Python in between. An imported function is
`w2c_env_f(struct w2c_env *, args)`: the glue can call the exported function of the other module itself (its instance pointer is
the first argument) instead of a Python callable.

**Mixing.** `{"env": a}` takes everything the import module "env" needs from `a`; all or nothing, to begin with. A dict works
as now (callables and numbers). Taking one name from `a` and the rest from Python needs a way to point at an export (an
attribute `a.g` is a number, the pointer is not reachable from Python); a marker such as `a.export("g")` is the candidate, left
open below.

**Recognising an instance of another extension.** The types are not the same objects in two extensions, so `isinstance` cannot
tell. The instance carries a capsule (a `PyCapsule`, usable in the limited API) with a tag and a version, which points to a
table of the exports: for each export its kind, value type, mutability and the pointer, and for a function the C function and
the instance pointer. The format is a contract between versions of wasmext, so it is versioned from the first day; an unknown
version is a `LinkError`, not a guess.

**Keeping the contract still.** Changing it means a new `v2` and every extension built before it fails to link with the new
ones, so it is made to change rarely: the table begins with its own `size`, and new fields are only appended (a reader checks
`size` before it reads one, so an old reader ignores them and a new one knows an old table has not got them); the entries are a
fixed-size record with a `kind` and room for flags; the pointers are those of wasm2c (`u32 *`, `wasm_rt_memory_t *`,
`wasm_rt_funcref_table_t *`), so wasmext adds nothing of its own to what must stay the same. The name `wasmext.link.v1`
changes only if a field is *removed or changes meaning*, which should never be needed. What the table holds is decided
before it is built, from what the three kinds of import need, and written down here first.

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

**Open questions**: the name of the marker helper (or whether `{"env": a}` only, all or nothing, is enough to begin with); whether
the format of the capsule is public API or private until the second user of it exists (proposal: private, documented, versioned).

## Decisions

- **Platforms.** `wasmext` is a pure Python wheel (`py3-none-any`) that depends on the wabt-package, so it installs wherever the
  wabt-package has a wheel (or builds from its sdist with a C++20 compiler): the platforms of `wasmext` are the platforms of the
  wabt-package, and nothing else limits them. Both packages cover the desktop platforms of `cibuildwheel` and nothing outside them
  (no Android, Pyodide or iOS wheels of the tools: `wasm2c` runs on the machine that builds, and an extension for Android or
  Pyodide is built with the wheel of the host, checked on `examples/coremark`). For the wabt-package the wanted set is Linux
  (manylinux and musllinux: x86_64, aarch64 as the core; i686, armv7l, ppc64le, s390x, riscv64 as well), Windows (x64, ARM64; x86 as well)
  and macOS (arm64, x86_64; universal2 as well). Every wheel is linked statically against the C++ runtime (a test checks it on every platform).
  `zig cc` is not a requirement of anyone: it only builds `_core.wasm` of the example (a dev dependency of this repository); the user of
  wasmext brings a `.wasm` made by whatever they like. The platforms of the packages that are built *with* wasmext (like `coremark`)
  can be more than these, Pyodide and Android among them.

- The glue is plain CPython C API, not nanobind, pybind11 or Cython: it is generated, targets abi3 from 3.11 (nanobind's linked mode needs 3.12 for
  that) and needs no C++ or extra build dependency.
- No WASI shim in Python. If WASI comes back, it is an existing C implementation (uvwasi, which WABT uses itself for `wasm-interp`).
- `wasmhost` is a different tool (a facade over engines); its API is a guide for names and errors, the reference for behaviour
  is the specification and the JavaScript API.
