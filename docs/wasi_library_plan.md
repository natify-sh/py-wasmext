# After `wasi_p2_*`: a separate WASI host library (plan, not started)

**Status (2026-10-23): a plan; nothing is moved.** The owner leans to **option B** below: "something like uvwasi, but with WASI 0.2 and later WASI 0.3, that works with a *fused component model → core wasm* module". The decision is taken when `wasi_p2_*` is finished (`http`, the Windows parts of `filesystem` and `sockets`, a test against Wasmtime). The numbers in the first table are from a reading of the code on 2026-10-23 (line counts checked); the days are an estimate, not a measurement.

## What there is

| Layer | Files | Lines | Depends on |
|---|---|---|---|
| WASI 0.1 core | `c/wasi_core.h`, `wasi_preview1.h`, `wasi_unstable.h` | 2 370 + 2 × ~37 | `wasm-rt.h`, but only through `wasm_rt_memory_t *memory` (`->data` 39 times, `->size` once) |
| WASI 0.1 files | `c/wasi_files_win32.h` | 896 | Win32 |
| WASI 0.1 Python front end | `c/wasi_python.h` | 1 309 | `Python.h`; stays in wasmext |
| WASI 0.2 | `c/p2/wasi_p2_{core,clocks,random,io,cli,filesystem,sockets,http}.h` | ~5 300 | libc and POSIX (Windows only for the core, clocks, random, io, cli) |

`p2/` is already a library in all but name: header-only, `static inline`, no global and no thread-local, one `wasi_p2_state` with hooks (`trap`, `realloc` = `cabi_realloc`, `wait`, `exit`, `random_bytes`, clocks, `socket_addr_check`, `http_check`, `http_send`), a memory is `{base, size}` for each component (what a fused module with several memories needs), and `c/p2/` is not read by the fingerprint of the ABI. 0.1 comes apart almost mechanically: `wasm_rt_memory_t` becomes `{data, size}`, `WASMEXT_WASI_PYTHON_FS` and the 12 `wasi_be_*` functions become the place of an outside back end.

## The options

* **A, 0.2 only.** A repository (or a directory with its own README, licence, tests and CI) with `p2/`. About 3–5 days: skeleton, SPDX headers, a C test runner (the expected results are now in `tests/test_wasi_p2_*.py` and must move), CI on Linux/macOS/Windows, and wasmext takes it back as a vendored copy or a submodule (the headers are copied to `build/wasmext/<module>/` already).
* **B, 0.1 + 0.2, and 0.3 later (the choice leaned to).** A: plus 4–7 days for 0.1: no `wasm_rt`, a neutral prefix instead of `wasmext_wasi_*`, the Windows files. 0.1 and 0.2 stay **two independent groups of headers in one repository**: they have different errno maps and different file back ends, and sharing code would cost much and give little. The main risk is the fingerprint of the ABI: `tests/test_abi.py` hashes every file in `src/wasmext/c/`, so taking 0.1 out changes it; whether that is "a change of the ABI" is for [abi_policy.md](abi_policy.md) to say (not studied yet).
* **C, nothing is separated.** The headers stay in wasmext. Cheapest; the library is not usable without it.

## What B needs besides moving files

1. **The glue to a fused module.** wasm2c names an import `w2c_<module>_<name>(host, ...)` and a fused module has one memory for each component, so a call of the library `(state, comp, ...)` needs a one-line wrapper for each import (up to 138 for the command world, 63 more for http), with `comp` taken from the suffix of the name. Generate it from a table of names and signatures (the WIT is the source: `docs/experiments/wasi_p2_audit/` already computes the flat signatures); keep the generator in the library or in wasmext's `_gen.py` (open).
2. **WASI 0.3.** The big change is async: `stream<T>`, `future<T>` and `async` functions replace the `pollable`/`wait` loop of 0.2 (a task that waits has to be able to give up the thread). The state of the host must therefore not assume that one call is one run to the end; keep that in mind in `wasi_p2_state` (the `wait` hook is where a scheduler would come in). Nothing of 0.3 is designed yet.
3. **Fused modules are the input.** The library does not read components; the fusing (components → one core module with the lowered imports) is done before it, and the library is only the host side of the imports that remain (`wasi:*`). The tests of the library should therefore include a fused module, not only C drivers that call the functions directly.
4. **Security as a public duty.** The confinement of paths and the policy of sockets and http become promises to other people: fuzzing, a policy for reports, and the tests of the WASI testsuite for 0.1 and a comparison with Wasmtime for 0.2.
5. **Versions.** A public library means semantic versions; while it is alpha it can say that it is unstable.

## Open

* **The name is chosen (the owner, 2026-10-23): `fusedwasi`** (free everywhere; first written `fuzedwasi` by a slip; the name that is reserved is `fusedwasi`). **Reserved: the repository <https://github.com/natify-sh/fusedwasi> and the project <https://pypi.org/project/fusedwasi> on PyPI** (both empty; nothing is moved yet).
* Whether the wrappers of item 1 are generated in the library or in wasmext.
* How the move of 0.1 is counted by the ABI policy.
* Windows `filesystem` and `sockets` (0.2) come before the move or after it.
