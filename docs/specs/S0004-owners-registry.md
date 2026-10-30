---
title: Registry of owners
kind: spec
id: S0004
status: implemented
superseded_by:
related: []
owner: maintainer
updated: 2026-10-30
---

# S0004 Registry of owners

## Summary
A `funcref` of wasm2c is `{ func_type, func, func_tailcallee, module_instance }`: the code and a pointer to the instance it belongs to. For us that pointer is the block of [S0003](S0003-instances.md): `wasmext_instance.module`. Nothing says who keeps that instance alive. If a function of A is in a table that B uses and A is freed, B calls into freed memory.

Before this step it was a chain of keep-alives written by hand in each front end (`writers`, `refs`, and `Table.get`, which finds the owner by scanning the exports of the instances that use the table). The chain cannot hold a function that no instance made (a host function). It is written twice (extension and wrapper).

This step is step 4 of layer 1 in [layers.md](../layers.md). It gives the store a registry of its members, in static C. A member lives until the store is closed, as in Wasmtime's `Store`. The registry replaces the Python-capsule design of `docs/owners_registry.md`.

Decisions of the owner of 2026-10-29: the handle is a number with a generation; the registry lives in the store; the store holds its members strongly until it is closed; an object of another store is a soft refusal in C (an exception in Python), not a panic.

## Goals / Non-goals
* Goals:
  * A handle `wasmext_owner` that recognises a stale handle.
  * A registry in the store: `key` (the `module_instance` pointer, or the pointer of a record of the host) to a member.
  * Operations that return a code and never abort: register, find, member, unregister, each.
  * The core registers an instance itself when it is instantiated, so a C host gets the registry with no line of code.
  * Lifetime as Wasmtime's `Store`: the store frees its members at the close.
  * A close that is safe for importers linked to exporters made after them.
  * A registry safe under threads.
* Non-goals:
  * Tables, `funcref` as a value and `Function` (step 5). Host functions as members (step 5): the registry takes any `key`, and the `HostFunction` record is registered there.
  * `externref` (step 6), tags (step 7), the registry across artifacts (step 8).
  * Hot reload and unloading one member: not possible until the lazy collector (step 9). The registry is made so that they will be: the members have a slot number and a generation, and the edges are findable.
  * The Python capsule `wasmext.owners.v1`, the weak entries and the wrapper over the registry of the extension (the design of `docs/owners_registry.md`).

## Interface

### Handle and registry (`src/wasmext/c/wasmext_registry.h`)
```c
typedef uint64_t wasmext_owner;   /* 0 is none */
```
Layout of the handle: the serial of the store in the top 16 bits (48 to 63), the index of the slot in 24 bits (24 to 47), the generation of the slot in 24 bits (0 to 23). `wasmext_store_serial_` is a counter of the process; each new store takes the next serial.

Ops of a member (any field may be NULL):
```c
typedef struct {
    void (*retain)(void *object);   /* once, when the member is registered */
    void (*release)(void *object);  /* once, at the close, after `close` */
    void (*unlink)(void *object);   /* at the close, first */
    void (*close)(void *object);    /* at the close, after `unlink` */
    int kind;                       /* (added by S0006) WASMEXT_KIND_* */
} wasmext_owner_ops;
enum { WASMEXT_KIND_NONE = 0, WASMEXT_KIND_INSTANCE = 1, WASMEXT_KIND_TABLE = 2, WASMEXT_KIND_EXTERN = 3, WASMEXT_KIND_HOST_FUNC = 4 };  /* (added by S0006) */
```
The kind is a field and not the address of the ops, because every translation unit that includes the header has its own copy of a `static const` ops, and the addresses would differ.

Slot and registry. The registry has a version and a size at its head, so that the record of the store in step 8 can carry it without a second layout.
```c
typedef struct {
    void *key; void *object; const wasmext_owner_ops *ops;
    uint64_t sequence;     /* the order of registration */
    uint32_t generation;
    uint32_t next_free;    /* index + 1 of the next free slot, in a free slot */
    uint8_t used;
} wasmext_slot;
typedef struct {
    uint32_t version, size;      /* WASMEXT_REGISTRY_VERSION and sizeof of this struct */
    uint32_t serial;             /* of the store */
    wasmext_slot *slots; uint32_t count, capacity; uint32_t free_head; uint64_t sequence;
    uint32_t *table; uint32_t table_capacity; uint32_t deleted;   /* open addressing, index + 1 of a slot */
} wasmext_registry;
```
Constants: `WASMEXT_REGISTRY_VERSION` 1, `WASMEXT_OWNER_MAX_SLOTS` (1 << 24), `WASMEXT_TABLE_EMPTY` 0, `WASMEXT_TABLE_DELETED` 0xFFFFFFFF.

Functions on the registry (the store wraps them under its lock):
```c
void wasmext_registry_init(wasmext_registry *r, uint32_t serial);
void wasmext_registry_destroy(wasmext_registry *r);
int  wasmext_registry_add(wasmext_registry *r, void *key, void *object, const wasmext_owner_ops *ops, wasmext_owner *out);
int  wasmext_registry_find(const wasmext_registry *r, const void *key, wasmext_owner *out);
int  wasmext_registry_find_kind(const wasmext_registry *r, const void *key, int kind, wasmext_owner *out);  /* (added by S0006) */
int  wasmext_registry_object(const wasmext_registry *r, wasmext_owner owner, void **object);
int  wasmext_registry_remove(wasmext_registry *r, wasmext_owner owner);
wasmext_slot **wasmext_registry_newest_first(const wasmext_registry *r, uint32_t *n);
```
Results: `WASMEXT_REGISTRY_OK` 0, `WASMEXT_REGISTRY_NOMEM` 3, `WASMEXT_REGISTRY_DUPLICATE` 4, `WASMEXT_REGISTRY_UNKNOWN` 5, `WASMEXT_REGISTRY_WRONG_STORE` 6, `WASMEXT_REGISTRY_STALE` 7.

### Members of the store (`src/wasmext/c/wasmext_store.h`)
The store holds `wasmext_registry registry` (a field of `wasmext_store`).
```c
int  wasmext_store_register(wasmext_store *s, void *key, void *object, const wasmext_owner_ops *ops, wasmext_owner *out);
int  wasmext_store_find(wasmext_store *s, const void *key, wasmext_owner *out);
int  wasmext_store_find_kind(wasmext_store *s, const void *key, int kind, wasmext_owner *out);   /* (added by S0006) */
int  wasmext_store_member(wasmext_store *s, wasmext_owner owner, void **object);
int  wasmext_store_unregister(wasmext_store *s, wasmext_owner owner);
void wasmext_store_each(wasmext_store *s, void (*visit)(void *object, void *arg), void *arg);
int  wasmext_store_adopt(wasmext_store *s, void *object, void (*free_fn)(void *object));
int  wasmext_store_unadopt(wasmext_store *s, void *object);
int  wasmext_store_close(wasmext_store *s);
int  wasmext_store_free(wasmext_store *s);
```
Results of the store: `WASMEXT_STORE_OK` 0, `WASMEXT_STORE_CLOSED` 1, `WASMEXT_STORE_BUSY` 2, `WASMEXT_STORE_NOMEM` 3, `WASMEXT_STORE_DUPLICATE` 4, `WASMEXT_STORE_UNKNOWN` 5, `WASMEXT_STORE_WRONG` 6, `WASMEXT_STORE_STALE` 7. The registry codes map one to one (`wasmext_store_registry_code_`).

### Registration of an instance (`src/wasmext/c/wasmext_instance.h`)
* `wasmext_instance.owner` (a `wasmext_owner`): the handle in the registry of the store, 0 before `instantiate`.
* The ops of an instance, `wasmext_instance_ops_`, are `{NULL, NULL, NULL, wasmext_instance_close_, WASMEXT_KIND_INSTANCE}`. `key` is `module`, `object` is the `wasmext_instance`.
* `wasmext_instance_free(i)` answers `WASMEXT_STORE_BUSY` for a registered instance.
* `wasmext_export.store` (the record of S0003, added at the end of the public record; the ABI declaration is updated): the store of the exporter, opaque.
* `wasmext_funcref` has `store` and `owner` fields (added by S0005).

## Semantics

### Handle
* 0 is none. A handle of a slot that was freed and reused has another generation, so a stale handle is recognised and not taken for the new member (the case of an instance made at the address of one that was freed). The generation wraps inside 24 bits and skips 0.
* A handle of another store has another serial: `WASMEXT_STORE_WRONG`. A handle of a gone member, or 0: `WASMEXT_STORE_STALE`.
* The serial is 16 bits so that a handle of one store never opens the member in the same slot of another store (see Changes, 2026-10-29).

### Registry
* Slots `{ key, object, ops, sequence, generation }`, a free list, and a hash table (open addressing) from `key` to the slot, under the lock of the store. It is rehashed when removed entries are many, or when it is half full.
* `register`: the store keeps `object` strongly (`ops->retain(object)` once). The `key` must be new: `WASMEXT_STORE_DUPLICATE`. A closed or closing store: `WASMEXT_STORE_CLOSED`.
* `find`: by the pointer a `funcref` carries. `WASMEXT_STORE_UNKNOWN` if the store has no such member. The registry of one store cannot tell a pointer of another store from a pointer of none: both are `UNKNOWN`. A registry knows its own members only. The front end reports `UNKNOWN` as a refusal with the reason in the text of the store, and raises its exception (a handle of another store is `WRONG`).
* `member`: the object of a handle, or `WRONG` or `STALE` (the object is not set then).
* `unregister`: takes a member out before the close. The ops are not run: the caller releases what it holds. The slot is used again later with another generation.
* `each`: calls `visit(object, arg)` for each member and each object of the arena, with the lock held (so `visit` must not call the store). A member with a NULL `object` is skipped. It is for a front end that shows its members to a cyclic collector (`tp_traverse` of CPython). A front end is not required to use it: `wasmtime-py` does not; a cycle through a function of the host is cured there by closing the store (`with store:`). The requirement of the front end is the explicit close.
* Kinds (added by S0006): `find_kind` finds a member only as the kind it claims. A member of no kind (`WASMEXT_KIND_NONE`) is not found by kind at all. A reference must be an `EXTERN`; the `module_instance` of a funcref an `INSTANCE` or a `HOST_FUNC`.

### Who registers
The core registers an instance itself in `wasmext_instance_instantiate`, after a good start (`key` = `module`, `object` = the instance). A C host gets the registry with no line of code. When registration fails the instance is released and cleared, and the call answers `WASMEXT_TRAP_CLOSED` (store closed) or `WASMEXT_TRAP_NO_MEMORY`. An instance that was never instantiated is not registered and can still be freed. A host function or a table registers by its own step (S0005).

### Lifetime
A member lives until the store is closed. `wasmext_instance_free` of a registered instance is refused (`WASMEXT_STORE_BUSY`). The store releases the structure of wasm2c at the close and frees the wrapper when the store is freed (`wasmext_store_adopt`), so a closed instance answers `WASMEXT_TRAP_CLOSED` instead of being a dangling pointer.

Instances are linked inside one store, as in Wasmtime, where an object of another store is refused. `bind_export` refuses a record of another store (`e->store != i->store`, or a record too short to carry `store`) with `WASMEXT_INST_LINK_FAILED` and the reason in the text of the store.

### Close (`wasmext_store_close`)
It refuses with `WASMEXT_STORE_BUSY` while a call is in flight. Then, outside the lock:
1. `unlink` of every member, newest first: an importer lets go of the tables, memories and globals of the exporters it was linked to (what `scrub_tables` does in the old glue). The hook is there for step 5; no member sets it yet.
2. `close` of every member, in the same order.
3. `release` of the objects that members retained, in the same order.
4. The arena, in the reverse order of owning.

An importer linked to an exporter made after it is safe because the unlink pass runs first.

### Threads
The registry is read and written under the lock of the store. The generation of a slot is only read under it. A lookup is on a cold path (putting a function in a table, taking it out). `call_indirect` inside wasm does not touch the registry. A close waits for none.

## Test plan
C first: `tests/c/test_registry.c` and the cases in `tests/c/test_links.c`.
* `uv run pytest tests/test_store_core.py -q -k registry`: `test_the_registry_of_owners` and `test_the_registry_under_sanitizers` (ASan/UBSan and TSan). They cover:
  * register and find by key and by handle; a duplicate key refused;
  * a stale handle after the store is closed and a new store made at the same addresses (the generation differs: a handle of the old store never opens a member of the new one);
  * a pointer of another store (`UNKNOWN`) and a handle of another store (`WRONG`);
  * `object` (`member`) and `each` with counting retain and release (each retain is released once);
  * the kinds (`test_kinds`);
  * threads: find and register from many threads under TSan; a close that waits for none;
  * `wasmext_instance_free` of a registered instance refused.
* `uv run pytest tests/test_store_core.py -q`: the whole file (store, errors, host, lock, registry).
* `uv run pytest tests/test_instance_core.py -q -k links`: `tests/c/test_links.c`. An instance is found by the `module_instance` of its own `funcref` (taken from a real module). The order of the close: importer made before exporter, the unlink pass first, no use after free under ASan. A record of another store is refused; this test replaced the test of two stores.
* `uv run pytest tests/test_instance_core.py -q -k externref`: `tests/c/test_externref.c`, the cases that offer an instance, a table, a host function and a reference in the wrong place (added by S0006).

Mutations caught: of the generation, of the serial of the store, of the key check, of the order of the close, and of the removed marks. The mutations of the two kind checks are caught (S0006).

## Alternatives considered
* The registry of `docs/owners_registry.md`: a registry `module_instance -> owner` for each interpreter, kept in the glue of each built module, shared through a capsule in the dictionary of the interpreter (`wasmext.owners.v1`), with weak entries (the registry keeps nothing alive; whoever receives a bare `funcref` looks the owner up and keeps it in a `Function` or in `refs`). Not taken: it is Python-specific, so a C host, the executable and a wrapper need their own copies. The capsule across front ends and across sub-interpreters was never tried. It left the chains of `writers` and `refs` in place between stores. The registry in the store, in static C, replaces it.
* Weak entries and who keeps whom alive: not taken. The store holds its members strongly until it is closed, as Wasmtime's `Store` does. This also removes the chains inside a store.
* Keeping the hand-written chains of keep-alives (`writers`, `refs`, scanning in `Table.get`): not taken. Every new feature has to extend them, and they cannot hold a function that Python itself made, since that has no instance.
* A handle of 32 bits of index and 32 of generation: not taken, it was the design. With 32 and 32 a handle of one store opens the member in the same slot of another store, and a lookup by a pointer cannot say which store a pointer belongs to. Built as 16 bits of serial, 24 of index, 24 of generation.
* Linking instances across stores: not taken. Closing the exporter's store freed what the importer's functions read (a use after free under ASan). Instances are linked inside one store.
* Explicit registration by every front end: not taken. The core registers an instance itself, so a C host needs no code.
* A kind as the address of the ops: not taken, the addresses differ between translation units. A kind is a field.
* A mutex-free registry: not taken. The registry is under the lock of the store; the lookup is on a cold path.
* Requiring a front end to walk the members with `each` for a cyclic collector: not taken. `wasmtime-py` does not; closing the store cures a cycle through a host function.
* Hot reload now: not possible until the lazy collector (step 9).

## Open questions
* A known gap of `docs/owners_registry.md` (2026-10-28, `test_a_python_callback_in_a_table_function` in `tests/test_wasi_across_instances.py`): an extension owner and a ctypes wrapper user, a table function that calls a Python callback ends in `Trap: Out-of-bounds access`. The cause is not known. It belongs to the old front ends; the registry does not cover it.
* The invariant to prove across stores: an owner is never freed while any table, global or `Function` can still hold one of its `funcref`s. Inside one store the registry holds it. Between stores the old chains rest on `writers` and `refs`.
* What a `funcref` of a closed store means in another store: refused (instances and funcrefs are of one store).
* The registry across artifacts is step 8.
* The capsule across front ends and sub-interpreters (the old design) was not tried and is not needed by this one.

## Changes
* 2026-10-28: `docs/owners_registry.md` written as a design note, for review, nothing built. It took what was decided in `TABLES_PLAN.md` and `context_concept.md`. Its known gap and its open invariants are listed above.
* 2026-10-29: design of step 4 written for review, replacing the Python-capsule design. The owner decided: the handle is a number with a generation; the registry lives in the store; the store holds its members strongly until closed; an object of another store is a soft refusal. Open points: the store frees the instances (changes the ownership of step 3, the tests change); the core registers an instance by itself and a front end only replaces the object; the handle as 32 bits of index and 32 of generation.
* 2026-10-29: built (`wasmext_registry.h`, the members in `wasmext_store.h`, the registration of an instance in `wasmext_instance.h`; `tests/c/test_registry.c`, the cases of `test_links.c`). Mutations of the generation, of the serial of the store, of the order of the close and of the removed marks are caught. What differs from the design, and why:
  1. The handle is 16 bits of the serial of the store, 24 of the index and 24 of the generation, not 32 and 32.
  2. The owner chose that the store frees its members; the first run showed what that means for a link across stores: closing the exporter's store freed what the importer's functions read (a use after free under ASan). So instances are linked inside one store. The record of an export carries the store (`wasmext_export.store`, added at the end of the public record, the ABI declaration updated) and `bind_export` refuses a record of another store, with the reason in the text.
  3. `wasmext_instance_free` is refused for an instantiated instance. The store releases the structure of wasm2c at the close and frees the wrapper when the store is freed (`wasmext_store_adopt`).
  4. The iteration for a cyclic collector (`wasmext_store_each`) covers the members and the arena, and a front end is not required to use it.
  5. `find` by a pointer answers `UNKNOWN` for a pointer of another store as for one of none; a handle of another store is `WRONG`.
* 2026-10-30: found in review after step 6c ([step6_externref.md](S0006-externref.md)): the members have a kind. The checks of 6a accepted any pointer that was a member of the store, and the members are of several kinds (instances, tables, host functions, references). A pointer of an instance would have passed as an `externref`, and `wasmext_extern_user` would have read an instance as a `wasmext_extern`; a reference would have passed as the `module_instance` of a funcref. The registry now records the kind of a member in its ops (`wasmext_owner_ops.kind`: `WASMEXT_KIND_INSTANCE`, `TABLE`, `EXTERN`, `HOST_FUNC`) and `wasmext_store_find_kind` finds a member only as the kind it claims (a member of no kind is not found by kind at all). A reference must be an `EXTERN`; the `module_instance` of a funcref an `INSTANCE` or a `HOST_FUNC`. This is a change to step 4 code, made there because it is a hole in what 6a built on it, not a side patch. `test_registry.c` (`test_kinds`) and the cases of `test_externref.c` cover it; the mutations of the two kind checks are caught.
* 2026-10-30: extended by S0005 (tables, host functions as members), S0006 (externref, kinds), S0007 (tags and exceptions).
* 2026-10-30: rewritten from `docs/step4_owners.md` into the spec format, status `implemented`.
