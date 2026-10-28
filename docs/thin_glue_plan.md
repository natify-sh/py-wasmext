# Thin glue: the audit in one page and one plan

Status: **written 2026-10-28**, after two read-only audits (the extension; the wrapper for ctypes and the shared library). The full reports, with a row for every function and block, are in [audit_thin_glue/](audit_thin_glue/) (`audit_extension.md`, `audit_ctypes_shared.md`). The principle is in [thin_glue.md](thin_glue.md). **Nothing is changed in the code yet.** The figures come from scripts that give each unit one main category by its name; the mixed functions were split by hand, so they are good to a few percent.

## What the audits found

1. **The logic is less than it looked, but it is written twice.** In the extension about **15 %** of the lines are LOGIC (174 of 1187 in `rich`); in the wrapper for ctypes about **25 %** (the template is not cut to the module: even `add` has 214 of 835). About 80 % of the extension is conversion, the life of Python objects and boilerplate, which is what a thin front end is made of.
2. **A core already exists, and the extension does not use it.** `wasmext_glue.h` and `<name>_api.h` hold much in plain C: the table and `funcref` functions, `export_find`, the memory pin, `link_import`, the store functions. The extension writes most of it again in `_py.c`.
3. **Only 38 lines of LOGIC (of 174, in `rich`) can move as they are** (no Python call inside). The rest is tangled with Python calls and has to be unpicked. The pattern is the one `wasmext_link_fail` already has: the core returns a code and a message, the front end makes the exception.
4. **Repeated code inside the extension itself:** `Instance_new` repeats a block of 44 lines for every function import (776 of the 1999 lines of `probe_py.c`, which has 17 imports); the table of trap codes is written twice (`raise_trap_code`, `raise_foreign_trap`); the checks for a `funcref` are in `Table_set` and in `funcref_arg`.
5. **The wrapper repeats checks that the C already makes** (the version of the ABI of an export, the signature of an import, with the same message): a pure deletion.
6. **The two Python layers talk to each other through attributes, not through C:** `_pending`, `__wasmext_keep__`, `__wasmext_ref__`, `__exports__`. `raise_trap_code` in the extension reads `_pending` of the wrapper by name. This is the kind of coupling that produced the `Trap` found on 2026-10-28.
7. **The executable bypasses `<name>_api.h`** and fills the state of fusedwasi by hand: the three front ends sit on **two** cores, not one.
8. **The C API changes shape from module to module** (`link_import<k>`, `host_call<k>`... exist only when the module needs them) and has no description of itself at run time, so the wrapper carries generated tables of names and signatures.
9. **A possible defect (not confirmed):** `Function.__call__` in the wrapper does not look at `_pending`, unlike `Instance._error`, so an exception of a host function inside a `Function` call becomes a plain `Trap`.
10. **The owner handle works with ctypes, with a condition (tested):** `Py_IncRef` and `Py_DecRef` as the retain and release of an owner work through `PyDLL`; through `CDLL` the process aborts when the last release frees the object ("GIL is released"). So every core entry that can release an owner must go through `PyDLL`, or the core queues releases for the front end. This is the same cause as the known `Trap`.
11. The core cannot track owners per slot of a table, because a guest `table.set` writes without telling it. Owner edges stay coarse, as they are.

## The plan, in stages (names, not numbers)

Each stage leaves behaviour and tests the same, except the one marked. About 250 tests already run on both front ends (the fixture `front_end`).

| Stage | What | Risk |
| --- | --- | --- |
| **Net** | record the generated `*_py.c` and `*_ctypes.py` of about 10 builds as golden files (outside the repository) and run the whole suite once: the baseline | none |
| **Free cleanups** | dedupe inside the templates (`import_ref`, the loop over the `hold` arrays, one `funcref` check, one table of trap codes); delete the wrapper's repeat of the C checks; move the code with no Python call into `<name>_glue.h` | low |
| **Checks and messages once** | `table_set`, the `funcref` checks, the limits of a table, `error_describe` (kind, text, exit value, signal), the module descriptor, the `config` builder: written once in the core, the texts copied verbatim; the front ends map the code to their exception | low to medium (the long texts are matched by tests) |
| **Linking through the core** | one definition of `export_find`/`export_at`; imports through descriptors with a generic `link_import`; `instantiate(resolver)` in C with the unlink on failure | medium |
| **The host-error cell** | replaces `_pending`; the wrapper stops parking the exception in an attribute at the same time (**changes the contract between the two front ends**) | high |
| **Owners in the core** | `wasmext_owner_ops` (retain and release supplied by the front end), the lists `writers`, `refs`, `hold*` move into the core; `Table.get` stops scanning. **This is the registry of [owners_registry.md](owners_registry.md).** Includes the one rule "who holds the GIL when a host function is called": **the only stage that changes behaviour**, guarded by `test_a_python_callback_in_a_table_function` (now `xfail`) | high |
| **State** | the pin counters and `Store_close` into the core; the executable goes through the API for store and config | low to medium |
| **Last, only if the hot path loses nothing** | a generic `callref` and a uniform host callback; a single static `wasmext_ctypes.py` with a generated stub | medium (speed; measured with the benchmark of `context_concept.md`) |

The registry of owners, which was to be built first, is **now one stage in the middle**, after the cleanups it depends on.

## Open (from the audits)

- Can the extension compile the shared library's `.c` directly? It decides whether the core entries are new code or a move of existing functions.
- Is a thread-local host-error cell enough? Are references held by the core safe with sub-interpreters and free-threaded builds? Neither is tried.
- Whether the C and Python texts are identical for global, memory and table links (only function links were compared by reading).
- Not read by either audit: most of `_gen.py` beyond the quoted blocks, `wasi_python.h` and `wasi2_python.h` (about 900 lines, classified by names), `_shared.py`. No speed was measured. The `wasip2` sample is a core module with `wasi:` imports, not a real component.
