# The size of a host of WASI 0.2

Status: **a count, 2026-10-22.** How a fact is known: **[read]** the WIT of the tag `v0.2.12` of `WebAssembly/WASI` (the repository also has the branch `wasi-0.2`), parsed with `wasm-tools component wit --json`;
**[run]** the imports of the programs of the studies ([wasi_p1_vs_p2_host_requirements.md](wasi_p1_vs_p2_host_requirements.md)) and the hosts in `examples/`. Script and full table:
[experiments/wasi_p2_scope/](experiments/wasi_p2_scope/).

## The size, in numbers

WASI 0.2 is **7 packages** (`cli`, `clocks`, `filesystem`, `http`, `io`, `random`, `sockets`), **31 interfaces**. For a host the unit is an **import**: a function, or the `[resource-drop]` of a resource.
Without the two exports (`wasi:cli/run#run`, `wasi:http/incoming-handler#handle`) and without the unstable items (4 functions, hidden behind features):

| Package | Interfaces | Functions | Drops | **Imports** | Seen in programs | Implemented | Stubbed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cli | 11 | 11 | 2 | 13 | 12 | 10 | 0 |
| clocks | 2 | 6 | 0 | 6 | 6 | 6 | 0 |
| filesystem | 2 | 30 | 2 | 32 | 29 | 24 | 5 |
| http | 3 | 52 | 11 | 63 | 0 | 0 | 0 |
| io | 3 | 19 | 4 | 23 | 12 | 11 | 0 |
| random | 3 | 5 | 0 | 5 | 1 | 1 | 0 |
| sockets | 7 | 52 | 6 | 58 | 55 | 17 | 0 |
| **all** | **31** | **175** | **25** | **200** | 115 | 69 | 5 |

- **A command (the world `wasi:cli/command`) can import 137 of them in 27 interfaces** (everything above except `http`). The world `wasi:http/proxy` imports 97 in 11 interfaces (it shares io, clocks, random and a part of cli
  with the command world, and adds the 63 of `http`).
- **Four programs asked for 115 of the 137** (git, git with sockets, hello, CPython with OpenSSL; all C on wasi-libc). **22 were never asked for** by any of them: `initial-cwd`, `descriptor.get-type`, `is-same-object`,
  `filesystem-error-code`, `error.to-debug-string`, `pollable.ready`, the blocking/`skip`/`splice`/`flush`/`write-zeroes` stream calls, `get-random-u64`, `insecure*`, the unused `network` drop and similar.
- The biggest groups: **`http/types` 62** (51 functions and 11 resources: fields, requests, responses, bodies, futures), **`sockets/tcp` 29**, **`filesystem/types` 31**, **`sockets/udp` 21**, `io/streams` 17.

## What the hosts here implement

| Host | Lines | Answers |
| --- | ---: | --- |
| `examples/wasi2_unbundled` `Host` | 293 | stdout/stderr, clocks, `poll`, a TCP client (connect, read, write); the rest raises `NotImplementedError` |
| `examples/wasi2_python` `FsHost` + `NetHost` | 442 + 121 | arguments, environment, `exit`, `random`, clock resolutions, **24 of the 30 filesystem functions**, name lookup (IPv4), TCP client with address/shutdown |

Counted by name: **69 of the 200 imports are implemented, 5 are stubs** (`advise`, `sync`, `sync-data`, `set-times`, `set-times-at` answer ok and do nothing). Of the 137 of the command world, **40 were asked for and are
not implemented**: **35 in `wasi:sockets`** (18 of `tcp`, all 18 of `udp`, `create-udp-socket`: bind, listen, accept, options, datagrams) and the 5 stubs. So **what a CPython or a git on WASI 0.2 asks for is
covered by the host of `wasi2_python` except UDP and the server side of TCP**; that is why `print`, `ssl`, an HTTPS request and `pip install` ran.

## Size of the rest **[estimate]**

- To cover the **command world** (137): +63 imports on top of the 74 answered. About **35 of them are sockets** (`bind`, `listen`, `accept`, the socket options, UDP) and are the same kind of code as the TCP client
  already written (a handle table and the `socket` module of Python): in the order of 200 lines. The rest (`blocking-*` streams, `skip`, `flush`, `get-random-u64`, `initial-cwd`, `get-type`, `is-same-object`, `to-debug-string`, `pollable.ready`,
  the real `set-times`/`sync`) are one to ten lines each.
- **IPv6** is not written in the sockets (the address variants are flattened to more numbers); it adds code to every call that takes an address.
- **`wasi:http` (63) is another size**: the host needs an HTTP client and, for `incoming-handler`, a server, and the types (`fields`, `request`, `response`, `incoming-body`, `future-incoming-response` with `poll`) are
  resources with ownership rules; no program here uses it. It is the largest block after sockets and filesystem, and CLI programs do not need it.
- **Not a sandbox:** the filesystem host trusts the guest's paths (`..`, symbolic links); a real host has to confine them. This is a size, not a count.
- The implemented functions are not all complete: for example `input-stream.read` never blocks (it answers an empty list when nothing is ready) and the TCP connect is blocking.

## Against the WASI 0.1 wasmext has in C

wasmext's WASI 0.1 (`wasi_core.h`, 1990 lines in C inside the module) answers `wasi_snapshot_preview1` in C (the study counted 42 of the 46 calls the programs made) and asks the host for none; WASI 0.2 asks the host for **137 imports for a command** (200 with `http`).
Same programs, same results ([wasi_p1_vs_p2_host_requirements.md](wasi_p1_vs_p2_host_requirements.md)). A host of 0.2 inside the module would be a work of the size of `wasi_core.h` plus the canonical ABI
(strings, lists, results through memory, resources as handles).
