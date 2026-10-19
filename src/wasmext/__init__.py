"""Turn WebAssembly modules into native CPython extensions (via wasm2c)."""

from ._gen import GenError, Glue, generate, mangle
from ._toolchain import Toolchain, find_toolchain
from ._wasm import Export, FuncType, GlobalType, Import, Limits, Module, TableType, ValType, WasmError, parse
from ._wasmize import _version, wasmize  # pyright: ignore[reportPrivateUsage]

__version__ = _version()

__all__ = [
    "Export",
    "FuncType",
    "GenError",
    "GlobalType",
    "Glue",
    "Import",
    "Limits",
    "Module",
    "TableType",
    "Toolchain",
    "ValType",
    "WasmError",
    "__version__",
    "find_toolchain",
    "generate",
    "mangle",
    "parse",
    "wasmize",
]
