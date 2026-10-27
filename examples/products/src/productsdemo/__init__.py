"""One wheel, two products of wasmext that are not Python extensions: `engine_ctypes` (a WebAssembly module as a shared library,
used through ctypes) and `hello` (a WASI program as a native executable).

>>> from productsdemo import engine_ctypes
>>> engine_ctypes.Instance(engine_ctypes.Store(), imports={"env": {"log": print}}).add(2, 3)
5
"""

import sys
from pathlib import Path

HELLO = Path(__file__).with_name("hello.exe" if sys.platform == "win32" else "hello")
