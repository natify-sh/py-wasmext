# Third-party material

- `tests/data/simple.wasm` and `tests/data/coremark.wasm` are the test modules of
  [vshymanskyy/wasm2mpy](https://github.com/vshymanskyy/wasm2mpy) (`test/`), copied unchanged. wasm2mpy is MIT
  licensed; its licence text is below. The same goes for `tests/data/wasm2mpy/` (seven of them, built there from
  [wasm3/embedded-wasm-apps](https://github.com/wasm3/embedded-wasm-apps)).
- `tests/data/pywasm3/*.wasm` and `collatz.wat` are from the examples of [wasm3/pywasm3](https://github.com/wasm3/pywasm3)
  (`examples/wasm/`), copied unchanged; pywasm3 is MIT licensed (Copyright (c) 2019 Volodymyr Shymanskyy), like wasm2mpy above.
- `tests/data/wasmhost/imports.wasm` is the module of `examples/imports.py` of
  [py-wasmhost](https://github.com/ballistics-lab/py-wasmhost) written out as a file.
- The C that wasmext writes (`<name>_wasmext/`, which can end up in your sdist) contains the runtime sources of `wasm2c`
  (`wasm-rt*.c`, `.h`, `.inc`) and the output of `wasm2c` itself, from [WABT](https://github.com/WebAssembly/wabt) (the
  wabt-package): Apache-2.0, Copyright the WebAssembly Community Group participants. Their licence text is in the wabt-package
  and in WABT's repository; keep it with copies of those files.

## wasm2mpy licence

MIT License

Copyright (c) 2024 Volodymyr Shymanskyy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## CoreMark

`examples/coremark/src/coremark/_core.wasm` is built from [CoreMark](https://github.com/eembc/coremark) of EEMBC
(Apache License 2.0) by `examples/coremark/build_wasm.py`; `examples/coremark/port/` is derived from its `barebones` port.

## Lua

`examples/lua/src/luawasm/_lua.wasm` is Lua 5.4.6, built to WASI by the [lua-wasi](https://github.com/nalgeon/lua-wasi) project and taken
as it is from the npm package `@antonz/lua-wasi` (MIT License). Lua is

Copyright (C) 1994-2023 Lua.org, PUC-Rio.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR
ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH
THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## QuickJS

`examples/quickjs/src/qjswasm/_qjs.wasm` is built by `examples/quickjs/build_wasm.py` from [QuickJS-ng](https://github.com/quickjs-ng/quickjs)
v0.17.0 (MIT License), a fork of QuickJS. Its LICENSE, as it is:

Copyright (c) 2017-2026 Fabrice Bellard
Copyright (c) 2017-2024 Charlie Gordon
Copyright (c) 2023-2026 Ben Noordhuis
Copyright (c) 2023-2026 Saúl Ibarra Corretgé

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

## WABT

`examples/wabt/src/wabtwasm/_wat2wasm.wasm` and `_wasm2c.wasm` are built by `examples/wabt/build_wasm.py` from [WABT](https://github.com/WebAssembly/wabt)
1.0.42 (Apache License 2.0; the text is in the repository of WABT), and `examples/wabt/src/wabtwasm/runtime/` holds the files `wasm-rt*` of its `wasm2c/`
directory, as they are. WABT's `picosha2` (MIT License, Copyright (C) 2017 okdshin) is compiled into the tools, in a copy without the function for `std::ifstream`.
