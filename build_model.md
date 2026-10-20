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
| wheel / `build` | `build/lib.*`, then the wheel | the same place, beside the product |
| in place (`-i`, editable install) | beside the `.wasm` in the source tree | the same place, beside the product |

- An extension has its stub `<name>.pyi` beside it. A shared library has `<name>_ctypes.py` and `<name>_ctypes.pyi` beside it.
  A program has no parts.
- Nothing is a source distribution format: the generated C is a step of the build. A source distribution has the `.wasm` and the
  project files only (distutils leaves `build/` out), and a build from it needs `wasm2c` (`wabt-package` is a build requirement,
  so it is there).
- `wasmext natify -i` builds in `build/` and puts the products in place; `-b` builds in `build/`.

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
| **platform wheel** (`cp311-abi3-<plat>`, `cp315-cp315t-<plat>`, ...) | `pkg/add.abi3.so`, `pkg/add.pyi` | — (the tag is `py3-none` when all are products) | — |
| **`py3-none-<plat>` wheel** (only libraries and programs) | — | `pkg/libengine.so`, `pkg/engine_ctypes.py`, `pkg/engine_ctypes.pyi` | `pkg/hello` |
| **mixed wheel** | the tag of the extensions (abi3 or native) | the same files as above | the same |
| **in place** (`-i`, editable) | `src/pkg/add.abi3.so`, `src/pkg/add.pyi` next to `add.wasm` | `src/pkg/libengine.so`, `engine_ctypes.py`, `engine_ctypes.pyi` | `src/pkg/hello` |
| **sdist** | `add.wasm`, `pyproject.toml`, `setup.cfg`, `PKG-INFO`, the Python of the project | the same | the same |

- A `py3-none-any` wheel does not exist for wasmext products: any extension, library or program has a binary, so a wheel has a platform tag.
  What is `py3-none-<plat>` is a wheel of libraries and programs only. (`wasmext` itself is `py3-none-any`.)
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

## What this removes

- `<name>_wasmext/` in the source tree, and the `.gitignore` and `MANIFEST.in` lines for it.
- The mode "a tree that ships its C builds without wasm2c" (a build always needs the toolchain).
- The copy of the runtime beside the C.

## Open (to be checked in CI)

- Windows, 260 characters: the objects of setuptools mirror the path of the source
  (`build/temp.<tag>/build/wasmext/<module>/...`). Relative paths do not help: the limit is on the full path the compiler
  writes. If it bites, the objects get flat names, as the program and the library already have.
- `plat_name` of cross builds (Android, iOS, Pyodide) is only in `temp.*`/`lib.*`, which setuptools names itself.
