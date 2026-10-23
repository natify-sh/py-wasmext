# The target of a module: what `wasi=`, the imports and the stub follow from (a concept)

Status: **agreed in principle on 2026-10-23, not built.** Nothing here is in the code. It is written down so that it is not only in a conversation. Open points are at the end.

## The problem

A module imports functions, and a part of them wasmext can answer by itself: the calls of WASI 0.1 are in C in every module that imports them, and `wasi=` holds their configuration (arguments, environment, files, streams, clocks). The WASI 0.2 imports are today ordinary imports: the stub has a `TypedDict` for each module (`_Imports0`, `_Imports1`, …, numbered by the order of the import section) and the caller writes the functions, or takes them from a host such as the Python one of fusedwasi.

Three things are wrong with it.

1. **WASI 0.1, WASI 0.2 and the imports of the user are one thing** (a function that the module calls and the host answers), but they are handled by three different ways: built into the module and configured by data (0.1), written by hand (0.2), written by hand (the rest).
2. **The binding is chosen by what the module looks like.** `_gen.py` binds the built-in WASI to every module that imports from `wasi_snapshot_preview1` or `wasi_unstable` (and checks the signature: an unknown name or another type is a `GenError`, so there is no way back to "these are my own imports"). But **names and types prove nothing**: a module can import and export exactly what a program of WASI 0.1 does and do something else inside, since wasm does not stop it from using `fd_*` for any logic, or from having no WASI in it at all. What looks like WASI from outside is the same. No check of the module can tell, and nothing in the file says it (LLVM does not write the triple into it; `producers` names the tools, not the target).
3. **WASI 0.2 needs more than imports.** A host of 0.2 calls back into the module (`cabi_realloc`, an export, for every string or list it returns), so the requirement is both an import and an export; and its arguments, environment and streams do not come as a configuration of the host but through imports (`wasi:cli/environment` and the like).

## The decision: the target is said, not guessed

**The build says which ABI the module has**, with the names that the toolchains use for it:

| target | what wasmext binds by itself | `wasi=` |
| --- | --- | --- |
| `wasm32-unknown-unknown` (alias `wasm32`) | nothing: every import is the caller's | none |
| `wasm32-wasip1` | the calls of `wasi_snapshot_preview1` and `wasi_unstable` (the snapshot is the name of the import module) | the configuration of WASI 0.1 |
| `wasm32-wasip2` | the functions of `wasi:*@0.2.x` that fusedwasi has | the configuration of WASI 0.2 |

- **The default is `wasm32`.** Nothing is bound unless it was asked for. The project is an alpha, so a module that has relied on the guess takes one line (`target = "wasm32-wasip1"`). When the target is `wasm32` and the module imports the names of `wasi_snapshot_preview1`, the build prints a **note** ("if this is a WASI program, say `--target wasm32-wasip1`") and does nothing else.
- **The check of the signatures stays, as a check of what was said**, not as a detection: with `wasm32-wasip1` a name of `wasi_snapshot_preview1` that the specification does not have, or another type, is an error of the build (it is the mistake of the person, not a module of its own kind). With `wasm32` nothing is checked: the host is the caller's.
- **The target is recorded in the artifact** (a constant of the module, `__target__` or the like) so that the run time and the stub do not guess either.
- **It is given** to `wasmext natify`, in `[tool.wasmext]`, and as an argument of the extension of the build; one place per project is enough.
- A target is **the name space of the imports of the module, not the kind of the file.** `wasm32-wasip2` in Rust makes a *component*; wasmext takes the core module that `unbundle` or `meld` gives from it, whose imports are `wasi:*`. The note on WASI 0.3 stays: `wasm32-wasip3` is "not supported" (`meld` keeps the async part only in part, see WASI_COMPONENTS.md).
- Not decided: `wasm32-wasip1-threads` (a module with `thread-spawn`).

## One chain for every import

Whatever the target, an import is answered in this order:

1. **What the caller gave** in `imports=` wins, for any function. (So a single call of WASI can be replaced, as today.)
2. **What the target binds** (the table above), by the key *(module without its version, name)*, e.g. `("wasi:io/streams", "[method]output-stream.write")` or `("wasi_snapshot_preview1", "fd_write")`. The patch versions of WASI 0.2 are compatible, so the version is not in the key.
3. **The rest stays required**, as `_Imports*` is today.

## Two tiers: the imports are exact, `wasi=` is for the simple hooks

Agreed on 2026-10-23 after a look at the stubs of `examples/wasi2_unbundled` and at what each way costs the caller.

1. **The imports (`imports=`) keep their full signatures**, the ones the module really calls: for `wasi_snapshot_preview1` the four integers of `fd_write(fd, iovs, iovs_len, nwritten_ptr)` and the errno it returns, for WASI 0.2 what the stubs show today (`get-arguments` takes the pointer of its result). A caller who replaces an import does it *explicitly and knowing the signature*, and what he does with it is his: he may take the original function, wrap it and put it back, which needs the signature of the original, so a lifted type under the same name is not possible (`fd_write(fd, data)` and the raw `fd_write` cannot be one key).
   - For a target that has a built-in host the WASI modules of the imports are **optional** (`NotRequired`, and each function in them too); only the modules that the target does not bind are required.
   - The names of the parameters come from the specification (witx for 0.1, WIT for 0.2), so the stub reads as the standard does.
   - The original is **taken on demand** (a lazy `Instance.original(module, name)` or the like), so who does not wrap pays nothing; and it is a thin call of the C function, not an object made for every import. The cost of a wrapper (the border C to Python to C twice) is **not measured**; it has to be before the shape of this call is fixed.
   - Optional **adapters in fusedwasi**, generated from the same table, convert between the exact level and the lifted one: `lift(raw)` gives the function with the values (`(fd, data) -> int`), `lower(fn)` makes the exact one from it. They are for the caller who wants to wrap a call and not to read the memory of the module by hand (in 0.2 the lowering of a list of strings is the `cabi_realloc` of the module).
2. **`wasi=` stays, for the simple hooks of the built-in host.** It is what a caller reaches for when he wants `print` for the standard output, the arguments or the environment, not a function of the border. Its keys are values and hooks on the level of the value: `args`, `env`, `preopens`, `readonly`, `stdin`, `stdout`, `stderr`, `clock`, `random` (the same for 0.1 and 0.2); 0.2 may add what only its world has (which sockets are allowed, `http`). A type checker refuses a key the target does not know. Each key feeds imports: `args` feeds `args_get` and `args_sizes_get` in 0.1 and `wasi:cli/environment.get-arguments` in 0.2. `clock` and `random` are hooks of the value (the id of the clock to nanoseconds, the number of bytes to bytes), so they need no access to the memory.
   - It exists for the targets that have a built-in host (`wasm32-wasip1`, `wasm32-wasip2`) and not for `wasm32`.
   - **If both are given for one function, the import wins** over the hook (the exact replacement is the more explicit one).
   - Whether 0.2 takes `wasi=` too (its arguments are only an import that the host answers, and the replacement of that import is possible) is open; the shape is the same for the caller, so it is likely.

## Where the types of WASI live

The types of the functions of WASI 0.1 and 0.2 (the standard interfaces) are kept **in fusedwasi**, with the implementation they describe, so that they change together; the stub of a module imports them by name instead of copying them. wasmhost uses the same types for its replacements. wasmext keeps only what is the module's own: the modules that are not WASI.

Together with it, **the names of the types are stable.** For the modules of WASI the name follows from the name of the module (`_Imports_wasi_io_streams_0_2_12` or, better, the name the type has in fusedwasi), not from the position in the import section (`_Imports7`), which moves when a module is added or the compiler reorders the section. For the other modules wasmext makes the name from the module name in the same way, in the order of appearance when two names meet.

## WASI 0.2: what the target `wasm32-wasip2` also asks

- **`cabi_realloc` of every component** is an export that the build checks for and binds to the `realloc` hook of the state of fusedwasi (`fusedwasi_p2_*` takes the memory of a component and its realloc). A component without it is an error of the build, not a trap on the first string.
- The arguments, the environment and the streams can be given as **hooks in `wasi=`** that fill the state of fusedwasi (the module reads them through the imports, `wasi:cli/environment.get-arguments`, as it must), or by replacing those imports with their exact signatures (with the adapters of fusedwasi for the lowering).
- The host of 0.2 is **not in the ABI of wasmext yet** (a standing decision); the first step is the stub and the Python path (the host of fusedwasi through `imports`), the C path comes later.

## What is not decided

- Whether `target = "auto"` (a guess with a note, asked for by name) is wanted at all. Its answer is "no" unless somebody asks.
- The exact spelling of the constant in the module and of the key in `[tool.wasmext]`.
- Mixed modules (one module that imports both `wasi_snapshot_preview1` and `wasi:*`): an error of the build for now.
- The order of the work: the target and the stub first (no change of the ABI of the C), the binding of 0.2 after.
- The cost of wrapping an original import, and the shape of `original()`: after a measurement of the crossing C to Python to C.
- Whether `wasi=` is also for WASI 0.2, and its keys there.
- What the targets mean for wasmhost (it has no build): it would take the target as an argument of the host (`Preview1`, a later `Preview2`) or from the imports of the module it is given, and nothing in a file says which.
