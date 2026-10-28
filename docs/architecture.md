# The architecture of the project: what it is to be at the end

Status: **written 2026-10-28**, at the owner's request, from what is built and from the plans ([WASI_TARGET_PLAN.md](WASI_TARGET_PLAN.md), layers.md, layers.md, [owners_registry.md](owners_registry.md), [context_concept.md](context_concept.md), [why_wasi_p2.md](why_wasi_p2.md)). Every element is marked: **[built]** it exists and is tested, **[planned]** it is decided and has a place in the plan, **[proposed]** it is my synthesis, to be agreed. Where the target differs from today, the section "From here to there" says what moves.

> **How the library is cut to get this picture is in [layers.md](layers.md)** (the owner's decision: front-end glue -> shared glue -> wasmext glue, one rework of the whole library, not small moves). The table of results R1-R5 at the end of this page is about the *features* that are written once on top of that, after it; it is not the way to the cut.

## What the project is for

**Take an unmodified WebAssembly module, built for a standard target, and run it** (the owner's principle): as a native CPython extension, as a shared library with a wrapper for ctypes, or as an executable, with WASI (0.1 and 0.2) answered by a host that is ours, so that nobody is told how to patch the sources. Three repositories:

| Repository | What it is |
| --- | --- |
| **fusedwasi** [built, 0.1.0a1 on PyPI] | the functions of WASI 0.1 and 0.2 in C (headers) and Python, with the state they need (`State`, `Guest`); it knows no engine and no consumer |
| **py-wasmext** | turns a module into native code with `wasm2c` (AOT) and gives it a Python-, ctypes- or C-facing shell; this is where the store, the linking and the ownership live |
| **py-wasmhost** | the same ideas for modules that run **in an engine** (wasmtime, wasm3, the JavaScript engines), in Python; WASI by fusedwasi |

## The layers of wasmext, from the bottom

```
 your program (Python, C, a shell)
        |
 [4] FRONT ENDS            thin: convert values, keep Python objects alive, call back into Python
        |                  extension for CPython | wrapper for ctypes over the shared library | executable
        |
 [3] THE CORE (C, no Python)   one for all front ends
        |                  store, instance, linking of imports to exports, tables and functions,
        |                  owners, traps, memory, the host (WASI config), errors as code + message
        |
 [2] THE MODULE            what depends on the module and nothing else (generated):
        |                  its exports and imports, signatures, the trampolines for the types it declares,
        |                  the glue of wasm2c  (<name>_w2c.c/h, <name>_glue.h, <name>_api.h)
        |
 [1] THE RUNTIME           wasm2c's runtime (a copy in every module) + fusedwasi (WASI 0.1 and 0.2)
```

**The rule between the layers:** a layer calls only the one below it, never a front end from the core. The core reaches Python (or ctypes) only through a **small table of callbacks that the front end gives it**: *retain* and *release* of an owner, *call a host function*, *describe an error*. That is what keeps one logic for three targets.

## The elements

### [1] The runtime
- **wasm2c's runtime**, compiled into each module [built]. A module never depends on another module's copy; modules that meet in one process agree on the one handler of traps through the capsule `wasmext.traps` [built].
- **fusedwasi** [built]: `State` (the world: arguments, environment, files, clocks, random, policies, tables of handles), `Guest` (one for each instance: its memory, `realloc`, trap, exit). One `State` and one `Guest` serve WASI 0.1 and 0.2. Its C headers are copied beside the C of a module at build time (`fusedwasi.get_include()`); a module built by wasmext needs neither wasmext nor fusedwasi at run time [built, a standing rule].

### [2] The module (generated, and only this)
For each `.wasm`: the output of `wasm2c`, `<name>_glue.h` (the exports as data, the getters of memories and tables, the link functions for the imports it has), `<name>_api.h` (the C API of that module). The target is that **the generator writes only what depends on the types and the names of the module**; the logic around it is not generated but shipped (next section) [proposed; today the generator also writes much logic, see the audits].

### [3] The core (shipped, hand-written C, no Python) — the heart of the "thin glue" decision
Today it is `src/wasmext/c/wasmext_glue.h` and what `_shared.py` writes into `<name>_shared.c`. The target [planned/proposed]:

| Part | What it holds | Status |
| --- | --- | --- |
| **ABI records** | `wasmext_export` (what an instance gives another), `wasmext_traps` (the stack of entries), later `wasmext_store` (C7); each versioned by `abi`, `floor`, `size`; fingerprint of the layout of the runtime | export, traps [built]; store record [planned, C7] |
| **Store** | a group of instances that share a host and a lifetime; `close` with a counter of active calls; the arena that holds its members until `close` | public `Store` in all three front ends [built]; arena, registry [planned] |
| **Instance and linking** | making an instance, binding each import to a host function or to an export of another instance, unlinking on failure; `export_find`/`export_at` | partly in the core, partly written again in the front ends [to be gathered] |
| **Tables and functions** | `funcref` tables, `Function`, the checks and the messages of `table_set`; type hashes | in the core as storage; the rules are written in each front end [to be gathered] |
| **Owners (the registry)** | `module_instance -> owner`, weak, one for an interpreter, shared through a capsule; opaque owner handles with front-end *retain*/*release*; replaces the keep-alive chains | [planned, C2b/C2c] |
| **Traps and errors** | trap code -> kind, text, exit code, signal; the cell for a host error (replaces `_pending`) | trap stack [built]; one table and the cell [planned] |
| **Memory** | the pin counters, `memory.grow`, views | counters in each front end [to be gathered] |
| **Host (WASI)** | the config of a store (`--dir`, `--env`, streams) in one builder; the binding of fusedwasi to an instance (`Guest` bound to its memory) | built per front end; one builder [planned] |
| **Tags, `externref`** | one identity of a tag in a store; `externref` owned by the arena | [planned, C6, C5] |
| **Shared runtime across artifacts** | a store made by one artifact used by an instance of another, through the versioned record `wasmext_store`; the state of WASI never crosses (opaque) | [planned, C7] |
| **Lazy collector** | frees members nothing reaches; hot reload | [planned, C8, later] |

### [4] The front ends (thin)
Each does only: **convert** a value (Python `int`/`float`/`bytes`/`Function`/`memoryview` <-> the wasm value), **keep Python objects alive** (it gives the core the retain and release), **call Python** for a host function and **map** the core's code and message to its own exception. Nothing else.

| Front end | Form | Status |
| --- | --- | --- |
| **Extension for CPython** (`--extension`) | `<name>_py.c`: the type objects (`Instance`, `Table`, `Function`, `Store`, `Host`, `Caller`), argument parsing, GC support (`tp_traverse` through the core's owner list), abi3 or native; declares free-threaded support once the Python side is audited | built, but carries logic that belongs below layers.md |
| **Wrapper for ctypes** (`--shared`) | the shared library with the C API, and a Python wrapper: *one static file* plus a small generated stub with the names and signatures (instead of a 800-1000 line template) | built as a template; static file [proposed] |
| **Executable** (`--exe`) | `<name>_main.c`: `main`, options, the store made through the API | built, but it fills the state of fusedwasi by hand instead of the API [to fix] |

The three **do not talk to each other through Python attributes** (`_pending`, `__wasmext_keep__`...): the contract between them is the C records and the core's functions [to fix; this is the cause of the known `Trap` between the extension and the wrapper].

### The build side (Python, build time only)
`_wasm.py` (parser), `_gen.py` (the extension's template and the glue), `_shared.py`, `_ctypes_gen.py`, `_exe.py`, `_natify.py`/`_cli.py`/`_setuptools.py`/`_importer.py` (how it is asked for: `wasmext natify`, setuptools, an import hook), `_inspect.py` (what a module imports and exports; names a component and tells how to turn it into a core module), `_toolchain.py`, `_abi.py` (the fingerprint of the C ABI). **The target: the generators are small** (names, signatures, trampolines for the declared types), because the logic is not generated.

### WASI
`host="wasm32-wasip1"` / `"wasm32-wasip2"` / `"wasm32"` says what answers a module's imports (not guessed from names). A module of 0.1 is answered inside the module (C, from fusedwasi); a module of 0.2 is a core module taken out of a component (`wasm-tools component unbundle` or `meld fuse`) with the flat `wasi:*` imports, answered by the same fusedwasi functions [built]. Components themselves are not read; WASI 0.3 is out of scope.

## py-wasmhost, at the end
A Python library over **engines** that have no store of their own in most cases. At the end it has a **store on the Python side** shaped like wasmext's (same names, same idea), so that moving values between instances and modules does not depend on the engine; the engines declare what they can (`supports(...)`), the rest honestly says "not supported". WASI is `wasmhost.wasi.preview1` over the Python twin of fusedwasi (and, if it is taken on, fused modules of 0.2 the same way; **not decided**). It is built **after** wasmext's store is done, to take its shape ([py-wasmhost/ROADMAP.md]).

## The tree

```
fusedwasi/                          [built, 0.1.0a1]
  src/fusedwasi/
    include/fusedwasi/p1/ p2/       C headers: WASI 0.1 (over 0.2) and 0.2, header-only
    p1/ p2/                         the Python twin
    signatures/*.json               the table of signatures: find_import(module, name)
    public_api.json                 the list of public names (everything else is private)
  tests/neutral/                    users that are not ours: wasmtime-py, wasm3, pywasm3

py-wasmext/
  src/wasmext/
    # ---- build time (Python) ----
    _wasm.py  _inspect.py           parse a module; say what it needs
    _gen.py   _shared.py            generators: the module part + the shells        [to shrink]
    _ctypes_gen.py                  -> a small stub generator + one static file     [proposed]
    _exe.py   _natify.py  _cli.py  _setuptools.py  _importer.py  _toolchain.py  _abi.py
    # ---- shipped C, no Python (the core) ----
    c/
      wasmext_glue.h                today: records, traps, tables, link helpers     [built]
      core/ (proposed split)        records.h  store.h  link.h  tables.h  owners.h
                                    traps.h    errors.h  memory.h  host.h          [planned/proposed]
      wasi_python.h wasi2_python.h  the Python hooks of the WASI host (the extension only)
    # ---- shipped front-end code (thin) ----
      (extension: shell of <name>_py.c)       [built; to shrink]
      wasmext_ctypes.py             the static ctypes wrapper                        [proposed]
  abi/current.json                  the fingerprint of the C ABI (a test fails when it moves)
  tests/                            ~250 tests run on both front ends (fixture front_end)
  examples/                         coremark link lua plugins products quickjs wabt
                                    wasi2_python wasi2_unbundled
  docs/                             this page, the plans, the audits, the studies

py-wasmhost/
  src/wasmhost/
    (engines)  wasmtime  wasm3  node  bun  jsc  jscontext  pyodide
    wasi/preview1.py                WASI 0.1 over fusedwasi
    (store on the Python side)      [planned, after wasmext]
  examples/  tests/  ROADMAP.md  BACKLOG.md
```

## Dependencies, in one direction

```
 wasmhost ---> fusedwasi (Python twin)            wasmext (build time) ---> wabt (wasm2c), fusedwasi (C headers)
 built extension / library / executable ---> wasm2c runtime + fusedwasi C (compiled in)  [nothing else at run time]
 front ends ---> core ---> module (generated) ---> runtime          (never upward)
```

## Rules that hold the shape

1. **Run an unmodified module.** A feature that needs the user to patch sources is a gap.
2. **No run-time dependency of a built module on wasmext or fusedwasi.**
3. **One logic, in the core; the front ends only convert.** A new feature is written once; each front end adds the conversion of its values.
4. **The core knows no Python.** It takes *retain/release*, *host call* and *describe error* from the front end.
5. **The state of the host never crosses artifacts.** What crosses is a versioned record of function pointers (`abi`, `floor`, `size`).
6. **The store owns its members until `close`;** a lazy collector is a later addition, not a requirement.
7. **No guessing the host from names:** the `host` setting says what answers the imports.
8. **A feature the engine or the target cannot do is refused with a message, not faked.**

## How we get there: by results, not by moving code (proposed, 2026-10-28)

The owner's objection to the plan so far: moving lines of code from one file to another gives no result. So **no cleanup stands alone.** Each step below ends with something a user can do and a test that shows it; the logic it needs is written **once, in the core**, and the same copies in the front ends are deleted **in the same change**. That is the whole of the "thin glue" work, done in the order of what it unlocks.

| Result | What a user can do at the end | What is built in the core, and what is deleted from the front ends in the same step | Shown by |
| --- | --- | --- | --- |
| **R1. Functions travel between instances and front ends** | pass a function (a `funcref`) as an argument and as a table element; put a Python function in a table; call a function of another instance, from the extension or from ctypes, in any pair, with no `Trap` | the registry of owners, `table_set` and its rules, `Function`, the one trap/error table, the host-error cell, the one rule for the GIL; delete: `writers`, `refs`, `_pending`, the copies of the table rules and of the trap map | `test_a_python_callback_in_a_table_function` (now `xfail`) passes on all pairs; `examples/plugins` and `link` use it |
| **R2. `externref`** | pass a Python object through a module and get the same object back | the arena owns it; a Python object is an owner handle with retain/release | a small example in `plugins` |
| **R3. Exceptions of WebAssembly with one identity** | catch a tag thrown in one instance in another, in a store | tags in the store | tests of tags across instances |
| **R4. One store for modules built apart** | `link`: `_app` and `_counter` in one store instead of linked by hand | the versioned record `wasmext_store` (C7) | the example `link` |
| **R5. py-wasmhost with the same store** | the same program on wasmtime, wasm3 and a JS engine with one API for values that cross | the store of wasmhost, in Python, after R1-R4 | its `ROADMAP.md` table, item by item |

**What this does to the thin-glue plan.** The standalone "stage 2" (rules and messages once, the thin Store) is **not a step of its own**: the parts R1 needs (the rules of `table_set`, the error map, the host-error cell) are built inside R1; the thin `Store` configuration is built the first time a result needs the executable or the wrapper to make a store through the API (R1 already does for the wrapper). Stage 1 (done on the branch `thin-glue`) stays as the safe base: it cut the repeats inside the templates and found where the audits were wrong.

**The measure of "thin" is not lines.** It is: *for each rule of the table above, how many places write it.* After R1 that number is **one** for table rules, errors and ownership; after the rest it is one for everything on the list.
