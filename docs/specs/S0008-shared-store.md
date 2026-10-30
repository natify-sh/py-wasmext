---
title: Shared store across artifacts
kind: spec
id: S0008
status: approved
superseded_by:
related: [D1, D2, D3, D29, D34]
owner: maintainer
updated: 2026-10-30
---

# S0008 Shared store across separately built artifacts

## Summary
Today a store links only instances made by the same artifact (one `.so` / `.pyd` / `.dll`, which has its own copy of the wasm2c runtime).
Step 8 lets artifacts built apart attach to one store and link, share tables, tags and references, and trap and throw across each other.
This changes the contract of the store, of the entry macros and of the exception functions, so it needs this spec approved before code.

Facts that bound the design (checked in the code and in the runtime sources of wasm2c 1.0.42):
1. Each artifact has its own `g_wasm_rt_jmp_buf`, unwind target, exception state, depth counter and stack limit. Today the generated entries
   (`WASMEXT_ENTER_REENTRANT/PLAIN`) write only the artifact's own copy, so a trap in another copy's code cannot reach the entry.
2. The exception state in the stock runtime file is a `static` thread-local per copy: a `try` in B never catches a throw from A.
3. The store code is `static inline`, so B works directly on A's store struct (mutex, registry, arena). Attach is safe only with an identical layout.
4. The store calls function pointers of the artifact that added a member, at close, from whichever copy runs `close`.
5. Trampolines alone do not work: re-raising a trap in "the caller's copy" needs the same per-thread shared state as option (b) of TABLES_PLAN.

## Goals / Non-goals
* Goals: attach with a checked record; links, tables, tags, externref and funcref across artifacts; a trap or a throw in one copy reaches the
  innermost entry or `try` of the thread; serials that cannot collide; close and free from either copy; a measured hot path.
* Non-goals: detaching before `store_free`; Pyodide and Android runs (until the emulator task);
  typed host functions with references (FFIs cannot pass structs by value; they use the uniform shape).

## Interface (proposed, recommended design 1)
* The **runtime of a store**. Every artifact keeps a full copy of the runtime (autonomy: one module needs nothing outside it) and uses it for the stores
  it makes itself. A store points at its runtime (`store->rt`, `wasmext_runtime`: a versioned table of the functions the code of an instance calls: trap,
  throw and catch with the exception state, allocate/grow/free of memories and tables, the stack check, the serial counter) and holds the per-thread stack
  of entries. An instance of any artifact made in that store runs on that runtime. `wasmext_artifact` (per artifact: `thread_ready`, `thread_free`, `depth`)
  lets the store make a foreign copy ready on a thread. The table only grows at its end.
* `WASMEXT_ENTER_SHARED` / `WASMEXT_LEAVE_SHARED` replace REENTRANT/PLAIN in all generated code; inline when the store runs on the runtime of the artifact itself.
  `enter` sets the active runtime of the thread from `store->rt` and `leave` restores the previous one and the saved unwind target (not `prev->buf`).
* A fixed header at the start of `wasmext_store`: `{size, abi, floor, layout, runtime, flags, rt}`. `int wasmext_store_attach(wasmext_store *s, char *why, size_t cap)`;
  new code `WASMEXT_STORE_INCOMPATIBLE`. `attach` refuses (reason in the caller's buffer) when x differs or below `floor`, `size` differs, `layout`
  (hash of sizes and offsets of store, registry, slot, owner ops, arena node, rlock, instance, host func, extern, `WASMEXT_NO_THREADS`, `_MSC_VER`)
  differs, `runtime` differs (code `WASMEXT_STORE_INCOMPATIBLE`), the creator was built without the trap handler (8b), or the store is closed (code `WASMEXT_STORE_CLOSED`, built so in 8a-1).
* `wasmext_store_new` takes the serial from the runtime of the store (`rt->next_serial()`); the per-artifact `wasmext_store_serial_` goes away.
  `wasmext_instance_new` refuses a store this artifact did not make or attach (`EXDEV`).
* `_natify` `_RUNTIME_WRAPPERS`: `impl` always defines `WASM_RT_TRAP_HANDLER`; `exceptions` renames the seven functions of the exceptions file to
  `wasmext_own_*` and defines the real `wasm_rt_*` names as forwarders to the active runtime (a wrapper in the manner of D6; the toolchain file is untouched).
* Signature letters `F` (funcref) and `E` (externref) replace `r` in `wasmext_export.signature`; shims and typed slots with references pass
  `wasm_rt_funcref_t` by value and `void *` (built in 8a-2; typed host functions with references stay refused).
* `int wasmext_tag_new(wasmext_store *s, const uint8_t *types, uint32_t n, wasmext_export *out)`: a host tag that **belongs to the store** (a member of kind
  `WASMEXT_KIND_TAG`, freed at close; see Decisions item 3 and 8a-3 under Changes). `bind_export` accepts it only for an instance of the same store.
* Discovery: the host passes the `wasmext_store *`; in layer 3 a capsule `wasmext.store.v<X>` carries the same pointer. No named symbol.

## Semantics
* No artifact is bound for life. An instance runs on the runtime of the store it was made in; the `wasm_rt_*` of every copy (the `exceptions` wrapper, `WASM_RT_TRAP_HANDLER`) forward to the active runtime of the thread. A call that passes through instances of two stores (a host function in between) has one active runtime at a time, each store's own entry stack.
* Through a table (raw call B to A): no store enter; a trap anywhere goes to the active runtime's trap and then to the innermost entry; a throw goes to the
  innermost `try` of any copy.
* Typed HOST functions with references are refused by `bind_typed`; a sealed record built by a C host is trusted C (`bind_export` compares letters and refuses an unknown one, not the code behind the address).
* Through a link: B's forwarder calls A's shim (nested enter); LINKED+code is re-raised in B. Open: re-throw an uncaught exception instead of trapping.
* Every copy that has an instance in the store is made ready on the thread at the first entry (stack limit and `wasm_rt_init_thread`). With depth counting
  (Windows, Emscripten) the entry saves and restores the counters of those copies.
* Every attached artifact stays loaded until `wasmext_store_free` returns. In 8a-1 this is the host's duty: `attach(s, why, cap)` only records the artifact in the store and has no unload hook (a hook would need a parameter; decide with the front end, layer 2).
* Imported tag cell stays one per (artifact, module) per process (D34); the store that holds a host tag clears the cells it was given when it closes (8a-3).
* The binding of an instance to a runtime is explicit and by store: whoever calls `wasmext_store_new` makes the store and its runtime, and any other artifact
  joins it only by `wasmext_store_attach`. Several stores can live in one process, each with its own instances, runtime, host and state, and nothing is
  shared between stores (a link, a table, a reference or a funcref of another store is refused, as today). One leak is known and comes from wasm2c, not from
  the design: an imported tag is a process-global symbol, so its cell is one per (artifact, module) per process (D34) and two stores that import the same
  tag get the same tag. Open question 5 is about this.
* The model is that of Wasmtime: a store is the one place where the runtime, the host (WASI state: descriptors, arguments, environment, preopens) and the
  state of its members live, and the instances of one or several modules (of any artifact) in it share all three. What differs from Wasmtime is only how the
  runtime is distributed: not one library, but a copy inside every artifact, of which the copy of the artifact that made the store is the one in use.
  A module that is alone needs nothing outside itself. The host of the store is reached through the store by an instance of any artifact; its layout is
  part of what `attach` checks (`layout` of `wasmext_host`, P1 bit, fusedwasi version). `docs/architecture.md` says "the state of WASI never crosses
  (opaque)"; that line is older and is superseded by this section, and needs a new Dn.

* The hashes of the layout rest on a hand-written list of the fields of each struct (`WASMEXT_LF_` in `wasmext_store.h`, `wasmext_instance.h`, `wasmext_host.h`), each struct salted with a constant of its own: a new field of a listed struct, or a new struct that another copy reads inline, must be added to the list, and a test in `tests/test_artifacts.py` swaps fields to prove the list is followed. What is hashed of the structs of fusedwasi (the state, the stream, the preopen) is their size, the preopen's fields and the switches of the build (`WASMEXT_HOST_P1`, the bits of a handle); the version of fusedwasi is not in it, because its headers have none (`fusedwasi.h` names a `<fusedwasi/version.h>` that the installed tree lacks).
* The functions that add to a store on behalf of the calling artifact (`instance_new`, `tab_new`, `extern_new`, `store_own`, `store_adopt`, `store_register`, `store_set_host`) refuse a store that this artifact neither made nor attached to, before they touch anything past the head (EXDEV for the two that answer an errno; `WASMEXT_STORE_INCOMPATIBLE` for the store functions; `WASMEXT_INST_BAD_ARGS` for `extern_new`).

### Known limit of 8a-1 (fixed by 8b)
* A trap (a signal included) in code of one copy while two copies are in one store aborts, or jumps into the stale buffer of the other copy. Seen in review: a guard-page access in `w2c_liba_load` ran the handler of signals of `libartifact_b`, which called its own `wasm_rt_trap`, found no entry and aborted (SIGABRT). Each copy has its own `g_wasm_rt_jmp_buf`, unwind target and handler, and the handler that runs is that of the copy that installed its chain last. 8a-1 therefore tests no trap across artifacts; the traps of one copy alone are as before.
* Requirement for 8b: a thread that calls into two copies leaks one alternate stack. Each copy of the runtime allocates and installs its own `sigaltstack` in `wasm_rt_init_thread`; the second replaces the first, and `wasm_rt_free_thread` of a copy frees its stack only if it is the one in place (the other is reported as "alternate stack was modified unexpectedly" and kept, so LeakSanitizer reports it). The readiness of the copies of a store on a thread (`thread_ready` and `thread_free` of all of them, in the reverse order) must be made one operation in 8b.

### Known limits of 8a-3
* Another copy of the core (an artifact that attached to the store) reallocs the list of cells `t->cells` that the copy that made the tag frees. This is fine with one libc; with separate CRT heaps (Windows, two DLLs) it is not. The registry has the same limit.
* A thread-local exception can keep the address of the tag of a closed store. The address is only compared (identity of the exception), never dereferenced.

## Test plan
`tests/c/test_artifacts.c` with a fixture `build_artifact` that uses the product's repairs and wrappers (D35); each artifact is a shared library with
hidden visibility, the test asserts the two copies' `wasm_rt_trap` addresses differ (also a Linux `dlopen(RTLD_LOCAL)` variant).
1. attach and each refusal text; 2. links of function, memory, global, table, tag, funcref and externref across artifacts;
3. traps (`unreachable`, guard-page OOB, host trap, recursion, A and B mutual recursion), first on a fresh thread where A was never entered, and from a deeper frame;
4. B writes into A's table, A calls B's function and it traps; 5. A throws through a table and B catches it, host reads the exception, host throw caught in A;
6. two threads, TSan; 7. nested stores; 8. close and free from either copy, each release once, unload hook last, ASan; 9. serials: a handle of a store made by B given to A is `WRONG`;
10. host tag in two stores, a second tag refused; 11. `-DWASM_RT_STACK_DEPTH_COUNT=1`, 10k traps, no false `EXHAUSTION`.
Mutations that must fail for the right reason: REENTRANT entry (case 3 aborts); layout check skipped (case 1); leave restores `prev->buf` (case 5);
serials from the artifact counter (case 9); no readiness of joined copies; adopt order reversed (ASan).
Benchmark: `uv run python tools/bench_calls.py` before and after, store of the artifact itself and of another artifact, numbers in `docs/BENCHMARKS.md`
(baseline there: case 1 about 56 ns, case 2 about 111 ns). An independent `reviewer` reads the diff.

## Alternatives considered
* **Design 2, fan-out per store, no runtime of the store:** each entry sets the top and unwind target of every attached artifact (O(n) per entry). Traps are right;
  exceptions do not cross artifacts (they become `UNCAUGHT` at the entry and skip B's `catch`, against S0007); serials only less likely to collide. No binding rule.
* **Design 3, no shared trap state:** links only through shims; a funcref of another artifact is refused. Free on the hot path, but it is option (d) that D3 rules out. Usable as step 8a.
* Trampolines only (a) and same-artifact-only (c): ruled out by D3.
Design 1 was corrected on 2026-10-30 after the maintainer's remark: copies of the runtime exist for autonomy, and instances of all modules in a store use the runtime of that store; there is no binding of an artifact to a group for life. Recommended: design 1, built as **8a** (record, attach, serials, lifetimes, references in signatures, host tags) then **8b** (the group state).

## Measured alternative: an opaque store (decided 2026-10-30: not taken now)
Store operations through a table of pointers into one place, instead of inline code and struct layouts in each artifact, would remove the layout hash, the artifact list and the identity of the artifact. Prototype and numbers: `docs/experiments/opaque_store/` (three runs, Xeon 2.8 GHz, gcc 13.3): operations of the store through the table cost +7.8 to +10.1 percent on case 1 and +11.2 to +11.8 percent on case 2 of `tools/bench_calls.py` (about 1.5 ns per indirect call; 3 per call, 7 through a link). Over the 10 percent rule on case 2. The maintainer decided to keep the inline store with the layout hash. A hybrid (hot head inline, cold operations through a table) stays a possible later change, with its own measurement and Dn.

## Decisions (taken on 2026-10-30 by the model of Wasmtime, at the maintainer's instruction)
1. **Design 1.** In Wasmtime an exception thrown by code of one module is caught by a `try` of another in the same store, because the runtime is one. Design 2 cannot do it.
2. **The `exceptions` wrapper is acceptable under D6.** It is a wrapper outside the toolchain file (the manner of the `mem` wrapper); it is the only way to give the seven functions the runtime of the store.
3. **Host tags belong to the store** (in Wasmtime a `Tag` is made in a `Store` and lives and dies with it), not immortal. The process-global cell of an imported tag (D34) is set once as before and **cleared when the store that made the tag closes** (compare-and-swap from this tag to empty); while a store holds the tag, a second live store that imports the same name gets `WASMEXT_INST_TAG_HELD` (from `bind_export`; `WASMEXT_STORE_INCOMPATIBLE` stays for `attach`) with the reason. This is a limit of wasm2c (one global symbol per import name), noted in the spec and not hidden.
4. **Shared entry in every build** (Wasmtime has one entry for all). Kept unless the benchmark shows more than 10 percent on case 1 or 2; then a build option with a record flag is a new decision.
5. **Compatibility:** the same x of the ABI and the same layout hash (`attach` refuses otherwise). Not the same source fingerprint: that would forbid two releases of one x, and the ABI is one thing for alpha.
6. **A link re-throws an uncaught exception** in the importer (Wasmtime propagates an exception through every frame of the store). This changes S0007 ("exceptions do not cross links"); S0007 is changed first, in the same step.
7. **Depth counting** (Windows, Emscripten): the entry saves and restores the counters of the copies that have an instance in the store. Moving Windows to the stack-limit check is a separate step if it measures better.
8. **New Dn** (written with the step): one supersedes D29; one amends D34 (host tags belong to the store, the cell is cleared at close); one records that D2's condition ("one party owns the traps of a group") is met; one records that the host is shared through the store (supersedes the line of `architecture.md`).
Known risks, not solved: MSVC `longjmp` across two DLLs (SEH) is untested; the artifact that made a store must stay loaded while any instance of the store runs.

Status `approved` by the maintainer on 2026-10-30 ("затверджую, починай 8a"). Step 8 is built as 8a-1 (header, layout hash, `attach`, `instance_new` refusal, test with two artifacts built apart, links through shims, a funcref of a foreign artifact refused), 8a-2 (references in link signatures: letters `F` and `E`), 8a-3 (host tags owned by the store), then 8b (runtime of the store: entry, exceptions, serials), each with an independent `reviewer` and a before/after run of `tools/bench_calls.py`.

## Changes
* 2026-10-30: created (draft) from the design study of a `Plan` agent.
* 2026-10-30: design 1 revised: the runtime belongs to the store, not to the artifact (no binding for life; open question about the interpreter dict removed).
* 2026-10-30: the model stated as that of Wasmtime (runtime, host and state shared in the store; only the distribution of the runtime differs).
* 2026-10-30: binding to the store explicit; stores share nothing (one known leak: the process-global cell of an imported tag).
* 2026-10-30: open questions decided by the model of Wasmtime; waiting for `approved`.
* 2026-10-30: approved by the maintainer; 8a-1 started.
* 2026-10-30: 8a-1 built. Differs from the text above: `wasmext_store_new()` and `wasmext_store_attach()` are macros over `wasmext_store_new_`/`wasmext_store_attach_` that pass `WASMEXT_CORE_IDENT` (abi, floor, layout, runtime), because the layout of the instance structs is known only in `wasmext_instance.h` and `wasmext_store.h` stays free of wasm2c (a program with the store alone gets a store-only layout and runtime 0); a closed store is `WASMEXT_STORE_CLOSED`; no unload hook; `wasmext_export` gets a field `artifact` at the end (the identity of the artifact: the address of `wasmext_artifact_`, defined with `WASMEXT_DEFINE_THREAD_STATE`), and `wasmext_instance`/`wasmext_tab` carry it; `instance_new` of a store this artifact neither made nor attached is `EXDEV`; the refusal of a funcref of another artifact is a TEMPORARY guard (`WASMEXT_TAB_FOREIGN_ARTIFACT`, one function `wasmext_foreign_artifact_`, every use marked "removed by 8b"). Found: a thread that calls into two copies leaks the alternate stack of the first (each copy installs its own, the runtime frees only the one in place); 8b makes the copies of a store ready together.
* 2026-10-30: 8a-1 after review: the layout hash covers every field (offset and size) of every struct another copy reads inline, `wasmext_tab` included (its struct moved to `wasmext_instance.h`); the layout of `wasmext_host` has its own word in the head (`host_layout`, set by `wasmext_store_set_host`, checked by `wasmext_instance_instantiate` against `wasmext_binding.host_layout`, the first call that touches the host); `has_artifact`/`instance_new` compare size, layout and runtime of the full core before locking; `wasmext_artifact_` is hidden; the temporary guard has a test and a mutation at every site; the artifacts are built with the product's `WASMEXT_CHAIN` flags.
* 2026-10-30: 8a-1 after the second review: the host hash has the switches of the build and the preopen of fusedwasi (no version macro exists: not hashed, said above); every hashed term is salted by its struct; `wasmext_funcref` is hashed; `tab_new`, `extern_new`, `store_own`, `store_adopt`, `store_register` and `store_set_host` check the store as `instance_new` does (the core calls the `_unchecked_` functions on stores it has checked); `wasmext_artifact_` hidden is tested.
* 2026-10-30: 8a-1 built (commits 7d48f84, 07534f0); opaque store measured and not taken; inline store kept.
* 2026-10-30: 8a-2 built. Differs from the text above: the letters are compared as letters by `bind_export` (the old refusal of `r` is gone); the checks are in the shim (a funcref: `wasmext_funcref_from_` and the temporary guard against the callee's artifact; an externref: `wasmext_extern_check_`; the answer is in `*trapped` as `WASMEXT_TAB_WRONG_STORE`/`STALE`/`FOREIGN_ARTIFACT`, which the importer turns into the trap `WASMEXT_TRAP_HOST`) and in the importer's forwarder (a funcref result: the same funcref check and guard); a funcref made by `ref.func` has the function itself in `func`, the export has its wrapper, so equality of funcrefs is by instance, not by `func`; a static assert (typedef of negative size) checks four words and a pointer. The shim path of an externref is checked in the shim only, not again in the importer.
* 2026-10-30: 8a-3 built (D39). Differs from the text above: `wasmext_tag_new` takes the store first and checks it as `wasmext_extern_new` does (a store this artifact neither made nor attached to: `WASMEXT_INST_BAD_ARGS`; closed: `WASMEXT_TRAP_CLOSED`); the types are the bytes of the binary format and a type that is not a value type, or more than 62 values, is `BAD_ARGS`. The tag is a `wasmext_host_tag` (identity = the address of its first byte, the signature as a record says it, the list of cells), registered under that address with kind `WASMEXT_KIND_TAG` and owned by the arena (freed at close, after the close of the members). The struct is in the hash of the layout (another copy of the core appends to its list). `bind_export` of a tag import, before it sets the cell, finds the tag among the members of the instance's store and remembers the cell in the tag's list (once; also when the set is then refused, which is harmless: the clear is a compare-and-swap from this tag to empty, `wasmext_cell_clear`); the close of the tag member clears its cells. A tag import already held by another tag is `WASMEXT_INST_TAG_HELD` (-12, returned by `bind_export`) with the reason in the text of the store, whether the record is a host tag or the tag of a module (one condition, one code; the texts differ; the code is not `WASMEXT_STORE_INCOMPATIBLE`, which is 8 and collides with `WASM_RT_TRAP_UNCAUGHT_EXCEPTION` in `wasmext_error_describe`); the core does not read the pointer in the cell (a store could free it at that moment). Found: the dangling of the cell exists only for host tags; the tag of an exporting instance is `w2c_<prefix>_<name>`, a constant of the module's own data, so closing its store leaves the cell pointing at data that lives as long as the program and a new store links the same tag again (tested in `test_host_tags.c`). A tag that is a host tag of a store that has a cell set is read by running code without a lock: the close clears only after `closed` is set, when no call is in flight or can start.
* 2026-10-30: 8a-3 after review: `wasmext_tag_new` owns the tag first and registers it last (a close in between could free it under `tag_new`); the cell is set inside `wasmext_tag_link_` under the lock of the store, after the check of `closing` (a bind that races a close could write a freed tag into the global cell); `bind_export` refuses at once an exporter record of a closed store (`WASMEXT_TRAP_CLOSED`: a tag's signature and a table are freed by the close); a held tag import is `WASMEXT_INST_TAG_HELD` (-12), no longer `WASMEXT_STORE_INCOMPATIBLE` (8, which collides with a wasm2c trap code); known limits of 8a-3 added.
