from setuptools import setup

from wasmext import natify

# src/wasi2python/_python.wasm (made by build_wasm.py) becomes the extension module wasi2python._python
setup(ext_modules=natify("src/wasi2python/*.wasm"))
