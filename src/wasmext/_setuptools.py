# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# (the class below is derived from the build_ext of whichever setuptools is there, which has no types)
"""setuptools hooks (entry points of wasmext): the wheel of an abi3 extension is tagged for it without any setting, and the files
of a module whose C is split are compiled at the same time.

`wasmize()` marks an abi3 extension with `py_limited_api` and the Py_LIMITED_API macro; setuptools names the file `.abi3.so`
but tags the wheel `cp311-cp311` unless `bdist_wheel --py-limited-api=cp311` says otherwise. This does that, for a project
that has not said anything itself (a `[tool.distutils.bdist_wheel]` setting wins).
"""

from __future__ import annotations

import os
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ._wasmize import LIMITED_API_VERSION, wasmize


def wheel_tag() -> str:
    """The `cpXY` of the oldest CPython the abi3 extensions support."""
    value = int(LIMITED_API_VERSION, 16)
    return f"cp{(value >> 24) & 0xFF}{(value >> 16) & 0xFF}"


def _is_abi3(ext: Any) -> bool:
    macros: list[Any] = getattr(ext, "define_macros", None) or []
    return bool(getattr(ext, "py_limited_api", False)) and ("Py_LIMITED_API", LIMITED_API_VERSION) in macros


# [tool.wasmext.wasmize] of pyproject.toml: the arguments of wasmize(), by the names that pyproject.toml has (kebab-case)
_WASMIZE_KEYS = {
    "module-list": "module_list",
    "exclude": "exclude",
    "build-dir": "build_dir",
    "force": "force",
    "quiet": "quiet",
    "stubs": "stubs",
    "limited-api": "limited_api",
    "guard-pages": "guard_pages",
    "parts": "parts",
}


def pyproject_calls(root: Path) -> list[dict[str, Any]]:
    """The calls of `wasmize()` that `pyproject.toml` in `root` asks for: `[tool.wasmext.wasmize]`, or several as `[[tool.wasmext.wasmize]]`,
    as the keyword arguments of the function. An empty list where the file or the table is not there."""
    path = root / "pyproject.toml"
    if not path.is_file():
        return []
    with path.open("rb") as f:
        table = tomllib.load(f).get("tool", {}).get("wasmext")
    if table is None:
        return []
    if not isinstance(table, dict):
        raise TypeError(f"{path}: [tool.wasmext] must be a table")
    for key in table:
        if key != "wasmize":
            raise ValueError(
                f"{path}: [tool.wasmext.{key}] is not something wasmext knows (it has [tool.wasmext.wasmize])"
            )
    wanted = table.get("wasmize", [])
    entries: list[Any] = [wanted] if isinstance(wanted, dict) else wanted
    calls: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError(f"{path}: [tool.wasmext.wasmize] must be a table, or an array of tables")
        unknown = sorted(set(entry) - set(_WASMIZE_KEYS))
        if unknown:
            raise ValueError(
                f"{path}: [tool.wasmext.wasmize] has no key {unknown[0]!r} (the keys are {', '.join(sorted(_WASMIZE_KEYS))})"
            )
        if "module-list" not in entry:
            raise ValueError(
                f"{path}: [tool.wasmext.wasmize] needs module-list (the .wasm files, as a glob pattern or a list of them)"
            )
        calls.append({_WASMIZE_KEYS[key]: value for key, value in entry.items()})
    return calls


def _add_extensions_from_pyproject(dist: Any) -> None:
    """Put the extensions of `[tool.wasmext.wasmize]` into `dist.ext_modules`, after those that a `setup.py` gave (it is not needed;
    one that has an extension of its own, a hand-written C one, goes with the table)."""
    root = Path(getattr(dist, "src_root", None) or os.getcwd())
    calls = pyproject_calls(root)
    if not calls:
        return
    extensions: list[Any] = list(getattr(dist, "ext_modules", None) or [])
    if any(getattr(e, "_wasmext_made", False) for e in extensions):
        raise ValueError(
            "setup.py calls wasmize() and pyproject.toml has [tool.wasmext.wasmize]: use one of them "
            "(an extension of another kind in setup.py goes with the table)"
        )
    for call in calls:
        extensions.extend(wasmize(**call))
    dist.ext_modules = extensions


def finalize_distribution_options(dist: Any) -> None:
    _add_extensions_from_pyproject(dist)
    extensions: list[Any] = getattr(dist, "ext_modules", None) or []
    if any(getattr(e, "_wasmext_parallel", False) for e in extensions) and "build_ext" not in dist.cmdclass:
        dist.cmdclass["build_ext"] = parallel_build_ext(dist.get_command_class("build_ext"))
    marked = [e for e in extensions if _is_abi3(e)]
    if marked:
        dist.get_option_dict("bdist_wheel").setdefault("py_limited_api", ("wasmext", wheel_tag()))


def _jobs(command: Any, count: int) -> int:
    """How many files to compile at once: WASMEXT_JOBS, else `build_ext -j`, else the number of processors."""
    env = os.environ.get("WASMEXT_JOBS")
    wanted = (
        int(env) if env and env.isdigit() else int(getattr(command, "parallel", None) or 0) or (os.cpu_count() or 1)
    )
    return max(1, min(wanted, count))


def parallel_build_ext(base: type) -> type:
    """A `build_ext` that compiles the sources of an extension from `wasmize()` that is split into files at the same time.

    setuptools compiles the sources of one extension one after the other. Here the sources are compiled first, in a pool of
    threads (the compilers are processes), and the extension is then built from the objects, which only links.
    """

    class WasmextBuildExt(base):  # type: ignore[misc, valid-type]
        def build_extension(self, ext: Any) -> None:
            sources = list(ext.sources or [])
            if not getattr(ext, "_wasmext_parallel", False) or len(sources) < 2:
                return super().build_extension(ext)
            try:
                from setuptools._distutils.dep_util import newer_group  # type: ignore[import-not-found]
            except ImportError:  # pragma: no cover - an old setuptools
                from distutils.dep_util import newer_group  # type: ignore[import-not-found, no-redef]
            if not (self.force or newer_group([*sources, *ext.depends], self.get_ext_fullpath(ext.name), "newer")):
                return super().build_extension(ext)  # up to date: it says so itself
            macros = list(ext.define_macros or []) + [(undef,) for undef in ext.undef_macros or []]

            def compile_one(source: str) -> list[str]:
                return self.compiler.compile(
                    [source],
                    output_dir=self.build_temp,
                    macros=macros,
                    include_dirs=ext.include_dirs,
                    debug=self.debug,
                    extra_postargs=ext.extra_compile_args or [],
                    depends=ext.depends,
                )

            first = compile_one(sources[0])  # alone: a compiler (MSVC) sets itself up on its first use
            with ThreadPoolExecutor(max_workers=_jobs(self, len(sources) - 1)) as pool:
                rest = list(pool.map(compile_one, sources[1:]))
            objects = [*first, *(obj for objs in rest for obj in objs)]
            saved = (ext.sources, ext.extra_objects, self.force)
            ext.sources, ext.extra_objects, self.force = [], [*(ext.extra_objects or []), *objects], True
            try:
                super().build_extension(ext)  # nothing to compile now: it links
            finally:
                ext.sources, ext.extra_objects, self.force = saved

    return WasmextBuildExt
