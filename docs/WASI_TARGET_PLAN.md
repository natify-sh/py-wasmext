# Plan: the `host` setting, typed named imports, `wasi=` hooks

Status: **a plan, nothing is built.** The concept and the reasons are in [wasi_target.md](wasi_target.md); this file is the order of the work. Each stage is a separate change that leaves the tests green. No stage changes the C ABI (`WASMEXT_ABI`) unless it says so. The numbers in brackets are the items of the agreed list.

## Stage 0: measure and check (no code in the product)

- Measure the crossing C to Python to C twice (a wrapper of an import that calls the original), to know whether a reference to the original can be a thin object made on demand. Decides the shape of stage 4. [39]
- Take the core imports of a real WASI 0.2 module (the `examples/wasi2_unbundled` ones) and compare their signatures and parameter names with the functions of fusedwasi (`host`, `comp` dropped). Decides whether the names for stage 2 can be generated. [45]
- Done when: two short notes (numbers; a table of matches and of mismatches).

## Stage 1: the `host` setting

- A value `wasm32` (default) / `wasm32-wasip1` / `wasm32-wasip2`, no `auto`; given to `wasmext natify`, to `[tool.wasmext]` and to the extension of the build; recorded in the artifact (a constant of the module). The spelling of the constant and of the key is chosen here. [4-9, 38]
- `_gen.py` binds the built-in WASI only for `wasm32-wasip1`; with `wasm32` every import is the caller's and a note is printed for the names of `wasi_snapshot_preview1`. The check of the signatures stays, only for the host that was said. [5-7]
- `wasm32-wasip3`: an error with the reason; threads variant left out. [11, 12]
- Mixed `wasi_snapshot_preview1` + `wasi:*`: an error of the build. [37]
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
