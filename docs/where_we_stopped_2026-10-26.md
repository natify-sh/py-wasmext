# Where we stopped (2026-10-26): WASI 0.1 over 0.2 is done, the Store is next

A note of the state at the end of a long session on `dev`, so that it is not only in a conversation. **[run]** run here, **[read]** read in a source, **[estimate]** a judgement. Everything below is pushed and the CI was green on the three systems for the commits named.

## 1. State

| Repository (branch) | At | What |
| --- | --- | --- |
| fusedwasi (`wasi-p2`) | `1514ff9` | p1 on top of p2: the arguments, environment, clocks, random bytes, sleep, standard streams, **files** (system layer of 0.2), and the **end of the program** |
| wasmext (`dev`) | `3f34ea5` | the glue and the products over the above; the C API of the shared library changed (below); the policy: an alpha does not keep the ABI |
| wasmhost (`fusedwasi-p1`) | `af6224a` | on fusedwasi `1514ff9` (only the lock moves with fusedwasi) |

Design and status: [fusedwasi_p1_over_p2.md](fusedwasi_p1_over_p2.md). Stages A (streams), B (files), C (the end of the program) are built, in C and in Python, with C-versus-Python parity tests (`tests/data/p1/*.txt`, one script run by both).

## 2. Decisions of this session (each is in the code and in a document)

- **The end of a program is what the call leaves, as in Wasmtime for core modules** (checked: [experiments/wasmtime_exit](experiments/wasmtime_exit/README.md)). `proc_exit` records `exited`/`exit_code` in the state of 0.2, `proc_raise` records `finished`/`end_value` in the state of 0.1, both trap; the glue clears them at the start of the next export call; **nothing is closed, no later call is refused, a trapping command is not over**. `WasiTerminated` is only the base of `WasiExit` and `WasiSignal`. The library answers `TRAP_ENDED` for the call that ended the program and `<name>_wasi_end` says how.
- **The unlink of a directory answers as the system does** (PERM on macOS, ACCES on Windows, ISDIR elsewhere): the suite of WASI wants it.
- **The Windows layer** (`wasi_p2_fs_win32.h` and its Python twin): rename of a directory onto an empty one, symlink onto a taken name is `exist`, `set_times` of a path touches the link itself. Known gap: **Python before 3.13 on Windows** has no `os.utime(follow_symlinks=False)`, so the Python twin follows the link there (the C does not).
- **The C API of the shared library:** an export with one number (`i32/i64/f32/f64`) as its result **answers the number**, `T <name>_<export>(m, ...)`; the code of the last call of any export is `<name>_status(m)` (and `<name>_status_ptr(m)`, the int itself, which the wrapper for ctypes reads without a call). Measured: 875 ns for a call with an out parameter, 501 ns with the value returned; the wrapper for ctypes went from 2265/970/3033 ns (add, nop, a call with a callback) to 715/263/922 ns. Other exports keep `int f(m, ..., out*)`.
- **The wrapper for ctypes builds a method for each signature of numbers** (`_fast_method`, `fast_callback`); the guard against a slow wrapper is a **ratio** to the raw ctypes call (`tests/test_extension.py`, skipped under coverage).
- **ABI:** `WASMEXT_ABI` stays `0x000001A3`. An alpha does not keep the ABI ([abi_policy.md](abi_policy.md), "Alpha does not keep the ABI"): the declaration `abi/current.json` is renewed with `python -m tests.abi_surface --update`, the fingerprint in `_abi.py` when `src/wasmext/c/` changes.
- **C7 (the record of the store for artifacts built apart)** has a draft in [context_concept.md](context_concept.md), "C7, a draft": the state of the host never crosses (opaque to the other artifact, reached through function pointers of the record), so fusedwasi needs no layout version for it. Nothing of it is built.

## 3. What is next (the plan is in [WASI_TARGET_PLAN.md](WASI_TARGET_PLAN.md), "The context: decisions")

1. **C2a: the public `Store`** (`Store(wasi=...)`, `Instance(store, ...)` as the required first argument with the shim, `store.host`, `store.runtime`, a manager for `with`; the trampoline of 0.1 binds the memory of the instance that calls). The blocker (the end of the program as a state of the shared host) is gone.
2. C2e (the calls of `Instance(` in the tests, examples, docs and wasmhost), C3 (the originals of both hosts from `store.host`), C4 (what Python makes, owned by the arena), C5 (`externref`), C2b/C2c (the registry of owners), C6 (tags), C7, C8, then **wasmhost stage 7**.
3. Open and small: the 13 % that the shared library loses to the extension on CoreMark (cause not found; a guess is the interposition of the exported symbols: try `-fvisibility=hidden`, `-fno-semantic-interposition`, `-Bsymbolic`); the Windows gap above; deferred in the plan: `caller`, `lift`/`lower`, the options of https, the final name of `host_full`, `-Os` for the code of the host.
4. **WABT:** the fix of `#2893` (our `return_call_indirect` patch) is merged into `main` of WABT as `f1c4e05`, not in a release; the patch stays for 1.0.42. Left to the maintainers, nothing to do from here.

## 4. How the work is done (the agreements, so that a new session keeps them)

- Never open a pull request, merge, tag or push to `main` unless asked. Commit and push the work of a branch; a stop hook asks for it.
- Extensions have **no run-time dependency** on wasmext or fusedwasi. No compatibility wrappers, no duplicated code in a commit.
- Before a push, in **each** repository: `uv run ruff format`, `uv run ruff check`, `uv run pyright`, and the tests; then **watch the CI** (the three systems) and fix what only Windows or macOS shows. A push cancels the runs in progress. The bot commit "style: auto-fix via pre-commit" does not start the CI.
- `uv.lock` of wasmext and wasmhost points at a commit of fusedwasi: after a change in fusedwasi, `uv lock --upgrade-package fusedwasi` there.
- The suite of WASI: `/tmp/claude-0/run_suite.sh` (extension) and `run_suite.sh exe` (executable), 72 of 72 expected; the scripts are in `/tmp` of the machine and are not in the repository.
- A flaky JavaScriptCore segfault on macOS (3.15t) happened once; one re-run of the failed job is the way, a second failure is real.
- `rm -rf` never with a wildcard; scratch files in `/tmp/claude-0`.
