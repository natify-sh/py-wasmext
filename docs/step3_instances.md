# Step 3 of layer 1: instances (a design, for review)

Status: **written 2026-10-29; nothing of it is built.** Step 3 of the order in [layers.md](layers.md). Read in the code of 2026-10-29. Builds on step 1 (the model and the descriptor) and step 2 (the store, the errors, the host).

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
