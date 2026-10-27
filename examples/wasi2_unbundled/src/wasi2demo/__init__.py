"""Two C programs built as WASI 0.2 components, their core modules taken out with `wasm-tools component unbundle`, turned into extensions by
wasmext, and run with a host of WASI 0.2 written in Python (`host.Host`): `_hello` prints a line, `_sock` connects to a TCP server.

>>> from io import BytesIO
>>> from wasi2demo import Host, _hello, run
>>> out = BytesIO()
>>> run(_hello, Host(stdout=out)), out.getvalue()
(1, b'hello from wasip2\\n')
"""

from __future__ import annotations

from typing import Any

from .host import Host

__all__ = ["Host", "run"]


def run(module: Any, host: Host) -> int:
    """Make an instance of the extension `module` with the imports of `host` and call `wasi:cli/run@0.2.12#run`: 0 is `ok`, 1 is `err`
    (the `main` of the program returned something other than 0; the number itself does not come out of `run`)."""
    instance = module.Instance(module.Store(), imports=host.imports())
    host.bind(instance)
    return getattr(instance, "wasi:cli/run@0.2.12#run")()
