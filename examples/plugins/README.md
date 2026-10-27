# wasmext-example-plugins

A host and two plugins, WebAssembly modules built into native CPython extensions, that **share one table** (the pattern of dynamic linking).
`_host` has a `funcref` table of 8 slots with a function in slot 0 and a `call(slot, x)` that calls a slot. `_double` and `_negate` import that
table and put functions of their own in it (`double` in slot 1, `negate` in slot 2, and `boom`, which traps, in slot 3). A call from a module into
a function of another goes through the table as a C call: nothing of it passes through Python, and a trap in a plugin comes back to the caller as its
own `Trap`.

```sh
# a C compiler is needed; wasmext is not on PyPI yet, so uv takes it from the root of the repository
# (`[tool.uv.sources]` in pyproject.toml). This is the way to build the example:
uv sync --reinstall      # --reinstall: build the extensions again (uv keeps what it built before)
uv run python -m plugindemo
uv run pytest
```

```python
host = _host.Instance(_host.Store())
table = host["table"]  # a _host.Table: the table of the host, for others to import
double = _double.Instance(_double.Store(), imports={"env": {"table": table}})  # the plugin puts `double` in slot 1
host.call(1, 21)  # 42: the host calls the function of the plugin through the table
```

A table does not need a host module. The extension of any module that shares tables has the class `Table`, made by the glue of that module (not by
`wasmext` while it runs), and `Table(initial, maximum=None)` makes one that no module owns, with `size`, `maximum`, `grow`, `get` and `set`:

```python
table = _double.Table(4, 16)
plugin = _double.Instance(_double.Store(), imports={"env": {"table": table}})
table.set(0, host.inc)  # Python puts a function of an instance in a slot
table.grow(2)  # the plugin sees 6 slots
```

Only a function of a module that shares tables (it imports or exports a table, or is built with the option `share_tables`: `natify(share_tables=True)`, `share-tables = true` in `pyproject.toml`, `--share-tables`) can be put in a table: a trap in it has to come back through the table to
the caller. `table.get(i)` gives the function in a slot as a `Function` (callable, with `signature` and `name`); the `name` is that of the export, and `None` for a function that an `elem` segment put there (wasm2c writes a wrapper of its own in the table, which is no export), unless the linker gave the wrapper the address of the export (identical code folding, seen with MSVC on x86 and ARM64), and then it is named. See "Linking instances" in the [README](../../README.md) and "Tables between instances" in [DESIGN.md](../../docs/DESIGN.md).

The modules are written in the text format (`wat/`); `build_wasm.py` makes the `.wasm` files with `wat2wasm` of the wabt-package
(`uv run python examples/plugins/build_wasm.py` from the root of the repository). The `.wasm` and the `.pyi` stubs are in the repository.
