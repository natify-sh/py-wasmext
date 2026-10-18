from setuptools import setup

from wasmext import wasmize

# src/linkdemo/_counter.wasm and _app.wasm become the extension modules linkdemo._counter and linkdemo._app
setup(ext_modules=wasmize("src/linkdemo/*.wasm"))
