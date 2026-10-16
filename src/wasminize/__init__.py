"""Turn WebAssembly modules into native CPython extensions (via wasm2c)."""

from ._wasm import Export, FuncType, GlobalType, Import, Limits, Module, TableType, ValType, WasmError, parse

__all__ = [
    "Export",
    "FuncType",
    "GlobalType",
    "Import",
    "Limits",
    "Module",
    "TableType",
    "ValType",
    "WasmError",
    "parse",
]
