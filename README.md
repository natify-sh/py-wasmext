# wasmext

Turn WebAssembly modules into **native CPython extensions**, in the manner of Cython: the module runs without a
WebAssembly engine at run time (no `wasmtime`, no `node` to install next to it).

```
module.wasm --wasm2c--> C + glue --C compiler--> module.cpython-3xx-....so | .pyd
```

[`wasm2c`](https://github.com/WebAssembly/wabt) (from the [wabt-package](https://github.com/ballistics-lab/wabt-package),
a dependency) translates the module to C; wasmext generates the glue that makes it a Python module and builds it with
setuptools. It is the idea of [wasm2mpy](https://github.com/vshymanskyy/wasm2mpy) moved to CPython, and an alternative to
[py-wasmhost](https://github.com/ballistics-lab/py-wasmhost), a facade over engines that you bring with you.

## Use

`wasmize()` turns the `.wasm` files of a project into the `Extension`s of its `setup.py`:

```python
from setuptools import setup
from wasmext import wasmize

setup(ext_modules=wasmize("src/mypkg/*.wasm"))  # build-system.requires = ["setuptools", "wasmext"]
```

```python
import mypkg.fast  # src/mypkg/fast.wasm

inst = mypkg.fast.Instance()  # Instance({"env": {"log": print}}) if the module imports functions
inst.add(2, 3)  # the exports are methods; an exported memory is a memoryview attribute
```

The command line works in the manner of `cythonize`: `wasmext 'src/mypkg/*.wasm'` writes the C, `wasmext -i ...` also builds
the extensions in place, `-b` under `build/` (`wasmext --help`).

### Native or abi3 wheels

By default every interpreter gets its own extension (`cp311`, `cp312`, ...). For **one wheel for all CPython from 3.11 on**
(the stable ABI, abi3) say so in two places, which go together:

```python
setup(ext_modules=wasmize("src/mypkg/*.wasm", limited_api=True))  # or: wasmext --abi3, or WASMEXT_LIMITED_API=1
```
```toml
[tool.distutils.bdist_wheel]
py-limited-api = "cp311"   # tags the wheel cp311-abi3 (without it the extension is abi3 but the wheel says cp311-cp311)
```

`limited_api=None` (the default) takes `WASMEXT_LIMITED_API` from the environment, so `cibuildwheel` can choose without
editing `setup.py`; `True`/`False` in the code outrank it. The glue uses only the limited API, so either kind builds from
the same C. abi3 does not exist for PyPy or free-threaded CPython (`3.13t`): build native extensions there.

[`examples/coremark`](examples/coremark) is a package built that way (abi3): three lines of `setup.py`, and `cibuildwheel` builds its
wheels. The build needs a C compiler and `wasm2c` (the wabt-package, or `WASMEXT_WABT`: a directory with its `bin/` and
`wasm2c/`).

## Development

```sh
uv sync
uv run pytest        # builds real extensions: needs a C compiler
```

`poc/` is the hand-written proof of concept this started from, with its measurements ([poc/README.md](poc/README.md)).

## License

MIT, see `LICENSE`. The C that wasmext writes contains the runtime of `wasm2c` (Apache-2.0, from WABT): see `NOTICE.md`.
