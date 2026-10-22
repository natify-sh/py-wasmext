# WASI 0.2, WASI 0.3 and the component model: the state of the research

wasmext supports WASI 0.1 (`wasi_snapshot_preview1`, `wasi_unstable`) and **core modules only**. This page is the one place for everything that was tried, checked, rejected and
proposed about WASI 0.2 (preview 2), WASI 0.3 (preview 3) and components with a WIT interface of their own, to see what support would take. **Nothing here is built into wasmext**,
except the fix told in "A bug this found" and the example [`examples/wasi2_unbundled`](../examples/wasi2_unbundled) (not built by the CI).

It was put together on 2026-10-21 from three sources, each of which is now merged in and no longer a page of its own: the first page of this name (tried on 2026-10-20 and 2026-10-21), the report of
a neighbouring session on the component model (experiments A to D, "the first report" below), and the report of the same session on jco, meld and zwasm with four follow-ups ("the second
report"). Their data is kept; what was repeated and what changed is told in "Corrections" at the end. **The code of the experiments** is in [experiments/](experiments/): `component_model/`
(first report), `jco_zwasm/` (second report), `wasi_checks/` (the checks of 2026-10-21).

A later study, with the same program built for WASI 0.1 and 0.2 and used in three ways (a 0.1 module, `unbundle`, `meld fuse`), with the numbers of imports that a host has to give and the shims that the build
needed, is in [wasi_p1_vs_p2_host_requirements.md](wasi_p1_vs_p2_host_requirements.md).

## How to read the marks

Every finding says how it is known, because the results depend on the tools and the machine:

| Mark | Meaning |
| --- | --- |
| **[run]** | run in a session of this repository, on the machine named in "Tools" |
| **[again]** | run again on 2026-10-21 for this consolidation (the figures may differ in a few bytes: the path of the source is in the debug information) |
| **[reported]** | run by the neighbouring session; not repeated here |
| **[read]** | taken from source code or documentation; nothing was run |
| **[estimate]** | a figure or a judgement, not a measurement |

The paths in "Ways" are **possible paths, not decisions**; a decision is written as one.

## Summary

| Question | Answer | How known |
| --- | --- | --- |
| Does `wasm2c` read a component? | No: `error: wasm components are not yet supported in this tool` (`wasm-validate` says the same); `wasmext inspect` said `unsupported WebAssembly binary version 0d000100`; since `wasi_flavor` it says this is a component and to use `wasm-tools component unbundle` or `meld fuse` | [again] |
| How to get core modules out of a component? | `wasm-tools component unbundle` (modules **above `--threshold`, 10240 bytes by default**, are taken out; `--threshold 0` takes all) | [again] |
| Does the core module of a WASI 0.2 command run as a wasmext extension? | **Yes**, with a host of about 40 lines of Python (hello) or 156 (a TCP client with real sockets); `examples/wasi2_unbundled` | [run], its tests pass [again] |
| Does a WASI 0.3 C program run? | **Yes**, through `wasm2c` with a host of 94 lines of C (`printf`, `usleep`, stdin, stderr, clocks), about 100 KB stripped | [reported], [again] |
| Can two modules of two components be joined directly? | **No, and it is silent**: the pointer points into the other memory (`1` instead of `196`). An adapter per function is needed | [again] |
| Can a composed component be made into one flat wasm? | **Yes**: `meld fuse` gives one core module with one memory per component, or `jco transpile` / `wasmtime-environ` give the graph of modules and the list of built-in functions | [again] (meld, jco), [reported] (`wasmtime-environ` plan) |
| Does wasmext take such a module, with several memories? | **Yes, without changes**: `inspect`, `natify -i -b`, calls from Python | [again] (a minimal pair and the complex component) |
| Is meld right? | **0.64.0: not entirely** (a `list<string>` inside a returned `option<record>` arrives empty, `get=apple,3,[,]`; jco in Node gives `[red,big]`); **0.65.0: yes on this component** (fixed, checked 2026-10-22, see below). Issues [#512](https://github.com/pulseengine/meld/issues/512), [#513](https://github.com/pulseengine/meld/issues/513) | [again] |
| Wasmtime or zwasm as the runtime of the artifact? | Rejected as the main path: slower (Cranelift ~25 %, zwasm ~2.8 times by CoreMark), a runtime of 1 to 2.5 MB in each artifact, no 32-bit JIT | [reported]; zwasm's feature support [read] |
| A ready native layer of WASI 0.2 + the canonical ABI to put into `wasm2c`? | None that is drop-in; the nearest (Airbus' fork of WAMR) is tied to WAMR. Nobody gives the layer to Python | [read] |
| WASI 0.3 and Rust components (callback style)? | Need an event loop; not tried | — |

Where it leads (a proposal, with the order and the cost): "Ways".

## Tools

| Tool | Version | Where from | Used for |
| --- | --- | --- | --- |
| wasi-sdk | 34.0 (clang 23.1.0-wasi-sdk) | release tarball `wasi-sdk-34.0-x86_64-linux.tar.gz` (35 returned 404 when probed; 34.0 was the newest) | `wasm32-wasip1`, `wasm32-wasip2`, `wasm32-wasip3`, `wasm-component-ld` |
| wasm-tools | 1.262.0 (e22db44da, 2026-10-13) | release tarball, or `uv tool install wasm-tools-package` (on PyPI **only as a pre-release**, `1.262.0.0b1`: a prebuilt binary) | `component unbundle`, `component new`/`embed`, `print`, `component wit --json`, `compose`, `parse`, `validate` |
| wit-bindgen | 0.63.0 (0.64 to 0.70 returned 404 when probed) | release tarball | the C bindings of a guest (`wit-bindgen c`) |
| WABT | 1.0.42 (`wabt-package` 1.0.42.0, the only final release on PyPI) | PyPI | `wasm2c`, `wat2wasm` (multi-memory on by default); WABT `main` at `0086e24` (2026-10-21) was also built, see [abi_policy.md](abi_policy.md) |
| wasmext | `0.0.0.dev50+gd17bf3d88`, branch `poc-wasm2c-ext` for the reported runs; later commits of the branch for the runs [again] | `uv sync` | `inspect`, `natify -i -b -q`, the linking of instances |
| CPython | 3.11.17 (the venv), 3.13 (system), 3.15.0 (the first page) | | |
| jco | 1.39.0 | npm `@bytecodealliance/jco`; depends on `binaryen` ^132 (its own `wasm-opt`), `unenv`, `rolldown`; about 355 MB of `node_modules` | `jco transpile` |
| meld | 0.64.0 (`b26f1c8`, 2026-10-21) for the first runs; **0.65.0** (2026-10-22) for the check of the fixes | 0.65.0: the release tarball `meld-v0.65.0-x86_64-unknown-linux-gnu.tar.gz` (also aarch64 and Apple, musl; `SHA256SUMS.txt`); 0.64.0: built from source, `cargo build --release -p meld-cli` (1 min 52 s, a binary of 5 MB), or its release tarball. pulseengine, Apache-2.0. **Not on crates.io or PyPI**: the crate `meld` there is a project of Merkle trees (jerkytreats/meld), the package `meld` on PyPI is MELD of the Krishnaswamy Lab; neither is this tool | `meld fuse` |
| zwasm | 2.7.0 (`d74e63b`, Zig 0.16.0) | built from source | a WASI 0.2 host for wasm2c (the prototype `w2c_host`), AOT and JIT |
| Wasmtime, `wasmtime-environ` | 50.0.0 | crates.io (the crate of `wasmtime-environ` was downloaded on 2026-10-21 to count its kinds of built-in functions) | the minimal runtime, the AOT tool, the plan of a component |
| Rust, PyO3 | 1.97.0, 0.27 | | the experiments with Wasmtime |
| Machine | Linux x86-64; the first report a 2-core VM (timings noisy) | | |

Notes on the environment of 2026-10-21: GitHub's web pages answered 403 and the documentation sites were unreachable through the proxy, so the **links in "Sources" were not opened again**; what answered was
the raw `features.json`, `git ls-remote`, the registries (PyPI, npm, crates.io) and the release assets by URL. The GitHub API was not reachable on the first day either.

## Recognising what a file is

How to tell the WASI of a file before anything is generated:

- **Core module or component:** bytes 4 to 7 of the file. A core module has `01 00 00 00`; a component has `0d 00 01 00` (layer 1, version 0x0d).
- **A core module with WASI 0.1:** import modules `wasi_snapshot_preview1` or `wasi_unstable` (what wasmext reads today).
- **A core module taken out of a WASI 0.2 component:** import modules such as `wasi:io/streams@0.2.12`, `wasi:cli/stdin@0.2.12`, `wasi:sockets/tcp@0.2.12`; the export
  `wasi:cli/run@0.2.12#run` stands where `_start` stands. `0.2.x` is preview 2; `x` is a patch release (compatible), so a host supports a range.
- **A WASI 0.3 one:** `@0.3.0` in the names, and imports for the async machinery: `[async-lower]…`, `[stream-new-…]`, `[future-read-…]`, `$root.[waitable-set-…]`,
  `[subtask-…]`, `env.__wasm_{get,set}_{tls_base,stack_pointer}`.
- **A component before `unbundle`:** the names of its imports (`wasi:cli/stdin@0.2.12`) are in its import section. Reading them needs a small parser of the
  component format, which wasmext does not have.

A core module taken out of a WASI 0.2 component is not recognised as WASI by wasmext (it looks for the 0.1 names only), so its imports are shown as "the host has
to provide" and can be given as Python callables: `Instance({"wasi:io/streams@0.2.12": {"[method]output-stream.write": f, …}})`.

What wasmext said of a component **[again]**: `not a module wasmext can read: unsupported WebAssembly binary version 0d000100` (a `WasmError` raised in `src/wasmext/_wasm.py`). The recognition
described above is built as `wasmext.wasi_flavor` (`component`, `fused`, `core-0.1`, `core-0.2`, `core-0.3`, `none`, `unknown`): `parse()` refuses a component with what to do, `inspect` prints a `wasi:` line, `natify` warns (only) about 0.2, 0.3 and fused modules; `tests/test_wasi_flavor.py`. A module fused by meld carries custom sections of its own, among them `meld.signature-manifest` (when built with `--emit-manifest`),
`wsc.transformation.attestation`, `component-provenance` and `producers` **[again]**; the check "this module is already fused" could rest on `meld.*`, but those are names of a young tool, and they come only with `--emit-manifest`; **built** (2026-10-22) on the attestation that meld 0.64 writes in every module instead (`wsc.transformation.attestation`: `transformation_type` `fusion`, `tool.name` `meld`), so `wasi_flavor` says `fused` for the output of `meld fuse` as it is (0.64).

## What the tools do with a component

- **`wasm2c` and `wasm-validate`** stop at the first byte of a component: `error: wasm components are not yet supported in this tool` **[again]**.
- **`wasm-tools component`** has seven subcommands **[again]**: `new` (a component from a core module), `wit`, `embed` (metadata of a WIT into a core module), `targets`, `link` (dynamic library modules into a component),
  `semver-check` and `unbundle` (core modules out of a component). There is no tool in it that lowers a component to **one** core module. `unbundle` is the way to the core modules.
- **`unbundle` takes out only the modules above `--threshold`** (default **10240** bytes); smaller ones stay in the component. So a toy component of a few hundred bytes gives nothing, and the shim and the fixup of a real
  component stay inside by default, which is why the first page saw "only the main one" written. `--threshold 0` takes out all of them **[again]**. The output file `-o` and `--module-dir` have to be in existing directories.
  The modules are named `unbundled-module0.wasm`, `unbundled-module1.wasm`, … and the component without them is written to `-o` (`rest.wasm`).
- **`wasm-tools component embed WIT.dir --world W x.wat | wasm-tools component new`** builds a component from a hand-written core module without any compiler **[again]**: this is how the minimal pair of
  `experiments/wasi_checks/minimal` was made (the core module has to export `memory`, `cabi_realloc` and the functions named `<interface>#<function>`).
- **`wasm-tools compose A -d B -o C`** joins two components and prints that it is deprecated in favour of `wac`. It refuses a file name that is not in kebab case: `guest.component.wasm` fails with
  ``error: `provider.component` is not in kebab case``, so the files are copied to `provider.wasm` and `guestc.wasm` first **[again]**. `wac` was not tried.
- **`wasm-tools component wit --json`** lists the interfaces, functions and types of a component, a composed one included (`host {'lookup': [('key','string'), ('->','u32')], …}`), which is enough for a generator
  of typed glue without a WIT parser of our own **[run]** (the minimal pair **[again]**).

## What the core module of a component looks like

### WASI 0.2 with sockets (a C program)

A C program with `getaddrinfo`, `socket`, `bind`, `listen`, `accept`, `recv`, `send`, `connect` and `stdin`, built with
`clang --target=wasm32-wasip2 -O1` (it does not build for `wasm32-wasip1`: no `netdb.h`).

| | |
| --- | --- |
| component | 482 649 bytes; imports `wasi:io`, `wasi:cli`, `wasi:clocks`, `wasi:sockets/{network,instance-network,udp,udp-create-socket,tcp,tcp-create-socket,ip-name-lookup}` (all 0.2.12), exports `wasi:cli/run@0.2.12` |
| core modules in it | two: `$main` and a shim that is only a table of `call_indirect` stubs |
| after `unbundle` | `unbundled-module0.wasm` (the main one): 453 382 bytes with DWARF, 72 251 stripped; 78 function imports, **3 exports**: `memory`, `cabi_realloc`, `wasi:cli/run@0.2.12#run`; 250 functions, 1 table |
| `wasm2c` | exit 0; 1 308 290 bytes of C (33 706 lines); `cc -c` compiles it |

The sockets are **imports**, not exports. Representative ones, with the flattened core signature (a `result` comes back through a pointer that is a parameter):

| Import | Signature |
| --- | --- |
| `wasi:io/error [resource-drop]error` (and 10 more resource drops) | `(i32) -> ()` |
| `wasi:io/poll poll` | `(i32, i32, i32) -> ()` |
| `wasi:io/streams [method]input-stream.read` | `(i32, i64, i32) -> ()` |
| `wasi:io/streams [method]output-stream.write` | `(i32, i32, i32, i32) -> ()` |
| `wasi:cli/stdout get-stdout` | `() -> i32` |
| `wasi:clocks/monotonic-clock now` | `() -> i64` |
| `wasi:sockets/tcp-create-socket create-tcp-socket` | `(i32, i32) -> ()` |
| `wasi:sockets/tcp [method]tcp-socket.start-bind`, `start-connect` | fifteen `i32` `-> ()` (the network and a flattened `ip-socket-address`) |
| `wasi:sockets/tcp [method]tcp-socket.accept` | `(i32, i32) -> ()` |
| `wasi:sockets/ip-name-lookup resolve-addresses` | `(i32, i32, i32, i32) -> ()` |

Twenty-eight methods of `tcp-socket`, fourteen of the UDP sockets and streams, three of the name lookup, eleven resource drops, and the stdio and clock ones make the 78.

### WASI 0.3

Built the same program with `clang --target=wasm32-wasip3 -O1`: a component of 534 204 bytes, valid. `wasm2c` refuses the component as above. After `unbundle` the core
module (510 352 bytes) has 80 function imports and 5 exports: `memory`, `wasi:cli/run@0.3.0#run`, `__wasm_task_hook`, `cabi_realloc`, `__indirect_function_table`.
Compared with 0.2 the imports add the async machinery listed above (a socket `connect` is an `[async-lower]` call, the waits are on waitable sets). `wasm2c` translates
it (1 594 366 bytes of C) and `cc -c` compiles it. **Not tried:** anything that runs it.

The same programs built again on 2026-10-21 **[again]** (`examples/wasi2_unbundled/c/hello.c` and `sock.c`, `clang -O1`, wasi-sdk 34.0, `unbundle` with the default threshold), and the two programs of the first page for comparison:

| Program | Target | Component | Core module | Imports | Exports |
| --- | --- | --- | --- | --- | --- |
| `net.c` (sockets, name lookup, stdin) | `wasm32-wasip2` | 482 649 | 453 382 (72 251 stripped) | 78 | 3 |
| `net.c` | `wasm32-wasip3` | 534 204 | 510 352 | 80 | 5 |
| `hello.c` | `wasm32-wasip2` | 226 639 (226 626 on the first page) | 219 128 (219 115) | 21 | 3: `memory`, `wasi:cli/run@0.2.12#run`, `cabi_realloc` |
| `sock.c` (23 lines) | `wasm32-wasip2` | 428 937 (428 924) | 401 300 (401 287) | 74 | 3 |
| `hello.c` | `wasm32-wasip3` | 277 652 | 270 191 | 33 | 5: `memory`, `wasi:cli/run@0.3.0#run`, `__wasm_task_hook`, `cabi_realloc`, `__indirect_function_table` |
| `sock.c` | `wasm32-wasip3` | 481 575 | 458 476 | 79 | 5 |

The difference of 13 bytes from the first page is the path of the source in the debug information. `wasm2c` and `cc -c` pass on every one of them **[again]** (`hello` p3: 553 373 bytes of C, 14 251 lines; `sock` p2: 1 092 921
bytes, 28 611 lines; `sock` p3: 1 372 740 bytes, 35 189 lines; the first page: 1 308 290 bytes and 33 706 lines for `net.c` p2, 1 594 366 bytes for p3), and `wasmext inspect` ends with `result: can be wrapped`
(p3 `sock`: 253 functions, 1 memory, 1 table, 19 globals, a start function). The imports that p3 adds to p2 are the async machinery: `[async-lower]wait-for`, `[stream-new-0]read-via-stream`,
`[future-read-1]…`, `$root` `[waitable-set-new|wait|poll|drop]`, `[waitable-join]`, `[subtask-cancel|drop]`, `env.__wasm_{get,set}_{tls_base,stack_pointer}` **[again]**.

### A component with a WIT of its own

The WIT (package `demo:text@0.1.0`): the interface `host` (`lookup: func(string) -> u32`, `log: func(string)`) is imported; the interface `api` is exported, with
`greet(string) -> string`, `birthday(person) -> person` (`record person { name: string, age: u32, nick: option<string> }`), `parse(string) -> result<u32, string>`,
`rev(list<u8>) -> list<u8>`, `area(shape) -> u32` (`variant shape { circle(u32), rect(tuple<u32,u32>), none }`) and `resource counter` (a constructor, `bump`,
and a static `make-default`).

`wit-bindgen c` made `lib.c`, `lib.h` and `lib_component_type.o`; with wasi-sdk 34 the object **must be linked** for `wasm32-wasip2` (without it: `undefined symbol:
__component_type_object_force_link_lib`). The component is 145 348 bytes and has three core modules (`$main`, the shim, and a fixup that fills the shim's table);
`unbundle --module-dir` wrote only the main one (140 442 bytes with DWARF). `wasm2c` and `cc -c` pass; `wasm-objdump`: 56 functions, 1 memory, 1 table, 5 globals.

The exports of that core module, which are the interface:

| Export | Core signature |
| --- | --- |
| `demo:text/api@0.1.0#greet` | `(i32, i32) -> i32` |
| `demo:text/api@0.1.0#birthday` | six `i32` `-> i32` |
| `demo:text/api@0.1.0#parse` | `(i32, i32) -> i32` |
| `demo:text/api@0.1.0#rev` | `(i32, i32) -> i32` |
| `demo:text/api@0.1.0#area` | `(i32, i32, i32) -> i32` |
| `demo:text/api@0.1.0#[constructor]counter` | `(i32) -> i32` |
| `demo:text/api@0.1.0#[method]counter.bump` | `(i32, i32) -> i32` |
| `demo:text/api@0.1.0#[static]counter.make-default` | `() -> i32` |
| `demo:text/api@0.1.0#[dtor]counter` | `(i32) -> ()` |
| `cabi_post_demo:text/api@0.1.0#greet`, `#birthday`, `#parse`, `#rev` | `(i32) -> ()` |
| `cabi_realloc` | `(i32, i32, i32, i32) -> i32` |
| `memory`, `wasi:cli/run@0.2.12#run` | |

The imports (six): `demo:text/host@0.1.0` `lookup (i32, i32) -> i32` and `log (i32, i32) -> ()`; `[export]demo:text/api@0.1.0.[resource-new]counter (i32) -> i32`;
and three of `wasi:cli` (`get-arguments`, `exit`, `exit-with-code`) that the C library brings.

How the values are passed, as the signatures show:

- a `string` or a `list` argument is `(ptr, len)`; a `record` is flattened to its fields (`person`: the name's pointer and length, the age, the discriminant of the
  `option`, the nick's pointer and length: six `i32`); a `variant` is `(tag, payload0, payload1)`; a resource handle is one `i32`;
- a string, a list, a record or a `result` that comes back is one `i32`, a pointer to an area of the linear memory: `(ptr, len)` for a string or a list, a discriminant and the
  payload for a `result`;
- `cabi_post_*` exist only for the functions that return heap data; each takes the pointer that function returned;
- a host import takes `(ptr, len)` for a string. The types do not show in the core signatures: a string and a record differ only in the WIT.

### A composed component

Two components (a provider exporting `shout(string) -> string`, a consumer importing it), joined by `wasm-tools compose` (it says it is deprecated in favour of `wac`): 278 383 bytes,
six core modules in all (a `$main`, a shim and a fixup in each of two nested components). `unbundle` wrote the two main ones. They **do not import or export each other**: each has its
own memory and its own `cabi_realloc`. The wiring is only in the component: the provider's exported instance is given to the consumer's import, and the call goes through
`canon lower` (the consumer's memory and realloc) and `canon lift` (the provider's memory, realloc, `post-return`, `string-encoding=utf8`), which copy and transcode the string between the
memories. That is not core code, so it is not in what `unbundle` gives. There was no adapter module.

Again on a minimal pair made from WAT **[again]** (a provider exporting `host.lookup(string) -> u32`, a guest importing it): with `--threshold 0` the composed component gives **four** modules — the guest (imports
`lookup`), the provider (exports `lookup`), a shim (exports a table `$imports` and an indirect stub) and a fixup (imports `actual` and the shim's table) — and a `rest.wasm` with three `canon` lines (a `canon lower` for the guest's
import, a `canon lift` for each export). The two main modules share nothing: each has its own memory and its own `cabi_realloc`.

## What was run

### A WASI 0.2 command on a Python host

Tried on 2026-10-21: wasi-sdk 34.0, wasm-tools 1.262.0 (installed with `uv tool install wasm-tools-package`, which gives the `wasm-tools` binary without a download from GitHub), CPython 3.15.0, Linux x86-64, wasmext of this branch.

The program: `int main(void) { printf("hello from wasip2\n"); return 3; }`, built with `clang --target=wasm32-wasip2 -O1`: a component of 226 626 bytes. `wasm-tools component unbundle` wrote one core module (219 115 bytes, copied to `hello02.wasm` because `natify` refuses a name with a hyphen) with 21 imports and 3 exports: `memory`, `cabi_realloc` and `wasi:cli/run@0.2.12#run` `() -> i32`.
`wasmext inspect` listed all 21 imports as "the host has to provide" (all `ok`) and ended with `result: can be wrapped`; `wasmext natify -i -b -q hello02.wasm` built the extension (abi3) and its `.pyi`.

The host is a dictionary of Python callables given to `Instance(...)`, one entry for each import, with the instance reached through a holder (`box["inst"]`) because the imports are made before it. What it does, as the signatures of the table above say:
- the drops, `pollable.block`: nothing; `get-stdin`, `get-stdout`, `get-stderr`: a number that stands for the stream (a handle table of our own);
- `get-terminal-*(retptr)`: writes the byte 0 (an `option` that is `none`) at `retptr` in the memory;
- `[method]output-stream.check-write(self, retptr)`: byte 0 (`ok`) at `retptr`, and a `u64` at `retptr + 8` (4096 bytes may be written);
- `[method]output-stream.write(self, ptr, len, retptr)`: writes `bytes(memory[ptr:ptr+len])` to the stream, byte 0 (`ok`) at `retptr`;
- `[method]output-stream.blocking-flush(self, retptr)`: byte 0; `subscribe`, `subscribe-duration`: a new number; the clocks: `time.monotonic_ns()` and a `datetime` (`u64` seconds, `u32` nanoseconds) at `retptr`;
- `poll(ptr, n, retptr)`: asks `cabi_realloc` for room, writes the indices of the ready pollables and the pair (`ptr`, `n`) at `retptr` (written, **not called** by this program).

Result: `inst["wasi:cli/run@0.2.12#run"]()` printed `hello from wasip2` and returned `1`. Eight calls of five imports were made (`get-stdout`, `get-terminal-stdout`, `output-stream.check-write`, `.write`, `.blocking-flush`); the clocks, `poll`, stdin and `subscribe` were not called. The `1` is the `err` of the `result` of `run`, because `main` returned 3; the 3 itself is not in it. The names with `:` and `#` are reached with `inst["…"]` or `getattr`.

What this shows: a WASI 0.2 command can be hosted by the extension with no change to wasmext, by Python callables, as "Ideas for the host of an unbundled module" says. What it does not show: a program that reads stdin, `poll` and `cabi_realloc` in use (the socket run below uses them), speed, a component with a WIT of its own, WASI 0.3, or a product with no Python (the program and the shared library have no such host).

#### The same, with a TCP socket

Tried the same day, the same tools. The program (`sock.c`, 23 lines) does `socket(AF_INET, SOCK_STREAM, 0)`, `connect` to 127.0.0.1:47123, `send("ping")`, `recv`, prints `reply: %s`: a component of 428 924 bytes; the core module after `unbundle` is 401 287 bytes with **74 imports** (28 of `tcp`, 20 of `udp`, streams, poll, clocks, `cli`; no name lookup) and the same three exports.

The host (`run_sock.py`, 156 lines of Python, scratch work, not in the repository) differs from the first one in these ways:
- a table of handles of its own: a number stands for a Python object (a socket, a stream, a pollable); `[resource-drop]*` removes the entry;
- the imports are generated from the import section (`wasm-objdump -x`) and all but the written ones raise `NotImplementedError("<name>")`; the module needs every import to be there, not every one to work;
- `create-tcp-socket(family, retptr)`: byte 0 (`ok`) and the handle at `retptr + 4`; `start-connect(self, network, tag, port, a, b, c, d, …, retptr)`: the `ip-socket-address` arrives **flattened** (a tag and then 11 more `i32`; for IPv4 the port and the four bytes are the first five), the host keeps the address; `finish-connect(self, retptr)` does the Python `connect` and writes `ok` and **two** handles (`retptr + 4` the input stream, `retptr + 8` the output stream);
- `input-stream.read(self, len, retptr)`: nothing to read yet is an empty list, not a wait; data is put in memory got from `cabi_realloc` and `(ptr, len)` written at `retptr + 4` and `+ 8`; the end of the stream is `err(stream-error::closed)` (bytes `1`, `1` at `retptr` and `retptr + 4`); the stream's `subscribe` gives a pollable whose readiness is `select` on the socket; `pollable.block` and `poll` wait for it.

A thread of the host listened on the port. Result: the server got `b'ping'`, the program printed `reply: pong`, and `run` returned `0`. Sixteen imports were called (among them `instance-network`, `create-tcp-socket`, `start-connect`, `finish-connect`, `input-stream.read` twice (the first answered empty), `input-stream.subscribe`, `pollable.block`, the output stream, the drops); `poll` was not (the libc blocked on one pollable), and no stub was reached.

Not tried: `bind`/`listen`/`accept`, UDP, `ip-name-lookup` (so a host name), IPv6, an error from the network (a refused connection and the mapping of its `error-code`), a large transfer, several pollables at once, closing from either side while the other writes. Note what this gives: WASI 0.1 in wasmext has no sockets (`sock_*` answer `ENOTSOCK`), and a WASI 0.2 program with the Python host above has them, because the host is the user's.

The two programs and the host are in [`examples/wasi2_unbundled`](../examples/wasi2_unbundled) (with tests; not built by the CI).

### WASI 0.3: a C program through `wasm2c` with a host of 94 lines of C

**[reported]**, the build and the output **[again]** in part (see "To repeat it"). The sources (`p3test.c`, `p3host.c`, `p3host.h`, `gen_p3.py`, `h3_main.c`) are in
[experiments/jco_zwasm/p3](experiments/jco_zwasm/p3/).

**What the core module of a `wasm32-wasip3` C program imports** after `unbundle`:
- the WASI functions `@0.3.0`, including the async-lowered `[async-lower]wait-for` and `wait-until`;
- the built-in functions `stream` and `future` with the types in the names (`[stream-new-0]`, `[async-lower][stream-write-0]…`, `[async-lower][future-read-1]…`, `[stream-drop-*]`, `[future-drop-readable-*]`);
- `$root` `[waitable-set-new|join|wait|poll|drop]`, `[subtask-cancel|drop]`;
- `env` `__wasm_get/set_stack_pointer`, `__wasm_get/set_tls_base`; in the component these are `context.get/set`.

The export `wasi:cli/run@0.3.0#run` is lifted through `hook0` of the fixup module: `__wasm_task_hook(0); run(); __wasm_task_hook(1)`.

**The host `p3host.c` (94 lines)** and the generator `gen_p3.py` (84 lines):
- one table of waitables for an instance;
- `stream.new` returns `(writable << 32) | readable`;
- `write-via-stream` takes the readable end, and the host writes to fd 1 or 2: `stream.write` at once gives `COMPLETED`, that is, `(n << 4) | 0`;
- `future.read` completes when the writable end is closed, and otherwise returns `BLOCKED` and queues an event for `waitable-set.wait`;
- stdin is a stream with the source fd 0;
- `wait-for` and `wait-until` are `nanosleep` and `RETURNED`;
- the clocks through `clock_gettime`;
- `context` is two `u32`.

```sh
clang --target=wasm32-wasip3 -O1 p3test.c -o t3.component.wasm
wasm-tools component unbundle t3.component.wasm --module-dir unb -o unb/rest.wasm && cp unb/unbundled-module0.wasm t3.wasm
wasm2c t3.wasm -o t3.c -n t3 && python gen_p3.py t3.wasm t3
cc -O2 -I<wabt>/wasm2c t3_main.c t3.c t3_imports.c p3host.c wasm-rt-*.c -lm
echo "a line from host stdin" | ./t3_native
```

```
slept >= 20ms: yes (20 ms)
stdin: a line from host stdin
to stderr
year >= 2026: yes
[p3] run -> 0; stream.write 4 (85 bytes), future.read 0, ...
# with </dev/null: "stdin: EOF", future.read 1, run -> 0
```

The program uses `printf`, `usleep` (through `wait-for`), `fgets` from stdin (a stream), `fprintf(stderr)` and `time`; all of it ran, and the binary after `strip` takes **96 KB**. The zwasm host for 0.2 gave 1.8 MB. This is one more argument for a host in C.

**What this host cannot do**, that is, what full 0.3 needs:
- an event loop for callback lifting (Rust): calling the `[callback]` export until the task finishes;
- streams between guests;
- subtasks with a real `BLOCKED`;
- cancellation;
- `backpressure`;
- cooperative threads (`thread.*`, the `context` slots);
- WASI 0.3 sockets, filesystem and http.

The code of zwasm `async.zig` (1.5 thousand lines) and `component_wasi_p3*.zig` (~4.1 thousand) is good as a reference for the callback style, and the style with blocking in `wait`, as shown above, is simpler for wasm2c.

zwasm does not run such a program: in `component_wasi_p2.zig` the operation `waitable-set.wait` is rejected with `UnsupportedWasiImport`, because zwasm supports the stackless (callback) style of asynchrony, in
which `WAIT` is returned, and not a `wait` called from the guest; wasi-libc for C makes `run` synchronous and blocks exactly in `waitable-set.wait`. The claimed 45/45 of zwasm is about the corpus of Rust components in
callback style, which was not checked (no Rust toolchain for `wasm32-wasip3` here). Run: `zig build install -Doptimize=ReleaseFast -Dwasi=p3` (zwasm v2.7.0, wasm: v3_0, wasi: p3), then `zwasm run hello3.component.wasm`
gives `cannot run component 'hello3.component.wasm': UnsupportedWasiImport`.

### Host functions between two modules (experiment A of the first report)

This is where the question "can the host functions of a WIT be generated with `wit-bindgen` and attached to a guest extension?" was tried. **[reported]**; the key finding was reproduced on a smaller pair **[again]**.
The code is in [experiments/component_model](experiments/component_model/README.md): `demo.wit`, `guest_impl.c`, `provider_impl.c`, `run.py`, `adapter.wat`, `commands.sh`.

**About the terms, because it matters later.** "Host" in a WIT is only the name of an interface (`interface host`) that the guest imports. The real host is native code outside wasm (an embedder) that does
`canon lower`/`canon lift`, that is, moves data between the memories of the modules and its own world. `wit-bindgen` generates the **guest** side only, that is, code that is itself compiled to wasm.

So the implementation of the interface `host` was written as **one more guest**: a separate world `provider` that **exports** this interface (`demo.wit`: the interfaces `host` with `lookup(string) -> u32` and
`log(string)`, `api` with `greet(string) -> string`, `inspect` with `last-log` and `calls`; the worlds `guest` and `provider`). wit-bindgen generated ordinary guest code for it. Both components went through `unbundle` and
then `natify`, and then it was checked whether their core modules can be joined by the instance linking of wasmext. wit-bindgen did not give a real host, that is, the moving of data between memories. It was written by
hand, and that is the main finding of the experiment.

The signatures that `wit-bindgen c` generated (`wit-bindgen c wit --world guest --out-dir gen_guest`, the same for `provider`):

```c
// gen_guest/guest.h
extern uint32_t demo_text_host_lookup(guest_string_t *key);
extern void demo_text_host_log(guest_string_t *msg);
void exports_demo_text_api_greet(guest_string_t *name, guest_string_t *ret);

// gen_provider/provider.h
uint32_t exports_demo_text_host_lookup(provider_string_t *key);
void exports_demo_text_host_log(provider_string_t *msg);
void exports_demo_text_inspect_last_log(provider_string_t *ret);
uint32_t exports_demo_text_inspect_calls(void);
```

The arguments of an export belong to the callee: they must be freed with `*_string_free`. A returned string is freed by `cabi_post_*`. The values expected from `lookup`: `"Murphy"` → **735**, `"wasm"` → **20**.

Build (`clang --target=wasm32-wasip2 -O1 -mexec-model=reactor`, then `unbundle`, then the core module copied to `_guest.wasm` / `_provider.wasm`, because `natify` refuses a name with a hyphen, then
`wasmext natify -i -b -q _guest.wasm _provider.wasm`):

| File | Size | Imports | Exports |
|---|---|---|---|
| `guest.component.wasm` | 271 953 | | |
| `_guest.wasm` (core) | 263 804 | 23: `demo:text/host@0.1.0` `lookup (i32,i32)->i32`, `log (i32,i32)`; 21 more from `wasi:io`, `wasi:cli`, `wasi:clocks` (libc pulls them in) | `memory`, `_initialize`, `cabi_realloc`, `demo:text/api@0.1.0#greet (i32,i32)->i32`, `cabi_post_demo:text/api@0.1.0#greet` |
| `provider.component.wasm` | 53 798 | | |
| `_provider.wasm` (core) | 52 279 | **0** | `memory`, `_initialize`, `cabi_realloc`, `demo:text/host@0.1.0#lookup (i32,i32)->i32`, `#log (i32,i32)`, `demo:text/inspect@0.1.0#last-log () -> i32`, `#calls`, `cabi_post_…#last-log` |
| `_guest.abi3.so` / `_provider.abi3.so` | 143 072 / 57 024 after `strip` (1 192 680 / 475 672 before it) | | |

The core signature of the guest's import is the same as the core signature of the provider's export. The list of the guest's WASI imports was taken from `wasm-tools print` into `guest_imports.json`, to put stubs in their place.

**Three ways of joining** (`run.py`): `direct` (the provider's functions given to the guest as its imports), `adapter` (a Python function copies the string from the guest's memory into the provider's through the
provider's `cabi_realloc` and calls its export) and `wasm-adapter` (the same adapter in wasm, `adapter.wat`, with the two memories as imports and `memory.copy`; no Python on the path of the call).

```sh
wat2wasm adapter.wat -o _adapter.wasm     # multi-memory is on by default in WABT 1.0.42 (there is only --disable-multi-memory)
wasmext inspect _adapter.wasm             # guest.memory, prov.memory: "ok (the memory of another instance)"; result: can be wrapped
wasmext natify -i -b -q _adapter.wasm
```

**The cycle of dependencies.** The adapter needs the guest's memory before the guest is made, and the guest needs the adapter's functions. It was broken like this: the guest's memory was moved into a separate holder module, and the guest was rewritten so that it imports it.

```sh
wasm-tools print _guest.wasm > g.wat
# remove "(memory (;0;) 2)" and insert after the last import:  (import "env" "memory" (memory (;0;) 2))
wasm-tools parse g2.wat -o _guest2.wasm && wasm-tools validate _guest2.wasm
echo '(module (memory (export "memory") 2))' > _memhold.wat && wasm-tools parse _memhold.wat -o _memhold.wasm
wasmext natify -i -b -q _guest2.wasm _memhold.wasm
```

Not checked: whether `-Wl,--import-memory` when the guest is linked gives the same without rewriting the WAT.

**Results** (each mode was also run on 301 calls):

| Mode | `greet('Murphy')` | `last-log` of the provider | Conclusion |
|---|---|---|---|
| `direct` | `'hello, Murphy #0'` (`#735` expected) | `''` | **Rejected.** There is no `LinkError`, because the signatures match and the call goes C to C. But `(ptr, len)` points into the guest's memory while the provider reads its own. The provider also does a `free()` on a foreign pointer, that is, quietly corrupts its own heap. 300 calls did not trap, and that is more dangerous than if there had been a trap. |
| `adapter` (Python) | `'hello, Murphy #735'` | `'greet(Murphy)'` | Works. Copying the string is `canon lower` by hand. |
| `wasm-adapter` | `'hello, Murphy #735'` | `'greet(Murphy)'` | Works, and there is no Python on the path of the call. Needs multi-memory and the guest's memory taken out. |

**Conclusion of A.** Functions with scalar types only (`u32`, `f64`, …) can be joined by a direct link already now. For `string`, `list` and `record` between modules an adapter is needed for each WIT function. Not checked: a string *returned* by the provider (the adapter has to read it back into the guest's memory and call `cabi_post_*`), a variant, resources.

**Reproduced [again]** on the smallest pair that can be written by hand, with no compiler (`experiments/wasi_checks/minimal`: a provider exporting `host.lookup(string) -> u32`, a guest importing it, both made from WAT with
`wasm-tools component embed` and `component new`, then `unbundle --threshold 0`): joined directly the guest gets `1` where `196` is expected, and no error; through the adapter in Python it gets `196`. The string is read
from the wrong memory, and nothing traps. The same holds for the pair as a composed component (below).

### Without `unbundle`: a guest built as `wasm32-wasip1`

* **A short way without `unbundle`.** The same guest built as `wasm32-wasip1`:

```sh
$SDK/bin/clang --target=wasm32-wasip1 -O1 -mexec-model=reactor -o _guest_p1.wasm \
    guest_impl.c gen_guest/guest.c gen_guest/guest_component_type.o
$W inspect _guest_p1.wasm
#   imports (6): demo:text/host@0.1.0.lookup, .log,
#                wasi_snapshot_preview1.clock_time_get, fd_close, fd_seek, fd_write
#   exports: memory, _initialize, cabi_realloc, demo:text/api@0.1.0#greet, cabi_post_…#greet
#   result: can be wrapped
```

wasmext already serves WASI 0.1 itself, so only the two imports from the WIT remain. The minus: there are no sockets in 0.1.

### The WIT types without a WIT parser of our own

* **The types are available without Rust.** This was checked:

```sh
$WT component wit --json guest.component.wasm
#   host  {'lookup': [('key','string'), ('->','u32')], 'log': [('msg','string'), ('->', None)]}
#   api   {'greet':  [('name','string'), ('->','string')]}
```

The test above is `wasm-tools component wit --json`; the minimal pair gave the same kind of listing **[again]**.

### Composing, then unbundling a composed component, and `jco transpile` (experiment C of the first report)

```sh
cp provider.component.wasm provider.wasm && cp guest.component.wasm guestc.wasm   # compose wants kebab-case names
$WT compose guestc.wasm -d provider.wasm -o composed.wasm   # WARNING: deprecated, use wac
$WT component wit composed.wasm      # imports only wasi:*, exports demo:text/api@0.1.0 (host is wired inside)
$WT component unbundle composed.wasm --module-dir unb_comp -o unb_comp/rest.wasm
#   unbundled-module0.wasm 263 804   (= _guest.wasm)
#   unbundled-module1.wasm  52 279   (= _provider.wasm, byte for byte)
#   rest.wasm               13 427   with 22 "canon lift" / "canon lower"
```

`composed.wasm` takes 327 874 bytes. `unbundle` gives the same two modules as in "Host functions between two modules", and all the wiring stays in `rest.wasm`. This is exactly the situation of `direct`, that is, the wrong one.

Again **[again]** on the minimal pair: see "A composed component" above (four modules with `--threshold 0`, the wiring in `rest.wasm`).

#### `jco transpile`

```sh
npm i @bytecodealliance/jco          # 1.39.0
npx jco transpile composed.wasm -o out --no-typescript
#   out/composed.core.wasm   263 804   (guest)
#   out/composed.core2.wasm   52 279   (provider)
#   out/composed.js          237 555   (glue) + base64-embedded modules
```

The modules embedded in `composed.js` as base64 were taken out like this:

```python
import base64
import re

s = open("out/composed.js").read()
for m in re.finditer(r"const (module\d+) = base64Compile\('([^']+)'\)", s):
    open(f"{m[1]}.wasm", "wb").write(base64.b64decode(m[2] + "=="))
```

| Module | Size | Role |
|---|---|---|
| `module1` | 283 | shim: 10 functions that call the table `$imports` through `call_indirect` |
| `module2` | 264 | fixup: fills the shim's table (`import "actual" "0".."9"`, `shim.$imports`) |
| `module4` | 88 | calls `main._initialize` |
| `module5` | 755 | **FACT adapter**: exports `adapter0`/`adapter1` (`lookup`/`log`) |

The imports of the FACT adapter, that is, what jco implements in JS and what would have to be written in C:

```
flags.instance1, flags.instance4         (mut i32 globals: may-enter / may-leave)
memory.m0                                 (the memory of one side)
realloc.f0                                (cabi_realloc of the callee)
callee.adapter0 / adapter1                (the provider's exports)
transcode."utf8-to-utf8 (mem1 => mem0)"   (copy between memories; in JS 5 lines)
context.get0/get1/set0/set1
async.enter-sync-call / exit-sync-call
runtime.trap23 / trap30
augments."mem1 MemorySize"
```

`wasmext inspect` on `module1`, `module2` and `module5` gives `result: can be wrapped`.

**Conclusion of this experiment.** A nested component can be flattened at build time into a graph of core modules that wasmext already knows how to link (functions, memory, globals, `funcref` tables). What is missing
is a runtime of built-in functions in C, an interpreter of the instance graph, and a typed layer outside. **Risk:** the names and the set of FACT imports are an implementation detail of `wasmtime-environ`, not a
specification. An end-to-end run through wasmext of the graph made by jco was not made by that report; the simple component was done by hand with 3 core modules and 9 built-in functions in C by the second report
(below).

## Flattening a composed component into core modules

Three ways were tried or read, all at build time and all giving something that `wasm2c` and wasmext can take: `jco transpile` (a graph of core modules plus JavaScript), `meld fuse` (one core module) and
`wasmtime-environ` called as a library (the plan, with no JavaScript). The code of the second report is in [experiments/jco_zwasm](experiments/jco_zwasm/README.md) (`complex/`, `meld/`, `envplan/`, `p3/`), as it came.

### The two components of the second report

Two test composed components (`wasm-tools compose guest.wasm -d provider.wasm`):

- **simple:** an interface `host { lookup(string) -> u32, log(string) }`; the guest exports `api.greet(string) -> string`;
- **complex:** an interface `store` with the types `record item { name: string, qty: u32, tags: list<string> }`, `variant shape`, `enum level`, `flags perms` and `resource counter` (a constructor, `bump`, `label`). The functions: `put(item) -> result<u32, string>`, `get(u32) -> option<item>`, `area(shape) -> u64`, `classify`, `check`, `sum(list<u32>) -> u64`, `make(u32) -> counter`, `peek(borrow<counter>)`. The guest exports `app.run-all() -> string`, which calls all of this.

The reference is Wasmtime on the same components:

```
simple : greet(Murphy) = hello, Murphy #735 · greet(wasm) = hello, wasm #20 · greet(Мерфі) = hello, Мерфі #512
complex: put=ok:0;put0=err:qty must be > 0;get=apple,3,[red,big];get9=none;area=48,42,0;level=0,1,2;perms=3;sum=4000000006;counter=15,counter=15,peek=100
```

### `jco transpile`: what it does and how much glue it makes **[reported]**

`jco transpile` uses `wasmtime-environ` (through `js-component-bindgen`) to take a component apart. The result:
- core modules: the original ones plus generated shim, fixup and FACT adapters;
- a **JS file** that instantiates these modules in the right order and implements the built-in functions: resource tables, transcoding, flags, traps, and also WASI through `preview2-shim`.

How much glue, the simple component against the complex one:

```sh
npx jco transpile composed.wasm   -o out    --no-typescript
npx jco transpile cxcomposed.wasm -o cx/jco --no-typescript
# the modules in base64 in the JS were taken out with a script; the imports were counted with wasm-tools print
```

| | Simple | Complex |
|---|---|---|
| JS | 237 555 bytes | 334 256 bytes |
| core modules | 2 original + 4 generated | 2 original + 6 generated |
| FACT adapters | 1 (755 bytes) | 2 (923 and 2934 bytes) |
| JS trampolines | 9 | 21 |
| built-in functions that the FACT modules import | `enter/exit-sync-call`, `flags`, `context.get/set`, `transcode utf8 (mem1→mem0)`, `mem1 MemorySize`, `realloc`, 2 traps | the same plus `resource.transfer-own/borrow`, `transcode utf8 (mem0→mem1)`, `mem1 I32Load/I32Store/I32Store8`, `post_return` ×3, `realloc` ×2, 6 traps |

Where the increase of JS trampolines in the complex one comes from: 18 of the 21 are operations on resource tables (`handleTable…`, `rscTableRemove`, `resourceTransferOwn/Borrow`) for the one resource `counter`, one for each pair (instance, resource type). Another 3 are checks of bounds and of discriminants. So the glue grows **with the number of resources, memories and crossings of a boundary**, not with the number of functions: in neither test did the functions add any JS.

`mem1 I32Load/I32Store` means that the jco adapter reaches the second memory through the host, not through multi-memory. In C these are trivial functions, or simply multi-memory (see "`meld fuse`").

How many kinds there are in all: the full list of the kinds of built-in functions is the variants of `enum Trampoline` in `wasmtime-environ` 50 (`src/component/info.rs`), **52 in all [again]** (counted in the crate downloaded on 2026-10-21):

- **synchronous (~10):** `LowerImport` (a host import, that is, WASI), `Transcoder`, `ResourceNew/Rep/Drop`, `ResourceTransferOwn/Borrow`, `Trap`, `EnterSyncCall/ExitSyncCall`;
- **asynchronous, WASI 0.3:** `TaskReturn/Cancel`, `WaitableSet*`, `Subtask*`, `Stream*`, `Future*`, `ErrorContext*`, `PrepareCall/StartCall`, `Backpressure*`, `Thread*`.

**Conclusion:** the glue of jco grows, but these are instances of a fixed set of kinds. In C each kind is written once (the synchronous ones, tens of lines each), and the table of instances is generated. For the simple component this has already been done by hand: 3 core modules through wasm2c and 9 built-in functions in C, and the results matched Wasmtime.

jco 1.39.0 was also run again on the minimal pair of `experiments/wasi_checks/minimal` **[again]**; the figures above are for the reporter's two components and were not reproduced, and the size of the JS differs on a
smaller component, as is to be expected. The first report ran `jco transpile` on its composed component too (the modules in base64, the FACT adapter and its imports: "Composing, then unbundling a composed component",
above).

### `meld fuse`: one core module

meld is a tool of pulseengine (Apache-2.0); 0.64 came out on 2026-10-21. At build time it fuses a composed component (several components joined through WIT) into **one** core module. Each component keeps its own memory
(multi-memory), and the Canonical ABI adapters between them are generated at once as plain wasm code: `cabi_realloc` in the memory of the callee, plus `memory.copy`. The component model between components then
needs no runtime: `wasm2c` compiles everything together, and only WASI and a few built-in resource functions are left to the host. **There is no need to take the component apart before meld**: it takes a component
directly, composed or several separate ones. For a single component `wasm-tools component unbundle` is enough, and meld is not needed (meld accepts a single one as well, which was not run).

**[reported]** (the figures); the result on the minimal pair and the bug **[again]**:

```sh
git clone https://github.com/pulseengine/meld && cargo build --release -p meld-cli     # 1 m 49 s
meld fuse composed.wasm   -o composed.fused.wasm   --exports world --explain --emit-import-map composed.imports.json
meld fuse cxcomposed.wasm -o cxcomposed.fused.wasm --exports world --explain --emit-import-map cxcomposed.imports.json
```

| | Simple | Complex |
|---|---|---|
| result | one core module, 321 539 bytes, `wasm-tools validate` ok | one core module, 499 878 bytes, ok |
| memories | 2 (multi-memory, one per component) | 2 |
| crossings of a boundary (`--explain`) | 2, both `memory-copy` | 11, all `memory-copy` |
| imports | 21 WASI | 42 WASI (two copies: one for each component, the second with the suffix `$2`) and 5 built-in resource functions of `counter` (`[resource-new]`, `[resource-rep]` ×2, `[resource-drop]`) |
| exports (`--exports world`) | `greet`, `cabi_post`, `memory$0`, `cabi_realloc$1` | `run-all`, `cabi_post`, both memories and both `cabi_realloc`, `[dtor]counter` |

Then wasm2c (multi-memory is on by default in WABT 1.0.42) and the glue `fused_glue.py` (115 lines). The glue does three things:
- gives every WASI import to the zwasm host ("A WASI 0.2 host for `wasm2c`"), and chooses the memory and `cabi_realloc` by the suffix `$N` (the number of the component);
- for the built-in functions of resources keeps one table in C, and `drop` calls the export `[dtor]`;
- generates the arguments for `instantiate`.

```sh
wasm2c composed.fused.wasm -o fa.c -n fa
python fused_glue.py composed.fused.wasm fa --mem DEFAULT=memory0x240:cabi_realloc0x241
python fused_glue.py cxcomposed.fused.wasm fb --mem DEFAULT=memory0x240:cabi_realloc0x241 --mem 2=memory:cabi_realloc \
       --dtor counter=demo0x3Acx0x2Fstore0x4000x2E10x2E00x230x5Bdtor0x5Dcounter
cc -O2 -I<wabt>/wasm2c fa_main.c fa.c fa_glue.c wasm-rt-*.c libzw_w2c_host.a -lm -lpthread
```

Results:

```
fa: greet(Murphy) -> hello, Murphy #735 · greet(wasm) -> hello, wasm #20 · greet(Мерфі) -> hello, Мерфі #512     = Wasmtime
fb: put=ok:0;put0=err:qty must be > 0;get=apple,3,[,];get9=none;area=48,42,0;level=0,1,2;perms=3;sum=4000000006;counter=15,counter=15,peek=100
    resource.new 2, rep 3, drop 2
```

The complex component differs from Wasmtime **only** in `get=apple,3,[,]` (`[red,big]` was expected). To check whose bug it is, the same component was fused with `meld fuse --component` and the result run on Wasmtime: it gives the same `[,]`. So **this is a bug of meld**: a `list<string>` inside an `option<record>` returned across the boundary is not copied into the guest's memory. The glue is not at fault. Everything else matches: resources (own and borrow, `drop` with the destructor), `result`, `option`, `variant`, `enum`, `flags`, `list<u32>`, `u64`.

**Pluses.** One core module, no runtime of the component model. The adapters between components are plain wasm (multi-memory + `memory.copy`), so wasm2c compiles them together with everything else. What is left to the host is WASI and a few built-in resource functions.

**Minuses.**
- meld is young (v0.64, released today), and a bug was found at once.
- `--emit-import-map` does not say which memory a WASI import belongs to. It was taken from the suffix `$N` and from the order of the exports, which is fragile. Inside meld this information exists (`import_memory_indices`), so it could be suggested to add it to the import map.
- The licence is Apache-2.0.

**[again]** The minimal pair (`experiments/wasi_checks/fused_simple/run_fused.py`: the composed pair of "A composed component" fused by `meld fuse`, built with `wasmext natify -i -b`, called from Python) gives `196`,
as expected, with two memories. The complex component (`experiments/wasi_checks/complex_fused/run_cx_fused.py`, the sources in `experiments/jco_zwasm/complex`) gives `get=apple,3,[,]` with meld, where jco in Node
gives `[red,big]`: **the bug is reproduced** and is in meld. The fused module carries the custom sections `meld.signature-manifest` (with `--emit-manifest`), `wsc.transformation.attestation`,
`component-provenance` and `producers`. Two upstream issues were opened by the owner of this repository: [pulseengine/meld#512](https://github.com/pulseengine/meld/issues/512) and
[#513](https://github.com/pulseengine/meld/issues/513) (their texts were not read here, so it is not said which finding each covers: the bug with `list<string>` in a returned `option<record>`, the import map that does
not say which memory a WASI import belongs to, or both).

**Released as v0.65.0, and the main finding checked here (2026-10-22): [experiments/meld_065/](experiments/meld_065/README.md).** On our own build of the complex component, fused by 0.65.0 and run on wasmtime 50.0.0, `get=apple,3,[red,big]` and the whole string equals the unfused one; 0.64.0 gives `[,]` on the same input. #512 is fixed, #513 (the import map, `"version": 2`) is in and was read on our composition (53 imports); the run of the fused core module through wasm2c and the zwasm host was not repeated. **A new finding, not reported:** with `--component`, two components that both export `wasi:cli/run` (commands) give an export name `run$0` that does not validate, in 0.64.0 and in 0.65.0; reactors are fine. What follows was written while the release was awaited and is kept as it was.

**Awaiting upstream; the release is on its way.** Issue [#512](https://github.com/pulseengine/meld/issues/512) is closed by pull request [#516](https://github.com/pulseengine/meld/pull/516), and issue
[#513](https://github.com/pulseengine/meld/issues/513) by [#518](https://github.com/pulseengine/meld/pull/518). Pull request [#521](https://github.com/pulseengine/meld/pull/521) is the release **v0.65.0**; its
`CHANGELOG.md` (read from the branch of the pull request, 2026-10-22) says; **the pull request was open (22 checks) when the owner of this repository pasted its description, and was then merged into `main` upstream (told by the owner, 2026-10-22); a release is not published yet**:
- **#512 fixed:** "nested lists and strings inside option, result and variant values are deep-copied across memories": a `list<string>` behind an option, result or variant had its pointer array copied to the other component but not the strings it
  points to, so the receiver read its own memory at the other component's addresses (empty or garbage strings, or a trap, at exit 0), under `--memory multi`. That is the `get=apple,3,[,]` above.
- **#513 fixed:** `--emit-import-map` now states, for each function import, **the memory its pointer arguments refer to, the allocator for list and string results, the string encoding and the owning component** (the map gets `"version": 2`;
  `null` = the lower has no such option, `{"unknown": ...}` = it could not be traced); resource intrinsics name their resource and `[dtor]` export. That is what the paragraph above missed ("which memory a WASI import belongs to").
- also in 0.65.0: a re-exported adapted import reaches the adapter from every importer (#504, SR-103).
- the description of the pull request says: the import map of 57 maps compared before and after the change differs in no index, kind, module or name; the clean-room review of #513 left gaps filed as [#520](https://github.com/pulseengine/meld/issues/520) (a `dtor` that can be determined is reported as `null`; a misleading reason `unknown` under `--memory shared`), none a wrong answer; [#515](https://github.com/pulseengine/meld/issues/515) is in review and will ship as **v0.65.1**.

So everything above and the multi-component findings in [wasi_p1_vs_p2_host_requirements.md](wasi_p1_vs_p2_host_requirements.md) were measured on meld 0.64.0, and **the experiment is to be repeated on 0.65.0** once it is published (the checks to repeat: the complex
component with `list<string>`, the import map, and a WASI import used by two components).

meld was built from source: `cargo build --release -p meld-cli` (1 min 52 s here, 1 min 49 s in the report; a binary of 5 MB). Its earlier version 0.63.0 produced **no adapter** on a hand-made provider and consumer
(`adapters_generated: 0`; the call stayed an import) in the first page; 0.64.0 does generate `memory-copy` adapters, on the real composed components of the second report and on the minimal pair **[again]**. So the
earlier statement is out of date and is kept here only as this line.

What meld takes and gives, as the second report put it:

- **The pipeline.** A composed or nested component: `meld fuse --exports world` → one core module with a memory for each component → `wasmext natify`. A single component: `unbundle`.
- **`--emit-import-map` does not say which memory each WASI import belongs to.** The report took it from the suffixes `$N` and from the order of the exports, and that is fragile; inside meld the information exists
  (`import_memory_indices`), so it was proposed to add it to the import map.
- **`--emit-manifest`** gives, for each export, the WIT signature, the core signature, the memory, the realloc, the post-return and the layout of the return area, which is enough to generate a typed layer for Python
  without a WIT parser of our own (the module then carries `meld.signature-manifest`).
- **Because meld has a bug, an independent check is useful**: the same component on Wasmtime or through the plan of `wasmtime-environ`.
- Not checked: meld on components with WASI 0.3 and async (`--explain` shows `async-lift`); how it handles the async built-in functions (most likely they stay imports for the host, as in `p3host.c`).

### `wasmtime-environ` as a build library **[reported]**, the kinds **[again]**

This is the same code that Wasmtime and jco use, but called directly. A program of 47 lines of Rust (`envplan`) calls `Translator::translate` and prints the plan:

```rust
let (tr, modules) = Translator::new(&Tunables::default_host(), &mut validator, &mut types, &scope).translate(&bytes)?;
// modules: core modules, including FACT adapters (writes the .wasm of each)
// tr.component.initializers: InstantiateModule / LowerImport / ExtractMemory / ExtractRealloc / ExtractPostReturn / Resource
// tr.trampolines: the built-in functions that the host must provide
```

```
simple : core modules 6; initializers 25 {InstantiateModule 6, LowerImport 15, ExtractMemory 2, ExtractRealloc 1, ExtractPostReturn 1}
         trampolines 25 {LowerImport 15, ResourceDrop 6, Transcoder 1, Trap 3}
complex: core modules 8; initializers 44 {InstantiateModule 8, LowerImport 30, ExtractMemory 2, ExtractRealloc 2, ExtractPostReturn 1, Resource 1}
         trampolines 57 {LowerImport 30, ResourceDrop 13, ResourceNew 1, ResourceTransferOwn 1, ResourceTransferBorrow 1, Transcoder 2, Trap 7, EnterSyncCall 1, ExitSyncCall 1}
```

Everything needed to generate C wiring instead of JS is here:
- which modules to instantiate and in what order;
- what to put in each import;
- which built-in functions to provide and with which parameters (the resource type, the memory, the encoding).

**Pluses.** This is the reference semantics of Wasmtime. Any component that Wasmtime accepts is covered, nested ones included. Rust is needed only at build time: the tool can be shipped as a binary or a wheel.

**Minuses.**
- The API of `wasmtime-environ` is not stable between versions of Wasmtime, so the version would have to be pinned.
- A generator of C wiring from this plan has not been written yet. Its size is close to that of `js-component-bindgen`, but without the WASI shims, because WASI is taken by the host.
- The licence is Apache-2.0 WITH LLVM-exception.

### Comparison

| | meld | `wasmtime-environ` + a C generator of our own | jco + a parse of the JS of our own |
|---|---|---|---|
| Result | one core module (multi-memory) | a graph of core modules + a table of built-in functions | a graph of core modules + a table of built-in functions |
| Checked | both components run natively; a bug of meld in `list<string>` | the plan obtained for both; there is no generator yet | the simple component run by hand |
| Dependency | the meld binary | a Rust crate at build time | Node and jco at build time, plus parsing the generated JS |
| Reliability | a young project | the semantics of Wasmtime | the semantics of Wasmtime, but the JS output is not meant to be parsed |

### wasmext accepts a module with several memories **[reported]**, **[again]**

**wasmext accepts a module with several memories without any changes.** Both modules fused by meld passed `inspect` and `natify`, and then I called them from Python. The results are the same as with the C glue and Wasmtime.

- **`inspect`:** both say `result: can be wrapped`. It shows `2 memory`, the function `start` from meld, 3–4 tables each; the exports `memory` and `memory$0` are shown as two separate memories.
- **`natify -i -b`:** the extensions were built (abi3, 1.6 and 2.5 MB without strip). The stub correctly suggests that `memory$0` and `cabi_realloc$1` are available through `getattr`.
- **The simple component from Python:** `greet` returns `hello, Murphy #735`, `hello, wasm #20` and `hello, Мерфі #512`. The argument is put through `cabi_realloc$1` into `memory$0`, and the result is read from there too.
- **The complex component from Python:** the built-in functions of the resource (`[resource-new/rep/drop]counter`) I implemented as Python functions; `drop` calls the export `[dtor]counter`. The result of `run-all` matches Wasmtime, except the already known bug of meld `get=apple,3,[,]`. The resources worked: `new 2, rep 3, drop 2`. The two memories really are different objects, 128 KB each.

The tools of wasmext did not have to be changed for this.

Caveats:
- **`inspect` labels both memories as `Instance.memory`.** This is a cosmetic inaccuracy, because the stub and the extension itself tell them apart correctly.
- **The WASI path was not checked in this run.** No WASI import was called: the start function of meld and both calls did without it, so the WASI stubs in Python were simply not needed. How these imports are served from different memories was checked earlier only by the C glue with the zwasm host.
- **The products `--shared` and `--exe` were not built on a module with two memories.**

The test is in `/home/claude/fuse/mm_test.py` (on the machine of the reporting session; it is not in the archive of sources).

**[again]** `wasmext inspect` and `wasmext natify -i -b` accepted both the minimal pair fused by meld and the complex one, and Python called them (`196`, and the complex result above). The caveat that `inspect` labels both memories
as `Instance.memory` is a small inaccuracy of the tool that nobody has recorded as an item to fix; it is recorded here. That wasmext links and runs a module with several memories agrees with
[FEATURES.md](FEATURES.md), where multi-memory is **done** (`3.0 multi-memory`).

## Other runtimes: what was read and what was run

Runtimes that already have the component model were looked at to see whether one of them could be the engine of the artifact instead of `wasm2c`. None became the main path; the reasons are in the tables.

### Which light runtimes have the component model **[read]**

| Runtime | Component model | AOT | Note |
|---|---|---|---|
| **WAMR** | in progress: the full CM + WASI 0.2 in the Airbus fork (`dev/cm_wasip2_complete`, stable specs as of August 2025, no async and no wasi:http); upstream is merging it through the branch `dev/cm_wasip2` (PR #4872, the parser in #4889); not yet in main | LLVM (`wamrc`), cross-compilation, 32-bit targets exist | the nearest candidate for the future |
| Wasmtime | full | Cranelift, 64-bit targets only; 32-bit only through Pulley (an interpreter) | checked, see below |
| Wasmi, wasm3, wazero, Wasmer | not found | | |
| w2c2 | no | compiles to C (C89) | an alternative to wasm2c, see "Decompiling WASM into C" |

### A cut-down Wasmtime as a PyO3 extension (experiment D of the first report) **[reported]**

The code is in [experiments/component_model](experiments/component_model/README.md): `pyext_Cargo.toml`, `aot_Cargo.toml`, `aot_main.rs`, `onefile_lib.rs`, `greeter_usage.py`, `cross_aot.sh`.

- **The runtime** as a PyO3 extension: `wasmtime = { version = "50", default-features = false, features = ["runtime", "component-model", "std"] }`, `pyo3 = { version = "0.27", features = ["extension-module", "abi3-py311"] }`,
  release profile `opt-level = "s"`, `lto`, `codegen-units = 1`, `panic = "abort"`, `strip`.
- **The AOT tool** runs at build time and contains the compiler: features `["cranelift", "component-model", "std", "all-arch", "pulley"]`; it reads a component or a core module (by bytes 4 to 8) and writes a `.cwasm`,
  optionally for another target.

Result: `libwtmin.so` takes **1 098 800 bytes**. `composed.cwasm` (161 848 bytes), after `Component::deserialize_file` and `linker.define_unknown_imports_as_traps`, returns `greet("Murphy")` → `"hello, Murphy #735"`. **A nested component works out of the box.**

**Cross-AOT from x64** (the loop is `cross_aot.sh`):

| Target | Result |
|---|---|
| x86_64 Linux | ok, 161 848 |
| aarch64 Linux | ok, 358 464 (`ELF 64-bit … ARM aarch64`) |
| aarch64 macOS | ok, 194 624 |
| aarch64 Windows | ok, 145 544 |
| riscv64 | ok, 202 840 |
| s390x | ok, 190 552 |
| i686, armv7 | **error**: Cranelift has no 32-bit backends |
| pulley32 / pulley64 | ok, 227 248 (an interpreter) |

Whether the runtime itself builds for aarch64, i686 and armv7 could not be checked here: `rustup target add` failed in the sandbox. By the Wasmtime documentation the runtime is ported, and the 32-bit targets work only through Pulley.

**One file: the runtime and the component together.** `onefile_lib.rs` embeds the `.cwasm` through `include_bytes!` and calls the exports by name. Values are converted between Python and WIT by the types taken from the
component itself, with no code generation per WIT (`Type::Bool`, the integers and floats, `String`, `List`, `Record`, `Option`; `result`: `Ok` gives the value, `Err` a `RuntimeError`). The engine is made once, the
component is deserialised from the embedded bytes, `linker.define_unknown_imports_as_traps(&comp)`, then a `Store` and the instance. From Python (`greeter_usage.py`):

```python
import greeter

c = greeter.instance()
c.call("demo:text/api@0.1.0", "greet", "Murphy")  # 'hello, Murphy #735'
c.call("demo:text/api@0.1.0", "greet", "wasm")  # 'hello, wasm #20'
```

`greeter.abi3.so` takes **1 255 216 bytes** and contains the runtime and the component in one file. Not done: variant, enum, flags, resources, host functions from Python (the `Linker` allows them).

**Speed: CoreMark, `wasm2c` against Cranelift AOT.**

The same `_core.wasm` (19 463 bytes, built by `examples/coremark/build_wasm.py` through `zig cc -target wasm32-freestanding -O3`). The Rust wrapper has the same imports `wiring.millis` and `wiring.print` as the example.

```sh
uv run --group wasm python examples/coremark/build_wasm.py
aot _core.wasm core.cwasm                    # 53 608
$W natify -i -b -q _core.wasm                # _core.abi3.so: 609 224, 69 184 after strip
python bench.py wasm2c; python bench.py cranelift    # twice each
```

| Run | wasm2c (wasmext) | Cranelift AOT (Wasmtime 50) |
|---|---|---|
| 1 | 29 653.8 | 22 507.3 |
| 2 | 26 720.1 | 20 184.4 |

Both reports had `Correct operation validated`. **Cranelift is slower by about 25 %.** The VM has 2 cores, so the spread is large, but the order is stable.

**Conclusion of the experiment**, what the Wasmtime variant gives against `wasm2c` + wasmext:

| Requirement | Minimal Wasmtime | wasm2c + wasmext |
|---|---|---|
| The component model, nested components | out of the box | has to be built ("Ways") |
| A self-contained artifact | yes, but each extension carries about 1 MB of runtime | yes, 57–143 KB after strip in our examples |
| 32-bit targets (Windows x86, armv7) | only Pulley, that is, an interpreter | any C compiler |
| Speed | about 25 % worse | close to native |
| Tied to versions | a `.cwasm` is tied to the version and configuration of the runtime | no |

**Rejected as the main path.** The variant stays as a fallback backend for what a flattener will not cover: WASI 0.3, async, complicated graphs of resources.

### zwasm **[reported]**, its features **[read]**

zwasm (clojurewasm, Zig, 2.7.0) is a runtime with an AOT and a JIT, a WASI 0.2 host and component support. Two things of it were used: its WASI 0.2 trampolines as a host for `wasm2c` modules, and its speed and features
as a comparison.

#### A WASI 0.2 host for `wasm2c` (the prototype `w2c_host`)

The WASI 0.2 trampolines of zwasm are registered in its own `Linker` through its classifier. Every call from a wasm2c module goes through a registered thunk, and `Runtime.memory` is pointed at the wasm2c memory before the call. The changes in zwasm take 9 lines (`pub` for `defineClassifiedFunc` and a hook for `cabi_realloc`), the C ABI is 122 lines of Zig (`zw_register`, `zw_call`, `zw_preopen`, `zw_set_args`).

| What was run | Imports | Result |
|---|---|---|
| `hello` (a WASI 0.2 command) | 21/21 | output present, the return code as with the Python host |
| `sock` (TCP `connect`, `send`, `recv`) | 74/74 | `reply: pong` from the server |
| `fs` (arguments, preopen, reading and writing files, `readdir`) | 39/39 | files read and written, the directory read |
| the simple composed, by hand following the layout of jco | 21/21 | = Wasmtime; invalid UTF-8 traps in `transcode` |
| the simple composed, fused by meld ("`meld fuse`") | 21/21 | = Wasmtime |
| the complex composed, fused by meld | 42/42 | = Wasmtime, except the bug of meld |

**Size.** The binary with the zwasm host takes ~1.8 MB (ReleaseSmall, `--gc-sections`, `strip`). The modules themselves take tens of KB. The reason is that `component_wasi_p2.zig` imports `Value` from `../zwasm.zig`, which pulls in the whole C API and the engine.

zwasm was built from source here (2.7.0, `d74e63b`, Zig 0.16.0) **[again]**; its runs were not repeated. The WASI 0.3 side of zwasm is told in "WASI 0.3: a C program through `wasm2c`".

#### The AOT of zwasm
**Yes, zwasm has an AOT, but it does not give the speed of `wasm2c`.** The same `.wasm` was measured (CoreMark, `wasm32-wasip1`, `-O3`) on each variant, two runs each:

| Variant | CoreMark |
|---|---|
| native gcc -O3 (the posix port) | 22 745 |
| native clang -O3 | 21 611 |
| **wasm2c (`wasmext natify --exe`)** | **23 428 / 23 232** |
| zwasm AOT (`zwasm compile` → `.cwasm`, compilation 0.1 s) | 8 360 / 8 126 |
| zwasm JIT | 8 049 / 8 592 |

- **wasm2c is at the level of native here.** A small plus over gcc, within the noise, though it is possible that 32-bit pointers help.
- **zwasm is about 2.8 times slower**, and the AOT hardly differs from the JIT. This is not by chance: the AOT stores the same code as the single-pass JIT, with no optimiser. The only advantage of the AOT is that there is no compilation at start-up.

**Why "compiling into zwasm" does not keep your model:**
- a `.cwasm` is not a self-contained artifact. It is loaded by the zwasm runtime, and `libzwasm.a` takes 2–2.5 MB;
- the JIT and the AOT exist for x86_64 and arm64 only. On 32-bit targets the interpreter is what is left;
- multi-memory, by `features.json`, works only in the interpreter, so a module from meld on zwasm would be very slow. wasm2c compiles it.

#### Features of zwasm against `wasm2c` by `features.json`

**Features by `features.json`** (zwasm against wasm2c):
- **In zwasm and not in wasm2c:** GC, typed function references, wide arithmetic, relaxed SIMD, threads (with a note: a single-threaded host, `wait` ends by timeout), WASI 0.2 components.
- **In wasm2c only behind a flag, in zwasm by default:** exceptions, memory64, tail call, extended const, custom page sizes.
- **A caveat of zwasm from the json itself:** SIMD only in the JIT (the interpreter traps on a vector instruction), multi-memory only in the interpreter.

**What follows from this.** wasm2c stays the main path, because it gives both the speed and the self-containedness. zwasm makes sense as a fallback backend exactly for modules that wasm2c does not translate (GC, typed function references, wide arithmetic), and the price is a roughly three times lower speed and a runtime inside the artifact. A summary of the features could be added to a document. What of this is already written in `wasm2c_limits.md` was not checked.

**Corrected [again]**: the claim "behind a flag in `wasm2c`: exceptions, memory64, tail call, extended const, custom page sizes" is wrong for four of the five. By `wasm2c --help` of WABT 1.0.42 exceptions, tail call,
memory64, multi-memory and extended const are **on by default** (there are only `--disable-*` flags for them); threads, custom page sizes, function references, GC, wide arithmetic and compact imports need an `--enable-*`
flag. So the `features.json` of the WebAssembly website is stale for `wasm2c`, and wasmext supports those four without passing a flag. The section on this is in [wasm2c_limits.md](wasm2c_limits.md); the page
already had sections on typed function references, GC and wide arithmetic, and a line each on relaxed SIMD and multi-memory, and did not mention zwasm as a backend, threads, exceptions, tail call, extended const or custom
page sizes before it was added. `features.json` was downloaded again on 2026-10-21.

### WAMR with the component model **[read]**

The first report's table (above) says "in progress" in the Airbus fork and in an upstream branch; the first page said "roadmap only", which is out of date. The fork is looked at in "Ready native layers of WASI 0.2".

## Ready native layers of WASI 0.2 and of the canonical ABI **[read]**

The aim: not to write a bridge by hand for each WASI function (sockets, file system, streams…) and for each WIT, but to find a ready layer that compiles for the native platform, implements the canonical ABI and WASI
0.2, and resolves the imports of a core module after `unbundle` or flattening. It is not known beforehand which interfaces a module imports, so the layer has to cover all of them. Looked for by search of the web and the
repositories, by reading and by compiling parts; dates and sizes of repositories were not checked.

### Canonical ABI code in C for the host side

Looked for (by search of the web and the repositories, not built or run; dates and sizes of repositories were not checked): the lift and lower of the canonical ABI as plain C or C++ for the **host** side.
None was found, so the glue of "A component with a WIT of its own" above would be written in wasmext.

| What | Side | Language | Found |
|---|---|---|---|
| `design/mvp/canonical-abi/definitions.py` and `run_tests.py` in WebAssembly/component-model | reference | Python, Apache-2.0 | the executable specification: lift and lower of every type, flattening, `realloc`, `canon lift`/`canon lower`; no ports to C, C++, Go, TypeScript or Zig were found |
| `wit-bindgen` (`c`, `cpp`) | guest | Rust, generates C and C++ | code for a module that is the component; running a component in a host is not in its scope. No generator of C for a host, present or planned. Hosts it lists: Wasmtime `bindgen!` (Rust), `jco`, `wasmtime-py`, `wasmtime-rb` |
| C API of Wasmtime (`wasmtime/component/{component,func,instance,linker,types,val}.h`) | host | C over Rust | a thin binding: `val.h` builds, clones and frees values; the conversion is in the Rust crate, so the ABI is not usable alone and brings the engine |
| `to-wit` (SingleStore) | tool | Rust with a C header, Apache-2.0, experimental | parses a WIT and gives the flattened parameters, size and alignment; a possible cross-check at build time, not a source of lift and lower |
| `wit-parser` | tool | Rust | no official C bindings; no other WIT parser in C or C++ was found |
| WAMR | host | C | the component model is **in progress**: the full CM + WASI 0.2 in the Airbus fork (below), and an upstream branch `dev/cm_wasip2` (PR #4872, the parser in #4889); not in main (the first page said "roadmap only": out of date) |
| wasm3, Wasmi, wazero, Wasmer, WasmEdge | host | | no component support found (WasmEdge says it is committed to it); not verified |

What this gives: port `definitions.py` to the generator (it emits lift and lower per type of the WIT), with `run_tests.py` as the oracle of the tests. `wit-bindgen c` is the model for the layout
of the code to emit (it is the other direction: there the host calls `realloc` of the guest, here the glue does).

### Would `wit-bindgen` help?

Looked at by reading the sources and docs on `main` (wit-bindgen 0.63.0, wasm-tools 1.262.0, wasmtime, jco) and by running `wasm-tools` and one third-party tool on
hand-written components; nothing was built into wasmext. What was not checked is marked.

- **The `wit-bindgen` command: no.** It has only guest backends (rust, c, cpp, go, csharp, moonbit, d) and a markdown one. Its README says that running a
  component in a host is not in that repository (hosts: Wasmtime `bindgen!` for Rust, `jco` for JavaScript).
- **The library `wit-bindgen-core`: partly, and for the hard part.** It depends only on `wit-parser`. Its `abi` module is the instruction generator of the
  canonical ABI and has the host directions: `abi::call` with `GuestExport` + `LowerArgsLiftResults` (the host calls an export: lower the arguments,
  `cabi_realloc`, lift the result) and `GuestImport` + `LiftArgsLowerResults` (the host implements an import). `jco` is built on it, which shows that a host
  backend works. A new backend would be written once, in Rust, against the `Bindgen` and `WorldGenerator` traits.
- **What a host backend still has to write:** the 97 `Instruction` cases in the target language; the call of `cabi_post_*`; the handle tables of resources
  (`own`, `borrow`, `[dtor]`); the reading of the WIT (`wasm-tools component wit --json` works on a composed component); async and streams (0.3). The
  names of the core exports (`<interface>#<func>`, `[method]r.f`, `cabi_post_<name>`) are a convention to be coded by hand.
- **Size** (counted lines of the existing backends: markdown 705, c 4296, moonbit 3978, go 3531, jco `function_bindgen.rs` 4425): a backend for synchronous functions
  only is about 1500 to 2500 lines of Rust. *That figure is an estimate, not measured.* It brings a Rust toolchain into the project (a build-time tool whose generated C
  is shipped would avoid that for users).
- **Nested and composed components: wit-bindgen does nothing for them.** `wasm-tools` has no subcommand that fuses, flattens or lowers a component (`compose` is
  deprecated in favour of `wac`; `unbundle` gives the modules and not the wiring). Flattening is done by `wasmtime-environ` (`translate/inline.rs`, and the FACT adapter
  modules, which import host builtins for transcoding and resource transfer), which `jco transpile` uses to write core modules plus JavaScript glue. The only tool found
  that claims to fuse components into one core module is the third-party **meld**. On a minimal hand-written provider and consumer, 0.63.0 produced a valid module but generated **no adapter** (`adapters_generated: 0`), so
  its claim was not shown then; **0.64 does** (see "`meld fuse`"). *Not checked:* `wasm2c` on a multi-memory output was not checked by that page, and was by the later reports (it works).
- **Python:** no tool that turns a component into Python was found. `wasmtime-py` has a dynamic `wasmtime.component` API (an engine, not pure Python).

| Case | Fit |
|---|---|
| WASI 0.2 command in wasmext (about 24 imports) | by hand in C, as for 0.1; no generator needed |
| A component with a WIT of its own in wasmext | a `wit-bindgen-core` backend if many WITs are expected; otherwise by hand from the Python reference (`definitions.py`) |
| Nested or composed component in wasmext | meld, if it proves out on real input, then the row above; otherwise an engine (Wasmtime) |
| The same in py-wasmhost | a port of `definitions.py` as a run-time interpreter over the types from `wasm-tools component wit --json`, with no Rust; nested components need the component model semantics itself (large) or an engine |

Recommended order: the WASI 0.2 command by hand first; try meld on a real composed component before designing anything for nested components.

### The Airbus fork of WAMR: `libc-wasi-p2` and `component-model`

Not built by us as a whole; the tree and the code were looked at, and parts compiled:

```sh
git clone --depth 1 --filter=blob:none --no-checkout -b dev/cm_wasip2_complete \
    https://github.com/airbus-forks/wasm-micro-runtime.git wamr-airbus
git log -1        # 2815b69 2026-06-05 "Merge branch 'main' into dev/cm_wasip2_complete"
git ls-tree -r --name-only HEAD | grep -iE "component|wasip2|canon"
```

What is there (checked by the tree and the code):

| Directory | Content |
|---|---|
| `core/iwasm/libraries/libc-wasi-p2/` | native WASI 0.2 in C: `wasi_p2_{cli,clocks,filesystem,io,random,sockets,error,common}.c` (an implementation on POSIX types) and `*_wrapper.c` (entry points with flat core signatures) |
| `core/iwasm/common/component-model/` | the parser of a component, the canonical ABI (`wasm_canonical_abi.c`, `wasm_component_canonical.c`, `wasm_component_flat.c`), resource tables, tasks |
| In all | about 40 thousand lines of C; the biggest files: `wasi_p2_sockets_wrapper.c` (4021), `wasm_component_types_section.c` (3436), `wasm_component_validate.c` (3012) |

The wrappers have the same signatures as the imports after `unbundle`. An example (shortened):

```c
void
wasi_io_streams_output_stream_write_wrapper(wasm_exec_env_t exec_env,
                                            uint32_t output_stream_handle,
                                            uint32_t contents_ptr,
                                            uint32_t contents_len,
                                            uint32_t offset_addr)
{
    WASMComponentFuncTypeInstance *func_type = wasm_get_component_func_type(exec_env);
    ...
    load_string_from_range(exec_env->cx, contents_ptr, contents_len, &contents_val);
    lift_borrow(exec_env->cx, output_stream_handle,
                func_type->params->params[0].type->type_specific.resource_handle, &lifted_handle);
    HostResource *hr = host_resource_table_get(get_global_host_resource_table(), ...);
    wasi_output_stream_write(output_stream_fd, &contents, &wasi_ret);   /* the POSIX part */
    ...
    store(exec_env->cx, offset_addr, func_type->results->result, result);
}
```

**Can it be separated from WAMR?** Checked by compiling the files of `libc-wasi-p2` separately:

```sh
cc -fsyntax-only -DBH_PLATFORM_LINUX -DWASM_ENABLE_COMPONENT_MODEL=1 -I. -I../../include -I../../common \
   -I../../common/component-model -I../../../shared/utils -I../../../shared/platform/linux \
   -I../../../shared/platform/include -I../../interpreter wasi_p2_*.c
#   wasi_p2_clocks.c, wasi_p2_random.c: ok
#   the rest: need ../interpreter/wasm.h, wasm_runtime_common.h, posix.h (the sandbox of WASI p1 in WAMR)
grep -ohE "\b(wasm_runtime_[a-z_0-9]+|wasm_get_[a-z_0-9]+|exec_env->[a-z_]+)\b" *.c | sort | uniq -c | sort -rn
#   247 exec_env->cx                        (the canonical ABI context: memory, realloc)
#   117 wasm_runtime_get_wasi_ctx / get_module_inst
#   116 wasm_get_component_func_type        (types from the parsed component)
#   103 wasm_runtime_set_exception
#    72 / 58  wasm_runtime_free / malloc    (+ bh_hash_map_*)
```

**Result: this is not a drop-in.** The WASI logic (the POSIX part) is almost independent. But the wrappers and the canonical ABI hold on to the WAMR runtime: to the ABI context, to the function types given by the parsed component, and to `exec_env`. A port would mean:
- a shim of about 10 functions of the WAMR runtime for a wasmext instance (memory, `cabi_realloc`, an exception as a trap, malloc);
- a source of function types: either the WAMR component parser at build time, or a static table for the WIT of WASI;
- Windows: the code is POSIX only (`sys/socket.h`, `poll`, `pthread`);
- a moving target: the branch is being merged into upstream WAMR in parts.

Besides this, **a layer of our own between the host interface and Python** is still needed ("What none of the options found gives").

### component-model-cpp (GordonSmith)

By the README; not built by us: header-only C++20, the canonical ABI **for the host side**, independent of the runtime (only the guest's memory and `realloc` are needed). Supports all the types, own/borrow resources, async, stream and future. Has `wit-codegen`, which generates C++ bindings from a WIT. The integration with WAMR is marked as ready, with Wasmtime it is not. **There is no WASI implementation.** The project is small: 55 commits, 16 stars, no releases.

This is a potential source of *generated* glue for an arbitrary WIT, but not of WASI.

### What none of the options found gives

A layer between the component model and Python (or another embedder) is given by nobody: not Airbus, not cmcpp, not wit-bindgen. Typed calls of exports from Python and host functions in Python will have to be generated by us in any case. An official reverse adapter "WASI 0.2 on top of 0.1", to reuse the existing C host 0.1 of wasmext, was not found; only the direct one exists: a 0.1 guest on a 0.2 host.

### Licences

*This is not legal advice but a statement of the licence terms. It is worth showing to a lawyer before a decision.*

| What goes into the artifact | Licence | What it requires when a binary is distributed |
|---|---|---|
| wasmext (generator, glue) | MIT | the copyright and the text of MIT |
| the wasm2c runtime (`wasm-rt*.c`), already in every module | Apache-2.0 (the header of `wasm-rt.h`: "Copyright 2018 WebAssembly Community Group participants") | see below |
| WAMR / the Airbus fork | Apache-2.0 WITH LLVM-exception (the header of `libc_wasi_p2.cmake`, Copyright 2026 Airbus Defence and Space Romania SRL) | see below |
| component-model-cpp | Apache-2.0 and BSL-1.0 (+ `LICENSE-BOOST-PFR`) | |
| Wasmtime | Apache-2.0 WITH LLVM-exception | |

**Apache-2.0 is not copyleft.** It does *not* require a module built with the WABT runtime to be licensed under Apache-2.0 itself: the whole artifact may be under MIT or closed. The terms of section 4 concern only the distribution of copies:
- 4(a): give the recipient a copy of the text of the licence;
- 4(b): mark the modified files;
- 4(c): keep the copyrights and the attribution in the source code;
- 4(d): if the original has a `NOTICE` file, carry its attribution on.

Plus the patent clause (section 3). In wasmext this is already taken into account: `NOTICE.md` mentions the wasm2c runtime and requires its licence to be kept with copies of the files. For ready wheels the practical rule is: put the `LICENSE` of WABT into `*.dist-info/licenses/` (as `wabt-package` already does) or into the documentation of the distributed product.

**The LLVM-exception is softer for binaries.** It allows not to fulfil 4(a), 4(b) and 4(d) for the parts of code that ended up in object form as a result of compiling your code. Whether it covers static linking of a library like WAMR, and not only the runtime of a compiler, is a matter of interpretation. The most careful way is to treat it as Apache-2.0: the text of the licence and the attribution next to the binary.

**Conclusion:** licence-wise, porting the code of Airbus or cmcpp adds the same obligations that the WABT runtime already has (attribution and the text of the licence), not new ones. The deciding problems of those options are technical ("The Airbus fork of WAMR"), not licensing. Compared with MIT they add the patent clause of Apache and the need to keep attribution for each source.

### Decompiling WASM into C **[read]**

| Tool | What it gives |
|---|---|
| `wasm2c` (WABT) | C that compiles; not for reading |
| **w2c2** (MIT) | C that compiles (mostly C89): core 1.0, threads, bulk memory, several modules and instances, parallel compilation, debug information from DWARF; 99.9 % of the spec tests, on CoreMark ~7 % of native; there is no component model |
| `wasm-decompile` (WABT) | readable pseudo-C for analysis, does not compile |
| Ghidra with a wasm plugin, Binary Ninja, IDA | reverse engineering |

## Ideas for the host of an unbundled module (not built, not decided)

Written down after the host in [`examples/wasi2_unbundled`](../examples/wasi2_unbundled) was made. **Nothing here changes the public interface or the ABI now**; each idea says what it would touch, so that they can be taken one by one, in any order, and together.

### What is true today

- The stub of a module has one `TypedDict` for each module of the imports, `_Imports0`, `_Imports1`, … (`_gen.py`, `by_module`), numbered **by the order in which the modules first appear in the import section** of the `.wasm`. The numbers are not stable: another compiler or another version of `wasm-tools` can reorder the section, a program that starts to use one more interface moves every number after it, and `_hello` and `_sock` number the same modules differently. Nobody writes `_ImportsN`: it is a private name for the editor and `pyright`. The public name is `Imports`, whose keys are strings (`"wasi:io/streams@0.2.12"` and the name of the function).
- At run time nothing says which imports an instance needs: `dir(module)` is `Instance`, `LinkError`, `Trap`, and `Instance({})` fails with `LinkError: missing import module '…'` for one module at a time. The example takes the list from `_imports.py`, which `build_wasm.py` writes from `wasm-objdump`.
- A WASI 0.1 module has no `Imports` in the stub (`imports: None = None`): its WASI calls are in C in the module. `wasi=` holds the configuration (data), and also `clock` and `random`, which are functions, while the other calls can be replaced through `imports` ("what the caller gives as an import wins", DESIGN.md) without the stub saying so.

### The key of an import

Every idea below resolves by the same key: **(module without its version, name of the function)**, as in `("wasi:io/streams", "[method]output-stream.write")`. The version is dropped on purpose: the patch releases of WASI 0.2 are compatible, so `@0.2.6` and `@0.2.12` are the same key. (A host that wants to refuse a version can compare the `major.minor` it knows.) Nothing at run time refers to a name of a type.

### 1. Names of the types in the stub

`_Imports_wasi_io_streams_0_2_12` instead of `_Imports7`: the module name with every character that is not a letter or a digit turned into `_`. If two modules give the same name (`a-b` and `a_b`) the second gets a number, in the order of the import section, so the names are the same from one build to the next.
- *Touches:* the generator and the text of every committed `.pyi` (the stubs of the examples), the tests that compare the text of a stub. Not the interface, not the ABI (the names begin with an underscore); not the fingerprint of `wasmext/c/`.
- *Gives:* a stub that does not change all over when a module is added, so a `diff` of a regenerated stub shows the change and only that; names a person can read.
- *Does not give:* anything at run time.

### 2. The map of a host: `map_wasi()`

What the example is moving to. A method returns a dictionary from the key to **bound methods**, not to names in strings:

```python
def map_wasi(self) -> dict[tuple[str, str], Callable[..., Any]]:
    return {
        ("wasi:cli/stdout", "get-stdout"): self.get_stdout,
        ("wasi:io/streams", "[method]output-stream.write"): self.write,
        (
            "wasi:sockets/tcp",
            "[method]tcp-socket.subscribe",
        ): self.subscribe_ready,  # one method may stand for several imports
    }
```

`imports()` stays general: for each import the instance needs it takes `map_wasi()[(module without version, name)]`, a drop for `[resource-drop]*`, and for the rest a function that raises `NotImplementedError("<module>.<name>")`. A misspelt method is an `AttributeError` when the map is made (and an error of the editor before), not when that import is first needed. A subclass changes one entry with `{**super().map_wasi(), key: self.mine}`.

### 3. The sugar `@wasi(module, name)`

A mark on the method says which import it answers; it can be stacked for a method that stands for several. Run on a small host (not in the repository):

```python
def wasi(module, name):
    def mark(fn):
        fn.__dict__.setdefault("__wasi__", []).append((module, name))
        return fn

    return mark


class Host(HostBase):
    @wasi("wasi:cli/stdout", "get-stdout")
    def get_stdout(self) -> int: ...

    @wasi("wasi:io/streams", "[method]output-stream.subscribe")
    @wasi("wasi:sockets/tcp", "[method]tcp-socket.subscribe")
    def subscribe_ready(self, resource: int) -> int: ...
```

The decorator only **writes a mark** on the function. `HostBase._registry()` walks the classes of `__mro__` (a subclass overrides its base), collects `{(module, name): attribute}`, and `imports(required)` looks the keys up as in section 2. A host of `get-stdout` answered 2, one method served `streams@0.2.6` and `tcp@0.2.12` both, and an import with no method raised `NotImplementedError("wasi:io/streams.poll")`.
- *Against section 2:* the mark is next to the code it describes (better for a host with many methods); but the registry is hidden state, and a misspelt string is as silent as in any table. The two can stand together: `map_wasi()` as the written-out form, `@wasi` as the sugar that builds it.
- *Later:* the calls of WASI 0.1 that wasmext answers in C could be written as such methods in a Python host for the ABIs to come (`@wasi("wasi_snapshot_preview1", "fd_write")`), so that the replacement of one call (today through `imports`, or `clock`/`random` in `wasi=`) has one form. That needs the stub to type the replacements (a `NotRequired` dictionary of the functions of `wasi_snapshot_preview1`), which is a change of the interface and not planned.

### 4. `__imports__`

A constant of the module that says what the instance needs, so that a host does not need `_imports.py` or `wasm-objdump`:

```python
module.__imports__ = (("wasi:io/streams@0.2.12", "[method]output-stream.write", ("i32", "i32", "i32", "i32"), ()), ...)
```

The module name with its version, the name, the types of the parameters and of the results. In the `.pyi` as `__imports__: Final[tuple[...]]`, the same in the wrapper for ctypes (it is a fact of the module, known when the C is made, like `__memory_page_sizes__`).
- *Gives:* a host that resolves itself (sections 2 and 3 take the list from the module); a check that the number of parameters of a method is the number of the import (the example's `start_connect(*rest)` hid that); a better message than `missing import module` one module at a time (all that are missing at once).
- *Touches:* the generator, the extension, the wrapper for ctypes, the stub: a new public name of the module, so a change of the interface (stable tier), not of the ABI.

### How they fit

| | Needs the generator | Run time | Public interface |
| --- | --- | --- | --- |
| 1. names of the types | yes (text of the stub) | nothing | no |
| 2. `map_wasi()` | no (the host of the user) | the host | no |
| 3. `@wasi` | no | the host | no |
| 4. `__imports__` | yes (extension, wrapper, stub) | a constant | yes (a new name) |

1 and 4 are in the generator and 2 and 3 in the host; 4 makes 2 and 3 simpler (the list of the imports comes from the module) but they work without it with a list written by the build, as the example does.

## Ways

**Possible paths, not decisions.** Some of them looked out of reach on the first page ("components made of components", "is there canonical ABI code in C to take") and are now shown to be within reach, in part by running them.
Where a way is the opinion of one report, the report is named. Nothing in the repository was changed because of these reports, and the ABI of the first alpha (`0.0.1a1`) does not depend on any of this; whether
the work is wanted before it is not answered here. The model of the project stays: **`wasm2c` → self-contained artifacts**, with the component model resolved **at build time**; a native runtime of the
component model, if it comes, is a replacement and not a precondition.

### What is established

1. **A component can be unwound into a flat core.** For one component `wasm-tools component unbundle` is enough (mind `--threshold`). For a composed or nested one: `meld fuse` gives one core module with a memory per
   component (the adapters are plain wasm, `memory.copy` and `cabi_realloc`); `jco transpile` and `wasmtime-environ` give a graph of core modules, the shim/fixup and the FACT adapters with the list of built-in
   functions. All of them pass `wasmext inspect` and `natify` and come down to the linking of instances that wasmext already has. The route through meld was run end to end (build, call from Python) on the reporter's two
   components and on the minimal pair; the route through the graph of jco was run end to end for the simple component by hand (3 core modules, 9 built-in functions in C) **[reported]**.
2. **WASI 0.2 command hosts:** a Python host of 40 to 156 lines runs `hello` and a TCP client; the zwasm trampolines passed `hello`, `sock`, `fs` and the composed components as a host in Zig; no host in C exists yet.
3. **WASI 0.3 C programs** run through `wasm2c` with a host of 94 lines of C (blocking in `waitable-set.wait` is natural for `wasm2c`); callback-style (Rust) components need an event loop and were not tried.
4. **Joining modules by a direct link is silently wrong for anything with a pointer** (strings, lists, records); scalars are fine. An adapter per function is needed (hand-written in Python or WAT, or generated, or built by meld).
5. **The host part cannot be had drop-in.** No ready native layer implements WASI 0.2 and the canonical ABI and is simply put into `wasm2c`; the nearest (Airbus' WAMR fork) is tied to WAMR. No one gives the layer to Python.
6. **The licences do not block the decision**, but each borrowed source adds attribution (Apache-2.0 obligations that the WABT runtime already brings; no new kind of obligation).
7. **The cost of Wasmtime or zwasm as the engine is measured**: slower (Cranelift by ~25 %, zwasm ~2.8 times by CoreMark), a runtime of 1 to 2.5 MB in each artifact, no 32-bit target except through an interpreter.

### What wasmext would have to do, level by level

1. **A WASI 0.2 command** (a core module that imports `wasi:*@0.2.x` and exports `…#run`): a host for the imports it uses, in C like the 0.1 one (about 24 for stdio and sockets of the 78 above);
   the instance has `cabi_realloc`, `memory` and a resource table for the handles; the entry point is `wasi:cli/run#run`, not `_start`.
2. **A component with a WIT of its own:** glue made per WIT world (the core signatures do not say strings from records): lowering the arguments with `cabi_realloc` and the memory, lifting
   the result from the returned pointer, calling the matching `cabi_post_*`, a handle table with `own` and `borrow` for resources and `[dtor]` when the Python object goes. Python objects for
   records, variants and results. Reading the WIT, or the component, to know the types.
3. **WASI 0.3:** all of the above and a runtime of the async model (waitable sets, subtasks, streams and futures, the task hook).
4. **Components made of components:** the semantics of the component model itself (the instance graph, `canon lift` and `canon lower` between memories, resources across components);
   `unbundle` is not enough. That is what Wasmtime and `jco` do; wasmext would rather leave it to an engine that does (py-wasmhost with wasmtime).
5. **Built.** The cheaper start: a function that tells the kind of a file (`wasi_flavor`: 0.1, 0.2, 0.3, component) from the bytes above, so that `natify` and `inspect` say what the file is and what to do (take the core
   module with `wasm-tools component unbundle`) instead of "not a module".

Details for the host of a WASI 0.2 command (from the analysis of the first report, **[read]** with the run above as the base):

3. **A resource table** for own-handles (streams, pollables, sockets) and `[resource-drop]*`.
4. **The encoding of `result`/`option`** by `retptr`. Returned lists (`input-stream.read`, `poll`) are placed through the guest's `cabi_realloc`.
5. **Mapping errno** to the variants of `error-code`.
6. **Stubs that return an error and not a trap:** a module needs all its imports, even those it does not call.
5. **Entry points:** `wasi:cli/run@0.2.x#run` instead of `_start`; for a reactor also `_initialize`. Much of the 0.1 code can be reused: for instance `output-stream.write` is almost the same as `fd_write`.

### Paths by stage

#### Now, with no changes to the core **[reported]**

* **A guest that needs only a WIT interface with no sockets:** build as `wasm32-wasip1` together with the `wit-bindgen c` bindings. WASI 0.1 is served by wasmext, and the own imports are passed as Python functions or by a link ("Without `unbundle`").
* **Functions with scalars only:** a direct link between modules ("Host functions between two modules", `direct`).
* **A WASI 0.2 command:** `unbundle` and a Python host, as in `examples/wasi2_unbundled`.
* **Anything with strings, lists and records between two modules:** an adapter. For now it is written by hand in WAT (`adapter.wat`) or in Python (`run.py`, the mode `adapter`).

#### Stages of extending wasmext (one at a time, in any order after the first)

1. **`wasi_flavor`** in `inspect` and `natify` (**built**): recognise core 0.1, core 0.2, core 0.3 or a component and suggest what to do (`wasm-tools component unbundle`). The cheapest step, and it removes the unclear "not a module".
2. **A typed WIT layer (a generator in Python, without Rust).** Take the types from `wasm-tools component wit --json`, port lift and lower from `design/mvp/canonical-abi/definitions.py`, and use `run_tests.py` as the oracle. The output is C code in the extension (a call of an export: lower → call → lift → `cabi_post_*`; an import: the other way) and a typed `.pyi`. Begin with `string`, `list`, `record`, `option`, `result`, `variant`, `enum`, `flags`; add resources (`own`/`borrow`, `[dtor]`) as a separate step.
3. **A generator of adapters between modules (WAT).** The same as `adapter.wat`, but generated from the WIT for each function. Do the copying between memories either by the multi-memory `memory.copy` (works in WABT and wasmext) or by a built-in function `transcode` in C, as in FACT. Resolve the cycle "the adapter needs the guest's memory" at the level of the instance graph: either a memory taken out into a separate module, or a deferred binding.
4. **A WASI 0.2 host** ("What wasmext would have to do"). The key of an import without the patch version, unknown imports return an error and not a trap. There are three ways, and none is a drop-in ("Ready native layers"):
   * **write it ourselves in C**: begin with stdio, clocks and random numbers, then TCP; the fewest dependencies, the most manual work;
   * **generate wrappers from the WIT of WASI** with the generator of step 2, and write by hand only the POSIX part, which is thin;
   * **port `libc-wasi-p2` from the Airbus fork through a shim** of the WAMR runtime: ready WASI logic, including sockets and the file system, but tied to their canonical ABI and types, POSIX only, and attribution under Apache-2.0 WITH LLVM-exception.
   A sensible combination: the generator of step 2 as the one layer of the ABI, and the POSIX part taken from Airbus only where it separates (like `wasi_p2_clocks.c` and `wasi_p2_random.c`, which compile on their own).
5. **Flattening nested components.** In the short term `jco transpile` can be used as a reference: take out the shim, the fixup and the FACT to see which graph and which built-in functions are needed, and compare the results. In the long term it is worth having a flattener of our own that reads the structure of the component (`rest.wasm` after `unbundle`: `canon lift`/`lower`, instances) and generates the adapters of step 3. Do not hold on to the names of the FACT imports.
6. **Put off WASI 0.3 and async.** They need a model of tasks (waitable sets, subtasks, stream and future), that is, a real runtime.

The second report put the order of work this way (the reporter's order, not a decision): 1. the WASI 0.2 host in C; 2. support for the modules from meld in wasmext (choosing the memory for each import, the built-in
functions of resources); 3. a generator of the Python layer; 4. WASI 0.3. zwasm and Wasmtime stay at every step as oracles for checking the results. The first page said the same of the first step: do the WASI 0.2 command by
hand first, and try meld on a real composed component before designing anything for nested components (which is now done).

#### A WASI host over the canonical ABI: how big it is **[estimate]**

Question put to the reporter: *"Will the WASI host over the canonical ABI be rather big, no?"* The answer: big, but not as much as it seems. The sizes are the reporter's estimates, not measurements.

**It is big, but not as much as it seems.** Most of the volume does not have to be written from scratch, and the general Canonical ABI is not needed for the WASI host at all. The estimates below rest on the code of zwasm and wasmext, but they are estimates.

**What the host does not need:**
- **The Canonical ABI between components:** meld builds it in as wasm adapters.
- **A general lift/lower for WASI:** in zwasm the trampolines have the layout of every 0.2 function written in by hand (`retptr`, the discriminant, the offsets). There is no generic Canonical ABI on this path.

By the volume in zwasm (lines of Zig):

| Part | zwasm | What wasmext has |
|---|---|---|
| The 0.2 trampolines (cli, io, clocks, random, filesystem) | ~2.1 thousand | 0.1 lies under them, and in wasmext it already exists in C (~4.2 thousand lines with Windows) |
| The context and the table of resources | ~1.4 thousand together with a part of 0.3, the table is 238 | — |
| Sockets | 1.4 thousand | nothing, to be written from scratch, plus Winsock |
| The classifier (236 names) | data | generated |

In C this is, roughly, **3–5 thousand new lines** for the full 0.2 with sockets. Without sockets, about half as much. In the binary it is tens of KB, not megabytes: my 0.3 host in C gave 96 KB for the whole program.

**Corrected [again]**: the existing 0.1 host in C is **2886 lines** of plain C (`wasi_core.h` 1990 and `wasi_files_win32.h` 896 in `src/wasmext/c/`); with the Python layer `wasi_python.h` (1293 lines) it is 4179, which is the
"~4.2 thousand" of the report. So the C that a 0.2 layer would stand on is about 2.9 thousand lines.

**What can be split into stages:**
1. **stdio, clocks, random, exit:** tens of functions, which most CLI programs run on. Hello called only 5 of 21 imports.
2. **The file system:** the biggest part, but these are almost one-to-one the 0.1 calls that you already have.
3. **Sockets.**

An unimplemented import returns an error instead of a trap, so a module with one is still instantiated.

**0.3:** in zwasm it is ~4.1 thousand lines of host plus 1.5 thousand of async. For C programs 94 lines were enough, because blocking in `wait` is trivial under wasm2c. The full 0.3 for Rust components is a separate big piece.

**Where the generic Canonical ABI is really needed** is in the typed layer for Python, for your own WIT interfaces. In zwasm this is `canon.zig` of 1.9 thousand lines. But it can be generated for a particular WIT (from the manifest of meld), and not written as an interpreter: for synchronous types without async that is hundreds of lines of a generator, not thousands of lines of a runtime.

**Summary:** the biggest piece is WASI 0.2, and it sits on the 0.1 that already exists. One can move in stages, beginning with the small.

#### Tools in the build pipeline

| Tool | Role | Status |
| --- | --- | --- |
| `wasm-tools component unbundle / wit --json / print / validate` | parsing a component, types, diagnostics | run |
| `wit-bindgen c` | guest bindings (guest and provider) | run |
| `wac` | composing components (`wasm-tools compose` is deprecated) | not tried |
| `jco transpile` | a reference for flattening and for the set of built-in functions | run (the unpacking) |
| `wasm-opt` / `wasm-merge` (Binaryen) | optimising or merging **core** modules after flattening; components, as far as known, it does not read | not tried |
| meld | fuses composed components into one core module (multi-memory) | run on real components; a bug found ([#512](https://github.com/pulseengine/meld/issues/512), [#513](https://github.com/pulseengine/meld/issues/513)) |
| component-model-cpp (`wit-codegen`) | generating C++ host glue from a WIT, the canonical ABI for the host side | not built |
| the Airbus fork of WAMR (`libc-wasi-p2`) | native logic of WASI 0.2 as a source for a port | the code was looked through, partly compiled |

#### What to watch

* **WAMR:** merging the component model into main (the branch `dev/cm_wasip2`, PRs #4872, #4889; the Airbus fork). Its AOT through LLVM cross-compiles also for 32-bit targets, so this is the likeliest native backend "out of the box" that keeps the speed.
* **Minimal Wasmtime** (`runtime` + `component-model`, ~1 MB, `.cwasm` through `include_bytes!`): a fallback backend for WASI 0.3 and complicated components while there is no runtime of our own. A prototype exists ("A cut-down Wasmtime as a PyO3 extension").
* **wit-bindgen:** the appearance of a host backend for C. If it appears, step 2 of "Stages of extending wasmext" can be replaced by it.

### What stays outside wasmext (the fourth follow-up of the second report)

Question: should unfolding and rebuilding of modules be put into wasmext, so that meld does not have to be dragged in; a person who knows the module is WASI 2 or 3 converts it, and wasmext reads the file and refuses a wrong
one with a message on what to convert it with? The answer, as a path:

**Yes, I would not push the conversion into wasmext.** The logic is simple: wasmext compiles core modules, and the preparation of a component is a separate step of the build, with its own tools, its own pace of development and its own bugs. But the border has to be drawn carefully, because wasmext has to know something about the conversion all the same.

**What stays outside wasmext** (an instruction, and if wanted a separate step or package):
- `wasm-tools component unbundle` for a single component;
- `meld fuse --exports world --emit-manifest` for a composed one.

Probably meld can be used for a single component too, so that the input is always one format with a manifest. It accepts one component as well, but I did not run it on a single one.

wasm-tools is already on PyPI (`wasm-tools-package`), and meld is not. If convenience is ever needed, it can be wrapped in the same way as you made `wabt-package`, but it will not become a dependency of wasmext.

**What must be in wasmext:**
- **Recognising the content** (that `wasi_flavor` of "Stages of extending wasmext"):
  - bytes 4–7 equal to `0d 00 01 00`: this is a component, it has to be converted;
  - imports of `wasi:*@0.2.x` or `@0.3.x`: a core module of 0.2 or 0.3;
  - custom sections `meld.*`: the module has already been fused by meld.

  On a wrong input `natify` and `inspect` refuse with a concrete piece of advice and a command, and not with "not a module".
- **The WASI 0.2 and 0.3 host, the built-in functions of resources, the table of handles.** This is a runtime, and conversion does not replace it.
- **Reading the metadata of the converter:**
  - **the manifest of meld** (`meld.signature-manifest`, if the module was built with `--emit-manifest`): the typed Python layer is generated from it;
  - **the binding of an import to a memory and to `cabi_realloc`.** For now it has to be guessed from the suffixes `$N`, and that is fragile. It is worth asking meld to write this into the manifest or the import map; until that exists, a heuristic will stay in wasmext.

**What is worth writing in the instruction:**
- the exact commands for each case (single, composed, WASI 0.2, WASI 0.3) and the checked versions of the tools;
- what to do if meld gives a wrong result: compare with `wasmtime run` on the source component;
- the limits, such as the already found bug of meld with `list<string>`, until it is fixed.

**There is one risk:** the user built without `--emit-manifest`, and there will be no typed layer. Then wasmext has to work as it does now (raw core functions), and only warn that the types are unavailable and how to get them.

Facts checked about this on 2026-10-21 **[again]**: `wasmext inspect` / `natify` said `unsupported WebAssembly binary version 0d000100` on a component (a `WasmError` from `src/wasmext/_wasm.py`); the
recognition has since been built (`wasi_flavor`); `wasm-tools-package` is on PyPI **only as a pre-release** (`1.262.0.0b1`), the same state in which `wabt-package` was before 1.0.42.0; a package named `meld` on PyPI is MELD of the
Krishnaswamy Lab and the crate `meld` on crates.io is a project of Merkle trees, neither is this tool, so meld has to be installed from source; the names `meld.*` are those of a young tool (0.64). The proposal agrees with
the rule of the project that a built module needs nothing of `wasmext` when it runs. Nothing in the repository was changed because of these messages.

### Rejected, with the reason

| Path | Why not |
| --- | --- |
| Wasmtime or zwasm as the runtime of the artifact | slower than `wasm2c` (Cranelift ~25 %, zwasm ~2.8 times), a runtime in every artifact (1 to 2.5 MB), no normal way for 32-bit targets, a `.cwasm` tied to the version of the runtime. Kept only as a fallback backend for what a flattener will not cover (WASI 0.3 async, complicated graphs of resources, GC, typed function references, wide arithmetic) and as an oracle for checking |
| zwasm's WASI host (Zig) inside the build | works (hello, TCP, files, composed), but adds about 1.7 to 1.8 MB, a Zig build and a vendored tree that changes fast; the reporter: not worth keeping. Only its trampolines, the table of resources and the classifier are worth reading as a model for C |
| The JS glue of jco | not needed, and its output is not meant to be parsed; the kinds of built-in functions are finite (52), so they are written once in C |
| `wit-bindgen` as the generator of a host | it has guest backends only; a host backend would be a new backend on `wit-bindgen-core` (estimated 1.5 to 2.5 thousand lines of Rust, brings a Rust toolchain into the project), see "Would `wit-bindgen` help?" |
| Porting `libc-wasi-p2` of Airbus as a whole | the wrappers and the canonical ABI hold on to the WAMR runtime (`exec_env`, parsed function types); POSIX only; a moving target. Parts that compile alone (`wasi_p2_clocks.c`, `wasi_p2_random.c`) are fair game |
| Linking two modules directly for anything with strings, lists, records | silent corruption of the callee's heap, no trap |
| Pulling meld into wasmext as a dependency | a young tool outside PyPI; a step of the build with its own pace and bugs |
| An official adapter "WASI 0.2 on top of 0.1" | not found; only the reverse (a 0.1 guest on a 0.2 host) exists |
| Wasmtime or zwasm for 32-bit targets (Windows x86, armv7) | no 32-bit JIT; Cranelift has no 32-bit backend; only Pulley, an interpreter |

### Not checked

- A string returned from the provider through an adapter (read back into the guest's memory, `cabi_post_*`); a variant, a record and resources between modules joined by hand.
- `-Wl,--import-memory` instead of rewriting the guest's WAT.
- A generator of C wiring from the plan of `wasmtime-environ`; an end-to-end run of the graph of jco through wasmext with built-in functions in C or Python (the simple component was done by hand in C by the reporter);
  nested components deeper than one level, exporting a resource outward, UTF-16 and Latin-1.
- meld on components with WASI 0.3 and async (`--explain` shows `async-lift`); the WASI path of a meld-fused module in wasmext from Python (no WASI import was called in the reporter's run); the products `--shared` and `--exe`
  on a module with two memories.
- A build of the Wasmtime runtime for aarch64, i686 and armv7 (`rustup` did not install the targets in the sandbox of the reporter).
- WAMR with the component model (a build of it), w2c2, and `wac` on real components.
- A full build of `libc-wasi-p2` from the Airbus fork outside WAMR with a shim of the runtime, and a run of `examples/wasi2_unbundled` on it; a build of component-model-cpp and its `wit-codegen` on `demo.wit` and on
  the WIT of WASI 0.2.
- The licence of `design/mvp/canonical-abi/definitions.py` (the repository WebAssembly/component-model) before a port into the generator.
- zwasm on Rust components for `wasm32-wasip3`; callback lifting of WASI 0.3 through `wasm2c`; `w2c_host` on Windows and macOS; the size of the zwasm host without the engine.
- In the TCP run: `bind`/`listen`/`accept`, UDP, `ip-name-lookup`, IPv6, errors from the network, a large transfer, several pollables at once, closing from either side.
- WASI 0.3 and Rust components (callback style): an event loop; sockets, the file system and http of 0.3.
- The links under "Sources": the sites answered 403 or were unreachable through the proxy on 2026-10-21 and were not opened again; the claims taken from them are marked **[read]** at the time of the reports.

## A bug this found

`wasmext inspect` never returned on the core module of a WASI 0.2 component. The C name of the export `wasi:cli/run@0.2.12#run` is `wasi_cli_run_…`, which the pattern `wasi_\w+` reserves, and a
suffix cannot free a name whose start is reserved. Fixed: such a name gets the prefix `x_`, and where no name is found it is an error and not a loop (`_ident` in `_shared.py`, `tests/test_shared.py`, `tests/test_cli.py`).

## To repeat it

```
# the component, then its core module, then C
clang --target=wasm32-wasip2 -O1 net.c -o net.wasm                      # wasi-sdk 34; wasm32-wasip3 for 0.3
wasm2c net.wasm                                                         # fails: components are not supported
wasm-tools component unbundle net.wasm --module-dir unb -o net.unb.wasm # unb/unbundled-module0.wasm is the main core module
wasm2c unb/unbundled-module0.wasm -o core.c && cc -c -I <wabt_package>/wasm2c core.c
python -m wasmext inspect unb/unbundled-module0.wasm
cp unb/unbundled-module0.wasm hello02.wasm && wasmext natify -i -b -q hello02.wasm      # then Instance({...the 21 imports as Python callables...}) and the export "wasi:cli/run@0.2.12#run"
# a WIT of its own: wit-bindgen c <wit dir> --world lib --out-dir gen; link gen/lib.c, gen/lib_component_type.o and the implementation
```


The release assets of wasi-sdk (34.0 was the newest at the time; 35 returned 404) and of wasm-tools and wit-bindgen (0.63.0; 0.64 to 0.70 returned 404 when probed) were downloaded by URL from their GitHub releases
pages; the GitHub API was not reachable from the machine where this was tried.

The release tarballs of the first report (the working files of that session were outside the repository: `/home/claude/exp` for WIT and `wasm2c`, `/home/claude/wtmin` for Wasmtime, and the one-file extension was
`onefile/src/lib.rs`):

```sh
curl -sSfLO https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-34/wasi-sdk-34.0-x86_64-linux.tar.gz
curl -sSfLO https://github.com/bytecodealliance/wasm-tools/releases/download/v1.262.0/wasm-tools-1.262.0-x86_64-linux.tar.gz
curl -sSfLO https://github.com/bytecodealliance/wit-bindgen/releases/download/v0.63.0/wit-bindgen-0.63.0-x86_64-linux.tar.gz
```

The checks of 2026-10-21 that are marked **[again]** are in [experiments/wasi_checks](experiments/wasi_checks/README.md) (`minimal/` made with `wasm-tools component embed … --world … && wasm-tools component new`, then
`unbundle --threshold 0`; `compose` of files with kebab-case names; `meld fuse … --exports world --emit-manifest --emit-import-map`; `wasmext natify -i -b`). The commands of the first report in the order it gives them
are in [experiments/component_model/commands.sh](experiments/component_model/commands.sh), of the second report in [experiments/jco_zwasm](experiments/jco_zwasm/README.md).
Also: `wasm2c --help` (the `--disable-*` and `--enable-*` flags) and the count of the variants of `enum Trampoline` in `wasmtime-environ` 50 (`src/component/info.rs`: 52).

## Corrections to what the earlier pages and reports said

What was checked again on 2026-10-21 and found different. The earlier wording is not kept except where it is told here.

| Statement | What is right | How |
| --- | --- | --- |
| The first page: `unbundle` gives only the main module | `unbundle` takes out only modules **above `--threshold`** (default 10240 bytes); the shim and the fixup of a real component stay inside unless `--threshold 0` | [again] |
| The first report: `unbundle` leaves the wiring out | the wiring is in `rest.wasm` (the `canon lift`/`canon lower` lines), and `jco transpile` or meld turn it into code | [again] |
| The first page: `meld` made no adapter (`adapters_generated: 0`) | true of 0.63.0 on a hand-made pair; 0.64.0 fuses real composed components with `memory-copy` crossings | [again] |
| The first page: WAMR has the component model in its roadmap only | in progress in the Airbus fork (`dev/cm_wasip2_complete`) and in the upstream branch `dev/cm_wasip2` | [read] |
| The second report: exceptions, memory64, tail call, extended const and custom page sizes need a flag in `wasm2c` | only custom page sizes do; the other four are on by default (`--disable-*`); `features.json` is stale for `wasm2c` | [again] (`wasm2c --help`, WABT 1.0.42) |
| The second report: the existing 0.1 host in C is "~4.2 thousand lines" | 2886 lines of C; 4179 with the Python layer `wasi_python.h` | [again] |
| The second report: 96 KB for the WASI 0.3 program | 104 736 bytes stripped here (hello, p3) | [again] |
| The second report: the Python test calls `Instance["name"]` | it gives a capsule, not a callable; use `getattr(inst, name)` | [again] |
| `wasm-tools-package` on PyPI as a way to get `wasm-tools` | exists only as a pre-release (`1.262.0.0b1`) | [again] |
| The second report: meld is not on PyPI or crates.io | right; the names there are other projects (MELD of the Krishnaswamy Lab, jerkytreats/meld) | [again] |
| Sizes of the same program on the first page and now | differ by 13 bytes: the path of the source is in the debug information | [again] |
| The size of the JS of jco | differs on a smaller component; the reporter's figures are for the reporter's components | [again] |
| `p3/gen_p3.py` | has a path to `wasm-tools` hard-coded (kept as it was written) | [again] |

## Sources

One list for the three sources. The sites were not reachable on 2026-10-21 (see "Tools"), so these are the links of the reports as they were written.

- [natify-sh/py-wasmext, branch poc-wasm2c-ext](https://github.com/natify-sh/py-wasmext/tree/poc-wasm2c-ext)
- [WAMR: Component model support, issue #2126](https://github.com/wasm-micro-runtime/wasm-micro-runtime/issues/2126)
- [WAMR TSC meeting notes](https://github.com/bytecodealliance/wasm-micro-runtime/wiki/TSC-meeting-notes)
- [airbus-forks/wasm-micro-runtime, branch dev/cm_wasip2_complete](https://github.com/airbus-forks/wasm-micro-runtime/tree/dev/cm_wasip2_complete)
- [GordonSmith/component-model-cpp](https://github.com/GordonSmith/component-model-cpp)
- [WebAssembly/component-model: canonical ABI definitions.py](https://github.com/WebAssembly/component-model/tree/main/design/mvp/canonical-abi)
- [Wasmtime: Building a Minimal Wasmtime embedding](https://docs.wasmtime.dev/examples-minimal.html)
- [Wasmtime: Platform Support](https://docs.wasmtime.dev/stability-platform-support.html)
- [Bytecode Alliance: Wasmtime portability](https://bytecodealliance.org/articles/wasmtime-portability)
- [wasmtime-environ: component/translate/adapt.rs](https://docs.wasmtime.dev/api/src/wasmtime_environ/component/translate/adapt.rs.html), [fact.rs](https://docs.wasmtime.dev/api/src/wasmtime_environ/fact.rs.html)
- [bytecodealliance/jco](https://github.com/bytecodealliance/jco)
- [w2c2](https://github.com/turbolent/w2c2)
- [clojurewasm/zwasm](https://github.com/clojurewasm/zwasm)
- [pulseengine/meld](https://github.com/pulseengine/meld), issues [#512](https://github.com/pulseengine/meld/issues/512) and [#513](https://github.com/pulseengine/meld/issues/513)
- [WebAssembly/website features.json](https://raw.githubusercontent.com/WebAssembly/website/refs/heads/main/features.json)
