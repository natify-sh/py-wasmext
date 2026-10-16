# wasmext

A proof of concept: turn a WebAssembly module into a **native CPython extension** (`.so`), so that the module runs
without any WebAssembly engine at run time. Nothing to install next to it: no `wasmtime`, no `node`.

It is the idea of [wasm2mpy](https://github.com/vshymanskyy/wasm2mpy) (a `.wasm` becomes a native MicroPython module)
moved to CPython, and an alternative to [py-wasmhost](https://github.com/ballistics-lab/py-wasmhost), which is a facade
over engines you have to bring with you.

```
module.wasm --wasm2c (WABT)--> module.c + glue/module.c + wasm-rt --cc--> module_ext.cpython-3xx-....so
```

`wasm2c` translates the module to plain C (a struct for the instance, one C function for each export, the imports as
functions that the embedder defines). The *glue* is a small C file that makes the exports Python functions, the imports
native or Python callables, and the linear memory a `memoryview`.

## The package

`src/wasmext` is the beginning of a tool in the manner of Cython: `wasmize()` turns the `.wasm` files of a project
into the `Extension`s of its `setup.py`.

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

The command line is the same in the manner of `cythonize`: `wasmext 'src/mypkg/*.wasm'` writes the C, `wasmext -i ...`
builds the extensions in place, `-b` under `build/` (`wasmext --help`).

`examples/coremark` is a package built that way. Builds with [wabt-package](https://github.com/ballistics-lab/wabt-package) (a dependency of wasmext; or
`WASMEXT_WABT`, a directory with its `bin/` and `wasm2c/`) and a C compiler; `uv run pytest` runs the tests.
The scripts and glue below are the proof of concept this started from.

## What is in the box

| | |
|---|---|
| `wasm/simple.wasm` | `add(i32, i32) -> i32`, 41 bytes |
| `wasm/coremark.wasm` | CoreMark, 10.8 KB; imports `wiring.{millis, print, stopWdt, delay}`, exports `memory`, `setup`, `loop` |
| `glue/simple.c`, `glue/coremark.c` | the glue, **written by hand** for these two modules (what a generator would emit) |
| `build.py` | `.wasm` -> `wasm2c` -> C compiler -> `build/<name>_ext*.so` |
| `bench/calls.py`, `bench/coremark.py` | the extension against [wasmhost](https://github.com/ballistics-lab/py-wasmhost) backends, if it is installed |

The two `.wasm` files are copied from wasm2mpy's `test/` (MIT, see `NOTICE.md`).

## Build and run (Linux)

You need a C compiler, the Python headers, and `wasm2c` with its runtime sources from [WABT](https://github.com/WebAssembly/wabt) 1.0.36
(the prebuilt release binary needs OpenSSL 1.1; building the `wasm2c` target from source is enough: about a minute).

```sh
export WASM2C=/path/to/wabt/build/wasm2c
export WABT_SRC=/path/to/wabt/wasm2c        # wasm-rt.h, wasm-rt-impl.c, wasm-rt-mem-impl.c ...
python build.py                              # build/simple_ext*.so and build/coremark_ext*.so
python bench/calls.py                        # the cost of one call
python bench/coremark.py                     # ~20 s per backend
```

```python
>>> import sys; sys.path.insert(0, "build")
>>> import simple_ext
>>> simple_ext.add(3, 4)
7
>>> simple_ext.add(0xFFFFFFFF, 2)    # i32 wraps as the specification says
1
```

## What was measured

One machine (Linux x86-64, 4 cores, CPython 3.13, gcc 13.3 `-O2`, WABT 1.0.36), a few runs each; the spread between
runs is about 10%, so only the big differences mean anything.

**The cost of a call** of `add(i32, i32)` (best of 5, nanoseconds):

| | per call |
|---|---|
| native extension | **150 - 215 ns** |
| wasmhost / wasmtime | 28 000 - 35 000 ns |
| wasmhost / node | 66 000 - 67 000 ns |
| wasmhost / bun | 70 000 ns |

**CoreMark**, the score the module prints itself (more is better; the extension has its imports in C, wasmhost has them in Python):

| | score |
|---|---|
| native extension | 21 800 - 22 200 |
| wasmhost / wasmtime | 20 500 - 21 700 |
| wasmhost / node | 20 800 |
| wasmhost / bun | 20 900 |

So the gain is **not in the computation** (the same ballpark as a JIT engine, within the noise), it is in the **cost of a
call** (roughly 200 to 450 times for a trivial function) and in **not needing an engine** at all.

## What this is not (yet)

- **Hand-written glue.** It is written for these two modules. The goal is to generate it from the module itself (its
  imports, exports and types); wasm2mpy has the same item open ("Auto-generate exports bindings").
- **Linux and CPython 3.13 only.** macOS and Windows (MSVC) are not tried; the build script refuses to run there.
- **One instance per module**, kept in a C global. The generated API allows many (`w2c_<name>` is a struct).
- **Traps** are turned into `RuntimeError` with `setjmp` in the glue (`wasm_rt_try`). A Python callable used as an import
  that raises would have to cross the C frames of the module with `longjmp`; this needs a small C shim and is not done.
- **Memory** is a `memoryview` made on request; it is stale after `memory.grow`.
- **Features** are what `wasm2c` 1.0.36 does. A module that needs, for example, the legacy exception handling that
  Emscripten emits, or `externref`, is not tried.
- **Not a sandbox.** It is native code in your process, protected only by the bounds checks that `wasm2c` generates.
- It does not run where a native extension cannot be loaded (iOS apps like Pythonista), which is where an engine facade still wins.

## Next

The aim is wheels: build the extensions with `cibuildwheel` straight from `.wasm`, one wheel per platform. `wasm2c`'s output
is plain C, so it can be generated once and shipped in the sdist, and the wheel builds then need a C compiler only, not WABT.
Open questions: the glue generator, `abi3` or not, MSVC, and the trap shim.
