# wasmext

Turn WebAssembly modules into **native CPython extensions**, in the manner of Cython: the module runs without a
WebAssembly engine at run time (no `wasmtime`, no `node` to install next to it).

[![license]][license-url]
[![pypi version]][PyPiUrl]
[![python versions]][PyPiUrl]
[![Pre-commit]][pre-commit-workflow]
[![coverage]][CodecovUrl]

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

To **use** a built wheel you need only Python (3.11 or later; the test suite runs on 3.11, on 3.15 and on the free-threaded 3.15t): no compiler, no WebAssembly engine.

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
Silicon, Intel), Pyodide, Android x86-64 (in an emulator), and, built but not run, Android arm64-v8a; the details and what is not confirmed are in
[FEATURES.md](FEATURES.md#platforms-where-a-native-extension-was-built-and-tested).

`wasm2c` is needed to make the C, and so for every build: the C is a step of the build (it is in `build/wasmext/`, not in the
sources and not in an sdist), and `wabt-package` is a build requirement. Where everything is made and put: [build_model.md](build_model.md).

## Use

`natify()` turns the `.wasm` files of a project into the `Extension`s of its `setup.py`:

```python
from setuptools import setup
from wasmext import natify

setup(ext_modules=natify("src/mypkg/*.wasm"))  # build-system.requires = ["setuptools", "wasmext"]
```

Or with no `setup.py` at all, in `pyproject.toml` (a hook of wasmext, an entry point of setuptools, reads the table). The keys are the
arguments of `natify()` with dashes: `module-list` (a glob pattern, or a list of them), `exclude`, `build-dir`, `force`, `quiet`, `stubs`,
`guard-pages`, `parts`, `product`; and, added to each extension the table makes, those of `Extension`: `extra-compile-args`,
`extra-link-args`, `define-macros` (`"NAME"`, `"NAME=value"` or `["NAME", "value"]`), `undef-macros`, `include-dirs`, `libraries`,
`library-dirs`. One setting is for the whole project, not an entry, because a wheel has one tag: `limited-api` goes in `[tool.wasmext]` (above the entries), and all the modules
are built the same way; a module of wasmext that took the default follows a hand-written extension that is not abi3, and settings that contradict each other are an error. (In a `setup.py` the same settings are those of an `Extension` given to `natify()`, as to `cythonize()`.)

```toml
[build-system]
requires = ["setuptools>=77", "wasmext"]
build-backend = "setuptools.build_meta"

[[tool.wasmext.ext-modules]]       # one table, or several for modules that need different settings
module-list = "src/mypkg/*.wasm"
parts = 4
```

A project that calls `natify()` in its `setup.py` and has this table is refused with a message (use one of them); a `setup.py` with an extension of
another kind (a hand-written C one) goes with the table. [`examples/quickjs`](examples/quickjs) is built this way.

```python
import mypkg.fast  # src/mypkg/fast.wasm

inst = mypkg.fast.Instance()  # Instance({"env": {"log": print}}) if the module imports functions
inst.add(2, 3)  # the exports are methods; an exported memory is a memoryview attribute
```

The values are Python's own: an `i32` or `i64` is an `int` (a result comes back signed, an argument is wrapped to the width, as the
JavaScript API does), an `f32` or `f64` a `float`, a `v128` 16 bytes (`bytes`, or any bytes-like object, in the order of WebAssembly
memory); an export with several results returns a tuple. A trap is `Trap` (a `RuntimeError`; an exception of WebAssembly that nothing catches is `UncaughtException`, a `Trap` with `.tag`, the index of the tag in the module, and `.values`) and the instance stays usable (a WASI command, which exports `_start`, is over after one); a missing
or wrong import is `LinkError`; an exported global is an attribute. The stub `<module>.pyi`, which the build puts beside the extension, says all that
for the module at hand.

The command line has a command for each thing it does (`wasmext --help`). `wasmext natify 'src/mypkg/*.wasm'` writes the C, in the manner of
`cythonize`; `wasmext natify -i ...` also builds the extensions in place, `-b` in `build/`. The settings of `natify()` are options: `-q`, `-f`, `-X`, `--build-dir`,
`--parts`, `--limited-api` / `--no-limited-api`, `--guard-pages` / `--no-guard-pages` / `--guard-pages-for ARCH=on|off,...`, `--no-stubs`, and the product (`--shared` or `--exe`, below).

`wasmext inspect 'src/mypkg/*.wasm'` says what a module imports (what the host has to provide) and exports, which exports become
methods of `Instance` and which are left out, and why. It writes nothing and needs no `wasm2c`; the exit status is 1 for a module
that cannot be wrapped.

### Shared libraries and programs

A module can be made into something other than a Python extension, for a package that ships a shared library (for C, or for Python over
`ctypes`) or a program. The product is a setting of both doors, one for each entry:

```toml
[[tool.wasmext.ext-modules]]
module-list = "src/pkg/engine.wasm"
product = "shared"      # "extension" (the default), "shared" or "exe"

[[tool.wasmext.ext-modules]]
module-list = "src/pkg/tool.wasm"
product = "exe"
```

`natify(..., product="shared")` is the same. Whatever product is asked for, `natify()` makes the C of **every** product that the module can have (an extension, a library, and a program if the module is a WASI command), and the build only chooses the sources to compile, so the
C made for one product never has to be made again for another (it is all in `build/wasmext/`). `wasmext natify FILE`, with `--shared` or `--exe` too, writes only that C, as `cythonize` does without `-b`; with `-i` (or `-b`) the extension, the library or the program is built too
(the options `--shared` and `--exe` exclude each other: a library holds no `main`; a program of a module that is not a command is refused). `setup.py build_ext` puts the file where an extension would go: `lib<name>.so` / `lib<name>.dylib` / `<name>.dll`
(with `<name>_ctypes.py` and its `.pyi` beside it, and its header `<name>_api.h` in `build/wasmext/`: the interface of the extension over `ctypes`), or the program `<name>` /
`<name>.exe`. A program needs a `_start` and no imports but WASI's (`--env NAME=VALUE`, `--dir HOST::GUEST[:ro]`, `--argv0`, `--help`); a
library exports only its API. The settings of the extension (`libraries`, `extra-compile-args`, ...) are the flags of the build. A reactor
(`_initialize`, no `_start`) is a library, and is initialized when the instance is made, in the extension and in the library alike (WASI says the host runs `_initialize` once, before any other export; a later explicit call of it does nothing). A package whose compiled files are all libraries and programs gets a wheel tagged
`py3-none-<platform>` (any Python 3), not for the interpreter that built it. The header `<name>_api.h` is in `build/wasmext/<module name>/`: nothing in a Python package needs it (the wrapper knows the signatures), it is for a host in C or another language that is built against the library, so a wheel does not have it; a project that wants it there copies it from the build directory (a `build_ext` subclass in `setup.py`, shown in [build_model.md](build_model.md)). wasmext builds the files and the project distributes them: it writes no helper that finds a program or a library at run time
(a library has its wrapper, which looks beside itself; for a program, a package does what suits it: `Path(__file__).with_name(...)` as `examples/products` does, `importlib.resources`, a `main()` of its own run by a `[project.scripts]` entry, or none of it; a project may have several programs
and may not want a launcher at all). `limited-api` and the stubs are for extensions only.

### What a source distribution carries

The `.wasm` and the project files, nothing that wasmext made: the C is a step of the build, in `build/wasmext/` (distutils leaves `build/` out of an sdist), and a build from the sdist makes it again with the wasm2c of `wabt-package`, a build requirement. A package that ships generated C and no wasmext, to be built by a C compiler alone, is not supported. The C is made again only when its SHA-256 digest says it is stale (another `.wasm`, wasmext or WABT, or `force`), never by the time of a file.

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
`LinkError`. A mutable global can only be shared as a reference; a number given for it is a `LinkError`. Tables cannot be linked yet (a module that imports one is refused; an exported one is left out).
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
except mypkg.lua.WasiExit as exit:  # proc_exit(code): the program is over, and what it opened is closed
    print("exit code", exit.code)
```

`wasi=` is optional. A key you leave out has its default, which the extension works out itself when it is needed; `None` is *nothing*.
`args` (default: the name of the module; `None`: no arguments), `env` (default: empty, the environment of the host is not passed on),
`stdin`, `stdout`, `stderr` (default: `sys.stdin`, `sys.stdout`, `sys.stderr` as they are when the program reads or writes, so that `print`
and a capture in a test or a notebook keep their order; or bytes / an object with `read` / `write` / a function for output; `None`: an empty
input, an output thrown away), `preopens` (`{name the program sees: directory of the host}`; default: none, the program sees no files),
`readonly` (`True`, a name or a list of names of the preopens that cannot be changed), `clock` (a function: the id of the clock ->
nanoseconds; default: the clocks of the system) and `random` (a function: how many -> that many bytes; default: the random bytes of the
system). The types are in the `.pyi` that the build puts beside the module. A call can also be replaced as any import can:
`Instance({"wasi_snapshot_preview1": {"clock_time_get": my_clock}})`; what you give wins, call by call.

A program is kept inside the directories it was given: `..` out of a directory, an absolute name, or a symbolic link that leads out is
`ENOTCAPABLE`. A directory the program opens is a capability for that directory only. A program built with an old libc finds a relative path
only through a preopen named `"."`.

What is there, of the 46 calls of the specification (WASI 0.1):

- **42 work**: arguments, environment, clocks, random bytes, `proc_exit`, `proc_raise`, the standard streams, and files and directories: reading,
  writing, creating, truncating, removing, renaming, hard and symbolic links, `pread`/`pwrite`, sizes, times, `fd_readdir`,
  `poll_oneoff` (clocks, and descriptors of files, which are always ready).
- **The four `sock_*` say `ENOTSOCK`** (wasmext gives the program no socket; the specification lets a host do it), as the
  specification allows. WASI 0.2 and 0.3 (components) are not supported: build for `wasm32-wasip1`.
- A symbolic link is made only with a relative target, and one that leads out of the directory is not followed.
- **How files are reached.** The calls go straight to the system, with no interpreter in between: `openat` on POSIX, the Win32 API
  (wide-character functions) on Windows. `-DWASMEXT_WASI_PYTHON_FS=1` makes them go through Python (`os`) instead, as a way to test.
- **Tested** against the programs of the official [wasi-testsuite](https://github.com/WebAssembly/wasi-testsuite) for WASI 0.1 (72 of
  them: C, Rust, AssemblyScript), all passing on Linux (both ways of reaching files), macOS and Windows in CI (`tests/wasi_testsuite/`);
  with the files through Python on Windows, `symlink_filestat` is expected to fail before Python 3.13, which cannot set the times of a link. A real program that
  uses all this is [`examples/lua`](examples/lua); `coreutils` (10.8 MB) was run by hand.

See [FEATURES.md](FEATURES.md#design-wasi) for the design.

### Guard pages

By default each memory reserves 8 GiB of *address space* (not RAM) and the MMU catches out-of-bounds accesses, with no checks in the code. That needs a
64-bit address space with room for it: a process with a limit (`ulimit -v`, some containers) or a 32-bit target cannot do it, and there the runtime allocates the memory at
its size and checks every access in code (about 30% slower on CoreMark). It is decided **when the C is compiled**, for the architecture the extension is built for, so it can be set
for some architectures and not others, in all the places that build:

```toml
[[tool.wasmext.ext-modules]]
module-list = "src/pkg/*.wasm"
guard-pages = { x86 = false, armv7l = false, default = true }   # or just true / false
```

`natify(..., guard_pages={"x86": False, "default": True})`, `wasmext natify --guard-pages-for x86=off,armv7l=off --guard-pages` (or `--no-guard-pages`), and
`WASMEXT_GUARD_PAGES=x86=off,default=on` (or `0`/`1`) say the same; the names of the architectures are `x86_64`, `x86`, `arm64`, `armv7l`, `ppc64le`, ... as the platform of the
interpreter that builds names them, which in a cross build (cibuildwheel for Windows x86 or ARM64) is the target. A memory that cannot be reserved is a `MemoryError`; wasmext does not
switch the mode when it runs (that would need both versions of the code in the module).

### Large modules

The C that `wasm2c` writes is about 13 times the size of the module, and one file of millions of lines is a very long job for a
C compiler (the 10.8 MB `coreutils.wasm` was not done in half an hour). A module of 1 MiB or more is therefore written in several
files, which are compiled at the same time (128 KiB of the module for each file, at most 256). `natify(..., parts=N)`, `wasmext
--parts N`, `WASMEXT_PARTS` and `wasmimport.install(parts=N)` set the number of files (1 keeps the module whole: the code of a split
module is somewhat slower, as a call from one file to another is not inlined); `WASMEXT_JOBS` sets how many are compiled at once.

### Native or abi3 wheels

The interpreter that builds decides. Cython and setuptools-rust leave abi3 to the project (the `Extension`, the macro and the tag of the wheel are
written in its `setup.py`); here `natify()` does all three. Where the interpreter loads abi3 files (it says so in its extension suffixes, as setuptools reads them:
CPython 3.11 and later; the file may be named `.abi3.so` or, as the newest interpreters do, `.abi3-<platform>.so`) the extension is **abi3** and the wheel is tagged `cp311-abi3`, one wheel for every CPython from 3.11 on; where it does not (PyPy, free-threaded
`3.14t` and `3.15t`), or the platform pins one exact CPython (Emscripten/Pyodide, Android, iOS), the extension is native, with the usual name and tag (`cp315-cp315t` for 3.15t). 3.15 also has **abi3t**, a stable ABI for the free-threaded build (PEP 803,
files `.abi3t.so`): wasmext does not build it (cibuildwheel does not tag it yet, and the glue would have to stop embedding `PyObject_HEAD`), and a free-threaded build gets a native extension. So the `cibuildwheel` selector decides what
you get:

```toml
[tool.cibuildwheel]
build = "cp311-* cp314t-* cp315t-*"   # cp311: the abi3 wheel; cp314t, cp315t: native free-threaded ones
```

`limited_api=True`/`False` in `natify()` (or `--limited-api` / `--no-limited-api`) forces one or the other (`True` still builds native where
abi3 is impossible, and says so); `WASMEXT_LIMITED_API=0` turns abi3 off for a `None`. A wheel has one tag, so this is **one setting for the whole project**: in
`pyproject.toml` it is `limited-api` under `[tool.wasmext]`, not in an entry; all the modules of wasmext in a wheel are built the same way, one that took the default follows
a hand-written extension that is not abi3, and settings that contradict each other (`True` for one call of `natify()`, `False` for another) are an error. The wheel is tagged by a
setuptools hook of wasmext, so nothing else needs to be set (a `[tool.distutils.bdist_wheel] py-limited-api` of the project wins). The glue uses only the limited API, so either
kind builds from the same C. abi3 costs little here: on one machine (CPython 3.11, gcc `-O2`) calls into the module and the code inside it ran at the same speed as native, and a call from
the module into a Python function about 5% slower.

The `.wasm` is the source of the extension, not part of it. `include-package-data` (on by default in a `pyproject.toml`) would ship
it in the wheel: set `include-package-data = false` under `[tool.setuptools]` and name what you do ship in `package-data`
(`py.typed`), as `examples/coremark` does. The stub `<name>.pyi` is made by the build and put beside the extension, in the wheel too.

[`examples/coremark`](examples/coremark) is a package built that way: three lines of `setup.py`, and `cibuildwheel` builds its
wheels. The build needs a C compiler and `wasm2c` (the wabt-package, or `WASMEXT_WABT`: a directory with its `bin/` and
`wasm2c/`). To use a `wasm2c` you have (a system one, or one built from source), name its parts: `WASMEXT_WASM2C` is the executable,
`WASMEXT_WASM2C_RUNTIME` the directory with `wasm-rt.h` and the rest of the runtime of the same version, and `WASMEXT_WASM2C_INCLUDE` the
one with `simde/` (only for modules with SIMD). Each part is taken from its variable, else from `WASMEXT_WABT`, else from the
wabt-package, which is not needed when the executable and the runtime are given. The runtime has to be that of WABT 1.0.42 or later and in one directory: the `wabt` of Debian/Ubuntu (1.0.34, the runtime in two places) does not do.

To try a module without building a wheel, `wasmimport` works as `pyximport` does (a development tool: it runs a C compiler on import). The
extension is kept in a cache, `~/.wasmbld` (or `WASMIMPORT_BUILD_DIR`, or `install(build_dir=...)`; `install(inplace=True)` puts it beside
the `.wasm`), one folder for each file and each Python, and is made again when the `.wasm`, wasmext, or how it is built (`guard_pages`,
`limited_api`, `parts`, the flags of the compiler) changes:

```python
import wasmimport

wasmimport.install()
import fast  # fast.wasm on sys.path, or in the working directory
```

### Examples

Each is a package whose integration is a few lines (`setup.py`, or for `quickjs` the table of `pyproject.toml` above), and whose wheels
`cibuildwheel` builds in CI on seven platforms (Linux x64 and ARM64, Windows x64, x86 and ARM64, macOS Apple Silicon and Intel). `coremark`
is built in CI on more: Linux armv7l, i686, ppc64le and riscv64, Pyodide and Android. Build and test an example with `uv sync --reinstall`
and `uv run pytest` in its folder.

| | |
|---|---|
| [`examples/coremark`](examples/coremark) | the CoreMark benchmark as a module (imports the clock and print from Python) |
| [`examples/link`](examples/link) | two modules that use each other's memory, variable and function with no Python in between |
| [`examples/lua`](examples/lua) | Lua 5.4, a WASI program: `luawasm.run(["script.lua"], root="dir")`, files in the directory it is given and nowhere else |
| [`examples/wabt`](examples/wabt) | WABT itself: `wat2wasm` and `wasm2c` as WASI programs in extensions (`wabtwasm.wat2wasm(...)`), and a directory for `WASMEXT_WABT` made of them, so that wasmext translates with a `wasm2c` that wasmext built; the C they write is the same bytes as the native tools' |
| [`examples/quickjs`](examples/quickjs) | QuickJS-ng, a JavaScript engine as a WASI program: `qjswasm.run(["script.js"], root="dir")`, an error of the script is code 1 and a message, as on the command line |
| [`examples/products`](examples/products) | one wheel with a shared library (used through `ctypes`) and a WASI program as a native executable, both made by wasmext; `py3-none-<platform>` |

What is supported, what is not yet, and the plan are in [FEATURES.md](FEATURES.md).

## Status

**Alpha.** The core works and is tested: in CI the test suite passes on Linux, macOS and Windows, the examples build into wheels on
seven platforms, and the WASI programs of the official test suite run on all three systems. But the interface can still change
(the format of the link between instances is `v1` and has not been in a release), and the rest of this section is what to expect.
The package is **not published on PyPI yet**; until it is, build the wheel from a checkout (`uv build`) and install it with
`pip install --find-links <the folder of the wheel> wasmext`, as the examples do in CI.

### Public interface

What may be relied on, and what may change. This is the boundary for the alpha; a change to the first tier is written in the release notes, a change to the others may come without one.

**Stable** (the interface that users of a built wheel, and of the build, see):

- The module that wasmext makes: `Instance(imports, wasi=...)`; an export as an attribute or a method; `instance["name"]` and `instance.__exports__` (a reference to give to another instance as an import; its content is opaque);
  an exported memory as a `memoryview`; an exported global as an attribute; a `v128` as 16 bytes; the exceptions `Trap` and `LinkError`, `UncaughtException` (for a module that has exception tags) and, for a module that uses WASI, `WasiExit`, `WasiSignal`, `WasiTerminated`; the `.pyi` beside the built module.
- The build: `natify()` and its keyword arguments, the options of `wasmext natify` (and `wasmext inspect`, whose text is for people, not for programs), the keys of `[[tool.wasmext.ext-modules]]` and `limited-api` of `[tool.wasmext]` in `pyproject.toml`, and the values of `product`.
- The environment variables of a user: `WASMEXT_WABT`, `WASMEXT_WASM2C`, `WASMEXT_WASM2C_RUNTIME`, `WASMEXT_WASM2C_INCLUDE`, `WASMEXT_LIMITED_API`, `WASMEXT_GUARD_PAGES`, `WASMEXT_PARTS`, `WASMEXT_JOBS`, `WASMEXT_NO_PYPROJECT`.
- The products: the header `<name>_api.h` of a shared library (its functions, `<name>_config`, the trap codes) and the wrapper `<name>_ctypes.py`, which has the interface of the extension; the command line of a program made with `--exe` (`--env`, `--dir`, `--argv0`, `--help`, `--version`) and its exit codes.
- `wasmext.__version__`, `GenError` and `WasmError`.

**Provisional** (works, used by the tests, but its shape is not settled): `generate()`, `parse()`, `mangle()`, `Glue` and the types of a parsed module (`Module`, `Import`, `Export`, `FuncType`, `GlobalType`, `TableType`, `Limits`, `ValType`);
`find_toolchain()` and `Toolchain`; `wasmimport` (`install`, `uninstall`, `clean`, `WasmFinder`, `WasmImportLoader`), a development tool.

**Private** (no promise at all): every module whose name begins with an underscore (`wasmext._*`), the setuptools hook that `pyproject.toml` entry points register, the headers in `wasmext/c/`, the C that wasmext writes (`*_glue.h`, `*_w2c.*`, `*_py.c`, the `build/wasmext/` folder: it is what is built, not an interface), the `WASMEXT_*` macros of those headers,
the cache of `wasmimport`, and the **link between instances**: the capsule `wasmext.export.v1` and the record behind it (`wasmext_export`, `<name>_export` in a header). A reference is only passed from `_export_find` to a `_link_*` function or to another instance; do not read its fields.
A module links to a module made by another version of wasmext only if both have the same record version and the same layout of the wasm2c runtime; otherwise the link is a `LinkError`, and nothing more is promised between versions of the alpha.

### Known limitations

- **WebAssembly:** tables are not exposed or linked (an exported table is left out and reported; a module that imports one is refused); no threads or shared memory;
  `funcref` and `externref` cannot be in a signature; relaxed SIMD is not supported (`wasm2c` aborts on it).
- **WASI** (0.1 only): 42 of 46 calls. There are no sockets (`sock_*` return `ENOTSOCK`): the specification lets the host give the program a socket, but wasmext
  gives it only directories, so this is a gap of wasmext and not of WASI.
  `poll_oneoff` has no clocks of the process or the thread. WASI 0.2 and 0.3 are not supported.
- **Files on Windows** use the Win32 API directly. Where Windows differs from POSIX the results differ too (see the Windows
  notes in [FEATURES.md](FEATURES.md)); a symbolic link needs a privilege there (an administrator, or Developer Mode).
- **Threads:** an extension is built with single-phase initialization and does not declare that it runs without the GIL, so importing it
  in a free-threaded build (`3.14t`, `3.15t`) turns the GIL on again. The WebAssembly code runs with the GIL held.
- **Memory that the runtime can move** (without guard pages, `--no-guard-pages`; on a 32-bit target, where the runtime does not use them; and memory64): the runtime reallocates such a memory when it
  grows. While a `memoryview` of it is alive, `memory.grow` answers -1 (WebAssembly allows that), as `bytearray` refuses to be resized while it is
  exported; drop the views (or `release()` them) to let it grow. With guard pages the buffer does not move, and a view keeps its length: take a new one
  after the memory grows. The same holds for the `memory` of the `ctypes` wrapper, and a C host of the shared library can `pin` a memory the same way.
- **Big-endian hosts** (s390x): a memory cannot be exported as a `memoryview`, and `v128` in a signature is refused.
- **Less tested in CI:** the example `coremark` is built and tested on Linux armv7l, i686, ppc64le, riscv64 and in Pyodide, and built (not run)
  for Android arm64; s390x (big-endian) and PyPy are not covered. Speed figures are from one machine.
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

Releasing: the version is the tag (`setuptools-scm`; nothing is written in `pyproject.toml`). A tag `v0.1.0a1` makes the sdist and the wheel
`0.1.0a1` and starts `.github/workflows/publish.yml`, which builds them, checks the metadata, installs the wheel on the three systems, checks that the
test suite (`pre-commit.yml`) has passed on the tagged commit, and makes a GitHub Release (a pre-release for `a`, `b` and `rc`) and publishes to PyPI (trusted publishing: the environment `pypi` of the
repository and a publisher for the project `wasmext` on PyPI); "Run workflow" with `testpypi` publishes to TestPyPI. `wasmext --version` and `wasmext.__version__` say which version is
installed, and the stub written beside a module names the version when it is a release.

## License

MIT, see `LICENSE`. The C that wasmext writes contains the runtime of `wasm2c` (Apache-2.0, from WABT): see `NOTICE.md`.

<!-- REUSABLE LINKS -->

[license]:
https://img.shields.io/github/license/natify-sh/py-wasmext

[license-url]:
https://opensource.org/licenses/MIT

[pypi version]:
https://img.shields.io/pypi/v/wasmext?logo=pypi

[python versions]:
https://img.shields.io/pypi/pyversions/wasmext?logo=python

[PyPiUrl]:
https://pypi.org/project/wasmext/

[Pre-commit]:
https://github.com/natify-sh/py-wasmext/actions/workflows/pre-commit.yml/badge.svg

[pre-commit-workflow]:
https://github.com/natify-sh/py-wasmext/actions/workflows/pre-commit.yml

[coverage]:
https://codecov.io/gh/natify-sh/py-wasmext/graph/badge.svg

[CodecovUrl]:
https://codecov.io/gh/natify-sh/py-wasmext
