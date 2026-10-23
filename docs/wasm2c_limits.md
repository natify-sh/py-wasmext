# What wasm2c cannot do, and what can be done about it

Status: **notes, nothing here is built.** Each section is one WebAssembly feature that `wasm2c` of WABT 1.0.42 does not translate (the table is in [FEATURES.md](FEATURES.md)), with what blocks it, which part of that can be got round and which cannot, and what it would cost. Two related items that are not blocked but have the same kind of way round (relaxed SIMD, compact imports) are at the end. The section before the last puts those features next to the ones that `wasm2c` reads only behind a flag, and next to what a runtime like zwasm has.

What `wasm-opt` can do is read from the source of Binaryen (`version_133`, the list of passes in `src/passes/pass.cpp`, a sparse clone), **not run**: no `wasm-opt` binary was available here. A pass that is not in the list does not exist in that version.

## Typed function references

**What it is.** `call_ref`, `ref.func` with a typed result, references with a type of their own (`(ref $t)`, `(ref null $t)`), `br_on_null` and the like.

**What blocks it.** `wat2wasm --enable-function-references` makes the binary, and `wasm2c` stops at `call_ref` (unexpected opcode 0x14). The README of WABT does not tick `wasm2c` for it (strict xfail `3.0 typed function references`).

**What can be got round, and what not.**
- *In the translator (upstream).* The natural place: `wasm2c` already has `wasm_rt_funcref_t` (`func_type`, `func`, `module_instance`) and `call_indirect` checks the type hash, so a `call_ref` is the same check on a value instead of a table element. This is a change in WABT, not in `wasmext`.
- *By a rewrite of the module before `wasm2c`.* Possible only for function references with no GC: the typed references would have to be lowered to an untyped `funcref` plus a type check, or to indices into a synthetic table. Every `ref.func`, `ref.null`, `ref.is_null`, `br_on_null` and every local, global and parameter of a reference type is touched, so it is a rewrite of the types of the whole module, not of a few instructions. Large.
- *With `wasm-opt`.* No pass in Binaryen's list lowers `call_ref`. `directize` turns indirect calls into direct ones (an optimization; not tested on `call_ref`). Not a way.

**Who needs it.** Mostly the modules that also use GC (the languages that compile to WasmGC). Alone it is rare. So its value depends on the section below.

**Verdict.** Wait for WABT. A rewrite is possible but not planned. The ways in full, with what was found in the session of 2026-10-22 (`wasmext inspect` says "can be wrapped" for a module that `natify` then cannot build), are in [typed_function_references_concept.md](typed_function_references_concept.md).

## Garbage collection (WasmGC)

**What it is.** `struct`, `array`, `i31`, `ref.cast`, `ref.test`, subtyping, and the allocation of objects that the engine collects.

**What blocks it.** First the *tool*: WABT 1.0.42 does not read the instructions (`wat2wasm --enable-gc`: unexpected token `struct.get`), and `wasm2c --enable-gc` says it supports a limited set of features (strict xfail `3.0 garbage collection`). `wasmext` refuses the GC types in a module. Then the *runtime*: even with a translator there is nothing to translate to. `wasm2c` has no heap of objects, no type descriptors for `ref.cast`, no collector.

**What a real implementation would need** (so that the size is clear): (1) a translator that reads and emits the GC instructions; (2) a heap with objects that carry a runtime type, and the subtyping checks of `ref.cast`/`ref.test`; (3) a collector that finds its roots in the wasm locals (which in the C of an ahead-of-time module are C locals, in registers or on the C stack: a precise collector needs stack maps, which `wasm2c` does not write; the other way is a *conservative* one, scanning the C stack, as the Boehm collector does), in the globals and in the tables; (4) the interplay with the host objects.

**Does the collector of the context do it?** No. The lazy collector in [context_concept.md](context_concept.md) works on *members* (instances, tables) and finds their references in tables and globals. A WasmGC heap is objects *inside* a module, in their thousands, with roots in C locals. It is another level of problem; the context could at most own such a heap.

**Does `wasm-opt` get round it?** No, with a small part that helps nothing in general. Binaryen has `heap2local` ("replace GC allocations with locals"), which removes the allocations that do not escape a function: an optimization on a module that still uses GC, not a lowering. It has `string-lowering` (stringref to imports from the host) and `strip-refining-casts`, `type-merging`, `type-refining` (optimizations). **No pass lowers structs and arrays to linear memory.** (J2CL-like lowering of that kind is done by the compilers, not by `wasm-opt`.)

**Verdict.** Blocked on the tool first. Not planned; the cost is a project of its own.

## Wide arithmetic

**What it is.** `i64.add128`, `i64.sub128`, `i64.mul_wide_s`, `i64.mul_wide_u`: 128-bit operations as pairs of `i64`.

**What blocks it.** `wasm2c --enable-wide-arithmetic` says it "currently only supports a limited set of features" (checked), as its README says.

**What can be got round.**
- The operations are definable with `i64` ones that `wasm2c` knows: `add128` is two additions and a carry (the carry is a comparison), `sub128` the same with a borrow, `mul_wide` is four 32-bit by 32-bit products and their sums. The rewrite is deterministic and gives the same result on every host. It must be made **before** `wasm2c`, because `wasm2c` stops at the opcode and the generated C has nothing to patch.
- It needs a rewriter of the function bodies: the parser and the writer of the binary, the new locals, and the multi-value results of the operations (two `i64` out). That is a module-rewriting tool that `wasmext` does not have.
- *With `wasm-opt`.* Binaryen reads and writes the opcodes (`WideArithmeticFeature`, `I64Add128` in `wasm-binary.h`) but has **no pass that lowers them** (no such name in the list), and its own `wasm2js` says "wide arithmetic is not supported". Not a way.

**Verdict.** Possible, large, not planned until a module needs it (the compilers emit it rarely: big-integer and cryptographic code).

## WABT issues opened from this project

Opened by the owner of this repository against `WebAssembly/wabt` (status read from the list "Open, created by me" on 2026-10-22; **all six are open**, none answered as far as this page knows). Each has a draft or a
reproduction in the repository where one was kept. Where wasmext has a patch, it matches only the broken shape, so a fixed `wasm2c` passes through and the patch can be removed.

| WABT | What | How wasmext lives with it | When the patch can go |
| --- | --- | --- | --- |
| [#2885](https://github.com/WebAssembly/wabt/issues/2885), fix: [PR #2901](https://github.com/WebAssembly/wabt/pull/2901) | `_addcarry_u64` in the C for 64-bit memories does not link with MSVC on ARM64 and on x86/Win32 (LNK2019: the intrinsic exists only on x64; upstream confirmed both, the fix is a restriction of the branch to `_M_X64`, which is what the regex here does) | regex in `_natify.py`, also on the shared `_w2c-impl.h` of a module in several files | when a `wasm2c` release has the fix |
| [#2886](https://github.com/WebAssembly/wabt/issues/2886) | `wasm2c` aborts (SIGABRT, no message) on relaxed SIMD instructions | not translatable; the feature is "no (wasm2c)" in FEATURES.md | when `wasm2c` translates or reports an error (**PR [#2908](https://github.com/WebAssembly/wabt/pull/2908), draft, makes it an error with exit status 1**: below) |
| [#2893](https://github.com/WebAssembly/wabt/issues/2893), fix: [PR #2900](https://github.com/WebAssembly/wabt/pull/2900) | the result of a `return_call_indirect` chain is lost when the callee has no tail-callable form (wrong value) | patch to the label that returns the result (`goto var_Bfunc`) | when fixed |
| [#2895](https://github.com/WebAssembly/wabt/issues/2895) | `wasm2c` aborts (SIGABRT) on wide arithmetic (`i64.add128` …) instead of reporting an error (the title was changed on 2026-10-23: relaxed SIMD is #2886 and PR #2908; PR #2909 is the draft that fixes this one) | none; the feature is "no (wasm2c)"; a message from `natify` could replace the abort | when fixed |
| [#2896](https://github.com/WebAssembly/wabt/issues/2896), fix: [PR #2903](https://github.com/WebAssembly/wabt/pull/2903) (draft) | an imported function in an element segment gets the wrong module instance | `_repair_imported_elements` in `_natify.py` (needed by `meld fuse` output) | when fixed |
| [#2897](https://github.com/WebAssembly/wabt/issues/2897), fix: [PR #2904](https://github.com/WebAssembly/wabt/pull/2904) (open, **approved by sbc100**; the binary reader reads the type once and then the names, as the proposal says; the section-count half of #2897 was already fixed in #2870) | compact imports: the encoding `0x7E` is decoded differently from the proposal and its spec tests | wasmext reads both forms itself and writes the ordinary form before `wasm2c` | when `wasm2c` follows the proposal |

[#2884](https://github.com/WebAssembly/wabt/issues/2884) (`return_call` in a function with locals writes C that does not compile) is **closed**: fixed by [PR #2887](https://github.com/WebAssembly/wabt/pull/2887), merged 2026-10-19 (`CWriter::WriteTailCallee` recorded `stack_vars_section` before `WriteLocals`). wasmext patches it with a regex in `_natify.py` (`_TAIL_CALL_LOCALS`); the patch stays until the minimum `wasm2c` has the fix, and `tests/test_patches_needed.py` fails the day the toolchain has it.

## Related, not blocked in the same way

**Relaxed SIMD.** `wasm2c` aborts on some of the operations (WABT #2886). The specification lets an engine give the result of a relaxed operation as that of the strict one, so a rewrite before `wasm2c` can replace `relaxed_swizzle` by `swizzle`, `relaxed_trunc` by `trunc_sat`, `relaxed_laneselect` by `bitselect`, `relaxed_madd` by a multiply and an add. Binaryen's `remove-relaxed-simd` pass is *not* this: it replaces the instructions with `unreachable`, so the module traps. Needs the same kind of body rewriter as wide arithmetic.

**Compact imports.** Only a shorter encoding of the import section (the module name written once for many imports); `wasm2c` does not read it. Binaryen *reads* it (`readCompactImportsShared`, the feature `CompactImports`), so `wasm-opt --enable-compact-imports in.wasm -o out.wasm` should write the usual form, which `wasm2c` then reads. **Not tested** (no binary here), and it makes `wasm-opt` a tool of the build. A rewrite of only the import section by `wasmext` itself is the other way: the other sections are copied as they are and the section size is written again. Wanted only when a compiler starts to emit it.

## Features that `wasm2c` has by default or behind a flag, and the ones a runtime like zwasm has

The sections above are features that `wasm2c` cannot translate at all. There is another group: features that `wasm2c` of WABT 1.0.42 translates, some **by default** and some **when a flag is given**; they are not gaps of `wasm2c`, but a tool that does not pass a flag has a gap. (`wasm2c --help` of 1.0.42 has `--disable-*` for exceptions, tail call, memory64, multi-memory, extended const, relaxed SIMD and others, which are therefore on; it has `--enable-*` for threads, custom page sizes, function references, GC, wide arithmetic, compact imports and code metadata, which are off.) This section puts the two groups side by side, with what a runtime that has the other features (zwasm, from the report merged into [WASI_COMPONENTS.md](WASI_COMPONENTS.md), "zwasm") does, so that it is clear what a fallback backend would add. The status of `wasmext` is that of the tables in [FEATURES.md](FEATURES.md); the column of zwasm is taken from the `features.json` of the WebAssembly site as that report read it, and was **not checked here**.

| Feature | `wasm2c` 1.0.42 | `wasmext` today | zwasm (by the report) |
| --- | --- | --- | --- |
| Exceptions (legacy `try`/`catch`, and `try_table`, `throw_ref`, `exnref`) | on by default | **done** (the flag is passed); an uncaught one is `UncaughtException`; not done: exported or imported tags, `exnref` in a signature | on by default |
| memory64 (and 64-bit tables) | on by default | **done** inside the module, an exported memory64 is a `memoryview`; a 64-bit table is not exported yet | on by default |
| Tail calls | on by default | **done**, with two repairs of the C that `wasm2c` 1.0.42 writes (a function with locals; a chain of `return_call_indirect`) | on by default |
| Extended constants | on by default | **done** | on by default |
| Multi-memory | on by default | **done** | **only in the interpreter**: a module fused by meld would be run slowly (the report) |
| Custom page sizes | with `--enable-custom-page-sizes` | **not yet**: the flag is not passed, the `memoryview` assumes 64 KiB pages, a module with a custom page size is refused with `WasmError`; the way to tell the page size is decided, not built | on by default |
| Threads, shared memory, atomics | with `--enable-threads` (translates; its README does not tick it) | **not yet**: the flag is not passed and the runtime is not built with its threads | yes, with a note: a single-threaded host, `wait` ends by timeout |
| Relaxed SIMD | on by default, but **aborts** on some of the operations (WABT #2886) | **no**; a rewrite of the bodies before `wasm2c` is an idea (above) | yes, but SIMD only in the JIT: the interpreter traps on a vector instruction |
| Typed function references | **no** (stops at `call_ref`) | **no** | yes |
| Garbage collection | **no** (WABT does not read it) | **no**; the types are refused | yes |
| Wide arithmetic | **limited** | **no** | yes |
| WASI 0.2 components | no (it does not read a component) | the core module of a component after `unbundle`, with a host written by hand ([WASI_COMPONENTS.md](WASI_COMPONENTS.md)) | yes (its own host) |

What this says:
- The report lists exceptions, memory64, tail call, extended const and custom page sizes as "behind a flag in `wasm2c`, by default in zwasm". Checked here with `wasm2c --help` of 1.0.42, that is true only of **custom page sizes**; the other four are on by default in `wasm2c`, and `wasmext` has them without passing any flag (no `--enable-*` is given to `wasm2c` in the sources of `wasmext`). The two that are open for `wasmext` are custom page sizes and threads, and for both the flag is needed and the way is known and short (pass the flag and finish the part of the runtime that depends on it: the size of the page in the `memoryview`, `wasm_rt_init_thread` and the C11 atomics).
- The features that **only a runtime like zwasm has** are those of the sections above (typed function references, garbage collection, wide arithmetic) and relaxed SIMD. For these, a fallback backend is the one way that needs no work on the translator, and its price is in the report: about 2.8 times lower speed (CoreMark: wasm2c about 23 000, zwasm AOT or JIT about 8 000), a runtime of 2 to 2.5 MB in the artifact, and a JIT or AOT only on x86_64 and arm64 (on 32-bit targets the interpreter is left, and multi-memory is there only in the interpreter).
- So the order for a module that `wasm2c` does not take stays: wait for WABT or rewrite the module (sections above) before a second backend, and use a second backend only for what has no other way.

## What `wasm-opt` is good for here, from the list of passes

Lowerings that exist and that could be used to get *to* something `wasm2c` reads: `memory64-lowering` (and `table64-lowering`, an alias), `multi-memory-lowering`, `i64-to-i32-lowering`, `signext-lowering`, `llvm-nontrapping-fptoint-lowering`, `alignment-lowering`, `strip-eh`, `translate-to-exnref`, and `asyncify` (the pause and resume of the idea in FEATURES.md, "Fuel"). `wasm2c` reads most of the things these lower, so they are not needed now. `wasm-opt` is **not** in the wabt-package; using it means a second tool in the build.

## Relaxed SIMD: the abort becomes an error message (PR #2908, draft)

[PR #2908](https://github.com/WebAssembly/wabt/pull/2908), "wasm2c: report relaxed SIMD instructions as unsupported instead of aborting" (opened by the owner from `natify-sh:wasm2c-relaxed-simd-error`, **draft**, 2 commits, no review yet; read from the page of the pull request on 2026-10-23, not run here): relaxed SIMD is on by default but the C writer of wasm2c has no translation for it, and the switches over unary, binary, convert and ternary opcodes ended in `WABT_UNREACHABLE`, so wasm2c died with SIGABRT and no message (**fixes #2886**, refers to #2837, the default). The pull request replaces them with `WABT_FATAL`: wasm2c prints the name of the instruction (`error: wasm2c does not support the i8x16.relaxed_swizzle instruction.`) and exits with status 1 (it was 134). It adds `test/wasm2c/relaxed-simd-unsupported.txt`. **It does not translate anything** (the author notes that SIMDe covers most of it) and it leaves the wide arithmetic instructions (#2895) aborting, which is a different path, for a separate change.
What it means here: nothing is translated by wasmext either way, so the feature stays "no (wasm2c)"; what changes is the message a user gets. When it is merged and in a release, `tests/test_patches_needed.py` (which gives wasm2c a module with a relaxed instruction and says the abort is still there) will fail, as it is meant to; the change to make then is to read the new message and pass it on as an error of `natify` instead of the failure of the process. The rewrite of the bodies before wasm2c (above) is the only way to the feature itself and is not started.

## Wide arithmetic: the abort becomes an error message (PR #2909, draft)

[PR #2909](https://github.com/WebAssembly/wabt/pull/2909), "wasm2c: report wide arithmetic instructions as unsupported instead of aborting" (opened by the owner from `natify-sh:wasm2c-wide-arithmetic-error`, **draft**, 1 commit `642914e`, no review yet; read from the page of the pull request on 2026-10-23, not run here; **fixes #2895**): the reader accepts the wide arithmetic opcodes without `--enable-wide-arithmetic`, the C writer has no translation, and `wasm2c` died with SIGABRT and no message. The pull request writes the quaternary expressions (`i64.add128`, `i64.sub128`) in a `Write` function of their own, as it is done for ternary ones, and reports all four instructions (`i64.add128`, `i64.sub128`, `i64.mul_wide_s`, `i64.mul_wide_u`) with `WABT_FATAL`: the name of the instruction and exit status 1 (it was 134). Test: `test/wasm2c/wide-arithmetic-unsupported.txt` (`i64.add128`; the other three were tried by hand). **It translates nothing**, so the feature stays "no (wasm2c)". As for #2908, `tests/test_patches_needed.py` (the case "#2895") will fail the day a release has it, and the change to make is to pass the new message on as a `natify` error.

## Tests of WABT on Windows (a pull request that is not for a defect of ours)

[PR #2905](https://github.com/WebAssembly/wabt/pull/2905), "test: run the wasm2c spec tests with memory64 on Windows" (**merged into `main` of WABT by sbc100 on 2026-10-22 as `aeba296`**, 17 checks passed; not in a release yet): `test/run-spec-wasm2c.py` skipped the wasm2c tests on Windows when memory64 was enabled, a skip from the days when memory64 was opt-in (#2086); since #2837 made it the default the skip holds for almost every test, **about 260 of 262 wasm2c tests are skipped on `windows-latest`**, so the C that wasm2c writes was practically never compiled with `cl.exe`. The pull request removes the skip. It was split out of #2901 at sbc100's request (so #2901 is now the one-line guard of `_addcarry_u64` and its test of a 64-bit memory, and #2905 is the removal of the skip). What it means here: until now the Windows checks of the output of wasm2c were done by our CI (the whole suite and the examples on MSVC), not by WABT's; from this commit WABT's own CI runs those tests on Windows too.

## Found here (one reported and closed, one not reported)

- **Outcome (2026-10-22): reported, and the WABT maintainers agreed to close it as not the intended use.** They said that wasm-rt is meant to be one implementation linked into the program, that several copies are not the supported setup, and (a second maintainer) that the built-in runtime should be treated as usable, tested and maintained, not as an example, while users may build a runtime that suits their setup. wasmext's way (stock runtime files untouched, the handling of several modules on our side) is consistent with that; no change is asked of WABT. The report, with its wording that was wrong about wasm2c ("every module translated by wasm2c is built with its own copy" is how wasmext builds, not how wasm2c is meant to be used), and the first reply are kept as the record. The first one was prepared with AI assistance and was labelled as such in the reply. Original text:
- **The handler of SIGSEGV/SIGBUS of every copy of the runtime replaces the one before it** (two modules in one process: a fault in the one set up first aborts the process), and **the alternate stack cannot be had without installing the handler** (`WASM_RT_STACK_EXHAUSTION_HANDLER` needs `WASM_RT_INSTALL_SIGNAL_HANDLER`). Draft of the issue, with a reproduction that was run on WABT 1.0.42: [wabt_issue_drafts/signal_handler.md](wabt_issue_drafts/signal_handler.md), files in [experiments/wabt_signal_repro/](experiments/wabt_signal_repro/). wasmext lives with it by a chain of handlers (`WASMEXT_CHAIN`, [patch_policy.md](patch_policy.md)).
- **A stack overflow in a thread other than the main one is reported as an out-of-bounds access** (not reported; it concerns the ordinary single-runtime case too) by the stock handler (`os_signal_handler` takes `si_code == SEGV_ACCERR` for memory; the guard page of a thread stack is `ACCERR`, the growing main stack is `MAPERR`): a wrong trap code, no crash. Measured in [experiments/stack_limit/](experiments/stack_limit/README.md). wasmext avoids it with the check of the stack pointer.

## Other open pull requests looked at (2026-10-22, the first page of 63)

Nothing that overlaps the two pull requests above: the ones about tail calls (#2898, #2877, #2872) are in the interpreter (`interp.cc`), the ones about names, segments and text (#2876, #2869, #2838, #2833, #2883) in the text writer. **#2782** (`wasm2c: uvwasi adapter layer for wasm2c output`) is a host for WASI **preview 1 only** (uvwasi is that, by its README) and has libuv in it; wasmext has a host of its own for preview 1 and none for 0.2, so it is not taken. The files of these pull requests were not read (the page shows titles), only guessed from them.
