"""`import wasmimport; wasmimport.install()` lets `import` find `.wasm` files and make extensions of them, as `pyximport` does for `.pyx`.

The work is done by `wasmext`: see `wasmext._importer` (a development tool; it runs a C compiler on import).
"""

from wasmext._importer import WasmFinder, WasmImportLoader, clean, install, uninstall

__all__ = ["WasmFinder", "WasmImportLoader", "clean", "install", "uninstall"]
