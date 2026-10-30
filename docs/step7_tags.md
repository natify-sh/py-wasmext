# Step 7 of layer 1: tags and exceptions

Status: **built 2026-10-30** (7a, 7b, 7c in one commit). On top of steps 3 to 6. The owner accepted the plan of 2026-10-30: a tag of a module is shared with another instance of the store; the host reads an exception that nothing caught; a host function throws; the part across separately built artifacts is for step 8.

## What there is (wasm2c)

- A tag is `wasm_rt_tag_t`, a pointer: two tags are the same if the pointers are equal. A module that **exports** a tag has a global `const wasm_rt_tag_t w2c_<p>_<name> = &<its private placeholder>`; one that **imports** a tag has no slot for it: it reads a global `extern const wasm_rt_tag_t w2c_<module>_<name>` whenever it throws or catches. A tag that is neither exported nor imported is `static` and cannot be named from outside.
- The payload of an exception is the value itself for a tag with one value, and `struct wasm_multi_<codes>` for more (natural layout); `wasm_rt_load_exception(tag, size, bytes)` and `wasm_rt_throw()` throw; the runtime keeps the active exception (tag, size, at most 256 bytes) **for the thread**: `wasm_rt_exception_tag/size/exception`. A throw with no `catch` in the module goes to the unwind target of the entry and the call answers `WASM_RT_TRAP_UNCAUGHT_EXCEPTION`.
- A function that another instance calls through a **link** (a typed shim) is entered with its own entry, so an exception that it does not catch comes back as a trap, not as an exception. An exception unwinds into the caller only where the code runs on the caller's native stack: a function reached through a **shared table** (steps 5, 6). That is the case tags are for.

## 7a: a tag shared between instances

`WASMEXT_TAG` is a kind of record. The record of an exported tag has `address` = its identity (the value of the global) and `signature` = the types of its values then `>` (`ij>`), as a function says its parameters. `wasmext_instance_bind_export` accepts it for a tag import if the kind and the signature fit (the text of the refusal names the import and both signatures). The import cannot be a slot of the instance, so **the binding defines the global that the module reads** (the header declares it `const`; the generated file renames the declaration, defines the variable, and `ref_slot` gives its address), and the core writes the tag of the exporter into it **once, for the whole program** (`wasmext_cell_set_once`, an atomic compare-and-set): every instance of the module, in any store, reads the same tag. All the instances of one exporter have the same tag, so the usual links agree; a link to **another** tag is refused with the reason, never mixed. Because it is a symbol, two modules of one program that import the same name from the same module collide at link time (as the imported functions did before). An import that is not bound is not run, whatever the global holds.

Tests: `tests/c/test_tags.c`, `test_tags`: a function of `ta` thrown through a shared table is caught by `tb`, which imports the tag; not caught by `tc`, which has a tag of its own with the same signature (identity, not structure); the refusals; a second link to another tag; the unbound import.

## 7b: the exception that nothing caught

`wasmext_instance_exception(instance, &ex)`: the tag (the identity a record gives), `tag_index` (which of the tags the module exports or imports it is; -1 for one it does not know), the values when the tag is known and none of them is a reference, and the bytes (`size`, up to 256). It reads the state of the **calling thread**, to be asked right after the call that answered `WASM_RT_TRAP_UNCAUGHT_EXCEPTION`; a later throw replaces it and a caught one stays there until then; `WASMEXT_INST_NO_EXCEPTION` for a thread that has had none. The binding has the table of the tags (`wasmext_tag_binding`: identity, types, the size of the payload, the function that reads it, the one that makes it). The payload buffer of the runtime is not aligned for the struct, so both are done through `memcpy` (UBSan found this).

## 7c: a host function throws

`wasmext_instance_throw(instance, tag, values, n)` makes the payload of a tag that the module exports or imports (else `WASMEXT_INST_UNDECLARED_TYPE`: the AOT rule, a payload is made by code the binding has for the tags the module can see; the wrong number or types of values, or a reference among them, is `WASMEXT_INST_BAD_ARGS`) and keeps it for the thread; the host function then answers **`WASMEXT_HOST_THROW`** (`*trapped = WASMEXT_HOST_THROW` in the typed shape). The generated function of the import, which is also the trampoline of a host function in a table, loads the exception and calls `wasm_rt_throw()`: a `catch` in the module catches it, and where none does the call ends as in 7b. `WASMEXT_HOST_THROW` with nothing made is a failure of the host (`WASMEXT_TRAP_HOST`); make the exception just before answering (a request that is answered with something else is dropped by the next one). The record is per thread (`wasmext_pending_throw_`, defined with the other thread state under `WASMEXT_DEFINE_THREAD_STATE`).

## Not done, and why

- A tag **made by the host** (not a tag of a module): an importer reads a symbol, so the host could give the program only one such tag for each import name. It waits for step 8, which has to settle what a store shared across artifacts is.
- Exceptions of unexported tags are told by the bytes only (the tag stays inside the module; the old glue patched the C of wasm2c to see them, and the new binding patches nothing).
- `exnref` (the exception as a value) and `throw_ref`: not carried.
- Across artifacts: step 8.
