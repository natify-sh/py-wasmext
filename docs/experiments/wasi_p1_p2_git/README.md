# git on WASI 0.1 and WASI 0.2: what the build lacked and what the host has to give

The sources and scripts of the study in [../../wasi_p1_vs_p2_host_requirements.md](../../wasi_p1_vs_p2_host_requirements.md) (the report: read that first). One program, built
twice with the same compiler, and used in three ways, to see which version of WASI and which way of deploying it asks least of the host.

How a fact is known: **[run]** run in a session of this repository on 2026-10-22 (Linux x86-64, 4 cores, wasi-sdk 34.0 = clang 23.1, wasm-tools 1.262.0, meld 0.64.0 built from
source at `30545b3`, WABT 1.0.42 from `wabt-package`), **[read]** read in source code or a header. The CPython target is not here yet.

## The program

| Name | What | Sources |
| --- | --- | --- |
| `lg2` | a git client of about 550 lines on **libgit2** 1.9.0 | `examples/git` of natify-sh/py-wasmhost (`lg2.c`, `compat.c`, `stubs/`), libgit2 from the crate `libgit2-sys 0.18.1+1.9.0` |
| `git.git` | **git itself**, 2.56.0, no libgit2 | `git-2.56.0.tar.xz` and `examples/git/real` of py-wasmhost (`wasi_compat.c`, `wasi_compat.h`) |

Both are built the way py-wasmhost builds them for WASI 0.1 (there with `zig cc`), here with **wasi-sdk 34**, which has `wasm32-wasip1` and `wasm32-wasip2` for the same clang. Checksums of the
tarballs are those that py-wasmhost pins. The only change that is not a shim: the stack is 1 MiB (`-Wl,-z,stack-size=1048576`); the default of wasi-sdk is 64 KiB, and libgit2 then traps
(out of bounds) while it creates a repository **[run]**.

## The variants

| Variant | Target | What the host gets as imports |
| --- | --- | --- |
| **p1** | `wasm32-wasip1`, a core module | `wasi_snapshot_preview1` |
| **p2, unbundled** | `wasm32-wasip2` makes a component; `wasm-tools component unbundle --threshold 0` takes the core module out | `wasi:*@0.2.12`, canonical ABI |
| **p2, meld** | the same component through `meld fuse --exports world` | the same, in one core module made by meld |
| **p2n** | `wasm32-wasip2` where nothing is replaced in the network code (the sockets of wasi-libc are used) | the above plus `wasi:sockets/*` |

## Results

### What the build lacked

| Missing | p1 | p2 | p2n | Note |
| --- | --- | --- | --- | --- |
| `pwd.h` (libgit2, git) | shim (9 lines) | shim | shim | wasi-libc has none on either target |
| `syslog.h`, `termios.h`, `sys/wait.h`, `grp.h`, `paths.h` (git) | 5 shims (50 lines) | the same | the same | none on either target; the system headers that git includes were scanned against both sysroots (83): besides these and `netdb.h` only Windows, BSD and optional-library headers are missing |
| `netdb.h` (git, libgit2) | **missing**: shim (23 lines) for git; libgit2's own `socket.c` **does not compile** | present | present | the one difference in the headers **[run]** |
| libgit2's `socket.c` | replaced by a bridge to the host (`stubs/socket.c`, 127 lines, 4 custom imports) | as it is | as it is | on p1 there is no way to compile the original |
| `process.c` of libgit2 | stub (35 lines) | the same | the same | no processes in WASI 0.1 or 0.2 |
| `wasi_compat.c` of git (113 lines: `fork`, `exec*`, `pipe`, `getuid`, … fail) | all | **2 lines fewer** (`dup`, `dup2` exist in wasi-libc of p2: the build fails with a duplicate symbol if the stubs stay) | **10 lines fewer** (also `getaddrinfo`, `freeaddrinfo`, `getnameinfo`, `gai_strerror`, `socket`, `connect`, `setsockopt`) | |
| TLS for libgit2 | the host does it (`wasmhost_net.connect(..., tls)`) | none | none: `tls_none.c` (3 lines) | WASI 0.2 has no TLS interface |
| two patches of git's source (`setup.c`, `merge.c`) | yes | yes | yes | no `/dev/null`, no child `git` |
| stack 1 MiB | yes | yes | yes | |

### What the host has to give (imports)

| Variant | `lg2` (libgit2) | `git.git` | Interfaces |
| --- | --- | --- | --- |
| p1, through wasmext | **0** (WASI is inside the module) | **0** | — |
| p1, on another host | 29 | 34 | 1 (`wasi_snapshot_preview1`), numbers only |
| p1 with the network of py-wasmhost | 33 (29 + 4 `wasmhost_net`) | — | 2 |
| p2, unbundled | 53 | 54 | 18 |
| p2, meld | 53 (the same set, another order; plus a table of 35 thunks) | 54 | 18 |
| p2n, unbundled or meld | 108 | 109 | 24 (`wasi:sockets/*` adds **55**: tcp 28, udp 20, ip-name-lookup 4, instance-network 1, two create-socket) |

The 20 imports of UDP are there although git does not use UDP: the sockets of wasi-libc are one object that wants the whole interface.

### Do they run

| | Result |
| --- | --- |
| p1 through wasmext, `lg2` and `git.git` | **yes**: `init`, `add`, `commit`, `log`, `status`; `Instance(wasi={"args", "env", "preopens", "stdout", "stderr"})` is all the host does (`run_p1_wasmext.py`) |
| p2 with the host of `examples/wasi2_unbundled` as it is | **does not link**: `LinkError: missing import module 'wasi:filesystem/types@0.2.12'`; the host writes 25 of the 54 imports (17 written, 8 resource drops) and does not list the filesystem, `environment`, `exit` or `random` at all |
| p2 with six additions (arguments, environment, `exit`, `exit-with-code`, an empty `preopens`, `get-random-bytes`: `run_p2_minihost.py`) | `git --version` **runs**, with **12** different imports called; `git init` stops: `fatal: cannot change to '/'` (the next thing it needs is a directory) |
| p2, unbundled and meld | the same for both **once the C of wasm2c is repaired** (below); before, the meld module traps at its first call |

### The way of use: unbundled or meld

- For **one component** the two give the same set of imports and the same exports (`memory`, `wasi:cli/run@0.2.12#run`, `cabi_realloc`). meld adds 35 small functions and a table.
- meld's module **trapped under wasmext before the first import** (and ran in V8). The cause is a bug of `wasm2c` 1.0.42 (and `main`): an imported function put into a table by an element segment gets the
  *address of a field* of the module instance instead of the pointer to the import's instance. meld puts every WASI import into such a table. `patch_import_elem.py` repairs the generated C (a new
  kind of entry); a minimal reproduction in plain C and a draft of the issue are in `wabt_issue/`. With it, `lg2` and `git.git` behave the same as unbundled (`git --version` runs).
- For **several components** (not git): `unbundle` with the default threshold (10240 bytes) takes **nothing** out of small modules, `--threshold 0` is needed; meld duplicates a WASI import for each
  component (`get-random-bytes`, `get-random-bytes$1`), and the memory and `realloc` of each are exported as `memory`, `memory$0`, `realloc`, `realloc$0`, `cabi_realloc$1`: which belongs to which is not told
  (the import map of meld says only `"kind": "wasi"`). Its adapters did not carry a **string** in a test of three levels of nesting: `jco` and V8 gave the right answer, the fused module gave an empty result.

## Files

| File | What |
| --- | --- |
| `gitbuild.sh` | `git.git` for `p1`, `p2`, `p2n` (`WORK`, `SDK`, `REAL` are variables) |
| `commands.sh` | the commands of the study in order (libgit2 builds, unbundle, meld, wasmext); not a script to run as it is |
| `shim/`, `shim_p1/` | the headers that wasi-libc lacks (`shim_p1/netdb.h` is for p1 only) |
| `socket_nonet.c`, `tls_none.c` | libgit2's socket stream without the host bridge; the answer of "no TLS" |
| `run_p1_wasmext.py` | `git init/add/commit/log/status` through the extension of a p1 module |
| `run_p2_minihost.py` | p2 on the host of `examples/wasi2_unbundled` with the six additions; which imports are called |
| `patch_import_elem.py` | the repair of the C of wasm2c for imported functions in element segments |
| `wabt_issue/` | the reproduction and the draft of the issue for WABT |

## Not done

- **CPython** (the next target of the study).
- The filesystem of WASI 0.2 in the host (`descriptor`, `open-at`, `read-via-stream`, …): 22 methods, the largest part of what is missing; `git init` is the first thing that needs it.
- HTTPS: no TLS in the program (libgit2 with USE_HTTPS=OFF) and none in WASI 0.2.
- The sockets of p2n were not run: the host of the example has a TCP client only, and git needs the name lookup too.
- Speed and size of the results beyond the file sizes (p1 1.20 and 4.07 MB, p2 1.39 and 4.27 MB, p2n 4.38 MB).
