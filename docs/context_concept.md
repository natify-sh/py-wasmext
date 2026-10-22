# The context: a group of instances that share (a concept)

Status: **an idea, not built, not decided.** Nothing here is in the code. It is written down so that it is not only in a conversation, and for the day a consumer asks for what it would give (see "What it would give"). The first form of the idea was a *domain* that instances join and leave (`attach`/`detach`); it is kept at the end as considered and replaced. The word *store* is not used: in wasmtime and the component model it means a runtime with an engine, and this is not that.

## The problem it answers

Two modules built apart share nothing by default: each is a self-contained extension, shared library or program with its own copy of the wasm2c runtime, and nothing of `wasmext` is needed when it runs. That isolation is wanted. What is shared is shared on purpose: a `funcref` table, a memory, a global (see TABLES_PLAN.md).

Sharing works today through chains of keep-alive: a table's owner keeps the instances that import it, a standalone `Table` keeps its writers, a `Function` keeps the table it came from, an instance keeps the owners of the functions it was given (`refs`). That is enough for what is built. It is not enough for what is postponed (TABLES_PLAN.md, "Not built"):

- a `funcref` in the signature of an **import**, and a `Function` called with a `funcref` **parameter**: from a bare `funcref` (`func`, `func_type`, `module_instance`) there is no way to find the owner that has to be kept alive;
- an `externref`: nobody says who owns the object behind it;
- the **tags** of the exceptions: not linked at all.

All three lack one thing: a place that knows who belongs together, and that outlives each member.

## The idea

A **context** is a small structure with an interface, compiled into every module, that holds the instances (and standalone tables, and the functions made by the host) that are allowed to exchange references.

- It is **not a runtime**. It has no engine, compiles nothing, runs nothing. It is a registry and a list of members with a duty to keep them alive. Each module still has its own copy of the wasm2c runtime.
- It is **explicit**, and a member is **bound to it when it is made**, not joined later:
  ```python
  with Context() as ctx:
      a = a_mod.Instance(context=ctx)
      b = b_mod.Instance({"env": a}, context=ctx)
      t = a_mod.Table(4, 8, context=ctx)
  ```
  `Instance` is the class of a module (`a_mod.Instance`), and a context knows nothing of modules, so the context is an argument of the constructor and not a factory (`ctx.Instance(...)` could not tell which module to make). A standalone `Table` takes the context the same way. A `Function` belongs to the context of its owner and only reads it.
- **Without a context argument an instance gets a private context**, made for it and closed with it. An instance that shares nothing is used as it is today.
- **Not in the same context, no exchange.** A table, a function or a global of one context is refused in another (a `LinkError`). Linking `Instance({"env": a})` needs `a` in the same context, else a `LinkError` that says so. There is no ambient "current context" (no `contextvars`): nothing joins by itself.
- **There can be many contexts**, and `with Context() as a, Context() as b:` gives two isolated worlds (a tenant, a request, a set of plugins). One context for everything is the common case, not a rule.
- **A member never leaves.** The members of a context only grow until it is closed. There is no `detach`.

The name `Context` is the working one (`SharedContext`, `DomainContext` were named; the word "shared" would mislead, since a private context is a context too).

## Closing

A context is closed by leaving the `with`, by `ctx.close()`, or, as a fallback, when the last of its members is gone (a member refers to its context, so the context lives while any member does; in Python the cycle needs `tp_traverse`/`tp_clear`).

The closing is **hard**: after it every member (instances, tables, `Function`s) is *closed*, and using one raises an error, like a closed file. It does not depend on who still holds a Python object. WebAssembly has no destructors, so no wasm code runs at the close; the memory is freed in order (instances, tables, memories), and the host callables and the objects behind `externref`s are let go.

A close must not free what a running call uses. The context counts its **active calls** (the entry that guards a reentrant call is the place); `close` from inside a call, or while another thread is in one, is refused (or waits: not settled). A call into a closed member is an error, never a crash.

**The counter of active calls: how it is kept (a proposal from the measurements, not decided).** `close` must know whether a call is in flight. The measurements ([experiments/context_bench/](experiments/context_bench/)) say where the counter must *not* be: one counter per context, or one per instance that several threads call, is a cache line the cores fight over (about 300 ns per call on 4 threads against 25-35 ns). So:

- the counter is **split by thread**: a few counters in the instance, each on a cache line of its own, a thread using the one its id selects; a call adds one to its line, then **reads a `closing` flag** (read by all, written only by `close`, so it stays shared and cheap); if the flag is up it takes the one back and fails with "closed";
- `close` **raises the flag first, then adds up the counters of all members** (the registry has the list); if the sum is not zero a call is in flight and `close` refuses (the answer to open question 1, if refusing is chosen). The cost is on `close`, which is rare, and not on the calls, which are many;
- the order matters and is the whole proof: a call does *add, then read the flag*, `close` does *raise the flag, then read the counters*, both with sequentially consistent operations (on x86 a `lock`ed add is a full barrier; on ARM an explicit barrier), so either the call sees the flag or `close` sees the call;
- a `close` made **from inside a call** sees its own thread's count above zero and refuses, so it cannot wait for itself;
- where there is one thread at a time (the GIL), a plain counter and a plain check are enough (1.5 ns); the atomic form is for builds without the GIL and for C hosts with threads, one macro as `WASMEXT_LOCK`;
- not measured: the cost of the sum with many members, of choosing the line by thread id, and the barrier on ARM.

**Several contexts and the order of closing.** Contexts can be connected only through the host (a callback, a queue): what passes is data (numbers, bytes, copies), never a `Function` or a `Table`. A Python object may be given as an `externref` to both contexts: it is a host object, each context keeps it. Nested `with` closes the inner first; the right order is to close first the context whose callbacks *call into* the other, so that is the one to nest inside. For callbacks both ways no order is right. So the order lowers the number of errors, and the safety is the hard close with the flag and the counter. `contextlib.ExitStack` serves a set of contexts that is not known in advance.

## The public interface, and what is inside

Outside: make a context, close it, the `context` argument of `Instance` and `Table`. Nothing else; the registry, the keep-alive and the locking are inside.

The core is **plain C in the common glue** (`wasmext_glue.h`), with no `Python.h`: the structure, the registry, the lock, the lookups, `new`/`close`. A host with no Python uses it as it is (`wasmext_context_new/close`, and an instance made in it; names to be settled). `Python.h` is only in the thin layer of the module (`<name>_py.c`): the class `Context` (the context manager), the capsule, `tp_traverse`/`tp_clear`; the same layers as `Table`, with the same public interface in the extension, in the wrapper for ctypes and in the `.pyi`.

Across modules built apart it is **a pointer to a structure with a header**, not a structure each module knows. The header has the version (as `WASMEXT_ABI` has), the size, and a table of functions. Every module works with a context **through that table**, not through the functions it has compiled itself, because each module has its own copy of the glue. The pointer travels between modules in a **capsule** on the object (as `wasmext.export.v<X>` does for the record of an export): no symbols shared by the linker, nothing for the user to see.

## What it holds

- **The members:** instances, standalone `Table`s, the functions made by the host.
- **The registry** `module_instance` → owner. A bare `funcref` of wasm2c carries `func`, `func_type` and `module_instance`; the context finds the owner from the last.
- **The host functions** as members: a record `HostFunction` (the callable, the type) is the `module_instance` of its `funcref`; `func` is a trampoline for the type, made at build time for each type the module declares (a type it does not declare cannot be made: the AOT rule). An exception of the callable becomes a trap.
- **The `externref`s** given to the members. An `externref` of wasm2c is an opaque `void *` (`wasm_rt_externref_t`) that wasm cannot make or change, only copy; it is the pointer to the object, and the context keeps the object alive. No handles, no counters.

## Ownership: an arena, and what it costs

A context **holds its members strongly** until it is closed. This is what `wasm3` (the runtime owns all its modules) and `wasmtime` (a `Store` frees its instances only when it is dropped; its documentation says a store should live about as long as one main instance) do, and it is chosen over counting by hand (atomics, cycles, the order of destruction).

The price: **the members of a context only grow.** No number overflows (the count is 64-bit); the memory grows, and with guard pages every instance also reserves address space. A context that makes and drops instances without end keeps them. The first remedy is simple: a context for each batch of work (`with` for each). A single member cannot be unloaded while the context lives; a plugin that shares a table with the host lives as long as the context.

Also, the registry does not follow who refers to whom, so the keep-alive chains of today (writers, importers, `refs`) are not needed **inside** a context. That is the gain; the loss is the unloading of one member (above).

### Later: a lazy collector

A member can be freed before the close if nothing can reach it, and for `funcref` that is decidable, because a reference cannot be in the linear memory: it is only in a table, a global, a local or the stack. So the roots are the Python references to the member (its count) and the calls in progress; the edges are the imports (X imports a table or a memory of Y) and the contents of the tables and globals (a `funcref` has `module_instance`, which names its owner). A mark-and-sweep over that small graph, run on demand (`ctx.collect()`) or past a limit, and only when no call is active, frees the members nothing reaches (cycles included). Python objects and `externref`s are edges too (through `tp_traverse`), which has to be done with care.

This is the same kind of algorithm as the tracing collector of a JavaScript engine (JavaScriptCore marks the wrappers and target instances of a table), but small, on demand and over members only. It would also give the **hot reload** that wasmtime does not have: make the new instance in the same context, let the host rewrite the table entries (`Table.set`) and the references, and `collect()` frees the old one. What is freed is the data of the instance (memory, tables, globals); the code of the module stays in its `.so`. Not for the first version; the registry is to be made so that it is possible (an id for each member, edges that can be found by scanning the tables).

## Locking

The registry can be read by one thread while another adds a member; without the GIL (a free-threaded build, a C host with threads) that reads freed memory. So it is under a **mutex**, taken only to look up or add a member, never on the path of a call into wasm, and **never held across a call outward** (Python, a destructor, a host function): it is dropped before. With that rule a recursive mutex is not needed. Because members are only added, a lookup needs the lock only against an addition.

A target with no threads (a CPython built without them, some embedded ones) must not need it: one macro, `WASMEXT_LOCK`/`WASMEXT_UNLOCK`, is a `pthread` mutex, an `SRWLOCK` or a C11 `mtx` where there are threads and **empty** where there are none (as `WASM_RT_THREAD_LOCAL` of wasm2c is empty where the compiler has no thread-local storage).

The stack of entries for traps (`wasmext_traps`) is thread-local for a different reason and is not part of the context: a trap jumps to the innermost entry of the call chain **of this thread**, and each thread has its own C stack; wasm2c itself keeps its call depth and the active exception thread-local.

## Overhead

**Measured as a C micro-benchmark** (`docs/experiments/context_bench/`, one machine, two runs; the lines below are the estimates written before, kept for the record, and the results are in the README there): a lock costs 15-20 ns per lookup, one lock under 4 threads 300-950 ns; a plain counter + check 1.5 ns per call, an atomic counter 12-14 ns, and one atomic counter shared by 4 threads about 220 ns (a counter per member: 19-29 ns). **Around real calls into a module from a C host with threads (no Python; `real.c`)**: a call through the library costs about 23 ns itself, 4 host threads scale as one (the runtime has no lock on that path), a counter for each thread adds 4-12 ns, a counter per instance is as good only while one thread calls it (4 threads on one instance: 292 ns), and one counter per context or a lock per call turns a 25 ns call into 330-435 ns on 4 threads (10-25 % on a call of 650 ns, nothing at 100 us). So the counter of active calls is split by thread (striped lines in the instance) and `close` sums them after raising a `closing` flag (each call: add to its own line, then read the flag; `close`: set the flag, then sum): the cost lands on the rare `close`. The counter of active calls should not be one atomic per context on the hot path, and the registry can be read lock-free because members never leave.

Estimates written before the measurement:

- a call into wasm: none from the registry; the active-call counter and the "closed" check are new (a counter in the entry that exists, a predictable branch; to measure);
- making or closing a context, adding a member: rare, microseconds;
- a `funcref` turned into a `Function` (the one hot place): one lookup by pointer under the lock (an uncontended mutex is tens of nanoseconds, plus a hash lookup; for comparison the entry that guards a reentrant call costs about 5 ns, 13 %, in a measurement of the Python interface);
- memory: an entry in the registry for each member, one mutex for each context, one Python object `Context`; on a target with no threads the lock costs nothing;
- unknown: the lock under many threads on one context, and the lookup with thousands of members.

A micro-benchmark in C (mutex plus hash lookup by pointer, one thread and several) would replace the estimates.

## What it would give

- the postponed items: `funcref` in an import, a `Function` with a `funcref` parameter (the owner is found in the context), the host functions as members;
- `externref`, as the arena above;
- a place for the **tags**: a tag must be one identity shared by the instances that use it, so that an exception thrown in one is caught in another; one more kind of export with the same rules as a table (not designed);
- no implicit sharing: what is shared is in the same `with`;
- the keep-alive chains of today become one case of the context (a rewrite of part of steps 3b to 7 of TABLES_PLAN.md: not small).

## A record of the process, next to the context (an idea, not decided)

Some things the autonomous modules touch are **one for the process or one for the thread**, and a context cannot own them: the handler of the signals (one for the process), the alternate stack (one for each thread), the stack of entries for traps (thread-local).
Each module has a copy of the runtime of wasm2c, and each copy acts as if it were alone. Found by experiment (2026-10-22, `tests/test_two_modules.py`): **two modules in one process, a trap by a signal (out of bounds past the guard pages, stack overflow) works only in the module imported last**; in the other the process aborts,
because the one handler of the process raises the trap of the runtime that installed it last. (`unreachable`, which is no signal, is not affected, and neither are modules that share tables, which already share the stack of entries.) The same one-alternate-stack-for-a-thread limit is why
a thread that runs several modules leaves a stack of each but one.

The idea: a **small record of the process** (the handler of the signals, who owns the alternate stack of a thread, the thread's stack of entries), **kept in each module as code**, found at run time through a capsule with a version (as `wasmext_traps` is), created by the first module that loads and joined by the others.
A module that finds none, or one it cannot read, works alone as today. It decides nothing about who may exchange references; that stays with the context, which is explicit. So the host installs nothing, and the autonomy of a module is kept; the price is one more record in the contract between wheels
of different versions (small: the signals, the stacks), and a thread that runs several modules is set up once and not once per module.

**Checked by experiment (2026-10-22):** with `--share-tables` on every module, all combinations of two modules trap correctly, so the stack of entries of `wasmext_traps` already does what the record needs for traps. But it cannot be turned on for all modules as it is: it keeps at most 64 runtimes
(`WASMEXT_MAX_RUNTIMES`) and its `enter`/`leave` loop over all of them on every call. A **lighter variant for modules that share no tables** (push and pop of the entry with no loop, the unwind target set for the module's own runtime only, two functions added at the end of `wasmext_traps`) and a **fall-back to the
autonomous behaviour instead of `ImportError`** when the capsule is not compatible would be needed. Not built; it touches the ABI of the record of traps. (The thread capsule of the Python layer is another thing, for another problem: setting up and giving back the alternate stack of each thread.)

Open: how modules built apart find the record in a C host with no Python (an explicit pointer, or none), subinterpreters (the handler is of the process, a capsule is of the interpreter), and Windows (vectored handlers: each module adds its own).

## Taken from, and not taken from, other runtimes

(Read in the code, not from memory: `wasmtime` `crates/wasmtime/src/runtime/store.rs`, `func.rs`, `gc/enabled/rooting.rs`; `wasm3` `source/m3_env.c`, `m3_env.h`; JavaScriptCore `Source/JavaScriptCore/wasm/WasmTable.cpp`. Other runtimes (wasmer, WAMR, WasmEdge) were not read.)

- **wasmtime:** a `Store` owns every instance until it is dropped; a `Func` is a copyable handle (store id, pointer) that owns nothing and is valid inside its store; a host function is held by the store; an `externref` is a GC object reached through the roots of the store, with a finalizer. An instance cannot be unloaded; a hot reload there is a new instance plus rewritten table entries. Taken: the arena. Not taken: the store as a runtime with an engine and a garbage collector.
- **wasm3:** a runtime owns all its modules; a table element is the pointer of the function, an `externref` an opaque host handle owned by no one. Taken: the arena.
- **JavaScriptCore:** a table is a garbage-collected cell that marks its wrappers and the target instances; what is unreachable is collected. The model of the lazy collector above.
- **The component model of WASI:** the same wish for an explicit boundary and a table of handles for resources (`own`, `borrow`, `[dtor]`), but its components **share nothing** and values are copied at the boundary (`canon lift`/`lower`). A context is the opposite inside: a place of trust where tables and functions are shared **without** copying; between contexts it is shared-nothing as there.

## Considered and not taken

- **A domain with `attach` and `detach`.** Any module joins and leaves. It lets one member be unloaded, but it needs a rule for a member that others still use (`detach` would refuse while a function of it is in a table of another, and the refusal needs a signal: an exception or a code), and it leaves the question of implicit linking. The context removes both by binding the member at its making and never letting it leave, at the price of the unloading of a single member (which the lazy collector gives back).
- **One shared runtime library** (all modules linked against one `.so` with one store). A `wasmtime` in miniature, and the point of the project is to leave that. It also fails across wheels built apart (`auditwheel` and `delocate` give each wheel its own copy) and fixes one configuration of the runtime macros for all modules.
- **A table of handles for `externref`.** It does counting by hand in one place and does not remove its problems; with an arena the plain pointer is safe, since wasm cannot make an `externref`.

## Open questions

1. Whether `close` from inside a call, or in another thread's call, **refuses or waits**, and how a refusal is told (the counter above works for refusing; waiting needs a way to be woken, and from inside a call it can only refuse) (an exception in Python, a code in C and in the wrapper for ctypes).
2. **The traps** (`wasmext_traps`, `share_tables`): outside the context as of now; whether making a member in a context checks that the module was built with the handler is not settled.
3. **The tags**: not designed.
4. The names of the functions and of the class; the signature (`context=` as a keyword only); whether a module-level default context exists (no, as of now).
5. The API of a library (`<name>_api.h`) and of the executable for the context; `WASMEXT_ABI` and the fingerprint (`tests/test_abi.py`) for the header of the context.
6. The lazy collector: when it runs, how Python objects and `externref`s are edges, the cost of scanning big tables.
7. The cost of the active-call counter and of the "closed" check on every call: **measured in C** (see Overhead: 4-12 ns per thread on a 23 ns call) and **in Python** ([experiments/free_threading/](experiments/free_threading/), 2026-10-22): a call into wasm holds the GIL for its whole length (a short call in another thread waits for all of a 1 s call), a module that declares `Py_MOD_GIL_NOT_USED` (one line, by hand in a test build) gives 3.7-4.0x on 4 cores for calls that do work, also on one shared instance with no state, and costs nothing on one thread; and **a stack overflow in a thread other than the one that imported the extension crashes the process** on every build (the extension never calls `wasm_rt_init_thread`), which is a bug of today whatever the context becomes.
