# The build model

Where the files of a wasmext project are made, and where they end up. The code follows this page; when they differ, the code
is wrong or this page is out of date.

## The idea

Three kinds of files, three places.

| Kind | What | Where |
|---|---|---|
| **Sources** | the `.wasm`, and the Python the author writes | the source tree; nothing generated is written there |
| **Generated** | the C (wasm2c output, glue, wrappers of the runtime), the C API header `<name>_api.h`, the stub `<name>.pyi` as it is made | `build/wasmext/<module name>/` |
| **Products** | the extension, the shared library, the program, and what is part of a product (the stub of an extension, `<name>_ctypes.py` and `.pyi` of a library) | where the build puts products: `build/lib.<plat>-<tag>/` and the wheel, or in place |

What setuptools makes from the generated C (objects) is in `build/temp.<plat>-<tag>/`, as for any extension.

## Generation

- One step for every product. The C of every target the module can have (extension, shared library, program) is made together;
  a build only chooses which files to compile (`generate_c`).
- The C does not depend on the platform or the Python (platform choices are macros at compile time), so it is **one copy per
  project**, `build/wasmext/<module name>/`, shared by every wheel built from the tree. It is made again only when its content
  digest says it is stale: another `.wasm`, another wasmext, another WABT, another number of files, or `force`
  (`WASMEXT_FORCE_REGEN=1`).
- The directory is named by the full module name (`pkg.add`), which is unique in a project; two packages cannot overwrite each
  other. Objects are separated by setuptools (`temp.<tag>`), products by `lib.<tag>`.
- Files are written whole or not at all (a temporary file, then `os.replace`), so builds of several Pythons from one tree do
  not read half a file.
- The runtime of wasm2c is not copied. Three small files in the directory (`<name>_rt_impl.c`, `<name>_rt_mem.c`,
  `<name>_rt_exceptions.c`) include the files of the toolchain, found by `-I`; the only change (`abort()` of
  `wasm_rt_allocate_memory` is a trap) is made in `<name>_rt_mem.c` by a macro. The original sources stay as they are.
- `wasmext natify` with no `-i`/`-b` only generates (into the same directory).
- `build_dir` (option, `--build-dir`, a key of the table) changes the directory of the generated files, and nothing else. It is
  rare. A user who changes it knows where the files are.

## Products

`-i`, `-b`, `setup.py` and the configuration only say **where a product goes**, never where the C is:

| | the product | its parts |
|---|---|---|
| wheel (`pip wheel`, `python -m build`, `pip install .`) | `build/lib.*` of the project, then the wheel | the same place, beside the product |
| `wasmext natify -b` | `build/lib.*` of the directory above the topmost package (`src/build/lib.*` for `src/pkg/x.wasm`), as `cythonize -b` | the same place, beside the product |
| in place (`-i`, `build_ext --inplace`, editable install: `pip install -e .`, `uv sync`) | beside the `.wasm` in the source tree | the same place, beside the product |

- An extension has its stub `<name>.pyi` beside it. A shared library has `<name>_ctypes.py` and `<name>_ctypes.pyi` beside it.
  A program has no parts.
- Nothing is a source distribution format: the generated C is a step of the build. A source distribution has the `.wasm` and the
  project files only (distutils leaves `build/` out), and a build from it needs `wasm2c` (`wabt-package` is a build requirement,
  so it is there).
  The `.wasm` of an extension gets into the sdist by wasmext itself (the `egg_info` that its hook installs adds it: the sources of the extension are the generated C, which an sdist
  leaves out); a library or a program has it as its source already. No `MANIFEST.in` is needed for it. Whether the `.wasm` is in the **wheel** is still the project's (see below).
- `wasmext natify -i` and `-b` build in the directory above the topmost package of each module (`src/` for `src/pkg/x.wasm`, as `cythonize` does), so the objects and
  `lib.*` are in its `build/` (`src/build/`); `-i` then puts the products in place, `-b` leaves them there. The generated C is in `build/wasmext/` of the working directory in both.
  (Checked on a small project with `setup.py build_ext --inplace`, `natify`, `-i`, `-b`, `pip install -e .`, `uv sync`, `pip install .`, `pip wheel`, `python -m build` and `uv build`.)

## Ways to build, checked

Each way below was run by hand on a small project (`src/demo/add.wasm`, `setup.py` with `natify("src/demo/*.wasm")`, setuptools, CPython 3.11, Linux, a clean tree
for each), with `wasmext` installed from a wheel. The generated C is in `build/wasmext/demo.add/` in all of them. (`pip` and `uv` need `wasmext` and `wabt-package` to be found:
from the index, `--find-links`, or `[tool.uv.sources]`.)

| Way | Where the product (`add.abi3.so`, `add.pyi`) is | What else it leaves |
|---|---|---|
| `python setup.py build_ext --inplace` | beside the `.wasm`, `src/demo/` | `build/lib.*` (a copy), `build/temp.*` |
| `wasmext natify FILE` | no product: only the C | |
| `wasmext natify -i FILE` | beside the `.wasm`, `src/demo/` | `src/build/lib.*`, `src/build/temp.*` (the build ran in `src/`) |
| `wasmext natify -b FILE` | `src/build/lib.*/demo/` | `src/build/temp.*` |
| `pip install -e .`, `uv sync` (an editable install) | beside the `.wasm`, `src/demo/`; `site-packages` has a `.pth` that names `src/` | `build/wasmext/` |
| `pip install .` | in `site-packages/demo/` | `build/lib.*`, `build/temp.*` in the tree |
| `pip wheel .`, `python -m build --wheel` | in the wheel `demo-0.1.0-cp311-abi3-<plat>.whl`: `demo/__init__.py`, `add.abi3.so`, `add.pyi` | `build/lib.*`, `build/temp.*` |
| `python -m build`, `uv build` (no arguments: an sdist, then the wheel **from the sdist**) | the same wheel, and `demo-0.1.0.tar.gz` | |

- The wheel has neither the C nor the `.wasm`; the sdist has the `.wasm` (below) and no C.
- **The sdist and the `.wasm`.** The sources of an extension are the generated C, which an sdist leaves out, and the `.wasm` is only among its `depends`, which setuptools
  does not take into an sdist. Without a remedy the sdist was built from nothing, `natify()` found no `.wasm`, and the wheel made from it was `py3-none-any` with only the
  Python of the project in it (the build said `'src/demo/*.wasm' does not match any files` and went on). wasmext's hook now installs an `egg_info` that adds the `.wasm` of
  every extension that `natify()` made (`egg_info_with_wasm`, `_setuptools.py`), so no `MANIFEST.in` is needed; `tests/test_products.py` builds an sdist in a clean
  tree and a wheel from it. (A library or a program has the `.wasm` as its source from the start.) A project that does not use the hook of wasmext (no setuptools, or
  `natify()` called from another backend) puts the `.wasm` into its sdist as that backend does.

## The trees

`pkg/add.wasm` is an extension, `pkg/engine.wasm` a shared library, `pkg/hello.wasm` a program (WASI command). The extension tree is what a real build gave
(abi3 on CPython 3.11, Linux); the products are the same by the code, with the file names of the platform.

### `build/`

```
build/
├── wasmext/                          generated, one copy per project, the same for every platform and Python
│   ├── pkg.add/                      one directory per module, by its full name
│   │   ├── add_w2c.c  add_w2c.h      wasm2c
│   │   ├── add_glue.h  wasmext_glue.h   the glue (and the WASI headers, for a module that uses WASI)
│   │   ├── add_rt_impl.c  add_rt_mem.c  add_rt_exceptions.c   include the runtime of the toolchain
│   │   ├── add_py.c                  extension front end
│   │   ├── add_shared.c  add_api.h   shared library front end and its C API header
│   │   ├── add_main.c                program front end (only for a WASI command)
│   │   └── add.pyi                   the stub, as it is made
│   ├── pkg.engine/                   the same; a product also keeps here its work: obj/, engine.map, libengine.shared.stamp
│   └── pkg.hello/
├── temp.<plat>-<tag>/                objects of an extension (setuptools)
└── lib.<plat>-<tag>/                 what the wheel is made from (products and their parts)
    └── pkg/
        ├── add.abi3.so   add.pyi                       extension
        ├── libengine.so  engine_ctypes.py  engine_ctypes.pyi   shared library (.dylib, .dll)
        └── hello                                       program (hello.exe)
```

### `dist/` and what is in each form

| | extension | shared library | program |
|---|---|---|---|
| **wheel with an extension** (`cp311-abi3-<plat>`, `cp315-cp315t-<plat>`: platform and Python ABI) | `pkg/add.abi3.so`, `pkg/add.pyi` | — (the tag is `py3-none` when all are products) | — |
| **wheel of libraries and programs only** (`py3-none-<plat>`: platform, not Python) | — | `pkg/libengine.so`, `pkg/engine_ctypes.py`, `pkg/engine_ctypes.pyi` | `pkg/hello` |
| **mixed wheel** | the tag of the extensions (abi3 or native) | the same files as above | the same |
| **in place** (`-i`, editable) | `src/pkg/add.abi3.so`, `src/pkg/add.pyi` next to `add.wasm` | `src/pkg/libengine.so`, `engine_ctypes.py`, `engine_ctypes.pyi` | `src/pkg/hello` |
| **sdist** | `add.wasm`, `pyproject.toml`, `setup.cfg`, `PKG-INFO`, the Python of the project | the same | the same |

- The tag follows what is in the wheel: only Python, `py3-none-any`; only libraries and programs, `py3-none-<plat>` (depends on the platform,
  not on Python); an extension in it, `cp311-abi3-<plat>` or `cpXY-cpXY-<plat>`. So a wheel with any product of wasmext is never `any`.
  (`wasmext` itself is `py3-none-any`.)
- `<name>_api.h`, the C, the objects, the stamps and `build/wasmext/` are in no wheel and no sdist. A project that wants a header in the wheel
  copies it (see above).
- The `.wasm` is in the sdist; whether it is in the wheel is the project's (`include-package-data = false` and `package-data`).

## The C API header `<name>_api.h`

It is generated, not a product: it stays in `build/wasmext/<module name>/`. The wheel does not carry it by default. A project
that wants to ship it (or a `.pyi`, or any other generated file) takes it from the build directory itself, in either way:

```python
# setup.py: after the build, copy the header into the package that is going to the wheel
from pathlib import Path
from setuptools import setup
from setuptools.command.build_ext import build_ext
from wasmext import natify


class build_ext_with_header(build_ext):
    def run(self):
        super().run()
        header = Path("build/wasmext/mypkg.engine/engine_api.h")  # the directory of the module, by its full name
        target = Path(self.build_lib) / "mypkg" / header.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(header.read_bytes())


setup(ext_modules=natify("src/mypkg/engine.wasm", product="shared"), cmdclass={"build_ext": build_ext_with_header})
```

The same is how a project puts anything else of `build/wasmext/` into the wheel or the source distribution.
`[tool.setuptools.package-data]` cannot name a file outside the package, so it is not the way.

## Build backends

**Decision: wasmext builds through setuptools, and says so.** `natify()` returns `Extension` objects and the hook is a setuptools entry point,
as with `cythonize()`. `setuptools>=84` is a dependency of `wasmext` (the version the suite runs with; `uv.lock`), and the compiler comes
from the `distutils` that setuptools provides (`import setuptools`, then `distutils.ccompiler`; `newer_group` from `setuptools.modified`),
not from its private `_distutils`. There is no alternative for the compiler driver of a Python extension (MSVC detection, the flags of the
platform, the variables of cibuildwheel) outside distutils. The sdist is whatever the backend makes of the source tree: wasmext adds no filter
of its own, so nothing a user puts into the sdist is taken out; it adds one thing, the `.wasm` of an extension (see "Ways to build, checked"). The generated files stay out because they are not in the source tree, and
`build/` is left out by the backend's own rules (distutils prunes it by the separator of the system, which is why the paths given to
setuptools use that separator). `uv build` and `pip` run the project's backend, so with setuptools they work as they do.

### What was tried, and found

- **Cython is the same.** In Cython 3.3.0, Python 3.12, a venv with no setuptools: `cython m.pyx` works; `cythonize m.pyx` (generation
  only) and `cythonize -i m.pyx` both fail with `No module named 'distutils'`. So `cythonize` is the setuptools layer, `cython` the translator.
  `wasmext natify` is the `cythonize` of wasmext. There is no `cython` of wasmext (a command that writes the C and needs no setuptools) and
  none is planned: the generated C is a step of the build and not a format of distribution (see above), so a standalone generate step
  has no use of its own. `wasmext inspect` needs no setuptools; `natify`, even with no `-i`/`-b`, imports it.
- **hatchling works, through a hook that runs the command.** `examples/coremark` and `examples/products` with `build-backend = "hatchling.build"`,
  a build hook (`hatch_build.py`) that runs `python -m wasmext natify -q -i [--shared|--exe] FILE`, `artifacts` for the built files and
  `build_data["tag"]` for the wheel tag: the wheels are `cp311-abi3-<plat>` (the extension and its `.pyi`) and `py3-none-<plat>` (the library with
  its ctypes wrapper, and the program); the tests of the examples pass in a clean environment, also from an isolated `uv build`. Kept in the
  session, not in the repository. It found: setuptools was not a declared dependency of `wasmext` (the examples had it as their own backend),
  so the isolated build failed with `No module named 'setuptools'` (fixed: it is a dependency); the project says the wheel tag itself on such a
  backend, as the hook of setuptools that does it is not there; and hatchling puts `build/` into the sdist unless the project's `.gitignore`
  has it, as it would any build output.
- **meson-python and scikit-build-core are not supported.** They rely on meson/CMake and ninja, find the compiler themselves (toolchain
  detection, cross files) and do not use distutils. They would take the generated C as sources of their own targets. A sketch of such a project
  (a `custom_target` with a fixed list of outputs, so `--parts 1`, in meson; a configure-time `execute_process` and `file(GLOB)` in CMake, compiling
  per product only `<n>_py.c` / `<n>_shared.c` / `<n>_main.c` with the common files) shows what is missing: the include directories of the runtime of
  the toolchain and of simde and the macros (`WASM_RT_USE_MMAP`, `Py_LIMITED_API`, `WABT_BIG_ENDIAN`) are not printed anywhere, and the ctypes wrapper
  of a library is written by the build and not by the generation. None of it is built or tried. If someone needs it, a `--print-build` (JSON) on
  `natify` and moving the wrapper into the generation are the first steps.

## What this removes

- `<name>_wasmext/` in the source tree, and the `.gitignore` and `MANIFEST.in` lines for it.
- The mode "a tree that ships its C builds without wasm2c" (a build always needs the toolchain).
- The copy of the runtime beside the C.

## Open (to be checked in CI)

- Windows, 260 characters: the objects of setuptools mirror the path of the source
  (`build/temp.<tag>/build/wasmext/<module>/...`). Relative paths do not help: the limit is on the full path the compiler
  writes. If it bites, the objects get flat names, as the program and the library already have.
- `plat_name` of cross builds (Android, iOS, Pyodide) is only in `temp.*`/`lib.*`, which setuptools names itself.
