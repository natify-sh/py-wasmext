# wasmext-example-quickjs

[QuickJS-ng](https://github.com/quickjs-ng/quickjs) v0.17.0, a JavaScript engine and a **WASI program** compiled to WebAssembly
(`src/qjswasm/_qjs.wasm`, 1.1 MB), turned into a native CPython extension by [wasmext](../..): a package with no WebAssembly engine at run
time, and a JavaScript engine that reads and writes files through the WASI that wasmext compiles into the module.

```sh
# wasmext (and with it wabt-package) is a build requirement, and a C compiler is needed. wasmext is not on PyPI yet, so uv takes it
# from the root of the repository (`[tool.uv.sources]` in pyproject.toml). This is the way to build the example:
uv sync --reinstall                                   # --reinstall: build the extension again (uv keeps what it built before)
uv run python -m qjswasm -e "console.log(2 ** 10)"   # 1024
echo 'console.log("hello")' > hello.js
uv run python -m qjswasm hello.js                    # the current directory is the whole world of the script
```

The tests: `uv run pytest` (the `dev` group of the example has pytest, and `uv sync` installs it).

With pip, build the wheel of wasmext in the root of the repository (`uv build --wheel -o dist`) and give it as a source:
`pip install --find-links ../../dist .`.

```python
import qjswasm

result = qjswasm.run(["script.js"], root="some/directory")  # Result(code, stdout, stderr)
```

An error of the script is what `qjs` does on the command line: a message on `stderr` and the code 1 (`proc_exit`, not a trap).
`std` and `os` are modules of QuickJS-ng under the names `qjs:std` and `qjs:os` (`import * as std from "qjs:std"`).

`setup.py` is the whole integration:

```python
from setuptools import setup
from wasmext import wasmize

setup(ext_modules=wasmize("src/qjswasm/*.wasm", parts=4))
```

## The WebAssembly module

`_qjs.wasm` is in the repository; `build_wasm.py` makes it again (`uv run --group wasm python examples/quickjs/build_wasm.py` from the
root of the repository, with `zig cc` from the `ziglang` package as `wasm32-wasi`). It clones the tag in the script and uses the sources
as they are, with the flags of the WASI build of its `CMakeLists.txt`. The module is the `qjs` command: it exports `_start` and imports 23
calls of `wasi_snapshot_preview1`.

QuickJS-ng is a fork of the QuickJS of Fabrice Bellard and Charlie Gordon; both licenses (MIT) are in [NOTICE.md](../../NOTICE.md).
