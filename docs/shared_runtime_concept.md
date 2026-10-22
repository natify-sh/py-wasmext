# One runtime for modules built apart: master and slave (an alternative, to be investigated)

Status: **an idea; a first experiment says it is possible (see "What the first experiment showed" below); not decided, nothing built in wasmext.** Written 2026-10-22 after the finding that two autonomous modules in one process disagree about the one handler of signals
([where_we_stopped_2026-10-22.md](where_we_stopped_2026-10-22.md), "Found and not solved"; `tests/test_two_modules.py`). How a fact is known: **[run]** run here, **[read]** read in sources (WABT `0086e24`, this repository), **[estimate]** a judgement.
The first thing to do with it is **to find out whether it is possible at all**; the list of what to find out is below, and nothing should be built before it is answered.

## The idea

Every module has a **copy of the runtime of wasm2c** compiled into it (`wasm-rt-impl.c` and the others), and each copy acts as if it were the only one: it installs its own handler of signals, keeps its own thread-local state, and knows nothing of the others. That is the autonomy of a module,
and the cause of the trouble where modules meet in one process.

The alternative: **one module is the master and the others are slaves.** The module that loads first publishes its runtime through a capsule (a versioned record with a table of functions and the layout fingerprint, as `wasmext_traps` already does for the stack of entries). A module that loads later **looks
for that capsule and, if the runtime in it is the same one as its own (same layout, same version of the contract), attaches to it**: it calls the master's functions instead of its own. If there is no capsule, or the runtime is not the same, it runs **on its own runtime**, as today. So the modules stay autonomous: nothing is installed, any module works alone, and
sharing happens only when it can, and only between modules that agree. The context ([context_concept.md](context_concept.md)) stays what it is (who may exchange references, who keeps whom alive); this is about the state of the runtime.

## What it would give, if it works

- one handler of signals, one setup of the alternate stack for a thread (the thread capsule would move into the master), one stack of entries for traps: the abort in the module imported first goes away, and a thread that runs several modules leaves no stack behind;
- no per-copy list of unwind targets, so **no limit of 64 modules and no loop over all of them on every call** (the cost of `--share-tables` for every module) **[read]**: with one copy of the state, there is nothing to keep in step;
- a place for the **tags** of exceptions, which are not linked at all now: one registry for the modules that share the runtime;
- a smaller surface than "a runtime as a DLL": the host installs nothing, and a module without a master is still complete.

## What it is not

Not a runtime library that the user has to install (that was refused for good reasons: wheels built apart, `auditwheel` and `delocate` give each wheel a copy of what it links), and not a change of what a module is: the code of the runtime is **still in every module**, only one copy of it is used when they agree.

## The options side by side

| | What | Cost | State |
| --- | --- | --- | --- |
| A | leave it: a known gap | none; a trap by a signal aborts in all but the last module | now (`FEATURES.md`, "Known gaps") |
| B | the stack of entries of `wasmext_traps` for all modules, with a lighter `push`/`pop` for those that share no tables and a fall-back to working alone | two functions added at the end of the record; the fall-back must be written | checked that the full form works with `--share-tables` **[run]**; not built |
| C | a small **record of the process** (handler, alternate stacks, stack of entries) found through a capsule | one record more in the contract | idea ([context_concept.md](context_concept.md)) |
| **D** | **master and slave: the whole runtime through a capsule** (this page) | **the largest: every `wasm_rt_*` the generated code uses goes through a table when attached** | **to investigate** |
| E | `WASM_RT_SKIP_SIGNAL_RECOVERY` in every copy and one handler of ours | a handler of our own; the thread-local state per copy is still not shared | not tried |
| F | no handler at all: `WASM_RT_STACK_DEPTH_COUNT` and bounds checks | about 4 times slower on calls inside a module; a limit counted in frames **[run]** | measured for the stack ([experiments/free_threading/](experiments/free_threading/)) |

B, C and E are steps on the way to D, or smaller answers to the same wound. D is **possibly the best** because it also gives one registry for tags and a single place for the state; it is also the one most likely to turn out impossible or too costly, which is why it comes first in the list of things to find out.

## What has to be found out (in this order)

1. **The surface of the runtime that the generated code touches.** From one small module **[run]**: the C of `wasm2c` and the glue use `wasm_rt_init`, `wasm_rt_init_thread`, `wasm_rt_free_thread`, `wasm_rt_is_initialized`, `wasm_rt_allocate_memory`, `wasm_rt_free_memory`, `wasm_rt_allocate_funcref_table`,
   `wasm_rt_free_funcref_table`, `wasm_rt_trap`, `wasm_rt_strerror`, and, **by name, as variables**, `wasm_rt_call_stack_depth`, `wasm_rt_last_segment_val` and (through the macros of the memory) `wasm_rt_fsgsbase_inst_supported` and the segue base. More appear with other features (grow, externref tables, exceptions:
   `wasm_rt_load_exception`, `wasm_rt_exception_tag`, `wasm_rt_set_unwind_target`, shared memories, the tags). To do: **make the full list for the biggest module and for each feature**, and for each name say whether it is a function that can be redirected by a macro or a variable that cannot.
2. **The thread-local state.** `g_wasm_rt_jmp_buf`, `wasm_rt_call_stack_depth`, `wasm_rt_last_segment_val` are `WASM_RT_THREAD_LOCAL` variables **read and written directly by generated code and macros**; `g_unwind_target` and `g_active_exception*` are static in the exceptions file. A slave cannot reach the master's thread-local variable by name (each shared object has its own).
   Ways to look at: an accessor function of the master that returns the address (a call on every entry), a copy kept in step by the master (what the loop of unwind targets does, which is the cost to avoid), or a rule that these stay per copy and only the entry is shared. **The answer decides whether D is possible with a good speed.**
3. **Whether the layout is the same.** Both sides must agree on `wasm_rt_memory_t`, `wasm_rt_funcref_t`, the tables, `wasm_rt_jmp_buf`, the tags, and on every macro that changes them or the behaviour (`WASM_RT_USE_MMAP`, `WASM_RT_MEMCHECK_*`, the way the stack is checked, `WASM_RT_USE_SEGUE`, `WASM_RT_TRAP_HANDLER`, the build of the glue with `-DWASMEXT_*`).
   wasmext has a fingerprint of the runtime (`WASMEXT_RUNTIME`) and a layout check (`WASMEXT_LAYOUT`); to do: **read what they cover and what they do not** (the file `wasm-rt-impl.c` itself, the version of `wabt-package`, the flags a user puts in `CFLAGS`, as the experiments here did).
4. **What travels in the capsule.** A record with its size and version, the fingerprint of the runtime, and a table of functions that **grows only at its end** (as `wasmext_export` and `wasmext_traps` do); where it is kept (the dict of the interpreter state, as the stack of traps is; a process-wide place is not reachable from Python without a shared symbol); who writes it **and how two modules that import at the same moment in two threads
   agree on who is the master** (a free-threaded build, or the GIL released during an import); what keeps the master alive (a slave holds a reference to the master's module, or to the capsule that holds it); what happens in a subinterpreter (the handler is of the process, the capsule is of the interpreter); the order of the imports (the master is whoever came first, so what the user sees depends on the order: how is that told).
5. **Signals.** Only the master installs the handler; a slave must not install its own (it would call `wasm_rt_init` of its own copy: the attached path must skip it). To check: that the handler of the master finds the entry of the current call of **any** module (the stack of entries), that SIGBUS on macOS, `sigsetjmp` with the mask (`WASMEXT_TRY`), the alternate stack and the guard pages behave as with one module,
   and what Windows does (a vectored handler for each module).
6. **Fall-back and the report to the user.** A slave that cannot attach (another runtime, another version) works alone and **keeps the known bug**; to decide how that is told (a warning at the import? an attribute of the module that says whose runtime it runs on?), so that the behaviour is not a silent function of the order of imports.
7. **Tags and exceptions.** Whether one registry of tags is really possible on top of the runtime (the tags are static data of the module and the glue adds a table of them: `wasmext_tags_*`), and what an exception that crosses from one module to another needs (the unwind target of the other copy).
8. **The cost.** To measure with the benchmarks that exist ([experiments/context_bench/](experiments/context_bench/): a call through the library 23 ns; [experiments/free_threading/](experiments/free_threading/)): the entry and the exit through a table, the access to a thread-local variable of the master, the calls that are not on the hot path (allocation, growth, free); an estimate **[estimate]**: memory accesses are inline and do not call the runtime, so the hot path should not change, but the entry
   of every call does.
9. **The other products.** The shared library, the program and the wrapper for ctypes: a C host has no capsule, so the pointer has to be passed by the host (`<name>_traps_use` is the existing form); the program has one thread and one module. To decide what D means for them (probably nothing, or the same explicit pointer).
10. **The test plan, before any code:** two and many modules in one process, in every order of import; modules built with different flags and with another `wabt-package`; concurrent imports; a thread that runs several modules; a trap by signal in each; the mismatch fall-back; the sanitizers ([.github/workflows/sanitizers.yml](../.github/workflows/sanitizers.yml)); `tests/test_two_modules.py` is the first test and is `xfail(strict)` today.
11. **What WABT could do** that would make this simpler or unnecessary (a vtable for the runtime, a chain to the previous handler, a recognition of the memories of one runtime by address): a proposal for the upstream is to be drafted **after** it is known which of A-F works here, as the owner asked.

## What the first experiment showed ([experiments/shared_runtime/](experiments/shared_runtime/), 2026-10-22 [run])

- **The surface is functions only** in the default configuration: 12 for a small module and 23 with memory and table growth and exceptions; **no variable of the runtime** is named by the generated code (point 1 and 2 above: the thread-local state is behind functions). Depth counting, the segue registers and
  the entry that does not use the shared stack would add variables; not tried.
- **Master and slave work through a capsule with a table of functions**: a slave linked with **no file of the runtime** runs values, `memory.grow`, both kinds of `table.grow`, exceptions, traps by signals (out of bounds, stack overflow), threads, at the same speed as the master; a pure slave with no master does not import.
- **Dual modules** (a runtime of their own, renamed `own_*`, and forwarders that choose; the first becomes the master, a later one attaches) work **in both orders of import**, with pure slaves alongside.
- **The fall-back to its own runtime is not harmless** (point 6 above): a module that could not attach, and ran the `wasm_rt_init` of its own runtime, **replaced the handler of SIGSEGV of the process** and the master's traps by signals then aborted the process. The handler has to be decided by one party: either only the first module installs it (the others built with
  `WASM_RT_SKIP_SIGNAL_RECOVERY`, and a handler of ours that goes to the stack of entries), or handlers are chained.
- **So the traps may need a smaller contract than the whole runtime** (a hypothesis, not tried): one handler of ours plus the stack of entries that every runtime already routes `wasm_rt_trap` to. The table of the whole runtime would then be for what else is shared (a registry of tags, one setup of a thread, one place for the state), not for traps.
- Still open from the list: concurrent imports (who is the master), subinterpreters, macOS and Windows, other configurations, the limit of 64 runtimes for slaves that still join the stack, the lifetime of the master, how the fall-back is told to the user, a C host without a capsule, and what the layout fingerprint does not cover.

## Conclusion of 2026-10-22: which concept is the most native with the autonomy kept (a judgement from what was tried)

**The most promising, and the one the experiments point to as the common core: one handler of signals for the process, installed by the first module that loads (every copy of the runtime built with `WASM_RT_SKIP_SIGNAL_RECOVERY`), which turns the signal into `wasmext_traps->trap` of the stack of entries that every runtime already routes `wasm_rt_trap` to,
plus the per-thread setup of the Python layer (done).** It is *not tried yet*; it is what the experiments make necessary, and it asks the least:
- **autonomy:** every module keeps its own copy of the runtime and runs alone; the first module installs the handler, so one is enough, and modules of **other runtime versions coexist** (they do not install a handler that competes, which is what broke the master in the experiment);
- **native:** it uses knobs that `wasm-rt` already has (`WASM_RT_SKIP_SIGNAL_RECOVERY`, `WASM_RT_TRAP_HANDLER`) and the stack of entries that `wasmext_traps` already is; no symbol tricks, no renaming, no table of the whole runtime;
- **the contract** is small and versioned (the handler, the stack of entries), found through the same kind of capsule `wasmext_traps` already uses; a light `push`/`pop` for modules that share no tables is needed so that the cost does not grow with the number of modules (and the limit of 64 goes away for them).

| Concept | Tried? | Verdict |
| --- | --- | --- |
| Thread setup by a capsule in the thread state (the fix) | **done**, tested | needed by every other choice; keep |
| `--share-tables` (the full stack of entries) for all modules | **run** with two modules: works | the loop over all runtimes and the limit of 64 rule it out as it is |
| **One handler of ours + `SKIP_SIGNAL_RECOVERY` + the (light) stack of entries** | **not tried** | **the best candidate; the next experiment** |
| Master and slave, the whole runtime through a capsule (this page) | **run**: possible, same speed, both orders of import, pure slaves | heavier than the traps need; its fall-back **steals the handler** unless the handler is decided by one party, which is the candidate above; keep for what else is to be shared (one registry of tags) |
| A record of the process | idea | the candidate above is its practical form |
| `WASM_RT_STACK_DEPTH_COUNT` (no handler for the stack) | **run** | about 4 times slower on calls inside a module; a limit counted in frames: an option, not the default |
| Weak symbols or symbol interposition instead of a capsule | read, not run | no on macOS and Windows, no check of compatibility before the binding, hijacks other packages' runtimes; no speed gain (the forwarders cost nothing measurable) |
| The context (a registry, explicit, bound at creation) | idea; measured costs | orthogonal: it is about who may exchange references, not about the OS resources; stays as designed |

**Update (same day): the candidate was tried** ([experiments/shared_runtime/](experiments/shared_runtime/), section 3): it **works for every module that takes part**, whichever runtime version (two modules in both orders; a module of another runtime that cannot join does not take the handler; a module with a handler of its own that goes to the same stack is harmless), and **a default module of today, which does not take part, breaks it in both orders**. And the stock knobs of
`wasm-rt` **cannot express it** (the alternate stack of a thread needs the runtime's own handler; `SKIP_SIGNAL_RECOVERY` falls back to depth counting): the experiment redirected `sigaction` in the files of the runtime to a no-op; a small change in WABT would make it a flag.

What is **not** known: whether the candidate works on macOS and Windows (a vectored handler there), with a free-threaded build, with a C host that has no capsule, and with subinterpreters. It is a hypothesis until `tests/test_two_modules.py` (the `xfail(strict)` test) passes on it.

## Opting out: a module with the same runtime that does not join (a requirement, not yet met by anything tried)

A module whose runtime is the same as the master's can still be wanted **alone**: for isolation (a module that must not share anything), for debugging, or because it is built another way. What each concept gives (a judgement; none of this opt-out was tried):

| Concept | Can a module with the same runtime stay out? |
| --- | --- |
| Master and slave, dual module (run) | **yes, as a choice at the attach** (a setting of the build, of the import or of the context: "own runtime"), the pointer simply stays empty. **But** the runtime of such a module installs its own handler of signals and, as the experiment showed, **takes it from the others** |
| One handler of ours + the (light) stack of entries (the candidate, not tried) | the handler is **one for the process by nature**, so "out" can only mean "not on the shared stack of entries"; its signals would then have no entry to go to (a trap outside any call: abort) unless it keeps a handler that **chains** |
| The context | **orthogonal**: it keeps references apart, not the handler of signals or the stacks of the OS; two contexts share one process handler |
| `WASM_RT_STACK_DEPTH_COUNT` (run) | **yes, naturally**: a module built so (and with its memory checked by bounds, not guard pages) needs **no handler at all**, so it cannot take one and does not need the shared ones; the price is the speed on calls inside it (about 4 times, measured) |
| Weak symbols | **no**: the binding is made at load for the whole process |

So an opt-out that does not harm the others needs one of two things: **a handler that chains** (each runtime saves the previous handler and gives it the signal when the fault is not in its own code, which needs a way to say "this thread is now inside my module": a thread-local mark set by the entry of the module; and, for memory, the addresses of its own memories),
or **a mode with no handler** (depth counting, bounds checks). Chaining is also what a proposal to WABT would be about. **A requirement for the design:** an explicit, documented setting "this module runs on its own runtime", whose behaviour toward the others is stated (it must not take the handler).

## How to choose

If 1 and 2 show that the thread-local state can be reached cheaply (or can stay per copy with only the entry shared), D is possible and is likely the best answer to the whole class of problems (signals, stacks, threads, tags). If not, **B** (the light entry on the existing stack of traps, with a fall-back) is the smaller answer to the wound that hurts now, and D stays an idea. Either way
the thread capsule of the Python layer stays: it sets up and gives back the alternate stack of a thread, which any of these needs.
