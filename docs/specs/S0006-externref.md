---
title: externref and globals of references
kind: spec
id: S0006
status: implemented
superseded_by:
related: []
owner: maintainer
updated: 2026-10-30
---

# S0006 externref and globals of references

## Summary
This is step 6 of layer 1 (see `docs/layers.md`). It sits on top of steps 3 to 5 (S0005 is the table step).
The core carries `externref` everywhere: in signatures, in tables and in globals. It also carries globals of `funcref`, which were refused since step 3.

The host gives the store a value it wants WebAssembly to hold (in Python: any object).
The store owns what it is given: it keeps the value until it is closed, then releases it once.
The collector that would free a value earlier is step 9.

Order inside the step, one commit each, CI between: 6a the value and the signatures, 6b tables of `externref`, 6c globals of `funcref` and `externref`.
Status: 6a, 6b and 6c built 2026-10-30. The step is complete. The owner accepted the order of `docs/layers.md` and the globals of both kinds of reference in this step.

### What there is (wasm2c)
* `wasm_rt_externref_t` is `void *` (null is `NULL`).
* `wasm_rt_externref_table_t` has the head of the funcref table (`data`, `max_size`, `size`).
* A global of `externref` is a `wasm_rt_externref_t`; a global of `funcref` is a `wasm_rt_funcref_t` (four words).
* Several results of `externref` come in `struct wasm_multi_e...`.
* The runtime has `wasm_rt_allocate/free/grow_externref_table`.
* The core refused `externref` everywhere (a signature, a table, a global) and a global of `funcref` (steps 3 and 5).

## Goals / Non-goals
* Goals:
  * `wasmext_extern_new`: a record `{ user, release, store }`, a member of the store; its pointer is the `externref` that WebAssembly sees.
  * `externref` in signatures: exports, imports, `call_ref` and the host functions of a table.
  * Tables of `externref` (element type 0x6F) next to tables of `funcref`.
  * Globals of both kinds of reference: read, write, record, link, and the value the host gives an immutable import.
  * A kind on every member of the store, so that a pointer is accepted only as the kind it claims to be.
* Non-goals:
  * The collector. Until step 9, a long-lived store that is given very many values holds them all. The way out is to close the store (an explicit `with store:`), which the front ends already require.
  * Counting references from the host. WebAssembly copies an `externref` where the host does not see (locals, a table, a global), so only a scan of what the store holds can say that nobody holds a value, and that is the collector.
  * An `externref` in the typed fast shape, and linking a function with an `externref` in its signature across instances (step 8, as for `funcref`).
  * `FEATURES.md` and the old glue: untouched. The old glue still refuses these features and goes with its step.

## Interface

### The value (`wasmext_instance.h`)
```c
typedef struct {
    void *user;
    void (*release)(void *user);
    wasmext_store *store;
    int released;
} wasmext_extern;

int   wasmext_extern_new(wasmext_store *store, void *user, void (*release)(void *user), wasmext_extern **out);
void *wasmext_extern_user(const wasmext_extern *e);
int   wasmext_extern_check_(wasmext_store *store, const void *e);
int   wasmext_extern_result_(void *self, const wasmext_val *r, wasm_rt_externref_t *out);
```
* In `wasmext_val` the type is `0x6F` and `as.ref` is the pointer to the record itself. There is no storage of the caller's, unlike a `funcref` result, which is a struct.
* `release` may be NULL.
* `wasmext_extern_check_` answers 0 or `WASMEXT_TAB_WRONG_STORE`. `wasmext_extern_result_` is used by the generated function of an import to take the answer of a host function.

Answers used (declared in `wasmext_instance.h`):

| constant | value | use here |
|---|---|---|
| `WASMEXT_TAB_WRONG_STORE` | -32 | a value that is not a member of this store, or not of the kind `EXTERN` |
| `WASMEXT_TAB_WRONG_ELEM` | -34 | an operation of one element type on a table of the other |
| `WASMEXT_TAB_BOUNDS` | -30 | index outside the table |
| `WASMEXT_TAB_FULL` | -31 | the table cannot grow that much |
| `WASMEXT_INST_BAD_ARGS` | -2 | wrong types; a funcref global read with no place to write into |
| `WASMEXT_INST_UNSUPPORTED` | -4 | `bind_typed` for a signature with a reference |
| `WASMEXT_INST_IMMUTABLE` | -8 | write to an immutable global |
| `WASMEXT_TRAP_HOST` | trap | a host answer that is not a member of the store |
| `WASMEXT_TRAP_CLOSED` | trap | closed store |

### Kinds of members (`wasmext_registry.h`, `wasmext_store.h`)
```c
typedef struct {
    void (*retain)(void *object);
    void (*release)(void *object);
    void (*unlink)(void *object);
    void (*close)(void *object);
    int kind;                 /* WASMEXT_KIND_* */
} wasmext_owner_ops;
enum { WASMEXT_KIND_NONE = 0, WASMEXT_KIND_INSTANCE = 1, WASMEXT_KIND_TABLE = 2,
       WASMEXT_KIND_EXTERN = 3, WASMEXT_KIND_HOST_FUNC = 4 };
int wasmext_registry_find_kind(const wasmext_registry *r, const void *key, int kind, wasmext_owner *out);
int wasmext_store_find_kind(wasmext_store *s, const void *key, int kind, wasmext_owner *out);
```
A reference must be an `EXTERN`. The `module_instance` of a funcref must be an `INSTANCE` or a `HOST_FUNC`. A member of no kind (`NONE`) is not found by kind at all.
`wasmext_store_find` (any kind, does not read the pointer) stays for the cases that need no kind.

### Tables (`wasmext_table.h`)
```c
wasmext_tab *wasmext_tab_new(wasmext_store *store, int elem, uint32_t initial, uint32_t maximum, int *error);
int wasmext_tab_get_extern(wasmext_tab *t, uint32_t index, void **out);
int wasmext_tab_set_extern(wasmext_tab *t, uint32_t index, void *ref);
int wasmext_tab_grow(wasmext_tab *t, uint32_t delta, uint32_t *previous);   /* follows the element type */
int wasmext_tab_size(wasmext_tab *t, uint32_t *size, uint32_t *maximum);    /* follows the element type */
int wasmext_tab_record(wasmext_tab *t, void *owner, wasmext_export *out);
int wasmext_instance_table_get_extern(wasmext_instance *i, uint32_t index, uint32_t element, void **out);
int wasmext_instance_table_set_extern(wasmext_instance *i, uint32_t index, uint32_t element, void *ref);
```
* `elem` is `0x70` or `0x6F`. `wasmext_tab_get/set` and `wasmext_instance_table_get/set` (S0005) are for funcref tables.
* The record of a table says its element type in bit 5 of `flags` (`32u`). `wasmext_tab_record` and `wasmext_instance_export_record` set it for `externref`.
* Internal: `wasmext_tab_xget_`, `wasmext_tab_xset_`, `wasmext_tab_xsize_`, `wasmext_tab_xgrow_`, `wasmext_instance_table_of_`.

### Globals (`wasmext_instance.h`)
```c
int wasmext_instance_global_get(wasmext_instance *i, uint32_t index, wasmext_val *out);
int wasmext_instance_global_set(wasmext_instance *i, uint32_t index, const wasmext_val *value);
int wasmext_instance_bind_global_value(wasmext_instance *i, uint32_t import, const wasmext_val *v);
```
They carry the types `0x70` and `0x6F`. The record of an exported global (`WASMEXT_GLOBAL`) has `type` = the value type byte; `bind_export` of a global compares that byte as it does for numbers.
The cell of an imported immutable global that the host gives is `uint64_t values[4]` for each import (32 bytes: a funcref is four words).

### Binding (`_binding.py`)
The binding carries `externref` in the signatures of exports, imports, `call_ref` and the host functions of a table.
* C types: `_CTYPE["externref"] = "wasm_rt_externref_t"`, `_MULTI_CODE["externref"] = "e"`, `_RT_TYPE["externref"] = "WASM_RT_EXTERNREF"`. The tables of the old glue lack the `externref`; the binding adds it.
* Letter in a signature of a record: `"r"` for both kinds of reference (`_SIG_LETTER`).
* `_has_ref(ft)` and `_linkable(ft)`: a function with a reference in its signature has no typed shape and no shim.
* The adapters, the forwarders and the trampolines (`_adapter`, `_forwarder`, `_trampoline`, `_slot_call`) pass an `externref` by the pointer, and check an answer with `wasmext_extern_result_`.
* Imports of tables of `externref` use `wasm_rt_externref_table_t`; imports of globals of both kinds are carried through `ref_slot`.

## Semantics

### The decision: the store owns what it is given
* `wasmext_extern_new` makes the record, adopts it in the store and registers it under its own pointer with `WASMEXT_KIND_EXTERN`. The pointer is the `externref` that WebAssembly sees.
* WebAssembly never reads the record. It only copies it (locals, tables, globals, arguments, results).
* The store keeps every record until it is closed. Then it calls `release(user)` once (in Python: the decref).
  `release` is not called again when the store is freed (the `released` flag).
* This is Wasmtime's model (the value lives in the store) without its collector.
* Errors of `extern_new`: NULL `store` or `out` is `WASMEXT_INST_BAD_ARGS`; a closed store is `WASMEXT_TRAP_CLOSED`; no memory is `WASMEXT_INST_NOMEM`.

### What crosses, and the checks
* A value goes in (an argument of a call, an answer of a host function, a write to a table or a global, `bind_global_value`): its pointer must be a member of this store, of the kind `EXTERN` (`wasmext_store_find_kind`, which does not read the pointer).
  Otherwise `WASMEXT_TAB_WRONG_STORE`. A value of another store, or one that this API did not make, is refused, never trusted. A NULL is always acceptable.
* A bad answer of a host function is a trap `WASMEXT_TRAP_HOST`.
* A value comes out (a result, a read from a table or a global): WebAssembly can give back only what it was given, so it is a member already and is not checked again.
  The host reads its `user` with `wasmext_extern_user(ref)`; NULL gives NULL.
* A function with an `externref` in its signature has no typed shape: `wasmext_instance_bind_typed` refuses it (`WASMEXT_INST_UNSUPPORTED`).
  It has no record for linking between instances either, as the functions with a `funcref` (step 8). A host function in a table (S0005, 5c) and `call_ref` (5b) carry it.

### Kinds of members
The checks of 6a first accepted any pointer that was a member of the store, and the members are of several kinds (instances, tables, host functions, references).
A pointer of an instance would have passed as an `externref`, and `wasmext_extern_user` would have read an instance as a `wasmext_extern`.
A reference would have passed as the `module_instance` of a funcref.
Now `wasmext_store_find_kind` finds a member only as the kind it claims. The kind is a field of `wasmext_owner_ops`, not the address of the ops.
Every translation unit that includes the header has its own copy of a `static const` ops, so the addresses would differ.
This changed step 4 code. It was done here because it is a hole in what 6a built on it, not a side patch to something finished.

### Tables of `externref`
* `wasmext_tab_new` takes the element type. `get/set` of an `externref` table take and give the pointer of the record.
* `grow` and `size` follow the element type. The operations of the other kind answer `WASMEXT_TAB_WRONG_ELEM`.
* `bind_export` refuses a table of the other element type (bit 5 of `flags` against the import), and keeps the limits as before.
* The operations on a table that an instance exports (`wasmext_instance_table_*`) do the same by the type in the descriptor.
* The take-back of a failed start (S0005) is for funcref tables only: the elements of an `externref` table are not functions of the instance.
* A write is checked as any value that goes in. The same locks and the same store entry as for funcref tables.

### Globals of references
* A read of a funcref global is written where the caller points `out->as.ref` (at a `wasmext_funcref`). NULL is `WASMEXT_INST_BAD_ARGS`. The funcref gets the store and the handle of its instance (`WASMEXT_TAB_STALE` if no member stands behind it).
* A read of an `externref` global gives the reference (`as.ref`), NULL when null.
* For a write the caller points `as.ref` at the `wasmext_funcref` to write, or at the `externref`. A write, and the value the host gives an immutable import, are checked as any value that goes in (`WASMEXT_TAB_WRONG_STORE`).
* An immutable global is `WASMEXT_INST_IMMUTABLE` on write. `bind_global_value` of a mutable global is `WASMEXT_INST_IMMUTABLE` (a mutable global is the global of another instance).
* The take-back of a failed start also empties a shared mutable global of `funcref` into which the start function put a function of its own (as it empties the elements of a table).

## Test plan
Commands:
```
uv run pytest tests/test_instance_core.py -q -k "externref or globals_of"
```
Expected: 4 passed (`test_externref_values`, `test_externref_under_sanitizers`, `test_globals_of_references`, `test_globals_of_references_under_sanitizers`).

C files that the tests build:
* `tests/c/test_externref.c` (ASan/UBSan, TSan): the value and the signatures (6a); the tables (6b): the table a module exports, shared with an importer, a table of the host, what goes in, the other element type, the limits, the failed start.
  It also has the cases that offer an instance, a table, a host function and a reference in the wrong place.
* `tests/c/test_ref_globals.c` (ASan/UBSan): globals of both kinds (6c).
* `tests/c/test_registry.c`, `test_kinds`: the kind of a member.
* Also `tests/c/test_tables.c` (S0005) for the tables of funcref.

Mutations that must fail the tests (done on 2026-10-30, each caught):
* 6a: the membership check, the check of a host answer and of its type, the release, the check of an argument, the refusal of the typed shape, the adapter, the registration.
* 6b: the check of what goes in, the bounds, the element type of each operation, the flag of the record, the size and growth;
  under LeakSanitizer and ASan: the free at the close and the take-back.
* 6c: each check of what goes in, the check that the caller gave a place to read into, the owner of the funcref read, the take-back from a global, the size of the cell.
  One of these is caught only by a sanitizer, and one by a crash.
* Kinds: the two kind checks (`test_kinds` and the wrong-place cases of `test_externref.c`).

## Alternatives considered
* Counting references from the host.
  Why not: WebAssembly copies an `externref` where the host does not see. Only a scan of what the store holds can say that nobody holds a value.
* A collector now.
  Cost: a scan of locals, tables and globals. Why not: it is step 9; until then the store keeps everything until it is closed.
* Accept any member of the store as a reference (the first form of 6a, `wasmext_store_find`).
  Why not: a pointer of an instance would pass as an `externref`. Fixed by the kind of the member.
* The kind as the address of the ops table.
  Why not: each translation unit has its own copy of a `static const` ops, so the addresses differ. The kind is a field.
* A typed fast shape and a link record for functions with an `externref`.
  Why not: a reference is checked as it comes in, and the typed shape has no checks. Linking across instances is for step 8.
* Globals of references in a later step.
  Why not: they were refused since step 3, and step 5 did not touch them; the owner accepted them in this step.

## Open questions
* The collector (step 9): when does a value leave a long-lived store before it is closed?
* A function with a reference in its signature cannot be linked across instances (step 8, with the trap state).

## Changes
* 2026-10-30: written as `docs/step6_externref.md`; moved to this spec with status `implemented`.
* 2026-10-30: the owner accepted the order of `docs/layers.md` and the globals of `funcref` and `externref` in this step.
* 2026-10-30, 6a: built `wasmext_extern_new/user`, `wasmext_extern_check_`, `wasmext_extern_result_` in `wasmext_instance.h`.
  The binding carries `externref` in the signatures of exports, imports, `call_ref` and the host functions of a table (the adapters, the forwarders and the trampolines).
  The tables of C types, letters of multi results and types of wasm2c in `_binding.py` have the `externref` that the old glue lacks.
  A `wasmext_val` of type 0x6F has the pointer to the record in `as.ref`. `tests/c/test_externref.c` was added.
* 2026-10-30, 6b: `wasmext_tab_new(store, elem, initial, maximum, error)` takes the element type (0x70 or 0x6F). The signature changed from 5a; the ABI is free in alpha.
  Added `wasmext_tab_get_extern/set_extern` and, for a table an instance exports, `wasmext_instance_table_get_extern/set_extern`.
  `grow` and `size` follow the element type; the operations of the other kind answer `WASMEXT_TAB_WRONG_ELEM`.
  The record of a table says its element type in bit 5 of `flags`, and `bind_export` refuses a table of the other type (and keeps the limits as before).
  The take-back of a failed start is for funcref tables only. The binding carries imports of `externref` tables.
  Tests: `tests/c/test_externref.c` and `test_tables`.
* 2026-10-30, 6c: `wasmext_instance_global_get/set`, the record of an exported global, `bind_export` of a global (the type byte is compared as for the numbers) and `wasmext_instance_bind_global_value` carry 0x70 and 0x6F.
  A read of a funcref global is written where the caller points `out->as.ref` (NULL is `WASMEXT_INST_BAD_ARGS`), with the store and the handle of its instance. The cell of such a value is 32 bytes.
  The take-back of a failed start also empties a shared mutable global of funcref.
  The binding carries imports of globals of both kinds. `tests/c/test_ref_globals.c` was added.
* 2026-10-30, after 6c, found in review: the members have a kind. The registry of step 4 records the kind of a member in its ops (`wasmext_owner_ops.kind`, `WASMEXT_KIND_INSTANCE`, `TABLE`, `EXTERN`, `HOST_FUNC`), and `wasmext_store_find_kind` finds a member only as the kind it claims.
  `test_registry.c` (`test_kinds`) and the wrong-place cases of `test_externref.c` were added.
