# One core, thin front ends: the principle, what is measured, and the way

Status: **written 2026-10-28 from the owner's statement of the same day; the audit below is a first measurement, nothing is moved yet.**

## The principle (the owner)

wasmext has three targets: the extension for CPython (`--extension`), the shared library with a wrapper for ctypes (`--shared`) and the executable (`--exe`). **They were meant to be one core with thin front ends.** The Python glue is only a binding: it converts types and keeps Python objects alive, and the logic is in one place, in C, below it. **Two parallel implementations of the same logic are a defect**, not a design: every feature is written twice, and the two drift apart.

A test of "thin": a new feature of the module (a table, a `funcref`, a tag, a registry) is written **once**, in the core, and each front end adds only the conversion of its values.

## What is there now (measured 2026-10-28)

Two small modules built in all forms (`wasmext natify`, the C written without compiling; the wrapper for ctypes from `build_shared`). Lines of each file:

| Module | extension `*_py.c` | wrapper for ctypes `*_ctypes.py` | shared library `*_shared.c` | public C API `*_api.h` |
| --- | ---: | ---: | ---: | ---: |
| `add` (one export, nothing else) | 409 | 835 | 181 | 91 |
| `rich` (an import, a memory, a table, a global) | 1288 | 1047 | 348 | 135 |

Going from `add` to `rich` adds about 880 lines to the extension, about 210 to the wrapper for ctypes and about 170 to the shared library. The logic of tables, functions, globals and the linking of instances is **in both Python layers, each its own copy**, and the C API that both could share exposes little.

Where the logic is (the largest functions of `rich`):

- extension: `Instance_new` (74 lines; makes the instance, binds the imports), `Table_set` (52), `Function_call` (40), `lookup_import` (31), `table_find_function`, `function_holder`, `export_ref`, `attach_traps`, `raise_trap_code`;
- wrapper for ctypes: class `Instance` (344), `Table` (119), `_set_import` (75), `Function` (68), `_share_traps`, `Store`.

**How tangled it is** (a rough count on the generated C of the extension, by function: references to the Python API, `Py*`): in `add` 4 % of the lines are in functions with no reference to Python, in `rich` 2 %, in a module with a shared table 3 %; 86 to 89 % are in functions with four or more. A reference is also a plain conversion (`PyLong_AsLong`), so the count is coarse, but it says the logic **cannot be lifted out as it is**: it has to be unpicked from the handling of Python objects first.

A first consequence is already known: the same scenario (a function of a table that calls a Python callback) works on one pair of front ends and traps on another (`tests/test_wasi_across_instances.py`, `test_a_python_callback_in_a_table_function`; the cause is that `CDLL` of the wrapper releases the GIL and the extension calls Python without it). With one core there would be one place for that rule.

## The decision of the owner (2026-10-28)

**First level what exists, before anything is added.** No new feature of the store (the registry of owners, `funcref` in imports, `externref`, tags) is built until the audit below is done and the first pieces are in the core. The order of the plan is changed to that.

## The way (proposed, not decided)

1. **Audit.** For every function of the two Python layers, one line: *conversion of a value* / *life of a Python object* / *logic*. The numbers above are lines, not this; the table says what really has to move and how much. It is the measure for "done".
2. **The core API.** `<name>_api.h` grows from "make a store, make an instance, call an export" to what the front ends need: the linking of imports to exports, tables and their functions, globals, memory, the traps (the entry stack), the owners. Plain C, no Python, the same for the three targets.
3. **Owners.** What keeps a function alive is not a Python object in the core. The core holds an **opaque owner handle with a retain and a release supplied by the front end**: the extension gives `Py_INCREF`/`Py_DECREF`, the wrapper for ctypes its own references, the executable nothing. The registry of owners ([owners_registry.md](owners_registry.md)) is in the core and uses those two calls. *To be decided*; it is the main design question of this note.
4. **Move a piece at a time**, with the behaviour and the tests unchanged: first what the registry and `Function` need anyway (tables, `funcref`, the linking), then the rest. After each piece the Python layers must be smaller and the tests the same.
5. **Done when** the audit table has no *logic* in the Python layers, or each remaining line is explained, and a feature is added in one place.

## Open

- Which parts are logic but cannot leave Python (exceptions from a callback become traps; a Python callable as a host function): the audit is to say, and the answer is the list of things the front ends must provide.
- The cost of the extra step through the core API on the hot path (a call into wasm): to be measured with the same benchmark as before (`docs/context_concept.md`, "Overhead").
- Whether the wrapper for ctypes can stay Python at all or becomes generated from the API (a binding), so that it is thin by construction.
