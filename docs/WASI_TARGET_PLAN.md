# Plan: the `host` setting, typed named imports, `wasi=` hooks

Status: **stages 0, 1 and the first part of 2 are built (see below); the rest is a plan.** The concept and the reasons are in [wasi_target.md](wasi_target.md); this file is the order of the work. Each stage is a separate change that leaves the tests green. No stage changes the C ABI (`WASMEXT_ABI`) unless it says so. The numbers in brackets are the items of the agreed list.

## Stage 0: measure and check (no code in the product)

- Measure the crossing C to Python to C twice (a wrapper of an import that calls the original), to know whether a reference to the original can be a thin object made on demand. Decides the shape of stage 4. [39]
- Take the core imports of a real WASI 0.2 module (the `examples/wasi2_unbundled` ones) and compare their signatures and parameter names with the functions of fusedwasi (`host`, `comp` dropped). Decides whether the names for stage 2 can be generated. [45]
- Done when: two short notes (numbers; a table of matches and of mismatches).

## Stage 1: the `host` setting

- A value `wasm32` (default) / `wasm32-wasip1` / `wasm32-wasip2`, no `auto`; given to `wasmext natify`, to `[tool.wasmext]` and to the extension of the build; recorded in the artifact (a constant of the module). The spelling of the constant and of the key is chosen here. [4-9, 38]
- `_gen.py` binds the built-in WASI only for `wasm32-wasip1`; with `wasm32` every import is the caller's and a note is printed for the names of `wasi_snapshot_preview1`. The check of the signatures stays, only for the host that was said. [5-7]
- `wasm32-wasip3`: an error with the reason; threads variant left out. [11, 12]
- Mixed `wasi_snapshot_preview1` + `wasi:*`: not an error, a warning; imports that do not belong to the host stay plain imports of the caller. [37]
- The existing tests, examples and CI that rely on the guess get `host = "wasm32-wasip1"` (one line each); a test that a module with the same names and another host gets no binding; a test of the note.
- Done when: all tests pass with the explicit host and the default does not bind.

## Stage 2: named, typed imports in the stubs

- Generator (stub of the extension and wrapper of ctypes alike): a named `TypedDict` for each import module, including `wasi_snapshot_preview1` and `wasi_unstable`; only the imports the module has; `NotRequired` when the host gives them, required when not; the name follows from the module name, not from the position. Value type `Callable` with the exact raw signature; `Protocol` with names left for later. [26-28, 30, 32, 16-18]
- The standard definitions live in fusedwasi (generated from witx / WIT with the implementation) and the generator writes the ones needed into the stub; the stub does not import fusedwasi. [31]
- A missing key is the default, an explicit `None` is `None`; what the module sees for `None` is decided here (trap or ENOSYS). [29, 43]
- `host = "wasm32"`: nothing changes. [33]
- Tests: stubs checked by pyright for p1 and p2 examples, a stub with `NotRequired` and required keys, a stub that works without fusedwasi installed.
- Done when: `wasi_snapshot_preview1` is typed in the stubs and in the ctypes wrapper, and `_Imports0..` are gone.

## Stage 3: `wasi=` follows the host

- `wasi=` only for hosts with a built-in implementation; the keys `args`, `env`, `preopens`, `readonly`, `stdin`, `stdout`, `stderr`, `clock`, `random`; each feeds its imports; the import wins over the hook for the same function; `None` is explicit, an absent key is the default. [21-24]
- Done when: the stub of `wasm32` has no `wasi=`, the stub of `wasm32-wasip1` has it, and the precedence is tested.

## Stage 4: the original of an import

- A reference to the import taken from the instance (`__getitem__`; no tables), typed with the function type of stage 2, made on demand. The shape is chosen from stage 0. [19, 39]
- Tests: wrap `fd_write` and call the original; no cost for who does not wrap.

## Stage 5: adapters `lift` / `lower` in fusedwasi

- Optional; only after stage 4. How an adapter reaches the memory (`attach(instance)`); p1 has no `lift` through the raw original (no realloc). [20, 40]
- Done when: decided with the user; not built before.

## Stage 6: WASI 0.2 as a host

- Python path first (imports of fusedwasi through `imports`), a check at build that the component exports `cabi_realloc`. [34-36]
- Whether `wasi=` is for 0.2 and its keys. [25, 41]
- The C path and the ABI of the host of 0.2 later, by a separate decision.

## Stage 7: wasmhost

- Decide what `host` means there (an argument of the class, or from the imports of the module). [42]

## Order and dependencies

0 → 1 → 2 → 3; 4 needs 0 and 2; 5 needs 4; 6 needs 2; 7 is independent after 1. The import resolver and the model are **not built** until the user decides on stage 0's results.

## The agreed list (the numbers used above)

Problem. 1. WASI 0.1, WASI 0.2 and the user's imports are one thing but handled in three ways. 2. Binding goes by the look of the module (names, signatures), which proves nothing; the file does not say the host. 3. WASI 0.2 needs an import and an export (`cabi_realloc`); its arguments, environment and streams come through imports.

Host. 4. `host` is `wasm32` (alias `wasm32-unknown-unknown`), `wasm32-wasip1` or `wasm32-wasip2`. 5. Default `wasm32`, no `auto`. 6. For `wasm32` with `wasi_snapshot_preview1` names the build only prints a note. 7. The check of signatures stays as a check of what was said (an error with `wasip1`, nothing with `wasm32`). 8. The host is recorded in the artifact. 9. It is given to `wasmext natify`, to `[tool.wasmext]` and to the extension. 10. A host is the name space of the imports, not the kind of the file; for `wasip2` the core module after `unbundle`/`meld`. 11. `wasm32-wasip3` is not supported. 12. `wasm32-wasip1-threads` is not decided.

Chain. 13. What the caller gave in `imports=`. 14. What the host binds, by (module without its version, name). 15. The rest is required.

Imports. 16. Exact full signatures, replaceable by the caller. 17. Required or not is decided per import of the module: what the host gives is `NotRequired`, what it cannot give is required. 18. Names of the parameters from the specification (witx, WIT). 19. The original is a reference to the import taken from the instance by `__getitem__` (no tables); it is new, `Function` exists today only as `Table.get(i)`. 20. Adapters `lift`/`lower` in fusedwasi (with `attach(instance)`) are not decided; p1 has no `lift` through the raw original (no realloc).

`wasi=`. 21. Stays for simple hooks: `args`, `env`, `preopens`, `readonly`, `stdin`, `stdout`, `stderr`, `clock`, `random`. 22. Each key feeds its imports. 23. Only for hosts with a built-in implementation; none for `wasm32`. 24. If both an import and a hook are given for one function, the import wins. 25. Whether it is for p2, and its keys: open.

Stubs. 26. Every import module is named, none numbered; `wasi_snapshot_preview1` and `wasi_unstable` get a type. 27. A named `TypedDict` per WASI module with only the functions the module imports; the key is the exact module name. 28. The container is a `TypedDict` with `NotRequired` (a `Protocol` cannot say a member may be absent); the value is a `Callable` now, a `Protocol` with names later. 29. An absent key is the default of the host, an explicit `None` is `None`; what the module sees for it is open. 30. The same types in the extension and in the ctypes wrapper. 31. The standard definitions live in fusedwasi; the generator writes the needed ones into the stub, so the stub does not import fusedwasi. 32. Stable names that follow from the module name, not from the place in the import section. 33. For `wasm32` nothing of this is generated.

WASI 0.2. 34. `cabi_realloc` is a required export; its absence is an error of the build. 35. Arguments, environment and streams through hooks of `wasi=` or replaced imports. 36. The host of 0.2 is not in the ABI of wasmext; stub and Python path first, C path later.

Mixed. 37. `wasi_snapshot_preview1` + `wasi:*` in one module is not an error but a warning (a note of the build): what does not belong to the chosen host is a plain import of the caller. A component fused through the component model is already P2, so nothing special is built for it.

Open. 38. The name of the constant and of the key in `[tool.wasmext]`. 39. The shape and the cost of the reference to the original (to measure). 40. How `lift`/`lower` work. 41. The keys of `wasi=` for p2. 42. What `host` means for wasmhost. 43. What the module sees for `None`. 44. The order of the work (this plan). 45. The check of the extracted p2 names against a real module.

## Stage 0: results (2026-10-23)

**The names of WASI 0.2 (item 45).** The core imports of `examples/wasi2_unbundled` (`_hello.wasm` 21, `_sock.wasm` 74) were mapped to the functions of fusedwasi by a fixed rule on the name: the module path with `/` and `:` as `_`, `[method]`/`[static]` dropped, `.` as `_`, `[resource-drop]x` as `x_drop`. **All 95 imports were found, and the number of parameters matched the core signature in all of them** once the two internal ones (`host`, `comp`) were dropped (the last parameter is `retptr`). So a generator can take the signature (the number and the kinds of the values) from fusedwasi, or better from the same WIT it is made from. **A limit:** the names are good for most (`wasi_io_streams_output_stream_write(self, ptr, len, retptr)`, `get_arguments(retptr)`, `poll(in_ptr, in_len, retptr)`), but where a record or a variant is flattened by hand the names are generic (`tcp_socket.start_connect(self, network, tag, p1 … p11, retptr)`). For those the generator has to name them from the WIT (`address.ipv4.port`, …), not take them from fusedwasi; the types (`i32`/`i64`) are not in the Python at all and come from the core signature of the module. A `Callable` is therefore enough for the first version, as decided.

**The cost of a wrapper (item 39).** One process, CPython 3.13, Linux, 1,000,000 calls of an import with four `i32` and one result: a Python function that returns at once, **98 ns per call**; a Python function that calls a C function of another instance (a stand-in for the original: the border C to Python to C), **148 ns per call**. So wrapping adds about **50 ns per call**, one more border. The built-in WASI call without a wrapper stays in C. For the calls that do real work (a write, a read, a clock) 50 ns is below the noise; for a hot loop of tiny calls it is a third more than the call to Python already costs. This is acceptable for a reference made on demand: **a thin object over the C function is enough, no cache and no special path is needed.** (The reference was not built; the stand-in is an exported function of a second module.)

Decision for stage 4 that follows: the reference is made on demand and is a thin callable; nothing in this measurement asks for a change of the shape. Stages 1 and 2 are not held up by stage 0.

## Stage 1: built (2026-10-23)

`host` is `wasm32` (default), `wasm32-wasip1` or `wasm32-wasip2` (alias `wasm32-unknown-unknown` for `wasm32`); anything else is an error (`wasm32-wasip3` says WASI 0.3 is not supported). It is an argument of `natify()`, `generate()`, `build_shared`/`build` and `wasmimport.install()`, the key `host` of `[tool.wasmext.ext-modules]`, and `wasmext natify --host`. It is an input of the C (it is in the digest and the head of the generated files) and is told by the module as `__host__` (also in the stub as `Literal`). Only `wasm32-wasip1` binds `wasi_snapshot_preview1` and `wasi_unstable`; with the others every import is the caller's and a note says so for the names of WASI 0.1 (and, with `wasm32-wasip1`, for `wasi:*` imports, a warning, not an error). `wasm32-wasip2` binds nothing yet and says so. A program (`--exe`) needs `wasm32-wasip1` and says so otherwise. The tests, the examples that use WASI 0.1 (lua, quickjs, wabt, products) and the test suite adapter now say `wasm32-wasip1`. The declaration of the ABI got `__host__` (an addition to the stub); its version is not changed here.

## Stage 2: first part built (2026-10-24)

The stub (one text, the `.pyi` of the extension and of the wrapper for ctypes alike, so both have the same interface) types the imports by module: a `TypedDict` for each module of the imports, named by the module (`_Imports_wasi_snapshot_preview1`, `_Imports_wasi_io_streams_0_2_12`, `_Imports_env`; every character that is not a letter or a digit becomes `_`; a clash gets a number in the order of the section), listing only the functions the module imports, each with the exact raw signature as a `Callable`. For a module that the host answers (`wasm32-wasip1`: `wasi_snapshot_preview1`, `wasi_unstable`) the key of the module in `Imports` and every function are `NotRequired` (a replacement), so `imports` is optional (`Imports | None = None`) unless the module also has imports of the caller's; for the others they are required, as before. The numbered `_Imports0..` are gone, and `wasi_snapshot_preview1` is typed where it was `imports: None = None`. Tested on both front ends (`tests/test_host.py`: a call of WASI replaced through `imports` in the extension and in the wrapper for ctypes) and with pyright against a generated stub.

Not yet (stay for the next parts): the explicit `None` (the runtime does not give it a meaning yet, so the types do not offer it), the standard definitions in fusedwasi and the names of the parameters (`Protocol`; the types of `Callable` come from the module's own function types, so fusedwasi is not needed for this part), the adapters.

### The explicit `None` (decided and built, 2026-10-24)

For a call of a host that wasmext answers (`wasm32-wasip1`), a function given as `None` in `imports` means **nothing is given**; an absent key is the default (the call of wasmext). The same in the extension and in the wrapper for ctypes (before, the extension raised `LinkError: ... is not callable` and the wrapper for ctypes took `None` as the default). What the module sees: a call that answers with an errno (the result is one `i32`) gets **ENOSYS (52)**; a call that has no errno to answer with (`proc_exit`) is a **trap** (`Trap: <module>.<name> was given as None: nothing to call`). An import of the caller's (not answered by the host) given as `None` is not linked (`LinkError`), as a missing one is. The stub types the functions of a bound module as `NotRequired[Callable[...] | None]`; the module key itself does not take `None`. ENOSYS and the trap are a choice of mine for "what the module sees" (the plan left it open); say if another is wanted.

### `lift` / `lower`: deferred (decided 2026-10-24)

Not built, and not planned for now. Reason beyond "no user yet": the adapters were proposed to live in fusedwasi and be imported by the code of the user (`from fusedwasi import lower`), which would make **fusedwasi a dependency at run time**. An extension of wasmext has none (the C of WASI is compiled into the module; the stub imports nothing), and that stays a rule. If the adapters come back, they must be generated into the module or the stub, or live in the glue of wasmext, with nothing to install on the host. The same rule holds for the standard types (the generator writes them into the stub) and for the names of the parameters of a later `Protocol`. Items 20, 40 of the list stay open.

## Stage 3: built (2026-10-24)

`wasi=` stays one parameter whose type follows the host (decided against separate `wasip1=` / `wasip2=`: one module has one host, the keys are mostly the same, so the code of the user does not change with the host). The stub of `wasm32-wasip1` names the configuration `WasiP1` (and `Wasi = WasiP1` for the code that already says `Wasi`); `wasm32-wasip2` will have `WasiP2` when its host is built (it has no `wasi=` now), `wasm32` has none. Checked on both front ends (`tests/test_host.py`): an import wins over the hook for the same call (`wasi={'stdout': ...}` and `imports` with `fd_write`: the import is called, the hook is not); a module whose host has no WASI built in takes no `wasi=` — the wrapper for ctypes used to accept it silently, and now raises `TypeError` as the extension does. The keys and their `None`/absent meaning (`None` is nothing, absent is the default) are those documented in the stub. The `wasi=` keys of WASI 0.2 remain open (item 25, 41).

### Stage 4: what is settled before it is built (2026-10-24)

The original of an import is a reference to the call that the host answers (for `wasm32-wasip1`, a call of WASI). `__getitem__` of an instance gives references to **exports** only (a `PyCapsule`, for linking instances, not callable from Python), so an import needs its own way in; the name `__imports__` is used for it (the idea of a list of needs under that name is dropped: the stub has the signatures). Open: the shape (nested `{module: {name: ...}}` as `imports=` is, and whether the values are callable objects, as a wrapper needs, or capsules like `__exports__`; unifying `__exports__` with the same callable is a later option).

## Stage 4: built (2026-10-24)

`Instance.__host__` gives a `Host` (for a host that has WASI built in, `wasm32-wasip1`; a module of host `wasm32` has none), with `Host.name` (`'wasm32-wasip1'`) and `Host.__imports__`: `{module: {name: the call}}`, the **originals** of the calls that wasmext answers (only the ones the module imports), **whatever the caller gave in place of them**. Each is a plain callable that does what the call of wasmext does on the memory of this instance and answers as the call does (the errno as an `int`; `proc_exit` and the like raise their exception: `WasiExit`). It is the way for a wrapper to pass a call on:

```python
def fd_write(*args):
    log(args)
    return inst.__host__.__imports__["wasi_snapshot_preview1"]["fd_write"](*args)


inst = mod.Instance({"wasi_snapshot_preview1": {"fd_write": fd_write}})
```

Other points as settled in the conversation: `__exports__` is the **current** reference to an export (a capsule, for linking), `__imports__` of the instance (the current binding) is **not built** (nothing needs it yet); the originals belong to the host, so they are under `Host.__imports__`. In the extension `Host` is a small type of the module (not creatable by the user); in the library it is `<name>_host_call<k>(m, parameters..., result*)` of the C API (0, or the code of a trap) and the wrapper for ctypes builds the same `Host` on it; the stub is the same text for both. `Host` is made so that it can later move under a context (context_concept.md): it holds the instance, no state of its own. Not built: a host shared between instances (needs the memory of the caller of each call), and the originals for WASI 0.2.

### Stage 7: what `host` means for wasmhost (settled in outline, 2026-10-24)

wasmhost has no build, so `host` is not a constant of a file. There it depends on the **runtime** (the backend): some backends have a WASI host of their own, others need one. Who answers the imports is chosen, never guessed from the names of the imports: **wasmhost's** (`wasmhost.wasi.Preview1`, over fusedwasi: what is there today, given by the user as `Preview1(...).imports()`) or **the user's own imports**. A host of the backend's own (where a backend has one) is not wanted for now. The chain is the one of wasmext (item 13-15): what the caller gave wins, then the host that was named, then the rest is required. Not designed yet: the spelling (an argument of the instantiation or of the class), and which backends can expose a host of their own through the API wasmhost has. To be settled with the owner of wasmhost before it is built.

### Stage 6: what is left, and what is not (corrected 2026-10-24)

The functions of WASI 0.2 **are written already**, in C in fusedwasi (`p2/wasi_p2_*.h`, one function per import, `fusedwasi_wasi_<interface>_<name>(state, comp, ..., retptr)`, `comp` being the number of the memory, so a module fused from components is covered) and in its Python twin. The earlier estimate of "adapting 201 functions" was wrong. What is left is the **binding in wasmext**, not the functions: (1) a table from the import `(module without version, name)` to the C function (the rule was checked on all 95 imports of `hello` and `sock`, stage 0); (2) the state of the host: made with the instance, the memory (and the memories) bound, and `cabi_realloc` of the module given to it as a call into the module; (3) the configuration `wasi=` of the host of 0.2 (arguments, environment, preopens, streams, clocks, random; and what only 0.2 has) turned into the state, with the hooks that p1 has for Python; (4) the exceptions of the end of the program (`exit`, a trap) as for p1; (5) the C API of the library and the wrapper for ctypes; (6) the stub and the tests (`examples/wasi2_unbundled` as the first one). The C ABI of wasmext grows (the state of the host of 0.2), which lifts the earlier rule "the host of 0.2 is not in the ABI".

### Order of the work (decided 2026-10-24)

Stage 6 (the host of WASI 0.2 built in, a private host of the module) is finished **as planned, with no change of direction**, even though the context idea (context_concept.md: one runtime and one host per context, several modules on it) bears on it. The shared runtime and the context are **the next step after it**; the host of 0.2 keeps its state free of the module (memory by number) so that it can move under a context.

### Stage 6: what the C host of fusedwasi asks of the binding (reconnaissance, 2026-10-24)

Read in `p2/wasi_p2_core.h` and `wasi_p2_io.h`; the host is made to be embedded:
- **State and life:** `fusedwasi_p2_state` (a table of handles, up to 8 memories, args, env, preopens, the standard streams, clocks, random, the policies of sockets and http), `fusedwasi_p2_init(s)` and `fusedwasi_p2_free(s)`. No global and no thread-local.
- **Functions:** one per import, `fusedwasi_wasi_<interface>_<name>(state, comp, parameters..., retptr)`, with `comp` the number of the memory. They have **no `trapped` out-parameter**: a trap is the callback `s->trap(s, message)`, which must not return (in a module it is `wasm_rt_trap`). The glue therefore needs one trampoline for each import (the host function of wasm2c is `result f(void *user, parameters..., int *trapped)`), which also sets the memory.
- **Memory** is a copy `{base, size}` (`fusedwasi_p2_set_memory`), not a pointer to the field as in p1: it must be set again before each call, since the memory moves when it grows.
- **`cabi_realloc`** is the callback `s->realloc(s, comp, old_ptr, old_size, align, new_size)`: in a module a call of its export `cabi_realloc` from the host function (a call inside a call; no new entry is needed).
- **The end:** `s->exit(s, code)` records `exited` and `exit_code` and traps; the glue turns it into `WasiExit(code)`.
- **Streams** are `fusedwasi_p2_stream` with `read`, `check_write`, `write`, `flush`, `ready`, `destroy`; the standard streams are `std[0..2]` (NULL: the descriptors of the process). A Python object behind a stream is a layer of ours (the twin of `wasi_python.h` for 0.2).
- **Policies** (`socket_addr_check`, `allow_ip_name_lookup`, `http_check`, `http_send`): refuse everything unless set.

Sub-stages: **6a** the extension, WASI 0.2 command (`wasi:cli`, `clocks`, `io`, `random`) with `wasi=` (`args`, `env`, `stdin`, `stdout`, `stderr`, `clock`, `random`), `examples/wasi2_unbundled/_hello` runs with no Python host; **6b** filesystem (`preopens`, `readonly`); **6c** sockets and http (policies; built, see below); **6d** the library and the wrapper for ctypes (built, see below). The table from the import to the C function and its core signature is made once from the headers of fusedwasi (a data file in wasmext), so a name the host does not have is a `GenError`, as for 0.1.

## Stage 6a: built (2026-10-24)

`host = "wasm32-wasip2"` makes the extension answer the imports of `wasi:*@0.2.x` with the C host of fusedwasi: for each import a generated function (the glue, no Python) sets the memory of the instance, calls `fusedwasi_wasi_<interface>_<name>(state, [0,] arguments)` and returns its result; the state (`fusedwasi_p2_state`) is in the instance, `cabi_realloc` is the callback that calls the export of the module, a trap is a `wasm_rt_trap`, and `wasi:cli/exit` raises `WasiExit(code)`. The table from the import to the C function and its signature is `src/wasmext/_wasi_p2_table.py`, made from the headers of fusedwasi by `tools/make_wasi_p2_table.py`; an import the table does not have, or one with another signature, is a `GenError`; a module that imports WASI 0.2 and does not export `cabi_realloc` (or `memory`) is refused. `wasi=` is read by the code of 0.1 (`wasi2_python.h` reuses it: `args`, `env`, `stdin`, `stdout`, `stderr`, `clock`, `random`, `preopens`, `readonly`; one reading, as planned for the neutral configuration), and the streams of the standard descriptors are Python objects (`sys.stdout` when none is given). A function given as `None` is nothing given: a trap. The stub has `WasiP2` / `Wasi = WasiP2` and the typed, named `_Imports_wasi_...` with the calls `NotRequired`. `examples/wasi2_unbundled/_hello.wasm` runs with no Python host (`tests/test_wasi2.py`; the module `tests/data/wasi2_probe.wat` is a core module of the same shape written by hand). Not in 6a: the originals of the calls (`Host`), the library and the wrapper for ctypes (6d), files (6b), sockets and http (6c: their policies refuse everything now).

## Stage 6b: built (2026-10-24)

The files of WASI 0.2 work in the extension with the host of fusedwasi, over the canonical ABI: `wasi:filesystem/preopens` lists the directories of `wasi={'preopens': {...}}`, `descriptor.open-at`, `read-via-stream` / `write-via-stream` (with `input-stream.blocking-read` and `output-stream.blocking-write-and-flush`), `create-directory-at`, `unlink-file-at`, the drops. Tested at the level of the ABI (`tests/data/wasi2_fs.wat`, a core module written by hand, and `tests/test_wasi2.py`): the directories are listed by name, a file is read, a missing one gives `no-entry`, a file is written and a directory made and removed on the real disk, a directory given as `readonly` refuses a write, and a name that leaves its directory (`../secret.txt`) is refused. The generator copies both system backends of fusedwasi (`..._fs_posix.h`, `..._fs_win32.h`) beside the C and includes only the header of the files, which includes the right one (the first attempt included both and failed on Linux). Windows is checked by CI only. Not done: the other functions of `wasi:filesystem` are bound but not tested (stat, directory listing, links, times, sync).

### Tests of the 201 functions

What is covered: `test_every_function_of_the_table_compiles_with_the_headers_the_glue_includes` (`tests/test_wasi2.py`) takes all 201 functions of `_wasi_p2_table.py` by address, in one file with the headers the glue includes, strictly (`-Werror=incompatible-pointer-types` and the like). It proves that the table, the headers and the glue agree on names and types; it does not call them. Run by wasmext's own tests: hello, arguments and environment, exit, clock and random, the files (`wasi2_fs.wat`), the sockets (`_sock.wasm`). Not run by them: the rest of `wasi:filesystem`, UDP, name lookup, http. Their behaviour is tested in fusedwasi (its C driver compares all 32 functions of `wasi:filesystem` with the Python twin), so wasmext does not repeat it; the official suite (`WebAssembly/wasi-testsuite`, branch `prod/testsuite-base`, checked 2026-10-24) has no WASI 0.2 programs: it has `wasm32-wasip1` and `wasm32-wasip3` (components that import `wasi:cli@0.3.x`, async, which the unbundled core module cannot carry), so a check of the whole chain for 0.2 needs programs of our own (C or Rust built as components, then `wasm-tools component unbundle`, like `examples/wasi2_unbundled`).

### Stage 6c: built

The network is refused unless the caller allows it, as in Wasmtime, and the policies are Wasmtime's: no patterns or lists. `wasi=` has `sockets` (`True`, or a function `(ip, port, use) -> bool`, `use` being `"tcp-bind"`, `"tcp-connect"`, `"udp-bind"`, `"udp-connect"` or `"udp-outgoing"`), `tcp` and `udp` (`False` refuses that protocol before the policy is asked), `dns` (a bool: `allow_ip_name_lookup`) and `http` (`True`, or a function `(scheme, authority) -> bool`). `None` or an absent key is a refusal; any other type is a `TypeError`. An exception in a policy traps and comes out of the call. `https` has no transport (`http_send` is not offered). `examples/wasi2_unbundled/_sock.wasm` connects to a real server in `tests/test_wasi2.py`; no test module imports `wasi:http`, so `http` is covered by its configuration only.

### Stage 6d: built

The shared library and the wrapper for ctypes answer WASI 0.2 as the extension does (`host = "wasm32-wasip2"`), with the same `wasi=` and the same tests (`tests/test_wasi2.py` runs on both front ends). The glue is the same (no Python); what the extension does with `wasi2_python.h`, the library does in C over the hooks of `<name>_config`: `args`, `env`, `dirs` (+ `dirs_readonly`), `stdin_read`, `stdout_write`, `clock`, `random`, `sleep` (the wait of a blocking call), and for 0.2 the policies `sockets` (a function, or `sockets_all`), `no_tcp`, `no_udp`, `dns`, `http` (a function, or `http_all`). A hook answers 0, an errno of WASI (64, the closed pipe, closes the stream; the rest fails it) or `HOOK_TRAP`; a policy answers 1, 0 or a negative number (a trap, the exception of the host stays in the wrapper). `<name>_wasi_end` answers 1 and the code after `wasi:cli/exit`. The wrapper has `__host__` (also for 0.1, where it was missing). Not here, for 0.2: the originals of the calls (`Host`, `<name>_host_call<k>`) and the `Host` class; a call given as `None` is always a trap.

### After stage 6: one shape of the host

The hosts of 0.1 and 0.2 are bound differently today (p1: the slot points at the function of fusedwasi and `user` is its state; p2: a trampoline for each import and `user` is the instance; the table is in `capabilities.md`, section 3). The context (a private host and runtime) needs one shape, so they are unified: the slot is `(fn, user)` with `user` the instance (later the context) and a trampoline only where something has to be done around the call; a direct binding stays for the calls that need nothing. Order: stage 6 as it is; the context as the next step, which fixes the shape; p1 moves first in that step, after a measurement of `fd_write` / `fd_read`, with the official test suite and `tests/test_host.py` as the net; then the originals of the calls (`Host`) for p2 and the `caller` of an import. Details: `capabilities.md`, section 4.
