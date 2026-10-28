# Audit of the ctypes wrapper and of the shared library / C API (read-only, 2026-10-28)

Scope: `src/wasmext/_ctypes_gen.py` -> `<name>_ctypes.py`, and `_shared.py` -> `<name>_shared.c`, `<name>_glue.h`, `<name>_api.h`, plus `src/wasmext/c/wasmext_glue.h`. The CPython extension (`_gen.py`) was looked at only by its emitted names and a few functions of `rich_py.c` (lines 72-168 and 426-530). Nothing in the repo was changed (all work in `/tmp/claude-0/audit`; note that `uv run` may have touched `.venv` or `uv.lock` in the repo, I did not check).

Samples used (all generated with `build_shared` as in `tests/conftest.py::build_ctypes`):

| Sample | What | wrapper lines |
| --- | --- | ---: |
| `add` | `/tmp/claude-0/glue/ct_add`, share_tables=False | 835 |
| `addsh` | add.wasm, share_tables=True (`/tmp/claude-0/audit/b/addsh`) | 1047 |
| `rich` | `/tmp/claude-0/glue/ct_rich`: import, memory, table, global (shares tables) | 1047 |
| `tbl` | tbl.wasm: table with call_indirect, grow | 1047 |
| `probe1` | wasi_probe.wat, host wasm32-wasip1, 17 WASI imports | 1142 |
| `p2` | tests/data/wasi2_probe.wat, host wasm32-wasip2 (a core module with p2 imports) | 1189 |
| `ks`, `imp` | kitchen_sink.wat; a module I wrote (`/tmp/claude-0/audit/imp.wat`) importing a table, a memory and two globals; only for the C API | 1047 each |

Headline facts, measured:

1. The wrapper is ONE template. `rich`, `addsh` and `tbl` differ only in the data tables (`_EXPORTS`, `_IMPORTS`, ...) and in names; `add` is the same minus `Table` and `Function` (the 212 lines the doc quotes as "rich minus add" are exactly `_SHARES_TABLES`); WASI adds ~295 lines (probe1) or ~342 (p2).
2. The C API is NOT a stable surface: its shape changes with the module (`link_import<k>`, `link_global_import<j>`, `set_global_import<j>`, `link_memory_import<j>`, `link_table_import<j>`, `unlink_tables`, `host_call<k>`, `funcref_call<k>`, `<export>`, `memory_<name>`, `global_<name>`) so the wrapper needs generated tables to know names and signatures. That, more than anything, is why the wrapper is large.
3. The executable does not use `<name>_api.h` at all: it uses `<name>_glue.h` and fusedwasi directly and builds its own store and WASI state by hand (`_exe.py` `_RUN_STATE`). So there are three front ends over two "cores" (api.h for ctypes, glue.h for exe and extension), not three over one.
4. The extension and the wrapper already talk to each other through a PYTHON protocol, not a C one: attributes `__exports__`, `__wasmext_ref__`, `__wasmext_keep__`, `_pending`, and `record.owner` being a `PyObject *` (the wrapper casts it with `ctypes.cast(record.owner, py_object)`; `rich_py.c` `raise_trap_code` reads `_pending` of the wrapper by name; `py_link0`). This is the biggest hidden coupling and it has no counterpart in C.

---

## Part A. The wrapper, row by row

Row = a top-level function/class (methods listed separately where they differ). Lines are the AST span from `rich_ctypes.py` (the spans add up to the file: the rest is "gaps", listed at the end). "C entry" is the symbol of the generated library (prefix `rich_`), "-" = none. For mixed rows the category is the dominant one and the mix is said in "does". `where` = where it belongs in the target design (CORE = plain C in the core; FE = stays in the front end; BIND = binding that could be generated).

### A.1 Rows present in every wrapper

| name | lines | cat | what it does | C entry today | where |
| --- | ---: | --- | --- | --- | --- |
| `Trap`, `LinkError` | 2+2 | BOILERPLATE | exception classes | - | FE (names are the contract; the CORE gives a *kind* code) |
| `_share_traps` | 26 | LOGIC | finds/publishes the stack of entries for traps in the interpreter dict as capsule `wasmext.traps.v0` through `PyInterpreterState_GetDict`, then `traps_use`. The extension has the same in C (`attach_traps`, 20 lines) | `rich_traps`, `rich_traps_use` | The stack and its compatibility check are already CORE. Only the RENDEZVOUS (where the first library leaves its pointer) is front-end: needs "a slot per interpreter/process". Either keep 20 lines per FE, or give the core one process-wide slot (own tiny shared object, see C.2 `wx_traps_slot`) |
| `_library` | 32 | BOILERPLATE | `CDLL`, env override of the path, `argtypes/restype` of 14 fixed entries | all `store_*`, `abi`, `runtime`, `new`, `free`, `status_ptr`, `instantiate`, `trap_message`, `wasi_end` | BIND (generated from the header) |
| `_to_i32/_to_i64` | 3+3 | CONVERT | wrap a Python int modulo 2**32/2**64 as WebAssembly does | - | FE (a conversion) |
| `_to_float` | 4 | CONVERT | int/float to float, TypeError otherwise | - | FE |
| `_to_v128` | 9 | CONVERT | 16 bytes <-> `c_uint8*16` with the error messages | - | FE |
| `_function` | 9 | BOILERPLATE | cache of C functions with `restype/argtypes` set on first use | any | BIND |
| `_unpin` | 5 | PYLIFE | weakref callback: unpin the memory when the memoryview dies | `rich_memory_memory_pin(m, 0)` | FE (the lifetime of the view is Python's); the pin counter is CORE and is |
| `_signature` | 2 | BOILERPLATE | docstring text | - | BIND |
| `_Export` | 8 | BOILERPLATE | ctypes mirror of the C struct `rich_export` / `wasmext_export` (12 fields, hand-copied) | the struct | BIND (must be generated from the header, today it is a second hand-kept copy: a field added in C must be added here) |
| `_usable` | 3 | LOGIC | `wasmext_export_ok` of the glue in Python (same x, size, floor) | the C `link_*` do the same check | CORE (delete; a C entry `wx_export_check(rec)` or checks inside `table_set`/`funcref arg`) |
| `_capi` setup (gap) | 6 | BOILERPLATE | `restype/argtypes` of the capsule functions | - | FE (Python-only protocol) |
| `_Reference` | 15 | PYLIFE | object holding the record the library filled plus the instance that owns it; exposes `__wasmext_ref__` as a capsule (an object and not a capsule so that no ctypes destructor runs during an exception) | `rich_export_find` fills the record | FE as a *handle* but the "keeps the instance alive" part is the owner edge: CORE (`wx_owner`) |
| `_capsule_of`, `_is_capsule` | 10+2 | CONVERT | follow `__wasmext_ref__` up to 3 times to a valid capsule | - | FE (Python protocol); disappears if records are passed as pointers |
| `_record_of` | 8 | CONVERT | capsule -> `_Export` | - | FE/BIND |
| `_function_of` | 8 | LOGIC | for a function export of an EXTENSION instance (flag bit 3 clear): scan `owner.__exports__` for the record that matches (`address`, `instance`) and return the bound method, so it is called through Python | - | Python-only bridge (FE). Goes away if the extension also sets flag bit 3 / gives a C-callable (see C.2 `wx_host_func`) |
| `_table_u32` | 6 | CONVERT | int check and range 0..2**32-1 with messages | - | FE for the TypeError; the range is CORE (`wx_table_new` returns an error code) |
| `_free`, `_store_free` | 2+2 | BOILERPLATE | finalizer targets | `rich_free`, `rich_store_free` | BIND |
| `Caller` (class, 4 methods) | 14 | PYLIFE | the object given to host callables that ask for it (`__wasm_caller__`): instance, store, memory | - | FE (Wasmtime-like, Python object) |
| `_with_caller` | 7 | PYLIFE | wraps a callable with `functools.partial(fn, caller)` once | - | FE |
| `Store.__init__/close/closed/runtime/__enter__/__exit__` | 13+5+3+4+4+2 | BOILERPLATE | forwards; messages ("the store is in use", "the store is closed") | `store_new/close/closed/free`, `abi`, `runtime` | thin already; BIND. The two messages are CORE return codes mapped to exception *types* by the FE |
| `Instance.__init__` | 53 | LOGIC | checks the store type/closed; decides from `_IMPORTS` whether `imports` is required (LinkError text) or forbidden (TypeError); iterates function imports (WASI ones optional, `None` = nothing given), then global, memory, table imports; instantiates; on failure unlinks tables; then tells the owners of imported tables to keep this instance (`__wasmext_keep__`) | `new`, `status_ptr`, `instantiate`, `unlink_tables`, `set_import<k>`/`link_*` via helpers | CORE: one `wx_instantiate(inst, resolver)` that walks the imports, calls the front end's resolver for each, links/sets, instantiates and unwinds on failure (C.2). FE keeps: the type check of `store`, the dict lookup (resolver) |
| `Instance._error` | 20 | LOGIC | code -> exception: HOST (take `_pending` of self, else of the store, else of every instance in `_owners`), NO_MEMORY -> MemoryError, CLOSED -> ValueError, ENDED -> `_ended()`, else `Trap(message)`; uncaught wasm exception -> `_uncaught` when the module has tags | `trap_message`, `trap_is_exception`, `exception`, `wasi_end` | CORE decides the KIND and carries the data (`wx_error_describe`, `wx_take_pending`); FE maps kind -> Python exception class. The chain walk over `_owners` is a graph the core already knows through its links |
| `Instance._function_import` | 33 | LOGIC | for a function import: is it a capsule/`__wasmext_ref__`/bound method of a wasmext instance? then Python re-checks ABI usable, kind, **signature string** (builds the letters `ijfdo` from `_IMPORTS`), then either calls the C linker (flag bit 3) or `_function_of`; otherwise plain callable | `link_import<k>` | CORE. The signature and ABI checks are DUPLICATED: `rich_link_func0` does the same `strcmp` with the same message. Pure deletion candidate (A) |
| `Instance._keep` | 4 | PYLIFE | append `record.owner` (cast to a Python object) to `_owners` | - | CORE owner edge |
| `Instance._global_import` | 19 | LOGIC | record -> `link_global_import<j>`; else mutable -> LinkError text; else type check of the plain value, convert, `set_global_import<j>` | `link_global_import<j>`, `set_global_import<j>` | CORE: `wx_link(kind GLOBAL)` / `wx_global_import_value`; mutability rule is in the module description, so CORE. Type check of the Python value is CONVERT |
| `Instance._memory_import` | 12 | LOGIC | memoryview -> its `.obj.__wasmext_ref__` -> record -> `link_memory_import<j>` | `link_memory_import<j>` | CORE link; the memoryview -> record step is FE |
| `Instance._table_import` | 11 | LOGIC | record -> `link_table_import<j>`, `_keep`, remember table owner | `link_table_import<j>` | CORE |
| `Instance.__wasmext_keep__` | 3 | PYLIFE | `_writers.append(other)` | - | CORE owner edge (writers) |
| `Instance._table`, `_reference` | 3+7 | LOGIC | `export_find` into a fresh record and wrap it (`_Reference`/`Table._of`) | `export_find` | CORE has the lookup; the wrapping is FE |
| `Instance.__exports__` | 13 | BOILERPLATE | dict name -> reference for every export, from the generated Python tables | `export_find` per name | CORE: `wx_export_list` (names are not in the library at run time today) |
| `Instance.__getitem__` | 6 | BOILERPLATE | same by name | `export_find` | CORE `export_find` already; names check needs the list |
| `Instance._set_import` | 75 | PYCALLBACK | builds a `CFUNCTYPE` for the signature, two Python callbacks (`callback` generic, `fast_callback` for numbers), converts args (v128 via `string_at`), checks the results (messages with the import name), writes multi-results through pointers, catches `BaseException` into `owner._pending` and sets `*trapped=1`; keeps the thunk in `_callbacks` and the weakref to self | `set_import<k>(m, fn, user)` | FE for the actual call into Python and the exception capture (unavoidable). The WHAT-to-do-with-a-failure (the slot `_pending`, who reads it, the code HOST) is CORE. With a uniform value-array callback (C.2) the per-signature `CFUNCTYPE` and the two specialised bodies collapse to one |
| `Instance._call` | 24 | CONVERT | convert args by the signature, call, read outs, `v128` -> bytes, `funcref` result -> `Function._of`; "direct" path reads `_status` | `<export>`, `status_ptr` | FE conversion; BIND for the prototype |
| `Instance._funcref_arg` | 19 | LOGIC | funcref parameter: None / Function / method -> record -> `_usable`, kind, `funcref` present, `flags & 16` (module shares tables) with the long message; remember the owner in `_refs` | - (the pointer `record.funcref` is passed) | CORE `wx_funcref_from_export(rec, &out, msg)` with the checks; the owner edge in `_refs` is CORE |
| `Instance._memory` | 14 | PYLIFE | `(c_uint8*size).from_address`, pin the memory, `weakref.finalize(buffer, _unpin)`, attach `_instance` and `__wasmext_ref__` so the view keeps the instance and can be imported by another instance | `memory_<name>`, `memory_<name>_pin`, `export_find` | FE (a buffer object lifetime). The pin count/`memory.grow` -1 rule is CORE and already is. The extension re-implements the pin (`mem_pins`, `memory_can_move` in `InstanceObject`): a second copy of `rich_memory_memory_pin` |
| `Instance._get_global/_set_global` | 2+2 | CONVERT | typed getter/setter | `global_<name>`, `set_global_<name>` | BIND |
| `_find_import` | 17 | CONVERT | `imports[module][field]`, or `module.__exports__[field]` when the shelf is a wasmext instance; LinkError messages "missing import module/..." | - | FE: this IS the resolver. The message texts should come from the core (`wx_instantiate` reports which import is missing) so both FEs say the same |
| `_nothing` | 9 | PYCALLBACK | a WASI call given as `None`: ENOSYS (52) if host is wasip1 and result is i32, else a trap | - | CORE (the rule depends only on host and result type); the Python callable it returns is the FE's way to pass "nothing" |
| `_SIMPLE`, `_RANGE` (gap) | 2 | CONVERT | tables for the fast path | - | FE |
| `_fast_method` | 40 | CONVERT | builds by `exec` a method specialised for a signature of numbers (no loops, `_convert<i>` per arg, result straight from `restype`, error code in `self._status`) | `<export>`, `status_ptr` | BIND (this is the hot path; keep it generated from the descriptor) |
| `_method` | 13 | BOILERPLATE | picks fast/slow | - | BIND |
| `_memory_property`, `_global_property` | 2+5 | BOILERPLATE | properties | - | BIND |
| module tail (gap) | ~10 | BOILERPLATE | `setattr(Instance, name, method)` loops | - | BIND |
| data tables (gap): `_EXPORTS _MEMORIES _GLOBALS _IMPORTS _GLOBAL_IMPORTS _MEMORY_IMPORTS _TABLES _TABLE_IMPORTS _SHARES_TABLES _REF_TYPES _WASI _HOST _TAGS _ABI ...` | ~25 (the lines are very long) | BOILERPLATE | description of the module: names, C symbol names, types, flags | none: the library has no run-time description | CORE `wx_module_info()` (C.2); then the wrapper loads it |
| `_CONVERT/_CTYPE/_ARG/_PYTYPE` (gap) | ~20 | CONVERT | type name -> converter/ctype | - | FE/BIND |
| header, imports, class shells, blanks (gap) | rest of 263 (157 blank, 19 comment) | BOILERPLATE | | - | - |

### A.2 Rows only when the module shares tables (`_SHARES_TABLES`), +212 lines

| name | lines | cat | what it does | C entry | where |
| --- | ---: | --- | --- | --- | --- |
| `_table_free`, `_funcref_free` | 2+2 | PYLIFE | finalizer targets | `table_free`, `funcref_free` | CORE (refcount) |
| `Function._of` | 12 | PYLIFE | wrap a funcref copy the library made: keeper, `weakref.finalize(self, funcref_free)`, type index, a record for use in another table | `funcref_type`, `funcref_export` | CORE object `wx_func` with a refcount; FE a shell |
| `Function.signature`, `.name`, `__repr__` | 6+3+2 | CONVERT / BOILERPLATE | `_REF_TYPES[type]` lookup; name set by `Table.get` | - | CORE `wx_func_signature` (from `wx_module_info`), name by the registry |
| `Function.__call__` | 23 | CONVERT | argument count check, convert, call `funcref_call<k>`, outs, trap -> MemoryError/Trap (**a second, different code -> exception map: does not go through `Instance._error`, so a HOST trap in a Function call has no `_pending` handling**) | `funcref_call<k>`, `trap_message` | CORE `wx_func_call(values)` + `wx_error_describe`; one map in the FE |
| `Function.__eq__/__hash__` | 4+2 | CONVERT | pass-through | `funcref_same`, `funcref_hash` | BIND |
| `Function.__wasmext_ref__` | 3 | PYLIFE | capsule over the record | - | FE protocol |
| `Table.__init__` | 15 | CONVERT | validate `initial/maximum` (messages), create table, make its export record, finalizer | `table_new`, `table_export`, `table_free` | limits check CORE (return codes); object FE |
| `Table._of` | 10 | PYLIFE | a Table pointing at an instance's table, keeps the instance | - | owner edge CORE |
| `Table.size/maximum/__len__/_index` | 3+4+2+5 | CONVERT | pass-through plus the IndexError text (calls `size` twice) | `table_size`, `table_maximum` | BIND |
| `Table._writers_list` | 2 | PYLIFE | where the keep-alive list is | - | CORE owner edge |
| `Table.set` | 26 | LOGIC | resolve method -> record, `_usable`, kind, `funcref` present, `flags & 16` message, remember keeper in writers, `table_set` | `table_set` | CORE: `wx_table_set(table, i, export_rec, msg)` doing the checks and the edge. The extension has `Table_set` (52 lines) with the same rules |
| `Table.get` | 18 | LOGIC | `table_get_ref`, then **scans** exports of the instance and of every writer to find the name of the slot's function (`table_is`) | `table_get_ref`, `table_is` | CORE registry (`owners_registry.md`): owner by lookup, name by the export list |
| `Table.grow` | 9 | CONVERT | error text from size/maximum | `table_grow` | message CORE |
| `Table.__wasmext_ref__/__wasmext_keep__` | 5+6 | PYLIFE | capsule; `writers.append` | - | CORE edge |

### A.3 Rows only when the host has WASI (probe1 / p2)

| name | lines | cat | what it does | C entry | where |
| --- | ---: | --- | --- | --- | --- |
| `WasiTerminated/WasiExit/WasiSignal`, `_SIGNALS` | 33 | BOILERPLATE | exceptions, signal names | - | FE (names); CORE gives code/signal |
| `Instance._ended` | 8 | LOGIC | `wasi_end` -> `WasiExit(code)` / `WasiSignal(n)` | `wasi_end` | CORE `wx_error_describe` (kind=exit/signal + value) |
| `_Config` | 12 | BOILERPLATE | ctypes mirror of `<name>_config` (13 fields; p2 adds 7) | the struct | BIND (generate) |
| `_STDIN/_STDOUT/_CLOCK/_RANDOM` (+ `_SOCKETS/_HTTP` p2) | 4 | PYCALLBACK | CFUNCTYPE shapes of the hooks | hook typedefs in `api.h` | BIND |
| `_strings` | 11 | CONVERT | list of str -> `char *[]`; rejects a bare str and NUL | - | CONVERT, but the NUL/str rules are CORE (`wx_config_arg`) |
| `_WASI_ERRNO` | 4 | CONVERT | OSError errno -> WASI errno (10 entries) | - | CORE (the WASI errno table is the core's: the hook could return a host errno) |
| `_write_all`, `_closed` | 9+4 | PYCALLBACK | write to a Python stream until all is written; closed stream = EBADF | - | FE (Python streams) |
| `_Streams` | 49 | PYCALLBACK | which Python object is stdin/stdout/stderr, text vs binary, incremental utf-8 decoder, bytes or callable or None | - | FE; this is the genuine Python glue of WASI |
| `_wasi_config` | 115 (p1) / 157 (p2) | split: ~59 (p2: ~71) LOGIC, rest PYCALLBACK | first part: validate the `wasi=` dict (unknown keys, env names, preopens/readonly rules, `realpath` + `isdir`, NotADirectoryError) and fill the struct; second part: the Python hooks (stdin/stdout/clock/random, p2: sockets/http policies) with the exception -> `failed()` -> errno or HOOK_TRAP and `owner._pending` | `store_new(config)` | validation: CORE builder (`wx_config_*`, C.2); the exe's CLI (`--dir host::guest:ro`) and the extension have their own copies; hooks: FE |
| `Host` + `Host.__imports__` + `_original` | 13+11 | BOILERPLATE / CONVERT | exposes the library's own WASI calls (`host_call<k>`) as Python callables | `host_call<k>` | BIND |
| `Instance.__host__` | 3 | BOILERPLATE | | - | BIND |

### A.4 What the wrapper does NOT do any more (already in C)

`api_enter` (runtime init per thread), the entry stack, `status` of the last call, store `active` counting and the closed check in `rich_call0`, the `funcref_call<k>` trampolines, table new/grow/set/is/get_ref, the record filling (`export_find`), the C-to-C link of a function, memory pin counting. Those are the good parts.

---

## Part B. The library

### B.1 What `<name>_api.h` exposes (rich: 46 functions; list)

Always: `store_new(config, &error)`, `store_close`, `store_closed`, `store_free`, `abi`, `runtime`, `new(store, &error)`, `free`, `thread_free`, `traps`, `traps_use` (only when the module shares tables), `instantiate`, `trap_message(code)`, `trap_is_exception(code)`, `wasi_end(m, &value)`, `status(m)`, `status_ptr(m)`; types `<name>_t`, `<name>_store_t`, `<name>_config` (args, env, dirs, dirs_readonly, hooks stdin/stdout/clock/random/sleep, user; p2 adds sockets/http/dns/tcp/udp), `<name>_export` (the 12-field record); trap codes `TRAP_HOST 0x7000, NO_MEMORY 0x7001, ENDED 0x7002, LINK_ERROR 0x7003, CLOSED 0x7004, HOOK_TRAP 0x10000, TRAP_LINKED 0x20000`.

Per import (index k from the order of the module): `set_import<k>(m, fn, user)` + typedef `import<k>_fn(user, args..., [outs...], int *trapped)`; `link_import<k>(m, rec, msg, cap)`; WASI: `host_call<k>` (the library's own implementation of that import). Per global import j: `link_global_import<j>`, `set_global_import<j>` (immutable only); `link_memory_import<j>`; `link_table_import<j>`; `unlink_tables`.

Tables (only if the module shares tables): `table_new/free/size/maximum/grow/export`, `table_is_null/is/set/get_ref`, `funcref_copy/free/same/hash/type/export`, `funcref_call<k>` for each function type of the module.

Per export: `<fn>(m, args..., [outs])` (a single number result is returned directly and the code is in `status`), `memory_<name>(m, &size)` and `memory_<name>_pin(m, pin)`, `global_<name>` / `set_global_<name>`, and one `export_find(m, name, owner, &record)`. With tags: `exception(m, &tag, values, cap, &count)`, `value` struct.

### B.2 What is implemented where

- `wasmext_glue.h` (362 lines, hand-written, no Python): trap codes, the export record and its versioning (`wasmext_export_ok/seal`), the layout checks (`WASMEXT_LAYOUT`), table helpers (`wasmext_table_new/free/grow/export`, `wasmext_function_export`), the entry stack for traps (`wasmext_traps`, `enter/leave/trap/join`, `WASMEXT_ENTER_SHARED/REENTRANT/PLAIN`), the signal-chain and the stack-limit code for the extension (`WASMEXT_CHAIN`, `WASMEXT_STACK_LIMIT`; actually in `<name>_glue.h`).
- `<name>_glue.h` (231 lines for rich, 543 p2, 1271 probe1): the instance struct, `host<k>` structs, `exp_ref[]` and `glue_funcref(i)`, the typed callers (`call<i>`, `callref<k>`), `ref_type` (matching a funcref's type by hash), `link_func<k>/global/memory/table`, `glue_instantiate/initialize/free`, the `w2c_env_<fn>` thunks that turn `*trapped` into a trap. No Python.
- `<name>_shared.c` (348 lines for rich; 181 add, 344 tbl, 422 ks, 302 imp, 652 p2, 1226 probe1): the wrappers of the above with exact names of `api.h`, `api_enter` (thread setup), the store and instance structs (store has `closed`, `active`, `instances`), pins, `export_find`, table functions.

### B.3 Capability matrix (the logic that does or does not have a C counterpart)

"Ext" is from reading emitted names and the lines of `rich_py.c` I quoted; I did not read the rest of `_gen.py`.

| Capability | In the C API now? | In the wrapper? | In the extension? |
| --- | --- | --- | --- |
| Link function import to another instance's export | YES, C to C only (`link_import<k>`, checks ABI, kind, signature string, sets `fn`/`user`) | yes, AND repeats the ABI/kind/signature checks in Python, and a Python bridge for extension peers (`_function_of`) | yes (`lookup_import`, `as_export_ref`, `rich_link_func0` direct, `py_import<k>`/`py_link<k>` for callables) |
| Link global / memory / table import | YES (`link_*_import<j>`, `set_global_import<j>` for immutable values) | yes; mutability rule and value type check in Python | yes (own code) |
| Resolve imports by NAME from a user dict, required/optional rule, `None` = nothing, WASI default | NO (only by index; whether an import is WASI is only in the generated Python tables) | yes (`_find_import`, `Instance.__init__`, `_nothing`) | yes (`lookup_import`, `Instance_new`) |
| Run-time description of the module (names, kinds, types, flags) | NO (header only; `export_find` is an `if strcmp` chain) | tables generated in Python | tables generated in C |
| Enumerate exports | NO | `__exports__` from the generated tables | `Instance_exports` from generated tables |
| Tables: new, size, max, grow, export record | YES | wrapper (limits messages) | yes (`Table_new`, `Table_grow`, ...) |
| Tables: set with checks (kind, ABI, shares tables) | slot write only (`table_set`, no checks) | `Table.set` 26 lines | `Table_set` 52 lines |
| Tables: get, who owns the function, name of the function | `table_get_ref` (a copy) and `table_is`; no owner, no name | `Table.get` scans exports of instance and writers | `Table_get`, `table_find_function` scan likewise |
| Function objects: call, eq, hash, type, signature | call/eq/hash/type YES; signature only through the generated `_REF_TYPES` | `Function` | `Function_*` |
| Funcref as parameter/result of an export | pointer passed; checks NO | `_funcref_arg` (checks, `_refs`) | its own |
| Globals typed get/set | YES | property | getset |
| Mutable global as import | link YES | yes | yes |
| Memory view and pin (`memory.grow` -> -1 while viewed) | YES (`memory_*_pin`, counts) | view lifetime via `weakref.finalize` | a second implementation of the pin (`mem_pins`, `memory_can_move`, `Memory_getbuffer`) |
| Entry stack for traps across modules | YES (`traps`, `traps_use`, glue macros) | `_share_traps` rendezvous | `attach_traps` rendezvous |
| Trap code -> description | message, `is_exception`, `exception(tag, values)`, `wasi_end` | `_error`, `_ended`, `_uncaught`: code -> Python exception, 3 places | `raise_trap_code`, `raise_foreign_trap`; the exe prints its own message and uses 134 |
| Exception raised in a host function | only `*trapped` and code HOST: the error is "the host's" | `_pending` on Instance and Store, searched through `_owners` | PyErr, plus it reads the wrapper's `_pending` BY NAME (`raise_trap_code`) |
| Owners / keep-alive | only the field `owner` (opaque `void*`) in the record | `_owners`, `_writers`, `_table_owners`, `_refs`, `Table._writers`, `Function._keeper`, `_Reference._owner`, `buffer._instance`, `_callbacks` | `writers`, `hold<k>`, `store_obj`, Function keeper, capsules |
| Registry of owners (design) | NO (`owners_registry.md`, nothing built) | - | - |
| Store: create, close (refused while a call runs), free (refused while instances live), closed check on every call | YES | forwards | likewise |
| Host / WASI config struct and hooks | YES (struct, hooks, `host_call<k>`) | validates and fills it (59-71 lines) and provides the hooks (Python streams) | its own | 
| Host config in the exe | NO: the exe does not use the API; own CLI parse and `fusedwasi_p2_state` filling | - | - |
| Host function from a front-end callable | typed `set_import<k>` only (one function type per import) | CFUNCTYPE per signature | `py_import<k>` per import |
| Tags / uncaught exception values | YES (`exception`) | converts | converts |
| Thread setup | YES (`api_enter`, `thread_free`) | none needed | `WASMEXT_PY_THREADS` setup in C |

Logic with NO counterpart in the C API (the list that matters): resolution of imports by name and the required/optional rule; the module description; checks of `table_set` and of funcref parameters; owner/keep-alive graph and owner lookup (so `Table.get` scans); the pending host exception and the search through linked instances; the code -> error-kind map; the validation of the WASI configuration; the unwinding of a failed instantiation (`unlink_tables` is called by the front end).

---

## Part C

### C.1 Totals per category

Lines of each generated wrapper by dominant category of each function (methods counted separately; "gaps" = lines outside any function/method: class shells, imports, comments, blanks, the data tables; all put under BOILERPLATE; of the 263 gap lines in `rich`, 157 are blank and 19 comment, 87 code). The split of `_wasi_config` is by my reading: its option-validation part counted as LOGIC (59 lines; p2: 71), the hook part as PYCALLBACK. Script: `/tmp/claude-0/audit/spans.py`.

| Module | file lines | CONVERT | PYLIFE | PYCALLBACK | LOGIC | BOILERPLATE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| add (no shared tables) | 835 | 124 | 62 | 84 | 214 | 352 |
| addsh / rich / tbl (shares tables) | 1047 | 203 | 104 | 84 | 258 | 399 |
| probe1 (wasip1) | 1142 | 146 | 62 | 202 | 281 | 452 |
| p2 (wasip2 core module) | 1189 | 146 | 62 | 232 | 293 | 457 |

(sums are one more than the file because the AST counts the last line; rounding aside.) Read this as: LOGIC is 25 to 26 % of every wrapper, CONVERT 11 to 19 %, PYLIFE 5 to 10 %, PYCALLBACK 7 to 20 %, BOILERPLATE 34 to 42 %. Rows that are LOGIC even for `add` (214 lines) are `Instance.__init__`, `_error`, the four `_*_import` methods, `_share_traps`: all of them exist for modules with no imports at all, since the template is not trimmed. Only the PYLIFE+PYCALLBACK+CONVERT part (about 35 %) is irreducible Python by nature; I would expect a thin wrapper of about 350 to 450 lines for `rich` (estimate, not measured).

C-side totals for comparison (lines, `api.h` / `shared.c` / `glue.h`): add 91/181/175, rich 135/348/231, tbl 129/344/230, imp 135/302/275, ks 146/422/319, p2 147/652/543, probe1 246/1226/1271.

### C.2 Proposed core API (names, signatures)

Principles: (a) everything module-independent is written ONCE in plain C and has no per-module prefix beyond a macro (`WX_PREFIX`, so that two libraries do not export the same symbol, as now); (b) everything module-specific is reachable through a DESCRIPTOR, so a front end does not need generated tables; (c) typed entries stay for the hot path; (d) errors are codes plus a kind plus a message, the front end maps kind -> exception class once.

```c
/* ---- value and descriptor (one place that says what a module is) ---- */
typedef struct { uint8_t type; /* 0x7F i32 .. 0x7B v128, 0x70 funcref */ union { int32_t i32; int64_t i64; float f32; double f64; uint8_t v128[16]; const void *ref; } as; } wx_value;
typedef struct { const char *module, *name; uint8_t kind /*FUNC TABLE MEMORY GLOBAL*/, wasi, mutable_; uint8_t nparams, nresults; const uint8_t *params, *results; } wx_import_desc;
typedef struct { const char *name; uint8_t kind; /* + type, flags */ ... } wx_export_desc;
typedef struct { uint32_t abi; const char *host; /* "", wasm32-wasip1, ... */ int shares_tables, has_tags, wasi;
                 size_t nimports; const wx_import_desc *imports; size_t nexports; const wx_export_desc *exports;
                 size_t nreftypes; const wx_reftype_desc *reftypes; } wx_module_info;
const wx_module_info *WX(info)(void);

/* ---- owners: refcount in the core, retain/release from the front end ---- */
typedef struct { void *user; void (*retain)(void *user); void (*release)(void *user); } wx_owner_ops;
typedef struct wx_owner wx_owner;                         /* core object, refcounted by the core */
wx_owner *WX(owner_new)(void *user, const wx_owner_ops *ops);   /* calls retain(user) once */
void      WX(owner_ref)(wx_owner *);  void WX(owner_unref)(wx_owner *);   /* last unref calls release(user) once */
/* edges: "A keeps B alive" is a core fact, not a Python list */
int  WX(instance_keeps)(WX(t) *a, wx_owner *b);           /* writers / refs / owners */
wx_owner *WX(instance_owner)(const WX(t) *m);              /* lookup by module_instance (the registry) */
void WX(instance_set_owner)(WX(t) *m, wx_owner *o);

/* ---- store, config ---- */
WX(store_t) *WX(store_new)(WX(config) *cfg, int *errno_);  /* as now */
WX(config) *WX(config_new)(void);
int WX(config_arg)(WX(config) *, const char *s, char *msg, size_t cap);          /* NUL / type rules once */
int WX(config_env)(WX(config) *, const char *k, const char *v, char *msg, size_t cap);
int WX(config_preopen)(WX(config) *, const char *guest, const char *host, int readonly, char *msg, size_t cap);   /* realpath + isdir */
void WX(config_stdout)(WX(config) *, int (*write)(void *, int fd, const uint8_t *, size_t), void *user);  /* + stdin, clock, random, sleep, sockets, http */
void WX(config_free)(WX(config) *);

/* ---- instantiate with a resolver: the whole linking loop in C ---- */
typedef struct { int kind; /* WX_RES_EXPORT, WX_RES_HOST, WX_RES_VALUE, WX_RES_ABSENT, WX_RES_NONE */
                 const WX(export) *record; wx_host_fn fn; void *user; wx_owner *keep; wx_value value; } wx_resolved;
typedef int (*wx_resolver)(void *ctx, const wx_import_desc *d, size_t index, wx_resolved *out, char *msg, size_t cap);
int WX(instantiate)(WX(t) *m, wx_resolver r, void *ctx, char *msg, size_t cap);   /* 0, or a code; on failure unlinks what it linked; fills msg for LinkError */
/* single-step version for a C host: */
int WX(link)(WX(t) *m, size_t import_index, const wx_resolved *r, char *msg, size_t cap);

/* ---- host functions: ONE callback shape for every signature ---- */
typedef void (*wx_host_fn)(void *user, const wx_value *args, wx_value *results, int *trapped);
/* typed set_import<k>(...) stay for C hosts and for the hot path; the generated C thunk <k> converts typed <-> wx_value */
wx_pending *WX(pending_new)(void);                          /* one per store */
void  WX(pending_set)(WX(t) *m, wx_owner *error);           /* the host function failed: keep this opaque error (retained) */
wx_owner *WX(pending_take)(WX(t) *m);                       /* searches m, its store, and the instances it is linked to, as `_error` does */

/* ---- calls ---- */
int WX(call)(WX(t) *m, size_t export_index, const wx_value *args, wx_value *results);   /* generic, checked against the descriptor */
/* typed <export>(...) unchanged */
int WX(error_describe)(const WX(t) *m, int code, wx_error *out);    /* kind: TRAP, HOST, NO_MEMORY, CLOSED, EXIT(code), SIGNAL(n), EXCEPTION(tag, values); text */

/* ---- exports, tables, functions ---- */
size_t WX(export_count)(const WX(t) *m);  int WX(export_find)(...);  /* as now, plus by-index */
int WX(table_new)(uint32_t initial, uint32_t max, WX(table) **out, char *msg, size_t cap);   /* limits checked */
int WX(table_set)(WX(table) *, uint32_t i, const WX(export) *func, char *msg, size_t cap);    /* kind, ABI, shares-tables checks + owner edge */
int WX(table_get)(const WX(table) *, uint32_t i, WX(func) **out);                             /* refcounted function object with owner and name */
WX(func) *WX(func_from_export)(const WX(export) *, char *msg, size_t cap);                     /* funcref parameter */
int WX(func_call)(WX(func) *, const wx_value *args, wx_value *results);                        /* + typed funcref_call<k> */
const wx_signature *WX(func_signature)(const WX(func) *);  const char *WX(func_name)(const WX(func) *);
void WX(func_ref)(WX(func)*); void WX(func_unref)(WX(func)*);

/* ---- memory (exists) ---- */
/* memory_<name>(m,&size), memory_<name>_pin; add by-name generic: */
uint8_t *WX(memory_view)(WX(t) *m, const char *name, size_t *size);  int WX(memory_pin)(WX(t) *m, const char *name, int pin);
```
`WX(x)` = `<name>_x` for the shared library, as now. `wx_owner` and `wx_value` and the descriptor structs are in a common header, identical in all libraries (versioned by the existing ABI number).

#### The owner handle with ctypes (the main design question)

The core holds `wx_owner{user, retain, release}`, count in the core, and never looks into `user`.

- Extension: `retain = Py_IncRef`-like, `release = Py_DecRef`-like, `user = PyObject *`.
- ctypes: `user = id(obj)` and the two function pointers can be the interpreter's own exported functions `Py_IncRef` and `Py_DecRef` taken from `ctypes.pythonapi` (`ctypes.cast(pythonapi.Py_IncRef, c_void_p).value`). No Python callback and no per-owner object: the same two pointers serve every owner. **I tested this** (`/tmp/claude-0/audit/own/t.py`, Python 3.13.16, a 3-line C library holding `(user, retain, release)`): under `ctypes.PyDLL` the object stays alive while held (refcount 3), and is freed after `drop()`; under `ctypes.CDLL` the SAME code aborts the process with "PyThreadState_Get: the function must be called with the GIL held" at the `Py_DecRef` that frees the object (the `Py_IncRef` did not complain). That is the same thing `tests/test_wasi_across_instances.py::test_a_python_callback_in_a_table_function` and `thin_glue.md` describe from the other side: `CDLL` releases the GIL around every call.
- Consequence for the design: a `release` may run at any call that drops an edge (`table_set` overwriting a slot, `instance free`, a store close). Choose one of:
  1. Calls that can drop an edge go through `PyDLL` (they run no wasm, so keeping the GIL costs nothing); calls into wasm stay on `CDLL`. Needs a second `CDLL`/`PyDLL` handle to the same library, and a rule in the header: "functions marked `/* may release */`". Simplest; I would start here.
  2. The core never calls `release` itself: it puts it in a queue (`wx_owner_drain(store)` returns them), and the front end drains after each call with the GIL held. Works for any front end that cannot call back at an arbitrary point (also Rust, Go).
  3. `retain/release` are `CFUNCTYPE` Python callbacks: ctypes takes the GIL when they are called, so it is safe from `CDLL`, but it costs a callback per edge and runs Python in finalizers during GC; not recommended.
- Limit to say out loud: a guest `table.set` / `table.copy` / `table.init` writes into a table without the core being told, so edges cannot be tracked per slot. Edges stay coarse as today ("the table keeps the writers alive as long as it lives"), which is what the registry note already assumes.
- The owner of a record must stop being "a `PyObject *` by convention" (`ctypes.cast(record.owner, py_object)` in the wrapper, `Py_INCREF(e->owner)` in the extension): with `wx_owner *` a plain C host works with both, and the two Python front ends stop reaching into each other's objects (`_pending`, `__exports__`).

### C.3 Can the wrapper be generated from the API (a binding by construction)?

Mostly yes, and it is nearly so already: `_ctypes_gen.py` is a 1536-line template filled from the same model that `_shared.py` uses to write `api.h`. What makes the current output NOT a binding is that (1) it contains the logic above (about 25 %), and (2) the C names and signatures are written into Python tables beside the header, a second hand-kept copy (`_Export`, `_Config`, `_EXPORTS`, `_IMPORTS`...).

To make it a binding by construction it needs:

1. Descriptor in the library (`wx_module_info`), so one static Python file (`wasmext_ctypes.py`, shipped once, ~300-450 lines of CONVERT/PYLIFE/PYCALLBACK) builds `Instance`, `Table`, `Function` classes at load time from the descriptor. The per-module generated part reduces to the `.pyi` and a stub with the name and the library path. (The generator could also keep emitting the descriptor as Python literals for speed, from the same model object that writes the C: one source.)
2. Structs generated from the header, not typed by hand: `_Export`, `_Config`, `wx_value`, the hook typedefs. The header is machine-written and regular, so either the generator writes both from one model (already the case) or a small parser reads `api.h`.
3. All semantics behind C entries (C.2): resolver-based `instantiate`, `table_set` with checks, `func_from_export`, `pending_*`, `error_describe`, config builder, owners. Otherwise the generated code needs a case for each rule.
4. A uniform host-callback shape (`wx_host_fn` with a `wx_value` array) so a single `CFUNCTYPE` serves every import; keep the typed path for numbers only if the benchmark says so (the current `fast_callback` exists for that reason: unmeasured here).
5. The hot path stays generated: `_fast_method` (an `exec` of a specialised method per signature) is a binding by nature and needs only the export's C name and types from the descriptor.
6. What stays hand-written Python and cannot be derived: value conversion rules and their messages, the exception classes, `memoryview` and its finalizer, `Caller`, the `Store` streams (`_Streams`, ~100 lines, the real Python part of WASI), the capsule protocol while the extension and the wrapper must interoperate.

### C.4 Ordered plan of small moves (behaviour and tests unchanged)

Safety net: about 250 tests already run on both front ends (`front_end` fixture in `tests/conftest.py`, params `extension` and `ctypes`; files: test_extension, test_host, test_linking, test_table_class, test_tables, test_wasi, test_wasi2, test_wasi_fs, test_store_shared, ...). Before step 1, record: the line counts above, the output of the full suite, and the call benchmark of `docs/context_concept.md`. After each step re-run both and re-count `spans.py`.

| # | Move | Removes (wrapper) | Risk |
| --- | --- | ---: | --- |
| 0 | Delete the Python repeat of checks the C already does: signature `expected` string and `_usable` in `_function_import`, `_global_import` etc. (same message already produced by `rich_link_func<k>` / `link_global<j>`) | ~10 | Low. The tests compare messages; check that the C message is identical (it looked identical for the function case: "import env.log is a function i>: the export given is another one (...)") |
| 1 | `table_set` and `funcref_from_export` in C with the checks and messages (kind, ABI, shares-tables); both Python `Table.set` and `_funcref_arg`, and the extension's `Table_set`, call it | ~35 wrapper, ~50 extension | Low to medium: the long message text is in tests (`test_table_class`). First real "written once" |
| 2 | `error_describe(code)` in C: kind + message + exit value/signal + uncaught exception; the three Python maps (`_error`, `Function.__call__`, `_ended`/`_uncaught`) and `raise_trap_code` use it | ~40 | Low. This also fixes `Function.__call__` ignoring `_pending` (see A.2) if the same map is used: a behaviour change to decide on first |
| 3 | `pending` slot in the core: `pending_set` / `pending_take` with the search through linked instances; host callbacks write it through the C entry; extension stops reading `_pending` by attribute | ~25 | Medium: touches the exception path across front ends; test `test_wasi_across_instances` and the host-exception tests |
| 4 | Module descriptor `wx_module_info`; wrapper loads names/types from the library instead of generated tables (keep generating them in parallel and assert equal in a test, then drop) | 25 long lines, plus the generator's side | Low. Also enables `export_count` / enumeration |
| 5 | `wx_config_*` builder; wrapper's `_wasi_config` validation, the extension's, and the exe's `--dir/--env` parse call it | ~60-70 wrapper | Medium: message texts and `realpath` timing are tested (`test_wasi_fs`); the exe has a different error format |
| 6 | Owners: `wx_owner` + `instance_keeps` + `instance_owner`, `PyDLL` for the entries that may release; replace `_owners`, `_writers`, `_table_owners`, `_refs`, `Table._writers`, `Function._keeper` | ~80 | HIGH. This is the registry of `owners_registry.md`; follows its own 5 steps; must settle the open GIL issue first (the known failing scenario) and the "guest can write to tables" limit. Not before 1 to 4 |
| 7 | `instantiate(resolver)` in C: the loop of `Instance.__init__`, unlink on failure, "missing import" message from the core | ~60 | Medium. After 6 (needs the owner arguments), but could be done before with `keep=NULL` |
| 8 | Uniform host callback (`wx_host_fn`) and `wx_call` | ~80 (`_set_import` 75 + a part of `_call`) | Medium: performance of host calls; measure with the existing benchmark before accepting |
| 9 | Extension: replace its second pin implementation by `memory_<name>_pin`, its `attach_traps` by the shared rendezvous | extension only | Low |
| 10 | Make the executable call the API for store and config instead of filling `fusedwasi_p2_state` by hand | exe only | Medium: the exe works without a registry of libraries; only after 5 |
| 11 | Single static `wasmext_ctypes.py` + generated stub (C.3) | most of the template | Medium: the packaging ("nothing of wasmext is needed to run this") must keep holding: ship the static file next to the library |

Quick wins in order of value per risk: 0, 4, 2, 1. Moves 6 and 7 are the ones that change the shape.

### C.5 What I could not determine

- The extension: I did not read `_gen.py` or most of `rich_py.c`; its rows in B.3 come from names, from 200 lines I quoted (`attach_traps`, `raise_trap_code`, `Instance_new`, `py_link0`), and from `docs/owners_registry.md`. Statements such as "`Table_set` has the same checks" and "the extension re-implements the pin" are from names/struct fields (`mem_pins`, `memory_can_move`, `Table_set` 52 lines) and not from reading the bodies.
- Speed: nothing measured. The cost of a uniform value-array callback, of `PyDLL` versus `CDLL` entries, and of the extra step through `wx_call` on the hot path is unknown. The wrapper's own fast paths (`_fast_method`, `fast_callback`) suggest ctypes overhead matters.
- The GIL failure of `test_a_python_callback_in_a_table_function`: I did not reproduce it; I only showed the `CDLL` GIL-release effect on a `Py_DecRef` from C. Whether that is the cause of that test is not established.
- `wasm32-wasip2` was built from a core module with p2 imports (`tests/data/wasi2_probe.wat`), not a real component or the programs in `tests/data/wasi2_real`; p2 sockets/http policy hooks were read in the template (`_NET_CONFIG_P2`) but their behaviour was not run.
- I did not run the test suite, nor import the built wrappers, nor check that all messages in the plan are character-identical between C and Python (only for the function-link case, by reading). The claim "`C message equals Python message`" for global/memory/table links is not checked.
- Free-threaded builds, sub-interpreters, Windows/macOS paths (`WASMEXT_CHAIN`, `pthread_sigmask`) were not looked at; the per-interpreter capsule rendezvous and `id(obj)` as owner address depend on them.
- Whether the line-count targets ("350 to 450 lines for `rich`") are reachable is an estimate from the category totals, not a measurement.
- `wasmext_glue.h` lines 1-20 and the rest of `rich_glue.h`/`p2_glue.h` I read for `rich`; the larger WASI glues (probe1 1271 lines, p2 543) and `wasi_python.h`/`wasi2_python.h` I did not read.
