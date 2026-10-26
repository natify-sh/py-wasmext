# Tables between instances, and the `Table` class: a plan

Status: **steps 0, 1 and 2 are built** (the spike; `funcref` tables exported by one instance and imported by another, in the extension, the wrapper for ctypes and the C API of the library). **Step 3, the `Table` class that the glue makes, is built** (3a to 3e: the glue, the extension, the wrapper for ctypes, the C API, the elements). The first version of this plan asked for an object of the package `wasmext` here, which is wrong (see "The principle"), and a short-lived replacement ("a module that only declares the table") did not give what is wanted either. What is marked *checked* was read in the code or run (`wasm2c` 1.0.42 from the wabt-package, the C of `wasmext`); the rest is reasoning.

## The principle

wasmext is a compiler: what a built module holds is decided when it is built, and it needs nothing of `wasmext` when it runs (DESIGN.md). So the `Table` of this plan is **not** a class of the package `wasmext`. It is a class that **the glue of each module generates**, as it generates `Instance`, `Trap` and `LinkError`: the common glue (`wasmext_glue.h`, no Python) has the operations, the glue of the module (`<name>_glue.h`) the typed access, and the Python glue (`<name>_py.c`, or the wrapper for ctypes) the type. Python gets a `Table` **from the extension or from the wrapper**, never from `wasmext`. Two modules share one table the way they share every other export: a record `wasmext_export` carried by the capsule `wasmext.export.v<X>` (the kind `WASMEXT_TABLE`); a `Table` of one extension is accepted as an import by another because it gives that capsule (`__wasmext_ref__`), not because they have a class in common.

## What is wanted

For `funcref` tables:

1. instance **B imports a table that instance A exports** (the same table: a write by one is seen by the other, `table.grow` too);
2. instance **B fills a table of A** with its own functions (the pattern of dynamic linking: a main module exports its table, a side module imports it and its `elem` segments put the side module's functions there);
3. a **`Table` object with no module behind it**: `Table(initial, maximum)` from the extension (or the wrapper for ctypes), imported by modules like any export, with `size` and `grow`, and later its elements.

Not in this plan: `externref` tables (that is "References": who owns an `externref`), tables with an initialiser expression (typed function references: `wasm2c` does not do them), `table64`, threads (shared tables).

## What there is today (built)

- *Checked.* The record `wasmext_export` has the kind `WASMEXT_TABLE = 1`; `type` is `sizeof(wasm_rt_funcref_table_t)`; `address` is the table. `_gen.py` links an imported table (`<name>_link_table<j>`: kind, size, limits, `LinkError` with the reason), exports a table the module defines (`instance["name"]`, a capsule), and undoes what a failed instantiation wrote (`<name>_scrub_tables`).
- *Checked.* The fingerprint `WASMEXT_RUNTIME` covers the memory, `wasm_rt_funcref_t`, `wasm_rt_funcref_table_t` and the buffer of `longjmp`; `WASMEXT_ABI` stayed 1 then (a whole number, nothing was published; the owner decided). It is now `0xXXYYZZLS` (`0x000001A1`), and the layout of the runtime is checked when a module is built (`WASMEXT_LAYOUT`), not compared when linked ([abi_policy.md](abi_policy.md)).
- *Checked.* A module that shares tables is built with `WASM_RT_TRAP_HANDLER`; every call into it pushes an entry on **one stack shared by all such modules** (the first to load publishes it as the capsule `wasmext.traps.v<X>` in the dictionary of the interpreter; the others join it; it is code of the modules, not of the package `wasmext`), so a trap in a function that came out of another extension reaches the right entry. The C API has `<name>_traps`, `<name>_traps_use`, `<name>_unlink_tables`; the wrapper for ctypes joins through `ctypes.pythonapi`.
- *Checked.* Who keeps what alive: an importer keeps the owner (`owner` in the record); the owner keeps every instance that imported its table, through the method `__wasmext_keep__` and a list `writers` that only a module with an exported table has. In C there is no collector: a host unlinks (`<name>_unlink_tables`) before it frees.
- *Checked.* The wrapper for ctypes gives, for a reference, an object (`_Reference`, with `__wasmext_ref__`) and not a capsule: a capsule is freed wherever its last reference goes, even while an exception is raised, and ctypes refuses to run a Python destructor then.
- Tests: `tests/test_tables.py` (the four pairs of front ends, a C host that links two libraries, the exhaustion of the stack in a subprocess, a module that only declares a table as a provider).
- Built after this was written (3a to 3e): `Table` with `size`, `maximum`, `grow`, `get`, `set`, `len`; `instance["tab"]` is a `Table`.

## What `wasm2c` gives

*Checked*, with a module that imports `env.tab` and exports its own table `own`:

- an **imported** table is a field of the instance, `wasm_rt_funcref_table_t *w2c_env_tab;`, and a function the host provides,
  `wasm_rt_funcref_table_t *w2c_env_tab(struct w2c_env *)`; the limits the module needs are the constants `wasm2c_t_min_env_tab`
  and `wasm2c_t_max_env_tab`;
- an **exported** table is reached by `wasm_rt_funcref_table_t *w2c_t_own(w2c_t *instance)`;
- the table is `{ wasm_rt_funcref_t *data; uint32_t max_size; uint32_t size; }`, an element is
  `{ func_type; func; func_tailcallee; module_instance }`;
- `call_indirect` compares the type of the element with the type the code expects, by the pointer first and by a 256-bit hash
  (`memcmp`) if the pointers differ. So an element made by another module is accepted when the type is the same, and a wrong type is a trap.

## The hard part: a trap in a function that came out of another extension

*Checked in the code, and shown to fail by the spike (below).* Each extension has **its own copy of the runtime** (`<name>_rt_impl.c`, and so its own
`g_wasm_rt_jmp_buf`), and a trap is `wasm_rt_trap` → `longjmp` to that copy's buffer, which `WASMEXT_ENTER_*` sets when a call enters
the module. Linked **functions** are safe today because the importer calls the exporter's typed function `<name>_call<i>`, which enters
the exporter (its own buffer) and answers a trap code that the importer turns into its own trap (`TRAP_LINKED`).

A table has no such step: B runs `call_indirect` and jumps to the `func` of an element, which is A's raw function. If A's function
traps there, it longjmps to **A's** buffer, which A did not set for this call (stale or empty). The same is true of the call-depth
counter and of the unwind target of exceptions. So raw pointers of another extension in a shared table are, as it stands, not safe.

Ways out, to choose by the spike:

| | Idea | Cost |
|---|---|---|
| a | The element that crosses the boundary is a **trampoline** in the exporter: `func` points to a wrapper that enters A, calls the real function and answers the trap code; B's side turns it into B's trap. | A wrapper for every function that can go into a foreign table (the ones in `elem` segments, and every `ref.func`); the type of the element must stay the real one. |
| b | The runtimes **share the state of the trap** (one buffer and one depth counter for the process, found through a symbol or a capsule). | Changes the way the runtime is built; the runtime is no longer copied unchanged. |
| c | A shared table only between modules **of the same extension** (several modules in one `.so`). | Not what is wanted. |
| d | Allow tables **only for a table whose elements are all made by its owner**, and refuse a write by another instance (case 2). | Gives up the pattern that matters most. **Ruled out by the owner** (see "Decisions"). |

The spike (step 0, done) chose (b) in the form of a **trap handler that goes to the innermost entry** (below).

## Step 0: the spike (done)

Two modules by hand, `a.wat` (exports a table of 4 with `ok` and `bad = unreachable` in slots 0 and 1, and its own `call`) and `b.wat` (imports
the table, `call(i)` is `call_indirect`), turned to C by `wasm2c` 1.0.42, each compiled with **its own copy** of `wasm-rt-impl.c` into its own
shared library, loaded by a small C program with `dlopen(RTLD_LOCAL)` (as Python loads extensions); B is given A's table as `w2c_env_tab`.
Linux x86-64, gcc. Run, not only read:

1. **A call through the table works** when nothing traps: B calls A's slot 0 and gets 5.
2. **The two copies of the runtime are two runtimes**: the addresses of `g_wasm_rt_jmp_buf` differ (and are the same if both libraries are
   loaded `RTLD_GLOBAL`, where the dynamic linker merges the symbols; Python does not load extensions so, and Windows has no such merging).
3. **A trap in A's function called by B is undefined behaviour with the stock runtime.** `wasm_rt_trap` of A's copy `longjmp`s to A's
   buffer, which was set by an earlier call of A or by none:
   - A had never been entered: `*** longjmp causes uninitialized stack frame ***`, the process aborts;
   - A had been entered earlier from a deeper place in the stack: the same abort;
   - A had been entered earlier from **the same depth** of the stack as B's call: it "works" (the code 5 comes back), by luck, because the
     dead frame lies where B's frame is. That is the case that would pass a careless test.
4. **A trap handler that goes to the innermost entry fixes it.** `WASM_RT_TRAP_HANDLER` is a macro of the runtime that replaces the `longjmp`
   of `wasm_rt_trap` by a call of a function. Both libraries are built with a handler that calls one function given to them by the host (here a
   program). That function
   keeps a stack of the buffers of the entries (each `WASMEXT_ENTER` pushes its buffer, the end of the call pops it) and jumps to the top one. The same
   test: slot 0 gives 5, slot 1 comes back to B's entry as the trap code 5, and a call after the trap works.

### The rest of the spike (also run)

Same setup, a second pair of modules where A also has a memory, a host function (an import of A that traps with the code 77) and
`rec` (infinite recursion), and B writes its own functions into A's table with an `elem` segment (case 2). Both libraries built with the trap
handler of 4 and the default configuration of the runtime on Linux x86-64 (guard pages, the stack exhausted by the signal on an alternate stack):

| Case, called by B through A's table (or by A for a slot B wrote) | Result |
|---|---|
| a function of B, written into A's table, called by A and by B | works; the type is accepted across modules (the check is by the 256-bit hash, not by the pointer) |
| `unreachable` in A | trap 5, as it should be |
| a load out of bounds in A (guard pages, a `SIGSEGV`) | trap 1 (OOB): the handler of the signal that the last `wasm_rt_init` installed belongs to the other copy, and still goes through the shared handler to the right entry |
| a host function of A that traps | trap 77 |
| infinite recursion in A (stack exhausted by the signal) | trap 10 (exhaustion), and the next calls work |
| mutual recursion A.ping → B.pong → A.ping through the table | trap 10, the next calls into A and B work |
| unload B (`dlclose`) while A's table still holds B's function, then A calls it | **segmentation fault**: the writers must be kept alive (the rule in "Design") |
| an uncaught `throw` in A, called by B; the entry sets only B's unwind target | wrong code (10, exhaustion): A's own unwind target is empty and its dereference is caught as a stack signal |
| the same, the entry sets the unwind target of **every** copy of the runtime | trap 8 (uncaught exception), as it should be |
| `return_call_indirect` of B into a plain function of A | works |
| `return_call_indirect` of B into a function of A that itself does `return_call_indirect` to a plain function | **wrong value** (garbage, 255 when 5 is expected) |

The last row is **not about tables between instances**: the same wrong value comes out of **one** module with no sharing at all
(`wasm2c` 1.0.42, `return_call_indirect` to a function whose own `return_call_indirect` goes to a function that has no tail variant: its
result is not put into the tail-call stack). It is a bug of `wasm2c` next to the one in [FEATURES.md](FEATURES.md) (#2884), found on the way; reported as [WABT #2893](https://github.com/WebAssembly/wabt/issues/2893), fixed by [PR #2900](https://github.com/WebAssembly/wabt/pull/2900) (merged into `main` of WABT on 2026-10-26 as `f1c4e05`, not in a release yet); wasmext repairs the C meanwhile (`_tail_call_result`).

What follows for the design: the entry must set the unwind target of every copy of the runtime (the stack of entries that the modules share keeps the list of the
setters that each module gives when it joins), not only the buffer of the trap.

Not run: macOS and Windows; the configurations of the runtime that count the depth of the stack (`WASM_RT_STACK_DEPTH_COUNT`; each copy
has its own counter, which a trap in the other copy does not reset); a `catch` in B of an exception thrown in A (that needs shared
tags: the identity of a tag and the active exception belong to one copy, so it is not possible before tags are linked); threads; a Python callable as the
host function (only a C function that traps stands for it); the lifetime rule itself (only the failure without it).

**Choice.** (b) in this form. The shared part is **not** in the package `wasmext`: an earlier version of this plan had it there (a function of the package passed at import time as a capsule), which would make `wasmext` a dependency of what it built, against "a built module needs nothing at run time" (DESIGN.md). As built, every product carries the code itself, the first module loaded in a process publishes the stack of entries in the dictionary of the interpreter (capsule `wasmext.traps.v<X>`) and the others join it; the package `wasmext` is not imported. Every module of wasmext is built with `WASM_RT_TRAP_HANDLER` and the `WASMEXT_ENTER_*` macros push and pop
into one shared stack of entries (one per thread), and set (and put back) the unwind target of every copy of the runtime for exceptions. It changes a core piece of the build (the runtime is not what the toolchain gives
unchanged, although its files stay as they are: the handler is a macro), but it is small and it was shown to work. (a), the trampolines,
is not needed. The two ways that gave up the pattern of dynamic linking are out.

## Design of the `Table`

- **Standalone, with no instance.** In the specification a table is an entity of the *store*, not of an instance: an instance holds the address of its tables, an import is the address of a table that exists already, and the host can make a table by itself (`table_alloc`; `new WebAssembly.Table` in the JavaScript API). `wasm2c` is the one that puts the table of a module into the structure of its instance, so a table *of a module* always has one there. A `Table` is a bare `wasm_rt_funcref_table_t` that the glue allocates itself: `wasm_rt_allocate_funcref_table(&t, initial, max)`, `wasm_rt_grow_funcref_table`, `wasm_rt_free_funcref_table` take no instance (*checked* in `wasm-rt.h`), and an importer only keeps the pointer (the code that links a table reads the kind, `address`, `type` and the limits, and never `e->instance`). So the record of a `Table` has `kind = WASMEXT_TABLE`, `address` the table inside the object, `instance = NULL` and `owner` the `Table` itself.
- **A table of a module is a `Table` too.** `instance["tab"]` returns the `Table` of that table: an object that points at the table inside the instance and has the instance as its owner; it gives the capsule as `__wasmext_ref__`. An import accepts the capsule, a `Table` of any extension or wrapper, and (as every import does) anything that gives the capsule.
- **Layers.**
  - *Common glue* (`wasmext_glue.h`, no Python): `new(initial, max)`, `size`, `grow`, `free`, and, for the elements, `get`/`set` (step 3d). It also holds what the record says of a table.
  - *Glue of the module* (`<name>_glue.h`, no Python): the typed access to the tables the module imports and exports (as now, `link_table`, `scrub_tables`), and the C functions that make a standalone table with this module's runtime.
  - *Python glue* (`<name>_py.c`): the type `Table(initial, maximum=None)` with `size`, `grow(n)`, `__len__`, `__wasmext_ref__`, `__wasmext_keep__`, a finalizer that frees a table it owns; the exports of the module that are tables become `Table`s.
  - *Wrapper for ctypes* and *C API of the library*: the same, over `<name>_table_new`, `<name>_table_size`, `<name>_table_grow`, `<name>_table_free`; the type in the wrapper is the reference object it already has, grown by those methods.
  - *Stub and `inspect`*: the stub names `Table` (and the exported tables as `Table`); `inspect` already names the tables.
- **Who keeps whom.** The owner of a table keeps every instance that imported it, because the parser does not read code and elements, so it cannot tell which ones write. That duty moves from `InstanceObject` to the owner in general: `__wasmext_keep__` and the list `writers` belong to the `Table`; an instance with an exported table keeps its `Table` objects, and the `Table` keeps the importers. An instance that fails to instantiate after it wrote into a table takes back what it wrote (`<name>_scrub_tables`) before it goes.
- **Allocation.** The runtime does not check the allocation of a table (1.0.42: a NULL that the first use trips over; later releases: `abort()`), so the glue tries the same allocation first and a table that cannot be had is a `MemoryError` (as it already does for the tables of a module).
- **The runtime fingerprint.** The structure is allocated by the runtime copy of the module that made the `Table` and used by others: they are compatible if the layout of the runtime is the same, which is checked when a module is built (`WASMEXT_LAYOUT`; it used to be the fingerprint `WASMEXT_RUNTIME` compared at every link).
- **The elements** (step 3d). A `funcref` is `{func_type, func, func_tailcallee, module_instance}`. To write one, the record of an exported **function** has to carry it; today it carries the typed call `<name>_call<i>` that catches a trap, not the raw function. A field appended at the end of `wasmext_export` does it (`size` and `floor` tell a reader). Reading an element gives a callable bound to the instance it belongs to, or `None`.

## Steps

**0. A spike. Done** (above): the choice made; (iii), a freed writer, not run at the time and covered by the tests of step 1.

**1. Imported and exported tables, `funcref`, between extension instances. Built** (`tests/test_tables.py`; Linux; macOS and Windows in CI). `_gen.py`: the link functions, the field, the export kind; `wasmext_glue.h`: the fingerprint and the stack of entries. An instance that imports a table is kept by the *owner*, whether or not it writes into it; one whose instantiation fails takes back what it put in the table.

**2. The library, ctypes, stubs and `inspect`. Built** (`<name>_export_find`, `<name>_link_table_import<j>`, `<name>_traps`, `<name>_traps_use`, `<name>_unlink_tables`; the wrapper joins the stack through the dictionary of the interpreter; the four pairs of front ends and a C host). Found on the way: the reference of the wrapper is an object; the entry saves the signal mask on macOS (`WASMEXT_TRY`).

**2b. An object for the memory. Tried; not done.** `instance.memory` as an object gave a view no cheaper (91 against 132 ns for `memoryview(inst.memory)`), at 79 lines of C for each module with a memory, and broke `.cast()`, slices, `.release()` and `len()`; the criterion (twice as cheap, no more code) was not met, so `instance.memory` stays a `memoryview`. Fast `read`/`write`/`u32` can be added beside it, with names that cannot clash with an export. This is about the memory only and says nothing against the `Table`: a table has no view to keep.

**3. The `Table` class.** 3a to 3e built (`tests/test_table_class.py`: the extension and the wrapper, the cross use of their classes, the C API from a C host, the same members in both and in the `.pyi`, the elements in the four pairs of front ends; `examples/plugins`).
- *3a. Common and module glue:* `new`, `size`, `grow`, `free` over the runtime; a record of a standalone table; the keep-alive duty on the owner in general.
- *3b. Python glue:* the type `Table`; `instance["tab"]` gives it; the imports accept it; the extension's own tests.
- *3c. The wrapper for ctypes and the C API:* `<name>_table_new/size/grow/free`; the wrapper's reference gets the methods.
- *3d. Elements:* `funcref` in the record of an exported function; `Table.get(i)` and `Table.set(i, function)`; a trap in an element reached from Python.
- *3e. Tests* in the four pairs of front ends and the C host: a `Table` imported by a module that fills it with an `elem` segment and by another that calls it; `grow` seen by both; the limits checked; the `Table` freed in each order with its users; the exhaustion of the stack through a `Table`.
*Exit of 3a to 3c:* `Table(4, 8)` imported by two modules, a module fills it, the other calls through it, `size` and `grow` from Python, in all pairs of front ends. *Exit of 3d:* the host writes and reads an element.

**4. Documents.** FEATURES.md (the rows of tables and of the shared global and memory), README ("Linking instances", "Known limitations", the public interface: `Table` among the stable names), DESIGN.md ("A global, memory or table with no code behind it" and "Tables between instances"); this file stays as the record.

**5. A: the option `share_tables`. Built** (asked for in the configuration and in the command line too; `tests/test_natify.py`, `test_cli.py`, `test_pyproject_config.py`, `test_table_class.py`). A module is built with the stack of entries for traps (`WASM_RT_TRAP_HANDLER`, `Glue.trap_handler`) when it asks for it, whether or not it has a table, so that its functions can be put in a table (limit A below). One setting, in every place that builds: `natify(share_tables=True)`, `share-tables = true` in `[[tool.wasmext.ext-modules]]` of `pyproject.toml` (type-checked like the others), `wasmext natify --share-tables` (and `--no-share-tables` to override the file? no: the command line ignores the table of the project, as it does for the other keys), and `wasmimport.install(share_tables=)`. The option is an input of the generated C, so it goes in the digest that decides whether the C is current (a change makes the C again); a module that has a table shares tables whatever the option says. It has the class `Table` (the stub and the wrapper) as any module that shares tables has; the library and the program get the same define (`build_shared`). The refusal of `Table.set` says "build the module with share_tables". *Exit:* a module with no table, built with the option, has its function put in a `Table` and a trap in it comes back to the caller, in the extension and in the wrapper for ctypes; the option changes the C; it is refused (a message) where it makes no sense (a program).

**6. B: the class `Function` (after the `Function` of py-wasmhost). Built** (`tests/test_table_class.py`, `examples/plugins`). `Table.get(i)` gives a `Function` for a slot, also for one that an `elem` segment filled; callable for the types the module of the class declares, found by the hash of the type; equal and hashable by (function, instance); `set` takes it. The design, what is taken from py-wasmhost and what differs, is in "The limits of the elements" below. *Exit:* `get` of a slot filled by an `elem` segment is a `Function` that is called and gives the result, in the four pairs of front ends; a type the module does not declare is told (`signature` is None, a call is a `TypeError`); the same members in the extension, the wrapper and the `.pyi`.

**7. 2: `funcref` in the signature of a function. Built for exports** (`tests/test_table_class.py`: the four pairs of front ends, the stub and the C API; the instance keeps the owners of the functions it was given, `refs`). **Not built:** a `funcref` in an *import* (the Function made for the host function needs an instance to keep alive, and the callable of the host has only its `user` pointer), and a `Function` called with a `funcref` parameter (what the callee keeps cannot be kept alive from here). Both are refused as before (the module, the type). Today an export with a `funcref` or `externref` parameter or result is left out and an import of one refuses the module (FEATURES.md, "Reference types in a signature"). The `funcref` is no longer foreign to the glue: the record of a function export carries its `funcref` and `Table` makes a funcref of an export (`set`) and a function of a funcref (`get`, step 6). So: a `funcref` **parameter** takes a function of an instance (as `Table.set` does) or None; a `funcref` **result** is a `Function` (needs step 6); a `funcref` in an imported function takes the same two ways. `externref` stays open ("References" in FEATURES.md: who owns an `externref`; the idea of one mechanism for the life of references). *Exit:* a `funcref` goes in and out of an export in the four pairs of front ends.

## The limits of the elements (3d), and the ways round them

Found when 3d was built. Written down so that nothing is only in a conversation.

**A. Only a function of a module that shares tables can be put in a table.** A trap in a function that a table calls runs `wasm_rt_trap` of the runtime copy *of that function's module*, which `longjmp`s to a buffer that only a call into that module sets. The stack of entries that fixes it joins the modules that are built with `WASM_RT_TRAP_HANDLER` (a macro of the C of the runtime, defined when the C of the product is compiled; `natify` and `build_shared` define it for a module that imports or exports a funcref table; it is not a flag of `wasm2c` and does not touch the translation of the `.wasm`). A function of any other module in a table is a crash (the first test of 3d aborted the process), so `Table.set` refuses it (bit 4 of the flags of the record). Ways round it:
1. *An option of the build*, `share_tables` (`natify(share_tables=True)`, a key of the table of `pyproject.toml`, `--share-tables`): the module is built with the stack of entries whether or not it has a table. Cheap, explicit, and it is what the message of the refusal should say instead of "give it a table". **Built (step 5).**
2. Build every module that exports a function so: no option, but the cost of the entry in every call of every module (not measured; the entry that guards a reentrant call costs about 5 ns, 13 %, in a measurement of the Python interface).
3. Trampolines in the exporter: not wanted (a call through a table has no way to carry a trap code back).

**B. `Table.get(i)` does not tell a function that an `elem` segment put in the slot.** It looks for an export of the instances that use the table whose function is the element (same function, same instance). `wasm2c` writes its own wrapper of the function into the table for an `elem` segment, not the exported symbol, so the two never compare equal. The reference for the way round is the `Function` of [py-wasmhost](https://github.com/natify-sh/py-wasmhost) (`src/wasmhost/_api.py`, `Function`, `Table`, `_function`): there the engine does not say what a function it found in a table is, so `table.get(i)` gives a `Function` that is one object for one function (found by the key of the function in a cache of weak references, so `table.get(0) is instance.exports.add` when the table holds it), whose `signature` is `None` until it is known (the engine, the module, or set by hand), is called after the signature is known, and a wrong signature given by hand is refused by the engine (a tiny module with a `call_indirect` of exactly that type), not obeyed. What carries over to the glue and what differs:
- *The class.* `get(i)` gives a `Function` (made by the glue of the module, like `Table`, with the same members in the extension, the wrapper for ctypes and the `.pyi`) and not a method of an instance: equal when the function and the instance are the same (`==` and `hash`), callable, with `signature` and `name` (the name of the export if one is found, else None). `set` takes a `Function` too.
- *The signature is not guessed and not set by hand.* wasmhost has to ask the engine or the caller; here the element has its type (`func_type`, the 256-bit hash that `wasm2c` compares in `call_indirect`) and the module that has the class knows the types it declares (`wasm2c<prefix>_get_func_type` returns the hash of a signature the module has): the type of the element is found by comparing hashes, and `signature` is `None` only for a type that the module of the class does not declare. A compiler cannot make a caller at run time (the AOT rule), so a `Function` is callable only for a signature that this module declares; for another it says so (`TypeError`), where wasmhost lets the caller set a type. The check of the type before the call is the hash, as in `call_indirect`, so a wrong type cannot run.
- *The call.* One typed caller in the glue for each type the module declares, `<name>_callref<k>(funcref, parameters..., int *trapped)`, built as the call of an export is (the stack of entries, the trap codes), but through `func` and `module_instance` of the funcref; in the C API `<name>_funcref_type` and `<name>_funcref_call`.
- *What keeps what alive.* A `Function` read from a table keeps the table, and the table keeps every instance that may have put a function in it, so the instance of the function lives as long as the `Function`.
**Built (step 6).** The search of 3d by export stays as the way to give the name. Found by the CI of `examples/plugins`: the name of a function that an `elem` segment put in a table is `None` where the wrapper of `wasm2c` is a function of its own, but where the linker folds identical code (MSVC on x86 and ARM64) the wrapper has the address of the export and the export is found and named; so a test can say that the name is `None` or the export's, and not which.

## Open

- A memory or a global made by the glue in the same way (`Memory(initial, max)`, `Global(type, value)`): the same pattern, not planned here; a module that only declares it works today.
- The cost of a `funcref` crossing from one runtime copy to another: not measured. (Reading the elements as callables is built: step 6.)
- The idea of one mechanism for the life of references and for `externref` (FEATURES.md, "References"): not decided.
- Not run: macOS and Windows beyond CI; the configurations of the runtime that count the depth of the stack (`WASM_RT_STACK_DEPTH_COUNT`); threads; a `catch` in one instance of an exception thrown in another (tags are not linked).

## Not built, and what it would take

Postponed by the owner until there is a consumer or a request. Nothing here is a bug; each is refused with a message as before.

- **`funcref` in an import** (the host function receives or returns a `funcref`), and **a `Function` called with a `funcref` parameter.** Both lack the same thing: from a bare `funcref` (`func`, `module_instance`) there is no way to find the owner that must be kept alive, and the host callable has only its `user` pointer.
  - *The way:* a registry `module_instance` to owner, kept in the glue of the built modules (not in the package `wasmext`), one per interpreter, shared through a capsule in the dictionary of the interpreter as the stack of entries is (`wasmext.owners.v1`); weak, so that it keeps nothing alive; under a lock for a free-threaded build; a plain C structure for a C host. An instance writes itself in at creation and out at its end; whoever receives a bare `funcref` finds the owner and keeps it (in a `Function`, in `refs`).
  - *Host functions:* a function made by the host gets a record `HostFunction` (the callable, the type), which is the `module_instance` of its `funcref`; `func` is a trampoline for the type, made at build time for each type the module declares (the AOT rule: a type the module does not declare cannot be made). The record is registered as an owner, so a host function is not an exception. An exception of the callable becomes a trap, so such a module needs `share_tables`.
- **`externref`.** Waits on the same question as the life of references (see Open): who owns an `externref`.

**Decision: not built on purpose, and refused.** A `funcref` in an import, a `Function` called with a `funcref` parameter and an `externref` stay refused with a message, in the extension, the wrapper for ctypes and the `.pyi`; nothing is passed as a raw pointer. The reasons: a switch for unsafe references would be a permanent part of the interface (what Python sees instead of a `Function`, a `.pyi` that differs by the build), what a raw reference means is settled by the design of the group of instances that share ([context_concept.md](context_concept.md)), and a Python extension is not expected to crash. The safe form is that design, for a later version (beta or stable).

*A switch that stays possible later, only on a request:* an option of the build `--unsafe-refs` (as `share_tables` is: `natify(...)`, the key of `pyproject.toml`, the command line), the same in every module that links, with a bit in the record of an export so that a mismatch is a `LinkError`. The C API is the natural first place, since a C host keeps the lives of things by contract already (`<name>_unlink_tables`): a `funcref` or `externref` as a plain `const void *`. Not built, not designed further.

## Decisions

1. `WASMEXT_ABI` was **not** raised for the tables (it was the whole number 1; the number is now `0xXXYYZZLS`, and the tables belong to the first version, `WASMEXT_SINCE_TABLE`). A field appended to `wasmext_export` does not break a reader either: `size` and `floor` tell it.
2. A **reduced scope is not enough**: case 2 (an instance fills a table of another) is part of the first version, so the problem of a trap in a foreign function and the problem of the lifetime of the writers had to be solved, not avoided. Trampolines, and tables only between modules of one extension, are out.
3. **The type of `instance.memory` does not change**: it stays a `memoryview` (after the experiment of step 2b).
4. **`Table` is made by the glue of the module, not by the package `wasmext`.** Nothing is made by `wasmext` while it runs; the shared stack of entries is code of the built modules. A module that only declares a table works and is not the way to get one.
5. **The exports stay methods** (`instance.add` is a method of the extension, a bound method of the wrapper), not `Function` objects or references: where a reference is wanted (an import, `Table.set`, a `funcref` parameter) the glue finds the export by `__self__.__exports__[__name__]`. Decided by the owner; nothing is planned to change it.
