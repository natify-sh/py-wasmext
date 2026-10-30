---
title: Instances
kind: spec
id: S0003
status: implemented
superseded_by:
related: []
owner: maintainer
updated: 2026-10-30
---

# S0003 Instances

## Summary
An instance is a static, module-independent core plus a generated binding of the module to it. This is step 3 of layer 1 in [layers.md](../layers.md). It builds on step 1 (the model and the descriptor) and step 2 (the store, the errors, the host).

Before this step an instance was written three times, each for its front end, over the same wasm2c module:
* the glue `<name>_glue.h` (generated per module from `_gen.py`): the structure of the instance, the typed functions `result f(void *instance, parameters..., int *trapped)` for every export, the host functions an import calls (`fn[slot]`, `user[slot]` in a structure per import module), the trampolines that turn a `trapped` into a `wasm_rt_trap`, the accessors of memories, tables and globals;
* the library (`<name>_shared.c`, `_shared.py`): a C API with a different shape for every module (`<name>_set_import<k>`, `<name>_link_*`, `<name>_call<i>`, `<name>_memory_<n>_pin`);
* the front ends (`<name>_py.c`, `_ctypes_gen.py`), which each re-implement the rules: which import is set, the status of the last call, the pins.

The shared record of an export, `wasmext_export` in `wasmext_glue.h`, already existed and is versioned (`abi`, `floor`, `size`). It is what an instance gives another instance, so it stays.

The core knows nothing of the module. The binding names the symbols that wasm2c made for this module, so it is generated from the model of step 1. No rule is decided in the binding.

## Goals / Non-goals
* Goals:
  * One instance core for every module and every front end: `src/wasmext/c/wasmext_instance.h`.
  * One generated binding per module: `generate_binding` in `src/wasmext/_binding.py`.
  * Function exports, `instantiate` (with a trap in the start function), a generic `call` for i32, i64, f32, f64 and v128, several results, no result.
  * Function imports by index of the descriptor, with one uniform host function and a typed fast path.
  * WASI 0.1 and 0.2 imports answered by the host of the store.
  * Exported memories (view, grow, pin) and exported globals (get, set).
  * The record of an export and imports given such a record: two instances linked in C.
* Non-goals (this step):
  * Tables, `funcref` and `Function` (step 5), `externref` (step 6), tags and exceptions across instances (step 7), the shared store across artifacts (step 8).
  * The owners: an owner handle exists here only as the `owner` of the export record, an opaque pointer (step 4 builds the registry).
  * Any change to an existing generator (rule of [layers.md](../layers.md)): the new binding is its own emitter beside the old ones.
  * The Python hooks of `wasi_python.h` (they become plain C hooks with a `user`, in the step of the front end).
  * The `_start` driver of the executable (the exe step).
  * More than one memory.

## Interface

### Static core (`src/wasmext/c/wasmext_instance.h`)
Value, one shape for every type. It is passed by pointer or in an array, never by value (a union in a signature differs between platforms).
```c
typedef struct {
    uint8_t type;            /* byte of the binary format: 0x7F i32, 0x7E i64, 0x7D f32, 0x7C f64, 0x7B v128 */
    union { int32_t i32; int64_t i64; float f32; double f64; uint8_t v128[16]; void *ref; } as;
} wasmext_val;
```
A v128 is 16 bytes in the order of WebAssembly memory (little-endian). The types 0x70 funcref and 0x6F externref in `type` and `as.ref` were added by S0005 and S0006.

Host function, one shape for every import:
```c
typedef int (*wasmext_host_fn)(void *user, const wasmext_val *args, wasmext_val *results);
```
`args` and `results` have the counts and types of the signature in the descriptor. 0 is success. Any other answer is a failure of the host, which keeps its own error: the call traps with `WASMEXT_TRAP_HOST`. The answer `WASMEXT_TRAP_LINKED` + code means "a trap of another instance, pass it through".

The typed fast path is `result f(void *user, parameters..., int *trapped)`. `*trapped` is read as the answer of a uniform function.

Operations. All return 0, the code of a trap (> 0) or a negative code of the API.
```c
wasmext_instance *wasmext_instance_new(wasmext_store *store, const wasmext_binding *binding, int *error);
int wasmext_instance_import_find(const wasmext_instance *i, const char *module, size_t module_n, const char *name, size_t name_n); /* index or -1 */
int wasmext_instance_bind_func(wasmext_instance *i, uint32_t import, wasmext_host_fn fn, void *user);
int wasmext_instance_bind_typed(wasmext_instance *i, uint32_t import, void *fn, void *user);
int wasmext_instance_bind_export(wasmext_instance *i, uint32_t import, const wasmext_export *e);
int wasmext_instance_bind_global_value(wasmext_instance *i, uint32_t import, const wasmext_val *v);
void *wasmext_instance_import_owner(const wasmext_instance *i, uint32_t import);
int wasmext_instance_instantiate(wasmext_instance *i);
int wasmext_instance_export_find(const wasmext_instance *i, const char *name, size_t n, int kind); /* index or -1 */
int wasmext_instance_export_record(wasmext_instance *i, uint32_t index, void *owner, wasmext_export *out);
int wasmext_instance_call(wasmext_instance *i, uint32_t index, const wasmext_val *args, uint32_t n_args, wasmext_val *results, uint32_t n_results);
int wasmext_instance_wasi_end(const wasmext_instance *i, uint32_t *value);
int wasmext_instance_memory(wasmext_instance *i, uint32_t index, wasmext_memory_view *out);
int wasmext_instance_memory_pin(wasmext_instance *i, uint32_t index, int pin);
int64_t wasmext_instance_memory_grow(wasmext_instance *i, uint32_t index, uint64_t delta);
int wasmext_instance_global_get(wasmext_instance *i, uint32_t index, wasmext_val *out);
int wasmext_instance_global_set(wasmext_instance *i, uint32_t index, const wasmext_val *value);
int wasmext_instance_status(const wasmext_instance *i);
int wasmext_instance_free(wasmext_instance *i);
```
* `index` of an export is an index into `descriptor->exports`. `import` is an index into `descriptor->imports`.
* `error` of `new` is an errno: `EINVAL` (null store or binding), `EBADF` (store closed), `ENOMEM`.
* `kind` of `export_find` is a `WASMEXT_DESC_*` value.

Memory view:
```c
typedef struct { uint8_t *base; uint64_t size; uint64_t pages; uint64_t max_pages; uint32_t page_size; int is64; } wasmext_memory_view;
```

Thread set-up, one flag for the artifact: `wasmext_thread_ready()`, `wasmext_thread_free()`. Exactly one file of an artifact defines `WASMEXT_DEFINE_THREAD_STATE` before it includes the header.

The instance (fields by the order in the header):
```c
typedef struct wasmext_instance_s_ {
    const wasmext_binding *binding;
    wasmext_store *store;
    void *module;                 /* the structure of wasm2c (and, after it, the slots of the imports) */
    unsigned char *bound;         /* per import: 1 once it has a host function */
    void **owners;                /* per import: the `owner` of the record it was linked to */
    uint64_t (*values)[4];        /* per import: room for an immutable global given by the host (32 bytes; "a funcref is four words" added by S0005) */
    wasm_rt_funcref_t *refs;      /* (added by S0005) per export: the table element that stands for a function */
    wasmext_counter *pins;        /* per export: pins of a memory */
    uint64_t *saved_max;          /* per export: the maximum a memory had before the first pin */
    WASMEXT_MUTEX_T pin_mutex;
    int instantiated;
    wasmext_owner owner;          /* (added by S0004) its handle in the registry of the store, 0 before instantiate */
    wasmext_counter status;       /* the answer of the last call; atomic */
} wasmext_instance;
```

Answers of the API that are not a trap:

| constant | value | meaning |
|---|---|---|
| `WASMEXT_INST_OK` | 0 | |
| `WASMEXT_INST_BAD_EXPORT` | -1 | index out of range, or an export of another kind than the call needs |
| `WASMEXT_INST_BAD_ARGS` | -2 | number or types of arguments or results do not fit the signature |
| `WASMEXT_INST_NOT_INSTANTIATED` | -3 | |
| `WASMEXT_INST_UNSUPPORTED` | -4 | a type or kind the core does not carry |
| `WASMEXT_INST_NOMEM` | -5 | |
| `WASMEXT_INST_BAD_IMPORT` | -6 | index out of range, not a function, or one that the core answers |
| `WASMEXT_INST_TOO_LATE` | -7 | the instance is made already; imports are bound before `instantiate` |
| `WASMEXT_INST_IMMUTABLE` | -8 | a global that cannot be set |
| `WASMEXT_INST_LINK_FAILED` | -9 | an export given for an import does not fit; the text naming the import is in the store (`wasmext_store_error`) |

Added later: `WASMEXT_INST_UNDECLARED_TYPE` -10 (S0005), `WASMEXT_INST_NO_EXCEPTION` -11 (S0007), `WASMEXT_TAB_BOUNDS` -30, `WASMEXT_TAB_FULL` -31, `WASMEXT_TAB_WRONG_STORE` -32, `WASMEXT_TAB_STALE` -33, `WASMEXT_TAB_WRONG_ELEM` -34 (S0005).

### Binding (`wasmext_binding`, made by `_binding.py`)
```c
typedef struct {
    const wasmext_descriptor *descriptor;
    size_t instance_size;                          /* sizeof the structure of the instance that wasm2c made */
    int  (*instantiate)(void *instance, void *host); /* wasm2c's instantiate, a trap caught: 0 or the code (the instance is then freed and cleared) */
    void (*release)(void *instance);               /* wasm2c's free */
    const wasmext_export_binding *exports;         /* descriptor->n_exports entries */
    wasmext_import_slot *(*import_slot)(void *instance, uint32_t import);  /* NULL when the module has no function import */
    void **(*ref_slot)(void *instance, uint32_t import);                   /* what wasm2c reads for a memory or global import; NULL when none */
    void (*call_begin)(void *instance);            /* before each call: forgets how the last one ended; NULL without WASI */
    int  (*wasi_end)(void *instance, uint32_t *value);  /* NULL without WASI */
    const wasmext_ref_type *ref_types; uint32_t n_ref_types;   /* (added by S0005) */
    const wasmext_tag_binding *tags;   uint32_t n_tags;        /* (added by S0007) */
} wasmext_binding;
```
`host` of `instantiate` is the host of the store for a module that has imports the core answers (`WASMEXT_DESC_USES_CORE`), else NULL.

One export of the binding, by the index of the descriptor:
```c
typedef struct {
    int (*adapter)(void *instance, void *function, const wasmext_val *args, wasmext_val *results); /* 0 or a trap code; NULL: no call */
    void *function;                   /* the typed function of wasm2c */
    void *(*address)(void *instance); /* memory: wasm_rt_memory_t *; global: pointer to its value; else NULL */
    void *shim;                       /* function: typed shim for the record that another instance imports; NULL for the others */
    const char *signature;            /* function: parameters, '>', results (i j f d o) */
    void (*funcref)(void *instance, wasm_rt_funcref_t *out);  /* (added by S0005) */
} wasmext_export_binding;
```

One slot per function import. The generated function that wasm2c declares for the import looks at the slot.
```c
typedef struct { wasmext_host_fn host; void *typed; void *user; void *self; /* self: added by S0005 */ } wasmext_import_slot;
```

### What the generator emits (`src/wasmext/_binding.py`)
* `generate_binding(model) -> str`: the C source of `<last>_binding.c`. It declares `extern const wasmext_binding <last>_binding` and uses `<last>_descriptor` (step 1).
* `binding_headers(model) -> tuple[str, ...]`: the headers of fusedwasi (below `fusedwasi/`) that the binding includes for the imports the core answers, dependencies first. A build copies them beside the binding. For WASI 0.1 it is `p1/wasi_p1.h`.
* Inside the C file: `struct <last>_block` (the structure of wasm2c, the slots, and for a module with core imports `fusedwasi_p2_guest guest` and `signalled`), `<last>_instantiate`, `<last>_release`, `<last>_export_bindings`, `<last>_import_slot`, `<last>_ref_slot`, `<last>_call_begin`, `<last>_wasi_end`, `<last>_ref_types`, `<last>_tags`.
* One adapter per distinct signature (`args[]` to the typed call to `results[]`; the other way round for a host import). A module with 40 exports of 6 signatures has 6 adapters.
* The functions that wasm2c declares for the imports (`w2c_<module>_<name>`): they call `fn[slot](user[slot], ...)` or the uniform function, and turn `trapped` into a trap.
* For core imports of WASI 0.1: `<last>_guest_trap`, `<last>_guest_exit`, `<last>_guest_signal`, `<last>_core_setup`. For WASI 0.2: `<last>_guest_realloc` in place of `signal`.
* `GenError` at build time: a 64-bit or shared table import; a module with core imports that does not export `memory`; a WASI 0.2 module that does not export `cabi_realloc`; an import that fusedwasi does not have, or whose signature differs (names both signatures).
* `ImportFact.core_comp` (in `_model.py`) says that the C function that answers a core import takes the component index. `core_call` and `core_header` hold the C function and its header. They are found once in `build_model`.

### Record of an export (`wasmext_export`, `wasmext_glue.h`)
Public and versioned by `WASMEXT_ABI`. Capsule name `WASMEXT_EXPORT`. Kinds: `WASMEXT_FUNC`, `WASMEXT_TABLE`, `WASMEXT_MEMORY`, `WASMEXT_GLOBAL` (0 to 3); `WASMEXT_TAG` (4) was added by S0007.
```c
typedef struct {
    uint32_t size, abi, kind, type, flags;
    void *owner, *address, *instance;
    const char *signature;
    uint32_t runtime;
    const void *funcref;  /* (added by S0005) the wasm_rt_funcref_t of a function, to put in a table */
    uint32_t floor;       /* lowest WASMEXT_ABI of a reader that can use this record (wasmext_export_seal) */
    const void *store;    /* (added by S0004) the store of the exporter */
} wasmext_export;
```
* `flags`: bit 0 global mutable; bit 1 memory is 64-bit; bit 2 memory checked with guard pages; bit 3 function callable with no Python; bit 4 function may be put in a table (added by S0005); bit 5 table elements are externref (added by S0006).
* `wasmext_export_seal(e)` sets `floor`. `wasmext_export_ok(e)` checks the same x, `size >= WASMEXT_EXPORT_BASE` and `WASMEXT_ABI >= floor`.
* `WASMEXT_SINCE_RECORD` is the version of the first record.

### Codes (`wasmext_glue.h`, `wasmext_errors.h`)
* Trap codes: `WASMEXT_TRAP_HOST` 0x7000, `WASMEXT_TRAP_NO_MEMORY` 0x7001, `WASMEXT_TRAP_ENDED` 0x7002, `WASMEXT_TRAP_LINK_ERROR` 0x7003 (in `wasmext_errors.h`), `WASMEXT_TRAP_CLOSED` 0x7004.
* `WASMEXT_TRAP_LINKED` 0x20000 and `WASMEXT_TRAP_OF(TRAPPED)`: the answer of a host function that is the export of another instance: LINKED + the code of its trap.
* `WASMEXT_END_NONE` 0, `WASMEXT_END_EXIT` 1, `WASMEXT_END_SIGNAL` 2: how a WASI program ended. `wasmext_signal_ends(number)` says which signals of `proc_raise` end it.
* `wasmext_error_describe(code)` returns `wasmext_error_info {kind, text}`. Kinds: `WASMEXT_ERR_TRAP` 0, `WASMEXT_ERR_HOST` 1, `WASMEXT_ERR_NOMEM` 2, `WASMEXT_ERR_ENDED` 3, `WASMEXT_ERR_LINK` 4, `WASMEXT_ERR_CLOSED` 5. `WASMEXT_ERR_UNCAUGHT` 6 was added by S0007.

### Descriptor (`wasmext_descriptor.h`, owned by step 1)
Read by the core: `wasmext_descriptor` (`version`, `size`, `flags`, `imports`, `exports`, `memories`, `tables`, `globals`, `start`), `wasmext_import_desc` (`core`, `index`, `type`), `wasmext_export_desc`, `wasmext_functype`, `wasmext_limits`, `wasmext_global_desc`, the kinds `WASMEXT_DESC_FUNC`, `WASMEXT_DESC_TABLE`, `WASMEXT_DESC_MEMORY`, `WASMEXT_DESC_GLOBAL` and the flag `WASMEXT_DESC_USES_CORE`. `WASMEXT_DESC_TAG` and `n_tags` were added by S0007.

### Host slot of the store (`wasmext_store.h`)
* `wasmext_store_set_host(store, host, release, lock)`: once. A second call answers `WASMEXT_STORE_BUSY` and changes nothing. The store owns the host through its arena.
* `wasmext_store_host(store)` returns the opaque host. `wasmext_store_host_lock(store)` returns its lock (`wasmext_rlock`, recursive, `wasmext_rlock_depth`, `wasmext_rlock_release_to`).
* The store stays free of fusedwasi.

## Semantics

### Calls and the store
* Every call enters the store (`wasmext_store_enter`/`leave`). A call into a closed store answers `WASMEXT_TRAP_CLOSED`. `close` of a store refuses while a call is in flight.
* A call checks the index and kind (`BAD_EXPORT`), the counts and types of arguments (`BAD_ARGS`, nothing is called), then `NOT_INSTANTIATED`. A trap leaves the instance usable, as in WebAssembly.
* `status` holds the answer of the last call. It is atomic. With calls from several threads it is the answer of one of them: use the result of the call. (ThreadSanitizer found a real race on `status`.)
* Each thread that calls into a module sets up the runtime once (`wasmext_thread_ready`). The flag is one for the artifact: one file defines `WASMEXT_DEFINE_THREAD_STATE`. `wasm_rt_is_initialized` does not do: a sanitizer installs an alternate stack in every thread and the runtime would take the thread for set up.

### Instantiate
* `instantiate` runs the start function. A trap in it is the returned code. The instance is then not usable and can only be freed. Instances whose instantiation failed take their own functions out of the shared tables (`scrub_tables`).
* An import that is not bound and not answered by the core: `WASMEXT_TRAP_LINK_ERROR` before anything runs, with the name in the text of the store. Bind it and try again.
* A module with core imports in a store with no host: `LINK_ERROR` with "the store has no host for the WASI imports of the module". No crash.
* After a good `instantiate` the instance is registered in the store (S0004).

### Imports
* `bind_func` and `bind_typed` take a function import by index. A function can be bound again until `instantiate`. After it: `WASMEXT_INST_TOO_LATE`. An index out of range, a non-function, an import the core answers, or a NULL function: `WASMEXT_INST_BAD_IMPORT`.
* `bind_typed` cannot check the signature; the descriptor has it. (A reference in the signature is refused with `UNSUPPORTED` by the typed shape since S0005 and S0006; the uniform shape carries it.)
* A failing host keeps its own error. The call traps with `WASMEXT_TRAP_HOST`. A trap of another instance goes through as LINKED + code.
* Reentrant calls (a host function calls back into the module) are supported.
* `bind_global_value` gives an immutable global a value of the host. A mutable global is `WASMEXT_INST_IMMUTABLE` (it is the global of another instance). A wrong type is `BAD_ARGS`.
* `import_owner` returns the `owner` of the record an import was linked to (what keeps the exporter alive; the host's business), or NULL.

### Record of an export and links
* `export_record` fills a `wasmext_export` for a function, a memory or a global. The record is valid as long as the instance is. A closed store answers `WASMEXT_TRAP_CLOSED`; before `instantiate`, `NOT_INSTANTIATED`; a function without a shim, `UNSUPPORTED`. For a function it sets `address` to a typed shim that enters the exporter's store and answers a trap as `WASMEXT_TRAP_LINKED` + its code.
* `bind_export` gives an import such a record. The checks are those that the old glue wrote for each import, once, from the descriptor. All refuse with `WASMEXT_INST_LINK_FAILED` and a reason in the text of the store:
  * the record version (`wasmext_export_ok`);
  * the record is of this store (S0004);
  * a function: the kind and the signature, compared as the letter string;
  * a global: the kind, type and mutability;
  * a memory: the kind, the runtime (`type == sizeof(wasm_rt_memory_t)`), 64-bit (flags bit 1), guard pages (flags bit 2), the pages of the exporter against the minimum of the import, and its maximum against the maximum of the import.
* Instances are linked inside one store (S0004).
* One memory and one global can be shared both ways between two instances.

### WASI imports answered by the host
* For each WASI import the binding writes a typed function `result <last>_wasi_import<k>(void *user, parameters..., int *trapped)`. It calls fusedwasi on the guest of the instance and is put in the slot with `user = block`. For 0.1: `fusedwasi_p1_<name>(&self->guest, args)`, with `unstable_` for the few calls the first snapshot has of its own. For 0.2: `<cname>(&self->guest, [comp,] args)`.
* The block of an instance holds `fusedwasi_p2_guest guest` and `signalled`. `instantiate(block, host)` makes the guest (`fusedwasi_p2_guest_init`, `user = block`, memory 0 bound by the pointers `&memory->data, &memory->size` of wasm2c, read at each access, so a memory that grows needs nothing), sets the hooks, and fills the slots.
* Hooks of the guest: `trap` (the message goes to `host->message`, then the host trap), `exit` (`exited`, `exit_code`, the host trap), `signal` for 0.1 (a signal that ends a process records the number and traps; the others answer success), `realloc` for 0.2 (through the exported `cabi_realloc`), `wait` (from the host).
* A call that ended the WASI program answers `WASMEXT_TRAP_HOST`. `wasmext_instance_wasi_end` says how: `WASMEXT_END_NONE`, `EXIT` (the code) or `SIGNAL` (the number). The end is what the call leaves, as in Wasmtime: the binding clears it before the next call (`call_begin`), the instance stays usable, and a neighbour in the same store is not touched.
* The typed functions run under the recursive lock of the host. After a trap the lock is released to the level it had before the call (`wasmext_rlock_release_to`), because the trap left the unlocks of fusedwasi behind. A WASI call is a system call anyway; the lock is recursive because a hook may call back into the module.
* Two instances made in one store share the one host: the same arguments, environment, preopens, descriptors and handles, the same hooks. A module built with `host = wasm32-wasip1` and one with `wasm32-wasip2` in one store share the one state (0.1 is over 0.2 in it). A module with `host = wasm32` has no core imports and is untouched.
* Headers: the binding of a module with core imports includes the headers of fusedwasi for exactly its calls. The mapping import to fusedwasi function lives in the model (`ImportFact`). `_gen.py` keeps its own copy until its step takes over (no side patches). The structures of the import modules are taken by wasm2c in the order of their names, not of the first import.

### Memories
* `wasmext_instance_memory` fills the view `{base, size, pages, max_pages, page_size, is64}` at this moment. It is valid until the module grows the memory (`memory.grow` or `wasmext_instance_memory_grow`), or for good while pinned. While pinned, `max_pages` is what the memory has.
* `memory_grow` returns the old number of pages, or -1 when it cannot (the maximum, the memory, or a pin that a move would break), or a negative code of the API. The host asks it when no call of the module is growing the same memory.
* `memory_pin(i, index, pin)`: pins count, under the mutex of the instance. The rule is moved as it was: while pinned, `memory.grow` answers -1 where the runtime would move the memory (the maximum is held at the current size). A 32-bit memory with guard pages never moves and is not touched.

### Globals
* `global_get` and `global_set` for i32, i64, f32, f64 and v128 (and 64-bit values). An immutable or a mistyped set is refused (`WASMEXT_INST_IMMUTABLE`, `WASMEXT_INST_BAD_ARGS`). The index is an export index (`BAD_EXPORT`).

### Free
* `wasmext_instance_free` frees an instance that the store does not hold (never instantiated, or whose instantiation failed). For an instantiated instance it answers `WASMEXT_STORE_BUSY` and does nothing (S0004).

## Test plan
The C tests need a real module. pytest builds one for each: `wat2wasm`, then `wasm2c`, then the binding of the emitter, then the C test with the static core, using the toolchain of the project (fixture `build` in `tests/test_instance_core.py`; the build is cached for the run). A C test is a plain program with no Python. As in step 1, a second reader checks the emitter: the descriptor inside the binding equals the model's dump.

Commands (each must pass):
* `uv run pytest tests/test_instance_core.py -q` (all of the step; 30 tests). Subsets:
  * `-k imports`: `tests/c/test_imports.c`. Function imports by index, the slot, uniform and typed, a failing host, a trap of another instance passed through, reentrant calls, `LINK_ERROR` with the name, bind after `instantiate` refused. The module has its import modules out of order.
  * `-k calls_of_an_instance`: `tests/c/test_instance.c`. Calls for i32, i64, f32, f64, several results, no result, the closed store, threads.
  * `-k start_function`: `tests/c/test_instance_start_trap.c`.
  * `-k v128`: `tests/c/test_instance_v128.c`.
  * `-k wasi`: `tests/c/test_wasi_imports.c` (0.1: `proc_exit`, `fd_write` to the stdout hook with iovecs, `args_sizes_get`/`args_get`, `environ_*`, `clock_time_get`, `random_get`, `proc_raise` ending and not ending, a call after the program ended) and `tests/c/test_wasi2_imports.c` (a fused core module with `exit`, the clock, random bytes, `get-arguments` as a list allocated through `cabi_realloc`, a write to stdout). Two instances of one module and one of another in one store share the hook and the arguments. A store with no host. A closed store. An unknown function and a wrong signature at build time.
  * `-k every_function_of_wasi`: `tests/c/test_binding_links.c`. A binding that answers every function of both families compiles and links.
  * `-k memories`: `tests/c/test_memory_globals.c`, on a 32-bit module and on a memory64.
  * `-k links`: `tests/c/test_links.c`. Two instances in one store: functions with several results and v128, a trap going through, one memory and one global shared both ways, a closed store of the exporter, seven kinds of refusal.
  * `-k what_the_binding_does_not_carry_yet`: the generator's refusals.
  * The sanitizer variants (`*_under_sanitizers`, `*_under_threadsanitizer`) run the same programs under ASan/UBSan and TSan on Linux.
* `uv run pytest tests/test_model_wasi_mapping.py -q`: the guard test of the mapping. It covers all 201 functions of both families.
* `uv run pytest tests/test_store_core.py -q`: includes `tests/c/test_rlock.c` (the recursive lock) and the host slot of the store.

Mutations (each was caught when the step was built): four in 3b1, three in 3b2a, three in 3c, four in 3d. A test is not trusted until a mutation of the code fails it for the right reason.

## Alternatives considered
* A `libffi` for a generic call: not taken. It is not on every target of the project. The generated adapter per distinct signature does the same job and is what a language with no generic call needs.
* A binding that is only data: not possible without a `libffi`. The binding is generated code (adapters, functions of the imports). The owner accepted this on 2026-10-29.
* Only the uniform host function: the typed fast path stays and is chosen per import when the front end has one. The benchmark of `context_concept.md` decides how much it matters; it is not measured.
* The WASI host inside the store (a store that knows fusedwasi): not taken (option A). The store stays free of fusedwasi and holds an opaque host. `Store()` in a front end is `new` + `set_host` in one.
* Threads and the host of WASI: (b) say that a store with WASI is for one thread at a time, as Wasmtime's store is (a call takes `&mut Store`). Not taken. (a), one recursive lock in the host around each call into fusedwasi, was built, because free-threaded is a requirement of layer 1.
* 3b2 in one commit for 0.1 and 0.2: not taken. Two commits, 3b2a for 0.1 and 3b2b for 0.2 (0.2 adds the canonical-ABI `realloc` and harder tests).
* Moving the mapping tables out of `_gen.py` at once: not taken. They move into the model (`ImportFact`); `_gen.py` keeps its copy until its step.
* Memory read through accessors in the glue (as the front ends did): replaced by the view `{base, size}` taken under the store's `enter`, valid until the next call that can grow it, or while pinned.
* The first design kept the C API with a different shape for every module (`<name>_set_import<k>`...): replaced by one shape.

## Open questions
* The typed fast path: how much it gains over the uniform function is not measured (`context_concept.md`).
* The Python hooks of `wasi_python.h`, the `_start` driver of the executable and more than one memory are not in this step.

## Changes
* 2026-10-28: design for review, step 3 of the order in [layers.md](../layers.md). The cut: a static core plus a generated binding. Order inside the step: 3a, 3b, 3c, 3d, each a commit with its C tests, CI between them.
* 2026-10-29: the owner accepted the four points: the binding is generated code; v128 crosses as 16 bytes in `wasmext_val`; the view of a memory is `{base, size}` under the store's `enter`; the order 3a to 3d with CI between.
* 2026-10-29: 3a built (`wasmext_instance.h`, `_binding.py`, `tests/c/test_instance*.c`, `tests/test_instance_core.py`). Function exports, `instantiate` with a trap in the start function, the generic `call` for i32, i64, f32, f64 and v128, several results, no result, the closed store, threads; under ASan, UBSan and TSan. ThreadSanitizer found a real race on `status`; it is atomic now.
* 2026-10-29: 3b1 built. Function imports by index of the descriptor: the slot of an import, the uniform host function and the typed fast path, a failing host, a trap of another instance passed through, reentrant calls, `LINK_ERROR` with the name in the text of the store, bind after `instantiate` refused. `tests/c/test_imports.c`. Four mutations are caught.
* 2026-10-29: 3b2a built. WASI 0.1 imports answered by the host: the host slot of the store, the guest in the block, the typed functions under the recursive lock of the host with `release_to` after a trap, `wasmext_instance_wasi_end`, the mapping in `ImportFact`. `tests/c/test_wasi_imports.c`, `tests/c/test_rlock.c`, the guard `tests/test_model_wasi_mapping.py`. Under TSan. Three mutations caught.
* 2026-10-29: 3b2b built. WASI 0.2: `ImportFact.core_comp`, `realloc` through the exported `cabi_realloc`, the headers of fusedwasi in dependency order. The test is a fused core module with `exit`, the clock, random bytes, `get-arguments` (a list allocated through `cabi_realloc`) and a write to stdout. The guard test covers all 201 functions. A binding that answers every function of both families compiles and links. Found by the 0.2 test and fixed: wasm2c takes the structures of the import modules in the order of their names, not of the first import; the test of 3b1 now has its modules out of order.
* 2026-10-29: 3c built. Exported memories: the view `{base, size, pages, max_pages, page_size, is64}`, `grow` from the host, `pin`/`unpin` with the rule moved as it was (a pinned memory that the runtime moves cannot grow; a 32-bit memory with guard pages is not touched), the pins from several threads under a mutex of the instance. Exported globals: `get`/`set` for i32, i64, f32, f64 and v128; an immutable or a mistyped set refused. `tests/c/test_memory_globals.c` on a 32-bit module and on a memory64, under ASan/UBSan and TSan. Three mutations caught.
* 2026-10-29: 3d built. The record of an export of a function, a memory or a global: `wasmext_instance_export_record`, with a typed shim in the binding that enters the exporter's store and answers a trap as `WASMEXT_TRAP_LINKED` + its code. `wasmext_instance_bind_export` gives an import such a record, with the checks that the old glue wrote for each import, once, from the descriptor (kind, signature, type and mutability of a global, runtime, 64-bit and guard pages of a memory, its pages against the import's limits, the version of the record). `bind_global_value` for an immutable global that the host gives. `import_owner`. The binding carries memory and global imports (table and tag imports were refused until steps 5 and 7). `tests/c/test_links.c`: two instances in one store and in two, functions with several results and v128, a trap going through, one memory and one global shared both ways, a closed store of the exporter, and seven kinds of refusal. Found and fixed on the way: the per-thread flag of `wasmext_thread_ready` was one for each file that includes the header, so a binding and the test set the thread up twice and the runtime aborts; `wasm_rt_is_initialized` does not do, so the flag is one for the artifact, defined by the one file that defines `WASMEXT_DEFINE_THREAD_STATE`. Four mutations caught.
* 2026-10-29: step 3 is complete. At that date the binding refused a module with a memory, table, global or tag import that it did not carry, a WASI import answered by the core, or a reference type in an import, each with the step that carries it.
* 2026-10-29: step 4 changed two things of this step ([S0004](S0004-owners-registry.md)): an instantiated instance is a member of the store and `wasmext_instance_free` is refused for it; instances are linked inside one store, and the test of two stores became a test of the refusal.
* 2026-10-30: extended by S0005 (tables, funcref), S0006 (externref), S0007 (tags and exceptions). Their additions to the structs above are marked in Interface.
* 2026-10-30: rewritten from `docs/step3_instances.md` into the spec format, status `implemented`. Interface and Semantics describe the code as it is now.
