# Layers: the rework of the whole library (a design, for review)

Status: **written 2026-10-28, for the owner's review; nothing of it is built.** It answers one statement of the owner: *the emitters for the extension and for the shared library are separate; there should be a chain* **front-end glue (pyglue / ctypes / exe) -> shared glue -> wasmext glue**, *and everything about implementation and features lives below it; this is about the whole library, not about single features; many things are begun and not finished; and the ABI may change (alpha), so there is no reason to rework in small pieces.* [architecture.md](architecture.md) is the picture of the end; this page is how the library is cut to get it. Facts are from the audits in [audit_thin_glue/](audit_thin_glue/) and from [FEATURES.md](FEATURES.md); what is a proposal says so.

## The problem, measured

- Four generators (`_gen.py` 4101 lines, `_shared.py` 1432, `_ctypes_gen.py` 1536, `_exe.py` 549) each carry logic that must be the same in all targets: linking, tables and functions, errors, config of the host, ownership. For a module with an import, a memory, a table and a global: extension 1288 lines of C, wrapper 1047 lines of Python, shared library 348 (C API 135). About 15 % (extension) to 25 % (wrapper) of the lines are logic; it is written twice; only 38 of 174 lines of logic in the extension could move as they are.
- The C API of the library has **a different shape for every module** (`<name>_set_import0`, `<name>_link_import0`, typed pointers for each import, `link_global_import<j>`...). A front end cannot be written once; it carries generated tables of names and signatures.
- The extension and the wrapper talk to each other through Python attributes (`_pending`, `__wasmext_keep__`, `__wasmext_ref__`); the executable bypasses the C API. Three front ends sit on two cores.
- Because a rule is written in several places, one scenario works on one pair of front ends and traps on another (found 2026-10-28: a Python callback in a table function of an extension called from the ctypes wrapper).

## The cut

```
 LAYER 3  front-end glue     pyglue (CPython extension) | ctypes glue | exe glue
          (thin, generated from the model + one static helper each)
              |  they call only the C API of layer 2
 LAYER 2  shared glue        the C API of a module: ONE shape for every module
          (C, no Python)     store, instance, imports by index, exports, memory, tables, globals, tags,
              |              owners, errors, traps, host config. Built into the extension, or a shared library.
 LAYER 1  wasmext glue       the module and its runtime: wasm2c output, the link functions it needs,
          (C, no Python)     the shipped core (records, traps, tables, owners, store), fusedwasi (WASI)
```

**One rule: a layer calls only the layer below it.** The core knows nothing of Python: it takes from a front end *retain/release* for an owner, *call a host function*, *describe an error*. The three front ends differ in nothing else than how they convert values, keep their own objects alive and map a code to their own exception.

## The model of a module (one input for every emitter)

Today each generator re-reads the parsed module and decides again what is exported, what a signature is, which imports need a trampoline. **One analysis, once** (a plain data structure, the "model"): exports and imports with kinds and signatures, memories (with their limits, 64-bit, shared), tables, globals, tags, start function, the declared function types, the `host`, the build flags (`share_tables`, guard pages, parts). Every emitter and the stub generator read it and nothing else; no emitter parses text of another. The stub (`.pyi`), the descriptor in the library and the glue come from the same facts, so they cannot disagree.

## Layer 1: wasmext glue

- **Generated per module:** the output of `wasm2c` (with the existing patches for WABT), `<name>_glue.h` (the exports as data, the accessors of memories and tables, the trampolines for the function types the module declares), and nothing that decides a rule.
- **Shipped (hand-written C, `src/wasmext/c/`):** the ABI records (`wasmext_export`, `wasmext_traps`, later `wasmext_store`), the tables and funcrefs, the stack of traps, the owners and the registry, the store with its arena and its `close`, the codes and messages of errors, the memory pin, the thread set-up. It is split into headers by subject (proposed: `records.h`, `store.h`, `link.h`, `tables.h`, `owners.h`, `traps.h`, `errors.h`, `memory.h`, `host.h`) so that one subject is one file.
- **WASI:** fusedwasi (the C headers, compiled in); the `host` setting says what answers a module. A module of 0.2 is a core module taken out of a component.

## Layer 2: shared glue, the C API (proposed, to be fixed in review)

**The same names and signatures for every module**, with `<name>_` as the prefix only. Built into the extension (static) or into a shared library (the ctypes wrapper, the executable's own program, a C host). Sketch, not final:

| Group | Entries (sketch) |
| --- | --- |
| module | `<n>_describe()` -> a **descriptor** of the module (names, kinds, signatures, limits, flags) read at run time; `<n>_abi()`, `<n>_runtime()` |
| store | `store_new(config)`, `store_close`, `store_free`, `store_closed`, one `config` builder (`dirs`, `env`, `args`, streams, clocks) validated in the core |
| instance | `new(store)`, `bind_import(m, index, kind, host_fn, user)` / `link_import(m, index, export_record)`, `instantiate`, `free`, `unlink` on failure |
| exports | `export_count/at/find`; `call(m, index, args[], results[])` (generic) and, generated, typed entries `call_<i>` for the hot path |
| memory, table, global, tag | `memory_*` (size, grow, pin/unpin), `table_*` (new, get, set with its rules, grow, owner), `global_*`, `tag_*` |
| owners | `owner_t` = an opaque handle; the front end gives `retain`/`release`; the registry `module_instance -> owner` is inside |
| errors, traps | `error_describe(code)` -> kind, text, exit value, signal, whether it is an exception of WebAssembly; the cell for the error of a host function; one rule for who holds the lock when a host function is called |
| host calls | one uniform callback `host_fn(user, args[], results[])` for every import, and `call` the same way, with typed fast paths kept (the hot path of the benchmark of `context_concept.md` is the criterion) |

The descriptor removes the generated tables from the wrapper and the per-import entry points from the API; **how the library describes itself is the first thing to settle in review.**

## Layer 3: the front ends

| Front end | Emits | Does |
| --- | --- | --- |
| **pyglue** (CPython extension) | a small `<name>_py.c` from the model + the static `wasmext_pyext.h` | converts Python values, keeps Python objects as owners (retain/release = INCREF/DECREF), calls a Python host function, maps the code of the core to its exception, `tp_traverse` through the owner list of the core; abi3 or native; later free-threaded |
| **ctypes glue** | one **static** `wasmext_ctypes.py` + a small stub with the names | the same through `dlopen`; every entry that can release an owner goes through `PyDLL` or the core queues the release |
| **exe glue** | `<name>_main.c` | options, the store made through the API |

The extension does **not** reimplement what layer 2 has: it links `<name>_shared.c` into the module. (Whether this compiles as it is, with the extension's flags, on all platforms, is not yet tried.)

## Where every capability of the library goes

| Capability (from FEATURES.md) | Layer | Note |
| --- | --- | --- |
| all WebAssembly features wasm2c has (MVP, multi-value, bulk, reference types, SIMD, tail calls, multi-memory, memory64, exceptions, branch hinting...) | 1, in the output of wasm2c | unchanged; what wasm2c lacks (relaxed SIMD, typed function references, GC, wide arithmetic) is refused with a message |
| exports of functions, memories, globals, tables | 2 `export_*`, 3 only converts | generic and typed entries |
| imports of functions, globals, memories, tables | 2 `bind_import`/`link_import` by index | no per-module entry points |
| `Table`, `Function`, `funcref` and `externref` in signatures | 2 `table_*`, owners | **begun, refused today:** finished here, once |
| tags and exceptions across instances | 2 `tag_*`, the store | begun in part |
| traps, uncaught exceptions, `proc_exit` | 2 `error_describe`, 1 trap stack | one table, one place |
| memory views that do not move under a `memoryview` (pin) | 2 `memory_pin` | one counter in the core |
| shared global/memory/table between instances, imports from another instance | 1 records + 2 `link_*`; across artifacts the versioned `wasmext_store` | |
| WASI 0.1 (in the module), WASI 0.2 (host, `host_full`), hooks, files, sockets, http | 1 (fusedwasi) + 2 `config`; Python hooks only in layer 3 | |
| stack check, signals, two modules in one process, Python threads | 1 trap stack and thread set-up; 3 sets the thread up | |
| type stubs, parameter names | from the model, in layer 3 | |
| `natify`, `inspect`, setuptools, import hook, `pyproject.toml`, products, abi3/native wheels, Pyodide, Android | the build side (Python), calls the emitters | stays |

## Begun and not finished (the owner's list; to be completed in review)

From `FEATURES.md`, `TABLES_PLAN.md` and the plans: `funcref` in an import and `Function` with a `funcref` parameter (refused); `externref` (refused); host functions as table members (refused); exported tags (not yet); the public store across modules (a `Store` of another module is a `TypeError`; C7); `host_full` and the shared runtime across artifacts (C7); the lazy collector (C8); threads/atomics and custom page sizes (not yet); `.wat` as a source (declined); other build backends (partly); Android arm64 (built, not tested); the free-threaded declaration (not made until the Python side is audited). For each one the decision is **finish it in the new layers, or remove it**; none is carried over half-made.

## How it is done: bottom-up, tested from C (the owner, 2026-10-28)

**Build the lower layer completely before the one above it.** Layers 1 and 2 are plain C with no FFI in mind: any language that can call C (Python `ctypes`/CPython, Rust, Go, Node, a C host) is a front end. So they are tested **directly from C**, with a small C test harness (`tests/c/`, built by the same toolchain as the modules, run by `pytest` and by CI on every platform, with the sanitizers). The Python front ends are written last and add no logic; their tests stay as the check that nothing was lost.

1. **Wasmext glue (layer 1), complete**, in this order (each step depends on the one before; its C test is written first):
   1. **Model and descriptor**: the data every later step reads.
   2. **Store**: arena, `close`, config (WASI from fusedwasi), error codes and description, trap stack (C2a part 1 exists).
   3. **Instances**: exports of functions, memories, globals; imports by index; one host-callback shape; `memory_pin`.
   4. **Registry of owners** (C2b/C2c): opaque handle with retain/release.
   5. **Tables and `funcref`** (C4): `funcref` in imports and parameters, `Function`, host functions in tables.
   6. **`externref`** (C5): rests on the owners of step 4.
   7. **Tags and exceptions across instances** (C6): one identity of a tag in a store.
   8. **Shared store across separately built modules** (C7, decision 6): after 4-7, so that the layout of the record is not changed twice.
   9. **Lazy collector** (C8): last; needs the registry and the shared store.

   Removed from the plans: threads/atomics, custom page sizes, `.wat` as a source, other build backends. Free-threaded declaration stays the last item, after an audit of the Python side. All tested from C against small `.wat` modules.
2. **Shared glue (layer 2): one C API, the same for every module, FFI-neutral** (no Python types, no callbacks that need a GIL, plain structs and function pointers, owners as opaque handles with retain/release). The descriptor of the module is read at run time. Tested from C; this API is the product for every host language.
3. **Front ends (layer 3)**, one after another over the finished API: ctypes glue (a static `wasmext_ctypes.py`), the executable, the extension. Old logic of the generators is deleted in the same step.

The ABI is **changed freely** (policy "Alpha does not keep the ABI"); `abi/current.json` and the fingerprint are renewed once at the end of each step. No step starts before the one below is complete and green.

**Done when** (measured): every rule of the table above is written in one place; the C tests of layers 1 and 2 cover the whole API; the suite is green on all platforms; the generated front-end glue holds conversions only (the number is to be fixed in review); the hot path of the benchmark of `context_concept.md` loses no more than a number we agree on.

## Risks and what is not known

- Whether the extension can link the shared glue statically, with its flags, on Windows (MSVC), macOS, Pyodide, Android: **not tried**; test it when step 3 starts.
- Speed of the generic `call`/host callback against the typed paths: **not measured**; measure from the C harness.
- Free-threaded builds and sub-interpreters with owners held by the core: **not tried**.
- A rework of this size touches most of the generator; the tests of the old shape have to be ported, not skipped.
- The thin-glue stage 1 on the branch `thin-glue` is superseded by this rework and is not to be merged.

## Decisions I need

1. The bottom-up order above, with the C test harness.
2. The cut: three layers; the extension over the same C API as the others.
3. The descriptor: the library describes itself at run time; imports bound by index with one callback shape; typed fast paths kept for exports.
4. The list of "begun and not finished": for each, finish or remove.
5. The acceptance numbers: size of the front-end glue, allowed loss on the hot path.
6. **A shared store across separately built modules, explicit and without Python.** The store is explicit; one module makes it and gives out the versioned record `wasmext_store` (`store_handle`), another module built apart takes it (`store_attach`) and makes its instances in it, as two extensions do through a capsule. The record carries a layout version (a mismatch is refused) and a count of attached modules; the store lives while one is attached. In CPython/ctypes a capsule only carries the same pointer. No process-global rendezvous. Open: a library unloaded while another holds its functions in a table (the registry of owners must keep it loaded).
