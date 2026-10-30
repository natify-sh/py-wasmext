---
title: Tables, funcref and host functions as table elements
kind: spec
id: S0005
status: implemented
superseded_by:
related: []
owner: maintainer
updated: 2026-10-30
---

# S0005 Tables, funcref and host functions as table elements

## Summary
This is step 5 of layer 1 (see `docs/layers.md`). It sits on top of step 3 (instances) and step 4 (the registry of owners).
It finishes what `docs/TABLES_PLAN.md` and the refusals of the old glue left open: a `funcref` in an import and as a parameter,
`Function`, and host functions in tables.

The static C core gets tables that belong to the store, the public value `wasmext_funcref`, calls of a function by its funcref
(`call_ref`), `funcref` in signatures, and host functions that stand as table elements.
Everything works inside one store, and a store is made by one artifact (one copy of the wasm2c runtime).

Status: built 2026-10-30 as 5a, 5b-1, 5b-2 and 5c. The step is complete. `externref` tables came in S0006.

### What there is (wasm2c)
* A table is `{ wasm_rt_funcref_t *data; uint32_t max_size, size; }`.
* An element is `{ func_type, func, func_tailcallee, module_instance }`.
* An imported table is a pointer the module reads. An exported one is reached by `w2c_<p>_<name>(w2c_<p> *)`.
* `call_indirect` compares the type of the element with the expected one by the pointer of the type.
  If the pointers differ, it compares a 256-bit hash. So an element made by another module of the same type is accepted.
* The static glue (`wasmext_glue.h`) already had the operations on a table that no module owns:
  `wasmext_table_new/free/grow/export` and `wasmext_function_export`. They are reused.
* The old glue (`_gen.py`, `_shared.py`, `_ctypes_gen.py`) refuses: a `funcref` in an import, a `Function` called with a
  `funcref` parameter, `externref`, a host function as a member of a table.
  Who keeps whom alive is the chains of the problem statement of step 4.
* Step 3 refused a table import and an export record of a table ("step 5"), and a `funcref` in a signature ("step 5 or 6").

### The one hard fact: a trap in a function that comes out of another runtime
Each artifact has its own copy of the wasm2c runtime and so its own `g_wasm_rt_jmp_buf`.
A function of another artifact in a shared table traps by a long jump to its buffer, which was not set for this call
(`docs/TABLES_PLAN.md`, the spike).
Inside one artifact (one copy of the runtime) there is no such problem.
The trap goes to the buffer of the call that is running, the caller's, as WebAssembly says.
Since step 4 instances are linked inside one store, and a store is made by one artifact, step 5 works inside one artifact.

## Goals / Non-goals
* Goals:
  * A table as a member of the store: `new`, `size`, `maximum`, `grow`, `get`, `set`, freed when the store is closed.
  * The same operations on a table that an instance exports.
  * A table import: the record of an exported or host table is bound to an import, and wasm2c gets the pointer.
  * `wasmext_funcref`: the public value of a function that is not an export any more.
    It carries its store and the handle of its owner, so a funcref of another store, or a forged one, is refused.
  * The functions of an instance as elements (`wasmext_instance_funcref`).
  * The take-back at the close: an instance that put functions of its own into a table it imported takes them out.
  * `call_ref`: call a funcref through an instance whose module declares its type.
  * `funcref` in a signature: argument and result of exports, imports, `call_ref` and host functions.
  * A function of the host as an element of a table.
* Non-goals:
  * Tables shared across separately built artifacts, and the trap state they need (step 8).
  * Calling by the host an element whose type no module of the artifact declares.
  * `funcref` in the typed fast shape, and linking a function with a `funcref` in its signature across instances (step 8, with the trap state).
  * `externref` (S0006), tags (S0007).
  * Synchronising a write to a table by WebAssembly code with the host's (the threads proposal, step 11).
  * Taking the lock of the host (`wasmext_rlock`) inside a host function put in a table: it is the business of the function itself, as for an import.

## Interface

### Value and errors (`wasmext_instance.h`)
```c
typedef struct {
    wasm_rt_funcref_t ref;   /* func_type, func, func_tailcallee, module_instance */
    const void *store;
    wasmext_owner owner;     /* handle of the instance (or host function) in the registry of that store */
} wasmext_funcref;
```
A `wasmext_val` of type `0x70` carries a pointer to a `wasmext_funcref` in `as.ref` (NULL is the null funcref).

Answers of the API that are not a trap:

| constant | value | meaning |
|---|---|---|
| `WASMEXT_INST_BAD_EXPORT` | -1 | index out of range, or an export of another kind than the call needs |
| `WASMEXT_INST_BAD_ARGS` | -2 | number or types of arguments or results do not fit; a funcref result with no place to write |
| `WASMEXT_INST_NOT_INSTANTIATED` | -3 | the instance is not made yet |
| `WASMEXT_INST_UNSUPPORTED` | -4 | a case the core does not carry (see Semantics) |
| `WASMEXT_INST_NOMEM` | -5 | out of memory |
| `WASMEXT_INST_LINK_FAILED` | -9 | an export given for an import does not fit; the text is in the store |
| `WASMEXT_INST_UNDECLARED_TYPE` | -10 | `call_ref` or `host_funcref`: the module does not declare the type |
| `WASMEXT_TAB_BOUNDS` | -30 | index outside the table |
| `WASMEXT_TAB_FULL` | -31 | the table cannot grow that much (its maximum, or memory) |
| `WASMEXT_TAB_WRONG_STORE` | -32 | the function is of another store, or is not a function of one |
| `WASMEXT_TAB_STALE` | -33 | the element is a function that no member of the store stands behind |
| `WASMEXT_TAB_WRONG_ELEM` | -34 | an operation of one element type on a table of the other |

Trap codes used: `WASMEXT_TRAP_CLOSED` (closed store), `WASMEXT_TRAP_HOST` (failure of a host function),
`WASM_RT_TRAP_NULL_REF` (`call_ref` of a null funcref). `WASMEXT_TABLE_NO_MAXIMUM` (0xFFFFFFFF) means no maximum.

### Table of the store (`wasmext_table.h`)
```c
typedef struct wasmext_tab_s_ wasmext_tab;   /* fields: elem, table, etable, store, owner, mutex, live */
wasmext_tab *wasmext_tab_new(wasmext_store *store, int elem, uint32_t initial, uint32_t maximum, int *error);
int wasmext_tab_get(wasmext_tab *t, uint32_t index, wasmext_funcref *out);
int wasmext_tab_set(wasmext_tab *t, uint32_t index, const wasmext_funcref *f);
int wasmext_tab_grow(wasmext_tab *t, uint32_t delta, uint32_t *previous);
int wasmext_tab_size(wasmext_tab *t, uint32_t *size, uint32_t *maximum);
int wasmext_tab_record(wasmext_tab *t, void *owner, wasmext_export *out);
```
* `elem` is `0x70` (funcref) or `0x6F` (externref, S0006). `wasmext_tab_new` returns NULL with `*error` set to `EINVAL`, `EBADF` (closed store) or `ENOMEM`.
* The table registers itself in the store with `WASMEXT_KIND_TABLE`.
* `wasmext_tab_record` fills the record that an import is given (`wasmext_instance_bind_export`). It is valid until the store is closed.

### Table that an instance exports (`wasmext_table.h`)
The index is the export index of the descriptor (`WASMEXT_DESC_TABLE`).
```c
int wasmext_instance_table_get(wasmext_instance *i, uint32_t index, uint32_t element, wasmext_funcref *out);
int wasmext_instance_table_set(wasmext_instance *i, uint32_t index, uint32_t element, const wasmext_funcref *f);
int wasmext_instance_table_grow(wasmext_instance *i, uint32_t index, uint32_t delta, uint32_t *previous);
int wasmext_instance_table_size(wasmext_instance *i, uint32_t index, uint32_t *size, uint32_t *maximum);
```

### Functions as elements and `call_ref` (`wasmext_instance.h`)
```c
int wasmext_instance_funcref(wasmext_instance *i, uint32_t index, wasmext_funcref *out);
int wasmext_instance_call_ref(wasmext_instance *i, const wasmext_funcref *f,
                              const wasmext_val *args, uint32_t n_args, wasmext_val *results, uint32_t n_results);
int wasmext_instance_host_funcref(wasmext_instance *i, const uint8_t *params, uint32_t n_params,
                                  const uint8_t *results, uint32_t n_results, wasmext_host_fn fn,
                                  void *user, void (*release)(void *user), wasmext_funcref *out);
typedef struct {                  /* a member of the store, WASMEXT_KIND_HOST_FUNC */
    wasmext_import_slot slot;     /* first: fn, user and the instance it is of (slot.self) */
    wasmext_store *store;
    void (*release)(void *user);
    int released;
} wasmext_host_func;
```
Helpers that the generated code and the checks use: `wasmext_funcref_member_`, `wasmext_funcref_check_`, `wasmext_funcref_from_`,
`wasmext_funcref_result_`, `wasmext_call_check_refs_`, `wasmext_call_fill_refs_`.

### Records and import (`wasmext_glue.h`, `wasmext_instance.h`)
* `wasmext_export` of kind `WASMEXT_TABLE`: `type` = `sizeof(wasm_rt_funcref_table_t)` (the same size for externref), `address` = the table.
* `flags` bit 4 is set on a function record that may be put in a table (of this store). `wasmext_export.funcref` points at the element of such a function.
  `WASMEXT_SINCE_TABLE` and `WASMEXT_SINCE_FUNCREF` (both 0x1A1) are the floors that `wasmext_export_seal` raises.
* `wasmext_instance_export_record` and `wasmext_instance_bind_export` accept a table. The checks are the record kind, `type`, the limits (size and maximum against what the import needs), and the element type.
* The old operations on a table that no module owns are used by the new ones: `wasmext_table_new`, `wasmext_table_free`, `wasmext_table_grow`, `wasmext_table_export`, `wasmext_function_export`.

### Binding (`wasmext_binding`, made by `_binding.py`)
* `ref_types` / `n_ref_types`: one `wasmext_ref_type` for each distinct function type of the type section.
  Fields: `type()` (wasm2c's type through `wasm2c_<p>_get_func_type`), `adapter`, `sig`, `trampoline`.
  The adapters of these types are always the reentrant ones.
* `wasmext_export_binding.funcref`: fills the element of a table that stands for an export. `shim` and `funcref` are set for every function, one with a reference in its signature included (8a-2, S0008).
* `ref_slot` gives the pointer wasm2c reads for a table import. `wasmext_import_slot.self` is the instance a slot is of.
* The trampoline of a type is the body of the forwarder of an import (`_slot_call` in `_binding.py`), shared with it. It is made for each type, and `func_type` is the type of the instance that made the funcref.
* The static headers of layer 1 are compiled strictly by `.github/scripts/layer1_check.c` (gcc, clang, MinGW, MSVC).

## Semantics

### Tables
* A table is a member of the store, as in WebAssembly and Wasmtime. It lives until the store is closed.
* Every operation enters the store (a closed store answers `WASMEXT_TRAP_CLOSED`; `close` refuses while an operation is in flight) and takes the lock of the table.
  The lock is the table's own. For an exported table it is the `pin_mutex` of the instance. So the host can call from any thread.
* A write to a table by WebAssembly code (`table.set`, `table.grow`, an `elem` segment) is not synchronised with the host's.
  A host that grows or sets a table does it when no call of the store is running, as it does for a memory.
* `set` puts a funcref in a slot. A null funcref (`ref.func` NULL) or NULL empties the slot.
  The funcref must be of the store (`store` equal) and made by this API: the pointer of its instance must be a member of the store under the very handle the value carries.
  A forged value is refused (`WASMEXT_TAB_WRONG_STORE`), not trusted.
* The type of an element is not checked when it is put in. `call_indirect` of the module that calls it compares it, as in WebAssembly.
* `get` answers `WASMEXT_TAB_STALE` for an element no member of the store stands behind. An empty slot has `out->ref.func` NULL.
* `grow` fills with null; `previous` is the size before. It answers `WASMEXT_TAB_FULL` at the maximum or when memory is short.
* A table import is refused when the limits do not fit (as for a memory). The text of the refusal is in the store.
* A bad index is `WASMEXT_TAB_BOUNDS`. A table with a 64-bit or shared limit is `WASMEXT_INST_UNSUPPORTED`.
* The take-back: when an instantiation fails, the `elem` segments or the start function may have put functions of the instance into tables it imports.
  The structure they point to is released. The core takes those elements out (slots become null), so the owner of the table and the others that share it do not call a function that is gone.
  It tests whether `module_instance` lies inside the structure of the failed instance. The host does not call into the store with the tables while an instance is made.

### Functions as elements
* `wasmext_instance_funcref` fills the funcref of exported function `index`. It works for a function with a reference in its signature as well.
* `wasmext_instance_call_ref` calls the function of an element through an instance whose module declares its type.
  The type is matched as `call_indirect` does: the pointer of the type, then its 256-bit hash.
* Errors of `call_ref`: undeclared type is `WASMEXT_INST_UNDECLARED_TYPE`; a null funcref is the trap `WASM_RT_TRAP_NULL_REF`; a funcref of another store is `WASMEXT_TAB_WRONG_STORE`; wrong counts or types are `WASMEXT_INST_BAD_ARGS`.
  After a trap the instances stay usable.
* The adapters of `ref_types` are the reentrant ones: the function is of any instance of the store, and the call may be made from inside a host function.
* An element of a type that no module of the artifact declares cannot be called by the host. It can still be called by WebAssembly through `call_indirect` (the AOT rule).

### `funcref` in a signature
* An argument is a `wasmext_val` of type `0x70` whose `as.ref` is a `wasmext_funcref` (NULL is the null funcref).
  Before the call the core checks that it is of the store and made by this API (`WASMEXT_TAB_WRONG_STORE`).
* A result is written where the caller points `as.ref`. NULL there is `WASMEXT_INST_BAD_ARGS` and nothing is called.
  After the call the core gives the result its store and the handle of its instance (`WASMEXT_TAB_STALE` if no member stands behind it). The same in `call_ref`.
* For an import, the host function is given a `wasmext_funcref` valid for the call (`slot.self` is the instance it is of).
  It answers one in the same way, or NULL. A function of another store, a forged one, a result of another type, or a failure of the host is a trap `WASMEXT_TRAP_HOST` (or the failure's own code).
* What a funcref cannot do: the typed fast shape has no funcref (it would pass a struct by value). So `wasmext_instance_bind_typed` refuses such an import (`WASMEXT_INST_UNSUPPORTED`).
  A function with a funcref in its signature has a record and is linked (8a-2, S0008): the letters of the signature are `F` and `E`, the shim and the typed slot pass `wasm_rt_funcref_t` by value and `void *`. The shim checks a reference as it comes in (a funcref of a member of the store and, until 8b, of the artifact of the callee; an externref a member of the store), and the importer checks a funcref that comes out; typed HOST functions with a reference stay refused (`bind_typed` answers `UNSUPPORTED`).
  Linking those across instances is for step 8, with the trap state.

### Host functions as elements
* `wasmext_instance_host_funcref` makes a `wasmext_host_func` and registers it as a member of the store under its own pointer. That pointer is the `module_instance` of the funcref.
  So it passes the same checks as the function of an instance (`set`, `call_ref`, `get`).
* `func` is the trampoline that the binding makes for the type. `func_type` is the type of the instance that made it, so another module with the same type accepts it in `call_indirect` (the hash).
* A type that the module does not declare is `WASMEXT_INST_UNDECLARED_TYPE` and nothing is made (the AOT rule).
* The store keeps the record until it is closed. `release(user)` is called once, at the close (not again when the store is freed). The record itself is freed with the store.
* A host function may call the module again from inside the call: the reentrant adapters put the buffer of the outer call back.
* A failure of the host in a trampoline is a trap, reported as for an import.

## Test plan
Commands:
```
uv run pytest tests/test_instance_core.py -q -k tables
```
Expected: 2 passed (`test_tables_of_funcref`, `test_tables_under_sanitizers`; the second builds with ASan/UBSan and with TSan).

C files that the tests build (through the fixture `build`, so they use the repairs of `_natify` and the runtime wrappers):
* `tests/c/test_tables.c`: five real modules built from `.wat`.
  * a table exported by one and imported by another; `elem` segments of the importer that fill the table of the exporter;
  * a standalone table filled with elements of two instances, called through `call_indirect` of a third;
  * a function of the wrong type is a trap in the caller; `grow` seen by both; an element of an instance whose store is closed;
  * a funcref of another store, and a forged one; the take-back; `call_ref` for every value type and several results;
  * `funcref` as parameter and result; a host function in a table called from wasm; a trap inside a function that comes through a table, with both instances usable after it.
* `tests/c/test_registry.c` (kinds of members) is in S0006.

Under ASan/UBSan and, where there are threads, TSan.

Mutations that must fail the tests (done on 2026-10-30, each caught):
* the take-back of the functions of a failed instantiation;
* the check of the store, the check of the owner (the handle), the check of the bounds;
* the lock of the table;
* the limits of an import.

Also the strict header check: `.github/scripts/layer1_check.c` (gcc, clang) compiles the static headers of layer 1.

## Alternatives considered
* Tables shared across separately built artifacts (functions of another runtime in a shared table).
  Cost: the trap goes to a long-jump buffer of the other copy of the runtime. It needs the trap state to be shared: the stack of entries `wasmext_traps` that the old glue has, or a trampoline in the exporter.
  Why not: deferred to step 8, which settles what a store shared across artifacts is. Step 5 works inside one artifact.
* A funcref that names its owner only by the pointer of the instance (the design of 2026-10-29).
  Why not: a forged value would be trusted. The built funcref carries `store` and `owner`, and `set` accepts it only when the pointer is a member of the store under that handle.
* Host functions for any type, made at run time.
  Why not: the glue is made ahead of time (the AOT rule, as in the old glue). A type the module does not declare has no trampoline.
* `call_ref` for any element.
  Why not: the adapter is found by the type of the element, and an adapter exists only for the types some module declares.
* A funcref in the typed fast shape.
  Why not: it would pass a struct by value, and a reference must be checked as it comes in.
* One commit for all of step 5.
  Why not: the order 5a, 5b, 5c, one commit each with CI between, was accepted by the owner.

## Open questions
None for this step. The four points of the design were accepted by the owner:
1. inside one artifact first (the trap state across artifacts is for step 8);
2. host functions as table members only for the types the module declares;
3. `call_ref` by the host only for the types a module declares;
4. the order 5a, 5b, 5c with CI between.

Still open elsewhere: the trap state across artifacts and a store shared across artifacts (step 8); threads and synchronisation of a table written by WebAssembly (step 11).

## Changes
* 2026-10-30: written as `docs/step5_tables.md` before it was built (design, dated 2026-10-29); moved to this spec with status `implemented`.
* 2026-10-29: design written. It had `table_new(store, initial, maximum)`, `export_funcref`, `call_ref`, host functions as members and the order 5a, 5b, 5c.
* 2026-10-30, 5a: built `wasmext_table.h` (a table of the store: `wasmext_tab_new/get/set/grow/size/record`; the same four operations on a table an instance exports: `wasmext_instance_table_*`).
  In `wasmext_instance.h`: the records and the import of a table, `wasmext_instance_funcref` and `wasmext_funcref`, and the take-back of the functions a failed instantiation left in a table it imports.
  In the binding: the table imports and exports and the filler of the funcref of each exported function.
  `tests/c/test_tables.c` (five real modules; ASan/UBSan and TSan; the mutations of the take-back, the checks of the store, of the owner and of the bounds, the lock, and the limits of an import were caught).
* 2026-10-30, what differs from the design:
  * a funcref value carries its `store` and the `owner` handle, and `set` accepts it only if the pointer of its instance is a member of the store under that very handle (a forged value is refused, not trusted);
  * `get` answers `WASMEXT_TAB_STALE` for an element no member stands behind;
  * the lock is the table's own (an instance's `pin_mutex` for an exported one);
  * a write by WebAssembly code is not synchronised with the host's (the threads proposal, step 11).
* 2026-10-30, 5b-1: built `wasmext_instance_call_ref(instance, funcref, args, results)` (item 5 of the design).
  The binding got `ref_types`, made from the type section. The adapters of these types are always the reentrant ones.
  Errors: `WASMEXT_INST_UNDECLARED_TYPE`, the trap `WASM_RT_TRAP_NULL_REF`, `WASMEXT_TAB_WRONG_STORE`.
* 2026-10-30, 5b-2: built `funcref` in a signature (item 6): arguments, results, `call_ref` and imports as in Semantics.
  The typed shape refuses it (`WASMEXT_INST_UNSUPPORTED`), `export_record` and `bind_export` refuse a function with one. `externref` in a signature was still refused (step 6, S0006).
  The check "Core without Python" now compiles the static headers of layer 1 strictly (`.github/scripts/layer1_check.c`, gcc, clang, MinGW, MSVC); before, only the old glue and the headers of fusedwasi were.
* 2026-10-30, 5c: built a function of the host as an element of a table (item 7): `wasmext_instance_host_funcref` and `wasmext_host_func`, as in Semantics.
  The lock of the host (`wasmext_rlock`) is the business of the function itself, as for an import (not done).
* 2026-10-30: the owner accepted the four open points (above) and the order 5a, 5b, 5c.
* 2026-10-30: the kind of a member (`WASMEXT_KIND_*`) was added to the registry after review of step 6 (S0006); `wasmext_funcref_member_` finds an instance or a host function only by kind.
* 2026-10-30: 8a-2 (S0008): a function with a funcref or an externref in its signature has a record, a shim and is linked; typed host functions with references stay refused.
