# The host of a module: what `wasi=`, the imports and the stub follow from (a concept)

Status: **agreed in principle on 2026-10-23, not built.** Nothing here is in the code. It is written down so that it is not only in a conversation. Open points are at the end.

## The problem

A module imports functions, and a part of them wasmext can answer by itself: the calls of WASI 0.1 are in C in every module that imports them, and `wasi=` holds their configuration (arguments, environment, files, streams, clocks). The WASI 0.2 imports are today ordinary imports: the stub has a `TypedDict` for each module (`_Imports0`, `_Imports1`, …, numbered by the order of the import section) and the caller writes the functions, or takes them from a host such as the Python one of fusedwasi.

Three things are wrong with it.

1. **WASI 0.1, WASI 0.2 and the imports of the user are one thing** (a function that the module calls and the host answers), but they are handled by three different ways: built into the module and configured by data (0.1), written by hand (0.2), written by hand (the rest).
2. **The binding is chosen by what the module looks like.** `_gen.py` binds the built-in WASI to every module that imports from `wasi_snapshot_preview1` or `wasi_unstable` (and checks the signature: an unknown name or another type is a `GenError`, so there is no way back to "these are my own imports"). But **names and types prove nothing**: a module can import and export exactly what a program of WASI 0.1 does and do something else inside, since wasm does not stop it from using `fd_*` for any logic, or from having no WASI in it at all. What looks like WASI from outside is the same. No check of the module can tell, and nothing in the file says it (LLVM does not write the triple into it; `producers` names the tools, not the host).
3. **WASI 0.2 needs more than imports.** A host of 0.2 calls back into the module (`cabi_realloc`, an export, for every string or list it returns), so the requirement is both an import and an export; and its arguments, environment and streams do not come as a configuration of the host but through imports (`wasi:cli/environment` and the like).

## The decision: the host is said, not guessed

**The build says which host the module's imports are for** (who stands on the other side of them), with the names that the toolchains use for the ABI:

| `host` | what wasmext binds by itself | `wasi=` |
| --- | --- | --- |
| `wasm32-unknown-unknown` (alias `wasm32`) | nothing: every import is the caller's | none |
| `wasm32-wasip1` | the calls of `wasi_snapshot_preview1` and `wasi_unstable` (the snapshot is the name of the import module) | the configuration of WASI 0.1 |
| `wasm32-wasip2` | the functions of `wasi:*@0.2.x` that fusedwasi has | the configuration of WASI 0.2 |

- **The default is `wasm32`.** Nothing is bound unless it was asked for, and there is **no `auto`**: a guess is not wanted in any form (decided). The project is an alpha, so a module that has relied on the guess takes one line (`host = "wasm32-wasip1"`). When the host is `wasm32` and the module imports the names of `wasi_snapshot_preview1`, the build prints a **note** ("if this is a WASI program, say `--host wasm32-wasip1`") and does nothing else.
- **The check of the signatures stays, as a check of what was said**, not as a detection: with `wasm32-wasip1` a name of `wasi_snapshot_preview1` that the specification does not have, or another type, is an error of the build (it is the mistake of the person, not a module of its own kind). With `wasm32` nothing is checked: the host is the caller's.
- **The host is recorded in the artifact** (a constant of the module, `__host__` or the like) so that the run time and the stub do not guess either.
- **It is given** to `wasmext natify`, in `[tool.wasmext]`, and as an argument of the extension of the build; one place per project is enough.
- A host is **the name space of the imports of the module, not the kind of the file.** `wasm32-wasip2` in Rust makes a *component*; wasmext takes the core module that `unbundle` or `meld` gives from it, whose imports are `wasi:*`. The note on WASI 0.3 stays: `wasm32-wasip3` is "not supported" (`meld` keeps the async part only in part, see WASI_COMPONENTS.md).
- Not decided: `wasm32-wasip1-threads` (a module with `thread-spawn`).

## One chain for every import

Whatever the host, an import is answered in this order:

1. **What the caller gave** in `imports=` wins, for any function. (So a single call of WASI can be replaced, as today.)
2. **What the host binds** (the table above), by the key *(module without its version, name)*, e.g. `("wasi:io/streams", "[method]output-stream.write")` or `("wasi_snapshot_preview1", "fd_write")`. The patch versions of WASI 0.2 are compatible, so the version is not in the key.
3. **The rest stays required**, as `_Imports*` is today.

## Two tiers: the imports are exact, `wasi=` is for the simple hooks

Agreed on 2026-10-23 after a look at the stubs of `examples/wasi2_unbundled` and at what each way costs the caller.

1. **The imports (`imports=`) keep their full signatures**, the ones the module really calls: for `wasi_snapshot_preview1` the four integers of `fd_write(fd, iovs, iovs_len, nwritten_ptr)` and the errno it returns, for WASI 0.2 what the stubs show today (`get-arguments` takes the pointer of its result). A caller who replaces an import does it *explicitly and knowing the signature*, and what he does with it is his: he may take the original function, wrap it and put it back, which needs the signature of the original, so a lifted type under the same name is not possible (`fd_write(fd, data)` and the raw `fd_write` cannot be one key).
   - **Required or not is decided function by function, from what the module really imports.** The stub lists only the imports the module has (as it does today), not every function of the standard module. What the module asks for and the host knows how to give, the host gives, and it is `NotRequired` (a replacement). What the module asks for and the host cannot give is **required** of the caller, as for `wasm32`. So a module that needs only part of an interface gets a `TypedDict` with only that part. If something the module imports could in theory go unused, `required` would be a strange thing to say about it: the rule is about what the module *asks for*, and it is up to the module's author not to import what is not needed.
   - The names of the parameters come from the specification (witx for 0.1, WIT for 0.2), so the stub reads as the standard does.
   - **The original is a reference to the import, taken from the instance by `__getitem__`** (the exact spelling is open). Tables have nothing to do with it. Today `Function` exists only as `Table.get(i)` and `instance[name]` gives exports (tables, functions), never an import, so this is a **new** way to reach an import, not something that works now. What is open: the key (module and name), how the reference is made (a thin object over the C function of the built-in host, made on demand so that who does not wrap pays nothing), and its cost (the border C to Python to C twice, **not measured**).
   - Optional **adapters in fusedwasi**, generated from the same table, convert between the exact level and the lifted one: `lift(raw)` gives the function with the values (`(fd, data) -> int`), `lower(fn)` makes the exact one from it. They are for the caller who wants to wrap a call and not to read the memory of the module by hand (in 0.2 the lowering of a list of strings is the `cabi_realloc` of the module).
2. **`wasi=` stays, for the simple hooks of the built-in host.** It is what a caller reaches for when he wants `print` for the standard output, the arguments or the environment, not a function of the border. Its keys are values and hooks on the level of the value: `args`, `env`, `preopens`, `readonly`, `stdin`, `stdout`, `stderr`, `clock`, `random` (the same for 0.1 and 0.2); 0.2 may add what only its world has (which sockets are allowed, `http`). A type checker refuses a key the host does not know. Each key feeds imports: `args` feeds `args_get` and `args_sizes_get` in 0.1 and `wasi:cli/environment.get-arguments` in 0.2. `clock` and `random` are hooks of the value (the id of the clock to nanoseconds, the number of bytes to bytes), so they need no access to the memory.
   - It exists for the values of `host` that have a built-in implementation (`wasm32-wasip1`, `wasm32-wasip2`) and not for `wasm32`.
   - **If both are given for one function, the import wins** over the hook (the exact replacement is the more explicit one).
   - Whether 0.2 takes `wasi=` too (its arguments are only an import that the host answers, and the replacement of that import is possible) is open; the shape is the same for the caller, so it is likely.

## The typed imports in the stubs (the extension, the wrapper for ctypes)

Today a module of WASI 0.1 has `imports: None = None` in its stub, in the extension and (as `imports: Any`) in the wrapper for ctypes: the module `wasi_snapshot_preview1` is neither typed nor named, although a call of it can be replaced. The stub of a module of WASI 0.2 types every function as `Callable[[int, ...], None]`, in a `TypedDict` called `_Imports7`. What is wanted, for the hosts that have a built-in implementation:

- **Every import module is named, none is only numbered.** Today the `TypedDict`s of the imports are `_Imports0`, `_Imports1`, … by the order of the import section, and `wasi_snapshot_preview1` (and `wasi_unstable`) has **no type at all**, in no stub and in no wrapper. After: each module of the imports has a type whose name follows from the module name, and the first snapshot is one of them like the others.
- **A named `TypedDict` for each WASI module of the imports, with a name that follows from the module** (not from its place in the import section), listing **the functions the module imports** from it, each `NotRequired` when the host gives it and required when not. The key in `Imports` is the exact name of the import of this module (`'wasi:io/streams@0.2.12'`, `'wasi_snapshot_preview1'`, `'wasi_unstable'`), so a module that imports the first snapshot types `wasi_unstable` and not the other.
- **Each function has the exact signature.** The container is a `TypedDict` (decided): the keys are strings, which is native to it, and the optionality of a function lives in the key (`NotRequired`), not in the function type. A `Protocol` cannot say that a member may be absent, so it is only ever the type of a *value*, never the container. For now the value is a plain `Callable[[int, ...], int]`; a `Protocol` with positional-only parameters (it shows the names of the parameters in the editor) is a later upgrade of the value types only, with no change to the structure, once it is worth the extra class per function. Example (now):
  ```python
  class WasiSnapshotPreview1(TypedDict, total=False):
      fd_write: Callable[[int, int, int, int], int]   # fd, iovs, iovs_len, nwritten -> errno
      args_get: Callable[[int, int], int]
  Imports = TypedDict('Imports', {'wasi_snapshot_preview1': NotRequired[WasiSnapshotPreview1], **the modules that are the caller's: required})
  ```
  For 0.1 the result is the errno (`int`); for 0.2 what the core signature has (`None`, or a handle as `int`), with the pointer of the result among the parameters. The names of the parameters, for the later `Protocol`, are extractable (0.1 from `fusedwasi.p1` with `inspect`, cross-checked with witx; 0.2 from the core signatures with `host`/`comp` dropped; the check against a real module is still to do).
- **The same types in the stub of the extension and in the wrapper for ctypes** (the wrapper has `imports: Any` today): `Instance.__init__(self, imports: Imports | None = None, *, wasi: Wasi | None = None)` in both.
- **The definitions of the standard types move to fusedwasi, and the generator puts them into the stub.** What describes a standard module of WASI (the `TypedDict` of the module, the type of each function) is made once, from the same tables as the implementation (witx for 0.1, WIT for 0.2), and lives in fusedwasi. The generator takes them from there **when it makes a stub and writes into the stub the ones the module imports**, so a stub does not import fusedwasi at all: neither the type checker nor the run time needs it to read the stub. What the generator writes is plain `typing` (a `TypedDict` for the dictionary of a module; for the function a `Callable` now, a `Protocol` later, see above).
- **A missing key is the default, an explicit `None` is `None`.** In `imports` and in `wasi=` alike: a key that is absent means "the built-in host gives it" (hence `NotRequired`, never a default value that hides the difference); a key set to `None` means the caller says explicitly that nothing is given (no `stdin`, no such import), and it is not turned into the default. So the value types are `Callable[...] | None` where nothing-given is meaningful. What the module sees for a `None` import (a trap, ENOSYS) is not decided.
- **The original** (the reference taken from the instance, see above) is typed with the same function type, so a wrapper has the signature in front of it.
- For `host = "wasm32"` nothing of this is made: every import is generated as it is today (with the stable name).

## Where the types of WASI live

The types of the functions of WASI 0.1 and 0.2 (the standard interfaces) are kept **in fusedwasi** as the source, with the implementation they describe, so that they change together. wasmext does not copy them by hand: its generator takes them from fusedwasi and writes the ones a module needs into the stub (see above), so the stub stays free of fusedwasi. wasmhost uses the same definitions for its replacements. wasmext's own part is the modules that are not WASI.

Together with it, **the names of the types are stable.** For the modules of WASI the name follows from the name of the module (`_Imports_wasi_io_streams_0_2_12` or, better, the name the type has in fusedwasi), not from the position in the import section (`_Imports7`), which moves when a module is added or the compiler reorders the section. For the other modules wasmext makes the name from the module name in the same way, in the order of appearance when two names meet.

## WASI 0.2: what the host `wasm32-wasip2` also asks

- **`cabi_realloc` of every component** is an export that the build checks for and binds to the `realloc` hook of the state of fusedwasi (`fusedwasi_p2_*` takes the memory of a component and its realloc). A component without it is an error of the build, not a trap on the first string.
- The arguments, the environment and the streams can be given as **hooks in `wasi=`** that fill the state of fusedwasi (the module reads them through the imports, `wasi:cli/environment.get-arguments`, as it must), or by replacing those imports with their exact signatures (with the adapters of fusedwasi for the lowering).
- The host of 0.2 is **not in the ABI of wasmext yet** (a standing decision); the first step is the stub and the Python path (the host of fusedwasi through `imports`), the C path comes later.

## What is not decided

- The exact spelling of the constant in the module and of the key in `[tool.wasmext]`.
- Mixed modules (`wasi_snapshot_preview1` and `wasi:*` in one module): **not an error, a warning (a note of the build).** The host binds what it is named for; every import that does not belong to it is a plain import of the caller, as with `wasm32` (decided). A component fused through the component model is already P2, so such a module is not expected, and nothing special is built for it.
- The order of the work: the host and the stub first (no change of the ABI of the C), the binding of 0.2 after.
- The cost of wrapping an original import, and the shape of the reference to the original: after a measurement of the crossing C to Python to C.
- Whether `wasi=` is also for WASI 0.2, and its keys there.
- What the host means for wasmhost (it has no build): it would take the `host` as an argument of its class (`Preview1`, a later `Preview2`) or from the imports of the module it is given, and nothing in a file says which.
