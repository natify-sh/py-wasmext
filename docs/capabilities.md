# Capabilities beyond the WASI spec

Notes, not a plan: what a module can import besides `wasi:*`, how a capability (a host service such as Redis) is given to a module, where its state lives, and how the host of WASI 0.1 and 0.2 is bound. Nothing here is built yet, except what is said to exist. It belongs with `context_concept.md` (the host as part of a context) and `WASI_COMPONENTS.md` (`lift` / `lower`).

## 1. What a module imports besides WASI 0.2

A component is a *world*: the interfaces it imports are whatever the world says. A command (`wasi:cli/command`) imports `wasi:*` only, and that is what the runtimes run as an executable. A core module taken out of a component (`wasm-tools component unbundle`) can import:

1. **Interfaces of the host's own** (`my:app/logger`): any WIT world may import any interface.
2. **Proposals of WASI that are not in 0.2:** `wasi:nn`, `wasi:keyvalue`, `wasi:config`, `wasi:logging`, `wasi:blobstore`, `wasi-gfx`, `wasi:tls`... versioned on their own.
3. **Other versions:** `wasi:cli@0.3.x` and the rest of 0.3 (async); the `wasm32-wasip3` programs of the official test suite import `@0.2.9` and `@0.3.2` side by side.
4. **Machinery of the component model:** `[resource-drop]…`, `[resource-new]…`, `[resource-rep]…` for the component's own resources; in 0.3 the async primitives.
5. **Glue between core modules:** a component made by `wit-component` has several modules (main, shim, adapter); one taken out imports the memory, the table of the shim (`$imports`), and, if a p1 adapter is not fused, `wasi_snapshot_preview1`.

What wasmext does with them (built): an import that is not `wasi:*@0.2` is a plain import of the caller (`imports=`), with a note; a `wasi:*@0.2` name that fusedwasi has not, or with another core signature, is a `GenError`; a `wasi:` import of another version under `wasm32-wasip2` is a note, and then a plain import. Memories, tables and globals of other modules go through the existing linking.

The limit: the caller gets the arguments of the canonical ABI as the core module has them (numbers, `(pointer, length)`, resource handles as indexes). Lifting them to values is `lift` / `lower` (deferred).

### Where it differs in real projects

A command is the common case; a host beyond the spec is where wasm is a plugin or a function inside a platform (examples from memory, the exact names and versions to be checked before they are relied on):

- **Platforms with capabilities of their own:** Spin (`fermyon:spin/key-value`, `sqlite`, `llm`, `variables`, `redis`, `mqtt`, now partly `wasi:keyvalue` / `wasi:config`), wasmCloud (`wasi:keyvalue`, `blobstore`, `messaging`, providers `wasmcloud:*`), Fastly Compute (`fastly_http_req` and the like as core imports; newer components use `wasi:http` plus their own).
- **Plugin systems:** Zed (`zed:extension/*`), Extism (host functions `extism:host/env`, core modules), Shopify Functions (`shopify_function_v1`), Zellij (`zellij_*` on p1), proxy-wasm in Envoy (`proxy_abi`). The host API is the product; WASI is often only what libc needs.
- **What a runtime adds:** Wasmtime has `wasi:nn`, `wasi:keyvalue`, `wasi:config`, `wasi:tls` (flags) and `wasi-threads` (the core import `wasi.thread-spawn`); `wasi-gfx` for graphics; everything of 0.3.
- **`wasi:http/proxy` is not an import beyond the spec:** it *exports* `wasi:http/incoming-handler@0.2.x#handle`, which for wasmext is an export with an unusual name.

For wasmext this matters because the case it is made for, wasm as an extension of Python, is the plugin case.

## 2. How a capability is given

Mechanism that exists: `imports={module: {name: callable}}` (extension and wrapper for ctypes), `<name>_set_import<k>(m, fn, user)` (library). A capability is a pair `(fn, user)` in a slot of the import; its state lives behind `user`, owned by whoever plugs it in. The built-in host of WASI is the same: p1 binds `fn` to the function of fusedwasi and `user` to its state, p2 binds `fn` to a generated trampoline and `user` to the instance. So Redis is not different from the host of WASI, except where its state is.

Decision (proposed): **only the interfaces of the WASI spec are built in; every other capability is plugged from outside.** Built in would cost the property that an extension has no runtime dependency and that the host is the host of the spec. Three ways to plug one from outside:

- a **Python object** (`class Redis`) whose methods are the imports; its state is its attributes (a pool of connections, a table of handles);
- a **C capability** through `set_import` in the library (speed, no Python);
- later, a **registration in a context**, which owns the host and gives the capabilities what they need (see `context_concept.md`).

### The state, at three levels

- **Shared:** a pool of connections, the configuration: one object, given to several instances.
- **Per instance:** the resources a module creates (a connection, a cursor) are handles, numbers in the space of *one* instance of the component. So even with a shared pool the capability keeps a table of handles *for each instance*, and drops it with the instance (`[resource-drop]` and the finalizer of the instance). Today an external `user` gets no "the instance is gone" call: the caller does it.
- **The memory of the caller:** a function that takes a key (a string) gets `(pointer, length)` in the memory of the instance that called. Today a capability reaches it through a `bind` that the host does by hand (`examples/wasi2_unbundled`, `Host.bind`). That cannot serve several instances with one object: **the callable does not know who called it.**

Proposed: an optional `caller` for an import (a handle that has the memory and `cabi_realloc` of the calling instance), the way other runtimes have a `Caller`. It is a design with `lift` / `lower`, because after them a function gets strings and not `(pointer, length)`, and the caller is hidden.

### What cannot be done from outside

A capability that returns a **stream or a pollable of `wasi:io`** (an answer that comes later, publish/subscribe) puts resources into the *table of handles of the host of WASI*. A Python function outside cannot reach the table of fusedwasi. (Its slots have a `kind`, an `obj` and a `destroy`, so opening them to other kinds is possible, but it has to be designed.) That is a job for the **context**: it owns the host, so a capability registered in it gets the shared pool, the handles of the host and the memory of the caller.

So: calls that are plain (Redis GET / SET: a string in, a value out) can be plugged from outside as soon as there is a `caller` (or `lift` / `lower`); the ones that return streams and pollables (pub/sub) wait for the context.

## 3. The host of WASI 0.1 and of 0.2 are bound differently

> **Since 2026-10-26** the state of 0.1 is over the state of 0.2 (`fusedwasi_p1_create(&config, &p2_state, ...)`; every WASI module has `store->wasi2`, and a module of 0.1 has `store->wasi` as well): the arguments, environment, clocks, random bytes, sleep, standard streams, files and the exit are those of the state of 0.2 (`fusedwasi_p1_over_p2.md`). The table is about the *binding* of the two families (state on the heap, `fn` of the slot, memory), which is still as it says.

The same idea (the state in the instance, `fn` and `user` in the slot), two shapes:

| | p1 | p2 |
| --- | --- | --- |
| State | `fusedwasi_p1_state *`, on the heap: `fusedwasi_p1_create(config)` / `_destroy` | `fusedwasi_p2_state`, in the structure of the instance: `fusedwasi_p2_init` / `_free` |
| `fn` of the slot | the function of fusedwasi itself (`fusedwasi_p1_<name>`): its signature is the one of the import | a trampoline made for each import (`<last>_p2_import<k>`) |
| `user` of the slot | the state | the instance |
| Memory | bound once with pointers to the fields of the runtime's memory (`fusedwasi_p1_bind(&data, &size)`): it follows `memory.grow` by itself | a *copy* of `{base, size}`: set again before each call (`p2_refresh`) because the memory may have grown |
| Extra argument | none | `comp`, the number of the component whose memory is meant (the core signature does not have it) |
| A failure of the host | `*trapped` | `s->trap(...)`, which does not return (`wasm_rt_trap`) |
| The program is over | `finished` (`proc_exit`, `proc_raise`) | `exited`, `exit_code` (`wasi:cli/exit`) |
| `cabi_realloc` | not used | a callback of the state that calls the export of the module |

The trampoline is why a capability that needs the memory of the caller will also want one (or the `caller` of section 2): the memory is something that has to be put right before the call.

## 4. The originals of the calls of WASI, and the shape of the p1 host

Two things that were mixed up in the conversation, and a decision.

**The originals of the calls** (exists for p1, not for p2). `Instance.__host__` gives a `Host` (`Host.name`, `Host.__imports__`: `{module: {name: callable}}`) whose callables are the implementation of wasmext itself (`fusedwasi_p1_<name>`; in the library `<name>_host_call<k>`). It is for a caller who replaces one call through `imports=` and wants to call the original from the replacement (log a write, filter a path, add a handler on top), or to give the originals to another instance. For `wasm32-wasip2` there is nothing like it: a call that is replaced is replaced for good. Built later, and it is small: the original is the trampoline `<last>_p2_import<k>` made callable from Python (it sets the memory by itself). It is in the plan as "not here" in 6a and 6d. This is *not* the "host of a context" (who owns the state of a host that has both p1 and p2); that is the idea of `context_concept.md`.

**Decision: the two hosts end in one shape, and the move of p1 is the first step of the context.** The context (`context_concept.md`: one runtime and one host, private to it) needs one shape of a host, so p1 and p2 are unified; it is not optional. The shape of p2 is the one to end with: a slot is `(fn, user)` where `user` is always the instance (later the context), the state is in that structure, and an import has a trampoline where something has to be done around the call. It is the place for a `caller`, for the originals of both hosts made the same way, and for a host that is a private part of a context. A direct binding (what p1 has: the slot points at the function of fusedwasi, whose signature is the signature of the slot, and the memory follows `memory.grow` through the pointers to the fields of the runtime) stays as an optimisation for a call that needs nothing around it. So "unified" is the slot and the owner of the state, not "a trampoline for everything".

Order: (1) stage 6 is finished as it is, p1 and p2 each in its own shape; (2) the context is the next step, and it fixes the shape; (3) p1 moves first in that step, before anything new is added, so that the change is seen alone: the behaviour does not change, the ABI of `host_call` and of `Host` changes on purpose, and the net is the official test suite in CI and `tests/test_host.py`; (4) before it, a measurement of the hot paths (`fd_write`, `fd_read` in a loop) before and after: if the extra indirect call shows, the trampoline is inlined, or the direct binding stays for the calls that need nothing around them. The other direction (p2 in the shape of p1) is more expensive: it asks for a change in fusedwasi p2 (the memory by pointers instead of a copy, functions without `comp`).

**Measured (2026-10-25): the trampoline costs nothing that shows.** A prototype (a scratch copy of the generator, not committed) gave every WASI call of p1 a trampoline `p1_import<k>(user = instance, ..., trapped)` that calls the function of fusedwasi with `self->wasi`; the same three WAT programs were built as executables with `-O2` with and without it: `clock_time_get` 20 000 000 times (no syscall), `random_get` 5 000 000 times, `fd_write` of one byte to `/dev/null` 2 000 000 times. Minimum of seven runs, three rounds: clock 0.59-0.63 s (direct) and 0.60-0.61 s (trampoline), about 30 ns a call; random 1.52-1.57 s and 1.50-1.57 s, about 300 ns; write 0.29-0.31 s and 0.29-0.30 s, about 145 ns. The difference is inside the noise of a run (about 5 %), so below 1-2 ns a call, even for the call with no syscall. That removes the cost as a reason to keep the direct binding; what is left against the move is the work and the change of the ABI of `host_call` / `Host`. (The Python hooks are unaffected: they are far above this.) Not measured: the refresh of the memory of p2 on each call (a store of a pointer and a size), which p2 pays already.

**If fusedwasi has to change for the unification, it changes (both twins, C and Python, with the parity tests).** The cost of two twins is not a reason to bend the shape on the side of wasmext.

**Done (2026-10-25): p1 is moved.** The glue of WASI 0.1 has a trampoline `<last>_p1_import<k>(user, ..., trapped)` for each import, as 0.2 has; the slot is `(trampoline, instance)` (in the glue's `_wasi_bind` and in the constructor of the extension), and the trampoline calls `fusedwasi_p1_<name>(self->wasi, ...)`. Nothing else changed: the state is still on the heap (`fusedwasi_p1_create`), the originals (`Host`, `<name>_host_call<k>`) still call the functions of fusedwasi, all 891 tests are as before. The same measurement on the real change (not the prototype), interleaved with the direct binding because the machine was busier than before: `clock_time_get` 0.68-0.70 s direct against 0.72-0.745 s with the trampoline for 20 000 000 calls, which is 1-2 ns a call (3-5 % of the cheapest call, 30 ns), and nothing to see on calls that make a syscall (`random_get`, `fd_write`).

**Done (2026-10-28, C3):** the originals exist for both families (`Instance.__host__`, one state and one guest for each instance in the glue; see WASI_TARGET_PLAN.md, C3). What follows is the reasoning of the day. **Deferred (2026-10-25), see the plan, "Decided after stage 6":** the originals for p2 (`Host`) wait for the context, where the host exists before the instances (today a replacement that wants the original of p1 has to find the instance late, because the original is bound to the state of one instance); the `caller` of an import waits for the first capability that shares a state among instances, and has to be a mark on the function (`fn.__wasm_caller__ = True`) and not something imported from wasmext, since an extension has no run-time dependency on wasmext or fusedwasi.
