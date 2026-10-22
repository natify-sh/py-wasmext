# Typed function references: options (a concept)

Status: **a concept, nothing is built, nothing is decided.** It puts the ways to support the function-references proposal (part of WebAssembly 3.0) in one place, with what is
known about each and how. The short version, kept with the other features that `wasm2c` cannot translate, is in [wasm2c_limits.md](wasm2c_limits.md), "Typed function references"; the row of the
table is in [FEATURES.md](FEATURES.md). This page is for the day somebody needs the feature, so that the work is not started from nothing.

How a fact is known: **[run]** run in a session of this repository (WABT 1.0.42 from `wabt-package`, 2026-10-22), **[read]** read in source code or documentation, **[estimate]**
a judgement, not tried.

## What it is

The proposal adds references with a type of their own: `(ref $t)` (not null) and `(ref null $t)`, the instructions `call_ref $t`, `return_call_ref $t`, `ref.as_non_null`,
`br_on_null` and `br_on_non_null`, and a `ref.func` whose result is typed. A call through a reference needs no table and no index: the reference is on the stack.

## What is the state

- `wat2wasm --enable-function-references` makes the binary. `wasm2c` stops at the first `call_ref`: `error: unexpected opcode: 0x14` **[run]**.
- `c-writer.cc` of WABT, both the tag `1.0.42` and `main` (read on 2026-10-22), has no code for `call_ref`, `return_call_ref`, `ref.as_non_null`, `br_on_null` or
  `br_on_non_null`, and the table in the README of WABT has no tick in the column of `wasm2c` for function references **[read]**. So a newer WABT does not help today.
- **wasmext says two different things about the same module.** For a module that uses `call_ref` in a body (and has no typed reference in a signature) `wasmext inspect` answers
  `result: can be wrapped`, because the reader of wasmext does not read the code, and `natify` then fails with the raw text of `wasm2c` (`wasm2c failed on cr.wasm: … unexpected
  opcode: 0x14`) **[run]**. A typed reference in a *signature*, a global or a table is refused by wasmext at once (its reader does not know the value types `0x63` and `0x64`).
- The proposal is in WebAssembly 3.0, together with GC; most modules that use it are made for WasmGC (Dart, Kotlin/Wasm, Java and the like) and need GC as well, which WABT does not
  read at all (see "Garbage collection" in [wasm2c_limits.md](wasm2c_limits.md)). Which compilers emit it alone was not checked; C, C++ and Rust through LLVM are not known to **[estimate]**.

So the value of the feature alone is small, and its cost depends on where it is done.

## The ways

### A. Do nothing (as now)

The feature stays "no (wasm2c)". Cost: none. The defect above (`inspect` and `natify` disagree) stays.

### B. Say it clearly (cheap, whatever else is chosen)

- `natify`: when `wasm2c` fails with `unexpected opcode: 0x14`, `0x15`, `0xd4`, `0xd5` or `0xd6` (`call_ref`, `return_call_ref`, `ref.as_non_null`, `br_on_null`,
  `br_on_non_null`), say which proposal the module uses and that WABT does not translate it. The text of the error of `wasm2c` is the only source: wasmext does not read the code.
- `inspect` cannot say it without a walker over the bodies of functions (the opcode byte alone is not enough: the same value can be an immediate), so it can only be told in the
  documentation, or when the walker of C below exists.
- Cost: small. Risk: the text of `wasm2c` can change between versions; the mapping then falls back to the raw message.

### C. Make `wasm2c` do it (WABT)

The natural place. `wasm2c` already has `wasm_rt_funcref_t` (`func_type`, `func`, `module_instance`). A `call_ref $t` is a call of `func` after a check for null; the type is known
when the module is validated, so the check of the hash that `call_indirect` makes is not needed, and the call can be cheaper than `call_indirect` **[estimate]**.

What the change in `c-writer.cc` would have to cover **[estimate]**:
- the typed reference types as `funcref` in locals, parameters, results, globals, tables and block types;
- the five instructions above, and `ref.func` with its typed result;
- locals of a non-null type (the proposal lets them be unset until set: the validator tracks it; the C can start them as null);
- `ref.null` of a typed heap type, `ref.is_null`, and the casts that belong to GC (`ref.cast`, `ref.test`) left out.

Two ways to carry it:
1. *Upstream:* a pull request to WABT. Slow and not in our hands.
2. *A patch in `wabt-package`.* `wabt-package` is the package of this organisation, so a patch to the source of WABT can be applied when the wheels are built, and a version of the
   package that has it becomes the minimum for the feature. Then wasmext only has to pass the flag (`--enable-function-references`; the effect on the C of a module that does not use
   it must be checked, as it was for the other flags: the C of an ordinary module came out the same with `--enable-custom-page-sizes` and with `--enable-compact-imports`).

Cost: a change to C++ in a project that is not ours; tests are needed on both sides (the spec tests of the proposal run through `wasm2c`). Risk: the patch has to be carried
across versions of WABT.

### D. Rewrite the module before `wasm2c` (in wasmext)

The same kind of step as the one that writes compact imports in the ordinary form before `wasm2c` (see "Compact imports" in [FEATURES.md](FEATURES.md)), but for code, which is much more.
The idea, not tried **[estimate]**:
- erase every typed reference type to `funcref` (a not-null reference becomes nullable; the checks that the validator made are not needed any more, since the module is valid);
- `call_ref $t` → keep the reference in a new local, put it into a scratch table of `funcref`, and `call_indirect` through that table with the type `$t`. For a stack
  `[args…, ref]` that is `local.set $tmp; i32.const 0; local.get $tmp; table.set $scratch; i32.const 0; call_indirect $scratch $t`. A null reference traps, as the proposal says
  (the text of the trap differs: `call_indirect` to a null element);
- `return_call_ref` the same with `return_call_indirect`; `ref.as_non_null` and `br_on_null` / `br_on_non_null` with a local and a test of `ref.is_null`.

What it needs: a reader and a writer of **all** the instructions with their immediates (today wasmext skips the bodies of functions), so that the types of locals and blocks and the
indices of the tables can be changed. This walker would be useful for other things too: the idea for relaxed SIMD in [wasm2c_limits.md](wasm2c_limits.md), and the diagnostics of B. Risk: a
silent mistake in the meaning of a program; it would need the spec tests of the proposal. Subtyping of function types (only with the GC proposal) is not covered: the types are
compared by the hash, so a reference to a subtype would trap. Cost: large.

### E. Another back end (zwasm, wasmtime)

A runtime that has the feature. Rejected in [WASI_COMPONENTS.md](WASI_COMPONENTS.md): it is slower and is a runtime inside every artifact, which is what wasmext leaves out. Not for this
feature alone.

## What I would choose (a recommendation, not a decision)

B now: it makes wasmext say the same thing in `natify` and in the documentation, and costs little. C-2 or D only if somebody has a module that needs this and not GC, and then C-2
first, because it is the smallest change that fits the AOT rule. A and E for the rest. If GC ever becomes a goal, the whole question is decided by that, not by this page.

## To find out before choosing

1. Is there an issue or a pull request in WABT for `wasm2c` and function references, and what was said (not looked for: the session is limited to this repository)?
2. Which real modules use typed function references and not GC, and from what compiler (a consumer is what decides)?
3. What the spec tests of the proposal (`function-references`) say of the cases above, in particular non-null locals and `br_on_null` with values on the stack.
4. For C-2: the C of an ordinary module with `--enable-function-references` against the C without it.
