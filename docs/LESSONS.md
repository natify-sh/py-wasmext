---
title: Lessons
kind: log
status: current
updated: 2026-10-30
---

Traps found on the way, with the rule. Newest last.

### Windows macros in identifiers
* What happened: a variable named `far` in `tests/c/test_tables.c`. `far` is a macro of `windows.h`.
* Symptom: the file compiled on Linux and macOS and failed only in the MSVC jobs.
* Cause: `windows.h` defines `far` (and other legacy names) as macros, so the identifier is rewritten.
* Rule: identifiers of tests and headers avoid the macro names of `windows.h`. The Windows jobs of Pre-commit and Python versions are the ones that find this.
* Where found: step 5a, commit aa214cd; fixed in b9b5e29 (`tests/c/test_tables.c`).

### clang of macOS and a const pointer to an uninitialised variable
* What happened: `tests/c/test_registry.c` passed a variable that was not initialised as a const pointer (the keys of the registry test).
* Symptom: `-Wuninitialized-const-pointer` failed the macOS clang job only.
* Cause: newer clang warns when an uninitialised object is passed through a pointer to const; gcc did not.
* Rule: initialise every variable a test hands to the code under test, even when the callee only reads it.
* Where found: step 4, commit ae2e463; fixed in 0b61efe.

### A static const ops structure in a header is not one object
* What happened: members of the registry were told apart by comparing the address of their `wasmext_owner_ops`, which is `static const` in a header.
* Symptom: the comparison fails across files.
* Cause: a `static const` object in a header is a separate object in every translation unit, so its address differs between files.
* Rule: never compare the address of a header-defined static object. Identity is a value: the ops carry a `kind` field and the registry compares that.
* Where found: step 6, `src/wasmext/c/wasmext_registry.h` (`wasmext_owner_ops.kind`, `WASMEXT_KIND_*`); the structures are in `wasmext_instance.h`.

### "Is a member of the store" is not "is a member of this kind"
* What happened: a check accepted a pointer if the store knew it as any member (instance, table, host function, reference).
* Symptom: none in the tests; a pointer of one kind was accepted where another kind was required (type confusion).
* Cause: the registry lookup answered only "known or not".
* Rule: a reference is checked by kind (`wasmext_store_find_kind`). An independent reviewer reads every change to ownership and ABI.
* Where found: self-review of the orchestrator after step 6a was pushed; fixed in 96fadf5.

### The exception buffer of wasm2c is not aligned for the payload
* What happened: the payload of a caught exception was read and written through a pointer to the payload struct.
* Symptom: UBSan reports a misaligned access.
* Cause: the runtime of wasm2c keeps the active exception in a byte buffer that is not aligned for the struct.
* Rule: read and write the payload with `memcpy`, as wasm2c does.
* Where found: step 7, `src/wasmext/_binding.py` (`_tag_payload`), commit 11fca32.

### Tests of the raw wasm2c output hid the product
* What happened: the tests built the raw C of wasm2c and the raw runtime, not what the product builds.
* Symptom: the tests passed while the product differs: the repairs of `src/wasmext/_natify.py` and the wrapper that turns the `abort()` of a failed memory allocation into the trap 0x7001 were never tested. With the raw runtime `tests/c/test_nomemory.c` aborts (SIGABRT); with the wrapper it gets NO_MEMORY.
* Cause: the fixture built a different artifact from the shipped one.
* Rule: the tests build what the product builds (fixture `build` in `tests/test_instance_core.py`). Raw wasm2c output is not a test subject.
* Where found: pointed out by the maintainer; fixed in ec18e4f (step 7d).

### An imported tag, and any import symbol, is a global of the program
* What happened: two modules of one test program imported the same `module.name`, and a tag import was expected to live in a slot of the instance.
* Symptom: duplicate symbols at link time; one tag per import name for the whole program.
* Cause: wasm2c reads an imported tag from a global symbol, not from a slot. Every symbol `w2c_<module>_<name>` of an import (function, global, table accessor, tag) is a global of the program.
* Rule: tests use distinct import module names. A tag link is made once for the program; a link to another tag is refused, never mixed.
* Where found: step 7, `docs/specs/S0007-tags-exceptions.md`, commit 11fca32.

### A tag import needs a writable variable
* What happened: modules that import tags, tables or globals need the `wasm_rt_*` types from the runtime headers, and the tag is declared `extern const`.
* Symptom: the core cannot write the tag of the exporter into the global the module reads.
* Cause: `wasm_rt_tag_t` is `const void *` and wasm2c declares an imported tag `extern const`.
* Rule: the generated binding renames that declaration with a `#define` and defines a writable variable.
* Where found: step 7, `src/wasmext/_binding.py` (`wasmext_declared_`), commit 11fca32.

### A mutation check can pass for the wrong reason
* What happened: mutants that did not compile, no-op mutations (a pin on a 32-bit memory with guard pages does nothing) or crashes unrelated to the mutated line were counted as caught.
* Symptom: a test looked trusted and was not.
* Cause: only "the test failed" was checked, not why.
* Rule: read the failure message every time; use a mutation that changes the behaviour.
* Where found: CLAUDE.md, principles ("for the right reason"); `docs/specs/S0003-instances.md` (3c: a 32-bit memory with guard pages is not touched).

### CI cancels the runs of the previous commit
* What happened: the Pre-commit run of aa214cd was cancelled by the push of the next commit.
* Symptom: a missing result for a commit, not a failure.
* Cause: the workflows set `concurrency` with `cancel-in-progress: true`.
* Rule: a step is closed when CI is green on its head, not on an earlier commit.
* Where found: `.github/workflows/pre-commit.yml`, `sanitizers.yml`, `publish.yml`; CLAUDE.md, "Before every push".

### Example wheels can time out before any test
* What happened: the job failed at "Download the wasmext wheel" with `Failed to ListArtifacts ... ETIMEDOUT`.
* Symptom: Example wheels red on a commit that changed nothing there (seen on run 41049169742, head 11fefba).
* Cause: a network failure of the runner, before any test ran.
* Rule: read the failing step. For this one, one `rerun_failed_jobs` is the answer.
* Where found: step 5c, head 11fefba; CLAUDE.md names it ("one network timeout (`ETIMEDOUT`) in Example wheels is re-run once").

### wasm2c orders the import structures by module name
* What happened: the generated binding listed the structures of the import modules in the order of the first import.
* Symptom: the binding broke on a module whose imports were not already in name order (found by the WASI 0.2 test).
* Cause: wasm2c passes the structures of the import modules in the order of their names (UTF-8 bytes).
* Rule: sort the modules by `m.encode("utf-8")`; keep a test module whose imports are out of order.
* Where found: step 3b2b, `src/wasmext/_binding.py` (`sorted(by_module, key=...)`), commit 06293c4.

### Thread set-up: one flag per artifact, not per file
* What happened: the "this thread is set up" flag was defined in a header, so each file had its own; `wasm_rt_is_initialized` was tried as the check.
* Symptom: the runtime aborted on the second `wasm_rt_init`. Under the sanitizers `wasm_rt_is_initialized` was wrong.
* Cause: a flag per translation unit set the thread up twice (binding and test). Sanitizers install their own alternate stack in every thread, so the runtime takes the thread for set up.
* Rule: one flag per artifact, defined by the one file that defines `WASMEXT_DEFINE_THREAD_STATE`. Do not use `wasm_rt_is_initialized`.
* Where found: step 3d, `src/wasmext/c/wasmext_instance.h` (`wasmext_thread_ready_`), `docs/specs/S0003-instances.md`.

### WIN32_LEAN_AND_MEAN does not belong in a public header
* What happened: `WIN32_LEAN_AND_MEAN` was defined in `wasmext_glue.h` to stop the winsock redefinition under MSVC.
* Symptom: `tests/test_abi_declaration.py` failed, because the define is a public constant of the ABI surface.
* Cause: a define in a public header is part of the declared surface.
* Rule: define it at the top of the generated binding, before `wasm-rt.h`. Run the ABI tests before a push that touches `src/wasmext/c/`.
* Where found: step 3, commits 541293b and a2defc1 (`src/wasmext/_binding.py`).

### Status of the last call raced between threads
* What happened: the answer of the last call was a plain integer in the instance.
* Symptom: ThreadSanitizer reported a data race.
* Cause: calls from several threads write `status` at once.
* Rule: shared state of an instance is atomic (`wasmext_counter status`); a caller uses the result of its own call, not `status`.
* Where found: step 3a, `src/wasmext/c/wasmext_instance.h`, `docs/specs/S0003-instances.md`.

### Closing an exporter's store while an importer lives
* What happened: instances of two stores were linked, and the store of the exporter was closed first.
* Symptom: use after free under ASan: the importer's functions read what the closed store freed.
* Cause: the store frees its members at close; a link across stores outlives them.
* Rule: instances are linked only inside one store; `bind_export` refuses a record of another store, with the reason in the text.
* Where found: step 4, `docs/specs/S0004-owners-registry.md`, commit ae2e463 (`tests/c/test_links.c`).

### Deleted marks fill a hash table
* What happened: the registry table (open addressing) marks removed entries as `WASMEXT_TABLE_DELETED`.
* Symptom: after many removals, searches no longer found keys.
* Cause: with no empty slot left, a search has nowhere to stop; the marks only accumulate.
* Rule: count the deleted marks and rehash when they are many (`deleted * 4 > capacity`).
* Where found: step 4, `src/wasmext/c/wasmext_registry.h`; the mutation of the removed marks is caught in `tests/c/test_registry.c`.

### An exception does not cross a link
* What happened: a wasm exception thrown by a function called through a link (a typed shim) was expected in the caller.
* Symptom: the caller gets a trap, not an exception.
* Cause: the shim enters the exporter with its own entry, so an uncaught exception ends there as a trap.
* Rule: an exception unwinds into the caller only where the code runs on the caller's native stack, for example a function reached through a shared table. Test exceptions through tables, not through links.
* Where found: step 7, `docs/specs/S0007-tags-exceptions.md`, commit 11fca32.

### Two copies of the runtime in one store: a trap goes to the handler of the copy entered last
* What happened: two shared libraries, each with its own copy of the wasm2c runtime, shared one store (S0008, 8a-1), and code of one copy hit a guard page.
* Symptom: SIGABRT, `w2c_liba_load` -> `os_signal_handler` of the other library -> `wasm_rt_trap` -> `abort` (no entry on its stack); a thread that called into both copies also leaked one alternate stack.
* Cause: every copy has its own `g_wasm_rt_jmp_buf`, unwind target, handler of signals and `sigaltstack`; a signal runs the handler installed last, and `wasm_rt_free_thread` frees only the stack that is in place.
* Rule: a test that builds two copies must build them with the product's flags (`signal_build_flags`) and must not trap across them until the store has one trap state (8b); the copies of a store are made ready on a thread, and let go of, together.
* Where found: independent review of step 8a-1, `docs/specs/S0008-shared-store.md` ("Known limit of 8a-1"), `tests/test_artifacts.py`.

