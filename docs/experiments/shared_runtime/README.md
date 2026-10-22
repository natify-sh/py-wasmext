# One runtime for modules built apart: an experiment (master, slave and dual)

Checks whether the idea of [../../shared_runtime_concept.md](../../shared_runtime_concept.md) is **possible**: modules built separately run on the runtime of wasm2c of **one** of them, which is handed over through a capsule. **[run]** 2026-10-22, Linux x86-64, gcc 13, CPython 3.11, wasm2c 1.0.42.
Nothing here is a part of wasmext: the generated Python layer of each module is patched by `patch.py` after `wasmext natify --share-tables` has written it, and the modules are compiled by `build.sh`.

```sh
WORK=/tmp/x PY=/path/to/python PROJECT=/path/to/py-wasmext FT_WASM=ft.wasm EX_WASM=ex.wasm ./build.sh   # ft.wat and ex.wat are here and in ../free_threading
python run.py        # in $WORK: the checks of master and slaves
python run_dual.py d1 d2     # more orders of import, see its docstring
```

## The surface of the runtime that the generated code needs **[run]**

`nm -u` on the objects of the C of wasm2c and of the glue of wasmext (the runtime files left out): in the default configuration (guard pages for memory, the handler of signals, the stack of entries of `wasmext_traps`) the code needs **only functions of the runtime and no variable of it**:

| Module | Functions |
| --- | --- |
| small (calls, a memory, a table) | 12: `init`, `init_thread`, `free_thread`, `is_initialized`, `trap`, `strerror`, `allocate_memory`, `free_memory`, `allocate_funcref_table`, `grow_funcref_table`, `free_funcref_table`, `set_unwind_target` |
| kitchen sink of the tests | 10 of those |
| with `memory.grow`, `table.grow` of funcref and externref, `throw`/`catch` | **23**: the above plus `grow_memory`, the three externref ones, `get_unwind_target`, `load_exception`, `throw`, `exception`, `exception_size`, `exception_tag` |

The thread-local variables (`g_wasm_rt_jmp_buf`, `wasm_rt_call_stack_depth`, the exception being thrown) are **behind these functions** in this configuration. They would be named by the generated code only with `WASM_RT_STACK_DEPTH_COUNT` (the counter of depth), the segue registers (clang, a flag), or the entry that does not use the shared stack. Not tried with them.

## 1. Master and pure slave (`ft` has the runtime; `ft2` and `ex` have none)

The master publishes a table of its functions (`shared_rt.h`, `rt_vtable`: a size, the layout fingerprint `WASMEXT_RUNTIME`, 23 function pointers and an idempotent `thread_ready`) in a capsule in the dict of the interpreter state. A slave is compiled and linked **with no file of the runtime**; `slave_shim.c` defines the 23 functions as forwarders to the table. `run.py`:

- **it works:** values; `memory.grow`; `table.grow` of both kinds; `throw` and `catch` inside a slave and an exception nothing catches (a `Trap` for Python); a **trap by a signal in the master and in each slave** (out of bounds past the guard pages, stack overflow on the alternate stack, `unreachable`): all `Trap`, where two modules with a runtime each aborted the one imported first;
  six worker threads that overflow and go out of bounds in `ft2`, `ft` and `ex`: all `Trap`, each thread set up once by the master;
- **speed:** the same: `add` 6.4M/s in the master and 6.6M/s in the slave, `work(1000)` 0.46M/s and 0.48M/s (the runtime functions are not on the hot path: the accesses to memory are inline in the C);
- a slave with **no master** does not import: `ImportError: shared runtime: no master module is loaded` (a pure slave has no runtime of its own to fall back to).

## 2. Dual modules: a runtime of its own **and** the forwarders (`d1`, `d2`, `d3`)

A dual module is what the concept asks for: it **contains its runtime** (compiled with the 23 names changed to `own_*`) and the forwarders, which choose by a pointer: the table of a master if the module attached to one, else `own_*`. At import: a compatible capsule is found, so it attaches; none, so it becomes the master and publishes its own table. `run_dual.py`:

| Order | Result |
| --- | --- |
| `d1 d2` and `d2 d1` | **both orders work**: the first is the master, the second attaches; signal traps in both, and in a worker thread |
| `d1 ft2 ex` | a dual master with two pure slaves: all trap correctly |
| `d1 d3`, `d3` built for another runtime (another fingerprint) | **the import of `d3` fails** with the message that wasmext already gives to a module that shares tables (`built with another runtime of wasm2c`), **and then the process aborts at the first trap of `d1` by a signal** (see below) |

## What the last row shows: the fall-back to its own runtime is **not harmless**

`d3` did not attach, so it started its own runtime, and **`wasm_rt_init` of that runtime replaced the handler of SIGSEGV of the process** (checked: the address of the handler is another one after the failed import). The handler is the process's, and every runtime installs its own without chaining, so a module that works on its own runtime
**breaks the signal traps of every module that is attached to the master**, whether it was imported or not (here the import failed after the damage). That is the same fault as the one that started this (two modules, one process), now between a master and a module that could not join. So the "fall-back to its own runtime" of the idea
works for traps by `unreachable` and for the module itself, and **a module on a runtime of another kind must not install a handler that competes**; either the handler is installed only by the first and the others skip it (`WASM_RT_SKIP_SIGNAL_RECOVERY` and a handler of our own, which
goes to the shared stack of entries), or handlers are chained.

## What was learnt

1. **It is possible.** Modules built apart run on one runtime handed over through a capsule, with all the features tried (memory growth, both kinds of table growth, exceptions, traps by signals, threads), with no change of speed, in either order of import, and with pure slaves that have no runtime at all.
2. **The thread-local state was not the obstacle** it looked like: in this configuration it is behind functions, which is what a table of functions can carry.
3. **The fall-back to a runtime of its own needs the handler of signals to be decided by one party.** Without that, autonomy (a module that cannot attach) takes the handler from the master.
4. **A smaller contract may be enough for the traps** (not tried): `WASM_RT_SKIP_SIGNAL_RECOVERY` in every copy, **one** handler of ours installed by the first module that loads, which turns the signal into `wasmext_traps->trap` of the stack of entries; every runtime already routes `wasm_rt_trap` to that stack. Then modules of any runtime version could coexist for traps with no table of the whole runtime;
   the table would only be needed for what else is to be shared (one registry of tags, one setup of a thread).
5. **Not covered here:** other configurations (depth counting, segue, memory64, shared memory, custom page sizes add functions and some variables), macOS and Windows (a vectored handler for each module), free-threaded builds and concurrent imports (who is the master), subinterpreters, a C host without a capsule, the limit of 64 runtimes (the slaves here still `join` the stack of entries, so they count; a real slave would not),
   the survival of the master (here the slave keeps no reference to it: the capsule has no destructor and the module is never unloaded), and the layout fingerprint (`WASMEXT_RUNTIME`) as the only check of "the same runtime".
