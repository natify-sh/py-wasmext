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

[`wasm2c`](https://github.com/WebAssembly/wabt) (from the [wabt-package](https://github.com/natify-sh/wabt-package),
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
  [wabt-package](https://github.com/natify-sh/wabt-package) that `wasmext` depends on (nothing to install by hand,
  and no WABT build);
- for a module with SIMD instructions, the headers of simde: the wabt-package carries them (1.0.42.0 or later) and wasmext adds them to the build by itself.

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

The values are Python's own: an `i32` or `i64` is an `int` (a result comes back signed, an argument is wrapped to the width, as the
JavaScript API does), an `f32` or `f64` a `float`, a `v128` 16 bytes (`bytes`, or any bytes-like object, in the order of WebAssembly
memory); an export with several results returns a tuple. A trap is `Trap` (a `RuntimeError`) and the instance stays usable; a missing
or wrong import is `LinkError`; an exported global is an attribute. The stub `<module>.pyi` written beside the `.wasm` says all that
for the module at hand.

The command line works in the manner of `cythonize`: `wasmext 'src/mypkg/*.wasm'` writes the C, `wasmext -i ...` also builds
the extensions in place, `-b` under `build/` (`wasmext --help`).

`wasmext inspect 'src/mypkg/*.wasm'` says what a module imports (what the host has to provide) and exports, which exports become
methods of `Instance` and which are left out, and why. It writes nothing and needs no `wasm2c`; the exit status is 1 for a module
that cannot be wrapped.

### Linking instances

An instance can take its imports from the exports of another one, with no Python in between: a function is then called
as a C function, a memory and a global are the very same ones. This works between modules of separate extensions.

```python
a = mypkg.lib.Instance()
b = mypkg.app.Instance({"env": a})  # the whole shelf: everything that `a` exports, under its names
b = mypkg.app.Instance({"env": {**a.__exports__, "log": print}})  # or by names, with what only Python can give
b = mypkg.app.Instance({"env": {"add": a.add, "counter": a["counter"], "memory": a.memory}})
```

The rule: **attributes use, items link**. `a.add(1, 2)`, `a.counter` (a number; `a.counter = 5` writes it) and `a.memory` (a
`memoryview`) are for you; `a['counter']` and `a.__exports__` (a dict of references) are what another instance imports (a bound
method `a.add` and the `memoryview` are accepted as references too). What does not fit (another kind, type, signature, size) is a
`LinkError`. A mutable global can only be shared as a reference; a number given for it is a `LinkError`. Tables cannot be linked yet.
[`examples/link`](examples/link) is a package of two modules that use each other; the design is in [FEATURES.md](FEATURES.md).

### WASI programs

A module that imports `wasi_snapshot_preview1` (or its first snapshot, `wasi_unstable`) gets those calls from wasmext, compiled into
the extension (C in `wasi_*.h` that the glue includes: the built module needs nothing of wasmext when it runs). `Instance()` needs no
imports, and the program is started as an export:

```python
import mypkg.lua  # lua.wasm, a command built for WASI

lua = mypkg.lua.Instance(wasi={"args": ["lua", "/hello.lua"], "preopens": {"/": "scripts"}, "readonly": True})
try:
    lua._start()
except mypkg.lua.WasiExit as exit:  # proc_exit(code): the instance stays usable
    print("exit code", exit.code)
```

`wasi=` is optional. A key you leave out has its default, which the extension works out itself when it is needed; `None` is *nothing*.
`args` (default: the name of the module; `None`: no arguments), `env` (default: empty, the environment of the host is not passed on),
`stdin`, `stdout`, `stderr` (default: `sys.stdin`, `sys.stdout`, `sys.stderr` as they are when the program reads or writes, so that `print`
and a capture in a test or a notebook keep their order; or bytes / an object with `read` / `write` / a function for output; `None`: an empty
input, an output thrown away), `preopens` (`{name the program sees: directory of the host}`; default: none, the program sees no files),
`readonly` (`True`, a name or a list of names of the preopens that cannot be changed), `clock` (a function: the id of the clock ->
nanoseconds; default: the clocks of the system) and `random` (a function: how many -> that many bytes; default: the random bytes of the
system). The types are in the `.pyi` that is written beside the module. A call can also be replaced as any import can:
`Instance({"wasi_snapshot_preview1": {"clock_time_get": my_clock}})`; what you give wins, call by call.

A program is kept inside the directories it was given: `..` out of a directory, an absolute name, or a symbolic link that leads out is
`ENOTCAPABLE`. A directory the program opens is a capability for that directory only. A program built with an old libc finds a relative path
only through a preopen named `"."`.

What is there, of the 46 calls of the specification (WASI 0.1):

- **41 work**: arguments, environment, clocks, random bytes, `proc_exit`, the standard streams, and files and directories: reading,
  writing, creating, truncating, removing, renaming, hard and symbolic links, `pread`/`pwrite`, sizes, times, `fd_readdir`,
  `poll_oneoff` (clocks, and descriptors of files, which are always ready).
- **`proc_raise` answers `ENOSYS`** and the four `sock_*` say `ENOTSOCK` (wasmext gives the program no socket; the specification lets a host do it), as the
  specification allows. WASI 0.2 and 0.3 (components) are not supported: build for `wasm32-wasip1`.
- A symbolic link is made only with a relative target, and one that leads out of the directory is not followed.
- **How files are reached.** On POSIX the calls go straight to the system (`openat`: no interpreter, no gap between a check and a use).
  On Windows they go through Python (`os`), which is slower for opening, `stat` and listing (reading and writing are still direct), and
  keeps a path inside its directory by checking it before using it. A native Windows path is not written.
- **Tested** against the programs of the official [wasi-testsuite](https://github.com/WebAssembly/wasi-testsuite) for WASI 0.1 (72 of
  them: C, Rust, AssemblyScript), all passing on Linux (both ways of reaching files), macOS and Windows in CI (`tests/wasi_testsuite/`);
  on Windows, `symlink_filestat` is expected to fail before Python 3.13, which cannot set the times of a link. A real program that
  uses all this is [`examples/lua`](examples/lua); `coreutils` (10.8 MB) was run by hand.

See [FEATURES.md](FEATURES.md#design-wasi) for the design.

### Large modules

The C that `wasm2c` writes is about 13 times the size of the module, and one file of millions of lines is a very long job for a
C compiler (the 10.8 MB `coreutils.wasm` was not done in half an hour). A module of 1 MiB or more is therefore written in several
files, which are compiled at the same time (128 KiB of the module for each file, at most 256). `wasmize(..., parts=N)`, `wasmext
--parts N`, `WASMEXT_PARTS` and `wasmimport.install(parts=N)` set the number of files (1 keeps the module whole: the code of a split
module is somewhat slower, as a call from one file to another is not inlined); `WASMEXT_JOBS` sets how many are compiled at once.

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

### Examples

Each is a package with a `setup.py` of a few lines, whose wheels `cibuildwheel` builds in CI on seven platforms (Linux x64 and ARM64,
Windows x64, x86 and ARM64, macOS Apple Silicon and Intel):

| | |
|---|---|
| [`examples/coremark`](examples/coremark) | the CoreMark benchmark as a module (imports the clock and print from Python) |
| [`examples/link`](examples/link) | two modules that use each other's memory, variable and function with no Python in between |
| [`examples/lua`](examples/lua) | Lua 5.4, a WASI program: `luawasm.run(["script.lua"], root="dir")`, files in the directory it is given and nowhere else |

What is supported, what is not yet, and the plan are in [FEATURES.md](FEATURES.md).

## Status

**Alpha.** The core works and is tested: in CI the test suite passes on Linux, macOS and Windows, the examples build into wheels on
seven platforms, and the WASI programs of the official test suite run on all three systems. But the interface can still change
(the format of the link between instances is `v1` and has not been in a release), and the rest of this section is what to expect.
The package is **not published on PyPI yet**; until it is, build the wheel from a checkout (`uv build`) and install it with
`pip install --find-links <the folder of the wheel> wasmext`, as the examples do in CI.

### Known limitations

- **WebAssembly:** tables are not exposed or linked (a module that imports or exports one is refused); no threads or shared memory;
  `funcref` and `externref` cannot be in a signature; relaxed SIMD is not supported (`wasm2c` aborts on it).
- **WASI** (0.1 only): 41 of 46 calls. `proc_raise` returns `ENOSYS`, and there are no sockets (`sock_*` return `ENOTSOCK`): the specification lets the host give the program a socket, but wasmext
  gives it only directories, so this is a gap of wasmext and not of WASI.
  `poll_oneoff` has no clocks of the process or the thread, and there are no signals. WASI 0.2 and 0.3 are not supported.
- **Files on Windows** go through Python (`os`), which is slower for opening, `stat` and listing than the direct calls on POSIX, and
  has a gap between a check and a use that `openat` does not have; a native path is not written, and the cost was not measured.
  Setting the times of a symbolic link needs Python 3.13.
- **Big-endian hosts** (s390x): a memory cannot be exported as a `memoryview`, and `v128` in a signature is refused.
- **Not tested in CI:** the Linux architectures other than x86-64 and ARM64 (armv7l, riscv64, ppc64le, i686 were run by hand under QEMU),
  Android, Pyodide, PyPy, iOS. Speed figures are from one machine.
- **Always:** the `.wasm` is fixed when the extension is built (no loading at run time), and building needs a C compiler.

The full list, with the reasons and the plan, is in [FEATURES.md](FEATURES.md).

## Development

```sh
git clone https://github.com/natify-sh/py-wasmext
cd py-wasmext
uv sync
uv run pytest        # builds real extensions: needs a C compiler
```

The official WASI tests run with `tests/wasi_testsuite/` (see the header of `adapter.py`; the runner of the suite needs Python 3.12,
`wasmext` itself 3.11): clone `WebAssembly/wasi-testsuite` (branch `prod/testsuite-base`), build the programs with
`prebuild.py <suite>/tests`, then `run-tests -r tests/wasi_testsuite/adapter.py`. `.github/workflows/wasi-testsuite.yml` does exactly that.

The repository is [natify-sh/py-wasmext](https://github.com/natify-sh/py-wasmext) (issues and pull requests there); its dependency, the
wasm2c and WABT tools as wheels, is [natify-sh/wabt-package](https://github.com/natify-sh/wabt-package).

`poc/` is the hand-written proof of concept this started from, with its measurements ([poc/README.md](poc/README.md)).

## License

MIT, see `LICENSE`. The C that wasmext writes contains the runtime of `wasm2c` (Apache-2.0, from WABT): see `NOTICE.md`.
