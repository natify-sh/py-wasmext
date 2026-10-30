---
title: Tags and exceptions
kind: spec
id: S0007
status: implemented
superseded_by:
related: []
owner: maintainer
updated: 2026-10-30
---

# S0007 Tags and exceptions

## Summary
This is step 7 of layer 1 (see `docs/layers.md`). It sits on top of steps 3 to 6.
A tag that a module exports can be imported by another instance of the store, so an exception thrown by one is caught by the other.
The host can read an exception that nothing caught, and a host function can throw one.
The part across separately built artifacts is for step 8.

Status: built 2026-10-30 (7a, 7b, 7c in one commit; 7d, the repairs of the build in the tests and the table of the tags, in the next).
The owner accepted the plan of 2026-10-30: a tag of a module is shared with another instance of the store; the host reads an exception that nothing caught; a host function throws; the part across separately built artifacts is for step 8.

### What there is (wasm2c)
* A tag is `wasm_rt_tag_t`, a pointer. Two tags are the same if the pointers are equal.
* A module that exports a tag has a global `const wasm_rt_tag_t w2c_<p>_<name> = &<its private placeholder>`.
* A module that imports a tag has no slot for it. It reads a global `extern const wasm_rt_tag_t w2c_<module>_<name>` whenever it throws or catches.
* A tag that is neither exported nor imported is `static` and cannot be named from outside.
* The payload of an exception is the value itself for a tag with one value, and `struct wasm_multi_<codes>` for more (natural layout).
* `wasm_rt_load_exception(tag, size, bytes)` and `wasm_rt_throw()` throw.
* The runtime keeps the active exception (tag, size, at most 256 bytes) for the thread: `wasm_rt_exception_tag/size/exception`.
* A throw with no `catch` in the module goes to the unwind target of the entry, and the call answers `WASM_RT_TRAP_UNCAUGHT_EXCEPTION`.
* A function that another instance calls through a link (a typed shim) is entered with its own entry, so an exception that it does not catch comes back as a trap, not as an exception.
* An exception unwinds into the caller only where the code runs on the caller's native stack: a function reached through a shared table (steps 5 and 6). That is the case tags are for.

## Goals / Non-goals
* Goals:
  * 7a: a tag shared between instances of a store (`WASMEXT_TAG` is a kind of record; an import is bound to the record of an export).
  * 7b: the host reads the exception that nothing caught: tag, place in the binding, values, bytes.
  * 7c: a host function throws an exception that a `catch` of the module can catch.
  * 7d: the C tests of steps 3 to 7 build what the product builds; the binding knows every tag of the module, also the ones the module keeps to itself.
* Non-goals (the limits of this step):
  * One tag per import name per process. An importer reads a symbol, so the program holds one tag for each import name.
  * No tag made by the host (not a tag of a module) in this step. Done in step 8a-3 (D39): it belongs to the store.
  * `exnref` (the exception as a value), `throw_ref`, `catch_ref`: not carried. `exnref` is step 12 of the order, "not before a real module that uses it exists".
  * Exceptions across separately built artifacts: step 8.
  * A reference among the values of a tag: the payload is not read or made (`decode` and `encode` are NULL).

## Interface

### Record of a tag (`wasmext_glue.h`)
* `enum { WASMEXT_FUNC = 0, WASMEXT_TABLE = 1, WASMEXT_MEMORY = 2, WASMEXT_GLOBAL = 3, WASMEXT_TAG = 4 };`
* The record of an exported tag (`wasmext_export`) has `kind` = `WASMEXT_TAG`.
  * `address` = its identity (the value of the global: the `wasm_rt_tag_t` that `throw` and `catch` compare).
  * `signature` = the types of its values then `>`, as a function says its parameters: `ij>` for a tag of an i32 and an i64.
* `flags` of the record: bit 0 global mutable, bit 1 memory 64-bit, bit 2 guard pages, bit 3 callable with no Python, bit 4 function may be put in a table, bit 5 table elements are `externref` (S0006). A tag record sets no flag.
* `wasmext_cell_set_once(void *volatile *slot, void *value)` in `wasmext_store.h`: an atomic compare-and-set of a process-wide cell. It answers 1 if the cell was NULL (now `value`) or was `value` already, else 0.

### Linking and the binding (`wasmext_instance.h`)
```c
int wasmext_instance_export_record(wasmext_instance *i, uint32_t index, void *owner, wasmext_export *out);
int wasmext_instance_bind_export(wasmext_instance *i, uint32_t import, const wasmext_export *e);
```
* `export_record` of a tag needs `address` and `signature` in the export binding, else `WASMEXT_INST_UNSUPPORTED`.
* `bind_export` of a tag import checks the kind and the signature. `WASMEXT_INST_LINK_FAILED` with the reason in the text of the store (`wasmext_store_error`; the text names the import and both signatures).

```c
typedef struct {
    const void *(*identity)(void *instance);
    wasmext_functype type;       /* the types of the values */
    uint32_t size;               /* the size of the payload that wasm2c keeps */
    void (*decode)(const void *payload, wasmext_val *out);
    int  (*encode)(const wasmext_val *values, void *payload);   /* decode and encode: NULL for a reference among the values */
} wasmext_tag_binding;
```
`wasmext_binding` has `const wasmext_tag_binding *tags; uint32_t n_tags;`.
`void **(*ref_slot)(void *instance, uint32_t import)` gives, for a tag import, the address of the global the module reads.
The descriptor kind is `WASMEXT_DESC_TAG` (import and export tables).

### Reading an exception (7b)
```c
#define WASMEXT_EXC_VALUES 16
#define WASMEXT_EXC_RAW 256
typedef struct {
    const void *tag;
    int tag_index;               /* place in the binding's tags; -1 if the module does not know it */
    uint32_t n_values;
    wasmext_val values[WASMEXT_EXC_VALUES];
    uint32_t size;               /* bytes, at most WASMEXT_EXC_RAW */
    uint8_t raw[WASMEXT_EXC_RAW];
} wasmext_exception;
int wasmext_instance_exception(const wasmext_instance *i, wasmext_exception *out);
```
`WASMEXT_INST_NO_EXCEPTION` (-11) when this thread has had none.

### Throwing from a host function (7c)
```c
#define WASMEXT_HOST_THROW 0x10000
int wasmext_instance_throw(const wasmext_instance *i, const void *tag, const wasmext_val *values, uint32_t n);
extern WASM_RT_THREAD_LOCAL struct wasmext_pending_throw_s_ { const void *tag; uint32_t size; uint8_t bytes[WASMEXT_EXC_RAW]; } wasmext_pending_throw_;
WASM_RT_NO_RETURN static inline void wasmext_throw_pending_(void);
```
* `wasmext_pending_throw_` is defined with the other thread state under `WASMEXT_DEFINE_THREAD_STATE`.
* The host function answers `WASMEXT_HOST_THROW` (`*trapped = WASMEXT_HOST_THROW` in the typed shape).
* `wasmext_throw_pending_` is called by the generated function of an import, which is also the trampoline of a host function in a table.
* Answers: `WASMEXT_INST_UNDECLARED_TYPE` (-10), `WASMEXT_INST_BAD_ARGS` (-2), `WASMEXT_TRAP_HOST`.

### What `_binding.py` emits
* `{last}_tags[]`: a `wasmext_tag_binding` for every tag of the module, in the order of its index space. First the imported ones, then the ones it defines, exported or not.
  * Exported tag: `{last}_tag{n}` returns `(void *)w2c_<prefix>_<name>`.
  * Imported tag: `{last}_tagi{k}` returns the global that was linked.
  * Defined tag: `{last}_tagd{j}` returns `wasmext_tags_<prefix>[j]`.
* `extern const wasm_rt_tag_t wasmext_tags_<prefix>[N];` is declared by the binding. `_export_tags` of `_natify.py` adds this table to the C of wasm2c, since wasm2c makes the tags `static`. A build without that repair does not link: the repair is part of the build, as the others are.
* `_tag_payload` makes, for a signature of values, a struct of the natural layout and the functions `<name>_dec` and `<name>_enc`. None when a reference is among the values.
* For a tag import: the binding defines the global the module reads. The header declares it `const`; the generated file renames the declaration (`#define <c> wasmext_declared_<c>`, then `#undef`), defines `wasm_rt_tag_t <c>;`, and `{last}_ref_slot` returns its address.
* The export row of a tag is `{0, 0, {last}_tag{n}, 0, "<signature>", 0}`.
* `_slot_call` emits `if (trapped == WASMEXT_HOST_THROW) wasmext_throw_pending_();` (typed shape) and `if (rc == WASMEXT_HOST_THROW) wasmext_throw_pending_();` (uniform shape).
* Build repairs the tests now use: `_repair_imported_elements`, `_portable`, `_repair_tail_calls`, `_export_tags`; the runtime through `_RUNTIME_WRAPPERS` (see Semantics, 7d).

## Semantics

### 7a: a tag shared between instances
* `bind_export` accepts the record of an exported tag for a tag import if the kind and the signature fit. A mismatch is `WASMEXT_INST_LINK_FAILED`.
* The import cannot be a slot of the instance. So the binding defines the global that the module reads, and the core writes the tag of the exporter into it once, for the whole program (`wasmext_cell_set_once`).
  Every instance of the module, in any store, reads the same tag.
* All the instances of one exporter have the same tag, so the usual links agree.
  A link to another tag is refused with `WASMEXT_INST_TAG_HELD` (since 8a-3; it was `WASMEXT_INST_LINK_FAILED`) and the reason (`is a tag that this program has linked to another tag already (wasm2c reads an imported tag from a global: one for the process)`), never mixed.
* Because it is a symbol, two modules of one program that import the same name from the same module collide at link time (as the imported functions did before).
* An import that is not bound is not run, whatever the global holds.
* Identity, not structure: a tag of another module with the same signature is a different tag and does not catch.
* Instances are linked inside one store (`bind_export` refuses a record of another store).

### 7b: the exception that nothing caught
* `wasmext_instance_exception` fills the tag (the identity a record gives), `tag_index` (which of the tags the module exports, imports or defines it is; -1 for one it does not know), the values (when the tag is known, none of them is a reference, the size fits and `n_params <= 16`), and the bytes (`size`, up to 256).
* It reads the state of the calling thread. Ask right after the call that answered `WASM_RT_TRAP_UNCAUGHT_EXCEPTION`.
* A later throw replaces the exception. A caught one stays there until then.
* The payload buffer of the runtime is not aligned for the struct, so both reading and making go through `memcpy` (UBSan found this).

### 7c: a host function throws
* `wasmext_instance_throw` makes the payload of a tag that the module exports or imports and keeps it for the thread. A tag the module neither exports nor imports is `WASMEXT_INST_UNDECLARED_TYPE`: the AOT rule, a payload is made by code the binding has for the tags the module can see.
  Since 7d the tags a module defines and keeps to itself are in the binding too, so the host can throw such a tag by the identity it learned from an exception.
* The wrong number or types of values, or a reference among them, is `WASMEXT_INST_BAD_ARGS`.
* The host function then answers `WASMEXT_HOST_THROW`. The generated function of the import loads the exception and calls `wasm_rt_throw()`.
  A `catch` in the module catches it. Where none does, the call ends as in 7b (`WASM_RT_TRAP_UNCAUGHT_EXCEPTION`).
* `WASMEXT_HOST_THROW` with nothing made is a failure of the host (`WASMEXT_TRAP_HOST`).
* Make the exception just before answering: a request that is answered with something else is dropped by the next one.
* The record is per thread.

### 7d: the tests build what the product builds
* The C tests of steps 3 to 7 had built the raw output of wasm2c and the raw runtime. The product builds the output through `_repair_imported_elements`, `_portable`, `_repair_tail_calls` and `_export_tags`.
  It builds the runtime through the wrappers of `_RUNTIME_WRAPPERS`: the allocation of a memory traps with `WASMEXT_TRAP_NO_MEMORY` and does not `abort()`; the trap handler; the exceptions.
* The fixture `build` of `tests/test_instance_core.py` now does the same. It uses those very functions, not copies. All the tests of steps 3 to 7 passed on it unchanged, ASan, UBSan and TSan included.
* A memory that cannot be had: `instantiate` answers `NO_MEMORY`. With the raw runtime the process aborts, so `test_nomemory.c` does test the wrapper.
* An exception of a tag the module keeps to itself is read with its values (`tag_index` is its place).

## Test plan
Commands:
```
uv run pytest tests/test_instance_core.py -q -k "tags or cannot_be_had"
```
Expected: 3 passed (`test_tags_shared_between_instances`, `test_tags_under_sanitizers`, `test_a_memory_that_cannot_be_had`).

C files that the tests build:
* `tests/c/test_tags.c`, `test_tags`: a function of `ta` thrown through a shared table is caught by `tb`, which imports the tag; not caught by `tc`, which has a tag of its own with the same signature (identity, not structure);
  the refusals; a second link to another tag; the unbound import; a tag that the module keeps to itself, told by the table of the tags of the build; the exception that nothing caught, with its values; a host function that throws.
  Also under ASan/UBSan (`test_tags_under_sanitizers`).
* `tests/c/test_nomemory.c`: a memory that cannot be had (`NO_MEMORY`; the raw runtime would abort).
* The earlier files (`test_tables.c`, `test_externref.c`, `test_ref_globals.c`) run on the repaired build too.

Mutations that must fail the tests: the old document records no mutation list for step 7. The list below is proposed by the spec writer from the code (not a record of runs):
* the compare of the signature of a tag import;
* the once-only write of the cell (a second link to another tag must be refused);
* the identity compare in `wasmext_instance_exception` and `wasmext_instance_throw`;
* the `memcpy` of the payload (a direct cast of the unaligned buffer is found by UBSan);
* the `wasmext_tags_<prefix>` repair (a build without `_export_tags` must not link);
* the wrapper of the allocation of a memory (the raw runtime makes `test_nomemory.c` abort).
These were not recorded as run; see Open questions.

## Alternatives considered
* A tag made by the host (not a tag of a module).
  Cost: an importer reads a symbol, so the host could give the program only one such tag for each import name.
  Why not: deferred to step 8, which has to settle what a store shared across artifacts is.
* `exnref` (the exception as a value) and `throw_ref`.
  Why not: not carried. The runtime of wasm2c has the type (`wasm_rt_exnref_t`, payload inline), but the parser of the project (`_wasm.py`, `ValType`) does not know it. It needs the parser, the binding and a real module that uses it. Step 12, not before one exists.
* Exceptions across separately built artifacts.
  Why not: step 8.
* A slot in the instance for an imported tag.
  Why not: wasm2c has no slot; the import is a global that the module reads. The binding defines the global and the core writes it once for the process.
* Mixing two tags for one import name.
  Why not: a link to another tag is refused with the reason, never mixed.
* Keeping the raw build in the C tests.
  Why not: the patches of the build are not incidental. The tests must build what the product builds (7d).

## Open questions
* A tag made by the host, and what a store shared across artifacts is (step 8).
* `exnref`, `throw_ref` and `catch_ref` (step 12).
* One tag per import name per process: is it enough after step 8?
* The mutation checks of step 7 are not recorded in the old document; run and record them.

## Changes
* 2026-10-30: written as `docs/step7_tags.md`; moved to this spec with status `implemented`.
* 2026-10-30: the owner accepted the plan: a tag of a module is shared with another instance of the store; the host reads an exception that nothing caught; a host function throws; the part across separately built artifacts is for step 8.
* 2026-10-30, 7a, 7b, 7c: built in one commit.
  * 7a: `WASMEXT_TAG` as a kind of record, the tag import in `bind_export`, the global defined by the binding, `wasmext_cell_set_once`. Tests: `tests/c/test_tags.c`, `test_tags`.
  * 7b: `wasmext_instance_exception`, `wasmext_exception`, the table of the tags (`wasmext_tag_binding`: identity, types, the size of the payload, the function that reads it, the one that makes it).
  * 7c: `wasmext_instance_throw`, `WASMEXT_HOST_THROW`, `wasmext_pending_throw_`.
* 2026-10-30, 7d: added after the owner pointed out that the patches of the build are not incidental.
  The fixture of `tests/test_instance_core.py` builds through the repairs and the wrappers of the product. New: `tests/c/test_nomemory.c`.
  The binding has every tag of the module, in the order of its index space (the imported ones, then the ones it defines, exported or not, read from `wasmext_tags_<prefix>`).
  The table is added to the C of wasm2c by `_export_tags`. So an exception of a tag the module keeps to itself is read with its values, and the host can throw it by the identity it learned from the exception.
* 2026-10-30, 8a-3 (S0008, D39): a tag made by the host (`wasmext_tag_new`) belongs to the store and is imported through the same `bind_export` of kind `WASMEXT_TAG`; the cell of D34 is cleared (compare-and-swap) when that store closes, and a second tag for a name that a live store holds is `WASMEXT_INST_TAG_HELD` with the reason. The tag of an exporting instance needs no clearing: its identity is static data of the module's artifact. "One tag per import name per process" stands while a store holds it.
* 2026-10-30, 8a-3 review: a tag import that holds another tag already is `WASMEXT_INST_TAG_HELD` (-12) from `bind_export`, for a host tag and for the tag of a module alike (the module case was `WASMEXT_INST_LINK_FAILED`); the cell is set under the lock of the store; the record of a closed store is `WASMEXT_TRAP_CLOSED`.
