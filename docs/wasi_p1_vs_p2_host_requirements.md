# WASI 0.1 or WASI 0.2: what the build lacks and what the host has to give (a study of git)

Status: **a study, done on 2026-10-22: git first, then CPython 3.15 (the section at the end).** The tables, the scripts and the sources are in
[experiments/wasi_p1_p2_git/](experiments/wasi_p1_p2_git/) (its `README.md` has the full tables); this page is the reading of them. How a fact is known: **[run]** run in a session of
this repository, **[read]** read in source code or a header, **[estimate]** a judgement.

## The question

Which version of WASI, and which way of deploying it with wasmext, asks **least of the host**? Two guesses were put to the test:

1. *WASI 0.2 may ask more of the host but needs less patching before the compilation.*
2. *WASI 0.2 should be able to build git itself (`git.git`), not only the client on libgit2.*

One program (git, as `lg2` on libgit2 and as `git.git` 2.56.0), one compiler (wasi-sdk 34, `wasm32-wasip1` and `wasm32-wasip2`), the same flags, the sources and the checksums of
py-wasmhost (`examples/git`, `examples/git/real`), and three ways of use: a WASI 0.1 module, a WASI 0.2 component taken apart with `wasm-tools component unbundle`, and the same component
fused by `meld fuse`; each through `wasmext natify`.

## The answer in short

| | Imports the host gives | Patching to build | Runs |
| --- | --- | --- | --- |
| **WASI 0.1, through wasmext** | **0** (WASI is inside the module; the host passes arguments, environment, folders, streams) | the most: libgit2 does not compile its sockets (no `netdb.h`), so a bridge to the host is needed | **yes** (`init`, `add`, `commit`, `log`, `status`) |
| WASI 0.1, on another host | 29 (libgit2) or 34 (git.git), numbers only | the same | not tried here |
| **WASI 0.2** (unbundled or meld) | **53 or 54**, in 18 interfaces, in the canonical ABI (strings, lists and `result` through memory, resources as handles) | less: `netdb.h` and the sockets come with wasi-libc; two stubs fewer (`dup`, `dup2`) | `git --version` yes, with 12 imports and a host of 6 additions; `git init` needs the filesystem, which the host does not have |
| WASI 0.2 with sockets | **108 or 109**, in 24 interfaces (+55 for `wasi:sockets`) | the least: 10 stubs fewer, libgit2's own sockets | not run |

**WASI 0.1 inside a module that wasmext builds gives the smallest demand on the host: none.** WASI 0.2 asks 53 to 109 imports because wasmext, as of now, builds the WASI of 0.1 itself (in C, in the
module) and has no WASI 0.2 of its own: all of it falls to the host. The first guess is **right in both halves**: 0.2 asks much more of the host (a host of the example runs 25 of 54 by name and does
not link) and it needs less patching (below). Whether one weighs patching of the build more than the host depends on who builds and who runs.

## What the build lacked, and the shims

Details and line counts are in the README of the experiment. What the two targets share, and what differs **[run]**:

- **Missing on both targets** (shims of a few lines each): `pwd.h`, `syslog.h`, `termios.h`, `sys/wait.h`, `grp.h`, `paths.h`. wasi-libc of wasi-sdk lacks them; `zig cc` brought them, which is why
  py-wasmhost did not need these. Of 83 system headers that git includes, only these and `netdb.h` are missing for a reason that matters (the others belong to Windows, BSD or optional libraries).
- **Missing on WASI 0.1 only: `netdb.h`.** For git it is a shim of 23 lines; for libgit2 it is worse: its own socket stream **does not compile**, so a replacement is needed that talks to the host
  (`stubs/socket.c`, 127 lines, four custom imports `wasmhost_net`, and the host does TCP and TLS). On WASI 0.2 libgit2's `socket.c` compiles as it is.
- **Stubs of py-wasmhost that WASI 0.2 does not need:** `dup` and `dup2` (wasi-libc of p2 has them; the link fails with a duplicate symbol if the stubs stay), and, if the network is wanted,
  `getaddrinfo`, `freeaddrinfo`, `getnameinfo`, `gai_strerror`, `socket`, `connect`, `setsockopt` (10 lines of 113 in all).
- **The same everywhere:** `process.c` (no processes in 0.1 or 0.2), `wasi_compat.c` (`fork`, `exec*`, `pipe`, `getuid`, … fail), two patches in git's source, and **the stack**: wasi-sdk gives 64 KiB, and libgit2
  then traps while it creates a repository, so the link has `-Wl,-z,stack-size=1048576`.
- **What does not go away on 0.2:** processes (git's remote helpers, `stash`, hooks), and **TLS**: WASI 0.2 has sockets and no TLS, so `https://` needs a library in the program or an interface of
  our own (`wasmhost_net` was one; as a WIT interface it would be kept as an import by `unbundle` and `meld`).

The second guess, **git itself on 0.2**, is right: `git.git` 2.56.0 builds for `wasm32-wasip2` with the same recipe, and, taking out the stubs of the network, with the real sockets of wasi-libc (by git's own code `git://` is in-process, so no helper should be needed for it, and `http(s)` is a child process and stays impossible; **not run**, with or without a network).

## What the host has to give

- **WASI 0.1 (29 or 34 functions)** are numbers: pointers, lengths, descriptors. wasmext writes them in C into the module (42 of the 46 calls), so the host passes configuration only.
- **WASI 0.2 (53 or 54 imports)**: 8 are `[resource-drop]`, and most of the rest pass `result`, `list`, `string` or `option` through memory (`cabi_realloc` of the module) or return a handle. By family: 22 are
  methods of the filesystem (`descriptor`, `directory-entry-stream`), plus `preopens`, 2 `environment`, 2 `exit`, 1 `random`, the standard streams and `poll`, two clocks.
- **What a host of 0.2 has to do first**, measured **[run]** on the host of `examples/wasi2_unbundled` with the smallest additions (arguments, environment, `exit-with-code`, an empty `preopens`, random bytes):
  `git --version` calls **12** different imports and prints `git version 2.56.0`; `git init` stops at "cannot change to '/'": it needs a **preopened directory**, and with it the 22 methods of the filesystem.
- **The host of the example does not link the program as it is**: its table of imports was made for the two demo programs, which use no filesystem. It writes 25 of the 54 by name.
- **Sockets add 55 imports** (tcp 28, udp 20, ip-name-lookup 4, network and the two create-socket functions); the 20 for UDP are there only because wasi-libc's sockets are one object. The example host has
  a TCP client (10 of them).

## Unbundled or meld

- **One component** (git): the same imports, the same exports; meld's module has 35 more functions and a table of thunks, and its imports are in another order. Nothing is gained by meld here, and a tool
  more is needed. `unbundle` also needs no `--exports` choice (without `--exports world` meld exports its tables too).
- **Several components** (not git; a test of two and of three levels of nesting): `unbundle` gives a core module for each component and a `rest.wasm` with the wiring (a threshold of 0 is needed, or small modules stay
  inside `rest.wasm`): every module needs its own host bound to its own memory, and the calls between components are left to whoever uses the modules. `meld` makes one module with a memory for each
  component, and the adapters between them, but a WASI import that two components use becomes **two imports** (`get-random-bytes`, `get-random-bytes$1`) and the host has to know which memory and
  `realloc` belongs to which (exported as `memory`, `memory$0`, `realloc`, `realloc$0`, `cabi_realloc$1`; the import map does not say). Its adapters did not carry a **string** (an empty result; `jco` and V8 gave
  the right one).
- **A bug of `wasm2c` found on the way, and a repair.** meld puts every import into a table, and `wasm2c` 1.0.42 (and `main`) gives an imported function placed in a table by an element segment the *address
  of a field* of the instance instead of the pointer to the import's instance. Under wasmext the meld module trapped at the first call (zero imports called; in V8 it ran). It is not a bug of meld or of wasmext.
  Reported: [WABT #2896](https://github.com/WebAssembly/wabt/issues/2896) (the draft is in `experiments/wasi_p1_p2_git/wabt_issue/`). **wasmext repairs it** as it does the other bugs of the C of `wasm2c`
  (`_repair_imported_elements` in `_natify.py`; FEATURES.md, "Patch for an imported function in an element segment"): a new kind of entry that reads the pointer. With it the meld module of `lg2` and of
  `git.git` runs as the unbundled one, built by `natify` itself, also in many files **[run]**.

## What it means for wasmext

1. For **the least demand on the host**, a program compiled for **WASI 0.1** is the better target as long as wasmext provides WASI 0.1 and not 0.2.
2. For **the least patching** and a standard way to the network, **0.2** is better — but wasmext would have to carry a host of 0.2: a filesystem (22 methods), `environment`, `exit`, `random`, and, for
   the network, `wasi:sockets` (name lookup and TCP). The example host has the standard output streams, `poll`, the clocks and a TCP client, and none of the filesystem. A host of 0.2 inside the module, in C, as the one of 0.1 is, would bring the demand
   on the host back to nothing; it is a work of a size of `wasi_core.h` for 0.2, not designed here.
3. **Unbundled** is the simpler way for one component; **meld** is for composed ones, and it needs the repair above and has the open questions about the memory of each import and about strings.
4. Done in the code because of this study: `wasi_flavor` tells the output of `meld fuse` as `fused` (it was told `none` or `core-0.2`) and warns only when such a module imports WASI 0.2 or 0.3; and the repair of the C of `wasm2c` for imported functions in element segments.

## CPython 3.15

The same method (`experiments/wasi_p1_p2_cpython/`; its `README.md` has the tables): commit `1c6794e` of python/cpython, the build that CPython ships (`Platforms/WASI`), wasi-sdk 34, the standard library of py-wasmhost to run it.
The expectation was that CPython would be the harder one; **for the build it was the easier one**.

| | git (`git.git`) | CPython |
| --- | --- | --- |
| Changes to the sources | 2 patches | **0** |
| Shims for headers | 6 on both targets, + `netdb.h` on p1 | **0** |
| What the target asks for | stubs of `wasi_compat.c` (113 lines), some removable on p2 | **the compiler**: for p2, `CC`, `CPP` and `CXX` with `--target=wasm32-wasip2` have to be given, or the script builds **a wasip1 module under the name of wasip2** (`--host-triple` changes only the triple of `configure`) |
| Host, p1 through wasmext | **0** imports | **0** imports (42 for another host) |
| Host, p2 | 54 (109 with the sockets) | **115**: git with the sockets + 6 (`monotonic-clock.resolution`, `wall-clock.resolution`, four filesystem methods) |
| Runs | p1 yes; p2: `--version` with 12 imports | p1 yes (`json`, `hashlib`, `zlib`, `decimal`; `socket` fails: `Errno 58`); p2: `--version` with 8 imports, `-c` stops at the standard library |

- **CPython asks for the sockets on p2 whether the program uses them or not** (55 of the 115 imports): `_socket` is built, and the sockets of wasi-libc are one object. A host of 0.2 for CPython has to have, or
  refuse in an orderly way, the whole of `wasi:sockets` (tcp 28, udp 20, name lookup 4) and 28 methods of the filesystem. WASI 0.1 cannot do sockets at all (`socket.socket()`: `Errno 58`; `getaddrinfo` is not in `_socket`).
- CPython itself marks the wasip2 target as `PY_SUPPORT_TIER 0` (not supported); the build passes all the same, and `configure` finds 20 more functions of the network.
- `unbundle` and `meld` give the same set of imports for CPython, as for git; with the repair of the C of `wasm2c` (WABT #2896) the meld module runs as the unbundled one.
- The answer to the question does not change: **WASI 0.1 through wasmext asks nothing of the host** (the whole of a Python that runs `json`, `hashlib`, `zlib`, `decimal` is a module and a few settings), and WASI 0.2 asks for 115 imports, of which the filesystem is what `python -c` needs first.

- **pip and the network.** With OpenSSL built for `wasm32-wasip2` (static, `no-threads`, `no-quic`) CPython gets `_ssl` and `_hashlib` and the host's imports stay the same (25 interfaces), so TLS
  can be in the module and WASI 0.2 needs no TLS interface; one workaround (`OPENSSL_THREADS` defined by hand). **Run** with a host in Python that adds the filesystem, name lookup and TCP to the example host ([examples/wasi2_python](../examples/wasi2_python/)): `print`, `ssl`, an HTTPS request with the certificate checked in the module, and `pip install` from a local HTTPS index. Details in
  [experiments/wasi_p1_p2_cpython/README.md](experiments/wasi_p1_p2_cpython/README.md). WASI 0.1 has no sockets: only a bridge to the host (as py-wasmhost does) gives it a network.

## Awaiting upstream

- **meld** [#512](https://github.com/pulseengine/meld/issues/512) (closed by [#516](https://github.com/pulseengine/meld/pull/516)) and [#513](https://github.com/pulseengine/meld/issues/513) (closed by [#518](https://github.com/pulseengine/meld/pull/518)): both are in **meld 0.65.0**, whose release pull request is [#521](https://github.com/pulseengine/meld/pull/521) (its changelog: deep copy of nested `list<string>` in option/result/variant; `--emit-import-map` states memory, realloc, string encoding and owner of each import, version 2); **merged into `main` upstream on 2026-10-22 (told by the owner), not published as a release yet**. The multi-component results here (strings through adapters, the duplicated imports, which memory an import belongs to) were measured on meld 0.64.0: to repeat on 0.65.0.
- **WABT** [#2896](https://github.com/WebAssembly/wabt/issues/2896) (imported function in an element segment; repaired in wasmext meanwhile) and
  [#2897](https://github.com/WebAssembly/wabt/issues/2897) (compact imports, encoding `0x7E`; wasmext normalizes before `wasm2c`): open.

## Not done

- PyPI itself (no outbound TCP in the session); threads; UDP and IPv6 in the host. The filesystem, the sockets, HTTPS and the standard library for p2 are done in the example `examples/wasi2_python` (not a part of wasmext).
- Measurements of speed; one machine, one compiler.
