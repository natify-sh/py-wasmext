from setuptools import setup

from wasmext import wasmize

# src/coremark/_core.wasm becomes the extension module coremark._core
setup(ext_modules=wasmize("src/coremark/*.wasm", limited_api=True))  # the stable ABI: one wheel per platform
