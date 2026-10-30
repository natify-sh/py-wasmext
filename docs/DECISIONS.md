---
title: Decisions
kind: log
status: current
updated: 2026-10-30
---

# Decisions

Short records: what was decided, why, what was rejected. Newest last. Never renumber; to change a decision add a new one with Supersedes: Dn.

The step documents `step1` to `step7` were moved to `docs/specs/` (`S0001` to `S0007`) on 2026-10-30; the section names in `Source:` lines are those of the old step texts (in git before that commit).

Dates are those of the source document. "undated" means the source gives no date. An entry that says CONFLICT: found two documents that disagree; both facts are written and nothing was chosen.

### D1. Every artifact keeps its own copy of the runtime; no shared runtime library
Status: accepted · Date: 2026-10-22 · Supersedes: — · Evidence: docs/experiments/shared_runtime/
Modules stay autonomous: each carries its own copy of the wasm2c runtime and runs alone. Rejected: one shared runtime `.so` with one store (a Wasmtime in miniature, which the project leaves; it fails across wheels because auditwheel and delocate give each wheel its own copy, and it fixes one set of runtime macros for all modules). The master/slave experiment worked but its fall-back stole the process signal handler, so it was not built.
Source: docs/context_concept.md, "Considered and not taken"; docs/shared_runtime_concept.md, "What the first experiment showed" and "Update 3"

### D2. Signals and the stack: a chain of handlers, not a shared runtime
Status: accepted · Date: 2026-10-22 · Supersedes: — · Evidence: tests/test_two_modules.py
Two modules in one process disagreed about the one signal handler. The answer built is a chain of handlers (and a stack check in each function prologue by default), for the extension and the shared library. The shared runtime (master and slave) is not built and not needed for signals; it is reconsidered only for a nested call of one module from another or a mode where one party owns the traps of a group, and neither has a consumer.
Source: docs/shared_runtime_concept.md, "Update 3 (later on 2026-10-22): what was built"

### D3. Tables: the writing of a foreign table is part of the first version
Status: accepted · Date: undated (October 2026) · Supersedes: — · Evidence: tests/test_tables.py
A reduced scope (a table only when all its elements are made by its owner, or tables only inside one extension, or trampolines) was ruled out: case 2, an instance filling a table of another, is in the first version, so the trap in a function that comes out of another runtime had to be solved. The spike chose a trap handler that goes to the innermost entry of a shared stack of entries. `WASMEXT_ABI` was not raised for the tables.
Source: docs/TABLES_PLAN.md, "Decisions" items 1 and 2 and "The hard part"

### D4. wasmext is a compiler: nothing is made by the package at run time
Status: accepted · Date: undated (October 2026) · Supersedes: — · Evidence: tests/test_table_class.py
`Table`, `Memory`, `Global` are not classes of the package `wasmext` (as the JavaScript API has them); the glue of each module generates its own `Table` as it generates `Instance`, `Trap`, `LinkError`. The type of `instance.memory` stays a `memoryview`.
Source: docs/TABLES_PLAN.md, "Decisions" items 3 and 4; docs/DESIGN.md, the paragraph on `wasmext.Table`

### D5. Exports stay methods, not `Function` objects
Status: accepted · Date: undated (October 2026) · Supersedes: — · Evidence: —
`instance.add` is a method of the extension and a bound method of the wrapper. Where a reference is wanted (an import, `Table.set`, a `funcref` parameter) the glue finds the export by `__self__.__exports__[__name__]`. Decided by the owner; nothing is planned to change it.
Source: docs/TABLES_PLAN.md, "Decisions" item 5

### D6. Patches to wasm2c: small, outside first, no `.patch` files, no vendored WABT
Status: accepted · Date: undated (October 2026) · Supersedes: — · Evidence: tests/test_patches_needed.py
wasmext takes wasm2c and its runtime from the wabt-package and changes them by wrappers (`_RUNTIME_WRAPPERS`), regex repairs of the generated C, and macros. Seven rules: small and exact, outside the files of WABT first, match only the known shape, state the cause and have a test that fails without the patch, fail loudly, tie to the WABT version, upstream when possible. No `.patch` files and no vendored copy: "a decision, not an omission".
Source: docs/patch_policy.md, the opening paragraph and rules 1 to 7

### D7. The ABI number is `0xXXYYZZLS`; first version `0.0.1a1`; series `v0`
Status: accepted · Date: undated (October 2026) · Supersedes: — · Evidence: tests/test_abi.py, tests/test_abi_declaration.py
One 32-bit number like `PY_VERSION_HEX` (x stable ABI, y compatible additions, z patch, L level, S serial). The first version is `0.0.1a1` (`0x000001A1`). Capsule names carry only x (`wasmext.export.v0`); a reader links if x is equal, its version is not below the record's `floor`, and `size` covers the first fields. `1.0.0` is planned as the one break (the context/store). The runtime layout is checked when a module is built, not when linked. Rejected: taking the ABI automatically from the package tag.
Source: docs/abi_policy.md, "The version number (decided)", "The capsule and the linking rule (decided)"

### D8. Alpha does not keep the ABI
Status: accepted · Date: 2026-10-26 · Supersedes: — · Evidence: tests/test_abi_declaration.py
While the package is alpha (`L` = `0xA`) a change of the public surface may break what was built before; no new x, y or serial is needed. `abi/current.json` and the fingerprint of `src/wasmext/c/` are still renewed with every change. Layers.md repeats it for the rework: the ABI is changed freely, the declaration renewed once at the end of each step.
CONFLICT: the same abi_policy.md says in "The version number" that inside `0.y.z` "nothing is broken" and modules of any two `v0` versions link; the section "Alpha does not keep the ABI" says nothing in the alpha is frozen. The alpha section is the later decision (2026-10-26), but the older text is still in the file.
Source: docs/abi_policy.md, "Alpha does not keep the ABI (decided 2026-10-26)" and "The version number (decided)"; docs/layers.md, "How it is done"

### D9. The context is renamed Store, and the store is always made by hand
Status: accepted · Date: 2026-10-26 · Supersedes: — · Evidence: —
The model is the `Store` of Wasmtime (every artifact carries a copy of the implementation). The store is the main way for modules to talk: functions, tables, memories, globals, funcref, externref, tags and traps cross natively inside a store; between stores nothing is shared. There is no implicit store; `Instance(store, ...)` requires one. The configuration (`wasi=`) is an argument of `Store` only and is shared by all its instances; a different configuration is a different store.
Source: docs/WASI_TARGET_PLAN.md, "The store: decisions (final, the owner, 2026-10-26)"; docs/context_concept.md, the note under the title

### D10. Three ways to run a WASI module; no 0.1-on-0.2 layer in the host
Status: accepted · Date: 2026-10-26 · Supersedes: — · Evidence: docs/experiments/p1_adapter_on_p2.md
A 0.1 module runs as 0.1; a fused 0.2 module runs as 0.2; a 0.1 module that has to be 0.2 is converted at build time (the adapter of Wasmtime) and is then a 0.2 module. No call of 0.1 goes through the `wasi:*@0.2` layer in the host; the adapter `p1-on-p2` is dropped. `host` stays the requirement of a module.
Source: docs/WASI_TARGET_PLAN.md, "The store: decisions", "The ways to run a module"

### D11. The host of an artifact has all the families; one flag shrinks it
Status: accepted · Date: 2026-10-26 · Supersedes: — · Evidence: —
The host holds the state of each family (0.1 and 0.2), made with the store from the one `wasi=`, and a generated registry of all 46 + 201 functions. One flag, `host_full` (working name), on the host only: false answers only the WASI imports of the module itself. Everything else is in every build. Cost measured: about 150-160 KB at `-O2` for both families.
Source: docs/WASI_TARGET_PLAN.md, "The store: decisions", "The host."

### D12. The store holds its members strongly until it is closed
Status: accepted · Date: 2026-10-26 · Supersedes: — · Evidence: tests/c/test_registry.c
As Wasmtime and wasm3 do. Chosen over counting by hand (atomics, cycles, order of destruction). Price: the members only grow; one member cannot be unloaded; the first remedy is a store per batch of work (`with`). Rejected: a "domain" with `attach`/`detach`, and a table of handles for `externref`. A lazy mark-and-sweep collector (hot reload, unloading) comes later and the registry is made so it is possible.
Source: docs/context_concept.md, "Ownership: an arena, and what it costs", "Later: a lazy collector", "Considered and not taken"

### D13. Work is bottom-up and tested from C
Status: accepted · Date: 2026-10-28 · Supersedes: — · Evidence: tests/c/
Layer 1 (the static C core) is built complete and tested from C (a plain C harness in `tests/c/`, with sanitizers, on the CI matrix) before layer 2 (the FFI-neutral shared C API, one shape for every module) and layer 3 (the front ends: ctypes, executable, extension). A layer calls only the layer below. No step starts before the one below is complete and green. Layer 1 steps 1 to 12 are listed in layers.md. This replaces the piecemeal plan (and the `thin-glue` branch is not to be merged).
Source: docs/layers.md, "How it is done: bottom-up, tested from C (the owner, 2026-10-28)"

### D14. Existing code is not patched on the side
Status: accepted · Date: 2026-10-28 · Supersedes: — · Evidence: docs/layers.md register of duplicates
If something already built needs a change, it is not fixed in passing: it is taken when the plan reaches its step and done there once, or the change is a new Dn with the reason. The old generated copy stays until the step that owns it takes over; the register of duplicates lists each pair and a guard test keeps it from drifting. Known bugs of the old layers are not fixed in the old shape.
Source: docs/layers.md, "Rule (the owner): existing code is not patched on the side" and "Old code that a step replaces"

### D15. The shipped core is the same for every module; the generated binding holds data only
Status: accepted · Date: 2026-10-28 · Supersedes: — · Evidence: tests/test_instance_core.py
The static hand-written C core in `src/wasmext/c/` decides every rule. What is per module is the wasm2c output, the descriptor, and a small generated table that ties the core to the symbols wasm2c mangled; no rule is decided in it.
CONFLICT: layers.md says the generated binding is "data only". specs/S0003-instances.md, in the same plan, says the binding is also generated code: one adapter per distinct signature, the forwarders of imports, and the trampolines for host functions in tables, and asks "Accepted?" because a `libffi` is not taken (not on every target). The step 3 binding was built that way; "no rule decided in it" holds in both.
Source: docs/layers.md, "Layer 1: wasmext glue"; docs/specs/S0003-instances.md, "Generated (`<name>_binding.c`...)" and "Open" item 1

### D16. The core is header code compiled into each artifact
Status: accepted · Date: 2026-10-28 · Supersedes: — · Evidence: tests/c/test_store.c
`static inline` functions in headers, as `wasmext_glue.h` is: no switch, no separate `.c`. Each built module has its own copy, as it has of the wasm2c runtime. Layer 2 later prefixes the names with the module name.
Source: docs/specs/S0002-store.md, "Where the code lives, and how it reaches an artifact"

### D17. Step 1: one model at build time, one descriptor at run time
Status: accepted · Date: 2026-10-28 · Supersedes: — · Evidence: tests/test_descriptor.py, tests/c/dump_descriptor.c
`build_model` analyses a module once (frozen dataclasses, no I/O) and every emitter reads only it. The library describes itself at run time (`wasmext_descriptor`, read-only data, a `version` and `size` checked by a reader). Function types are inline in each import and export (no table of types); names are WebAssembly names, never mangled C names; value types use the bytes of the binary format; parameter names are in the descriptor (the owner's answer). Two readers of the same facts must agree (C text against `ModuleModel.dump()`).
Source: docs/specs/S0001-model-descriptor.md, the Status paragraph and "The descriptor"

### D18. `close` refuses when a call is in flight; it never waits
Status: accepted · Date: 2026-10-28 · Supersedes: — · Evidence: tests/c/test_store.c, tests/test_store_core.py
`wasmext_store_close` raises the flag, adds the split per-thread counters, and returns BUSY if a call is in flight, so a close from inside a call cannot wait for itself. Twice is 0. After the close every entry that takes the store fails with a code (`WASMEXT_TRAP_CLOSED` for a call), never a crash. Counters are split by thread because one shared counter costs about 300 ns per call on 4 threads against 25 to 35 ns.
Source: docs/specs/S0002-store.md, "What step 2 builds" item 3; docs/context_concept.md, "Closing"

### D19. Free-threaded safety is a requirement of layer 1; ctypes uses CDLL
Status: accepted · Date: 2026-10-28 · Supersedes: — · Evidence: tests/c/test_store.c (TSan)
Not a last item: from step 2 the store, the registry and the counters are thread-safe by design (one locking rule, atomic counts, no lock held across a call outward) and the C tests include concurrent use. `ctypes` loads the library with `CDLL`, never `PyDLL`. `Py_MOD_GIL_NOT_USED` is declared by the extension front end once its audit is done.
Source: docs/layers.md, "Free-threaded is a requirement of layer 1" and "Layer 3: the front ends"

### D20. The host lock lives in `wasmext_host` and is recursive; fusedwasi stays lock-free
Status: accepted · Date: 2026-10-29 · Supersedes: — · Evidence: tests/c/test_rlock.c, tests/c/test_wasi_imports.c
One host is shared by all instances of a store, so a WASI call takes one recursive lock in the host (a hook may call back into the module). Rejected: (b) "a store with WASI is for one thread at a time". The state of fusedwasi has no lock by design (the plan says so), and the README of fusedwasi has no sentence about it.
CONFLICT: layers.md and context_concept.md state the rule "no lock held across a call outward", and context_concept says a recursive mutex is not needed with it. The host lock of step 3b2 is held around a call into fusedwasi whose hook may call back into the module, hence recursive. The two rules are for different locks (registry and store against host); no document reconciles them.
Source: docs/specs/S0003-instances.md, "3b2" Open item 1 and Status (3b2a); the sentence about fusedwasi's README: maintainer, sessions of 2026-10-27..30

### D21. The host is an object owned by the store through the arena
Status: accepted · Date: 2026-10-29 · Supersedes: — · Evidence: tests/c/test_host.c
`wasmext_host_new` makes the host of fusedwasi (config copies, streams, clocks, random, sockets, http hooks); the store owns it with `wasmext_store_own`, and a host slot (`wasmext_store_set_host`, once) holds it, so the store module stays free of fusedwasi and wasm-rt (option A). One `wasmext_host` serves 0.1 and 0.2. The Python hooks later become plain C hooks with a `user`, in the extension's own step.
Source: docs/specs/S0002-store.md, "Part 2b" (What 2b builds, items 2 and 3); docs/specs/S0003-instances.md, "3b2" item 1

### D22. The configuration is strict
Status: accepted · Date: 2026-10-29 · Supersedes: — · Evidence: tests/c/test_host.c
An environment item with no `=` or no NAME, a directory with no host path, a NULL array with a count, or a NULL item is `EINVAL`. A `dirs` item must be `host::guest` with both parts; `NAME=` (empty value) is fine. Reason: nobody outside the project passes a configuration, so there is no old behaviour to keep.
Source: docs/specs/S0002-store.md, "Part 2b" paragraph "Built (2026-10-29)"

### D23. One host-function shape for every import, with a typed fast path kept
Status: accepted · Date: 2026-10-29 · Supersedes: — · Evidence: tests/c/test_imports.c
`int host_fn(void *user, const wasmext_val *args, wasmext_val *results)`; 0 is success. A typed shape `result f(void *user, parameters..., int *trapped)` stays, chosen per import. `wasmext_val` is a tagged value passed only by pointer or in arrays; `v128` is 16 bytes. Imports are bound by index of the descriptor.
Source: docs/specs/S0003-instances.md, "Static (`src/wasmext/c/wasmext_instance.h`)" item 5 and Status 3b1

### D24. The registry of owners lives in the store; the handle is a number with a generation
Status: accepted · Date: 2026-10-29 · Supersedes: — · Evidence: tests/c/test_registry.c
The core registers an instance itself when it is instantiated; a front end only replaces the object. A stale handle is recognised, not taken for a new member at the same address. This replaces the Python-capsule design (one registry per interpreter, shared through `wasmext.owners.v1`, weak entries, keep-alive chains `writers`/`refs`).
CONFLICT: docs/owners_registry.md (2026-10-28) still describes weak entries and the capsule, and TABLES_PLAN.md still describes the `writers`/`refs` chains. specs/S0004-owners-registry.md (2026-10-29) says it replaces the capsule design and keeps strong members; owners_registry.md keeps its reading of the problem only.
Source: docs/specs/S0004-owners-registry.md, Status paragraph and "What step 4 builds" items 1 and 4; docs/owners_registry.md, "The design"

### D25. Registry handle: 16-bit store serial, 24-bit index, 24-bit generation
Status: accepted · Date: 2026-10-29 · Supersedes: — · Evidence: tests/c/test_registry.c
Not 32 and 32 (the first design). With 32/32 a handle of one store opens the member in the same slot of another store, and a lookup by a pointer cannot say which store a pointer belongs to. `find` by a pointer answers UNKNOWN for a pointer of another store; a handle of another store is WRONG.
Source: docs/specs/S0004-owners-registry.md, Status paragraph, points (1) and (5)

### D26. Instances are linked only inside one store
Status: accepted · Date: 2026-10-29 · Supersedes: — · Evidence: tests/c/test_links.c
The store frees its members at close, and the first run showed a link across stores was a use after free under ASan (closing the exporter's store freed what the importer's functions read). So, as in Wasmtime, an object of another store is refused: `wasmext_export.store` was added and `bind_export` refuses a record of another store, with the reason in the text.
Source: docs/specs/S0004-owners-registry.md, Status paragraph, point (2)

### D27. The store frees its instances; `wasmext_instance_free` is refused when instantiated
Status: accepted · Date: 2026-10-29 · Supersedes: — · Evidence: tests/c/test_registry.c, tests/c/test_links.c
At close: first an unlink pass in reverse registration order (an importer lets go of what it took from exporters), then release in reverse order. A closed instance answers `WASMEXT_TRAP_CLOSED`, not a dangling pointer. The cyclic-collector walk (`wasmext_store_each`) exists, but a front end is not required to use it; what is required is an explicit close (`with store:`), as in `wasmtime-py`.
Source: docs/specs/S0004-owners-registry.md, Status paragraph points (3) and (4), and "What step 4 builds" items 5 and 6

### D28. An object of another store is a soft refusal in C and an exception in Python
Status: accepted · Date: 2026-10-29 · Supersedes: — · Evidence: tests/c/test_registry.c, tests/c/test_tables.c
An error code with the reason in the text of the store (`WRONG_STORE` and similar), never a panic or an abort; the Python front end raises its exception. The registry knows its own members only.
Source: docs/specs/S0004-owners-registry.md, Status paragraph (end), and "What step 4 builds" item 3

### D29. Tables first inside one artifact; the trap state across artifacts is step 8
Status: accepted · Date: 2026-10-30 · Supersedes: — · Evidence: tests/c/test_tables.c
Each artifact has its own `g_wasm_rt_jmp_buf`, so a trap in a function that comes from another artifact jumps to a buffer not set for the call. Inside one artifact there is no problem, and since step 4 a store is made by one artifact. A store joined by modules of another artifact needs shared trap state (the entry stack or a trampoline in the exporter); that is decided in step 8 and written there.
Source: docs/specs/S0005-tables.md, "The one hard fact" and "Open" item 1 (accepted, Status)

### D30. Host functions in tables and `call_ref` by the host only for declared types (the AOT rule)
Status: accepted · Date: 2026-10-30 · Supersedes: — · Evidence: tests/c/test_tables.c
The trampoline of a host function is made by the binding for each type the module declares in its type section; a type the module does not declare is `WASMEXT_INST_UNDECLARED_TYPE` and nothing is made. `call_ref` is matched like `call_indirect` (the type pointer, then its 256-bit hash). An element of an undeclared type can still be called by wasm. The same rule limits `wasmext_instance_throw` to tags the module exports or imports.
Source: docs/specs/S0005-tables.md, Status (5b-1, 5c) and "Open" items 2 and 3; docs/specs/S0007-tags-exceptions.md, "7c"

### D31. A funcref in a signature or a global is passed by pointer to a `wasmext_funcref`
Status: accepted · Date: 2026-10-30 · Supersedes: — · Evidence: tests/c/test_tables.c, tests/c/test_ref_globals.c
A `wasmext_val` of type 0x70 has `as.ref` pointing to a `wasmext_funcref` (NULL is the null funcref); the typed fast shape has none. A funcref carries its `store` and the `owner` handle, and `set` accepts it only if the pointer of its instance is a member of the store under that very handle: a forged value is refused, not trusted. Results are written where the caller points `as.ref` (NULL is BAD_ARGS). Globals of funcref and externref were put in step 6 (the owner accepted this); their cell is 32 bytes.
Source: docs/specs/S0005-tables.md, Status (5a, 5b-2); docs/specs/S0006-externref.md, Status and "6c"

### D32. `externref` is a pointer to a record the store owns until close; the lazy collector is step 9
Status: accepted · Date: 2026-10-30 · Supersedes: — · Evidence: tests/c/test_externref.c
`wasmext_extern_new(store, user, release, &ref)` makes a record `{user, release, store}`, a member of the store; its pointer is the `externref` WebAssembly sees. `release(user)` is called once at close (in Python: the decref). A value going in must be a member of this store, else `WASMEXT_TAB_WRONG_STORE`; NULL is always acceptable. The host cannot count references because wasm copies them where the host does not see (locals, tables, globals). Until step 9 a long-lived store holds every value it was given and the way out is to close it.
Source: docs/specs/S0006-externref.md, "The decision: the store owns what it is given" and "What crosses, and the checks"

### D33. Members of the registry have a kind (`WASMEXT_KIND_*`)
Status: accepted · Date: 2026-10-30 · Supersedes: — · Evidence: tests/c/test_registry.c (`test_kinds`), tests/c/test_externref.c
Found in review after step 6a: checks accepted any pointer that was a member of the store, so an instance pointer would have passed as an `externref`. Now a pointer is accepted as a reference only if it is an `EXTERN`, and as the `module_instance` of a funcref only if it is an `INSTANCE` or `HOST_FUNC` (`wasmext_store_find_kind`). The kind is a field in the ops, not the address of the ops, because every translation unit has its own copy of a `static const`. A change to step 4 code, made as a hole in what 6a built on it, not a side patch.
Source: docs/specs/S0006-externref.md, "Found in review, after 6c: the members have a kind"

### D34. Tags: one tag per import name in the program; tags made by the host wait for step 8
Status: accepted · Date: 2026-10-30 · Supersedes: — · Evidence: tests/c/test_tags.c
wasm2c reads an imported tag from a global symbol, so the binding defines that global and the core writes the exporter's tag into it once for the whole program (atomic compare-and-set); a link to another tag is refused. Two modules importing the same name from the same module collide at link time. A tag made by the host would be one per import name; it waits for step 8. Identity is the pointer (not structure).
Source: docs/specs/S0007-tags-exceptions.md, "7a" and "Not done, and why"

### D35. The C tests build what the product builds (step 7d)
Status: accepted · Date: 2026-10-30 · Supersedes: — · Evidence: tests/test_instance_core.py, tests/c/test_nomemory.c
The tests of steps 3 to 7 had built the raw wasm2c output and runtime. The fixture now runs the C through the repairs of `_natify` (`_repair_imported_elements`, `_portable`, `_repair_tail_calls`, `_export_tags`) and the runtime through `_RUNTIME_WRAPPERS` (a memory allocation traps, it does not `abort()`), using those very functions. The binding uses the table `wasmext_tags_<prefix>` so a tag the module keeps to itself is known. 7d was inserted after step 7 with the owner's agreement; raw wasm2c output is not a test subject.
Source: docs/layers.md, "7d (inserted after 7, the owner agreed 2026-10-30)"; docs/specs/S0007-tags-exceptions.md, "7d"

### D36. Custom page sizes and threads/atomics are done at the end of layer 1; `exnref` is last
Status: accepted · Date: 2026-10-30 · Supersedes: — · Evidence: —
Custom page sizes are item 10 (2026-10-28), threads and atomics item 11, `exnref` item 12 "at the very end" (2026-10-30), and only when a real module that uses it exists: the runtime has the type, but `_wasm.py` (`ValType`) does not know it. `exnref` and `throw_ref` are not carried by step 7.
Source: docs/layers.md, "How it is done" items 10 to 12; docs/specs/S0007-tags-exceptions.md, "Not done, and why"

### D37. Other build backends and `.wat` as a source are dropped; Android and Pyodide
Status: accepted · Date: 2026-10-28 · Supersedes: — · Evidence: —
Removed from the plans, because for each item of "begun and not finished" the decision is finish it in the new layers or remove it. Android arm64 and Pyodide already build in CI; Android is to be tested in an emulator in CI later (a task of the front-end phase). The tests use small `.wat` modules, which is not a source for users.
Source: docs/layers.md, "How it is done" (the paragraph "Removed from the plans")

### D38. Process: specs before contracts, decisions as Dn, lessons in LESSONS.md
Status: accepted · Date: 2026-10-30 · Supersedes: — · Evidence: docs/specs/README.md, docs/templates/decision.md
A spec (`docs/specs/Snnnn`) is written and approved before a contract is changed (the record `wasmext_export`, `wasmext_binding`, the descriptor, the trap state, the store layout), and a reviewer reads the diff without the implementer's reasoning. Decisions are recorded here with Dn ids and not re-opened without a new Dn that supersedes. Lessons (traps already found) go in `docs/LESSONS.md`. Decided after looking at the discipline of the w2py repository.
Source: CLAUDE.md, "Read first" and "How work is organised"; the w2py reference: maintainer, sessions of 2026-10-27..30
