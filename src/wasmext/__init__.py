"""Turn WebAssembly modules into native CPython extensions (via wasm2c)."""

from ._gen import GenError, Glue, generate, mangle
from ._natify import _version, natify  # pyright: ignore[reportPrivateUsage]
from ._toolchain import Toolchain, find_toolchain
from ._wasm import (
    Export,
    FuncType,
    GlobalType,
    Import,
    Limits,
    Module,
    TableType,
    ValType,
    WasiFlavor,
    WasmError,
    parse,
    wasi_flavor,
)

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
    "WasiFlavor",
    "WasmError",
    "__version__",
    "find_toolchain",
    "generate",
    "mangle",
    "natify",
    "parse",
    "wasi_flavor",
]
