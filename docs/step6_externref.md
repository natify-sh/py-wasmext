# Step 6 of layer 1: `externref` (and the globals of both kinds of reference)

Status: **6a, 6b and 6c built 2026-10-30; step 6 is complete;** written 2026-10-30; the owner accepted the order of [layers.md](layers.md) and the globals of `funcref` and `externref` in this step (they were refused since step 3 and step 5 did not touch them).** On top of steps 3 to 5. Order inside the step, one commit each, CI between: **6a** the value and the signatures, **6b** tables of `externref`, **6c** globals of `funcref` and `externref`.

## What there is

- **wasm2c.** `wasm_rt_externref_t` is `void *` (null is `NULL`); `wasm_rt_externref_table_t` has the head of the funcref table (`data`, `max_size`, `size`); a global of `externref` is a `wasm_rt_externref_t`, of `funcref` a `wasm_rt_funcref_t` (four words); several results of `externref` come in `struct wasm_multi_e...`; the runtime has `wasm_rt_allocate/free/grow_externref_table`.
- **The core refused** `externref` everywhere (a signature, a table, a global) and a global of `funcref` (steps 3 and 5).

## The decision: the store owns what it is given

The host gives the store a value it wants WebAssembly to hold (in Python: any object). **`wasmext_extern_new(store, user, release, &ref)`** makes a record `{ user, release, store }`, a member of the store under its own pointer (the registry of step 4), and the pointer is the `externref` that WebAssembly sees. WebAssembly never reads it; it only copies it (locals, tables, globals, arguments, results). The store keeps every record **until it is closed**, and then calls `release(user)` once (in Python: the decref). This is Wasmtime's model (the value lives in the store) without its collector; **the collector is step 9**: until then a long-lived store that is given very many values holds them all, and the way out is to close the store (an explicit `with store:`), which the front ends already require.

Why the host cannot count the references: WebAssembly copies an `externref` where the host does not see (locals, a table, a global), so only a scan of what the store holds can say that nobody holds a value, and that is the collector.

## What crosses, and the checks

- A value goes **in** (an argument of a call, an answer of a host function, a write to a table or a global, `bind_global_value`): its pointer must be **a member of this store** (`wasmext_store_find`, which does not read the pointer), else `WASMEXT_TAB_WRONG_STORE`: a value of another store, or one that this API did not make, is refused, never trusted. A null (`NULL`) is always acceptable.
- A value comes **out** (a result, a read from a table or a global): WebAssembly can give back only what it was given, so it is a member already and is not checked again. The host reads its `user` with `wasmext_extern_user(ref)`.
- In `wasmext_val` the type is 0x6F and `as.ref` is the pointer to the record itself (no storage of the caller's, unlike a `funcref` result, which is a struct).
- A function with an `externref` in its signature has no typed shape (`wasmext_instance_bind_typed` refuses it), and no record for linking between instances, as the functions with a `funcref` (step 8); a host function in a table (5c) and `call_ref` (5b) carry it.

## 6b: tables

`wasmext_tab` gets the element type (0x70 or 0x6F): `wasmext_tab_new` takes it, `get`/`set` of an `externref` table take and give the pointer of the record. The export record of a table says its element type (bit 5 of `flags`), and an import is refused when the type differs (as the limits are). The operations on a table that an instance exports, `wasmext_instance_table_*`, do the same by the type in the descriptor. The binding carries imports and exports of `externref` tables.

## 6c: globals of references

`wasmext_instance_global_get/set`, the record of an exported global, `bind_export` of a global and `bind_global_value` carry the types 0x70 and 0x6F: the value is a `wasmext_funcref` (the caller points `as.ref` at its own for a read, and at the one to write) or the `externref` pointer; a write is checked as any value that goes in. The cell of an imported immutable global that the host gives is as big as a `funcref` (32 bytes).

## 6a built

`wasmext_extern_new/user`, `wasmext_extern_check_`, `wasmext_extern_result_` in `wasmext_instance.h`; the binding carries `externref` in the signatures of exports, imports, `call_ref` and the host functions of a table (the adapters, the forwarders and the trampolines; the tables of C types, letters of multi results and types of wasm2c in `_binding.py` have the `externref` that the old glue lacks). A `wasmext_val` of type 0x6F has the pointer to the record in `as.ref`. `tests/c/test_externref.c` (ASan/UBSan, TSan; mutations of the membership check, of the check of a host answer and of its type, of the release, of the check of an argument, of the refusal of the typed shape, of the adapter and of the registration are caught).

## 6b built

`wasmext_tab_new(store, elem, initial, maximum, error)` takes the element type (0x70 or 0x6F; the signature changed from 5a, the ABI is free in alpha); `wasmext_tab_get_extern/set_extern` and, for a table an instance exports, `wasmext_instance_table_get_extern/set_extern`; `grow` and `size` follow the element type; the operations of the other kind answer `WASMEXT_TAB_WRONG_ELEM`. The record of a table says its element type in bit 5 of `flags`, and `bind_export` refuses a table of the other type (and keeps the limits as before). The take-back of a failed start is for funcref tables only (the elements of an externref table are not functions of the instance). The binding carries imports of `externref` tables. `tests/c/test_externref.c`, `test_tables`: the table a module exports, shared with an importer, a table of the host, what goes in, the other element type, the limits, the failed start; mutations of the check of what goes in, of the bounds, of the element type of each operation, of the flag of the record, of the size and growth, and (under LeakSanitizer and ASan) of the free at the close and of the take-back are caught.

## 6c built

`wasmext_instance_global_get/set`, the record of an exported global, `bind_export` of a global (the type byte is compared as for the numbers) and `wasmext_instance_bind_global_value` carry 0x70 and 0x6F. A read of a funcref global is written where the caller points `out->as.ref` (NULL is `WASMEXT_INST_BAD_ARGS`), with the store and the handle of its instance; a read of an externref global gives the reference. A write, and the value the host gives an immutable import, are checked as any value that goes in (`WASMEXT_TAB_WRONG_STORE`). The cell of such a value is 32 bytes. The take-back of a failed start now also empties a shared **mutable global of funcref** into which the start function put a function of its own (as it empties the elements of a table). The binding carries imports of globals of both kinds. `tests/c/test_ref_globals.c` (ASan/UBSan; mutations of each check of what goes in, of the check that the caller gave a place to read into, of the owner of the funcref read, of the take-back from a global and of the size of the cell are caught; one of them only by a sanitizer, one by a crash). `FEATURES.md` and the old glue are untouched: the old glue still refuses them, and goes with its step.
