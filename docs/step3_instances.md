# Step 3 of layer 1: instances (a design, for review)

Status: **3a built 2026-10-29** (`wasmext_instance.h`, `_binding.py`, `tests/c/test_instance*.c`, `tests/test_instance_core.py`: function exports, `instantiate` with a trap in the start function, the generic `call` for i32/i64/f32/f64/v128, several results, no result, the closed store, threads; under ASan/UBSan/TSan; ThreadSanitizer found a real race on `status`, now atomic). **3b1 built 2026-10-29** (function imports by index of the descriptor: the slot of an import, the uniform host function and the typed fast path, a failing host, a trap of another instance passed through, reentrant calls, `LINK_ERROR` with the name in the text of the store, bind after `instantiate` refused; `tests/c/test_imports.c`; four mutations are caught). **3b2a built 2026-10-29** (WASI 0.1 imports answered by the host: the host slot of the store, the guest in the block, the typed functions under the recursive lock of the host with `release_to` after a trap, `wasmext_instance_wasi_end`, the mapping in `ImportFact`; `tests/c/test_wasi_imports.c`, `tests/c/test_rlock.c`, the guard `tests/test_model_wasi_mapping.py`; under TSan; three mutations caught). 3b2b (WASI 0.2), 3c and 3d are not built; the binding refuses a module with a memory/table/global/tag import, a WASI import answered by the core, or a reference type in an import, each with the step that carries it. The owner accepted the four points below on 2026-10-29. Step 3 of the order in [layers.md](layers.md). Read in the code of 2026-10-29. Builds on step 1 (the model and the descriptor) and step 2 (the store, the errors, the host).

## What there is

An instance is written three times, each for its front end, over the same wasm2c module:

- the **glue** `<name>_glue.h` (generated, per module, from `_gen.py`): the structure of the instance, the typed functions `result f(void *instance, parameters..., int *trapped)` for every export, the host functions an import calls (`fn[slot]`, `user[slot]` in a structure per import module), the trampolines that turn a `trapped` into a `wasm_rt_trap`, the accessors of memories, tables and globals;
- the **library** (`<name>_shared.c`, `_shared.py`): the C API with a different shape for every module (`<name>_set_import<k>`, `<name>_link_*`, `<name>_call<i>`, `<name>_memory_<n>_pin`...);
- the **front ends** (`<name>_py.c`, `_ctypes_gen.py`), which each re-implement the rules (which import is set, the status of the last call, the pins).

The shared record of an export, `wasmext_export` in `wasmext_glue.h`, already exists and is versioned (`abi`, `floor`, `size`): it is what an instance gives another instance, so it stays.

## The cut

An instance is **a static, module-independent core plus a generated binding of the module to it**. The core knows nothing of the module; the binding is the part that has to name the symbols that `wasm2c` made for this module, so it is generated, from the model of step 1.

**Static (`src/wasmext/c/wasmext_instance.h`):**

1. `wasmext_val`: the tagged value, `{ type; union { i32, i64, f32, f64, v128[16], ref } }`, passed by pointer or in arrays only (the rule of [layers.md](layers.md)).
2. `wasmext_instance`: made in a store (step 2) by `wasmext_instance_new(store, binding, &error)`; it enters the store (`enter`/`leave`) for every call, and a call into a closed store answers `WASMEXT_TRAP_CLOSED`. It holds: the module's own structure (the memory of the wasm2c instance), the state of each import (set or not), the status of the last call, the pins of each memory.
3. The operations, all returning a code of step 2: `bind_import(i, kind, ...)` by index (a host function, or a record of an export of another instance, for a function, a memory, a global), `instantiate` (runs the start function; a trap in it is a code; a missing import is `LINK_ERROR`), `export_find(name)` / `export_at(i)`, `call(i, args[], results[])`, `global_get/set`, `memory` (base, size, grow, `pin`/`unpin`), `export_record(i, &record)` (fills the existing `wasmext_export`), `free`.
4. The rule of `pin`, moved as it is: while pinned, `memory.grow` answers -1 where the runtime would move the memory (the maximum is held at the current size); pins count.
5. The host-function shape: **one callback for every import**, `int host_fn(void *user, const wasmext_val *args, wasmext_val *results)`; 0 is success, `WASMEXT_HOOK_TRAP`-style codes for a failure the host keeps. The **typed fast path** (a host function written as `result f(void *user, parameters..., int *trapped)`) stays and is chosen per import when the front end has one (the benchmark of `context_concept.md` decides how much it matters; not measured).

**Generated (`<name>_binding.c`, from the model; no rule is decided in it):**

- the `wasmext_binding` of the module: the descriptor (step 1), `sizeof` the instance, `instantiate`/`free` over `wasm2c`'s `wasm2c_<p>_instantiate/free` with the catching of a trap, tables by export index (the address of a memory, a global, a table; the typed function);
- **one adapter for each distinct signature**: `args[]` -> the typed call -> `results[]` for an export, and the other way round for a host import (`results[]` <- uniform callback). A module with 40 exports of 6 signatures has 6 adapters. This is the only per-signature code, and it is what a language with no generic call needs; a `libffi` is not taken (it is not on every target of the project).
- the functions that `wasm2c` declares for the imports (`w2c_<module>_<name>`), which call `fn[slot](user[slot], ...)` and turn `trapped` into a trap, as the glue does now.

## What is not in step 3

Tables, `funcref` and `Function` (step 5), `externref` (6), tags and exceptions across instances (7), the shared store across artifacts (8), the owners (4: an owner handle exists here only as the `owner` of the export record, an opaque pointer, as now), threads. No existing generator is changed (rule of [layers.md](layers.md)); the new binding is its own emitter beside the old ones.

## The order inside the step, each a commit with its C tests

- **3a**: the binding emitter for a module without imports: function exports, `instantiate` with a trap in the start function, `call(i, args, results)` for the signatures of the corpus (all value types, multi-value, `v128`), the status of a trap and the code of the call.
- **3b**: imports by index with the uniform callback and the typed fast path; a host function that fails (trap of the host) and the message kept; WASI imports answered by the host of step 2 when the module's host says so.
- **3c**: memories (base, size, grow, `pin`) and globals (get, set, mutable/immutable, `v128`, 64-bit).
- **3d**: `export_record` and `bind_import` from the record of another instance (a function, a memory, a global), two instances of different modules linked in C, in one store.

## The tests (C first)

The C tests need a real module, so pytest builds one for each: `wat2wasm` -> `wasm2c` -> the binding of the emitter -> the C test and the static core, with the toolchain of the project (`conftest.py` already builds extensions this way); the build is cached for the run. The C test is a plain program (no Python): it builds a store and an instance, calls, reads memory and globals, links two instances, closes the store, and the runs are under ASan/UBSan/TSan as before. As in step 1, a second reader checks the emitter: the descriptor inside the binding must equal the model's dump.

## Open (for the owner)

1. The binding is **generated code** (adapters for signatures, the functions of the imports), not only data. I see no way round it without a `libffi`. Accepted?
2. The uniform callback and the generic `call` pass `v128` as 16 bytes in `wasmext_val`. Accepted?
3. Where the memory of an instance is: today the front ends read it through accessors in the glue. In the new core the view is `{ base, size }` taken under the store's `enter`, valid until the next call that can grow it (or while pinned). Accepted?
4. The order 3a-3d, one commit each, CI between them?

## 3b2: the imports that the host of WASI answers (a design, for review; read 2026-10-29)

**What there is.** The existing glue already does this with the machinery that 3b1 built: for each WASI import it writes a **typed** function `result <last>_wasi_import<k>(void *user, parameters..., int *trapped)` that calls fusedwasi on the *guest of the instance* (`fusedwasi_p1_<name>(&self->guest, args)` for 0.1, with `unstable_` for the few calls the first snapshot has of its own; `<cname>(&self->guest, [0,] args)` for 0.2), and puts it in the slot with `user = self`. So a WASI import is a typed host function in a slot, and 3b2 is: generate those functions and the guest, and fill the slots.

**What 3b2 builds:**

1. **The host slot of the store.** `wasmext_store_set_host(store, host, release)`: once (a second call is refused), the store owns the host through its arena, `wasmext_store_get_host(store)` returns the opaque pointer. The store stays free of fusedwasi (decided: option A). `Store()` in a front end is then the two calls in one.
2. **The guest in the block.** The block of an instance (3b1) gets `fusedwasi_p2_guest guest` and `signalled`. `instantiate` of the binding takes the host: `instantiate(void *block, void *host)`; for a module with core imports it makes the guest (`fusedwasi_p2_guest_init(&guest, &host->wasi)`, `user = block`, memory 0 bound by the pointers `&memory->data, &memory->size` of wasm2c, read at each access, so a memory that grows needs nothing), sets the hooks, and fills the slots of the core imports with the typed functions. A store with no host and a module with core imports: `instantiate` answers `LINK_ERROR` with "the store has no host for WASI" (no crash).
3. **The hooks of the guest**, as the glue has them: `trap` (the message goes to `host->message`, then the host trap), `exit` (`exited`, `exit_code`, the host trap), `signal` for 0.1 (`wasmext_signal_ends`: a signal that ends a process records the number and traps; the others answer success), `realloc` for 0.2 (the `cabi_realloc` that the module exports; a module of 0.2 without it is a build error), `wait` (from the host).
4. **How a program ends.** A call that ended the WASI program answers `WASMEXT_TRAP_HOST`; `wasmext_instance_wasi_end(i, &value)` says how: `WASMEXT_END_NONE`, `EXIT` (the code) or `SIGNAL` (the number). The end is what the call leaves, as in Wasmtime: the binding clears it before the next call (`call_begin`), the instance stays usable, and a neighbour in the same store is not touched.
5. **The mapping import -> fusedwasi function in the model.** Today it is in `_gen.py` (`_P2_FUNCS`, `_p2_cname`, `_WASI_SIGNATURES`, `_WASI_UNSTABLE_OWN`) and decided in several places. `ImportFact` gets the C function that answers a core import (and whether it takes the component index), found once in `build_model`; an import that fusedwasi does not have, or whose signature differs, is a `GenError` at build time naming both signatures, as now.
6. **Headers.** The binding of a module with core imports includes the headers of fusedwasi for exactly its calls (as `Glue.wasi_headers` lists now); `generate_binding` has a companion that lists them, so a build copies them beside the binding.

**What this gives.** Two instances made in one store share the one host: the same arguments, environment, preopens, descriptors and handles, the same hooks. A module built with `host = wasm32-wasip1` and one with `wasm32-wasip2` in one store share the one state (0.1 is over 0.2 in it). A module with `host = wasm32` has no core imports and is untouched.

**Not in 3b2:** the Python hooks of `wasi_python.h` (they become plain C hooks with a `user` in the front end's own step); the executable's `_start` driver (the exe step); more than one memory.

**The tests (C first).** Real modules from `.wat`: for 0.1, `proc_exit`, `fd_write` to the stdout hook (iovecs in memory), `args_sizes_get`/`args_get`, `environ_*`, `clock_time_get`, `random_get`, `proc_raise` (an ending and a non-ending signal), a call after the program ended; for 0.2 the calls with flat types (`wasi:cli/exit`, `wasi:clocks/monotonic-clock now`, `wasi:random/random get-random-u64`); two instances of one module and one of another in one store (the same stdout hook receives all; the same arguments); a store with no host; a closed store; an unknown function and a wrong signature at build time; the same under ASan/UBSan. The streams, files and sockets of 0.2 are tested by fusedwasi itself; here only that the binding reaches them.

**Open (for the owner):**

1. **Threads.** The state of fusedwasi has no lock (the plan says so), and one host is shared by all the instances of a store, so two threads calling WASI at the same time in one store would race. Wasmtime avoids it because a call takes `&mut Store`. Options: (a) one lock in the host, taken around each call into fusedwasi (a WASI call is a system call anyway; recursive, because a hook may call back into the module); (b) say that a store with WASI is for one thread at a time, as Wasmtime's. I propose (a), since free-threaded is a requirement of layer 1.
2. **Order.** 3b2a for WASI 0.1 and then 3b2b for 0.2 (each its own commit and CI), or both at once? I propose two commits: 0.2 adds the canonical-ABI `realloc` and the harder tests.
3. The mapping tables move into the model (point 5), and `_gen.py` keeps its own copy until its step takes over (rule: no side patches). Accepted?
