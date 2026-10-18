"""Two WebAssembly modules that use each other, as native extensions: `_counter` has a variable, a function and a memory,
`_app` imports them. Nothing goes through Python on a call from one to the other.

>>> import linkdemo
>>> counter, app = linkdemo.make()
>>> app.tick()                  # app calls counter.bump(1) directly, and says what it got through `log`
1
>>> counter.count               # the variable of counter, written by app's call
1
"""

from __future__ import annotations

from collections.abc import Callable

from . import _app, _counter  # the extensions made from _counter.wasm and _app.wasm

__all__ = ["make"]


def make(log: Callable[[int], None] = print) -> tuple[_counter.Instance, _app.Instance]:
    """A counter and an app that uses it. `log` is what only Python can give the app (the module cannot print)."""
    counter = _counter.Instance()
    # The shelf "env" of the app: everything that counter exports (the memory, the variable, the function), and log from here.
    # The later key wins, so a log of the counter, if it had one, would be replaced by this one.
    app = _app.Instance({"env": {**counter.__exports__, "log": log}})
    return counter, app
