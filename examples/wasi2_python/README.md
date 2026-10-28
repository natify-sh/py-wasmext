# wasmext-example-wasi2-python

CPython 3.15 built for **WASI 0.2** (with OpenSSL, so `ssl` works), turned into a native CPython extension by wasmext, and run on a **host written in Python**
that answers the WASI 0.2 calls: filesystem, name lookup and a TCP client. TLS is inside the module (OpenSSL), so the host needs no TLS interface.
It is the follow-up of [wasi2_unbundled](../wasi2_unbundled/) (whose `Host` it extends) and of the study in
[docs/wasi_p1_vs_p2_host_requirements.md](../../docs/wasi_p1_vs_p2_host_requirements.md). **An example, not a part of wasmext, and not run in the CI** (the module is 36 MB and the
build takes minutes); it has no tests.

Checked by hand (2026-10-22, Linux x86-64, wasi-sdk 34, CPython `1c6794e`, OpenSSL 3.5.0):

| What | Result |
| --- | --- |
| `python -c "print(1 + 1)"` | `2`, 26 imports of the host called |
| `import ssl, hashlib` | `OpenSSL 3.5.0`, `sha256` right |
| `socket.getaddrinfo('localhost', …)` | `('127.0.0.1', port)` through `ip-name-lookup` |
| `urllib.request.urlopen('https://localhost:…')` with a self-signed CA | the page, with the certificate checked, in the module |
| `pip install --index-url https://localhost:… --target /site/pkgs demo-pkg` | **installed** (index and wheel downloaded over HTTPS), `import demo_pkg` works; 48 imports called |
| `python -m ensurepip` | **fails**: it starts pip in a child process, and WASI has none; `guest/wasi_pip.py` runs the bundled pip in the same process instead |

PyPI itself was **not** tried (no outbound TCP in the session that made this): the test index is `tools/tls_server.py`. For PyPI the host would have to reach the network and the
program needs a CA bundle (pip's own `certifi` is inside the pip wheel and is found).

## Build and run

```sh
# 1. the program: CPython and OpenSSL for wasm32-wasip2 (see ../../docs/experiments/wasi_p1_p2_cpython/: opensslbuild.sh, then cpbuild.sh). For p2 the compiler has to be named: without
#    CC, CPP and CXX the build makes a core module for WASI 0.1 under the name of a component, and build_wasm.py below fails (no unbundled-module0.wasm). The extra arguments go after `--`:
#      cpbuild.sh host p2 -- "CC=$SDK/bin/clang --target=wasm32-wasip2" "CPP=$SDK/bin/clang --target=wasm32-wasip2 -E" \
#          "CXX=$SDK/bin/clang++ --target=wasm32-wasip2" --with-openssl=$OPENSSL
#    (remove cross-build/wasm32-wasip2 of the CPython checkout first if it was configured for another compiler)
# 2. the module out of the component, and the standard library
python build_wasm.py /path/to/cpython/cross-build/wasm32-wasip2/python.wasm       # src/wasi2python/_python.wasm, 36 MB, and _imports.py (its imports), not in git
python tools/make_stdlib.py /path/to/cpython /tmp/pyroot                           # /tmp/pyroot/lib/python3.15 (+ wasi_pip)
# 3. the extension (wasm2c + a C compiler: several minutes), then run
uv sync --reinstall
uv run python -m wasi2python --preopen /tmp/pyroot=/py -- -c "print(1 + 1)"
uv run python -m wasi2python --preopen /tmp/pyroot=/py --preopen /tmp/site=/site -- \
    -m wasi_pip install --index-url https://localhost:18443/simple --cert /py/tls/cert.pem --target /site/pkgs demo-pkg
```

`python tools/tls_server.py DIR 18443` serves `DIR` (a PEP 503 index: `DIR/simple/<name>/index.html` and the wheels) over HTTPS with a certificate it makes in `DIR`
(`cert.pem`); `DIR` is the directory preopened as `/py`, so the program sees the certificate as `/py/tls/cert.pem` if `DIR` is `/tmp/pyroot/tls`.

From Python: `wasi2python.run(arguments, preopens, environment=..., stdout=..., stderr=...)` returns the exit code.

## Guest or host? Checked on wasmtime

The component itself (`python.wasm`, before `unbundle`) was run on wasmtime 50 (`wasmtime-py`, WASI 0.2 of wasmtime) to see which problems belong to the guest. On wasmtime: `print(1 + 1)` and `import ssl`
work (`OpenSSL 3.5.0`), so the build needs no more patching for them. `os.write` writes **65536 of 300000 bytes** (the cut-short certificate bundle is the guest's, see below), and `--target` at a preopened
directory itself fails in pip (`os.makedirs('/site')` asks `os.path.exists('/')`, and `/` is not a preopen): use a subdirectory, as above. The network could **not** be compared: the Python binding of wasmtime
has no call to allow TCP, and `inherit_network` (called through the C binding) gave name lookup but `Permission denied` on `connect`.

## The host

`FsHost` (`fshost.py`) answers `wasi:cli` (arguments, environment, exit), `wasi:random`, `wasi:clocks` resolution and `wasi:filesystem` over Python's `os`
(descriptors are file descriptors; `open-at`, `read`/`write`, the streams of a file, directory listing, `stat`, `mkdir`, `rename`, `unlink`, `symlink`,
`readlink`, `metadata-hash`). `NetHost` (`nethost.py`) adds `wasi:sockets` name lookup (IPv4) and a TCP client with a blocking connect. The layouts of the canonical ABI are
written by hand in the docstrings; the arguments are the flattened numbers of the core module.

- **Not a sandbox.** A path with `..` or a symbolic link can leave a preopened directory.
- Not written (a call raises `NotImplementedError`): UDP, `listen`/`accept`, IPv6, standard input (reads end at once), `set-times` (answers ok and does nothing), `advise`, `sync`.
- No processes (`subprocess`, `ensurepip`, `pip` build backends), no threads.

## Workarounds the build and pip need

- OpenSSL is built `no-threads` (wasi-libc has no `pthread_exit`) and `no-quic`, and its `configuration.h` gets `#define OPENSSL_THREADS 1` by hand, because CPython refuses OpenSSL without the macro. WASI has no threads, so it only
  silences the check. See `docs/experiments/wasi_p1_p2_cpython/opensslbuild.sh`.
- `guest/wasi_pip.py` gives pip `os.getuid`, `os.umask` and an empty `mmap` module (none of them exist on WASI), and an `os.write` that loops: wasi-libc's `write(2)` writes only what the stream allows
  (**65536 bytes for 300000 on wasmtime** [run], 4096 on this host), and `importlib.resources` calls `os.write` once, so pip's certificate bundle (234 KB, taken out of the wheel) came out cut short and
  `load_verify_locations` failed with `PEM lib`. It is a property of the guest, the same on the reference host, not of this host.
