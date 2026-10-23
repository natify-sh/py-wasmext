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
loop from Python for tiny pieces of work; give it the work in larger pieces. On CoreMark (one machine, gcc) the extension made with the
default check of the stack reaches about 91% of the same benchmark compiled as C directly, and about 98% with the guard page for the stack
(`WASMEXT_STACK_CHECK=guard`, which is warned about; the earlier build, with the guard page only, was within the noise of native). The 9% buys a stack check
that needs no handler of signals on an alternate stack per thread and names an overflow right in every thread: see
[experiments/stack_limit](docs/experiments/stack_limit/README.md) and [FEATURES.md](docs/FEATURES.md).
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
[FEATURES.md](docs/FEATURES.md#platforms-where-a-native-extension-was-built-and-tested).

`wasm2c` is needed to make the C, and so for every build: the C is a step of the build (it is in `build/wasmext/`, not in the
sources and not in an sdist), and `wabt-package` is a build requirement. Where everything is made and put: [build_model.md](docs/build_model.md).

## Use

`natify()` turns the `.wasm` files of a project into the `Extension`s of its `setup.py`:

```python
from setuptools import setup
from wasmext import natify

setup(ext_modules=natify("src/mypkg/*.wasm"))  # build-system.requires = ["setuptools", "wasmext"]
```

**The host.** A module's imports are answered by someone, and wasmext does not guess who from their names (a module can import `fd_write` and be something else). `host` says it: `"wasm32"` (the default: every import is yours, in `imports=`), `"wasm32-wasip1"` (wasmext answers `wasi_snapshot_preview1` and `wasi_unstable` itself, `wasi=` configures them, and a WASI program can be made into an executable) or `"wasm32-wasip2"` (named; the imports of WASI 0.2 are yours for now). `natify(..., host="wasm32-wasip1")`, `host = "wasm32-wasip1"` in the table, `wasmext natify --host wasm32-wasip1`, `wasmimport.install(host=...)`. The module tells it as `__host__`. A module that imports WASI 0.1 and is built with `wasm32` gets a note and asks for those imports like any others. See docs/wasi_target.md.

Or with no `setup.py` at all, in `pyproject.toml` (a hook of wasmext, an entry point of setuptools, reads the table). The keys are the
arguments of `natify()` with dashes: `module-list` (a glob pattern, or a list of them), `exclude`, `build-dir`, `force`, `quiet`, `stubs`,
`guard-pages`, `parts`, `share-tables`, `host`, `product`; and, added to each extension the table makes, those of `Extension`: `extra-compile-args`,
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
`cythonize`; `wasmext natify -i ...` also builds the extensions in place, `-b` only in `build/`: as `cythonize` does, that is the `build/` of the directory above the topmost package (`src/build/` for `src/pkg/x.wasm`), where the objects and `lib.*` are; the generated C stays in `build/wasmext/` of the working directory. The settings of `natify()` are options: `-q`, `-f`, `-X`, `--build-dir`,
`--parts`, `--limited-api` / `--no-limited-api`, `--guard-pages` / `--no-guard-pages` / `--guard-pages-for ARCH=on|off,...`, `--no-stubs`, `--share-tables`, and the product (`--shared` or `--exe`, below).

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
C made for one product never has to be made again for another (it is all in `build/wasmext/`). `wasmext natify FILE`, with `--shared` or `--exe` too, writes the C (all of it, for every product the module can have), as `cythonize` does without `-b`; with `-i` (or `-b`) the extension, the library or the program is built too
(the options `--shared` and `--exe` exclude each other: a library holds no `main`; a program of a module that is not a command is refused). `setup.py build_ext` puts the file where an extension would go: `lib<name>.so` / `lib<name>.dylib` / `<name>.dll`
(with `<name>_ctypes.py` and its `.pyi` beside it, and its header `<name>_api.h` in `build/wasmext/`: the interface of the extension over `ctypes`), or the program `<name>` /
`<name>.exe`. A program needs a `_start` and no imports but WASI's (`--env NAME=VALUE`, `--dir HOST::GUEST[:ro]`, `--argv0`, `--help`); a
library exports only its API. The settings of the extension (`libraries`, `extra-compile-args`, ...) are the flags of the build. A reactor
(`_initialize`, no `_start`) is a library, and is initialized when the instance is made, in the extension and in the library alike (WASI says the host runs `_initialize` once, before any other export; a later explicit call of it does nothing). A package whose compiled files are all libraries and programs gets a wheel tagged
`py3-none-<platform>` (any Python 3), not for the interpreter that built it. The header `<name>_api.h` is in `build/wasmext/<module name>/`: nothing in a Python package needs it (the wrapper knows the signatures), it is for a host in C or another language that is built against the library, so a wheel does not have it; a project that wants it there copies it from the build directory (a `build_ext` subclass in `setup.py`, shown in [build_model.md](docs/build_model.md)). wasmext builds the files and the project distributes them: it writes no helper that finds a program or a library at run time
(a library has its wrapper, which looks beside itself; for a program, a package does what suits it: `Path(__file__).with_name(...)` as `examples/products` does, `importlib.resources`, a `main()` of its own run by a `[project.scripts]` entry, or none of it; a project may have several programs
and may not want a launcher at all). `limited-api` and the stubs are for extensions only.

### What a source distribution carries

The `.wasm` (wasmext adds it itself, for an extension too, so `python -m build` and `uv build`, which make the wheel from the sdist, find it; no `MANIFEST.in` is needed) and the project files, nothing that wasmext made: the C is a step of the build, in `build/wasmext/` (distutils leaves `build/` out of an sdist), and a build from the sdist makes it again with the wasm2c of `wabt-package`, a build requirement. A package that ships generated C and no wasmext, to be built by a C compiler alone, is not supported. The C is made again only when its SHA-256 digest says it is stale (another `.wasm`, wasmext or WABT, or `force`), never by the time of a file.

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
`LinkError`. A mutable global can only be shared as a reference; a number given for it is a `LinkError`. A `funcref` table is linked like the others (`a['tab']` is a `Table`, or the whole instance as the shelf; a `Table(4, 8)` of the module's own class, with no module behind it, is imported too): it is one table, so a write or `table.grow` by one instance is seen by the other, and an element of the other instance can be called (a trap in it is a trap of the caller); an `externref`, 64-bit or shared table is left out, and an imported table is not exported again. The instance that owns a table keeps alive the instances that imported it. From Python a table is read and written with `Table.get(i)` (a `Function`: callable if its type is one the module declares, with `name` and `signature`) and `Table.set(i, function)`; only a function of a module that shares tables (a `funcref` table of its own, or the option `share_tables`) can be put in a table, because a trap in it has to come back through the table to the caller. A `funcref` is also a parameter or a result of an exported function. [`examples/plugins`](examples/plugins) shows it.
[`examples/link`](examples/link) is a package of two modules that use each other; the design is in [DESIGN.md](docs/DESIGN.md).

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
  (wide-character functions) on Windows. `-DFUSEDWASI_P1_HOST_FS=1` makes them go through Python (`os`) instead, as a way to test.
- **Tested** against the programs of the official [wasi-testsuite](https://github.com/WebAssembly/wasi-testsuite) for WASI 0.1 (72 of
  them: C, Rust, AssemblyScript), all passing on Linux (both ways of reaching files), macOS and Windows in CI (`tests/wasi_testsuite/`);
  with the files through Python on Windows, `symlink_filestat` is expected to fail before Python 3.13, which cannot set the times of a link. A real program that
  uses all this is [`examples/lua`](examples/lua); `coreutils` (10.8 MB) was run by hand.

See [DESIGN.md](docs/DESIGN.md#design-wasi) for the design.

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


### Traps from the stack and from signals

A fault in a module is the error of a call (`Trap`), not the end of the process that holds the module: an access past the memory, and the stack running out. Three things to know:

- **The stack is checked in each function by default** (off Windows, Emscripten and WASI): the prologue compares the address of the frame with the lowest safe address of the thread. No handler of signals on an
  alternate stack per thread is needed for it, and an overflow is called what it is in every thread. It costs about 9% on CoreMark against C (the guard page: about 2%). `WASMEXT_STACK_CHECK=guard` in the
  environment of the build uses the guard page and the handler instead, and warns about what it gives up; any other value is an error. Windows keeps the counter of the depth of wasm2c (500 calls).
  Measurements and the reasons: [experiments/stack_limit](docs/experiments/stack_limit/README.md). Alpha (`0.0.1a2`).
- **Two modules in one process** each turn a fault into a trap of their own (a chain of handlers of SIGSEGV/SIGBUS; the runtime of wasm2c installs none of its own). A crash that is not in a call of a module stays a crash.
  Known: a module called from inside a call of another module, through Python, is not told apart when a fault comes (the one first in the chain takes it).
- Any thread may call a module; each sets itself up at its first call.

### Large modules

The C that `wasm2c` writes is about 13 times the size of the module, and one file of millions of lines is a very long job for a
C compiler (the 10.8 MB `coreutils.wasm` was not done in half an hour). A module of 1 MiB or more is therefore written in several
files, which are compiled at the same time (128 KiB of the module for each file, at most 256). `natify(..., parts=N)`, `wasmext natify
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
`cibuildwheel` builds in CI on seven platforms (Linux x64 and ARM64, Windows x64, x86 and ARM64, macOS Apple Silicon and Intel) for `coremark`, `lua`, `quickjs` and `products` (`link` and `wabt` are built locally only). `coremark`
is built in CI on more: Linux armv7l, i686, ppc64le and riscv64, Pyodide and Android. Build and test an example with `uv sync --reinstall`
and `uv run pytest` in its folder.

| | |
|---|---|
| [`examples/coremark`](examples/coremark) | the CoreMark benchmark as a module (imports the clock and print from Python) |
| [`examples/link`](examples/link) | two modules that use each other's memory, variable and function with no Python in between |
| [`examples/plugins`](examples/plugins) | a host and two plugins that share one `funcref` table (dynamic linking), and a `Table` that no module owns, with a function put in it from Python |
| [`examples/lua`](examples/lua) | Lua 5.4, a WASI program: `luawasm.run(["script.lua"], root="dir")`, files in the directory it is given and nowhere else |
| [`examples/wabt`](examples/wabt) | WABT itself: `wat2wasm` and `wasm2c` as WASI programs in extensions (`wabtwasm.wat2wasm(...)`), and a directory for `WASMEXT_WABT` made of them, so that wasmext translates with a `wasm2c` that wasmext built; the C they write is the same bytes as the native tools' |
| [`examples/wasi2_unbundled`](examples/wasi2_unbundled) | two C programs built as WASI 0.2 components, their core modules taken out with `wasm-tools component unbundle` and run as extensions with a host of WASI 0.2 written in Python (stdout, clocks, `poll`, a TCP client socket); not built by the CI |
| [`examples/quickjs`](examples/quickjs) | QuickJS-ng, a JavaScript engine as a WASI program: `qjswasm.run(["script.js"], root="dir")`, an error of the script is code 1 and a message, as on the command line |
| [`examples/products`](examples/products) | one wheel with a shared library (used through `ctypes`) and a WASI program as a native executable, both made by wasmext; `py3-none-<platform>` |

What is supported, what is not yet, and the plan are in [FEATURES.md](docs/FEATURES.md).

## Status

**Alpha.** The core works and is tested: in CI the test suite passes on Linux, macOS and Windows, the examples build into wheels on
seven platforms, and the WASI programs of the official test suite run on all three systems. But the interface can still change
(the format of the link between instances is `v1` and has not been in a release), and the rest of this section is what to expect.
The package is on PyPI as a pre-release (`0.0.1a1`): `pip install --pre wasmext`. To try the code of a branch, build the wheel from a checkout (`uv build`) and install it with
`pip install --find-links <the folder of the wheel> wasmext`, as the examples do in CI.

### Public interface

What may be relied on, and what may change. This is the boundary for the alpha; a change to the first tier is written in the release notes, a change to the others may come without one.

**Stable** (the interface that users of a built wheel, and of the build, see):

- The module that wasmext makes: `Instance(imports, wasi=...)`; an export as an attribute or a method; `instance["name"]` and `instance.__exports__` (a reference to give to another instance as an import: a capsule of the ABI below, or, from the wrapper for ctypes, an object that gives one as `__wasmext_ref__`);
  an exported memory as a `memoryview`; an exported global as an attribute; a `v128` as 16 bytes; the exceptions `Trap` and `LinkError`, `UncaughtException` (for a module that has exception tags) and, for a module that uses WASI, `WasiExit`, `WasiSignal`, `WasiTerminated`; the `.pyi` beside the built module.
- The build: `natify()` and its keyword arguments, the options of `wasmext natify` (and `wasmext inspect`, whose text is for people, not for programs), the keys of `[[tool.wasmext.ext-modules]]` and `limited-api` of `[tool.wasmext]` in `pyproject.toml`, and the values of `product`.
- The environment variables of a user: `WASMEXT_WABT`, `WASMEXT_WASM2C`, `WASMEXT_WASM2C_RUNTIME`, `WASMEXT_WASM2C_INCLUDE`, `WASMEXT_LIMITED_API`, `WASMEXT_GUARD_PAGES`, `WASMEXT_PARTS`, `WASMEXT_JOBS`, `WASMEXT_NO_PYPROJECT`, `WASMEXT_FORCE_REGEN` (a build again of the C), `WASMEXT_<NAME>_LIBRARY` (the path of the library for its ctypes wrapper); `WASMIMPORT_BUILD_DIR` of `wasmimport` is provisional.
- The products: the header `<name>_api.h` of a shared library (its functions, among them `<name>_export_find` and `<name>_link_*_import<j>` for functions, globals and memories; `<name>_config`, the trap codes) and the wrapper `<name>_ctypes.py`, which has the interface of the extension; the command line of a program made with `--exe` (`--env`, `--dir`, `--argv0`, `--help`, `--version`) and its exit codes.
- `wasmext.__version__`, `GenError` and `WasmError`.
- **The ABI between built modules** (one number made like `PY_VERSION_HEX`, `0xXXYYZZLS`: `WASMEXT_ABI` in `wasmext_glue.h`; it is not the version of the package, but at a release the two agree in the numeric part):
  - the record `wasmext_export` (`size`, `abi`, `kind`, `type`, `flags`, `owner`, `address`, `instance`, `signature`, `runtime`, `funcref`, `floor`; the field `funcref` and the flag bit 4 belong to the tables and are **provisional** with them, see below; `<name>_export` in `<name>_api.h`; `flags`: bit 0 a mutable global, bit 1 a 64-bit memory, bit 2 a memory with guard pages, bit 3 a function that needs no Python, bit 4 a function of a module that shares tables, which may be put in a table; `funcref` is set for a function: the `wasm_rt_funcref_t` of it, valid while `owner` is; `floor` is the last field: the lowest ABI of a reader that can use the record, set by the exporter from what the record uses) and the capsule `wasmext.export.v<X>` (X is the major part of the ABI) that carries it in Python. Any host may make such a record and give it
    to an instance as an import, or read one it was given. A reference to an export that is not a capsule gives one as its attribute `__wasmext_ref__` (what the wrapper for ctypes gives);
  - **provisional, with the tables:** for modules that share tables, the stack of entries for traps: the struct `wasmext_traps` (`size`, `runtime`, `enter`, `leave`, `trap`, `join`) and the capsule `wasmext.traps.v<X>` that carries it in the dictionary of the interpreter, which the first such module loaded puts there.
  A record only grows at its end (its `size` tells a reader what is there, its `floor` what a reader must be to use it). Modules link if their major part (x) is the same, the reader is not below the `floor` of the record and `size` covers the first version of the record, whichever versions of wasmext made them; otherwise the link is a
  `LinkError` that says so. The layout of the structs of the wasm2c runtime (the memory, the table, the element of a table) is **not** compared when modules are linked: it is checked when a module is built (`WASMEXT_LAYOUT` in `wasmext_glue.h`), and a runtime with another layout does not build. `WASMEXT_RUNTIME` is a fingerprint of it for the maintainers (only the stack of traps compares it, because of the buffer of `longjmp`).
  In `v0` (x = 0) nothing that works is broken: only fixes (z) and additions that break nothing (y); `1.0.0` is planned to break once, with the *context*. `abi/current.json` declares the public surface (constants, structs, signatures of the C API) and `tests/test_abi_declaration.py` fails on any difference with the code and says what version the change needs; `tests/test_abi.py` also fingerprints all the files of `wasmext/c/`. What a version needs is the maintainer's decision. The policy (the number, the `floor`, the declaration and the layout check are built; the CI against earlier releases is not) is in [abi_policy.md](docs/abi_policy.md).

**Provisional** (works, used by the tests, but its shape is not settled): `generate()`, `parse()`, `mangle()`, `Glue` and the types of a parsed module (`Module`, `Import`, `Export`, `FuncType`, `GlobalType`, `TableType`, `Limits`, `ValType`);
`find_toolchain()` and `Toolchain`; `wasmimport` (`install`, `uninstall`, `clean`, `WasmFinder`, `WasmImportLoader`), a development tool.

**Provisional, the tables and references** (they work and are tested, but they are alpha inside the alpha: the way instances are linked may change with the design of the *context*, a group that instances are bound to when they are made, see [context_concept.md](docs/context_concept.md)): an exported `funcref` table by `instance["name"]`, which is a `Table` (not an attribute); the classes `Table` (`Table(initial, maximum=None)`, `size`, `maximum`, `grow(delta)`, `get(index)`, `set(index, function)`, `len()`) and `Function` (what `Table.get` and a `funcref` result give: `name`, `signature`, a call, `==` and `hash` by function and instance; it cannot be made by hand), both with the same members in the extension, the wrapper for ctypes and the `.pyi`, in a module that shares tables (it imports or exports a `funcref` table, has a `funcref` in the signature of an export, or is built with `share_tables`); a `funcref` as a parameter (None, a `Function`, or a function of an instance of a module that shares tables) or a result (a `Function` or None) of an export; the option `share_tables` (`natify(share_tables=)`, `share-tables`, `--share-tables`, `wasmimport.install(share_tables=)`); in the C API of a library `<name>_link_table_import<j>`, `<name>_traps`, `<name>_traps_use`, `<name>_unlink_tables`, the table and function API (`<name>_table_new`, `_free`, `_size`, `_maximum`, `_grow`, `_export`, `_is_null`, `_is`, `_set`, `_get_ref`; `<name>_funcref_type`, `_call<k>`, `_copy`, `_free`, `_same`, `_hash`, `_export`; a `funcref` in the signature of an export is `const void *` in and `void **` out, freed with `<name>_funcref_free`); the field `funcref` and the flag bit 4 of the record `wasmext_export`, and the stack of entries `wasmext_traps` with its capsule `wasmext.traps.v<X>`.

**Private** (no promise at all): every module whose name begins with an underscore (`wasmext._*`), the setuptools hook that `pyproject.toml` entry points register, the headers in `wasmext/c/` (except the record, the stack of entries, the capsules and the macros of the ABI named above), the methods `__wasmext_keep__` (an owner of a table is told of an instance that imports it) and the other names with `__wasmext_` in them that are not named above, the C that wasmext writes (`*_glue.h`, `*_w2c.*`, `*_py.c`, the `build/wasmext/` folder: it is what is built, not an interface), the other `WASMEXT_*` macros of those headers,
and the cache of `wasmimport`.

### Known limitations

- **WebAssembly:** a `funcref` table is linked between instances (an extension, a wrapper for ctypes or a library, in any pair), and a module that imports or exports one (or is built with `share_tables`) has the class `Table` (`Table(initial, maximum=None)`, `size`, `maximum`, `grow`, `get`, `set`, `len`; the same in the extension, the wrapper and the `.pyi`; `get` gives a `Function`, called if its type is one that the module declares; only a function of a module that shares tables (it has a `funcref` table, or is built with `share-tables`, `natify(share_tables=True)`, `--share-tables`) can be put in a table), a memory or a global with no code behind it is a module that only declares it (built like any other; there is no object for it that `wasmext` makes while it runs), and an `externref`, a 64-bit or a shared table is left out and reported (an imported table is not exported again); the owner of a table keeps the instances that imported it alive for as long as it lives; a C host unlinks them (`<name>_unlink_tables`) before freeing them; no threads or shared memory;
  a `funcref` is a parameter or a result of an **export** (a parameter takes None, a `Function`, or a function of an instance that shares tables; a result is a `Function` or None; the instance keeps what it was given), but not of an import (the module is refused), and an `externref` cannot be in a signature; a function of a module that does not share tables cannot be put in a table.
- **The tables and references are provisional** (see "Public interface"). They were run in CI on Linux, macOS and Windows with the test suite, except the test of a C program over two libraries, which is skipped on Windows.
- **Not supported by `wasm2c` or not read by wasmext:** relaxed SIMD (`wasm2c` aborts), typed function references (`wasm2c` stops at `call_ref`), garbage collection (WABT does not read it; wasmext refuses the types), wide arithmetic (limited in `wasm2c`), custom page sizes (the module is refused with a `WasmError`) and compact imports. What can be done about each is in [wasm2c_limits.md](docs/wasm2c_limits.md).
- **Exception tags** cannot be exported, imported or shared between instances: an uncaught exception of a tag of another module is an `UncaughtException` whose `tag` is `None`.
- **WASI** (0.1 only; 0.2, 0.3 and components were tried, see [WASI_COMPONENTS.md](docs/WASI_COMPONENTS.md)): 42 of 46 calls. There are no sockets (`sock_*` return `ENOTSOCK`): the specification lets the host give the program a socket, but wasmext
  gives it only directories, so this is a gap of wasmext and not of WASI.
  `poll_oneoff` has no clocks of the process or the thread. WASI 0.2 and 0.3 are not supported.
- **Files on Windows** use the Win32 API directly. Where Windows differs from POSIX the results differ too (see the Windows
  notes in [DESIGN.md](docs/DESIGN.md)); a symbolic link needs a privilege there (an administrator, or Developer Mode).
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

The full list, with the reasons and the plan, is in [FEATURES.md](docs/FEATURES.md).

## Development

```sh
git clone https://github.com/natify-sh/py-wasmext
cd py-wasmext
uv sync
uv run pytest        # builds real extensions: needs a C compiler
uv tool install pre-commit && pre-commit install   # the hooks of .pre-commit-config.yaml, for commit and for push
```

The hooks that run on a commit are the ones CI runs on the three systems (`pre-commit.yml`: pyright, ruff, pytest). Before a **push** two more run: pyright as it
sees the code on Windows and on macOS (`--pythonplatform`), because an attribute of the library that exists on one system is an error of the type checker on another
(CI found `os.fdatasync` and the POSIX-only `os` attributes that way); they are not part of CI, which has the real systems.

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
