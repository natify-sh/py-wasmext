# One shape for fusedwasi: p1 and p2 (a proposal, before wasmext and wasmhost)

Status: **taken up again on 2026-10-26 (see `fusedwasi_p1_over_p2.md`): the owner decided on one state, as Wasmtime has, and p1 on top of p2; the design is in that file, and what is below is the earlier draft.** (Earlier the same day: *set aside: not what the owner meant.* The owner's concern was how the originals of the host's calls are taken and how the user's imports are put in (`WASI_TARGET_PLAN.md`, "The structure of a module"), not the inside of fusedwasi, and no WASI 0.1 call is to go through the layer of `wasi:*@0.2` (p1 runs as p1, p2 as p2; a p1 module that has to be p2 is converted at build time, outside the host). The adapter `p1-on-p2` is dropped; the cut of p2 into a typed core waits for `lift` / `lower`. What is left of this file, at a low priority and with no link to the context: the merge of the duplicated file code of p1 and p2 (the system layer), and the three defects of the p2 host at the end. The text below is kept as it was written. The order the owner asked for (2026-10-26): **unify fusedwasi first, then integrate the unified thing in wasmext and wasmhost.** Anything in wasmext that was made for one shape (the trampoline of p1 in the glue, `wasi2_python.h`, the library config of `_shared.py`) is redone on top of the new fusedwasi, and nothing of wasmext's context (`context_concept.md`) is built until this is settled. Every change in fusedwasi is a change in **both twins** (C and Python) with the parity tests.

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

## The shape, a draft (2026-10-26; the first step of B; not code yet)

What exists already, found in the code: the seam of the system layer is **there in both twins but in two forms.** In C, p2 has `fusedwasi_p2_sys_*` (`wasi_p2_fs_posix.h`, `wasi_p2_fs_win32.h`: `open_at`, `lstat`, `fstat`, `readlink`, `mkdir`, `rmdir`, `unlink`, `rename`, `link`, `symlink`, `set_times`, `pread`, `pwrite`, `ftruncate`, `fsync`, `list`, ... each over a `dirref` and a `leaf`), while p1 keeps the same work inline in `wasi_p1_core.h` and in `wasi_p1_files_win32.h`. In Python, p1 has a backend class (`Files` in `wasi_p1_files.py`, `PosixFiles`, `Win32Files`, over an `Entry`), while p2 has the same inside `wasi_p2_filesystem.py`. So B is a **merge of two existing seams**, not a new invention: the `sys_*` of p2 in C is the base (it already works on a `dirref` and a leaf, with no WASI inside), the `Files` of p1 in Python is the base of the twin.

### Files, after B

```
include/fusedwasi/
  sys/    fusedwasi_sys.h  fusedwasi_sys_posix.h  fusedwasi_sys_win32.h   the operating system, once
  core/   fusedwasi_core.h                                                 config, hooks, memory, failure, exit
  p1/     wasi_p1.h  wasi_p1_unstable.h  wasi_p1_core.h                    descriptors, errnos, the calls of 0.1
  p2/     wasi_p2_<package>.h  (typed core)   +  wasi_p2_abi_<package>.h    the cut (below)
src/fusedwasi/
  sys/    base.py  posix.py  win32.py                                      the twin of sys/
  core.py                                                                  the twin of core/
  p1/  p2/                                                                 as now, over sys and core
```

### The system layer (`fusedwasi_sys_*`)

No WASI in it: no `wasi` in a name, no rights, no resource, no handle. It takes the `dirref` + leaf form of p2 as it is, and answers with **one neutral error set**, `fusedwasi_err` (`FUSEDWASI_E_NOENT`, `_EXIST`, `_ACCES`, `_NOTDIR`, `_ISDIR`, `_NOTEMPTY`, `_LOOP`, `_NAMETOOLONG`, `_XDEV`, `_PERM`, `_NOSPC`, `_IO`, `_INVAL`, `_BADF`, `_PIPE`, `_NOTSUP`, `_UNKNOWN` and the rest that either front end uses; named as the errno of the system, and not as an errno of WASI or an `error-code`). Each front end has **one table** from `fusedwasi_err` to its own vocabulary (the errno of 0.1, the `error-code` of `wasi:filesystem`, of `wasi:sockets`, the `stream-error`): the two tables are the only place the mapping lives. p1 needs a few operations that p2 does not have as separate calls (a descriptor with a cursor: `read`, `write`, `seek`; `allocate`; `set_flags` for append and nonblock; `advise`; `fdatasync`); they are added to the layer, and p2 uses what it needs of them.

```c
typedef int fusedwasi_err;                       /* 0 or FUSEDWASI_E_* */
typedef struct fusedwasi_dir fusedwasi_dir;      /* a directory below which names are looked up (an fd, or a path on Windows) */
typedef struct fusedwasi_file fusedwasi_file;    /* an open file */
fusedwasi_err fusedwasi_sys_open_at(fusedwasi_dir *dir, const char *leaf, uint32_t open_flags, uint32_t flags, fusedwasi_file *out);
fusedwasi_err fusedwasi_sys_stat_at(fusedwasi_dir *dir, const char *leaf, int follow, fusedwasi_stat *out);
fusedwasi_err fusedwasi_sys_read(fusedwasi_file *f, void *buf, size_t n, size_t *got);          /* cursor */
fusedwasi_err fusedwasi_sys_pread(fusedwasi_file *f, void *buf, size_t n, uint64_t off, size_t *got);
fusedwasi_err fusedwasi_sys_seek(fusedwasi_file *f, int64_t off, int whence, uint64_t *pos);
/* ... mkdir rmdir unlink rename link symlink readlink set_times truncate sync list close: as in p2 today */
```

**One definition of the sandbox lives here:** what is "below a directory" (no `..` that leaves, a symlink that leads out is refused or followed inside, a case of Windows names), the open of a path component by component, once. Today it is written twice.

The twin: `sys/base.py` has an abstract class `Sys` with the same names and the same return convention (an error number from one set, as `fusedwasi_err` is, returned in a tuple the way `Files` does today), `posix.py` and `win32.py` implement it. A parity script (the existing one for files, aimed at `sys`) runs one scenario in both and compares what they answer.

### The core: one configuration, one memory API, one failure

```c
typedef struct {                                  /* every field may be zero */
    const char *const *args;  size_t nargs;       /* NULL: the name of the program alone */
    const char *const *env;   size_t nenv;        /* "NAME=value" */
    const fusedwasi_preopen *preopens;  size_t npreopens;      /* {host path, guest name, writable} */
    fusedwasi_hooks hooks;                         /* below */
    fusedwasi_policy net;                          /* sockets / dns / http decisions, refused by default */
    void *user;                                    /* the host's own, given to every hook; never freed by the core */
} fusedwasi_config;
typedef struct {                                  /* one set of hooks for both versions; a hook answers 0, FUSEDWASI_E_*, or FUSEDWASI_HOOK_TRAP */
    int (*stdin_read)(void *user, uint8_t *buf, size_t cap, size_t *got);
    int (*stdout_write)(void *user, int fd, const uint8_t *buf, size_t n);   /* fd 1 or 2 */
    int (*clock)(void *user, uint32_t id, uint64_t *ns);
    int (*random)(void *user, uint8_t *buf, size_t n);
    int (*sleep)(void *user, uint64_t ns);
    void (*end)(void *user, int how, uint32_t value);                          /* the program is over */
} fusedwasi_hooks;
```

- **One way to give it:** `fusedwasi_p1_create(&config, ...)` and `fusedwasi_p2_init(&s)` + `fusedwasi_p2_configure(&s, &config)` read the same `fusedwasi_config`; a host that speaks both fills it once (two states, one configuration). The old p1 `fusedwasi_p1_config` and the fields of the p2 state are kept as wrappers for a release.
- **Memory:** `fusedwasi_set_memory(state, comp, base, size)` for both (a copy, set again when the memory may have moved; `fusedwasi_bind_memory(state, comp, &data, &size)` is the convenience for an engine that keeps the base and size in fields: it fills the copy before each call through one macro). The trampoline of the glue does the refresh; measured, it is free.
- **Failure:** one callback `fail(state, code, message)`, noreturn where the host can jump (wasm2c: `wasm_rt_trap`; Python: an exception); a call of p1 loses its `trapped` parameter when the build says the host can jump, and keeps it behind a macro (`FUSEDWASI_NO_JUMP`) where it cannot. The end of the program: `end` hook plus the record `exited` / `exit_code` (p1 adds `finished`, `end_value` as aliases).

The twin: `core.py` has `Config` (a dataclass with the same fields and names) and the same hooks as callables; `State` of p1 and `Host` of p2 take a `Config`.

### The cut of p2 (the requirement of the adapter)

Each function of p2 becomes two: a **typed core** that works on values and handles and knows nothing of the memory of the guest, and a **wrapper of the canonical ABI** that reads the arguments out of the memory (strings, lists), calls the core, and writes the result to the memory (through `cabi_realloc` where the layout asks for it).

```c
/* typed core (wasi_p2_filesystem.h): no pointers into the guest */
fusedwasi_p2_err fusedwasi_p2_descriptor_open_at(fusedwasi_p2_state *s, uint32_t self, uint32_t path_flags,
                                                 const char *path, size_t path_len, uint32_t open_flags, uint32_t flags, uint32_t *handle_out);
/* wrapper of the canonical ABI (wasi_p2_abi_filesystem.h): what the import of the module calls today */
void fusedwasi_wasi_filesystem_types_descriptor_open_at(fusedwasi_p2_state *s, uint32_t comp, uint32_t self, uint32_t path_flags,
                                                        uint32_t ptr, uint32_t length, uint32_t open_flags, uint32_t flags, uint32_t retptr);
```

The names of the wrappers (`fusedwasi_wasi_<iface>_<name>`) and their signatures **do not change**: wasmext's table (`_wasi_p2_table.py`), the generated trampolines and the tests stay as they are. The typed core is new, and it is what the adapter `p1-on-p2` calls (a module of 0.1 has no `cabi_realloc`), and what `lift` / `lower` in Python will call. In the twin the same cut: `wasi_filesystem_types_descriptor_open_at(host, comp, ...)` stays, over a new `descriptor_open_at(host, self, path_flags, path: bytes, ...) -> handle`.

The order inside p2 follows the use: the cut is made first for the packages the adapter needs (`filesystem`, `io` streams for stdin/stdout, `clocks`, `random`, `cli` environment and exit); `sockets` and `http` follow, since p1 has no use of them yet.

### What does not change (and so is not touched by B)

The table of what a guest holds, in each front end; the shape of each call in the ABI of its version; the vocabulary of errors, apart from the two mapping tables; `poll_oneoff` and `wasi:io/poll`; `proc_exit` / `proc_raise` and `cli/exit`. The wrappers of the old names, for one release.

### Steps of B, each green before the next

1. **The system layer for files, p2 first.** Rename `fusedwasi_p2_sys_*` to `fusedwasi_sys_*` over `fusedwasi_err`, add the operations of p1, one sandbox; the table `fusedwasi_err` to `error-code`. Twin: `sys/`. The tests of p2 (filesystem, C vs Python) stay green; the parity script aims at `sys`.
2. **p1 moves onto it.** `wasi_p1_core.h` and `wasi_p1_files_win32.h` lose their file code; the table `fusedwasi_err` to the errno of 0.1. The official test suite for p1 (in wasmext's CI) and the p1 tests of fusedwasi stay green. Twin: `Files` becomes the `Sys`.
3. **One configuration.** `core/` and `core.py`; p1 and p2 read `fusedwasi_config` / `Config`; the old entry points are wrappers.
4. **The cut of p2** in the order above, with the wrappers' names unchanged; tests unchanged, plus tests that call the typed core.
5. Then wasmext (the glue, the two `*_python.h`, the library config, the executable), the context, wasmhost; and the adapter `p1-on-p2` over the typed core, with the differential test.

### To settle before step 1

- The exact neutral error set (the union of what both front ends map: to be listed from the two mapping functions that exist, `fusedwasi_p1_errno` and the `error-code` conversion of p2).
- Whether `fusedwasi_dir` is the `dirref` of p2 as it is (an `int` on POSIX, a record on Windows) or a pointer to a small record on both.
- The names (`sys`, `core`, `fail`); `fusedwasi_config` against `fusedwasi_host_config`.

## Found by the experiment of the wasm adapter (2026-10-26): three defects of the p2 host, to be fixed in both twins

See `experiments/p1_adapter_on_p2.md`. They are independent of the unification and small, and the typed core / the adapter p1-on-p2 would meet them: (1) the descriptor that `open-at` makes for a directory should inherit `read` and `mutate-directory` from its parent (to check against the specification and Wasmtime first); (2) `fusedwasi_p2_alloc` must call `cabi_realloc` also for a size of 0 (the canonical ABI does); (3) the random source of the C host must not open `/dev/urandom` on every call. A fix is a change in C and in Python with a test in each, and goes before step 1 of B or with it.
