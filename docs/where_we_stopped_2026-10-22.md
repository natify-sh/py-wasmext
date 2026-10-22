# Where we stopped (2026-10-22): what is done, what is not, and the ideas

A note of the state at the end of one long working session on the branch `dev` (against `main`): so that it is not only in a conversation. How a fact is known is marked as elsewhere: **[run]** run here, **[read]** read in sources,
**[estimate]** a judgement. Nothing here is a decision unless it says so; the decisions that wait for the owner are listed at the end.

## 1. Done and in the repository

**Features of wasmext (code, tests, docs)**
- `wasi_flavor` (core WASI 0.1/0.2/0.3, component, `fused` = the output of `meld fuse`), shown by `inspect`; a warning in `natify`.
- Compact imports: a reader that follows the proposal (both encodings), and a rewrite to ordinary imports before `wasm2c`, because WABT 1.0.42 reads `0x7E` differently ([WABT #2897](https://github.com/WebAssembly/wabt/issues/2897)).
- A repair of the C of `wasm2c` for an imported function in an element segment (`_repair_imported_elements`; [WABT #2896](https://github.com/WebAssembly/wabt/issues/2896)): without it the output of `meld fuse` trapped at its first call.
- The message of the refusal of custom page sizes is true now.
- **Stack overflow in a thread other than the one that imported the extension is a `Trap`** (it was a SIGSEGV that killed the process, and `Instance()` in such a thread aborted in a build with assertions): the entry of a call sets the thread up at its
  first call, and a capsule in the dict of the thread state gives the stack back when the thread ends (`src/wasmext/_gen.py`, `tests/test_threads.py`; `src/wasmext/c/` unchanged, so the fingerprint of the ABI is the same). Whole suite after the first version: 784 passed; after the last edit
  140 tests of the generator, ABI, tables and threads, and 250 under the sanitizers.
- CI: **ASan + UBSan job** (`.github/workflows/sanitizers.yml`, after o-murphy/rp2040py; `WASMEXT_TEST_CFLAGS` in `tests/conftest.py`; a canary `tests/test_sanitizers.py`). Run by hand on five test files, no report; **not run in CI yet**, nor the whole suite under it.
- Tests that document a known gap: `tests/test_two_modules.py` (`xfail(strict)`, see 3).

**Concepts and studies (docs)**
- `typed_function_references_concept.md`, `custom_page_sizes_concept.md`, `context_concept.md` (updated, see 4), `threads_wasm2c_wasix_concept.md` (a reading of `wasm2c` and WASIX; nothing built).
- `wasi_p1_vs_p2_host_requirements.md` and `experiments/wasi_p1_p2_git|cpython/`: which WASI version and way of use asks least of the host. **WASI 0.1 through wasmext asks nothing of the host (0 imports); 0.2 asks 53 to 115.** Unbundled and meld give the same imports for one component.
- `wasi_p2_host_scope.md` and `experiments/wasi_p2_scope/`: the size of a host of WASI 0.2 from the WIT of `v0.2.12`: **7 packages, 31 interfaces, 200 imports (137 for a command, 63 of them `wasi:http` extra)**; what four programs asked for (115 of 137) and what the hosts here implement (69, 5 stubs).
- `examples/wasi2_python/`: **CPython 3.15 on WASI 0.2 through wasmext on a host in Python** (filesystem over `os`, name lookup, TCP): `print`, `import ssl` (OpenSSL 3.5.0 built for `wasm32-wasip2`), an HTTPS request with the certificate checked **inside the module**, and **`pip install` from a local HTTPS index**.
  An example, not in the CI, no tests; PyPI itself was not tried (no outbound TCP in the session). Workarounds: `OPENSSL_THREADS` defined by hand (WASI has no threads), pip run in the same process (`ensurepip` needs a child process), shims for `os.getuid`, `os.umask`, `mmap`, and an `os.write` that loops.
- `experiments/context_bench/` (C, with and without a module), `experiments/free_threading/` (Python; GIL, free-threaded with the GIL on, free-threaded without it; and the fix against `WASM_RT_STACK_DEPTH_COUNT`).
- `wasm2c_limits.md`: the six WABT issues opened from here, all open on 2026-10-22: [#2885](https://github.com/WebAssembly/wabt/issues/2885), [#2886](https://github.com/WebAssembly/wabt/issues/2886), [#2893](https://github.com/WebAssembly/wabt/issues/2893),
  [#2895](https://github.com/WebAssembly/wabt/issues/2895), [#2896](https://github.com/WebAssembly/wabt/issues/2896), [#2897](https://github.com/WebAssembly/wabt/issues/2897) ([#2884](https://github.com/WebAssembly/wabt/issues/2884) is not in the list of open ones; not checked).

## 2. What the measurements said

- **The context guard (C, [run]):** a call through the library costs ≈23 ns; a lock costs 15-20 ns; one lock or one counter shared by 4 threads costs 300-950 ns; a counter **per thread** (own cache line) costs as one thread. A counter per instance is as bad as one per context when several threads call the instance (292 ns).
- **Python ([run], 3.14):** a call into wasm holds the GIL for its whole length (a short call in another thread waited for all of a 1 s call); a module that declares `Py_MOD_GIL_NOT_USED` (by hand in a test build, **not in wasmext**) gives 3.7-4.0x on 4 cores for calls that do work, also on one shared instance with no state, and costs nothing on one thread.
- **Stack overflow, the fix against the flag ([run]):** `WASM_RT_STACK_DEPTH_COUNT` needs no setup per thread but is **about 4 times slower on calls inside a module**, and counts frames, not bytes: limit 500 is far too low for real programs, limit 100,000 crashes a thread with a small stack.
  The fix keeps full speed and the real limit of each stack. The fix is the default; the count could be an option for a host that cannot have a handler on its thread stacks. Not offered as a setting.
- **Sanitizers ([run]):** under ASan and UBSan with abort on the first report, `test_threads`, `test_extension`, `test_tables`, `test_table_class` and `test_linking` pass (250). A test that asks for an impossible allocation needs `allocator_may_return_null=1`.

## 3. Found and not solved

- **Two modules in one process: a trap that comes from a signal works only in the module imported last** ([run], `tests/test_two_modules.py`). The handler of SIGSEGV/SIGBUS is one for the process, each runtime installs its own with no chaining, and it raises the trap of its own runtime, which is not the entry of the call
  that is running in the other module; the process aborts (exit 134). `unreachable` (no signal) is fine; modules that share tables are fine (they share one stack of entries). Known before today: nothing; it was not in FEATURES.md.
- With `--share-tables` all combinations of two modules worked ([run]) **but it cannot be turned on for every module as it is**: the shared stack of entries keeps at most **64 runtimes** (`WASMEXT_MAX_RUNTIMES`), and each entry and exit **loops over all of them** (a cost that grows with the number of loaded modules).
- A thread that runs **several modules** leaves a stack of each but one, and the runtime says "alternate stack was modified unexpectedly" in a debug build (one `sigaltstack` for a thread, one runtime copy for each module). The thread that imports a module is not registered for giving the stack back (as before): a leak per thread, small.
- `ensurepip` cannot run on WASI (no child processes), the whole of `wasi:sockets` UDP and the server side of TCP are not in the host of the example, there is **no TLS interface in WASI 0.2** (TLS is in the module, from OpenSSL).
- The multi-component results with meld (strings through adapters, duplicated imports, which memory an import belongs to) were measured on meld **0.64.0**; the fixes are in 0.65.0, **a pull request that was open, not published** ([#521](https://github.com/pulseengine/meld/pull/521)): to repeat the experiment on it. [#515](https://github.com/pulseengine/meld/issues/515) is in 0.65.1.
- Not tried at all: free-threading with state (imports, host callables, `memoryview`, `Table`/`Function`, GC, instances made from several threads), macOS and Windows for the thread fix and for sanitizers, TSan, the full suite under the sanitizers, a 3.15t build.

## 4. Ideas, not decisions

1. **The context** ([context_concept.md](context_concept.md)): the registry and arena stay as designed; the counter of active calls is **split by thread, `close` raises a `closing` flag and then adds the counters up** (a proposal: the cost is on the rare `close`); a plain counter under the GIL.
2. **A record of the process next to the context:** what is one for the process or the thread (handler of signals, alternate stacks, stack of entries) cannot belong to a context. It would be **kept in each module as code and found through a versioned capsule**, created by the first module, joined by the others, with a fall-back to working alone
   as today, so the host installs nothing and the modules stay autonomous. Open: C hosts with no Python, subinterpreters, Windows (vectored handlers).
3. **The fix for the signal traps of ordinary modules** (the practical form of 2): a lighter variant of the shared stack of entries, **`push`/`pop` with no loop** over the runtimes, used by modules that do not share tables, and the full one only for those that do; it adds two functions at the end of `wasmext_traps` (the policy allows a record to grow
   at its end, but it is a change of the contract between wheels of different versions) and **falls back to the autonomous behaviour instead of an `ImportError`** when the capsule is not compatible. The existing knob `WASM_RT_SKIP_SIGNAL_RECOVERY` could let the copies leave the handler to one owner. **Not built.**
3b. **A shared runtime: master and slave** ([shared_runtime_concept.md](shared_runtime_concept.md)): one module publishes the whole runtime through a capsule, a module that finds a compatible one attaches to it, any other keeps its own. May be better than 2 and 3 (one handler, one setup of a thread, no limit of 64, a registry for tags);
   **first to be found out whether it is possible at all** (the thread-local variables that the generated code reads by name, the layout, what travels in the capsule, concurrent imports, the cost); eleven points of what to find out are in that page. Nothing built.
4. **WABT side:** the runtime of `wasm2c` assumes one copy per process (its README: shared state is defined once by the embedder). Possible improvements to propose upstream, not bugs: chain to the previous handler, and recognise the memories of this runtime by address. A draft of such a proposal is **to be written once 3 is shown to work**, as the owner asked.
5. **Sanitizers:** TSan for the C layer without Python (the shared library and a driver with `pthread`s, such as `real.c`), the whole suite under ASan+UBSan on a schedule; the interpreter is not instrumented, so TSan on the Python side would be noise.
6. **Free-threading:** declare `Py_MOD_GIL_NOT_USED` only after the Python side of an instance is audited (the context is where that belongs); `Py_mod_gil` is one line for single-phase init (`PyUnstable_Module_SetGIL`).
7. **Threads and WASIX** ([threads_wasm2c_wasix_concept.md](threads_wasm2c_wasix_concept.md)): `wasm2c` does not translate `memory.atomic.wait/notify` and starts no threads; WASIX replaces the wait by imports (`futex_*`) and needs a host that spawns a thread running the same module on a shared memory. The first step, if it is taken, is two instances on one shared memory, a thread each. Only noted.
8. **Typed function references:** say it clearly in `natify` when `wasm2c` stops at `call_ref` (the smallest step); the rest waits for a consumer.
9. **WASI 0.2 inside wasmext:** a host of 0.2 in C in the module would be a work of the size of `wasi_core.h` plus the canonical ABI; wasmext's own filesystem of 0.1 could be the base of the 22 to 28 filesystem methods. Not designed.
10. **A Python package with pre-built `meld`** and **moving `wabt-package` into the WebAssembly organisation (or into `WebAssembly/wabt`)**: drafts of two issues were sent to the owner as files; the second is not posted.

## 5. Waits for the owner (decisions)

- The questions of the context: `close` from inside a call or in another thread's call **refuses or waits** (the counter above is enough for refusing); whether the creation of a member checks that the module was built with the handler of traps; tags can wait.
- Whether to go on with idea 3 (it touches the ABI of the record of traps), and in what form.
- Whether to post the issue about `wabt-package`, and the one about `meld` on PyPI.
- Whether the ASan+UBSan job should run on every push or on a schedule, and whether the whole suite goes into it.
