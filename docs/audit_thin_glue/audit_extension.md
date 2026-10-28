> Measurement of 2026-10-28. Its plan (moving pieces one at a time) is replaced by [../layers.md](../layers.md); the numbers and the lists of what each front end must provide stay valid.

# Audit of the extension side (generated `<name>_py.c`) against the former thin_glue note

Read-only audit of `/home/user/py-wasmext` (branch dev). Nothing in the repo was changed. Scratch output (extra generated modules, scripts) is in `/tmp/claude-0/audit/` (`v/` = extra natify builds, `tally.py` = the line counter used below).

## 0. What I read, what I ran, how the numbers were made

Read in full: `the former thin_glue note`, `docs/owners_registry.md` (first 50 lines = all of it), `/tmp/claude-0/glue/c_rich/rich/rich_py.c` (all 1288 lines), `rich_glue.h` (the typed core part), `rich_api.h` (the public C API), `src/wasmext/c/wasmext_glue.h` lines 105-215, and the template side of `_gen.py` by grep/sample (the line ranges below come from grepping the `add("static ...")` definitions; the bodies I read are the ones visible in the generated output).

Generated and read (parts): extra modules built with `uv run wasmext natify -q -f` from tests/data and /tmp/claude-0/glue:

| Build | Shows | `*_py.c` lines |
| --- | --- | ---: |
| add (`c_add`), rich (`c_rich`), tbl (`c_tbl`) | the three samples asked for | 409 / 1288 / 1108 |
| add `--share-tables` | what a table-sharing module adds (Table, Function, writers) | 937 |
| rich `--share-tables` | same as rich (already shares: it has a funcref table) | 1288 |
| kitchen_sink.wasm | memory/global imports, multi-result, v128, start function, exported table/global/memory | 1438 |
| exceptions.wat | tags: `raise_uncaught` | 522 |
| wasi_hello.wasm `--host wasm32-wasip1` | WASI store, `Host` object, `host_callN` | 952 |
| wasi2_probe.wasm `--host wasm32-wasip2` | WASI 0.2 store, 4 import groups | 1359 |
| probe.wasm (`b_extension/probe`) | 17 imports of `wasi_snapshot_preview1` with host `wasm32` (so every one is a Python import) | 1999 |
| fr.wat (mine) | `funcref` parameter and result: `funcref_arg`, `funcref_result`, `refs` | 1049 |
| ti.wat (mine) | an imported table: `keep_alive`, `scrub_tables` | 1120 |

Not run: the test-suite (I was told read-only; `uv run` was used only for `natify`). Not read: the bodies of `wasi_python.h`/`wasi2_python.h` (I read their header comment and the list of their functions), `rich_shared.c`, `_shared.py`, `_ctypes_gen.py`, `_natify.py`. So every statement about the ctypes wrapper or the shared library below is from `rich_api.h` and `the former thin_glue note`, not from their code.

How the line counts were made (`/tmp/claude-0/audit/tally.py`): the generated file is cut into top-level units (a function, a struct, a method table, a comment block); each unit counted by its non-blank lines (blank lines are 38 / 101 / 97 in add / rich / tbl). A unit gets ONE primary category by name. For eleven mixed functions I split the unit by a fraction that I measured by hand-reading rich (`Instance_new`, `Table_set`, `Table_get`, `table_find_function`, `Store_close`, `export_ref`, `Memory_getbuffer`, `Memory_releasebuffer`, `Table_new`, `wasmext_py_thread_setup_`, `attach_traps`). The fractions are estimates (a line with `PyErr_SetString(...)` inside a check counts as the check, i.e. LOGIC). The totals are therefore good to a few percent, not exact; section 3 gives both the "primary only" and the "split" figures so the effect of the estimate can be seen.

## 1. Findings in one screen

1. The extension is not only a binding. Of 1187 non-blank lines of `rich_py.c`, the split estimate gives LOGIC 174 (15 %), and of those only about 38 lines are in functions with no `Py*` token at all and can move as they are. The other ~136 LOGIC lines are the checks and decisions of linking, `Table.set/get`, store close, buffer pinning, written with Python calls in the middle.
2. Most of the generated bulk is CONVERT + PYLIFE + BOILERPLATE (about 80 %), which is what a thin front end should be. So the target is realistic: the Python-API-free part is the "descriptor" of the module (exports, imports, types), and all decisions can become C functions that return a code plus a message (the pattern `wasmext_link_fail(msg, cap, text)` and `<name>_link_func0` already exist and are the model).
3. Repeated copies inside the extension itself (before any question of the ctypes wrapper):
   - `Instance_new` repeats a 44-line block for EVERY function import (the lookup, `as_export_ref`, the "method of an instance with `__exports__`" search, link or callable). In `probe` this is 776 of 1999 lines (17 imports); in wasi2 324 lines.
   - `raise_trap_code` repeats a 13-line `_pending` loop once per import group: 68 lines in wasi2 (4 groups) against 26 for one group.
   - The check "export record is OK, is a FUNC, has a funcref, has flag 16" is written in `Table_set` and again in `funcref_arg`, and a third time in the same spirit in `table_find_function`.
   - The "ref or method of an instance" search is written in `Instance_new` (per import) and in `function_holder`.
   - `raise_trap_code` and `raise_foreign_trap` are two copies of the trap-code-to-exception table.
   - `Function_call` (switch by type) and `Instance_fN` are the same "convert arguments, call typed core, convert result" code twice.
4. The extension and the ctypes wrapper talk through duck-typed Python attributes, not through a C contract: `__wasmext_ref__`, `__wasmext_keep__`, `__exports__`, `__wasm_caller__`, `_pending` (read in `raise_trap_code` from the foreign owner object), `.obj` of a memoryview. Each is a place where a rule lives in two layers. `_pending` is the clearest: the exception of a host function that failed in ANOTHER instance is parked in a Python attribute of that instance, and the extension reads it by name.
5. The core part that exists and is already plain C: `wasmext_glue.h` (export record `wasmext_export`, `wasmext_table_new/free/grow/export`, `wasmext_function_export`, the traps stack `wasmext_traps*`, `WASMEXT_ENTER_*`), and in the module glue `<name>_glue.h`: `_glue_instantiate/_initialize/_free`, `_glue_funcref`, `_link_func/global/memory/table<N>`, `_call<N>`, `_callref<N>`, `_ref_type`. `<name>_api.h` of the shared library already has a much larger set (tables, funcref copy/same/hash, pin, `export_find`, `link_import<N>`, `store_*`). The extension does not use that set: it re-implements most of it in `_py.c`. That is the direct measure of "two parallel implementations". (Whether the shared library's `.c` can be compiled into the extension is not determined, see section 6.)

## 2. The audit table

Columns: name | approx lines (in `rich_py.c` unless said; `n/a` = not in rich) | category | what it does | needs Python C API? | where it belongs. `_gen.py` ranges are the line ranges of the template that emits the block (approximate at the edges; I grepped the start of each definition and took up to the next one). "Generated function names" are the C names.

Legend for "where": CORE = plain C in the shared core, FRONT = stays in the extension, SPLIT = needs unpicking (the how is given in section 2.3).

### 2.1 Rows

| Block / function (`_gen.py` lines) | Lines (rich) | Category | What it does (one line) | Python C API? | Where |
| --- | ---: | --- | --- | --- | --- |
| file header: `#define WASMEXT_GENERATED_*`, includes, `WASMEXT_PY_THREADS` (915-935) | 1-15 | BOILERPLATE | version/hash macros, `Python.h`, include of `<name>_glue.h` | includes only | FRONT |
| comment block on thread set-up (936-948) | 17-22 | BOILERPLATE | prose | no | FRONT (comment) |
| `wasmext_py_thread_end_` (949-962) | 12 | PYLIFE | capsule destructor kept in the thread-state dict: gives the alternate stack back when the thread ends | yes (`PyCapsule_GetPointer`, `PyThread_get_thread_ident`) | FRONT: it is only the "thread exit hook"; the work it calls (`wasm_rt_free_thread`, flag) is core |
| `wasmext_py_thread_setup_` (963-993) | 28 | LOGIC (60 %) + PYLIFE (40 %) | per-thread runtime set-up (`wasm_rt_init_thread` or `wasmext_stack_limit_init_`, ready flag) and registers the exit hook in the thread dict | yes for the dict/capsule part (9 refs); the first 5 lines and the `WASMEXT_CHAIN` line are plain C | SPLIT: `wasmext_thread_setup()` core returns "needs hook?"; front end only registers the destructor |
| `#ifndef WASMEXT_TRAP_HANDLER` ... `void wasmext_trap_rich(code) { wasmext_traps_->trap(code); }` (995-1008) | 65-69 | LOGIC | the function the runtime calls for a trap: goes to the innermost entry | no | CORE as is |
| `attach_traps` (1009-1036) | 72-92 | LOGIC (35 %) + PYLIFE (65 %) | the entries-stack is shared by all modules of the interpreter: first module publishes `wasmext_traps_own_` in the interpreter dict as a capsule, later ones take it (`wasmext_traps_use`) | yes (16 refs: interpreter dict, capsule, ImportError) | SPLIT: core `wasmext_traps_attach(get, put)` makes the decision; front end gives get/put on the interpreter dict |
| `TrapError`, `LinkError`, `InstanceType`... statics (1038-1066) | 94-98 | BOILERPLATE | type/exception globals | yes | FRONT |
| `StoreObject`, `InstanceObject`, `MemoryObject`, `TableObject` typedefs (1161-1222, `_table_type_c` 3505+) | 100-134 | BOILERPLATE | layout of the Python objects; they hold the core structs (`rich_store st`, `rich_instance core`) plus the PYLIFE fields `store_obj`, `caller`, `weakreflist`, `writers`, `hold0.{fn,lo}`, `mem_pins`, `mem_max_pages` | yes | FRONT; but `mem_pins`, `mem_max_pages` are LOGIC state and `hold*`, `writers` are ownership state that belong in the core instance (see C-owners below) |
| `raise_trap_code` (1259-1307) | 137-162 (26) | PYCALLBACK | trap code to Python exception: HOST (exception already set, else find a parked `_pending` exception in each linked foreign owner by `getattr`, else `Trap`), CLOSED -> ValueError, NO_MEMORY -> MemoryError, else `Trap(wasm_rt_strerror)`; wasi builds also read `guest.exited`, `signalled`, `p2_message` | yes (20 refs) | SPLIT: the decision "which of these is it" (and the text) is LOGIC and is the same in every front end; creating the exception object is FRONT |
| `raise_trap` (1308-1312) | 164-167 | PYCALLBACK | guarantees an exception exists after a trap | yes | FRONT |
| `raise_uncaught` (1226-1258; only with tags) | n/a (ex: 26) | PYCALLBACK | builds `UncaughtExceptionError(tag, values)` from the tag payload via `<name>_tag_of/_tag_values` (core) | yes (25 refs) | FRONT (values come from core as `wasmext_value[]`) |
| `raise_foreign_trap` (3053+, in `_function_type_c`) | 577-586 | PYCALLBACK | the same table as `raise_trap_code` for a function of another module (no wasi cases; adds UNCAUGHT text) | yes | SPLIT with `raise_trap_code` into one core `wasmext_trap_describe(code, flags, info)` + one FRONT `raise(info)` |
| `py_importN` family (1356-1397) | 169-173 (5-10 each; 17 copies in probe = 170) | PYCALLBACK | trampoline of an import: converts C args to a Python tuple, calls the callable, converts result back, sets `*trapped=HOST` on exception | yes (6 refs each) | FRONT (CONVERT+call), but the one-per-signature copies can be one `py_import_dyn(user, wasmext_value*, n, ..)` driven by a type table (see C-call) |
| `lookup_import` (1399-1431) | 175-205 (31) | CONVERT | `imports[module][field]`; a shelf with `__exports__` gives its exports; LinkError for missing / not callable | yes (22 refs) | FRONT (how a Python mapping presents imports). The error texts are the same ones the ctypes wrapper has: take them from core descriptors |
| `store_make`, `Store_new` (1432-1479) | 208-220 | BOILERPLATE (rich) / CONVERT in wasi builds | alloc Store; with wasi: parse `wasi=` config, `wasmext_wasi2_new`, open preopens, raise OSError | yes | FRONT (config parsing is `wasi_python.h`, CONVERT) |
| `Store_traverse/clear` (1480-1497) | 222-230 | PYLIFE | GC support; with wasi visits the config objects | yes | FRONT |
| `store_release` (1498-1508) | 233-235 (wasi: 5) | LOGIC | let the host go once (`fusedwasi_p2_free`, drop config) | none in the core call; wasi build also calls `wasmext_wasi2_free` (Py) | SPLIT: core `store_release_core`; Python config drop FRONT |
| `Store_close` (1509-1521) | 237-246 | LOGIC (60 %) + CONVERT | idempotent close; refuse when `st.active`; sets `closed` | yes only for the 2 error lines | SPLIT: core `wasmext_store_close(st)` returns 0/1 (exists as `rich_store_close` in the shared API) |
| `Store_enter/exit/closed` (1522-1538) | 248-259 | BOILERPLATE | context manager protocol, `closed` getter | yes | FRONT |
| `Store_runtime` (1539-1556) | 261-275 | CONVERT | builds `types.SimpleNamespace(name, abi, fingerprint)` from core constants | yes (16 refs) | FRONT (data from `rich_abi()/rich_runtime()` of the core) |
| `Store_dealloc` (1557-1566) | 277-285 | PYLIFE | untrack, weakrefs, clear, `store_release` if not closed, free | yes | FRONT |
| `Instance_traverse/clear/dealloc` (1567-1614) | 287-314 | PYLIFE | GC visit/clear of `store_obj`, `caller`, `hold*.fn/lo`, `writers`; dealloc frees the core (`rich_glue_free`) then clears, then drops the store | yes | FRONT, but the list of held owners comes from the core (C-owners) |
| `as_export_ref` (1615-1644, 3-level `__wasmext_ref__` search) | 319-331 | CONVERT | Python object -> capsule of an export record, following `__wasmext_ref__` up to 3 levels | yes | FRONT (it is the unwrap of the Python protocol) |
| `keep_alive` (1645-1651; only if tables are imported; ti.wat 466) | n/a | PYLIFE | calls `owner.__wasmext_keep__(self)` (Python method call) so the exporter keeps the importer | yes | CORE owners list (replaces the Python-level protocol) |
| `function_holder` (3300-3326 `_FUNCTION_HOLDER`) | 336-356 (21) | CONVERT | what stands for the export `v` is: v itself, its `__wasmext_ref__`, or `owner.__exports__[v.__name__]` for a bound method | yes (19 refs) | FRONT (same search as in `Instance_new`: write once) |
| `CallerObject`, `Caller_traverse/clear/dealloc`, `Caller_get_instance/store/memory`, `Caller_getset` (1652-1699) | 359-399 (~40) | PYLIFE (traverse/clear/dealloc, 16 lines), CONVERT (getters, 15), BOILERPLATE (getset 6) | the object a Python callable receives when it has `__wasm_caller__` | yes | FRONT (Python-only API object) |
| `with_caller` (1700-1728) | 401-424 | PYCALLBACK | wraps the callable in `functools.partial(fn, caller)` once, at instance creation | yes (22 refs) | FRONT |
| `Instance_new` (1729-1982) | 426-499 (74) | LOGIC (~18 %) + CONVERT (~43 %) + PYLIFE (~30 %) + PYCALLBACK (~9 %) | arg parse and store check; alloc and keep store; `writers` list; for each import: lookup, find export ref, link (`rich_link_func0`) or install `py_import0` and keep callable; then `glue_instantiate`, `glue_initialize`, raise trap | yes (57 refs of 74 lines) | SPLIT (the big one): see 2.3 |
|   sub-blocks of the template: func imports (1763-1861), global imports (1862-1900), memory imports (1901-1937), table imports (1938-1967), tail (1968-1982) | rich: 452-494 for the one func import | | per import ~44 lines for a function, 22 global, 28 memory, 28 table | | |
| `Instance_fN` family (2246-2285) | 502-511 (10-15 each) | CONVERT | METH_FASTCALL: check nargs, convert each arg, call `<name>_callN(&core.inst, ..., &trapped)`, raise_trap, convert result | yes (6-11 refs) | FRONT; the core call is already one line |
| `export_addressN`, `export_memoryN`, `export_tableN` (2289-2293, 2344-2362) | 513, 522, 524 | LOGIC | `w2c_<name>_<export>(&inst)` for the record `address` | no (but takes `InstanceObject *`) | CORE as is (take `<name>_instance *`) |
| `py_linkN` family (2295-2325) | 515-520 (6 each) | PYCALLBACK | what ANOTHER instance calls when it linked this export: calls typed core; on trap raises the Python exception here and answers `HOST` | calls `raise_trap` (so yes, indirectly) | SPLIT: after `Exception parked in the front end`, core returns `TRAP_HOST`; with a core "pending error" cell the trampoline would be plain C |
| `Instance_keep` (2363-2379) | 527-531 | PYLIFE | `writers.append(other)` for `__wasmext_keep__` | yes | CORE (`wasmext_owners_add`) |
| `export_table[]` (2287-2342, `mapped`) | 533-539 | LOGIC (data) | name, kind, type, flags, address getter, function, signature, index of every export | no | CORE: `<name>_exports[]` in `<name>_glue.h` |
| `export_free` (2380-2384) | 541-544 | PYLIFE | capsule destructor: DECREF owner, free record | yes | FRONT |
| `export_ref` (2385-2409) | 546-565 | LOGIC (55 %) + PYLIFE (45 %) | fill a `wasmext_export` from `export_table[k]` (address, funcref, signature, runtime, seal) and wrap in a capsule that owns a ref to the instance | yes for malloc/INCREF/capsule (9 refs) | SPLIT: core `<name>_export_find(inst, name/k, owner, &rec)` (exists in shared API) fills it; FRONT does capsule |
| `FunctionObject` + `Function_make/traverse/clear/dealloc` (3053-3272) | 568-619 | PYLIFE | the Python object for a funcref element; `keeper` = table or instance that keeps its instance alive | yes | FRONT (object), keeper = core owner |
| `Function_call` (3053-3272) | 621-660 (40) | CONVERT | `switch(type)`: arity check, convert args, `<name>_callrefK(&ref,...)`, raise_foreign_trap, convert result | yes (22 refs) | FRONT, or a generic `wasmext_callref_dyn` on `wasmext_value[]` |
| `Function_signature/name/repr` | 662-713 (~30) | CONVERT | signature tuple of strings; name; repr | yes | FRONT (the signature of type k is from a core table) |
| `Function_ref` | 678-690 | PYLIFE | `__wasmext_ref__` of a Function: `wasmext_function_export` (core) + capsule + INCREF | yes | FRONT capsule; core already fills the record |
| `Function_richcompare`, `Function_hash` | 692-704 | LOGIC | identity of a funcref = `func` and `module_instance` equal; hash from the same | tokens only for return | CORE: `wasmext_funcref_same/hash` (exist as `rich_funcref_same/hash`) |
| `table_u32` (3528-3548) | 737-754 | CONVERT | int -> uint32 with the exact errors | yes | FRONT |
| `Table_new` (3550-3583) | 756-783 | CONVERT (60 %) + LOGIC (20 %) + PYLIFE (20 %) | parse initial/maximum, `initial > maximum`, `wasmext_table_new`, `writers` list | yes | SPLIT: the range check in core (`wasmext_table_check_limits` with message) |
| `Table_traverse/clear/dealloc` | 785-805 | PYLIFE | | yes | FRONT |
| `Table_size/maximum/length/grow` (3606-3632) | 807-835 | CONVERT | read `table->size/max_size`; `grow` builds the ValueError text (two cases) | yes | FRONT, text of the error from core (`wasmext_table_grow` already core) |
| `Table_ref` (3633-3650) | 838-852 | PYLIFE | record + capsule for a table (own: `wasmext_table_export`, instance's: `export_ref`) | yes | FRONT |
| `Table_keep`, `table_writers`, `writers_have` (3383-3392, 3649-3660) | 855-880 | PYLIFE | keep-alive list scan/append: the owner instance keeps its importers, a standalone table its own list | yes | CORE owners (`wasmext_owners_add_unique`) |
| `table_index` | 866-873 | CONVERT (+ LOGIC bound) | index parse + range check | yes | FRONT for the parse; `wasmext_table_index_ok` in core |
| `Table_set` (3345-3398) | 883-934 (52) | LOGIC (~50 %) + PYLIFE (~28 %) + CONVERT (~22 %) | None empties the slot; find the export record behind the object; version check; kind FUNC; funcref non-null; flag 16 ("shares tables") else refuse; add the exporter to `writers` if not there; store the 16-byte funcref | yes (33 refs) | SPLIT: see 2.3 |
| `table_find_function` (3399-3422) | 937-959 | LOGIC (35 %) + CONVERT (65 %) | walk `x.__exports__`, compare each funcref (`func`, `module_instance`) with the element to find the export whose name the Function gets | yes (15 refs: dict walk, getattr) | SPLIT: reverse lookup `funcref -> export name` must be core (registry of module_instance -> exports) |
| `Table_get` (3424-3452) | 962-987 | LOGIC (55 %) + CONVERT + PYLIFE | empty slot -> None; else `Function_make`, then scan `owner` + `writers` to name it | yes (18 refs) | SPLIT with `table_find_function` |
| `table_getters[]`, `Table_of` (3510-3523) | 989-1003 | LOGIC (data) / PYLIFE | handle object for an exported table of an instance (owner + index + pointer) | yes | FRONT object; getter table CORE |
| `Table_methods`, `Table_getset`, `table_slots` | 1005-1030 | BOILERPLATE | | yes | FRONT |
| `export_value` (2413-2419) | 1034-1037 | CONVERT | table export -> `Table` object, others -> capsule | yes | FRONT |
| `Instance_subscript` (2420-2435) | 1040-1053 | CONVERT | `instance['name']` search in `export_table[]` | yes | FRONT (search by name = `<name>_export_find`) |
| `Instance_exports` (2436-2451) | 1056-1069 | CONVERT | the dict `{name: ref}` | yes | FRONT |
| `Instance_methods` (2452-2466) | 1071-1075 | BOILERPLATE | | yes | FRONT |
| `memory_can_move` (2478-2487) | 1080-1087 | LOGIC | whether the runtime moves the memory on grow (not with guard pages) | no | CORE as is |
| `Memory_getbuffer` (2488-2505) | 1089-1105 | LOGIC (60 %) + CONVERT | size check, `PyBuffer_FillInfo`; first buffer freezes `max_pages` (pin counter `mem_pins`) | yes (6 refs) | SPLIT: core `<name>_memory_pin(inst, which, +1)` (exists as `rich_memory_memory_pin`); FRONT does `PyBuffer_FillInfo` |
| `Memory_releasebuffer` (2506-2516) | 1107-1111 | LOGIC (80 %) | last release restores `max_pages` | yes (2) | same as above |
| `Memory_ref`, `Memory_dealloc`, `memory_getters[]`, `Memory_getset` | 1114-1134 | PYLIFE / BOILERPLATE | handle object | yes | FRONT |
| `Instance_memory` (2542-2564) | 1136-1155 | CONVERT | `memoryview` over a `MemoryObject` that keeps the instance alive (big-endian: NotImplementedError) | yes | FRONT |
| `Instance_global_getN/setN` (2565-2587) | 1157-1171 | CONVERT | the global's value to/from Python | yes | FRONT; the access is the core pointer `w2c_<name>_g(&inst)` |
| `Instance_getset`, `Instance_members`, `Store_members/methods/getset`, `*_slots`, `*_spec` (2692-2817) | 1173-1250 (~110) | BOILERPLATE | type objects | yes | FRONT |
| `module_def`, `PyInit_rich` (2818-2903) | 1252-1288 | BOILERPLATE (~28) + LOGIC (~7: `wasm_rt_init`, `WASMEXT_STACK_LIMIT` init, `WASMEXT_CHAIN` install, `attach_traps`) | create types and exceptions, add to module | yes | FRONT; the 7 init lines are core (`wasmext_runtime_init()`) |

### 2.2 Blocks that exist only in other variants (read in the extra builds)

| Block (`_gen.py`) | Seen in | Lines | Category | What it does | Python API? | Where |
| --- | --- | ---: | --- | --- | --- | --- |
| `wasmext_is_v128`, `wasmext_bytes_v128`, `wasmext_v128_bytes` (1070-1097) | kitchen_sink | 21 | CONVERT | buffer of 16 bytes <-> v128 | yes | FRONT |
| `funcref_arg`, `funcref_result` (3454-3504) | fr | 38 | CONVERT + LOGIC + PYLIFE | funcref parameter: same 4 checks as `Table_set`; appends the owner to `self->refs`; result -> `Function_make` | yes (21 refs) | SPLIT like `Table_set`: shared validation `wasmext_funcref_check(e, &err)` and `wasmext_owners_add(&inst->refs, owner)` |
| `keep_alive` + `<name>_scrub_tables` after instantiate (1968-1980) | ti | ~10 in `Instance_new` | PYLIFE / LOGIC | after a failed instantiation the tables of others are scrubbed (core call); after success each exported table's owner keeps this instance alive via `__wasmext_keep__` | yes | CORE (scrub already core; keep -> owners) |
| memory import block (1901-1937) | ks | ~28 each | CONVERT / PYLIFE / LOGIC | the memoryview of a memory: look up `.obj`, `as_export_ref`, `<name>_link_memory0` (core), INCREF the owner into `hold0.mo0` | yes | SPLIT (same shape as func import) |
| global import block (1862-1900) | ks | ~22 each | same | `<name>_link_global0`; `hold0.go0` | yes | same |
| table import block (1938-1967) | ti | ~22 each | same | `<name>_link_table0`; `hold0.to0` | yes | same |
| `HostObject`, `host_callN`, `host_put`, `Host_imports/name/dealloc`, `Instance_host`, `host_slots/spec` (2588-2690; wasi only) | w1, w2 | w1: 749-851 = 103; w2 about 130 | CONVERT (`host_callN`, 14-17 each; `host_put`, `Host_imports` 24) + BOILERPLATE (rest) | exposes the originals of the WASI calls as Python callables (`instance.__host__.__imports__`) | yes | FRONT; `<name>_hostcallN` is already core |
| `wasmext_nothing_errno`, `wasmext_nothing_trap` (1048-1058; wasi only) | w1 | ~10 | PYCALLBACK | a stand-in callable for an import given as `None` | yes | FRONT |
| `raise_trap_code` wasi extras (1262-1306) | w1, w2 | +3 lines (w1) / +42 (w2: one `_pending` loop per group) | PYCALLBACK | `guest.exited`, `signalled`, `p2_message` branches before the `_pending` search | yes | SPLIT as above |
| `wasmext_wasi2_*` and `wasi_python.h` (hand-written in `src/wasmext/c/`, 548 + 356 lines, included into the generated file) | w1, w2 | 904 | CONVERT (config keys, option parsing: `wasi_apply_option`, `wasi_pack_strings`, `wasi_setup_preopens`) + PYCALLBACK (stream write/read hooks, `wasi_py_clock`, `wasi_py_random`, `wasi2_sleep`, `wasi2_wait`, `wasi2_policy`, network check hooks) + PYLIFE (`wasmext_wasi2_traverse/clear/free`, `wasi_py_options_free`) | the Python side of the WASI host: files-like objects, `time`/`random`, policy callables | yes | FRONT, as the hooks of a core that has a C interface (`rich_config` in `rich_api.h` is that interface). Not counted in the totals below (they live in headers, not in `_py.c`). I listed them from their function names and header comment only; bodies not read |

### 2.3 LOGIC rows: what can move as is, what is tangled, how to unpick

| LOGIC item | Moves AS IS (no Python call inside) | Tangled with Python, and how to unpick |
| --- | --- | --- |
| thread set-up (`wasmext_py_thread_setup_`) | the whole of `wasm_rt_init_thread`, `wasmext_stack_limit_init_`, the ready flag, the `WASMEXT_CHAIN` touch | only the destructor registration is Python (capsule in thread dict). Make core `int wasmext_thread_setup(void)` return "a thread-exit hook is needed"; front end registers `wasmext_thread_free` in its way (capsule in Python; `rich_thread_free` already exists for hosts) |
| trap handler one-liner | all | none |
| `attach_traps` | `wasmext_traps_use`, `wasmext_traps_own_` | the rendezvous key-value store is the interpreter dict. Pass two callbacks (`get(key)`, `put(key, ptr)`); front end implements them with `PyInterpreterState_GetDict`; error text to ImportError by the front end |
| `raise_trap_code` decision part | code classification, texts (`wasm_rt_strerror`, "the store is closed", "a host function ... failed"), wasi end (exit code / signal) | the `_pending` loop is Python attribute access on the foreign owner. Replace by a core "host error cell": the failing host function (the front end's `py_importN` or `py_linkN`) stores an opaque handle into `store->pending` (+ release callback from the owner ops); `raise` takes it. This removes the attribute coupling with the ctypes wrapper |
| `Store_close` | `closed`, `active` logic | error classes: core returns 0/1 and front end raises `RuntimeError` |
| `export_address/memory/table`, `export_table[]`, `memory_can_move`, `table_getters`, `memory_getters` | all (these are the 31-38 no-Py lines) | none; only the argument type is `InstanceObject *` (change to `<name>_instance *`) |
| `export_ref` | record filling (`kind`, `type`, `flags`, `address`, `funcref`, `signature`, `runtime`, seal) | INCREF of owner, `PyMem_Malloc`, capsule. Core fills a caller-provided `wasmext_export` (like `wasmext_table_export` already does); front end owns allocation and capsule |
| `Function_richcompare/hash` | all | wrap return value only |
| `Table_new` range check, `Table_grow` failure reason | `initial > maximum`, grow refusal reason (max / memory) | message formatting `PyErr_Format`; core returns code + reason enum, front end formats (or core formats into a buffer like `wasmext_link_fail`) |
| `Table_set`, `funcref_arg` | `wasmext_export_ok`, `kind == FUNC`, funcref non-null, `func_type` non-null, flags 16, the 16-byte store; add owner to the writer list | `function_holder` + `as_export_ref` unwrap (CONVERT: keep in front end and hand core a `const wasmext_export *`); `PyErr_SetString` of 5 texts; `Table_keep` through `PyList_Append`. Unpick: (1) core `int wasmext_table_set(table, index, const wasmext_export *e, wasmext_error *err)` does checks and store; (2) core `wasmext_owners_add_unique(list, owner)` replaces `writers_have/Table_keep/Instance_keep/keep_alive`; (3) front end maps `err.kind` (TYPE / LINK / INDEX) to the exception class |
| `Table_get`, `table_find_function` | `elem->func == NULL`, copy of the element, the comparison `func` and `module_instance` | walk of `x.__exports__` and `getattr(found, "__name__")`. Unpick with a core `const char *wasmext_funcref_export_name(const wasm_rt_funcref_t *f)` that uses a registry `module_instance -> export descriptor` (the `owners_registry.md` registry, step 2); front end then only builds `Function(name=PyUnicode)` |
| `Instance_new` link decision | per-import: record is OK, kind, signature string compare, set `host.fn[i]`/`user[i]` (`<name>_link_funcN` already does it), instantiate + initialize, `scrub_tables` | lookup in a Python mapping (CONVERT), unwrap of `__wasmext_ref__` / bound method (CONVERT), `Py_INCREF` of the exporter into `hold*` (PYLIFE), `with_caller` (PYCALLBACK), error text to `LinkError`. Unpick: (1) generate a table of import descriptors `{module, field, kind, signature}` in the core; (2) front end loops: resolve value -> either `wasmext_export*` + owner, or callable; (3) call `<name>_link_import(inst, i, rec, owner, &err)` / `<name>_set_host(inst, i, fn, user, user_release)`; (4) core retains through owner ops. The loop is then one copy, not one per import |
| memory pins | `mem_pins[]`, `mem_max_pages[]`, `max_pages = pages`, restore | `PyBuffer_FillInfo`, `view->internal` marker. Move counters into core instance; front end keeps the buffer protocol |

## 3. Totals per category (lines of `_py.c`, non-blank)

"Split" = my estimate with the mixed functions split by the fractions in section 0. "Primary" = each unit counted wholly in its main category (shown so the effect of the estimate can be judged). Lines of the hand-written included headers are NOT in these numbers.

| Module | Total non-blank (file lines) | CONVERT | PYLIFE | PYCALLBACK | LOGIC | BOILERPLATE | LOGIC in functions with no `Py*` token |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| add (`c_add`) split | 371 (409) | 79 (21 %) | 68 (18 %) | 27 (7 %) | 46 (12 %) | 151 (41 %) | 8 |
| add primary | 371 | 65 | 41 | 25 | 89 | 151 | |
| rich (`c_rich`) split | 1187 (1288) | 396 (33 %) | 262 (22 %) | 86 (7 %) | 174 (15 %) | 270 (23 %) | 38 |
| rich primary | 1187 | 328 | 180 | 79 | 330 | 270 | |
| tbl (`c_tbl`) split | 1011 (1108) | 327 (32 %) | 233 (23 %) | 44 (4 %) | 164 (16 %) | 244 (24 %) | 37 |
| tbl primary | 1011 | 280 | 165 | 42 | 280 | 244 | |

Reading: going from add to rich adds about 816 non-blank lines; the added lines are CONVERT +317, PYLIFE +194, LOGIC +128, BOILERPLATE +119, PYCALLBACK +59. The 8 no-Py LOGIC lines of add are `store_release` (4) and the `export_table[]` data (4); in rich and tbl the rest are `memory_can_move`, the `export_table[]` data, `export_memory0/table0` and the getter tables.

Other builds, split estimate (for scale; the same tool):

| Build | Total non-blank | CONVERT | PYLIFE | PYCALLBACK | LOGIC | BOILERPLATE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| add `--share-tables` | 857 | 275 | 202 | 38 | 126 | 217 |
| kitchen_sink | 1332 | 482 | 282 | 101 | 186 | 282 |
| exceptions | 475 | 122 | 68 | 77 | 50 | 158 |
| wasi_hello (wasip1) | 895 | 252 | 137 | 104 | 101 | 301 |
| wasi2_probe (wasip2) | 1289 | 398 | 203 | 207 | 138 | 342 |
| probe (17 Python imports) | 1896 | 738 | 320 | 393 | 229 | 217 |

Observations:
- `add` to `add --share-tables`: +486 lines (409 -> 937 in the file) of which only 80 are LOGIC; the cost of sharing tables is mostly Table/Function objects (CONVERT/PYLIFE).
- `probe` shows the effect of the per-import copy: CONVERT 738 and PYCALLBACK 393 are 60 % of the file, from 17 imports, and the work per import is the same.
- The doc figure "2-4 % of the lines are in functions with no Py reference" is confirmed; with my counting of no-Py LOGIC it is 8 / 38 / 37 lines (2 % / 3 % / 4 %) of the non-blank lines.

## 4. Proposed core C API entries

Plain C, no Python, in `wasmext_glue.h` (generic, one copy) and `<name>_glue.h`/`<name>_api.h` (typed per module). Names are proposals. Many already exist in `<name>_api.h` (marked `[exists in api.h]`) and in `wasmext_glue.h` (`[exists in glue.h]`); the work is to make the extension call them instead of re-implementing, and to put them where both the extension and the shared library compile them (one definition).

Error/trap vocabulary (replaces the code-to-exception tables):
```c
typedef struct { int kind; char message[256]; } wasmext_error; /* WASMEXT_E_NONE,LINK,TYPE,VALUE,INDEX,NOMEM,CLOSED,BUSY */
/* what a trap code means, once: fills class (TRAP, CLOSED, NOMEM, HOST, UNCAUGHT, ENDED_EXIT, ENDED_SIGNAL), text, value */
void wasmext_trap_describe(const void *instance /* may be NULL */, int code, int foreign, wasmext_trap_info *out);
const char *rich_trap_message(int code);                 /* [exists in api.h] */
int  rich_trap_is_exception(int code);                   /* [exists in api.h] */
```
Host-function failure that crosses instances (replaces `_pending`):
```c
void  wasmext_host_error_set(void *error, void (*release)(void *));   /* thread-local cell; front end stores its exception handle */
void *wasmext_host_error_take(void);                                 /* the failed call returns the handle; NULL if none */
```
Owners (the main design question of the former thin_glue note): opaque handle plus retain/release supplied by the front end:
```c
typedef struct { void (*retain)(void *owner); void (*release)(void *owner); } wasmext_owner_ops;
void wasmext_store_set_owner_ops(<name>_store *st, const wasmext_owner_ops *ops);  /* extension: Py_INCREF/DECREF thunks; exe: NULL */
/* what an instance holds (replaces hold0.fn/lo/go/mo/to, writers, refs); released in <name>_glue_free */
int  wasmext_hold(<name>_instance *inst, int import_index, void *owner);        /* retains; 0 / -1 NOMEM */
int  wasmext_owners_add_unique(wasmext_owner_list *l, const wasmext_owner_ops *ops, void *owner);  /* writers / refs / keep_alive */
void wasmext_owners_each(const <name>_instance *inst, void (*visit)(void *owner, void *arg), void *arg);   /* for tp_traverse */
void wasmext_owners_clear(<name>_instance *inst);                                /* for tp_clear (releases and forgets) */
```
`wasmext_owners_each` is what keeps the CPython GC correct once the references are held in C: `Instance_traverse` still calls `Py_VISIT` for each owner it is given. Registry (from `owners_registry.md`): `void *wasmext_funcref_owner(const wasm_rt_funcref_t *)`, `const char *wasmext_funcref_export_name(const wasm_rt_funcref_t *)`.

Linking and exports (replaces the three per-import blocks and `export_ref`/`export_table[]`):
```c
typedef struct { const char *module, *field; int kind; const char *signature; } <name>_import_info;
int  <name>_import_count(void);   const <name>_import_info *<name>_import_info_at(int i);
int  <name>_link_import(<name>_instance *inst, int i, const wasmext_export *e, void *owner, wasmext_error *err);  /* generic over kind; wraps link_func/global/memory/table<N> */
int  <name>_set_host(<name>_instance *inst, int i, void *fn, void *user, void (*user_release)(void *));           /* a host callable */
int  <name>_export_count(void);   int <name>_export_at(int k, const char **name, int *kind);
int  <name>_export_find(<name>_instance *inst, const char *name, void *owner, wasmext_export *out);               /* [exists in api.h as rich_export_find] */
int  wasmext_export_check_funcref(const wasmext_export *e, wasmext_error *err);                                    /* the 4 checks of Table_set / funcref_arg */
```
Functions and funcrefs:
```c
int      <name>_funcref_type(const void *funcref);                          /* [exists] */
int      wasmext_funcref_same(const void *a, const void *b);                /* [exists as rich_funcref_same] */
uint64_t wasmext_funcref_hash(const void *f);                               /* [exists as rich_funcref_hash] */
int      <name>_callref_dyn(const void *funcref, const wasmext_value *args, int nargs, wasmext_value *res, int *trapped);  /* new; generic Function.__call__ */
const <name>_type_info *<name>_type_info_at(int k);                         /* params, results (names too) for Function.signature and argument checks */
```
Tables (add the checks the front end now does):
```c
int  wasmext_table_check_limits(uint32_t initial, uint32_t maximum, wasmext_error *err);
int  wasmext_table_set(void *table, uint32_t index, const wasmext_export *e, wasmext_error *err);   /* None: e == NULL */
int  wasmext_table_get(const void *table, uint32_t index, wasm_rt_funcref_t *out);                  /* 0 empty, 1 filled, -1 range */
int  wasmext_table_grow_error(void *table, uint32_t delta, wasmext_error *err);                      /* the two messages */
/* [exist] rich_table_new/free/size/maximum/grow/export/is_null/is/set/get_ref, rich_funcref_copy/free/export */
```
Globals, memory, store, threads:
```c
int  <name>_global_get(<name>_instance *i, int k, wasmext_value *v);   int <name>_global_set(<name>_instance *i, int k, const wasmext_value *v);
void <name>_memory_pin(<name>_instance *i, int which, int pin);         /* [exists as rich_memory_memory_pin]; counters move into the core instance */
int  wasmext_store_close(<name>_store *st);   int wasmext_store_closed(const <name>_store *st);   /* [exist as rich_store_close/closed] */
int  wasmext_thread_setup(void);              /* 1 if a thread-exit hook must be registered */   /* [rich_thread_free exists] */
int  wasmext_traps_attach(void *(*get)(const char *key), int (*put)(const char *key, const void *p));
int  wasmext_runtime_init(void);              /* wasm_rt_init, stack limit, chain handler: the 7 init lines of PyInit */
```
What the front ends must provide (the answer to the "Open" question in the former thin_glue note about logic that cannot leave Python):
- retain/release of an owner (`wasmext_owner_ops`), and the `tp_traverse` visit of the owners the core lists;
- creating the exception object for a core `wasmext_error`/`wasmext_trap_info`, and the `wasmext_host_error` handle;
- a host function as a Python callable: the trampoline (`py_importN` or one dynamic one) and the GIL rule: the front end's trampoline must acquire what its runtime needs before calling Python (the known failing scenario of `test_a_python_callback_in_a_table_function`: the ctypes front end releases the GIL, the extension does not; put the rule in one named hook `host_enter/host_leave` of the ops table);
- the interpreter-keyed rendezvous (`get/put`) for the traps stack and for the owners registry;
- the thread-exit hook;
- conversions, argument parsing, type objects, the `Caller`, WASI config and stream objects.

## 5. Ordered plan of small moves

Each step keeps behavior and tests; each is one commit's worth. "Tests" are the existing ones named by file (I did not run them). Steps 1-3 touch only `_gen.py` templates and change no core API; steps 4+ move code. Step 11 changes behavior and is separate on purpose.

| # | Move | Size | Risk | What guards it |
| ---: | --- | --- | --- | --- |
| 0 | Snapshot the generated `*_py.c` of the 10 builds above as golden files (outside the repo) and run the whole test-suite once for a baseline. | none | none | baseline |
| 1 | Dedupe inside the templates, no semantics change: one `import_ref(v)` helper for "ref or method of an instance" (used by `Instance_new` per import and by `function_holder`); one loop over the `hold*.lo` arrays in `raise_trap_code`; the funcref validation as one function used by `Table_set` and `funcref_arg`; one `raise_trap_describe` shared by `raise_trap_code` and `raise_foreign_trap` (a flag for the differences). Expected: `Instance_new` of probe 776 -> about 150 lines (estimate), wasi2 `raise_trap_code` 68 -> about 30. | `_gen.py` 1399-1982, 1259-1312, 3053+ | low: output text changes, behavior does not; diff goldens by eye | test_linking, test_tables, test_table_class, test_wasi_across_instances, test_two_modules, test_caller, test_wasi2 |
| 2 | Move the no-Py code to `<name>_glue.h`: `export_table[]` as `<name>_exports[]`, `export_address/memory/table`, `memory_can_move`, the trap handler, `table_getters/memory_getters`, `Function_richcompare/hash` bodies as `wasmext_funcref_same/hash`. The extension includes and calls them. | 35-40 lines per module | low | test_extension, test_tables, test_features (memoryview, pins) |
| 3 | Core checks that return a code and message (the `wasmext_link_fail` pattern): `wasmext_export_check_funcref`, `wasmext_table_check_limits`, `wasmext_table_index_ok`, `wasmext_table_grow_error`. The texts are copied verbatim from the templates. The extension maps `err.kind` to the exception class it raised before. | about 60 lines out of the extension | low-medium: the message strings are probably matched by tests (`match=`), so copy them exactly | test_tables, test_table_class, test_linking |
| 4 | `wasmext_trap_describe` (core) for the non-Python branches of `raise_trap_code`/`raise_foreign_trap`: class, text, exit code, signal. Front end keeps "make the exception from it" (one function). Do not touch the `_pending` part yet. | about 25 lines per module | medium: the foreign variant is deliberately different (no wasi branches, adds UNCAUGHT) | test_wasi, test_wasi2, test_features (tags), test_wasi_across_instances |
| 5 | Exports through the core: `<name>_export_find`/`export_at` used by `export_ref`, `Instance_subscript`, `Instance_exports` (they already exist in the shared lib; make one definition both include). The capsule stays. | about 40 lines | low-medium: capsule destructor order and INCREF of owner must stay as is | test_linking, test_two_modules, test_abi |
| 6 | Imports through descriptors: generate `<name>_import_info[]` and generic `<name>_link_import` (wrapping the existing `_link_func/global/memory/table<N>`), and let `Instance_new` loop over the table (the lookup and the unwrap stay in Python). Hold arrays stay in the extension for now. | removes the per-import generation | medium: error texts of the four kinds, partial failure cleanup (`scrub_tables`), order of side effects (a failure at import 3 after import 1 was linked) | test_linking, test_compact_imports, test_caller |
| 7 | Owners: introduce `wasmext_owner_ops`, `wasmext_hold`, `wasmext_owners_add_unique`, `wasmext_owners_each/clear`. Move `hold*`, `writers`, `refs`, `Table.writers` into the core instance; `Instance_traverse/clear` call `owners_each/clear`; `Instance_keep`, `Table_keep`, `keep_alive`, `writers_have` disappear. Replace the call of `owner.__wasmext_keep__` by the core list. Keep `__wasmext_keep__` in the extension during the transition so the ctypes wrapper keeps working; remove after its own move. | about 90 lines per table-sharing module | HIGH: reference counts and GC visits (a cycle through a C-held reference that `tp_traverse` does not report becomes a leak; a missing one is a crash), dealloc order (core freed before owners cleared today), interop with the wrapper which still calls `__wasmext_keep__` | test_threads, test_two_modules, test_table_class, test_sanitizers, a refleak run, `gc.collect()` scenarios; add a test first |
| 8 | `Table_set/get`, `table_find_function`, `funcref_arg`: core `wasmext_table_set(table, i, rec, err)` / `wasmext_table_get`, name lookup through the registry (`wasmext_funcref_export_name`); the front end converts and wraps. Needs 3 and 7. | about 100 lines | high-medium: replaces scan-by-`__exports__` with a registry; owner lifetime invariant of `owners_registry.md` (open point 2 and 3: address reuse) | test_tables, test_table_class, test_wasi_across_instances |
| 9 | Pin counters into the core (`<name>_memory_pin`), `Memory_getbuffer/releasebuffer` become `PyBuffer_FillInfo` + a call. Move `Store_close` logic to `wasmext_store_close`. | about 30 lines | low-medium: thread safety of the counter (today protected by the GIL; the core has no lock) | test_features (memoryview, grow), test_store_shared, test_threads |
| 10 | `wasmext_thread_setup`, `wasmext_traps_attach(get, put)`, `wasmext_runtime_init`; the host-error cell replacing `_pending`. Last, because it changes the cross-front-end contract: the wrapper must stop parking the exception in `_pending` at the same time. | about 60 lines | HIGH: signal handler/alternate stack per thread, sub-interpreters, wrapper compatibility | test_threads, test_sanitizers, test_wasi_across_instances |
| 11 | (behavior change, not part of "same tests") one place for the rule "who holds the GIL when a host function is called" (`host_enter/host_leave` in the ops table). This is the fix for the known divergence, so it needs a new/changed test. | small | high | `test_wasi_across_instances.py::test_a_python_callback_in_a_table_function` |
| 12 | Last: generic `<name>_callref_dyn` and `<name>_type_info_at` so `Function_call` and `Function_signature` lose their per-type switch, and a dynamic `py_import_dyn`. Only if the benchmark of `docs/context_concept.md` shows no loss on the hot path; keep the typed `Instance_fN`/`py_importN` fast paths regardless. | about 40 lines + the 17-copy `py_importN` | medium: speed | benchmark + test_extension |

Order logic: 1 (dedupe) first because it makes every later diff small and gives the first real numbers; 2-3 are the free ones (no ownership); 4-6 are about decisions and records; 7-8 are the ownership change that the whole of the former thin_glue note hangs on; 9-10 are the smaller state moves; 11 and 12 are separate because one changes behavior and the other may cost speed.

## 6. What I could not determine

- Whether the extension can compile the shared library's `.c` (the `rich_shared.c` set: table/funcref/pin/export_find) directly. The extension includes only `<name>_glue.h`; `_shared.py` and `_natify.py` build wiring was not read. This decides whether the core "entries" are new code or just a move of the existing `rich_shared.c` functions to a header; I guess the second but did not check.
- The exact fraction split of the 11 mixed functions: it is my reading of rich (and of Table_set line by line); other modules use the same fractions. The error is a few tens of lines per module in LOGIC vs CONVERT/PYLIFE.
- How much of the ctypes wrapper copy corresponds one-to-one with a block here (no read of `_ctypes_gen.py`); so "this rule is written twice" is shown only where the extension itself reads a Python attribute of the wrapper (`_pending`, `__wasmext_keep__`, `__wasmext_ref__`), not for every row.
- Whether a thread-local host-error cell is enough for the `_pending` replacement when the ctypes front end releases the GIL (threads, re-entrancy through a table function). Needs a design check with `test_wasi_across_instances`.
- Whether holding references in C is safe with the free-threaded build and sub-interpreters (the interpreter-keyed rendezvous is a per-interpreter dict today). `owners_registry.md` itself says this is "designed on paper, not tried".
- The cost on the hot path of `<name>_callref_dyn`/`py_import_dyn` (not measured).
- Behavior of the `.pyi` stub generation, `_importer.py`, and `_setuptools.py`: not part of the generated C and not read.
- Whether all message strings of the templates are asserted by tests (I did not search the tests): the plan treats them as asserted.
- The bodies of `wasi_python.h` / `wasi2_python.h` (904 lines): classified from the function list and the header comment, not read; they are outside the totals.
- Anything about `--exe` and `--shared` front ends beyond what `rich_api.h` shows.
