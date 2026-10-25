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

**Decision: the p1 host moves to the shape of the p2 host later, not now.** The shape of p2 (the state in the structure of the instance, `user` is the instance, a trampoline for each import) is the one to end with: it is the place for a `caller`, for the originals of both hosts made the same way, and for a host that is a private part of a context. But p1 needs no trampoline (the signature of the function of fusedwasi is the signature of the slot, the memory follows `memory.grow` through the pointers to the fields of the runtime), a trampoline adds an indirect call to the hot paths (`fd_write`, `fd_read`), it changes the ABI of `host_call` and of `Host`, and p1 is tested (the official test suite runs in CI). So p1 is moved when one of those three needs arrives; the test suite is the net. The other direction (p2 in the shape of p1) is more expensive: it asks for a change in fusedwasi p2 (the memory by pointers instead of a copy, functions without `comp`).
