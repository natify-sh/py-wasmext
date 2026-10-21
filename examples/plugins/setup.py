from setuptools import setup

from wasmext import natify

# src/plugindemo/_host.wasm, _double.wasm and _negate.wasm become the extension modules plugindemo._host, ._double and ._negate
setup(ext_modules=natify("src/plugindemo/*.wasm"))
