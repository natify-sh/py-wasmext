# CPython 3.15 on WASI 0.1 and WASI 0.2: what the build lacked and what the host has to give

The sources and scripts of the CPython part of the study in [../../wasi_p1_vs_p2_host_requirements.md](../../wasi_p1_vs_p2_host_requirements.md); the same method as for git in
[../wasi_p1_p2_git/](../wasi_p1_p2_git/README.md): one program, one compiler, two targets, and three ways of use. How a fact is known: **[run]** run in a session of this repository on
2026-10-22 (Linux x86-64, 4 cores, wasi-sdk 34.0 = clang 23.1, wasm-tools 1.262.0, meld 0.64.0 at `30545b3`, WABT 1.0.42 from `wabt-package`), **[read]** read in source code.

## The program and the variants

CPython 3.15.0+dev, commit `1c6794e` of python/cpython (the one that py-wasmhost pins), built with **the build that CPython itself ships**, `Platforms/WASI` (`build-python` for the Python that the
cross build needs, then `build-host`). Nothing else of py-wasmhost is used except `lib/python315.zip` (the standard library as byte code, made from the same commit by its `mkstdlib.py`) to run the result.

| Variant | Target | How it is used |
| --- | --- | --- |
| **p1** | `wasm32-wasip1`, a core module (`python.wasm`) | through wasmext, which has WASI 0.1 in the module |
| **p2, unbundled** | `wasm32-wasip2`, a component; `wasm-tools component unbundle` takes the module out | WASI 0.2 for the host |
| **p2, meld** | the same component through `meld fuse --exports world` | the same, in the module that meld made (wasmext repairs the C of wasm2c for it: WABT #2896) |

## What the build lacked

| | p1 | p2 | Note |
| --- | --- | --- | --- |
| Changes to the sources of CPython | **0** | **0** | the shipped `Platforms/WASI` and `config.site-wasm32-wasi` did all |
| Shims for missing headers | **0** | **0** | (git needed six on both targets) |
| zlib | built by hand (the 9 files of the zlib that the crate of libgit2 carries, 85 KB) | the same | wasi-sdk has none; without it `zlib`, `gzip` and `zipfile` with compression are missing |
| **The compiler** | as the script sets it | **`CC`, `CPP`, `CXX` with `--target=wasm32-wasip2` have to be given** | `--host-triple wasm32-wasip2` only changes the triple for `configure`: the script runs wasi-sdk's `clang`, whose default target is wasip1, **and builds a wasip1 module under the name of wasip2** (the file has the same size as the p1 one and starts `00 61 73 6d 01 00 00 00`, not `0d 00 01 00`) **[run]** |
| What `configure` finds | no sockets, no `netdb.h` | 20 more `HAVE_*`: `socket`, `connect`, `bind`, `listen`, `getaddrinfo`, `getnameinfo`, `gethostbyname`, `netdb.h`, … | `pyconfig.h` differs in 21 definitions; `PY_SUPPORT_TIER` is 2 for p1 and **0 for p2** (not supported by CPython) |
| Extension modules not built | 36 | the same 36 | `_sqlite3`, `_curses`, `fcntl`, `mmap`, `pwd`, `termios`, … on both; `_socket` is built on both |
| Stripping | `llvm-strip` (7.95 MB) | `llvm-strip` fails on a component (`invalid version number`); `wasm-tools strip` (8.29 MB) | |
| Time (4 cores) | native Python 2 min 36 s; cross 2 min 0 s | 2 min 2 s | |

## What the host has to give

| Variant | Imports | Interfaces | Size |
| --- | --- | --- | --- |
| p1, through wasmext | **0** (WASI is inside the module) | — | 7.95 MB |
| p1, on another host | 42 | 1 (`wasi_snapshot_preview1`) | 7.95 MB |
| p2, unbundled | **115** | 24 | 8.27 MB |
| p2, meld | 115 (the same set, one more table of 83 thunks) | 24 | 8.00 MB |

By interface (p2): filesystem 28 + `preopens` 1, **sockets 55** (tcp 28, udp 20, ip-name-lookup 4, network 1, two create-socket), clocks 6, `io` 12, `cli` 12 (arguments and environment 2, exit 2, standard streams
and terminals 8), `random` 1. It is the set of `git.git` on p2 with the sockets (109 imports) **plus six**: `monotonic-clock.resolution`, `wall-clock.resolution` and the filesystem methods `advise`, `set-times`, `sync-data`, `write` **[run]**.
**CPython asks for the sockets whether the program uses them or not**, because the sockets of wasi-libc are one object and `_socket` is built.

## Does it run

| | Result |
| --- | --- |
| p1 through wasmext | **yes**: `python --version`, `sys.platform == "wasi"`, `json`, `re`, `hashlib`, `zlib`, `decimal` run; four runs take 0.36 s in all, with the instance made each time (`run_p1_wasmext.py`, with `lib/python315.zip` of py-wasmhost as `/py`) |
| p1, sockets | `socket.socket()` → `OSError [Errno 58] Not supported`; `socket.getaddrinfo` → `AttributeError: module '_socket' has no attribute 'getaddrinfo'` (`HAVE_GETADDRINFO` is not defined there) (`run_p1_sockets.py`) |
| p2 on the host of `examples/wasi2_unbundled` with six additions (as for git) | `python --version` **runs**, with **8** different imports called, for the unbundled and the meld module alike; `python -c "print(1 + 1)"` stops: `WARN: Could not find the standard library directory`, exit 1, after 11 imports — it needs a **preopened directory with the standard library**, that is, the filesystem (`run_p2_minihost.py`) |

## Files

| File | What |
| --- | --- |
| `cpbuild.sh` | `native` (the build Python), `zlib p1|p2`, `host p1|p2 [configure arguments]`; for p2 pass `CC=`, `CPP=`, `CXX=` with `--target=wasm32-wasip2` |
| `run_p1_wasmext.py` | CPython on the extension of the p1 module |
| `run_p1_sockets.py` | what `socket` does on p1 |
| `run_p2_minihost.py` | p2 on the host of the example plus six additions; which imports are called |

The unbundle, meld and natify commands are those of [../wasi_p1_p2_git/commands.sh](../wasi_p1_p2_git/commands.sh).

## pip and the network: TLS (`_ssl`) on WASI 0.2

Why: py-wasmhost wanted a working network for `pip`. WASI 0.1 has no sockets (`Errno 58`); WASI 0.2 has `wasi:sockets` but no TLS, and the build above had no `_ssl` ("Could not build the ssl module").

**[run]** OpenSSL 3.5.0 builds for `wasm32-wasip2` with wasi-sdk 34 (`opensslbuild.sh`: `libcrypto.a` 6.2 MB, `libssl.a` 0.9 MB). Needed on the way: `no-quic` (`socketpair`), `-DOPENSSL_NO_UNIX_SOCK` (no `sun_path`),
`no-threads` (`pthread_exit` is missing; with `threads` the build fails). CPython 3.15 with `--with-openssl=...` then builds **`_ssl` and `_hashlib`** (modules: 81 built-in, was 79; missing 7, was 9; `python.wasm` 36.4 MB,
was 32.7 MB). **The imports of the host did not change**: the same 25 interfaces (`wasi:sockets` is there already; OpenSSL asks nothing new of WASI).

**One workaround:** CPython refuses OpenSSL without `OPENSSL_THREADS`, and this OpenSSL is built `no-threads`; the macro is defined by hand in the installed `configuration.h`. WASI has no threads, so nothing runs in two threads,
but it is a workaround, not a clean fix (a clean one would be a CPython option for a single-threaded OpenSSL, or `pthread_exit` in wasi-libc).

**Run [run]:** with a host in Python that has the filesystem (over `os`), name lookup and a TCP client, now in [examples/wasi2_python](../../../examples/wasi2_python/) (the host of `examples/wasi2_unbundled` plus `fshost.py` and `nethost.py`),
the unbundled module runs through wasmext: `print(1 + 1)`, `import ssl` (`OpenSSL 3.5.0`), `getaddrinfo`, an `https://localhost` request with the certificate checked **inside the module**, and
**`pip install` of a wheel from a local HTTPS index** (48 imports called). The host gave no TLS interface. Found on the way: `ensurepip` needs a child process (not on WASI; pip is run in the same process instead); pip needs `os.getuid`, `os.umask` and `mmap`
(shimmed in the guest); the host must report a large `check-write` for files, or writes through `os.write` are cut to 4096 bytes. **Not tried:** PyPI itself (no outbound TCP in the session), a CA bundle other than pip's own, UDP, IPv6, a sandbox.

## Not done

- The standard library for the p2 run: the filesystem of WASI 0.2 in a host (22 to 28 methods) is the first thing `python -c` needs.
- The sockets of p2 were not run (`socket` is in the build; the host of the example has a TCP client only); HTTPS has no TLS on either target.
- `ssl`, `sqlite3`, `bz2`, `lzma`, `ctypes`, threads: not built on either target (the shipped configuration); no extension modules that load from files (no `dlopen`).
- Speed and memory; one machine.
