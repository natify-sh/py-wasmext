# One shape for fusedwasi: p1 and p2 (a proposal, before wasmext and wasmhost)

Status: **decided on 2026-10-26: B + the adapter of option C as a separate layer ("B + 2"); nothing is built.** See "Decision" at the end. The order the owner asked for (2026-10-26): **unify fusedwasi first, then integrate the unified thing in wasmext and wasmhost.** Anything in wasmext that was made for one shape (the trampoline of p1 in the glue, `wasi2_python.h`, the library config of `_shared.py`) is redone on top of the new fusedwasi, and nothing of wasmext's context (`context_concept.md`) is built until this is settled. Every change in fusedwasi is a change in **both twins** (C and Python) with the parity tests.

## What is different today (read in `include/fusedwasi/p1/` and `p2/`)

| | p1 | p2 |
| --- | --- | --- |
| State | `fusedwasi_p1_state *` on the heap, made by `fusedwasi_p1_create(&config, &err, &bad)` | `fusedwasi_p2_state` in the structure of the instance, `fusedwasi_p2_init(&s)`, then fields and callbacks set |
| Configuration | a `fusedwasi_p1_config` (arguments, environment, preopens, hooks) given at the creation | fields and callbacks of the state itself (`s->args`, `s->socket_addr_check`, `s->wall_ns`, ...) |
| Memory | `fusedwasi_p1_bind(w, &data, &size)`: pointers to the fields of the engine, follows `memory.grow` | `fusedwasi_p2_set_memory(s, comp, base, size)`: a copy for up to 8 memories, set again when it moves |
| A call | `fusedwasi_p1_<name>(state, args..., int *trapped)`, answers an errno of WASI | `fusedwasi_wasi_<iface>_<name>(state, [comp,] args)`, answers the value |
| A failure of the host | `*trapped` (no jump) | `s->trap(s, message)`, which does not return (a jump in the module, an exception in the twin) |
| The end of the program | `finished`, `end_value` | `exited`, `exit_code`, `exit` callback |
| What a guest holds | file descriptors (a table of entries with rights) | resources: a table of handles with a generation, a kind, an object, a destructor; `fusedwasi_p2_stream` |
| Clocks, random, wait | hooks in `hooks` | `wall_ns`, `monotonic_ns`, `random_bytes`, `wait` in the state |
| Network | none (`sock_accept` is the only socket call of 0.1) | `socket_addr_check`, `allow_ip_name_lookup`, `http_check`, `http_send` |
| Files, POSIX | inside `wasi_p1_core.h` (2359 lines) | `wasi_p2_fs_posix.h` (363) |
| Files, Windows | `wasi_p1_files_win32.h` (894) | `wasi_p2_fs_win32.h` (667) |

So the two share an idea and a name, and little else. Two things are the same work done twice: **the operating-system layer for files** (open below a directory, no escape from it, stat, readdir, rename, links, times, the errors) is written for p1 (POSIX and Win32) and again for p2 (POSIX and Win32); and **the configuration** (arguments, environment, preopens, the standard streams, clocks, random bytes) is stated in two shapes, which each host (wasmext's glue, `wasi_python.h`, `wasi2_python.h`, the library config, the executable, wasmhost) turns into the shape again.

## What can be one

Three layers, from the bottom:

1. **The system layer (`fusedwasi_sys_*`)**, shared by both: files below a directory with no way out, the errors of the system as one set, clocks, random bytes, and (when p1 gets them) sockets. It knows nothing of WASI; it has a POSIX and a Win32 backend, once. p1 and p2 are two front ends over it.
2. **The core: one configuration and one state header**, shared by both. One `fusedwasi_config` (arguments, environment, preopens with read-only, the standard streams, clock, random, sleep, the network and http policies; unused fields are zero), one way to bind memories, one way to say a failure and the end of the program. The hosts (wasmext, wasmhost, the executable) fill **one** structure, whichever version of WASI the module speaks.
3. **The front ends:** `p1` (descriptors, errnos, the calls of 0.1) and `p2` (resources, the calls of 0.2) keep what is truly different: the table of what the guest holds, and the shape of a call that the ABI of each version dictates.

Layer 3 stays two things on purpose: a descriptor of 0.1 and a resource of 0.2 are not the same thing, and the programs of both exist. The alternative, **p1 as an adapter over p2** (what Wasmtime does), is one implementation of the files and the sockets and the strongest unification; it also means rewriting a p1 that passes the official test suite, and it is the biggest risk. It is listed as option C below.

## Decisions that shape the work

**1. A failure of the host: `trapped` or `s->trap`?**
- `trapped` (p1) works where there is no jump (any host), costs a branch at each call.
- `s->trap` (p2, noreturn) keeps the calls simple and is what an engine with a jump (wasm2c) or an exception (Python) does anyway; it needs a host that can jump out of C.
- Proposal: **keep both the ways the front ends already have**, and put the choice in the core as one callback `fail(state, code, message)` that a host implements by jumping or by setting a flag. A call of p1 then is `uint32_t f(state, args...)` and the failure is the callback; the `trapped` parameter becomes optional (a macro) for hosts that cannot jump. To settle: whether the jump-less hosts (the interpreters, WASI in a browser through Python) exist among the users; if not, `trapped` goes.

**2. Memory: pointers to the engine's fields or a copy?**
- Pointers follow `memory.grow` by themselves and need no refresh (p1); a copy lets one state serve **up to 8 memories** of a component (p2's `comp`) and engines that keep memory out of the process.
- Proposal: **a copy, with a `set_memory` that the host calls when the memory may have moved** (the trampoline does it), and a helper for the common case of one memory that is bound by pointers (`bind` stays as a convenience that fills the copy). The cost measured for the trampoline (`capabilities.md`, section 4) is below the noise, so the copy costs nothing that shows.

**3. The configuration.** One `fusedwasi_config`; `fusedwasi_create(&config, version)` returns the state of the version asked for (p1 or p2, or both: two states, one configuration, see `context_concept.md`, "host with both p1 and p2"). The hooks of p1 and the callbacks of p2 become one set of hooks with one signature each. This is the part that wasmext, wasmhost and the executable gain the most from: **one place to fill**.

**4. The system layer.** Moving the POSIX/Win32 file code under `fusedwasi_sys_*` is mechanical work with a big test net behind it (the parity script, the official test suite for p1, the files tests for p2). The sandbox rules (what is "below a directory", symlinks, `..`, case on Windows) must be **one** definition; today they are written twice and could differ.

## Options, from small to large

- **A. Align the surface only.** One `fusedwasi_config` and one set of hooks; p1 and p2 keep their own state and their own files. Smallest; the duplicated file code stays.
- **B. A plus the system layer (recommended).** A, and the OS code of files (and clocks, random) is shared by both front ends. The duplicated code is gone, the sandbox has one definition, and the front ends are small. Medium; the risk is held by the existing tests of both.
- **C. B plus p1 as an adapter over p2.** One implementation of files and sockets; p1 is a thin translation (descriptor to resource, errno to error code). Largest, and the only one that gives p1 the sockets and http of p2 for free; the cost is the rewrite of a tested p1 and a different set of semantics to keep (rights, `fd_*` details). Not before B has held.

## Order of work (for B)

1. **Write down the shape** (this file, then the decisions above settled): `fusedwasi_config`, the memory API, the failure callback, the names. No code.
2. **The system layer for files** in C and in the twin; p2 first (it is the newer, with the cleaner code and more tests of its own), then p1 moves onto it; the parity script and the official test suite must stay green at each step.
3. **One configuration** (`fusedwasi_config`) in C and the twin; p1 and p2 read it; the old entry points stay as thin wrappers for one release, so wasmext keeps working while it is moved.
4. **Then wasmext:** the glue (`_wasi_bind`, the p2 and p1 trampolines), `wasi2_python.h` and `wasi_python.h` merge into one Python side, the library config of `_shared.py` and the executable of `_exe.py` fill the one structure. Then the context (`context_concept.md`, C1 onward), where the host is a private part of it.
5. **Then wasmhost** (stage 7 of `WASI_TARGET_PLAN.md`).

## Open

- Whether jump-less hosts matter (decision 1).
- Whether the state of p1 and p2 is **one** state that can speak both versions (one table of what a guest holds with a kind for descriptors and for resources) or **two states** over one configuration. Two is simpler and is what `context_concept.md` assumed; one saves a copy of the files code only if option C is taken.
- The twin: the Python side of fusedwasi mirrors every function; the shape of the system layer in Python (`os`-based) is a re-statement of the C one and has to be checked against it by the parity script.
- What happens to the Python-side hosts that exist (`wasi_python.h`): they should shrink to a configuration and the hooks that need Python.
- Sockets for p1: not in 0.1 outside `sock_accept`; if the system layer has them, p1 could offer `sock_*` of the later snapshots without being asked.

## Decision (2026-10-26, the owner): B, then the adapter as a separate layer

- **B is the work in hand:** the system layer for files (clocks, random bytes) shared by both front ends, one `fusedwasi_config`, one way to bind memory, one failure callback; two states over one configuration; the old entry points stay as thin wrappers for a release.
- **The adapter of option C is the end of the line, and it is an added layer, not a rewrite:** `p1-on-p2`, the functions of 0.1 written over the state of 0.2. **The native p1 stays as it is** until the adapter has proved its parity (a differential test: the same programs and the official test suite through the native p1 and through the adapter, with the same results); only then is the duplicate looked at. Because it keeps the semantics of the native p1, this is the safe way to the one implementation of the files and the sockets.
- **A requirement that B must carry for the adapter:** p2 is cut into a **typed core** (`descriptor_open_at(state, ...)` answering a value, no pointers into the memory of the guest, no `cabi_realloc`) and a **wrapper of the canonical ABI** (reads and writes the memory, calls `cabi_realloc`, answers the layout the component model wants). Today the functions of p2 are the canonical entries and mix the two, and a module of 0.1 has no `cabi_realloc`, so the adapter cannot call them. The same cut is what `lift` / `lower` will use in Python. The system layer and the typed core are therefore designed together.
- **The wasm adapter of Wasmtime (`wasi_snapshot_preview1.wasm`, composed with a p1 program by `wasm-tools component new --adapt` and `meld`) is an experiment only, not a path:** it needs the gluing of WIT and `meld fuse`, a whole bridge for the sake of lifting p1. It gives the semantics of Wasmtime and not ours. Given to a separate agent as an experiment (what runs, how big, how fast, what breaks); the result goes to `docs/experiments/`.
