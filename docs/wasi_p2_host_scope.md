# The size of a host of WASI 0.2

Status: **a count, 2026-10-22.** How a fact is known: **[read]** the WIT of the tag `v0.2.12` of `WebAssembly/WASI` (the repository also has the branch `wasi-0.2`), parsed with `wasm-tools component wit --json`;
**[run]** the imports of the programs of the studies ([wasi_p1_vs_p2_host_requirements.md](wasi_p1_vs_p2_host_requirements.md)) and the hosts in `examples/`. Script and full table:
[experiments/wasi_p2_scope/](experiments/wasi_p2_scope/).

## The size, in numbers

WASI 0.2 is **7 packages** (`cli`, `clocks`, `filesystem`, `http`, `io`, `random`, `sockets`), **31 interfaces**. For a host the unit is an **import**: a function, or the `[resource-drop]` of a resource.
Without the two exports (`wasi:cli/run#run`, `wasi:http/incoming-handler#handle`) and without the unstable items (4 functions, hidden behind features):

| Package | Interfaces | Functions | Drops | **Imports** | Seen in programs | Implemented | Stubbed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cli | 11 | 11 | 2 | 13 | 12 | 10 | 0 |
| clocks | 2 | 6 | 0 | 6 | 6 | 6 | 0 |
| filesystem | 2 | 30 | 2 | 32 | 29 | 24 | 5 |
| http | 3 | 52 | 11 | 63 | 0 | 0 | 0 |
| io | 3 | 19 | 4 | 23 | 12 | 11 | 0 |
| random | 3 | 5 | 0 | 5 | 1 | 1 | 0 |
| sockets | 7 | 52 | 6 | 58 | 55 | 17 | 0 |
| **all** | **31** | **175** | **25** | **200** | 115 | 69 | 5 |

- **A command (the world `wasi:cli/command`) can import 137 of them in 27 interfaces** (everything above except `http`). The world `wasi:http/proxy` imports 97 in 11 interfaces (it shares io, clocks, random and a part of cli
  with the command world, and adds the 63 of `http`).
- **Four programs asked for 115 of the 137** (git, git with sockets, hello, CPython with OpenSSL; all C on wasi-libc). **22 were never asked for** by any of them: `initial-cwd`, `descriptor.get-type`, `is-same-object`,
  `filesystem-error-code`, `error.to-debug-string`, `pollable.ready`, the blocking/`skip`/`splice`/`flush`/`write-zeroes` stream calls, `get-random-u64`, `insecure*`, the unused `network` drop and similar.
- The biggest groups: **`http/types` 62** (51 functions and 11 resources: fields, requests, responses, bodies, futures), **`sockets/tcp` 29**, **`filesystem/types` 31**, **`sockets/udp` 21**, `io/streams` 17.

## What the hosts here implement

| Host | Lines | Answers |
| --- | ---: | --- |
| `examples/wasi2_unbundled` `Host` | 293 | stdout/stderr, clocks, `poll`, a TCP client (connect, read, write); the rest raises `NotImplementedError` |
| `examples/wasi2_python` `FsHost` + `NetHost` | 442 + 121 | arguments, environment, `exit`, `random`, clock resolutions, **24 of the 30 filesystem functions**, name lookup (IPv4), TCP client with address/shutdown |

Counted by name: **69 of the 200 imports are implemented, 5 are stubs** (`advise`, `sync`, `sync-data`, `set-times`, `set-times-at` answer ok and do nothing). Of the 137 of the command world, **40 were asked for and are
not implemented**: **35 in `wasi:sockets`** (18 of `tcp`, all 18 of `udp`, `create-udp-socket`: bind, listen, accept, options, datagrams) and the 5 stubs. So **what a CPython or a git on WASI 0.2 asks for is
covered by the host of `wasi2_python` except UDP and the server side of TCP**; that is why `print`, `ssl`, an HTTPS request and `pip install` ran.

## Size of the rest **[estimate]**

- To cover the **command world** (137): +63 imports on top of the 74 answered. About **35 of them are sockets** (`bind`, `listen`, `accept`, the socket options, UDP) and are the same kind of code as the TCP client
  already written (a handle table and the `socket` module of Python): in the order of 200 lines. The rest (`blocking-*` streams, `skip`, `flush`, `get-random-u64`, `initial-cwd`, `get-type`, `is-same-object`, `to-debug-string`, `pollable.ready`,
  the real `set-times`/`sync`) are one to ten lines each.
- **IPv6** is not written in the sockets (the address variants are flattened to more numbers); it adds code to every call that takes an address.
- **`wasi:http` (63) is another size**: the host needs an HTTP client and, for `incoming-handler`, a server, and the types (`fields`, `request`, `response`, `incoming-body`, `future-incoming-response` with `poll`) are
  resources with ownership rules; no program here uses it. It is the largest block after sockets and filesystem, and CLI programs do not need it.
- **Not a sandbox:** the filesystem host trusts the guest's paths (`..`, symbolic links); a real host has to confine them. This is a size, not a count.
- The implemented functions are not all complete: for example `input-stream.read` never blocks (it answers an empty list when nothing is ready) and the TCP connect is blocking.

## Against the WASI 0.1 wasmext has in C

wasmext's WASI 0.1 (`wasi_core.h`, 1990 lines in C inside the module) answers `wasi_snapshot_preview1` in C (the study counted 42 of the 46 calls the programs made) and asks the host for none; WASI 0.2 asks the host for **137 imports for a command** (200 with `http`).
Same programs, same results ([wasi_p1_vs_p2_host_requirements.md](wasi_p1_vs_p2_host_requirements.md)). A host of 0.2 inside the module would be a work of the size of `wasi_core.h` plus the canonical ABI
(strings, lists, results through memory, resources as handles).

## The layout of a host of WASI 0.2 in C (a plan, 2026-10-22; nothing of it is built)

Decided in the discussion (the owner's constraint stays: a host of 0.2 is an example, not a part of wasmext, until it is decided otherwise):

- **Like `wasi_core.h` of 0.1, one file per package, header-only, every function `static`**, so that the compiler drops what a module does not use. `wasi_core.h` is 1990 lines for the 46 calls of 0.1 on three systems; 137 imports of the command world are estimated at **4 to 6 thousand lines** of C (an estimate from the sizes of the Python hosts in `examples/`, 293 + 442 + 121 lines for 69 imports; not measured).
- **No `#define` for the choice of a function or a package.** The defines stay what they are in 0.1: the system and the backend of files (`_WIN32`, `WASMEXT_WASI_PYTHON_FS`). **The choice is made by the generator, from the names of the imports of the module** (`wasi:cli/stdout@0.2.12` and so on), as for 0.1 it is made from `wasi_snapshot_preview1` / `wasi_unstable`; it includes the files of the packages that appear and the ones they need. A version `@0.2.x` is matched by its prefix, so that a host works with `0.2.6` and with `0.2.12`.
- **The files** (prefix `wasi_p2_`, so that no name meets `wasi_core.h`; each includes what it needs and has a guard):

| File | What | Includes |
| --- | --- | --- |
| `wasi_p2_core.h` | the state of the host, the **one table of resources** (streams are used by cli, filesystem and sockets), the helpers of the canonical ABI (strings, lists, records, variants, option, result, flags, resources) | |
| `wasi_p2_io.h` | streams, poll, error | core |
| `wasi_p2_clocks.h`, `wasi_p2_random.h` | clocks, random | core |
| `wasi_p2_cli.h` | stdin, stdout, stderr, environment, exit, terminals | io |
| `wasi_p2_filesystem.h` | filesystem | io, clocks |
| `wasi_p2_sockets.h` | sockets (Winsock on Windows: `-lws2_32`), the part that is not implemented answers "not implemented: name" | io, clocks |

- **`http` is not in the first round** (63 imports of the world `wasi:http/proxy`, not of `command`; none of the four programs asked for one): a file `wasi_p2_http.h`, included only when the module imports `wasi:http/...`, if a component of Rust or JavaScript has to be run.
- **Names** carry the interface (`wasi_cli_stdout_get_stdout`): `get-stdout` and similar names repeat in the interfaces, which in 0.1 they did not.
- **What the module asks for is the check:** an import that the host has no function for becomes a function that traps with "not implemented: <name>", and the build says it; the list of the requirements of a module (21 imports for the simple pair, 42 for the complex one) is the test.
- **Several memories** (a module fused by meld has one for each component): the call of an import takes the memory and the `cabi_realloc` of its component, which the import map of meld 0.65 states (`"version": 2`); the host of 0.1 is bound to one memory.
- **The types of WIT** are not in the fused core module (it has flat `i32`); they come from `wasm-tools component wit --json` of the source component. A generator of the glue from the official WIT (a script in the repository, its result committed) was suggested for the repetitive lifting and lowering, **once, not for each module**; the bodies (what `path_open` does) are written by hand and some of them can use the backend of 0.1.

### Is anything in the plans a blocker for `wasi_p2_*.h`? (a check, 2026-10-22)

Read in FEATURES.md ("What is open"), `where_we_stopped`, `abi_policy.md` and the notes: **no.** WASI 0.2 has no row among the open items that it depends on, and the pieces it needs are there: multi-memory (done), a core module fused by meld 0.65 (the bugs #512/#513 fixed), the repair of imported functions in element segments (`_repair_imported_elements`, and WABT #2903), `wasi_flavor` (tells a component from a fused module), the state of a host per instance as in `WASI_STATE` of 0.1 (so the context is **not** needed). What is new work: the generator part that binds the imports `(interface, name)` to the functions, the choice of memory and `cabi_realloc` for each import (the host of 0.1 is bound to one memory), the canonical ABI helpers and the bodies. The files would be in `src/wasmext/c/`, which are in the fingerprint of the ABI (`tests/test_abi.py`): a new file only adds, so the fingerprint changes and the number stays (`abi_policy.md`). **The one constraint is the owner's earlier decision that a host of 0.2 is an example and not a part of wasmext; it is the owner's to lift.**

### The shape of the host: parallel C and Python, flat functions, a state and no globals (decided in the discussion, 2026-10-22)

- **Two hosts in parallel with the same structure:** `wasi_p2_*.h` (C) and `wasi_p2_*.py` (Python), a file for a package in each. They are tested **apart from the AOT compiler** (`natify`/wasm2c is not needed): a test gives a host a fake memory (an array of bytes) and the arguments as the flat ABI of the core module gives them, and reads the results out of the memory; the C and the Python host get the same input and their outputs are compared; the behaviour is compared with Wasmtime on the same components. A module through wasm2c is the integration test later. The Python host may later move to `natify-sh/wasmhost` (it has to depend on nothing of wasmext: a memory and values in, values out; what is in that repository was not looked at).
- **One table of the signatures, made once from the WIT** (`wasm-tools component wit --json`), used by both, so that they do not drift. A subset first (clocks, random, cli, io/streams, the minimum of the filesystem), parity proved, then the rest: not 137 functions twice at once.
- **The surface is flat functions**: in the fused core module a method is `[method]output-stream.write(handle, ptr, len, retptr)`, a constructor `[constructor]...`, a resource is an `i32`. **The state is not flat**: a table of handles (`own`/`borrow`, drop), streams of several kinds behind one interface (stdout, a file, a socket, a pipe: classes in Python, a struct with a tag and function pointers in C) and pollables. Not a deep hierarchy: the table and one or two base types.
- **No globals.** Everything that changes (the table, streams, pollables, the bound memories and `cabi_realloc`, buffers) is in one structure `wasi_p2_state` made for an instance and passed as the first argument (`void *s`, like `WASI_STATE(s)` of 0.1); no mutable `static` and no thread-local in `wasi_p2_*.h`; in Python a class `Host` holds the table and there is no mutable state at the level of the module. Constant tables (names, signatures) are allowed. What two instances share (a common stdout) is passed in explicitly when they are made. Reasons: several instances and several modules in one process, threads and free-threading, tests in parallel, the context. Also: a handle carries a generation counter to catch a use after the drop; the state is "one thread for a state" or has a lock (to be chosen and written down); the state holds the memory of each component by number, and an import takes its own.

### Where the files are, and what is built (2026-10-22)

**Decided by the owner: the host of 0.2 becomes a part of wasmext, but is not in the ABI yet.** The constraint "an example, not a part of wasmext" is lifted. The files:

- C: `src/wasmext/c/p2/wasi_p2_<package>.h`; Python: `src/wasmext/p2/wasi_p2_<package>.py` (a subpackage, `wasmext.p2`). The C is in a **subdirectory**, which `abi_fingerprint` does not read (it reads the files of `c/` only), so the ABI number and the fingerprint do not change; `pyproject.toml` ships both. Nothing here is promised, and no module of the generator includes them yet.
- **Built: `core`, `clocks` (6 imports), `io` (23 imports: `error`, `poll`, `streams`), `random` (5 imports), `cli` (13 imports) and `filesystem` (32 imports)**, C and Python, one package at a time as decided. Core: `wasi_p2_state` / `Host` (memories by number, the table of handles with a generation in the top 12 bits and the index in the low 20, the clocks as hooks so that tests can fix them, a `trap` hook), the checked little-endian stores. No mutable global.
  Clocks: `wall-clock` `now`/`resolution` (a `datetime` through the pointer), `monotonic-clock` `now`/`resolution`/`subscribe-instant`/`subscribe-duration` (a pollable is a slot of the table with an object that answers `ready`, which `io` shares: deadlines, streams).
  Io: `error` (`to-debug-string` through the `cabi_realloc` of the component, a hook of the state), `poll` (`ready`, `block`, `poll` of a list, an empty list traps), `streams` (read/skip, write/check-write/flush, `write-zeroes`, `splice` and the blocking forms, `subscribe`, drops; a write of more than `check-write` traps; `closed` and `last-operation-failed` with an `error` resource). A stream of the host is an object with a few methods (C: a struct of function pointers); `MemoryInput` and `BufferOutput` are in the files, files and sockets come with their packages. The layouts of the results are written in `wasi_p2_io.py`.
  Cli: `environment` (arguments, variables, `initial-cwd`: lists and strings through `cabi_realloc`, list first), `exit` (`exit` and `exit-with-code`: Python raises `Exit(code)`; C calls the hook `exit` of the state, which by default records `exited`/`exit_code` and traps, as `proc_exit` of 0.1 does with its `end` hook), `stdin`/`stdout`/`stderr` and the terminals. **The standard streams are done as in the WASI 0.1 host:** the caller may give a stream; by default Python uses `sys.stdin.buffer`/`sys.stdout.buffer`/`sys.stderr.buffer` **of the moment** (the text layer is flushed first, so that a capture and the order against `print` hold) and C uses the descriptors 0, 1 and 2 (`poll` for readiness; made when first asked for, freed with the state). Every `get-stdout` is a new handle to the same stream; dropping it closes nothing. `get-terminal-*` is `none` unless the state says the stream is a terminal; the terminal resources have no methods.
  Filesystem: `preopens` and the whole of `types` (the 27 methods of `descriptor`, `directory-entry-stream`, `filesystem-error-code`, the drops). **POSIX only** (`dir_fd` / the `*at` calls); Windows is not started. **The paths are confined, as in `wasi_walk` of 0.1:** a path is walked by name, every directory on the way opened with `O_NOFOLLOW` from the one before; `..` cannot go above the directory the descriptor stands for; an absolute path or a link with an absolute target is `not-permitted`; links are expanded by hand (40 at most, then `loop`), the one at the end only with `symlink-follow`. This is a walk by name and not `openat2(RESOLVE_BENEATH)`, so a process that changes the tree under the walk is not stopped (as in 0.1). **Rights:** a descriptor has `read`, `write`, `mutate-directory`; a write without `write` is `bad-descriptor`, a change of a directory without `mutate-directory` and a descriptor given more than its parent has are `not-permitted`; a preopen can be read-only (`Host(preopens=[(path, name, False)])`, `struct wasi_p2_preopen`). Streams over a file (`read-via-stream`, `write-via-stream`, `append-via-stream`) use a duplicate of the descriptor, so they outlive its handle; the `error` of a failed file stream carries the `error-code`, which `filesystem-error-code` returns. Directory entries are a sorted snapshot without `.` and `..`. `advise` is accepted and does nothing; `metadata-hash` is the inode and the device. The errno-to-`error-code` table is the same in both. Not done: Windows, `access` checks beyond what the system says, quotas.
  Random: `get-random-bytes`/`u64`, the insecure pair and `insecure-seed` (a tuple of two u64 through the pointer); the bytes come from hooks of the state (`os.urandom`, `/dev/urandom`, `BCryptGenRandom` with `-lbcrypt` on Windows, which is not tested here), the insecure ones from the same source unless replaced; a request of more than 64 MiB and a source that fails are traps. Every C function is `static inline` (`WASI_P2_FN`) so that the unused ones do not warn.
- **Tests: `tests/test_wasi_p2_clocks.py`, `tests/test_wasi_p2_io.py`, `tests/test_wasi_p2_random.py`, `tests/test_wasi_p2_cli.py` and `tests/test_wasi_p2_filesystem.py`** (a real tree of files, 19 paths against the confinement, symbolic links, loops, read-only preopens, every call of `descriptor`; an extra test of the walk) (the last one also runs the descriptor streams over pipes and checks the Python default against a capture) (the C driver of the io test is clean under ASan/UBSan, run by hand): the same scenario in Python and in C (`tests/data/wasi_p2_clocks_driver.c`), fixed clocks, a fake memory; the outputs are equal (the bytes of the result, the handles, a use of a dropped handle, a pointer outside the memory, a missing memory trap). No wasm2c.
- **Not built:** the table of the signatures from the WIT (the functions are written by hand for now), the check against Wasmtime, the generator part that binds `(interface, name)` to the functions, the other packages (next: `sockets`, `http`). The question of what "nothing" is for a WASI import (an error code or a trap) is not decided.
