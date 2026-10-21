"""A host and two plugins, as native extensions, that share one table. `_host` has a table of 8 slots with a function in slot 0;
`_double` and `_negate` import that table and put functions of their own in it. A call from one module into a function of
another goes through the table, as a C call: nothing of it passes through Python.

>>> import plugindemo
>>> host, double, negate = plugindemo.make()
>>> host.call(0, 41)      # slot 0: the host's own `inc`
42
>>> host.call(1, 21)      # slot 1: `double`, put there by the plugin _double
42
>>> double.call(2, 5)     # a plugin calls the slot of the other plugin
-5
"""

from __future__ import annotations

from . import _double, _host, _negate  # the extensions made from _host.wasm, _double.wasm and _negate.wasm

__all__ = ["make", "standalone"]


def make() -> tuple[_host.Instance, _double.Instance, _negate.Instance]:
    """The host and the two plugins that use its table."""
    host = _host.Instance()
    table = host["table"]  # a _host.Table: the table of the host, for others to import
    return host, _double.Instance({"env": {"table": table}}), _negate.Instance({"env": {"table": table}})


def standalone() -> tuple[_double.Table, _host.Instance, _double.Instance]:
    """A table that no module owns, made here, with a function of the host put in it from Python (`Table.set`), and a plugin on it."""
    table = _double.Table(4, 16)  # the Table of the extension _double (any module that shares tables has one)
    host = _host.Instance()
    plugin = _double.Instance({"env": {"table": table}})  # the plugin puts `double` in slot 1
    table.set(0, host.inc)  # and Python puts the host's `inc` in slot 0
    return table, host, plugin
