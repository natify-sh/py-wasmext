# wasmext-example-wabt

[WABT](https://github.com/WebAssembly/wabt) 1.0.42, the toolkit that `wasmext` itself uses to turn WebAssembly into C, built **by wasmext** into native
CPython extensions: `wat2wasm` (text to binary) and `wasm2c` (binary to C) as WASI programs (`src/wabtwasm/_wat2wasm.wasm` and `_wasm2c.wasm`, 1.3 MB
each), with no engine and no WABT binary at run time. A test that the C-to-extension pipeline can run on its own output.

```sh
# wasmext (and with it wabt-package) is a build requirement, and a C compiler is needed. wasmext is not on PyPI yet, so uv takes it
# from the root of the repository (`[tool.uv.sources]` in pyproject.toml). This is the way to build the example:
uv sync --reinstall                       # --reinstall: build the extensions again (uv keeps what it built before)
uv run pytest
uv run python -m wabtwasm wasm2c module.wasm -o module.c --module-name=module
```

```python
import wabtwasm

wasm = wabtwasm.wat2wasm('(module (func (export "f") (result i32) i32.const 42))')  # bytes
files = wabtwasm.wasm2c(wasm, name="m")  # {"m.c": ..., "m.h": ...}
```

A tool that fails raises `WabtError` (`.code`, `.stdout`, `.stderr`). The tools run in a directory of their own that is their whole world.

## wasmext, built with a wasmext extension

`python -m wabtwasm toolchain DIR` writes a directory of the kind that `WASMEXT_WABT` takes (`bin/wasm2c`, `wasm2c/` with the runtime of the C, the
version): `bin/wasm2c` is a shell script that runs the extension. With it wasmext translates with a `wasm2c` that wasmext built:

```sh
uv run python -m wabtwasm toolchain /tmp/wabt
WASMEXT_WABT=/tmp/wabt wasmext natify -i pkg/module.wasm      # the head of the C says: #define WASMEXT_GENERATED_WABT "1.0.42-wabtwasm"
```

What was checked (Linux x86-64): the C of `qjs.wasm` of [`examples/quickjs`](../quickjs) (17.3 MB, 1537 functions) from this `wasm2c` and from the one of the
wabt-package is the same bytes, the `.c` and the `.h`; this one takes 0.42 s for it and the native one 0.24 s. `coremark-minimal.wasm` was turned into an
extension by wasmext with this directory. The script is for POSIX (wasmext runs `bin/wasm2c` as a program; on Windows it has to be an `.exe`).

## The WebAssembly modules

`_wat2wasm.wasm` and `_wasm2c.wasm` are in the repository, with the files of the runtime (`runtime/`); `build_wasm.py` makes them again
(`uv run --group wasm python examples/wabt/build_wasm.py` from the root of the repository, with `zig c++` from the `ziglang` package as
`wasm32-wasi`). It clones the tag in the script and compiles the sources as they are, with what CMake does (`config.h` from `config.h.in`, C++20,
`-fno-exceptions`); the interpreter of WABT is left out. One thing is changed in a copy: `picosha2.h` has a function for `std::ifstream` that the libc++
of wasm32-wasi does not accept and that WABT never calls, so the copy that is compiled has no such function (the script fails if the header is not the one it
knows). WABT is under the Apache License 2.0, as the `wasm-rt` files in `runtime/` are: see [NOTICE.md](../../NOTICE.md).
