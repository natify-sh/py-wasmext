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

## 3. One handler of signals for the process (`e1` .. `e5`; `one_handler.h`, `no_sigaction.h`)

The candidate that the conclusion of [../../shared_runtime_concept.md](../../shared_runtime_concept.md) names: **no runtime installs a handler; the first module installs one for the process, which turns the signal into a trap on the stack of entries of `wasmext_traps`**
(the modules are in the mode `--share-tables`, so that every runtime sends `wasm_rt_trap` to that stack).

**A finding on the way: the stock knobs of `wasm-rt` cannot express it.** `WASM_RT_STACK_EXHAUSTION_HANDLER` (the alternate stack of a thread, which a stack overflow needs) is an `#error` without `WASM_RT_INSTALL_SIGNAL_HANDLER`, and `WASM_RT_SKIP_SIGNAL_RECOVERY` turns that off, so a runtime that "does not install its handler" falls back to **counting the depth** (about 4 times slower on calls inside a module).
Here the call of `sigaction` in the files of the runtime goes to a function that does nothing (`no_sigaction.h`, force-included into those files only), and the one handler is installed by the module in its own file. **A small change in WABT (allow the alternate stack without the installation of the handler, or a hook for it) would make this a flag** and is what a proposal upstream would be.

Results ([run]; `run_dual.py e1 e2` and so on, each in a process of its own):

| Case | Result |
| --- | --- |
| `e1 e2` and `e2 e1` (two modules in the mode, both orders) | **both trap correctly** (out of bounds, stack overflow), also in a worker thread: **the bug of two modules is gone** |
| `e1 e3` (`e3` is built for another runtime and cannot join the stack of entries) | the import of `e3` fails (the message wasmext already gives), **and `e1` still traps correctly afterwards**: no handler was taken (`d3` of section 2, which had its own, broke the master) |
| `e1 e4`, `e4 e1` (`e4`: a module in the shared-stack mode with the default runtime, whose own handler replaces ours) | **works in both orders**: its handler too sends the trap to the shared stack, so it is harmless |
| `e1 e5`, `e5 e1` (`e5`: **a default module of today, not on the shared stack**, with a handler of its own) | **the process aborts in both orders** ("WebAssembly code trapped outside any call into a module") |

So the one handler **works for every module that takes part, whichever runtime version it has** (as long as it can join the stack of entries and installs no handler that goes elsewhere), and it **cannot protect against a module that does not take part**:
wheels built before this change, or other wasm2c-based packages, break the arrangement exactly as two default modules break each other today (no regression, no repair). Also seen: a thread that runs several modules prints "alternate stack was modified unexpectedly" at its end in a debug build (one `sigaltstack` for a thread, one allocation per runtime copy), as before.
Not measured here: the cost per call of the full stack of entries with many modules (the loop over runtimes, and the limit of 64, are those of `--share-tables`: the light `push`/`pop` is still to be built).

## 4. A chain of handlers (`c1`, `c2`; `chain_handler.h`)

Every module has a runtime of its own and **no capsule, no shared stack of entries**. Each module installs a handler at its import **and keeps the one that was there**. The entry of every call of the module sets a thread-local mark `chain_active_` (saved and restored around the call, and also on the path of a trap: `patch.py`).
When a fault comes: if the mark of this module is up in this thread, **the module's own runtime turns it into its own trap**; if not, the fault is **given to the handler that was before** (called as it was installed: with `siginfo`, or the plain one, or the default action). As in section 3 the runtime of the module is not allowed to install a handler of its own (`no_sigaction.h`: the stock knobs cannot say "the alternate stack, but no handler").

**A pitfall found: the handler must not use lazy binding or general-dynamic TLS.** The first version **hung** (a handler spinning in `__tls_get_addr@plt`, 97 % CPU) when a fault in the first module went through the handler of the second. **Either** `-Wl,-z,now` **or** `-ftls-model=initial-exec` alone removes it (checked separately). The handler of a module that is linked as a shared object touches a thread-local variable, which is not safe in
a signal handler the usual way; the build has to make it so.

Results ([run]; `run_dual.py` in a process of its own each; the three builds have `-z now` and `initial-exec`):

| Case | Result |
| --- | --- |
| `c1 c2` and `c2 c1` | **both orders work**: a trap by a signal (out of bounds, stack overflow) in **each** module, also in a worker thread; the first module, behind the second in the chain, included |
| `e5 c1` (`e5`: a default module of today, imported **before**) | **works**: `c1` kept the handler of `e5`, and the fault in `e5` reaches it through the chain |
| `c1 e5` (the default module imported **after**) | **aborts**: it replaces the handler and does not chain (this is the one fault that the chain cannot repair; a module that does not take part and is imported last) |
| a **real** fault outside any WebAssembly code (`ctypes.string_at(0)`), `-X faulthandler`, `c1 c2` loaded | **`Fatal Python error: Segmentation fault`**, exit 139: the fault reaches `faulthandler` (or the default action) as if the modules were not there |
| the same with a **default module of today** (`e5`) loaded | **`Fatal Python error: Aborted`**, exit 134: its handler turns **any** SIGSEGV of the process into a trap of its own runtime and jumps to a buffer that is not set |
| speed (`add`, `work(1000)`, a call-heavy `fib`) | the same as a default module, within the noise of the machine |

Not tried: a call from a module into another through a host function (a nested call), where both marks are up and the order of the chain decides which entry the trap goes to (an **innermost** entry needs the order that the shared stack gives); macOS (SIGBUS, `sigsetjmp` with the mask) and Windows (vectored handlers); free-threaded builds; the cost of the entry on a C host with no Python (the mark is in the glue of any front end).
