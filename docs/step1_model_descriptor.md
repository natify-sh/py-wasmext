# Step 1 of layer 1: the model and the descriptor (a design, for review)

Status: **written 2026-10-28; nothing of it is built.** It is step 1 of the order in [layers.md](layers.md). Facts below are read in the code of 2026-10-28.

## What there is

- `src/wasmext/_wasm.py` already parses a binary: `Module` (types, imports, defined functions, tables, memories, globals, tags, exports, start, names of locals, `fused_by`), with the index spaces (`all_functions`, `all_memories`...). This is a sound description of the **binary**; it stays as it is.
- Every generator then re-derives what it needs on top of it: `_gen.py` (`_Import`, `_ImportMemory`, `_ImportTable`, `_ImportGlobal`, `Glue`), `_shared.py` (`ApiModel`), `_exe.py` (`BuildFlags`), `_ctypes_gen.py` (its own tables). The same decision (which import is answered by WASI, which export name becomes which C identifier, which import group a slot belongs to) is made in several places.
- The library does not describe itself at run time; a front end learns names and signatures from generated code.

## The model (build time, Python): `src/wasmext/_model.py`

One function `build_model(module: Module, options) -> ModuleModel`, frozen dataclasses, no I/O. It adds to `Module` only **facts about the build**, once:

- the name and the C prefix of the module; the `host` (`wasm32-wasip1`, full, none); the flags (`share_tables`, guard pages, parts);
- for every import: its index in its kind, and whether the core answers it (WASI) or the user supplies it;
- for every export: the C identifier that is made of its name (unique, not in the reserved set);
- `dump()`: a canonical text of all of it (one fact per line), used by tests.

Emitters read the model and nothing else. In this step **no existing emitter is changed** (rule of [layers.md](layers.md)); each is moved onto the model in the step that owns it.

## The descriptor (run time, C): `src/wasmext/c/wasmext_descriptor.h` + generated `<name>_descriptor.c`

Read-only data in the library, reached by `const wasmext_descriptor *<name>_describe(void)`. Plain C, no Python, no allocation.

```c
typedef struct {
  uint32_t version, size;               /* of this struct: a reader checks both */
  const char *name;                     /* the module */
  uint32_t flags;                       /* share_tables, uses_wasi, 64-bit memory... */
  uint32_t n_types;   const wasmext_functype *types;     /* params/results as value-type bytes of the binary format */
  uint32_t n_imports; const wasmext_import_desc *imports;/* module, name, kind, index in kind, type */
  uint32_t n_exports; const wasmext_export_desc *exports;/* name, kind, index in kind, type */
  uint32_t n_memories; const wasmext_limits *memories;
  uint32_t n_tables;   const wasmext_table_desc *tables;
  uint32_t n_globals;  const wasmext_global_desc *globals;
  uint32_t n_tags;     const wasmext_functype *tags;
  int32_t  start;                       /* -1: none */
} wasmext_descriptor;
```

- Names are the **WebAssembly names** (UTF-8, as in the binary), never the mangled C names: a front end finds things by name; C names are a build fact.
- Value types use the bytes of the binary format (`0x7F` i32...), so there is no second numbering.
- Parameter names (the "name" section) are in the descriptor as an optional array; the `.pyi` stays generated at build time from the **same model**, so the types a user sees do not change.
- Cost: constant data in `.rodata`, read once when a front end binds a module; no cost on any call.
- The header is part of `src/wasmext/c/`, so it is under the ABI fingerprint; the descriptor has its own `version` and `size`.

## The tests (C first)

1. `tests/c/test_descriptor.c`: a plain C program, compiled with the generated `<name>_descriptor.c` and nothing else (no Python, no wasm2c output), that prints the **canonical text** of the descriptor.
2. A pytest builds that program for a set of small `.wat` modules and compares its text with `ModuleModel.dump()` of the same module: **two readers of the same facts must agree.** The set covers every kind and edge: multi-value, `memory64`, shared memory, funcref tables, mutable/immutable globals, tags, an import of each kind, WASI imports, names with quotes/percent/backslash/non-ASCII, empty module, start function.
3. A size/version test: a reader refuses a descriptor of another `version` or a smaller `size`.
4. The same program runs under the sanitizers and on the matrix of CI (it is plain C).

## Not in this step

No change of the extension, the wrapper, the executable, `wasmext_export`, or the API; no store. The descriptor does not replace the record `wasmext_export` (the runtime pointers for linking): later steps join them by export index.

## Open (for the owner)

1. Names of parameters in the descriptor: included (above), or only in the `.pyi`?
2. The place of the C harness: `tests/c/` with its own tiny build script, or built through the toolchain module of wasmext (`_toolchain.py`)?
3. Is one canonical-text format enough as the comparison, or do we also want the model as JSON for golden files?
