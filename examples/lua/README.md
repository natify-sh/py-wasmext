# wasmext-example-lua

[Lua](https://www.lua.org/) 5.4.6, a **WASI program** compiled to WebAssembly (`src/luawasm/_lua.wasm`), turned into a native CPython
extension by [wasmext](../..): a package with no WebAssembly engine at run time, and a Lua that reads and writes files through the WASI that
wasmext compiles into the module (in C, no interpreter in between for the data).

```sh
# wasmext (and with it wabt-package) is a build requirement, and a C compiler is needed. wasmext is not on PyPI yet, so uv takes it
# from the root of the repository (`[tool.uv.sources]` in pyproject.toml). This is the way to build the example:
uv sync --reinstall                       # --reinstall: build the extension again (uv keeps what it built before)
uv run python -m luawasm -e "print(2^10)" # 1024.0
echo 'for l in io.lines() do print(l * 2) end' > double.lua
seq 3 | uv run python -m luawasm double.lua   # the current directory is the whole world of the script
```

The tests: `uv run pytest` (the `dev` group of the example has pytest, and `uv sync` installs it).

With pip, build the wheel of wasmext in the root of the repository (`uv build --wheel -o dist`) and give it as a source:
`pip install --find-links ../../dist .`.

```python
import luawasm

result = luawasm.run(["script.lua"], root="some/directory")  # Result(code, stdout, stderr)
```

`setup.py` is the whole integration:

```python
from setuptools import setup
from wasmext import natify

setup(ext_modules=natify("src/luawasm/*.wasm", parts=8, host="wasm32-wasip1"))  # the C of the module in 8 files, compiled at the same time
```

`cibuildwheel` builds wheels of it as it does for any extension (see `.github/workflows/example-wheels.yml`: Linux, macOS and Windows).

## What the script can reach

Only the directory it is given (`root=`): it can read, write, append, truncate, create directories and remove files there, and **nothing
above it** (`..`, an absolute name, or a symbolic link that leads out is refused with `ENOTCAPABLE`). With no `root` it sees no files. See
"WASI programs" in the [README](../../README.md).

## The WebAssembly module

`_lua.wasm` is Lua 5.4.6 (MIT) built to WASI with wasienv, taken as it is from the npm package
[`@antonz/lua-wasi`](https://www.npmjs.com/package/@antonz/lua-wasi) (`dist/lua.wasm`, from https://github.com/nalgeon/lua-wasi). It
imports 19 functions of `wasi_unstable`, the first snapshot of WASI, and exports `memory` and `_start`. It was built **without
`longjmp`**: an error in a script (a syntax error, `error()`, a failed `pcall`) ends it with a trap and no message, which `luawasm.run`
reports as the code `134` (`luawasm.ABORTED`).

The module is 329 KB; wasm2c writes about 4 MB of C for it, which one file of takes half a minute to compile and eight files take a few
seconds (see "Large modules" in the [README](../../README.md)).
