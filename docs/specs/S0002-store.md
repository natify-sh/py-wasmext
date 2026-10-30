---
title: Store
kind: spec
id: S0002
status: implemented
superseded_by:
related: []
owner: maintainer
updated: 2026-10-30
---

# S0002 Store

## Summary
Step 2 of layer 1 (see `docs/layers.md`). The store is what a group of instances share and what ends with it. It is static C in
`src/wasmext/c/`: no Python, no module. A host that is not Python uses it as it is.

It has five parts:
1. `wasmext_store.h`: the arena, the counter of active calls with the `closing` flag, the lock, the text of the last refusal,
   `close` and `free`.
2. `wasmext_errors.h`: one table of error codes and their meaning.
3. `wasmext_host.h`: `wasmext_config` and `wasmext_host`, the host of WASI (the state of fusedwasi built from a configuration).
   A store owns its host through the arena.
4. `wasmext_rlock.h`: a recursive lock that can be let go down to a level. It guards the host.

The same header `wasmext_store.h` also holds the members of the store. That part belongs to S0004.

Why. The store was generated per module as C text inside Python strings in `_shared.py` (`<last>_store_t`, `<last>_store_new`,
`<last>_store_close`, `<last>_store_closed`, and the copy of the configuration: arguments, environment, `dirs`, streams, clocks,
sockets). Every module carried its own copy of this logic, and the extension and the wrapper added their own on top. The only static
piece was the trap code `WASMEXT_TRAP_CLOSED` and the stack of traps in `wasmext_glue.h`. The store is the first thing that moves from
the generator into the static core. It rests on what the owner decided in `docs/context_concept.md` (the arena, the hard close, the
counter of active calls, the lock; "context" there is the store) and on `docs/WASI_TARGET_PLAN.md`.

The host of WASI was written three times over the same state of fusedwasi (`fusedwasi_p2_state`, with callbacks for streams, clocks,
random bytes, sleep and the network policies):
* the shared library: `_shared.py` generates C (`_p2_helpers`, `_p2_new`, `api_p2_release`): the struct `<last>_config`, the copy of
  arguments, environment and `dirs`, the hooks over the callbacks of the configuration, the release. All of it carries the module
  prefix and none of it needs the module;
* the extension: `wasi_python.h` (548 lines) and `wasi2_python.h` (356 lines) do the same with Python callables. The glue
  `<name>_glue.h` has a store struct of its own (`wasi`, `wasi_py`, `p2_message`, `wait`, `closed`, ...);
* the executable: through the store of the shared library.

`<last>_config` is the same in every module (the network fields exist only in a 0.2 build, which is the only difference). What is truly
per module is small: the guest of an instance (`wasi_guest_init` binds the memory of that instance by its mangled name) and the
callbacks that need the instance (`trap`, `exit`, `signal`, `realloc`). That is S0003, not this step.

## Goals / Non-goals
* Goals:
  * One plain store in the static core, the same for every module and every front end.
  * `close` never waits. It refuses with a code when a call is in flight, so a `close` from inside a call cannot wait for itself.
    Closing twice is fine. After the close every entry that takes the store fails with a code (`WASMEXT_TRAP_CLOSED` for a call),
    never a crash.
  * Free-threaded safety from the start (a requirement of layer 1): the counter of active calls is split by thread and uses atomics
    (C11-style builtins on GCC and Clang, Interlocked on MSVC). Where there is one thread (`WASMEXT_NO_THREADS`) the plain form is used.
  * One table of error codes and descriptions in one place. The extension and the wrapper kept several.
  * The configuration of the host is checked once, in the core. A bad item gives `EINVAL`.
  * The host is an object made by `wasmext_host_new` and owned by the store through the arena, so the store module stays free of
    fusedwasi and wasm-rt.
  * A failed hook traps the host the way the generated code did (`wasm_rt_trap(WASMEXT_TRAP_HOST)` after keeping the message in the
    host). The state of fusedwasi has no lock, so the host brings one (`wasmext_rlock`).
* Non-goals:
  * Instances (see S0003), owners and the registry (see S0004), tags (see S0007), anything that needs a module.
  * The versioned record `wasmext_store` with `abi`, `floor`, `runtime`, `families`, `retain`/`release`, `attach` and `bind_import`
    (the shared store across separately built modules, step 8 of `docs/layers.md`). A field is not added before the step that tests it.
  * The guest of an instance and its callbacks (see S0003).
  * The Python hooks (`wasi_python.h`, `wasi2_python.h`). They become a front end that gives the static host plain C hooks whose `user`
    is the Python callable, so the logic of streams and policies is written once. That is done in the extension's own step, not patched here.
  * Removing the old generated store (`_shared.py`, the glue of `_gen.py`) and the old copy of the configuration. They stay until
    layers 2 and 3 take them over (rule: no side patches). The tests of the old shape keep running until then.

## Interface

### Where the code lives
Header code compiled into each artifact (each built module has its own copy, as the runtime of wasm2c does). `static inline` functions
in a header, the way `wasmext_glue.h` is. No switch, no separate `.c`. One file defines the counter of the serial of stores:
`WASMEXT_DEFINE_THREAD_STATE` (`wasmext_store_serial_`). Layer 2 later puts the module prefix on the names
(`<last>_store_new` calls `wasmext_store_new`) in the generated file.

### `src/wasmext/c/wasmext_store.h`
Results of the functions of the store:
```c
#define WASMEXT_STORE_OK 0
#define WASMEXT_STORE_CLOSED 1    /* the store is closed (or closing) */
#define WASMEXT_STORE_BUSY 2      /* a call is in flight: nothing was closed */
#define WASMEXT_STORE_NOMEM 3
#define WASMEXT_STORE_DUPLICATE 4 /* the pointer is a member of the store already */
#define WASMEXT_STORE_UNKNOWN 5   /* the pointer is not a member of this store */
#define WASMEXT_STORE_WRONG 6     /* the handle is of another store */
#define WASMEXT_STORE_STALE 7     /* the handle is of a member that is gone */
#define WASMEXT_STORE_LINES 8
#define WASMEXT_STORE_ERROR_SIZE 256
```
Types:
```c
typedef struct wasmext_arena_node_ { void *object; void (*release)(void *object); struct wasmext_arena_node_ *next; } wasmext_arena_node;
typedef struct { wasmext_counter active; char pad_[64 - sizeof(wasmext_counter)]; } wasmext_store_line_;   /* one cache line each */
typedef struct {
    wasmext_store_line_ lines[WASMEXT_STORE_LINES];
    wasmext_counter closing;   /* 1 while `close` decides, and for good once it has succeeded */
    wasmext_counter closed;    /* 1 once the arena is let go */
    WASMEXT_MUTEX_T mutex;
    wasmext_arena_node *arena;    /* the last owned first */
    wasmext_arena_node *adopted;  /* freed when the store is freed (not at the close) */
    wasmext_registry registry;    /* see S0004 */
    void *host;                   /* the host of WASI, opaque here: set once; owned through the arena */
    void *host_lock;              /* its lock, for the code that calls into the host from the instance */
    char error[WASMEXT_STORE_ERROR_SIZE];
} wasmext_store;
```
Portability layer (GCC/Clang, MSVC, or `WASMEXT_NO_THREADS`): `wasmext_counter`, `wasmext_atomic_add/load/store`, `WASMEXT_THREAD_LOCAL`,
`WASMEXT_MUTEX_T`, `WASMEXT_MUTEX_INIT/DESTROY`, `WASMEXT_LOCK`, `WASMEXT_UNLOCK`. Any other compiler is an `#error`.

Functions:
```c
wasmext_store *wasmext_store_new(void);                       /* NULL when out of memory */
int  wasmext_store_closed(const wasmext_store *s);            /* also true for NULL */
int  wasmext_store_enter(wasmext_store *s);                   /* the line to give back to leave, or -1 when closed or closing */
void wasmext_store_leave(wasmext_store *s, int line);
int  wasmext_store_own(wasmext_store *s, void *object, void (*release)(void *object));
int  wasmext_store_set_host(wasmext_store *s, void *host, void (*release)(void *object), void *lock);
void *wasmext_store_host(wasmext_store *s);
void *wasmext_store_host_lock(wasmext_store *s);
void wasmext_store_set_error(wasmext_store *s, const char *text);
void wasmext_store_error(wasmext_store *s, char *buffer, size_t capacity);
int  wasmext_store_adopt(wasmext_store *s, void *object, void (*free_fn)(void *object));
int  wasmext_store_unadopt(wasmext_store *s, void *object);
int  wasmext_store_close(wasmext_store *s);
int  wasmext_store_free(wasmext_store *s);
int  wasmext_cell_set_once(void *volatile *slot, void *value);
```
The members of the store (`wasmext_store_register`, `wasmext_store_find`, `wasmext_store_find_kind`, `wasmext_store_member`,
`wasmext_store_unregister`, `wasmext_store_each`) are in the same header. Their contract is S0004.

### `src/wasmext/c/wasmext_errors.h`
```c
#define WASMEXT_TRAP_LINK_ERROR ((wasm_rt_trap_t)0x7003)   /* an import was not set */
enum { WASMEXT_ERR_TRAP = 0, WASMEXT_ERR_HOST = 1, WASMEXT_ERR_NOMEM = 2, WASMEXT_ERR_ENDED = 3,
       WASMEXT_ERR_LINK = 4, WASMEXT_ERR_CLOSED = 5, WASMEXT_ERR_UNCAUGHT = 6 };
typedef struct { int kind; const char *text; } wasmext_error_info;
wasmext_error_info wasmext_error_describe(int code);
```
The trap codes it maps are defined in `wasmext_glue.h`: `WASMEXT_TRAP_HOST` (0x7000), `WASMEXT_TRAP_NO_MEMORY` (0x7001),
`WASMEXT_TRAP_ENDED` (0x7002), `WASMEXT_TRAP_CLOSED` (0x7004). 0x7003 is `WASMEXT_TRAP_LINK_ERROR`, defined here. Any other code is a trap
of the runtime of wasm2c; its text comes from `wasm_rt_strerror`.

| code | `kind` | `text` |
|---|---|---|
| `WASMEXT_TRAP_HOST` | `WASMEXT_ERR_HOST` | a host function failed |
| `WASMEXT_TRAP_NO_MEMORY` | `WASMEXT_ERR_NOMEM` | out of memory |
| `WASMEXT_TRAP_ENDED` | `WASMEXT_ERR_ENDED` | the call ended the WASI program |
| `WASMEXT_TRAP_LINK_ERROR` | `WASMEXT_ERR_LINK` | an import was not set |
| `WASMEXT_TRAP_CLOSED` | `WASMEXT_ERR_CLOSED` | the store is closed |
| `WASM_RT_TRAP_UNCAUGHT_EXCEPTION` | `WASMEXT_ERR_UNCAUGHT` | `wasm_rt_strerror(code)` |
| any other | `WASMEXT_ERR_TRAP` | `wasm_rt_strerror(code)` |

Needs `wasm-rt.h` (through `wasmext_glue.h`) and, for the text of a trap of the runtime, `wasm-rt-impl.c`.

### `src/wasmext/c/wasmext_host.h`
```c
#define WASMEXT_HOOK_TRAP 0x10000      /* what a hook answers for a failure of its own */
typedef struct {
    const char *const *args; size_t nargs;   const char *const *env; size_t nenv;
    const char *const *dirs; size_t ndirs;   const int *dirs_readonly;
    int (*stdin_read)(void *user, uint8_t *buf, size_t cap, size_t *got);
    int (*stdout_write)(void *user, int fd, const uint8_t *buf, size_t n);
    int (*clock)(void *user, uint32_t id, uint64_t *ns);
    int (*random)(void *user, uint8_t *buf, size_t n);
    int (*sleep)(void *user, uint64_t ns);
    void *user;
    int (*sockets)(void *user, const char *ip, uint16_t port, uint32_t use);
    int sockets_all; int no_tcp, no_udp; int dns;
    int (*http)(void *user, const char *scheme, const char *authority);
    int http_all;
} wasmext_config;
typedef struct wasmext_host wasmext_host;      /* the state of fusedwasi first, the copies, the hooks, `message[160]`, `wait`, `lock` */
wasmext_host *wasmext_host_new(const wasmext_config *config, const char *program, int *error);
void wasmext_host_free(void *host);            /* fits wasmext_store_own */
```
Define `WASMEXT_HOST_P1` for a build for WASI 0.1. Needs the headers of fusedwasi (`fusedwasi/p2/wasi_p2_core.h`, `wasi_p2_io.h`, and
`fusedwasi/p1/wasi_p1_core.h` for 0.1) and the runtime of wasm2c. The network fields are always there. A 0.1 build ignores them.

### `src/wasmext/c/wasmext_rlock.h`
```c
typedef struct { WASMEXT_MUTEX_T mutex; wasmext_counter owner; long depth; } wasmext_rlock;
void wasmext_rlock_init(wasmext_rlock *l);     void wasmext_rlock_destroy(wasmext_rlock *l);
void wasmext_rlock_lock(wasmext_rlock *l);     void wasmext_rlock_unlock(wasmext_rlock *l);
long wasmext_rlock_depth(wasmext_rlock *l);    void wasmext_rlock_release_to(wasmext_rlock *l, long level);
#define WASMEXT_THREAD_ID()
```

## Semantics

### Calls and close
* A call into the store does `line = wasmext_store_enter(s)`, runs, then `wasmext_store_leave(s, line)`. `enter` returns -1 when the
  store is closed or closing. The line is chosen by the address of a thread-local variable (`% WASMEXT_STORE_LINES`), so threads
  rarely share a counter.
* The order is the proof. `enter` adds to its line, then reads `closing`. `close` raises `closing`, then reads the lines. Both are
  sequentially consistent, so either the call sees the flag or `close` sees the call.
* `wasmext_store_close`:
  1. Takes the lock. If `closed` is set, returns `WASMEXT_STORE_OK` (twice is fine).
  2. Raises `closing`, adds up the lines. If the sum is not 0 it lowers `closing` and returns `WASMEXT_STORE_BUSY` with nothing done.
     A call of this very thread counts, so a `close` from inside a call is refused. It never waits.
  3. Otherwise it takes the members and the arena, sets `closed`, and lets go of the lock.
  4. Outside the lock, in this order: `unlink` of every member, newest first; `close` of every member in the same order; `release` of
     the objects that members retained (the member operations are in S0004); then the arena, in the reverse order of owning.
* A call that races with a `close` that is then refused (BUSY) may fail with "closed" though the store stays open. It is the same
  as if it had come after the close was tried. A successful `close` means no call was in flight, and none starts after it.
* `wasmext_store_free` closes first and returns BUSY (nothing freed) if a call is in flight. Then it frees what was adopted, the
  registry and the mutex, and the store. Nothing may refer to the store, or to what it adopted, afterwards. `free(NULL)` is OK.
* The lock is taken only to add to the arena, to close, to set or read the host and the error text, and for the members. It is never
  held across a call outward. `release` functions run outside the lock.

### Arena
* `wasmext_store_own(s, object, release)`: the store owns `object` until it is closed. Then `release(object)` is called, in the reverse
  order of owning, once. On a refusal (`WASMEXT_STORE_CLOSED` or `WASMEXT_STORE_NOMEM`) the object is not owned and the caller frees
  it. After a failed `new` of an object nothing is left in the arena for it.
* `wasmext_store_adopt` / `wasmext_store_unadopt`: an object the store frees when it is freed, not when it is closed. It is for what
  must stay valid, closed, after the close (the wrapper of an instance). `unadopt` returns `WASMEXT_STORE_UNKNOWN` if the object was not adopted.

### Host slot and error text
* The store has one host. `wasmext_store_set_host` gives it once: `WASMEXT_STORE_BUSY` if there is one already (nothing changes);
  the refusals of `own` otherwise (then the host is not owned and the caller frees it). `release` runs at the close, as for any
  owned object. `lock` is the lock of the host and may be NULL.
* `wasmext_store_set_error` keeps the text of the last refusal, cut to `WASMEXT_STORE_ERROR_SIZE - 1` bytes. `wasmext_store_error`
  copies it into a buffer, cut to fit and always ended with a zero byte. A zero capacity does nothing.
* `wasmext_cell_set_once` sets a cell from NULL to a value once, for a process-wide cell written at a link and read by running code.
  It returns 1 if the cell was NULL (now the value) or was the value already, else 0.

### Errors
* `wasmext_error_describe(code)` gives `kind` and `text` as in the table above. A front end maps `kind` to its own exception.
* The extension and the wrapper keep their own tables until layers 2 and 3 take over (`docs/layers.md`, register of duplicates).

### The host of WASI
* `wasmext_host_new(config, program, &error)`: `config` may be NULL. `program` is the name of the module: the first argument when the
  configuration gives none. Returns NULL and sets `*error` (an errno) when it cannot make the host. `error` may be NULL.
* Checks, done here once. Each failure is `EINVAL`; running out of memory is `ENOMEM`:
  * `args` NULL: the arguments are `program`. `args` not NULL with `nargs` 0: no arguments. A NULL item is `EINVAL`.
  * `env` NULL with `nenv` not 0, or a NULL item, or an item with no `=`, or an empty NAME: `EINVAL`. The item is cut at the first
    `=`. An empty value (`NAME=`) is fine.
  * `dirs` NULL with `ndirs` not 0, or a NULL item, or an item that is not `host::guest` with both parts not empty: `EINVAL`.
  * `dirs_readonly` NULL, or a flag for each dir: 1 is a directory the program cannot change.
  * In a build with `WASMEXT_HOST_P1`, the descriptors of 0.1 are made at once, and the errno of a directory that cannot be opened
    is given as `*error`.
* Hooks. Every field may be 0. A hook answers 0, an errno of WASI, or `WASMEXT_HOOK_TRAP`. Without a hook the core uses the
  descriptors 0, 1 and 2 and the system.
  * `stdin_read`: no bytes read at all is the end of the input. At most 65536 bytes are asked for at a time.
  * `stdout_write`: `fd` is 1 or 2. An EPIPE of WASI (64) closes the stream. Any other errno fails the stream with "i/o error".
  * `clock`: `id` 0 realtime, 1 monotonic, 2 and 3 of the process and the thread.
  * `sleep`: without it the core sleeps in slices of 100 ms. With it the `wait` for the guests sleeps 1 ms at a time through it.
  * `sockets` and `http` (WASI 0.2): the network is refused unless it is allowed (as in Wasmtime). 1 allows, 0 refuses, a negative
    number is a failure and traps. `sockets_all` / `http_all` allow everything without asking. `no_tcp` / `no_udp` refuse the protocol
    whatever `sockets` says. `dns` allows name resolution. Unused by 0.1.
* A hook that answers `WASMEXT_HOOK_TRAP` (or a policy that is negative) traps the host: the message is kept in `host->message` and
  `wasm_rt_trap(WASMEXT_TRAP_HOST)` is called. The state of fusedwasi points to the host by `user`; the container-of is in one place
  (`wasmext_host_of_`).
* The errno mapping of a hook for 0.1 (`fusedwasi_p1_errno`) is used where `WASMEXT_HOST_P1` is defined, and `EIO` otherwise.
* The host brings a `wasmext_rlock`, taken around each call into fusedwasi from an instance: the state has no lock of its own, by
  design. The lock is recursive because a hook may call the module back. `wasmext_rlock_release_to` lets go of what a thread took
  above a level, because a trap leaves a function of fusedwasi by a long jump that skips its unlock.
* `wasmext_host_free(host)` lets go of the state of fusedwasi, the copies and the lock. NULL is fine. It fits
  `wasmext_store_own(store, host, wasmext_host_free)` and `wasmext_store_set_host`.
* One `wasmext_host` serves 0.1 and 0.2 (the alternative of two hosts was not chosen). The 0.2 network policies stay in it.

## Test plan
Run from the repository root. All pass as of 2026-10-30.

```
uv run pytest tests/test_store_core.py -q
```
Result seen: `9 passed in 12.71s` (the ThreadSanitizer cases run on Linux; they are skipped where there is no sanitizer).

The tests, all plain C built by `tests/c_build.py` (`compile_c`) with `-I src/wasmext/c`, no wasm module and no Python in the program.
Each prints `ok` and exits 0:
1. `test_the_store`: `tests/c/test_store.c`. Lifecycle (`close` twice); the arena frees in the reverse order, once, and nothing before
   the close; `own` after the close is refused and not owned; a `close` while a call is in flight (including from inside a call)
   is BUSY and leaves the store open; after the close `enter` is -1; the error text is cut to fit and ended; the host slot is
   given once and released once; threads call `enter`/`leave` while another closes, and after a successful close no call is inside.
2. `test_the_store_under_threadsanitizer` (Linux, `-fsanitize=thread`, `ROUNDS=4`): the same program, TSan clean.
3. `test_the_table_of_errors`: `tests/c/test_errors.c` with `wasm-rt-impl.c`, `wasm-rt-mem-impl.c`, `wasm-rt-exceptions-impl.c` of the
   runtime of wasm2c. Every code has a kind and a text.
4. `test_the_host_of_wasi[wasi-0.2]` and `[wasi-0.1]`: `tests/c/test_host.c` over the real headers of fusedwasi and the runtime of wasm2c
   (`-DWASMEXT_HOST_P1` for 0.1). Defaults; the configuration is copied (arguments, environment cut at the first `=`, `dirs` as
   `host::guest`, read-only flags); a bad item gives `EINVAL`; the hooks are called (a write reaches `stdout_write`, a read reaches
   `stdin_read`, the clock and random reach theirs, a hook that fails sets the message and traps); the host is freed once; the same
   host is freed by the arena at `close`.
5. `test_the_recursive_lock` and `test_the_recursive_lock_under_threadsanitizer`: `tests/c/test_rlock.c` (recursion, release to a level, exclusion).
6. `test_the_registry_of_owners` and `test_the_registry_under_sanitizers` (`tests/c/test_registry.c`) belong to S0004. They run in the same file.

The same suite is run in CI with `CC=cc` and `CC=clang`; the ASan/UBSan runs set `WASMEXT_TEST_CFLAGS` (see `tests/conftest.py`). The mutation
"a copy is not freed" in the host is caught by the leak check (LeakSanitizer).

When `src/wasmext/c/` changes: update the fingerprint (`uv run pytest tests/test_abi.py`) and `uv run python -m tests.abi_surface --update`.

## Alternatives considered
* **`close` waits for the calls in flight.** Cost: a `close` from inside a call waits for itself (a deadlock). Not chosen: `close`
  refuses with `WASMEXT_STORE_BUSY` and never waits (the owner's open question is answered).
* **One shared counter of active calls.** Cost: a cache line fought over by every call. Not chosen: the counter is split by thread
  into `WASMEXT_STORE_LINES` lines with the flag `closing`. The cost of the sum and of choosing a line is not measured yet;
  `docs/experiments/context_bench/` is the place to measure it before the choice is final.
* **A separate `.c` file or a switch for the store.** Not chosen: header code compiled into each artifact, `static inline`, like
  `wasmext_glue.h`.
* **The state of fusedwasi allocated by the host that makes the store.** Not chosen: it is allocated inside the store's reach, as
  before (the owner's proposal accepted).
* **The host as fields of the store.** Not chosen: the host is a separate object owned through the arena
  (`wasmext_store_own(store, host, wasmext_host_free)`). The store module stays free of fusedwasi and wasm-rt and the composition
  stays clean.
* **Keep the lenient checks of the old generated configuration.** Not chosen (the owner, 2026-10-29): no old behaviour to keep.
* **Patch the old generated store and the Python hooks on the side.** Not chosen: the old shape stays until the step that owns it
  takes over (rule: no side patches).
* **Lay out the record `wasmext_store` (size, `abi`, `floor`, `runtime`, `families`, `retain`/`release`) now and fill it as far as it exists.**
  Not chosen: a field is not added before the step that tests it. It waits for step 8.

## Open questions
* The cost of the split counter (the sum at `close`, the choice of a line) is not measured. Measure it in `docs/experiments/context_bench/`.
* The Python hooks (`wasi_python.h`, `wasi2_python.h`) and the old generated store still exist. Their removal is in layers 2 and 3.
* The shared store across separately built modules (the versioned record `wasmext_store`, `attach`) is not built (step 8).

## Changes
* 2026-10-28: part 2a built: `wasmext_store.h`, `wasmext_errors.h`, `tests/c/test_store.c`, `tests/c/test_errors.c`,
  `tests/test_store_core.py`. The arena, the counter of active calls with the flag, the lock, the text of an error, `close` and `free`,
  and the table of errors. `close` returns BUSY, never waits.
* 2026-10-28: item 5 of the design (the record `wasmext_store`) was deferred to step 8: a field is not added before the step that
  tests it. The design for 2a was also read in the code of this date.
* 2026-10-29: part 2b design written (the host of WASI in the static core), read in the code of this date, then built: `wasmext_host.h`
  (`wasmext_config`, `wasmext_host_new`, `wasmext_host_free`, `WASMEXT_HOST_P1` for 0.1) and `tests/c/test_host.c`, built in both modes
  (0.2 and 0.1), under ASan with LeakSanitizer. The mutation "a copy is not freed" is caught.
* 2026-10-29: what differs from the design of 2b. The test showed what the generated code did and the design note did not say:
  the checks of the configuration were lenient. The owner asked to fix that before going on. An environment item with no `=` or no
  NAME, a directory with no host path, a NULL array with a count or a NULL item are now `EINVAL`. A `dirs` item must be `host::guest`
  with both parts (the owner, the same day: nobody outside the project passes a configuration, and every Python front end writes both
  parts). An empty value (`NAME=`) is fine. The old generated copy in `_shared.py` and the store of the glue stay until layers 2 and 3.
* 2026-10-30: this document written as S0002 from `docs/step2_store.md`. Interface and Semantics describe the code of this date.
  `wasmext_rlock.h` is added to the interface: it was built after the old document (the lock of the host).
