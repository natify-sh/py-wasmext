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
* Non-goals: rebinding or merging groups after binding; detaching before `store_free`; Pyodide and Android runs (until the emulator task);
  typed host functions with references (FFIs cannot pass structs by value; they use the uniform shape).

## Interface (proposed, recommended design 1)
* A **group** record per set of artifacts: the per-thread stack of entries, the one unwind target, the active exception, the serial counter.
  `wasmext_runtime` (table of the runtime functions, grows only at its end) and `wasmext_artifact` (per artifact: `thread_ready`, `thread_free`,
  `depth`) in `wasmext_glue.h`; `int wasmext_runtime_join(const wasmext_runtime *group)`.
* `WASMEXT_ENTER_SHARED` / `WASMEXT_LEAVE_SHARED` replace REENTRANT/PLAIN in all generated code; inline when the artifact is its own group.
  `leave` restores the saved unwind target, not `prev->buf`.
* A fixed header at the start of `wasmext_store`: `{size, abi, floor, layout, runtime, flags, rt}`. `int wasmext_store_attach(wasmext_store *s, char *why, size_t cap)`;
  new code `WASMEXT_STORE_INCOMPATIBLE`. `attach` refuses (reason in the caller's buffer) when x differs or below `floor`, `size` differs, `layout`
  (hash of sizes and offsets of store, registry, slot, owner ops, arena node, rlock, instance, host func, extern, `WASMEXT_NO_THREADS`, `_MSC_VER`)
  differs, `runtime` differs, the creator was built without the trap handler, or the store is closed.
* `wasmext_store_new` takes the serial from the group (`rt->next_serial()`); the per-artifact `wasmext_store_serial_` goes away.
  `wasmext_instance_new` refuses a store this artifact did not make or attach (`EXDEV`).
* `_natify` `_RUNTIME_WRAPPERS`: `impl` always defines `WASM_RT_TRAP_HANDLER`; `exceptions` renames the seven functions of the exceptions file to
  `wasmext_own_*` and defines the real `wasm_rt_*` names as forwarders to the group (a wrapper in the manner of D6; the toolchain file is untouched).
* Signature letters `F` (funcref) and `E` (externref) replace `r` in `wasmext_export.signature`; shims and typed slots with references pass
  `wasm_rt_funcref_t` by value and `void *`.
* `int wasmext_tag_new(const uint8_t *types, uint32_t n, wasmext_export *out)`: a host tag, **immortal** (process lifetime, `store = NULL`),
  accepted by `bind_export` from any store.
* Discovery: the host passes the `wasmext_store *`; in layer 3 a capsule `wasmext.store.v<X>` carries the same pointer. No named symbol.

## Semantics
* An artifact binds to a group at its first `store_new`, `store_attach` or `runtime_join`; attaching to a store of another group is refused.
* Through a table (raw call B to A): no store enter; a trap anywhere goes to the group's trap and then to the innermost entry; a throw goes to the
  innermost `try` of any copy.
* Through a link: B's forwarder calls A's shim (nested enter); LINKED+code is re-raised in B. Open: re-throw an uncaught exception instead of trapping.
* Every copy joined to the group is made ready on the thread at the first entry (stack limit and `wasm_rt_init_thread`). With depth counting
  (Windows, Emscripten) the entry saves and restores the counters of the joined copies.
* Every attached artifact stays loaded until `wasmext_store_free` returns; `attach` adds an unload hook through `wasmext_store_adopt` (freed last).
* Imported tag cell stays one per (artifact, module) per process (D34).

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
Benchmark: `uv run python tools/bench_calls.py` before and after, own group and attached, numbers in `docs/BENCHMARKS.md`
(baseline there: case 1 about 56 ns, case 2 about 111 ns). An independent `reviewer` reads the diff.

## Alternatives considered
* **Design 2, fan-out per store, no group:** each entry sets the top and unwind target of every attached artifact (O(n) per entry). Traps are right;
  exceptions do not cross artifacts (they become `UNCAUGHT` at the entry and skip B's `catch`, against S0007); serials only less likely to collide. No binding rule.
* **Design 3, no shared trap state:** links only through shims; a funcref of another artifact is refused. Free on the hot path, but it is option (d) that D3 rules out. Usable as step 8a.
* Trampolines only (a) and same-artifact-only (c): ruled out by D3.
Recommended: design 1, built as **8a** (record, attach, serials, lifetimes, references in signatures, host tags) then **8b** (the group state).

## Open questions (for the maintainer)
1. Design 1 (a throw in A is caught by a `try` in B; one group per artifact for life) or design 2?
2. Is forwarding the seven exception functions in the `exceptions` wrapper acceptable under D6?
3. Shared entry in every build, or a build option with a record flag? Depends on the benchmark.
4. Compatibility: the same source fingerprint (one release), or the same x plus the layout hash?
5. Host tags immortal (proposed) or owned by a store with the cell reset?
6. Should a link re-throw an uncaught exception in the importer (changes S0007)?
7. Depth-count platforms: save the joined counters at entry, or first move Windows to the stack-limit check?
8. May the Python front end publish the group in the interpreter dict at import, to avoid the binding-rule conflict?
9. New Dn: one supersedes D29, one amends D34 (host tags), one notes D2's condition "one party owns the traps of a group" is now met.
Known risks, not solved: MSVC `longjmp` across two DLLs (SEH) is untested; the group's library must stay loaded while any member runs.

## Changes
* 2026-10-30: created (draft) from the design study of a `Plan` agent.
