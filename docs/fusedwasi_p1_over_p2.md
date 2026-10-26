# One state in fusedwasi: WASI 0.1 on top of WASI 0.2 (design, 2026-10-26)

Status: **decided by the owner on 2026-10-26** ("take one state, as Wasmtime does, now, so that it is not redone later"); this reverses the entries that dropped `p1-on-p2` and set `fusedwasi_unification.md` aside. **Nothing here is built.** The work of the Store in wasmext (`WASI_TARGET_PLAN.md`, C2a) stops after its part 1 (`a7e4a4c`) until this is done in fusedwasi, as the owner asked from the start: fusedwasi first, then wasmext and wasmhost. Every change is made in both twins (C and Python) with the parity tests.

## What it is, and what it is not

- A module of 0.1 **stays a module of 0.1**: it imports `wasi_snapshot_preview1`, goes through wasm2c as it is, and nothing is converted or glued before (no `meld`, no `wasm-tools component new`). No import is renamed to `wasi:*@0.2`.
- Inside the host, the functions of 0.1 (`fusedwasi_p1_fd_write`, ...) do not own a state: they work on the **one state** of 0.2 (`fusedwasi_p2_state`: the table of resources, the configuration, the streams, the clocks) through its **typed core**, and keep only what is 0.1's own on top of it (the table of descriptors with their rights, the position of a file, `poll_oneoff`, `proc_raise`). This is what `wasmtime-wasi` does: `p1.rs` uses `WasiCtx` and `ResourceTable` of 0.2, and its `Descriptor` holds `Resource<streams::InputStream>`, `Resource<streams::OutputStream>` and a file (`experiments/wasmtime_store_linker_caller.md`).
- The typed core is the second half of a cut of each function of 0.2 (see `fusedwasi_unification.md`, "The cut of p2"): the **typed core** works on values and handles and knows nothing of the memory of the guest and of `cabi_realloc`; the **wrapper of the canonical ABI** (`fusedwasi_wasi_<iface>_<name>`) reads the arguments out of the memory, calls the core and writes the result. The names and the signatures of the wrappers do not change, so the glue of wasmext, its table (`_wasi_p2_table.py`) and the tests of 0.2 stay.

## The mapping of the 46 calls of 0.1 (to be checked against the code of p1 and the specification when each is moved)

| Calls of 0.1 | Built on (typed core of 0.2) | Kept in 0.1 |
| --- | --- | --- |
| `args_get`, `args_sizes_get`, `environ_get`, `environ_sizes_get` | `cli/environment` (arguments, environment) | the packing into the buffers of the guest |
| `clock_res_get`, `clock_time_get` | `clocks` (wall, monotonic: now, resolution) | the ids 2 and 3 (CPU time of the process and the thread) have no equivalent in 0.2: a small addition to the system layer |
| `random_get` | `random` (get-random-bytes) | |
| `fd_write`, `fd_read`, `fd_pwrite`, `fd_pread`, `fd_seek`, `fd_tell` | the standard streams as streams of 0.2; a file: the open file of the descriptor of 0.2 with the position kept by 0.1 (as `Descriptor::File { fd, position, append }` in Wasmtime) | the offset, `O_APPEND`, `iovec` handling |
| `fd_close`, `fd_renumber` | drop of the resource | the table of fd numbers |
| `fd_fdstat_get`, `fd_fdstat_set_flags`, `fd_fdstat_set_rights` | `descriptor.get-type`, `get-flags` | **the rights** (computed from the flags of the descriptor and from `readonly` of the preopen; `FUSEDWASI_P1_R_*` masks) |
| `fd_filestat_get`, `path_filestat_get`, `fd_filestat_set_size`, `fd_filestat_set_times`, `path_filestat_set_times` | `stat`, `stat-at`, `set-size`, `set-times`, `set-times-at` | the conversion of the structures (`filestat` against `descriptor-stat`) |
| `fd_sync`, `fd_datasync`, `fd_advise`, `fd_allocate` | `sync`, `sync-data`, `advise`; `allocate` has no call in 0.2 | `allocate` in the system layer |
| `fd_readdir` | `read-directory` (the directory-entry stream) | the cookie, the packing of `dirent` |
| `fd_prestat_get`, `fd_prestat_dir_name` | `preopens.get-directories` | the numbering from 3 |
| `path_open` | `open-at` | the translation of `dirflags`, `oflags`, `fdflags`, rights into the flags of 0.2; the sandbox rules (ENOTCAPABLE) |
| `path_create_directory`, `path_remove_directory`, `path_unlink_file`, `path_rename`, `path_link`, `path_symlink`, `path_readlink` | `create-directory-at`, `remove-directory-at`, `unlink-file-at`, `rename-at`, `link-at`, `symlink-at`, `readlink-at` | |
| `poll_oneoff` | `io/poll` (pollables of the clocks and of the streams) | the subscriptions and the events |
| `proc_exit` | `cli/exit` | the code (0.2 knows only ok / err; the code is kept in the state) |
| `proc_raise`, `sched_yield` | none | all of it |
| `sock_accept`, `sock_recv`, `sock_send`, `sock_shutdown` | the tcp-socket of `sockets` (only on a socket that was given to the program) | |

## One state, and what moves

- **One `fusedwasi_state` per store** (the name and the struct are the state of 0.2, widened): the table of resources, the configuration (`args`, `env`, `preopens`, the streams, the clocks, the random bytes, the policies of the network), the end of the program per instance (kept by wasmext, as decided). A module of 0.1 and a module of 0.2 in one store share it. The numbers they see stay different (an fd of 0.1, a handle of 0.2).
- **One configuration** (`fusedwasi_config`): arguments, environment, preopens (read-only flag), the hooks, the policies; the hooks of 0.1 (`stdin_read`, `stdout_write`, `clock`, `random`, `sleep`, `end`) and the callbacks of 0.2 become one set. This is what the hosts of wasmext (the glue, `wasi_python.h`, `wasi2_python.h`, the library config, the executable) fill, once.
- **The system layer is the one of 0.2** (`fusedwasi_p2_sys_*` over `dirref` and a leaf, POSIX and Win32). The files code that 0.1 has of its own (inside `wasi_p1_core.h`, 2359 lines, and `wasi_p1_files_win32.h`, 894 lines; in Python `wasi_p1_files*.py`) is **removed**, not kept: this is the merge of the two seams that B wanted, as a result and not as a step of its own. The few additions 0.1 needs (a cursor on a file, `allocate`, the CPU clocks, `O_APPEND`) go into that layer.
- **Python twin:** `fusedwasi.p1.wasi_p1` is rewritten over `fusedwasi.p2` (core + `Host`), with `Files` and the backends removed.

## Costs and risks, said plainly

- **A big rewrite of a tested p1.** The net is the **72 tests of the official suite** (rust 42, c 14, assemblyscript 16; the pinned ref of `wasi-testsuite.yml`) run through wasmext both ways it is run in CI (as extensions and as native executables), plus the tests of fusedwasi and the parity script `tests/p1_script.py`. **The suite is the gate of every step that touches p1, and p1 is not changed without it running (72 of 72 before and after).** It is run locally by `/tmp/claude-0/run_suite.sh`-style steps (the same as the workflow: prebuild the programs, `run-tests` with `tests/wasi_testsuite/adapter.py`, `check_results.py`), and in CI of wasmext.
- **No small p1-only host:** 0.1 needs the core of 0.2 (about 66 KB at `-O2`, 29 KB at `-Os`, measured), where the p1 host alone is about 35-46 KB. `host_full = false` shrinks less for 0.1. The two together (both families) get smaller than the sum, since the p1 layer is thin.
- **The rights and the sandbox of 0.1 are richer than the flags of 0.2:** they have to be rebuilt on top (Wasmtime does it in `p1.rs`); the differences found in the experiment of the wasm adapter (exit code, `ENOTCAPABLE` against `EPERM`, rights of a preopen, types of the standard streams, CPU clocks, `sock_accept` on a non-socket) are a list of what the tests must check, though that adapter is not this layer.
- **The defects of the p2 host found by the same experiment are fixed first** (they would be inherited): the descriptor of a directory opened by `open-at` must keep `read` and `mutate-directory` as asked and inherit the permission of its parent as the host of Wasmtime does (to check against its source and the specification), `cabi_realloc` must be called also for a size of 0, the random source of the C host must not open `/dev/urandom` on each call.

## The order of the work (fusedwasi, each step green in both twins before the next)

1. **F0:** this design reviewed; the three defects of the p2 host fixed (C and Python, a test each).
2. **F1:** the cut of p2 into the typed core and the wrapper for the packages that 0.1 uses: `cli` (environment, exit, stdio), `clocks`, `random`, `io` (streams, poll), `filesystem`. The wrappers keep their names; the tests of p2 stay green; new tests call the core.
3. **F2:** `fusedwasi_config` and the widened state, one configuration read by both; no wrappers of the old entry points: nothing of fusedwasi is released (alpha), so the old names are changed, not kept.
4. **F3:** p1 over the core, **in place, with no second copy of the code kept in a commit**: the calls that hold no descriptor table (the environment and the arguments, the clocks, `random_get`) move first, one group after another, each commit with the suite at 72 of 72; then **the descriptor table and everything that uses it** (`fd_*`, `path_*`, `poll_oneoff`, `sock_*`, `proc_exit`) move **together in one change**, because they share the table and cannot be half in the old state and half in the new; the old code of those calls (and the files code of p1, C and Python) is deleted in that same change. While it is worked on, a copy of the old p1 may sit in the working tree for a differential run of the same programs through the old and the new (never committed).
5. **F4:** what is left: the files code of p1 and its backends are gone in both twins, the parity script and the tests of fusedwasi green, the official suite 72 of 72 through wasmext (extensions and native executables, three systems in CI).
6. **Then wasmext:** one state in the Store (the Store of `WASI_TARGET_PLAN.md`, C2a continues), the glue, the two `*_python.h` merged, the library config, the executable; then the originals, the registry of the functions, and wasmhost.
