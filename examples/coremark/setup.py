from setuptools import setup

from wasmext import natify

# src/coremark/_core.wasm becomes the extension module coremark._core
setup(ext_modules=natify("src/coremark/*.wasm"))  # abi3 where the Python has a stable ABI, else native
