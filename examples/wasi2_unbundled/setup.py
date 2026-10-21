from setuptools import setup

from wasmext import natify

# src/wasi2demo/_hello.wasm and _sock.wasm become the extension modules wasi2demo._hello and wasi2demo._sock
setup(ext_modules=natify("src/wasi2demo/*.wasm"))
