# wasmext-example-wasi2-unbundled

Two C programs built as **WASI 0.2 components**, run as native CPython extensions. `wasm2c` does not read a component, so the **core module** is taken out
of each component (`wasm-tools component unbundle`), wasmext turns that module into an extension, and the WASI 0.2 calls it makes are answered by a **host
written in Python** (`wasi2demo.host.Host`). Nothing in wasmext knows WASI 0.2: the host is a dictionary of Python callables given to `Instance(...)`.

| Program | What it does | Core module | Imports |
| --- | --- | --- | --- |
| `c/hello.c` → `_hello` | `printf("hello from wasip2\n"); return 3;` | 219 KB | 21 |
| `c/sock.c` → `_sock` | connects to a TCP server, sends `ping`, prints the reply (`pong`) | 401 KB | 74 |

```sh
# a C compiler is needed; wasmext is not on PyPI yet, so uv takes it from the root of the repository
# (`[tool.uv.sources]` in pyproject.toml)
uv sync --reinstall      # --reinstall: build the extensions again (uv keeps what it built before)
uv run pytest
```

```python
from io import BytesIO
from wasi2demo import Host, _hello, run

out = BytesIO()
run(_hello, Host(stdout=out))  # 1: main returned 3, which is the err of the result of wasi:cli/run#run
out.getvalue()  # b'hello from wasip2\n'
```

`run(module, host)` makes `module.Instance(host.imports())`, gives the instance to the host (`host.bind`, the imports need its memory and `cabi_realloc`) and
calls the export `wasi:cli/run@0.2.12#run`. The number is `0` for `ok` and `1` for `err`: the value `main` returned does not come out of it.

## The host

The imports of a core module taken out of a component are plain functions; the arguments of the canonical ABI are flattened to numbers, a `result` comes back
through a pointer that is the last argument, a resource (a stream, a socket, a pollable) is a number. `Host` keeps a table of handles for them.

Written and run: `wasi:cli` stdout and stderr (not stdin), `wasi:clocks`, `wasi:io/poll` and the streams, and a **TCP client** (`create-tcp-socket`,
`start-connect`, `finish-connect`, `read`, `write`). `Host(remap=...)` sends a connection to the address the program asks for to another one: `sock.c`
connects to 127.0.0.1:47123, and the test serves it on a free port. Every other import is there too (the module needs all of them to be given) and raises
`NotImplementedError` when it is called: `bind`/`listen`/`accept`, UDP, name lookup, IPv6, stdin. The errors of the network are not turned into the
`error-code` of WASI: an `OSError` comes out of the call.

What was seen and what was not is in [WASI_COMPONENTS.md](../../docs/WASI_COMPONENTS.md), "A WASI 0.2 command on a Python host". This host runs in the extension
only: a shared library or a program made by wasmext has no Python host for these imports.

## Making the `.wasm` files again

They are in the repository, so a build needs only a C compiler. To make them again from `c/`:

```sh
uv tool install wasm-tools-package        # wasm-tools 1.262
WASI_SDK_PATH=/opt/wasi-sdk-34.0 python build_wasm.py
```

`build_wasm.py` builds each program with `clang --target=wasm32-wasip2`, takes the core module out of the component with `wasm-tools component unbundle`
(module 0 is the program; the other core modules of a component are glue for the component model) and writes `src/wasi2demo/_imports.py`, the list of the
imports that the host has to give.

This example is not built by the CI.
