# Step 2 of layer 1: the store (a design, for review)

Status: **part 2b built 2026-10-29** (`wasmext_host.h`, `tests/c/test_host.c`; see the end of this page; the configuration is not validated beyond NULL arrays with a count, as before: the move keeps the behaviour). **Part 2a built 2026-10-28** (`wasmext_store.h`, `wasmext_errors.h`, `tests/c/test_store.c`, `tests/c/test_errors.c`, `tests/test_store_core.py`): the arena, the counter of active calls with the flag, the lock, the text of an error, `close`/`free`, and the table of errors. **Part 2b is not built:** `wasmext_config` and the state of the host of WASI (fusedwasi) inside the store, which is moved out of the generated C of `_shared.py` and `_gen.py` (the hooks of streams, clocks, random and the network policies are generated there with the names of the module). Item 5 (the record `wasmext_store`) waits for step 8: a field is not added before the step that tests it. `close` returns BUSY, never waits. Step 2 of the order in [layers.md](layers.md). It rests on what the owner already decided in [context_concept.md](context_concept.md) (the arena, the hard close, the counter of active calls, the lock; "context" there is the store) and on [WASI_TARGET_PLAN.md](WASI_TARGET_PLAN.md). Facts are read in the code of 2026-10-28.

## What there is

- The store is **generated per module, as C text inside Python strings** in `_shared.py` (`<last>_store_t`, `<last>_store_new`, `<last>_store_close`, `<last>_store_closed`, the copying of the configuration: arguments, environment, `dirs`, streams, clocks, sockets). Every module carries its own copy of this logic; the extension and the wrapper add their own on top.
- The only static piece is the code of the trap (`WASMEXT_TRAP_CLOSED`) and the stack of traps in `wasmext_glue.h`.

So the store is the first thing that moves from the generator into the static core.

## What step 2 builds (static C, `src/wasmext/c/`, no Python, no module in it)

1. **`wasmext_config`**: one plain struct for the host of a store (arguments, environment, `dirs`, read-only flags, streams, clocks, sockets, http, DNS, `user`), with the checks (a bad `dirs` item, a missing `=`) done once in the core. It replaces `<last>_config` and the copying code in `_shared.py`.
2. **`wasmext_store`**: made by `wasmext_store_new(config, &error)`; it owns the state of the host (fusedwasi, `host` of the build), an **arena** of what it owns (`own(object, free_fn)`, freed in the reverse order at the close), an **error cell** (the text of the last refusal), the **lock** (`WASMEXT_LOCK`, empty where there are no threads), and the **counter of active calls with the `closing` flag** (split by thread, as in "Closing" of the concept note).
3. **`wasmext_store_close`**: raises the flag, adds up the counters, refuses when a call is in flight (the owner's open question is answered here: **refuse** with a code, never wait, so a `close` from inside a call cannot wait for itself), then frees the arena in order. Twice is 0. After the close every entry that takes the store fails with a code (`WASMEXT_TRAP_CLOSED` for a call), never a crash.
4. **Codes and descriptions of errors** (`wasmext_error_describe(code)` -> kind, text, whether it is an exception of WebAssembly, exit value, signal): one table in one place; the extension and the wrapper keep several now.
5. **The header of the record `wasmext_store`** (size, `abi`, `floor`, `runtime`, `families`, `retain`/`release`...) is laid out now but filled only to the part that exists; `attach` and `bind_import` come in step 8. A field is not added before the step that tests it.

Not in this step: instances (step 3), owners (4), the registry, tags, anything that needs a module.

## Where the code lives, and how it reaches an artifact

The core is **header code compiled into each artifact** (each built module has its own copy, as the runtime of wasm2c does), written as `static inline` functions in a header, the way `wasmext_glue.h` is: no switch, no separate `.c`. Layer 2 later puts the module prefix on the names (`<last>_store_new` calls `wasmext_store_new`) in the generated file.

## The tests (C first)

`tests/c/test_store.c`, a plain C program, no wasm and no Python, run by pytest, under ASan/UBSan and on the matrix (and ThreadSanitizer on Linux):

- new with a full, an empty and a bad config; every bad item gives its code and text;
- the arena frees in the reverse order, once, also after a failed `new`;
- `close` twice; `close` while a call is in flight (a thread inside `enter`/`leave`) is refused; `close` from inside a call is refused; after the close `enter` fails;
- the proof of the counter: many threads call `enter`/`leave` while another closes; the flag and the sum never let a call run on a closed store (TSan clean);
- the error table: every code has a text and a kind.

The old shape is not patched; the generated store of `_shared.py` and the wrappers go in the steps that own them (layer 2 and 3), so the tests of the old shape keep running until then.

## Open (for the owner)

1. **Free-threaded:** the split counter is built now with C11 atomics (a requirement of layer 1, from the owner), the plain form where there is one thread. The cost of the sum and of choosing a line is not measured; `docs/experiments/context_bench/` is the place to measure it before the choice is final.
2. Is the state of fusedwasi (`fusedwasi_p2_state`, and p1 over it) allocated inside the store as now, or by the host that makes the store? I propose inside, as now.

## Part 2b: the host of WASI in the static core (a design, for review; read 2026-10-29)

**What there is.** The host of WASI is written three times over the same state of fusedwasi (`fusedwasi_p2_state`, with its callbacks for streams, clocks, random bytes, sleep and the network policies):

- the shared library: `_shared.py` generates C (`_p2_helpers`, `_p2_new`, `api_p2_release`): the configuration struct `<last>_config`, the copy of arguments, environment and `dirs`, the hooks over the callbacks of the configuration, the release. All of it carries the module prefix, and none of it needs the module;
- the extension: `wasi_python.h` (548 lines) and `wasi2_python.h` (356 lines) do the same with Python callables; the glue `<name>_glue.h` has a store struct of its own (`wasi`, `wasi_py`, `p2_message`, `wait`, `closed`...);
- the executable: through the shared library's store.

`<last>_config` is the same in every module (the network fields exist only in a 0.2 build, which is the only difference). What is truly per module is small: the **guest of an instance** (`wasi_guest_init` binds the memory of that instance by its mangled name), and the callbacks that need the instance (`trap`, `exit`, `signal`, `realloc`). That is step 3, not this one.

**What 2b builds** (static C, `src/wasmext/c/wasmext_host.h`, in the manner of `wasmext_glue.h`; needs the headers of fusedwasi and `wasm-rt.h`, not a module):

1. **`wasmext_config`**: today's `<last>_config`, one struct for all modules; the network fields are always there (a 0.1 build ignores them).
2. **`wasmext_host`**: an object made by `wasmext_host_new(config, &error)`: the fusedwasi state, the copies of arguments, environment and preopens, the three standard streams, the hooks (stdin, stdout and stderr, clock, random, sleep, sockets, http), the message of a trap of the host (`p2_message`), the `wait`. The checks of the configuration (a bad `dirs` item, a missing `=`) are done here, once. `wasmext_host_free` releases it.
3. **Owned by the store through the arena**: `wasmext_store_own(store, host, wasmext_host_free)`. The store module stays free of fusedwasi and wasm-rt; the host is an object the store owns, as any other. (This is the "inside the store" of the decision, with the composition kept clean.)
4. **A hook that fails traps the host** the way the generated code does (`wasm_rt_trap(WASMEXT_TRAP_HOST)` after keeping the message in the host); the container-of from the state to the host is `offsetof` in one place.
5. The errno mapping of a hook for 0.1 (`fusedwasi_p1_errno`) is used where the p1 header is included, and `EIO` otherwise, as now.

**Not in 2b:** the guest of an instance and its callbacks (step 3); the Python hooks (`wasi_python.h`, `wasi2_python.h`): they become a front end that gives the static host plain C hooks whose `user` is the Python callable, so the logic of streams and policies is written once. That change is made in the extension's own step, not patched here.

**Tests (C first)**, `tests/c/test_host.c`, over the real headers of fusedwasi and the runtime of wasm2c (no module, no Python): the configuration is copied (arguments, environment cut at the first `=`, `dirs` as `host::guest`, read-only flags); a bad item gives its errno; the hooks are called (a write to a stream reaches `stdout_write`, a read reaches `stdin_read`, a clock and random reach theirs, a hook that fails sets the message); the host is freed once, under ASan with no leak; the same host is freed by the arena at `close`.

**Open (for the owner):**
1. The host as a separate object owned through the arena (above), or as fields of the store? I propose the object.
2. A 0.1-only build and a 0.2 build share one `wasmext_host`: the 0.2 network policies stay in it and are simply unused by 0.1. Any objection?

**Built (2026-10-29).** `wasmext_host.h` (static C, the configuration and the host of fusedwasi; `wasmext_host_new/free`, `WASMEXT_HOST_P1` for 0.1) and `tests/c/test_host.c`, built in both modes (0.2 and 0.1), under ASan with LeakSanitizer; the mutation 'a copy is not freed' is caught. The test shows what the generated code did and the design note did not say: the checks of the configuration are lenient (`NAME` without `=` is a name with an empty value, a `dirs` item without `::` has the guest name `/`); only an array that is NULL with a count, or a NULL item, is `EINVAL`, new in the move. The old generated copy in `_shared.py` and the store of the glue stay until layers 2 and 3 take them over (rule: no side patches).
