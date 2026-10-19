from setuptools import setup

from wasmext import wasmize

# src/qjswasm/_qjs.wasm becomes the extension module qjswasm._qjs. The C that wasm2c writes for it is in 4 files, compiled at the
# same time.
setup(ext_modules=wasmize("src/qjswasm/*.wasm", parts=4))
