# Step 5 of layer 1: tables, `funcref` and `Function` (a design, for review)

Status: **written 2026-10-29; nothing of it is built.** Step 5 of the order in [layers.md](layers.md), on top of the steps 3 (instances) and 4 (the registry of owners). It finishes what [TABLES_PLAN.md](TABLES_PLAN.md) and the refusals of the old glue left open: a `funcref` in an import and as a parameter, `Function`, host functions in tables.

## What there is

- **wasm2c.** A table is `{ wasm_rt_funcref_t *data; uint32_t max_size, size; }`; an element is `{ func_type, func, func_tailcallee, module_instance }`. An imported table is a pointer the module reads (`w2c_<module>_<name>(struct w2c_<module> *)` gives it), an exported one is reached by `w2c_<p>_<name>(w2c_<p> *)`. `call_indirect` compares the type of the element with the expected one by the pointer of the type, and by a 256-bit hash if the pointers differ, so an element made by another module of the same type is accepted.
- **The static glue already has** (`wasmext_glue.h`) the operations on a table that no module owns: `wasmext_table_new/free/grow/export` and `wasmext_function_export`. They are reused.
- **The old glue** (`_gen.py`, `_shared.py`, `_ctypes_gen.py`) refuses: a `funcref` in an import, a `Function` called with a `funcref` parameter, `externref`, a host function as a member of a table. Who keeps whom alive is the chains of step 4's problem statement.
- **Step 3 refuses** a table import and an export record of a table ("step 5"); a `funcref` in a signature ("step 5 or 6").

## The one hard fact: a trap in a function that comes out of another runtime

Each artifact has **its own copy of the runtime** of wasm2c and so its own `g_wasm_rt_jmp_buf`. A function of another artifact in a shared table traps by a long jump to *its* buffer, which was not set for this call ([TABLES_PLAN.md](TABLES_PLAN.md), the spike). Inside **one artifact** (one copy of the runtime) there is no such problem: the trap goes to the buffer of the call that is running, the caller's, as WebAssembly says. Since [step 4](step4_owners.md) instances are linked inside one store, and a store is made by one artifact, **step 5 works inside one artifact**. A store joined by modules of another artifact (step 8) needs the trap state to be shared (the stack of entries `wasmext_traps` that the old glue has for it, or a trampoline in the exporter); that is a decision of step 8 and it is written there, not here.

## What step 5 builds (static C `wasmext_table.h` and in the binding)

1. **`wasmext_funcref`**: the public value of a function that is not an instance's export any more: a copy of the four words of `wasm_rt_funcref_t` and the handle of its owner (found in the registry of step 4 by `module_instance`, so a funcref of another store is refused with `UNKNOWN`/`WRONG`). A `wasmext_val` of type 0x70 carries a pointer to it; it is valid for the call it is passed in.
2. **Tables.** (a) A table as a member of the store: `table_new(store, initial, maximum)` (a member under the registry, freed at the close), `size`, `maximum`, `grow`, `get(i)` (the `wasmext_funcref`, or empty), `set(i, funcref)` (the owner of the funcref must be a member of this store, else refused; the type is checked by `call_indirect` when it is called, as in WebAssembly). (b) An instance's exported table: its record (`WASMEXT_TABLE`, `type` = `sizeof(wasm_rt_funcref_table_t)`, the store), the same operations on it. (c) A table import: `bind_export` takes the record (kind, size, limits as for a memory), the binding gives wasm2c the pointer.
3. **The functions of an instance as elements.** `export_funcref(i, export_index, &funcref)`: what `Table.set` puts in a slot; the binding fills `func_type` through `wasm2c_<p>_get_func_type(...)` and `func`, as the old `_gen.py` does for `exp_ref`.
4. **The unlink at the close** (the hook of step 4): an instance that put functions of its own into a table it imported takes them out (the old `scrub_tables`), so that the exporter of the table does not hold a function of a closed instance.
5. **`Function`: calling a funcref.** `call_ref(funcref, args[], results[])`: the core finds the adapter by the type of the element. The binding gives a table of the types the module declares (as the old `_ref_types`), each with its adapter; an element of a type that no module of the artifact declares cannot be called by the host (it can still be called by wasm through `call_indirect`).
6. **`funcref` in a signature.** The uniform shape of step 3 gets the type 0x70: an argument or a result is a `wasmext_funcref` by pointer. An exported function with a `funcref` parameter keeps what it was given alive (the store holds every member, so nothing is added; the checks are that the funcref is of a member of this store).
7. **Host functions as members** (the hardest piece, last): a `HostFunction` record `{ callable, type }` is registered in the store under its own pointer (the registry takes any key); the `func` of its funcref is a **trampoline for the type**, made by the binding for each type the module declares (a type it does not declare cannot be made: the AOT rule, as in the old glue), which calls the uniform host function (step 3b) with `module_instance` = the record. An exception of the host function is a trap, so a module that has them needs the entry of step 3d's shim; the failure is reported as for an import.

## The order inside the step, each a commit with C tests

- **5a:** tables and elements: items 2, 3, 4 (a table of the store; export, import and sharing of a table between two instances; `set` of an element made by another instance and a `call_indirect` through it; the unlink at the close; the refusal of a funcref of another store).
- **5b:** items 5 and 6: `call_ref`, `funcref` in a signature of an export and of an import.
- **5c:** item 7: host functions as members of a table.

## The tests (C first)

Real modules built from `.wat`: a table exported by one and imported by another; `elem` segments of the importer that fill the table of the exporter; a standalone table filled with elements of two instances, called through `call_indirect` of a third; a function of the wrong type is a trap in the caller; `grow` seen by both; an element of an instance whose store is closed; a funcref of another store (`WRONG`/`UNKNOWN`); the unlink; `call_ref` for every value type and several results; `funcref` as parameter and result; a host function in a table called from wasm; a trap inside a function that comes through a table, with both instances usable after it; the same under ASan/UBSan and, where there are threads, TSan; mutations of the owner check, of the unlink and of the type check.

## Open (for the owner)

1. **Inside one artifact first** (the section above); the trap state across artifacts is decided in step 8. Accepted?
2. The host function as a member of a table (item 7) keeps the old AOT rule: only the types the module declares. Accepted?
3. `call_ref` by the host works only for a type that some module of the artifact declares. Accepted?
4. The order 5a, 5b, 5c, one commit each, CI between them?
