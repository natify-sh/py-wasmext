# Why WASI 0.2 (preview 2): the principle, the evidence and the price

Status: **written 2026-10-28** from the owner's statement of the same day and from the studies in this repository ([wasi_p1_vs_p2_host_requirements.md](wasi_p1_vs_p2_host_requirements.md), [WASI_COMPONENTS.md](WASI_COMPONENTS.md)). Where a line is the owner's word and not something measured here, it says so. The plan of the work is [WASI_TARGET_PLAN.md](WASI_TARGET_PLAN.md); the concept of the `host` setting is [wasi_target.md](wasi_target.md).

## The principle

**Take an unmodified WebAssembly module, compiled for a given target, and run it.** Do not tell people how to patch or configure the original sources. That is what `wasmext`, `wasmhost` and `fusedwasi` are for: the host side (the WASI functions, the state they need, the linking) is ours, so that the module and its sources stay as their authors made them (the owner, 2026-10-28).

A feature that works only when the user patches the source, or builds the program in a special way, is a **gap** to write down, not a recipe to hand out.

## Why WASI 0.2 follows from the principle

1. **A program built for `wasm32-wasip2` needs fewer changes than the same program for `wasm32-wasip1`**, wherever it uses the network or the system interfaces that wasi-libc of 0.2 brings with it (below). The owner's reading of the experiments: WASI 0.2 works more natively.
2. **The owner's statement: WASI 0.2 is the production-ready version of WASI now.** That is a judgement about the standard, not a measurement made here; it is the reason to build the support on 0.2 and not to wait for the next version.
3. Some of our examples, and of the programs of other people, are much easier to run through 0.2 for exactly the reason in point 1: less preparation of the sources before they are compiled to WebAssembly.

## What the experiments showed, exactly

One compiler (wasi-sdk 34), the same flags, the same sources, built for both targets (2026-10-22; tables in `experiments/wasi_p1_p2_git/` and `experiments/wasi_p1_p2_cpython/`).

| | WASI 0.1 (`wasm32-wasip1`) | WASI 0.2 (`wasm32-wasip2`) |
| --- | --- | --- |
| **git (libgit2 and `git.git`)** | `netdb.h` is missing; the socket stream of libgit2 **does not compile**: a bridge to the host was written (`stubs/socket.c`, 127 lines, four imports of our own) | `netdb.h` and the sockets come with wasi-libc; `socket.c` compiles as it is; `dup` and `dup2` are there (the old stubs make the link fail); up to 10 stubs fewer |
| **CPython 3.15** | 0 changes in the sources, 0 shims for missing headers | the same: **0 and 0**. `configure` finds 20 more `HAVE_*` (`socket`, `connect`, `getaddrinfo`, `netdb.h`...); `pyconfig.h` differs in 21 definitions |
| the same on both | no processes (`fork`, `exec*`), `pwd.h`, `syslog.h`, `termios.h` and a few more headers missing, the stack of 64 KiB (`-z stack-size`) | the same |

So the claim is narrower than "0.2 needs less patching": **it holds where the program needs the network and the system interfaces** (git: yes; the core of CPython: no difference, but more of it works without a patch on 0.2). CPython needs the compiler to be named for 0.2 (`CC`, `CPP`, `CXX` with `--target=wasm32-wasip2`), or the build makes a module for 0.1 under the name of a component.

## What it costs

- **The host has to give much more.** A module of 0.1 that wasmext builds asks the host for nothing (the WASI is inside it, in C); a module of 0.2 asks for 53 or 54 imports (109 with sockets), in the canonical ABI. This is the price that **fusedwasi** pays down: the functions of WASI 0.2 in C and in Python, with their state.
- **No TLS and no processes in 0.2.** `https://` needs a library in the program or an interface of our own; `fork`/`exec` stay impossible.
- **CPython does not support `wasm32-wasip2` officially** (`PY_SUPPORT_TIER` 0).
- **`wasm2c` does not read a component.** The component is turned into a core module first: `wasm-tools component unbundle` or `meld fuse` (fusedwasi's README has the commands, tried on 2026-10-28). That is a step on the **artifact**, not a patch of the **sources**; it still is a step the user takes, and it is written down as a point to keep an eye on against the principle (below).
- **WASI 0.3 and async are not supported.** `meld` 0.65 does not keep the async part of the canonical ABI, so support through it would be partial.

## What exists and was checked

- `host="wasm32-wasip2"`, the imports typed in the stubs, the default WASI 0.2 host on fusedwasi.
- `examples/wasi2_unbundled` (two C programs, the sockets one included) and `examples/wasi2_python` (CPython with OpenSSL: `print(1 + 1)`, `ssl`, `hashlib`, `socket.getaddrinfo`, `pip install` over HTTPS to a local server). Both were run again on 2026-10-28 with `fusedwasi` 0.1.0a1 from PyPI.
- `fusedwasi` 0.1.0a1 is published (C headers and the Python twin; 0.1 is implemented over 0.2 in one state).

## Open points against the principle

1. **The step component -> core module** is not a patch of sources, but it is something the user does. Whether wasmext should take a component directly (call `unbundle`/`meld` itself, or read the component) is not decided.
2. **`https://`** (TLS) is not in WASI 0.2: the programs that need it have to carry a library, which is a build matter again.
3. **Processes** are not in 0.1 or 0.2: `git` remote helpers, hooks and `stash` stay impossible.
4. **wasmhost** runs WASI 0.1 only today (`wasmhost.wasi.preview1`); running fused modules of 0.2 there is not decided (see its `ROADMAP.md`).
5. **WASI 0.3** is out of scope until `meld` keeps the async ABI.
