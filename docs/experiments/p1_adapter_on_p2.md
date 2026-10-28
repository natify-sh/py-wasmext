# Experiment: a WASI 0.1 program on the WASI 0.2 host through Wasmtime's wasm adapter ("variant 1")

Date 2026-10-26. Done by a subagent in `/tmp/claude-0/exp_adapter` (scripts: `work/pipe.sh`, `fix.py`, `build.py`, `suite.py`, `bench.py`); nothing in the repositories was changed. The numbers are the agent's, read from its report; the explanations marked *(inferred)* were not checked against a source. The owner's decision stands: this is an **experiment, not the path** (a removed note, "Decision"); the useful result is what it showed about the p2 host.

## What it is

`wasm-tools component new P1.wasm --adapt wasi_snapshot_preview1=wasi_snapshot_preview1.command.wasm` gives a component; `meld fuse` (pulseengine/meld v0.65.1, built from source in 2 min; `bytecodealliance/meld` was not reachable) makes ONE core module of it; a ~20-line post-fix (`fix.py`) aliases `cabi_realloc` to the adapter's `cabi_import_realloc` and keeps only `memory` and `wasi:cli/run@0.2.12#run`; then `build(..., host="wasm32-wasip2")`. The adapter is the one of the crate `wasi-preview1-component-adapter-provider` 49.0.4 (Wasmtime 49.0.4, Apache-2.0 WITH LLVM-exception; command adapter sha256 `9d0499d4...df65df8`, 51 826 bytes; imports `wasi:{cli,clocks,filesystem,io,random}@0.2.12`, no sockets, no http). Without `meld`, `component unbundle` leaves 4 core modules (main, adapter, a shim with an indirect-call table, a fix-up module) that import each other's memory and tables, which wasmext cannot take.

## Results

- **It works** for hello, arguments, environment, stdin (100 KB through `cat`, md5 identical), files with `--dir`, clock and random: the same stdout and stderr as native p1.
- **Size:** the core module +10 % (+30 KB on 290 KB programs); the executable +58 % to +260 % (a C test program 1.23 MB to 1.96 MB, hello 115 KB to 413 KB: the larger p2 host plus ~30 KB of adapter code through wasm2c).
- **Speed:** `fd_write` 145 to 158 ns, `clock_time_get` 35 to 41 ns (10-20 % slower); `random_get` **38x slower (299 ns to 11.4 us), which is not the adapter**: the p2 host opens, fstats and reads `/dev/urandom` on every call (`strace`).
- **The official suite (72 tests of `wasm32-wasip1`: rust 42, c 14, assemblyscript 16):** native p1 72/72; adapter on the unmodified p2 host **30/72**; with two small changes to a copy of the fusedwasi p2 host **68/72** (still failing: 3 AssemblyScript tests, and `proc_exit-failure` where the exit code 33 becomes 1).

## Differences from native p1

1. **The exit code is lost** (the adapter): `wasi:cli/exit` takes ok/err, so any non-zero `proc_exit` is 1.
2. **Process and thread CPU clocks** (ids 2, 3): native 0, adapter EBADF; an invalid clock id: EINVAL against EBADF.
3. **`sock_accept` on a non-socket traps in the adapter** (native ENOTSOCK); the adapter has no sockets or http.
4. **Errnos:** `unlink` of a directory EINVAL against EISDIR; a path out of the preopen (`..`, a symlink that escapes) ENOTCAPABLE against EPERM.
5. **File types and stat:** `fd_fdstat_get(0/1)` and `fd_filestat_get(1)` give "unknown" in the adapter; `dev` and `ino` of a path differ.
6. **Rights** of a preopen differ (native `0x3fffffff` both; adapter base `0x7b7fe00`, inheriting `0xff7ffff`).
7. A zero-length `fd_write` / `fd_read` on a bad fd succeeds in the adapter (EBADF native).
8. Two AssemblyScript tests (`args_get-multiple-arguments`, `environ_get-multiple-variables`) trap with an assertion inside the adapter; the cause was not found.
9. Matched: arguments, environment, streams, file create/read/rename/remove, directory listing and order, monotonic and realtime clocks, entropy, `sched_yield`, symlink and link behaviour, `poll_oneoff` on a clock.

## What it showed about the fusedwasi p2 host (independent of this variant)

These three belong to fusedwasi whatever is decided about adapters (a p1-on-p2 layer of our own would hit the same):

1. **`open-at` gives a new descriptor exactly the flags requested**, so a directory opened by a p1 `path_open` has neither `read` nor `mutate-directory`, and creating a file or a directory below it fails (EROFS / EPERM); 37 of 42 Rust tests fail on it; with a copy where a directory child inherits `read | mutate-directory` from its parent, 29 more pass. *(inferred: Wasmtime's host lets a child inherit the parent's permissions, since the suite passes there; the rule was not read in its source.)*
2. **`fusedwasi_p2_alloc` does not call `cabi_realloc` for a size of 0** (`wasi_p2_core.h` ~line 337) and returns `align`; the canonical ABI calls the realloc also for an empty list or string, and the adapter relies on it (`random_get(buf, 0)` and `file_pread_pwrite` trip an assertion). Removing the early return fixed both in the copy.
3. **The random source of the C host opens `/dev/urandom` on every call** (`fusedwasi_p2_default_random_bytes`: `fopen`, `fread`, `fclose`): the 38x. A `getrandom` / `getentropy` call, or a descriptor kept open, would be much cheaper; the Python twin uses `os.urandom`.

## Verdict

Technically viable, about five commands per program (`wasm-tools`, the adapter, `meld`, the post-fix), with Wasmtime-adapter semantics and not ours. It is not a substitute for the native p1 or for the planned `p1-on-p2` layer. Not tried: the reactor and proxy adapters, p1 reactors, Rust `wasm32-wasip1` programs outside the suite, Windows, macOS, `poll_oneoff` on files and sockets.
