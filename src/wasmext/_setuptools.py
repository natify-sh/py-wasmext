"""setuptools hooks (entry points of wasmext): the wheel of an abi3 extension is tagged for it without any setting.

`wasmize()` marks an abi3 extension with `py_limited_api` and the Py_LIMITED_API macro; setuptools names the file `.abi3.so`
but tags the wheel `cp311-cp311` unless `bdist_wheel --py-limited-api=cp311` says otherwise. This does that, for a project
that has not said anything itself (a `[tool.distutils.bdist_wheel]` setting wins).
"""

from __future__ import annotations

from typing import Any

from ._wasmize import LIMITED_API_VERSION


def wheel_tag() -> str:
    """The `cpXY` of the oldest CPython the abi3 extensions support."""
    value = int(LIMITED_API_VERSION, 16)
    return f"cp{(value >> 24) & 0xFF}{(value >> 16) & 0xFF}"


def _is_abi3(ext: Any) -> bool:
    macros: list[Any] = getattr(ext, "define_macros", None) or []
    return bool(getattr(ext, "py_limited_api", False)) and ("Py_LIMITED_API", LIMITED_API_VERSION) in macros


def finalize_distribution_options(dist: Any) -> None:
    extensions: list[Any] = getattr(dist, "ext_modules", None) or []
    marked = [e for e in extensions if _is_abi3(e)]
    if marked:
        dist.get_option_dict("bdist_wheel").setdefault("py_limited_api", ("wasmext", wheel_tag()))
