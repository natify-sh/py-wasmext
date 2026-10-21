from setuptools import setup

from wasmext import natify

# src/luawasm/_lua.wasm becomes the extension module luawasm._lua. The C that wasm2c writes for it is in 8 files, compiled at the
# same time: a few seconds instead of the half minute that one file takes.
setup(ext_modules=natify("src/luawasm/*.wasm", parts=8))
