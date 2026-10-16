"""Turn WebAssembly modules into native CPython extensions (via wasm2c)."""

from ._gen import GenError, Glue, generate, mangle
from ._wasm import Export, FuncType, GlobalType, Import, Limits, Module, TableType, ValType, WasmError, parse

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
    "ValType",
    "WasmError",
    "generate",
    "mangle",
    "parse",
]
