# wasmext

Turn WebAssembly modules into **native CPython extensions**, in the manner of Cython: the module runs without a
WebAssembly engine at run time (no `wasmtime`, no `node` to install next to it).

This is **ahead-of-time (AOT) compilation**: the WebAssembly is translated to C and compiled to machine code when the
extension is built, not interpreted or compiled by a JIT while the program runs. So what you get is the speed of compiled
C with little overhead of its own: what remains is what WebAssembly itself requires (every memory access is checked, by
guard pages by default; traps) and the cost of crossing between Python and the module (converting arguments and results
on a call, and a call into Python for each import the module uses). The code of the module should not be called in a
loop from Python for tiny pieces of work; give it the work in larger pieces. On CoreMark the extension was on a par with the
same benchmark compiled as C directly (within the noise of the measurement, on one machine: see [FEATURES.md](FEATURES.md)).
The price of AOT is that the `.wasm` is fixed when the extension is built: a module cannot be loaded at run time (that is what
an engine, or `wasmimport` as a development tool, is for), and building needs a C compiler.

```
module.wasm --wasm2c--> C + glue --C compiler--> module.cpython-3xx-....so | .pyd
```

[`wasm2c`](https://github.com/WebAssembly/wabt) (from the [wabt-package](https://github.com/ballistics-lab/wabt-package),
a dependency) translates the module to C; wasmext generates the glue that makes it a Python module and builds it with
setuptools. It is the idea of [wasm2mpy](https://github.com/vshymanskyy/wasm2mpy) moved to CPython, and an alternative to
[py-wasmhost](https://github.com/ballistics-lab/py-wasmhost), a facade over engines that you bring with you.

## Requirements

To **use** a built wheel you need only Python (3.11 or later): no compiler, no WebAssembly engine.

To **build** an extension (`pip install` from an sdist, `wasmext`, `wasmimport`, `cibuildwheel`) you need:

- **a C compiler** for your platform: gcc or clang (Linux, macOS: the Xcode command line tools), or MSVC (Windows; the
  Build Tools for Visual Studio). The C of `wasm2c` and the glue are plain C (C99 and GNU extensions on gcc/clang);
- **the Python development headers** (`Python.h`): `python3-dev` / `python3-devel` on Linux distributions; the python.org
  installers, `uv` and `cibuildwheel` have them; on Linux and macOS an extension is not linked against `libpython`, so the headers are all it needs (on Windows the `libs` directory of the installation too);
- **setuptools** (the extensions are built with it), and **wasm2c** with its runtime, which come from the
  [wabt-package](https://github.com/ballistics-lab/wabt-package) that `wasmext` depends on (nothing to install by hand,
  and no WABT build);
- for a module with SIMD instructions, the headers of simde: the wabt-package is to carry them (see [FEATURES.md](FEATURES.md)).

Building a native extension has been tested on Linux (x86-64 glibc and musl, ARM64), Windows (x64, ARM64), macOS (Apple
Silicon, Intel), Pyodide, and, built but not run, Android arm64-v8a; the details and what is not confirmed are in
[FEATURES.md](FEATURES.md#platforms-where-a-native-extension-was-built-and-tested).

`wasm2c` is needed only to make the C. A tree that ships the C (`<name>_wasmext/`, for example in an sdist) builds with the
compiler and the headers alone.

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

`wasmext inspect 'src/mypkg/*.wasm'` says what a module imports (what the host has to provide) and exports, which exports become
methods of `Instance` and which are left out, and why. It writes nothing and needs no `wasm2c`; the exit status is 1 for a module
that cannot be wrapped.

### Native or abi3 wheels

The interpreter that builds decides, as it does in Cython: where it has a stable ABI (CPython 3.11 and later) the extension is
**abi3** and the wheel is tagged `cp311-abi3`, one wheel for every CPython from 3.11 on; where it has not (PyPy,
free-threaded `3.14t`, Emscripten/Pyodide, Android, iOS) the extension is native. So the `cibuildwheel` selector decides what
you get:

```toml
[tool.cibuildwheel]
build = "cp311-* cp314t-*"   # cp311: the abi3 wheel; cp314t: a native free-threaded one
```

`limited_api=True`/`False` in `wasmize()` (or `--abi3` / `--no-abi3`) forces one or the other (`True` still builds native where
abi3 is impossible, and says so); `WASMEXT_LIMITED_API=0` turns abi3 off for a `None`. The wheel is tagged by a setuptools hook of
wasmext, so nothing else needs to be set (a `[tool.distutils.bdist_wheel] py-limited-api` of the project wins). The glue uses only
the limited API, so either kind builds from the same C.

The C that wasmext writes (`<name>_wasmext/`) and the `.wasm` are the sources of the extension, not part of it. setuptools puts
the sources of an extension into the manifest, and `include-package-data` (on by default in a `pyproject.toml`) then ships them in
the wheel: set `include-package-data = false` under `[tool.setuptools]` and name what you do ship in `package-data` (the stub,
`py.typed`), as `examples/coremark` does. The sdist keeps them, so that it builds without `wasm2c`.

[`examples/coremark`](examples/coremark) is a package built that way: three lines of `setup.py`, and `cibuildwheel` builds its
wheels. The build needs a C compiler and `wasm2c` (the wabt-package, or `WASMEXT_WABT`: a directory with its `bin/` and
`wasm2c/`).

To try a module without building a wheel, `wasmimport` works as `pyximport` does (a development tool: it runs a C compiler on import):

```python
import wasmimport

wasmimport.install()
import fast  # fast.wasm on sys.path, or in the working directory
```

What is supported, what is not yet, and the plan are in [FEATURES.md](FEATURES.md).

## Development

```sh
uv sync
uv run pytest        # builds real extensions: needs a C compiler
```

`poc/` is the hand-written proof of concept this started from, with its measurements ([poc/README.md](poc/README.md)).

## License

MIT, see `LICENSE`. The C that wasmext writes contains the runtime of `wasm2c` (Apache-2.0, from WABT): see `NOTICE.md`.
