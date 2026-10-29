# Step 4 of layer 1: the registry of owners (a design, for review)

Status: **written 2026-10-29; nothing of it is built.** Step 4 of the order in [layers.md](layers.md). It replaces the Python-capsule design of [owners_registry.md](owners_registry.md) (kept for its reading of the problem). The owner's decisions of 2026-10-29 are applied: the handle is a number with a generation, the registry lives in the store, the store holds its members strongly until it is closed (as Wasmtime's does), and an object of another store is a soft refusal in C (an exception in Python), not a panic.

## The problem

A `funcref` of wasm2c is `{ func_type, func, func_tailcallee, module_instance }`: the code and a pointer to the instance it belongs to (for us, the block of [step 3](step3_instances.md): `wasmext_instance.module`). **Nothing says who keeps that instance alive.** If a function of A is in a table that B uses and A is freed, B calls into freed memory. Today it is a chain of keep-alives written by hand in each front end (`writers`, `refs`, and `Table.get` that finds the owner by scanning the exports of the instances that use the table), which cannot hold a function that no instance made (a host function), and is written twice (extension and wrapper).

## What step 4 builds (static C, `src/wasmext/c/wasmext_registry.h`; the registry is a member of the store)

1. **The handle `wasmext_owner`**: a `uint64_t`, the index of a slot in the high word and its **generation** in the low word. 0 is none. A handle of a slot that was freed and reused has another generation, so a stale handle is *recognised*, not taken for the new member (the case of an instance made at the address of one that was freed).
2. **The registry**: slots `{ key, object, ops, generation }`, a free list, a hash from `key` (the `module_instance` pointer, or the pointer of a record of the host) to the slot, under the lock of the store. It has a **version and a size** at its head, so that the record of the store in step 8 can carry it without a second layout.
3. **The operations** (all return a code of step 2, none aborts):
   - `register(store, key, object, ops, &owner)`: the store keeps `object` strongly (`ops->retain(object)` once); `key` must be new.
   - `find(store, key, &owner)`: by the pointer of a `funcref`; `WASMEXT_ERR_UNKNOWN_OWNER` if the store has no such member, and **`WASMEXT_ERR_WRONG_STORE` when the pointer is a member of another store** (a registry lookup that fails is a refusal with the reason in the text of the store; the front end raises its exception).
   - `object(store, owner)`: the object, or NULL for a stale or foreign handle.
   - `each(store, visit, arg)`: walks the members, for a front end that must show them to a cyclic collector (`tp_traverse` of CPython).
4. **Who registers.** The core registers an instance itself when it is instantiated (`key` = `module`, `object` = the `wasmext_instance`), so that a C host gets the registry without a line of code. A front end that wants its own object kept (the Python `Instance`) replaces the object with `set_object(store, owner, object, ops)`.
5. **Lifetime, as Wasmtime's `Store`.** A member lives until the store is closed. `wasmext_instance_free` of a registered instance is **refused** (`WASMEXT_STORE_BUSY`); the store frees the instances at the close. That is a change of the tests of step 3, which free their instances by hand: they will let the store do it (an instance that was never instantiated is not registered and can still be freed).
6. **The close.** (a) A pass **unlink** in reverse order of registration: an importer lets go of the tables, memories and globals of the exporters it was linked to (what `scrub_tables` does in the old glue; step 3's imports have nothing to scrub yet, the hook is there for step 5). (b) The members are released in reverse order of registration. An importer linked to an exporter made *after* it is safe because the unlink pass runs first.
7. **Threads.** The registry is read and written under the lock of the store; the generation of a slot is only read under it. A lookup is on a cold path (putting a function in a table, taking it out); `call_indirect` inside wasm does not touch the registry.
8. **Hot reload** and unloading one member are not possible until the lazy collector (step 9); the registry is made so that they will be: the members have a slot number and a generation, and the edges are findable.

## What is not in step 4

Tables, `funcref` as a value and `Function` (step 5), host functions as members (step 5: the registry takes any `key`, and the `HostFunction` record is registered there), `externref` (6), tags (7), the registry across artifacts (8).

## The tests (C first, `tests/c/test_registry.c` and the cases in `test_links.c`)

register and find by key and by handle; a duplicate key refused; a stale handle after the store is closed and a new store made at the same addresses (the generation differs: a handle of the old store never opens a member of the new one); a pointer of another store: `WRONG_STORE`; an instance is found by the `module_instance` of its own `funcref` (taken from a real module); the order of the close (importer made before exporter; the unlink pass first; no use after free under ASan); `object` and `each` with counting retain/release (each retain is released once); threads (find and register from many threads under TSan, a close that waits for none); `instance_free` of a registered instance refused; mutations of the generation, of the key check and of the order of the close are caught.

## Open (for the owner)

1. **The store frees the instances.** Point 5 changes the ownership of step 3: a C host no longer frees a registered instance, the store does at the close (the tests change). Accepted?
2. **The core registers an instance by itself** (point 4) and a front end only replaces the object. Accepted, or should registration always be explicit?
3. The handle is 32 bits of index and 32 of generation in a `uint64_t`. Accepted?
