"""CPython 3.15 built for WASI 0.2, as a native extension, on a host written in Python: filesystem, name lookup, TCP (and TLS, which is in the module)."""

from __future__ import annotations

import importlib
import importlib.resources
import io
from collections.abc import Mapping, Sequence

from .fshost import Exit, FsHost
from .nethost import NetHost

__all__ = ["Exit", "FsHost", "NetHost", "run"]


def run(
    arguments: Sequence[str],
    preopens: Sequence[tuple[str, str]],
    *,
    environment: Mapping[str, str] | None = None,
    stdout: io.RawIOBase | io.BufferedIOBase | None = None,
    stderr: io.RawIOBase | io.BufferedIOBase | None = None,
) -> int:
    """Run `python ARGUMENTS...`; `preopens` is [(directory of the host, name for the program)]. Returns the exit code."""
    from wasmext import parse

    from . import _python  # type: ignore[attr-defined]

    host = NetHost(["python", *arguments], dict(environment or {}), list(preopens), stdout=stdout, stderr=stderr)
    given, table = host.imports(), host.table()
    imports: dict[str, dict[str, object]] = {}
    for item in parse(importlib.resources.files(__package__).joinpath("_python.wasm").read_bytes()).imports:
        key = (item.module.split("@")[0], item.name)
        function = table.get(key) or given.get(item.module, {}).get(item.name)
        if item.name.startswith("[resource-drop]"):
            function = host.drop
        if function is None:
            label = f"{key[0]}.{item.name}"

            def function(*_a: int, label: str = label) -> None:  # type: ignore[misc]
                raise NotImplementedError(label)

        imports.setdefault(item.module, {})[item.name] = function
    instance = _python.Instance(imports)
    host.bind(instance)
    try:
        return int(getattr(instance, "wasi:cli/run@0.2.12#run")())
    except Exit as e:
        return e.code
