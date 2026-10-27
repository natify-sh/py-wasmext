# wasmext-example-link

Two WebAssembly modules built into two native CPython extensions that **use each other**: `_counter` has a memory, a variable
(a mutable global) and a function, and `_app` imports all three from it. Nothing of that goes through Python: `_app`
calls `bump` of `_counter` as a C function, and reads and writes the same bytes and the same variable.

```sh
# a C compiler is needed; wasmext is not on PyPI yet, so uv takes it from the root of the repository
# (`[tool.uv.sources]` in pyproject.toml). This is the way to build the example:
uv sync --reinstall      # --reinstall: build the extensions again (uv keeps what it built before)
uv run python -m linkdemo
```

The tests: `uv run pytest` (the `dev` group of the example has pytest, and `uv sync` installs it).

With pip, build the wheel of wasmext in the root of the repository (`uv build --wheel -o dist`) and give it as a source:
`pip install --find-links ../../dist .`.

```python
counter = _counter.Instance(_counter.Store())
app = _app.Instance(
    _app.Store(), imports={"env": {**counter.__exports__, "log": print}}
)  # everything counter exports, and log from Python
app.tick()  # app calls counter.bump(1) directly, and tells `log` the result
counter.count  # 1: the variable of counter, written by that call
```

The two modules are written in the text format (`wat/`); `build_wasm.py` makes the `.wasm` files with `wat2wasm` of the
wabt-package (`uv run python examples/link/build_wasm.py` from the root of the repository). The `.wasm` are in the repository.

The rule of the Python side: **attributes use, items link**. `counter.bump(1)`, `counter.count` and `counter.memory` use what
counter exports; `counter['bump']` and `counter.__exports__` hand over a reference that another instance can import. An import that
is the wrong kind, or has another type or signature, is a `LinkError` when the instance is made. See "Linking instances"
in the [README](../../README.md) and the design in [DESIGN.md](../../docs/DESIGN.md).
