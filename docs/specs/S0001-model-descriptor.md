---
title: Model and descriptor
kind: spec
id: S0001
status: implemented
superseded_by:
related: []
owner: maintainer
updated: 2026-10-30
---

# S0001 Model and descriptor

## Summary
Step 1 of layer 1 (see `docs/layers.md`). A module has two readers of the same facts about it.

* The **model** (build time, Python): `src/wasmext/_model.py`. One analysis of a parsed module. Frozen dataclasses, no I/O.
* The **descriptor** (run time, C): `src/wasmext/c/wasmext_descriptor.h` and a generated `<name>_descriptor.c`.
  It is read-only data in the library. A host that can call C reads it. No Python, no allocation.

A contract is needed because later steps (S0002 and after) read these facts. The two readers must agree, so a test compares them.

Why it exists. `src/wasmext/_wasm.py` already parses a binary: `Module` has types, imports, defined functions, tables, memories, globals,
tags, exports, start, names of locals and `fused_by`, with the index spaces (`all_functions`, `all_memories`, ...). That is a sound
description of the binary and it stays as it is. But every generator re-derived what it needed on top of it:
`_gen.py` (`_Import`, `_ImportMemory`, `_ImportTable`, `_ImportGlobal`, `Glue`), `_shared.py` (`ApiModel`), `_exe.py` (`BuildFlags`),
`_ctypes_gen.py` (its own tables). The same decision was made in several places: which import WASI answers, which export name becomes
which C identifier, which import group a slot belongs to. The library also did not describe itself at run time. A front end learned
names and signatures from generated code.

## Goals / Non-goals
* Goals:
  * Add to `Module` only facts about the build, once: who answers each import, the flags.
  * Give the library a way to describe itself at run time: names, kinds, signatures, limits, flags.
  * One canonical text (`ModuleModel.dump()`) that both readers can print, so a test can compare them.
  * Names are the WebAssembly names (UTF-8, as in the binary), never mangled C names. A front end finds things by name.
    C names are a build fact.
  * Value types use the bytes of the binary format (`0x7F` for i32, and so on). There is no second numbering.
  * Cost: constant data in `.rodata`, read once when a front end binds a module. No cost on any call.
  * The header is part of `src/wasmext/c/`, so it is under the ABI fingerprint. The descriptor has its own `version` and `size`.
* Non-goals:
  * No change of the extension, the wrapper, the executable, the record `wasmext_export` or the API. No store (see S0002).
  * The descriptor does not replace the record `wasmext_export` (the runtime pointers for linking). Later steps join them by export
    index (see S0003).
  * No existing emitter is changed in this step (rule of `docs/layers.md`). Each emitter moves onto the model in the step that owns it.
  * The stub (`.pyi`) is generated at build time from the same model. The types a user sees do not change.

## Interface

### C: `src/wasmext/c/wasmext_descriptor.h`
Reached by `const wasmext_descriptor *<name>_describe(void)`. The generated file also defines `const wasmext_descriptor <last>_descriptor`.

```c
#define WASMEXT_DESCRIPTOR_VERSION 1u

enum { WASMEXT_DESC_FUNC = 0, WASMEXT_DESC_TABLE = 1, WASMEXT_DESC_MEMORY = 2,
       WASMEXT_DESC_GLOBAL = 3, WASMEXT_DESC_TAG = 4 };      /* kinds, in the order of the binary format of exports */

enum { WASMEXT_DESC_SHARE_TABLES = 1u,   /* built with the tables shared between instances */
       WASMEXT_DESC_USES_CORE = 2u };    /* the core answers some imports (WASI) */

typedef struct { const char *p; uint32_t n; } wasmext_str;                       /* UTF-8 bytes and a length */
typedef struct { uint32_t n_params, n_results; const uint8_t *params, *results; } wasmext_functype;
typedef struct { uint64_t min, max; uint8_t has_max, shared, is64; } wasmext_limits;
typedef struct { uint8_t elem; wasmext_limits limits; } wasmext_table_desc;
typedef struct { uint8_t type, is_mutable; } wasmext_global_desc;

typedef struct {
  wasmext_str module, name;
  uint8_t kind;
  uint8_t core;          /* 1: the core answers this import, the caller gives nothing */
  uint32_t index;        /* in the imports of its kind (also the index in the arrays of memories, tables, globals, tags) */
  wasmext_functype type; /* for a function and a tag; zeros otherwise */
} wasmext_import_desc;

typedef struct {
  wasmext_str name;
  uint8_t kind;
  uint32_t index;        /* in the index space of its kind: the imports first, then what the module defines */
  wasmext_functype type; /* for a function and a tag; zeros otherwise */
  const wasmext_str *param_names; /* NULL, or n_params entries; an unnamed parameter has p == NULL */
} wasmext_export_desc;

typedef struct {
  uint32_t version, size; /* WASMEXT_DESCRIPTOR_VERSION and sizeof of this struct */
  wasmext_str name;       /* the module, as it is imported */
  uint32_t flags;
  uint32_t n_imports;  const wasmext_import_desc *imports;
  uint32_t n_exports;  const wasmext_export_desc *exports;
  uint32_t n_memories; const wasmext_limits *memories;      /* the whole index space: imported first */
  uint32_t n_tables;   const wasmext_table_desc *tables;    /* the same */
  uint32_t n_globals;  const wasmext_global_desc *globals;  /* the same */
  uint32_t n_tags;     const wasmext_functype *tags;        /* the same */
  int64_t start;       /* index of the start function, or -1 */
} wasmext_descriptor;
```

Encodings:
* Value type bytes: `0x7F` i32, `0x7E` i64, `0x7D` f32, `0x7C` f64, `0x7B` v128, `0x70` funcref, `0x6F` externref.
* Function types are inline in each import and export. There is no table of types.
* Names carry a length. A name may hold a zero byte.
* Parameter names (the "name" section) are in the descriptor as an optional array on the export (`param_names`).
* A reader checks `version` and `size` before it reads anything else. The C reader in the tests refuses a descriptor whose `version` is not `WASMEXT_DESCRIPTOR_VERSION` or whose `size` is not `sizeof(wasmext_descriptor)`.

### Python: `src/wasmext/_model.py`
* `build_model(module: Module, name: str, *, host: str = "wasm32", share_tables: bool = False) -> ModuleModel`.
  `name` is the dotted name as it is imported. `host` is checked by `check_host` (see `wasmext._gen.HOSTS`).
* `ModuleModel` (frozen, slots): `name`, `last`, `host`, `share_tables`, `module`, `imports`, `exports`;
  property `flags`; method `dump() -> str`.
  `last` is the C identifier of the last part of the name: the prefix of the C API.
* `ImportFact`: `module`, `name`, `kind`, `index` (among the imports of its kind), `type`, `core`,
  `core_call`, `core_header`, `core_comp`.
* `ExportFact`: `name`, `kind`, `index` (in the index space of its kind), `type`, `param_names`.
* Constants: `FLAG_SHARE_TABLES = 1`, `FLAG_USES_CORE = 2`; `KIND_CODES` (func 0, table 1, memory 2, global 3, tag 4);
  `VALTYPE_BYTES` (the bytes above).
* `__all__ = ["ExportFact", "ImportFact", "ModuleModel", "build_model"]`.

### Python: `src/wasmext/_descriptor.py`
* `generate_descriptor(model: ModuleModel) -> str`: the C source of `<last>_descriptor.c`.
  It includes `wasmext_descriptor.h`, emits the arrays as `static const` and defines `<last>_describe()`.
  An empty array becomes `#define <last>_desc_<array> 0`.

### The canonical text (`ModuleModel.dump()`)
One fact per line. The C reader `tests/c/dump_descriptor.c` prints the same text.
```
module "<name>"
flags <n>
start <index or -1>
memory <i> <min> <max or -1> <shared> <is64>
table <i> <elem byte> <min> <max or -1> <shared> <is64>
global <i> <type byte> <mutable>
tag <i> (<param bytes>)->(<result bytes>)
import <kind> "<module>" "<name>" <index> <core> <type>
export <kind> "<name>" <index> <type> [names <p1> <p2> ...]
```
`<kind>` is the word `func`, `table`, `memory`, `global` or `tag`. `<type>` is a function type as above, a table (`<elem> <limits>`),
a global (`<type byte> <mutable>`) or limits (`<min> <max or -1> <shared> <is64>`).
Names are written in double quotes. A byte outside printable ASCII, the quote and the backslash are written as `\xHH`.
An unnamed parameter is `-`.

## Semantics
* The model adds to `Module` only facts about the build, decided once:
  * the name and the C prefix (`last`) of the module, the `host` (`wasm32`, `wasm32-wasip1`, `wasm32-wasip2`), and `share_tables`;
  * for every import: its index in its kind, and whether the core answers it (`core`) or the user supplies it;
  * for every export: its index in its kind, its type, and the names of the parameters of a function (`None` if the module names none).
* The core answers an import only when it is a function and the host says so (`_answered_by_core`, the one place that decides):
  * `wasm32-wasip1`: the module is `wasi_snapshot_preview1` or `wasi_unstable`;
  * `wasm32-wasip2`: the module starts with `wasi:` and contains `@0.2.`;
  * any other host: nothing.
* For an import answered by the core the model also keeps what answers it: the function of fusedwasi (`core_call`), its header below
  `fusedwasi/` (`core_header`, with the prefix `p1/` or `p2/`), and whether it takes the index of the component (`core_comp`).
  A function that fusedwasi does not have, or has with another signature, is a `GenError`.
* `flags` is `WASMEXT_DESC_SHARE_TABLES` if `share_tables`, plus `WASMEXT_DESC_USES_CORE` if any import is answered by the core.
* `memories`, `tables`, `globals` and `tags` hold the whole index space, imported first (`all_memories`, ...).
* `start` is the index of the start function, or `-1`.
* The descriptor is constant data. Names are WebAssembly names, never mangled C names.
* Two readers of the same facts must agree: the text of `dump()` and the text printed from the descriptor in C are the same for every
  test module.
* A reader of the descriptor in C (`dump_descriptor.c`) exits with code 2 and prints "descriptor version" on stderr when `version`
  is not `WASMEXT_DESCRIPTOR_VERSION` or `size` is not `sizeof(wasmext_descriptor)`.
* Emitters read the model and nothing else. In this step no existing emitter is changed.

## Test plan
Run from the repository root. All pass as of 2026-10-30.

```
uv run pytest tests/test_descriptor.py -q
```
Result seen: `48 passed in 5.45s`.

What it builds and checks:
1. `tests/c/dump_descriptor.c`: a plain C program, compiled with the generated `<name>_descriptor.c` and nothing else
   (no Python, no wasm2c output), with `-DDESCRIBE=<last>_describe`. It prints the canonical text of the descriptor.
   Build helper: `tests/c_build.py` (`compile_c`), include path `src/wasmext/c`.
2. `test_c_and_python_read_the_same_facts`: for each small `.wat` module in `MODULES` and each host (`wasm32`, `wasm32-wasip1`,
   `wasm32-wasip2`), the text printed by the C program equals `ModuleModel.dump()`. `.wat` is turned into a binary with
   `wat2wasm --enable-threads --debug-names`. The set covers: empty module, multi-value, unnamed parameters, memory and
   mutable/immutable globals, `memory64`, shared memory, funcref tables, externref table, an import of each kind, tags, start
   function, `v128`, names with quote, backslash, zero byte, percent and non-ASCII, and WASI imports (p1, unstable, 0.2).
3. `test_the_model_says_who_answers_the_imports`: the `core` flag per host.
4. `test_parameter_names_are_in_the_model`: the "name" section reaches `param_names` and `dump()`.
5. `test_a_reader_refuses_another_version`: a descriptor with `version + 1` makes the C reader exit with 2 and
   "descriptor version" on stderr.

The program is plain C. It runs under the sanitizers and on the CI matrix.

Related guard test: `tests/test_model_wasi_mapping.py` (the mapping of WASI imports to fusedwasi, listed in `docs/layers.md`).

The ABI follows the header: when `src/wasmext/c/wasmext_descriptor.h` changes, update the fingerprint
(`uv run pytest tests/test_abi.py`) and `uv run python -m tests.abi_surface --update`.

## Alternatives considered
* **Leave each emitter to re-derive the facts** (the state before this step). Cost: the same decision is made in several places and
  can differ. Not chosen: one model, once.
* **A table of types in the descriptor** (the first sketch). Not chosen: function types are inline in each import and export.
* **Parameter names only in the `.pyi`.** Not chosen (the owner's answer): the names are in the descriptor as an optional array, and
  the `.pyi` is generated from the same model.
* **Mangled C names in the descriptor.** Not chosen: a front end finds things by name. C names are a build fact.
* **A second numbering of value types.** Not chosen: the bytes of the binary format are used.
* **Move the emitters onto the model now.** Not chosen: no existing emitter is changed in this step. Each moves in the step that owns it.
* **The model also as JSON for golden files.** Not done: one canonical text is the comparison (see Open questions).
* **C harness through the toolchain module of wasmext (`_toolchain.py`).** Not chosen: the harness lives in `tests/c/` and is built
  by `tests/c_build.py`.

## Open questions
* None for the contract. Items 1 (parameter names) and 2 (place of the C harness) of the old "Open" list are answered as described
  above. Item 3: the model as JSON for golden files is not built. One canonical text is enough so far.
* The descriptor has no flag for 64-bit memory: `is64` is in each `wasmext_limits`. Add a flag only if a reader needs it.

## Changes
* 2026-10-28: step 1 built: `_model.py`, `_descriptor.py`, `c/wasmext_descriptor.h`, `tests/c/dump_descriptor.c`,
  `tests/test_descriptor.py`. Facts of the first document were read in the code of that day.
* 2026-10-28: what differs from the first design (the sketch in the old document was only a design; the header is the reference):
  function types are inline in each import and export (no table of types); parameter names are in the descriptor (the owner's answer).
* 2026-10-30: this document written as S0001 from `docs/step1_model_descriptor.md`. Interface and Semantics describe the code of
  this date.
