---
title: Shared store across artifacts
kind: spec
id: S0008
status: draft
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
  differs, `runtime` differs, the creator was built without the trap handler, or the store is closed.
* `wasmext_store_new` takes the serial from the runtime of the store (`rt->next_serial()`); the per-artifact `wasmext_store_serial_` goes away.
  `wasmext_instance_new` refuses a store this artifact did not make or attach (`EXDEV`).
* `_natify` `_RUNTIME_WRAPPERS`: `impl` always defines `WASM_RT_TRAP_HANDLER`; `exceptions` renames the seven functions of the exceptions file to
  `wasmext_own_*` and defines the real `wasm_rt_*` names as forwarders to the active runtime (a wrapper in the manner of D6; the toolchain file is untouched).
* Signature letters `F` (funcref) and `E` (externref) replace `r` in `wasmext_export.signature`; shims and typed slots with references pass
  `wasm_rt_funcref_t` by value and `void *`.
* `int wasmext_tag_new(const uint8_t *types, uint32_t n, wasmext_export *out)`: a host tag, **immortal** (process lifetime, `store = NULL`),
  accepted by `bind_export` from any store.
* Discovery: the host passes the `wasmext_store *`; in layer 3 a capsule `wasmext.store.v<X>` carries the same pointer. No named symbol.

## Semantics
* No artifact is bound for life. An instance runs on the runtime of the store it was made in; the `wasm_rt_*` of every copy (the `exceptions` wrapper, `WASM_RT_TRAP_HANDLER`) forward to the active runtime of the thread. A call that passes through instances of two stores (a host function in between) has one active runtime at a time, each store's own entry stack.
* Through a table (raw call B to A): no store enter; a trap anywhere goes to the active runtime's trap and then to the innermost entry; a throw goes to the
  innermost `try` of any copy.
* Through a link: B's forwarder calls A's shim (nested enter); LINKED+code is re-raised in B. Open: re-throw an uncaught exception instead of trapping.
* Every copy that has an instance in the store is made ready on the thread at the first entry (stack limit and `wasm_rt_init_thread`). With depth counting
  (Windows, Emscripten) the entry saves and restores the counters of those copies.
* Every attached artifact stays loaded until `wasmext_store_free` returns; `attach` adds an unload hook through `wasmext_store_adopt` (freed last).
* Imported tag cell stays one per (artifact, module) per process (D34).
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

## Decisions (taken on 2026-10-30 by the model of Wasmtime, at the maintainer's instruction)
1. **Design 1.** In Wasmtime an exception thrown by code of one module is caught by a `try` of another in the same store, because the runtime is one. Design 2 cannot do it.
2. **The `exceptions` wrapper is acceptable under D6.** It is a wrapper outside the toolchain file (the manner of the `mem` wrapper); it is the only way to give the seven functions the runtime of the store.
3. **Host tags belong to the store** (in Wasmtime a `Tag` is made in a `Store` and lives and dies with it), not immortal. The process-global cell of an imported tag (D34) is set once as before and **cleared when the store that made the tag closes** (compare-and-swap from this tag to empty); while a store holds the tag, a second live store that imports the same name gets `WASMEXT_STORE_INCOMPATIBLE` with the reason. This is a limit of wasm2c (one global symbol per import name), noted in the spec and not hidden.
4. **Shared entry in every build** (Wasmtime has one entry for all). Kept unless the benchmark shows more than 10 percent on case 1 or 2; then a build option with a record flag is a new decision.
5. **Compatibility:** the same x of the ABI and the same layout hash (`attach` refuses otherwise). Not the same source fingerprint: that would forbid two releases of one x, and the ABI is one thing for alpha.
6. **A link re-throws an uncaught exception** in the importer (Wasmtime propagates an exception through every frame of the store). This changes S0007 ("exceptions do not cross links"); S0007 is changed first, in the same step.
7. **Depth counting** (Windows, Emscripten): the entry saves and restores the counters of the copies that have an instance in the store. Moving Windows to the stack-limit check is a separate step if it measures better.
8. **New Dn** (written with the step): one supersedes D29; one amends D34 (host tags belong to the store, the cell is cleared at close); one records that D2's condition ("one party owns the traps of a group") is met; one records that the host is shared through the store (supersedes the line of `architecture.md`).
Known risks, not solved: MSVC `longjmp` across two DLLs (SEH) is untested; the artifact that made a store must stay loaded while any instance of the store runs.

Status stays `draft` until the maintainer sets `approved` (rule of CLAUDE.md: no code before). Step 8 is built as 8a then 8b, each with an independent `reviewer` and a before/after run of `tools/bench_calls.py`.

## Changes
* 2026-10-30: created (draft) from the design study of a `Plan` agent.
* 2026-10-30: design 1 revised: the runtime belongs to the store, not to the artifact (no binding for life; open question about the interpreter dict removed).
* 2026-10-30: the model stated as that of Wasmtime (runtime, host and state shared in the store; only the distribution of the runtime differs).
* 2026-10-30: binding to the store explicit; stores share nothing (one known leak: the process-global cell of an imported tag).
* 2026-10-30: open questions decided by the model of Wasmtime; waiting for `approved`.
