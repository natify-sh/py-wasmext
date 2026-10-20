# wasmext-example-products

One wheel with the two products of wasmext that are not Python extensions:

- `engine.wasm` as a **shared library** (`product = "shared"`), used through `productsdemo.engine_ctypes`, the module that wasmext writes beside it
  (`Instance`, `Trap`, ... as in an extension, on `ctypes`; nothing of wasmext is needed to run it);
- `hello.wasm`, a WASI program, as a **native executable** (`product = "exe"`), run with no Python.

```python
from productsdemo import HELLO, engine_ctypes

engine_ctypes.Instance({"env": {"log": print}}).add(2, 3)  # 5
subprocess.run([HELLO])  # prints "hello, wasi", exits with 3
```

The wheel does not depend on the version of Python (`py3-none-<platform>`), so cibuildwheel builds one per platform
(`build = "cp311-*"`); its repair step (`auditwheel`, `delocate`, `delvewheel`) sees a library and a program like any others.

```sh
uv sync --reinstall      # --reinstall: build the products again (uv keeps what it built before)
uv run pytest
```

The modules are written in the text format (`wat/`); `build_wasm.py` makes the `.wasm` files with `wat2wasm` of the wabt-package. The `.wasm` are in the repository.
