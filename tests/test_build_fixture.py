"""The fixture `build_extension` builds as the product does (the tests build what the product builds)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest
import setuptools

from wasmext._natify import fusedwasi_version_macro  # pyright: ignore[reportPrivateUsage]

from .conftest import DATA


def test_build_extension_passes_the_version_of_fusedwasi(
    build_extension: Callable[..., ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    fused = fusedwasi_version_macro()
    assert fused is not None
    seen: list[str] = []  # the compiler's arguments, or the macros of the setuptools Extension
    run, extension = subprocess.run, setuptools.Extension

    def spy_run(args: Any, *a: Any, **k: Any) -> Any:
        seen.extend(str(x) for x in args)
        return run(args, *a, **k)  # pyright: ignore[reportUnknownVariableType]

    def spy_extension(*a: Any, **k: Any) -> Any:
        seen.extend(f"-D{n}={v}" for n, v in k.get("define_macros", ()))
        return extension(*a, **k)

    monkeypatch.setattr(subprocess, "run", spy_run)
    monkeypatch.setattr(setuptools, "Extension", spy_extension)
    build_extension(DATA / "caller_nomem.wat", "fusedwasi_version_probe")
    assert f"-D{fused[0]}={fused[1]}" in seen
