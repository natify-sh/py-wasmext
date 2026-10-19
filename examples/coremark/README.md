# wasmext-example-coremark

[CoreMark](https://github.com/eembc/coremark) of EEMBC as a WebAssembly module (`src/coremark/_core.wasm`, built by
`build_wasm.py` with `zig cc` from the reference sources and the small port in `port/`) turned into a native CPython extension by
[wasmext](../..): a package with no WebAssembly engine at run time.

```sh
# wasmext (and with it wabt-package) is a build requirement, and a C compiler is needed. wasmext is not on PyPI yet.
# From a checkout, uv takes wasmext from the root of the repository (`[tool.uv.sources]` in pyproject.toml):
uv build --wheel -o dist
uv venv && uv pip install dist/*.whl
.venv/bin/python -c "import coremark; print(coremark.run())"

# With pip, build the wheel of wasmext in the root of the repository (`uv build --wheel -o dist`) and give it as a source:
pip install --find-links ../../dist .
```

`setup.py` is the whole integration:

```python
from setuptools import setup
from wasmext import wasmize

setup(ext_modules=wasmize("src/coremark/*.wasm"))
```

`cibuildwheel` builds wheels of it as it does for any extension.

## The WebAssembly module

`_core.wasm` is in the repository; `build_wasm.py` makes it again (`uv run --group wasm python examples/coremark/build_wasm.py` from the root of the repository, with
`zig cc` from the `ziglang` package as `wasm32-freestanding`, no libc, no WASI). The module is the reference CoreMark
(the files of EEMBC, unchanged) with the `barebones` port: it imports `wiring.millis` (the clock) and `wiring.print`,
exports `setup` (one run of the benchmark), and prints the report of CoreMark: `Correct operation validated` when the
CRCs are right and the run lasted 10 s or more, then `CoreMark 1.0 : <iterations per second> / ...`. A run shorter than
10 s prints the same report with `ERROR! Must execute for at least 10 secs for a valid result!`, as CoreMark does.
