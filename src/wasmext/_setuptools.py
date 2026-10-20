# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# (the class below is derived from the build_ext of whichever setuptools is there, which has no types)
"""setuptools hooks (entry points of wasmext): the wheel of an abi3 extension is tagged for it without any setting, and the files
of a module whose C is split are compiled at the same time.

`natify()` marks an abi3 extension with `py_limited_api` and the Py_LIMITED_API macro; setuptools names the file `.abi3.so`
but tags the wheel `cp311-cp311` unless `bdist_wheel --py-limited-api=cp311` says otherwise. This does that, for a project
that has not said anything itself (a `[tool.distutils.bdist_wheel]` setting wins).
"""

from __future__ import annotations

import os
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ._natify import LIMITED_API_VERSION, natify


def wheel_tag() -> str:
    """The `cpXY` of the oldest CPython the abi3 extensions support."""
    value = int(LIMITED_API_VERSION, 16)
    return f"cp{(value >> 24) & 0xFF}{(value >> 16) & 0xFF}"


def _is_abi3(ext: Any) -> bool:
    macros: list[Any] = getattr(ext, "define_macros", None) or []
    return bool(getattr(ext, "py_limited_api", False)) and ("Py_LIMITED_API", LIMITED_API_VERSION) in macros


# [tool.wasmext.ext-modules] of pyproject.toml: the arguments of natify(), by the names that pyproject.toml has (kebab-case)
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


# ... and what is added to each extension that the call makes, as `Extension()` has it (the flags, the macros, the libraries)
_EXTENSION_KEYS = {
    "extra-compile-args": "extra_compile_args",
    "extra-link-args": "extra_link_args",
    "define-macros": "define_macros",
    "undef-macros": "undef_macros",
    "include-dirs": "include_dirs",
    "libraries": "libraries",
    "library-dirs": "library_dirs",
}


def _macro(value: Any) -> tuple[str, str | None]:
    """A macro as the table says it: "NAME", "NAME=value", or ["NAME", "value"]; `Extension` wants (name, value or None)."""
    if isinstance(value, str):
        name, _, text = value.partition("=")
        return (name, text if "=" in value else None)
    if isinstance(value, list) and len(value) == 2 and all(isinstance(v, str) for v in value):  # pyright: ignore[reportUnknownArgumentType]
        return (value[0], value[1])
    raise TypeError(f"define-macros: {value!r} is not NAME, NAME=value or [NAME, value]")


# the type that each key wants: "str", "bool", "int", or "strs" (a string, or a list of strings)
_KEY_TYPES = {
    "module-list": "strs",
    "exclude": "strs",
    "build-dir": "str",
    "force": "bool",
    "quiet": "bool",
    "stubs": "bool",
    "limited-api": "bool",
    "guard-pages": "bool",
    "parts": "int",
    "extra-compile-args": "list",
    "extra-link-args": "list",
    "undef-macros": "list",
    "include-dirs": "list",
    "libraries": "list",
    "library-dirs": "list",
}


def _check_value(path: Path, key: str, value: Any) -> None:
    """A value of the wrong type is an error that names the key, not a TypeError from the depths of natify() (or, for a string where a list
    is wanted, a list of its characters)."""
    kind = _KEY_TYPES.get(key)
    where = f"{path}: [tool.wasmext.ext-modules] {key}"
    strings = isinstance(value, list) and all(isinstance(v, str) for v in value)  # pyright: ignore[reportUnknownVariableType]
    if kind == "str" and not isinstance(value, str):
        raise TypeError(f"{where} must be a string, not {value!r}")
    if kind == "bool" and not isinstance(value, bool):
        raise TypeError(f"{where} must be true or false, not {value!r}")
    if kind == "int" and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
        raise TypeError(f"{where} must be a whole number of at least 1, not {value!r}")
    if kind == "strs" and not (isinstance(value, str) or strings):
        raise TypeError(f"{where} must be a string or a list of strings, not {value!r}")
    if kind == "list" and not strings:
        raise TypeError(f"{where} must be a list of strings, not {value!r}")
    if key == "define-macros" and not isinstance(value, list):
        raise TypeError(f"{where} must be a list, not {value!r}")


def pyproject_calls(root: Path) -> list[dict[str, Any]]:
    """The calls of `natify()` that `pyproject.toml` in `root` asks for: `[tool.wasmext.ext-modules]`, or several as `[[tool.wasmext.ext-modules]]`,
    as the keyword arguments of the function, and under the key "extension" what is added to the extensions it makes. An empty list where
    the file or the table is not there."""
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
        if key != "ext-modules":
            raise ValueError(
                f"{path}: [tool.wasmext.{key}] is not something wasmext knows (it has [tool.wasmext.ext-modules])"
            )
    wanted = table.get("ext-modules", [])
    entries: list[Any] = [wanted] if isinstance(wanted, dict) else wanted
    calls: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError(f"{path}: [tool.wasmext.ext-modules] must be a table, or an array of tables")
        unknown = sorted(set(entry) - set(_WASMIZE_KEYS) - set(_EXTENSION_KEYS))
        if unknown:
            known = sorted([*_WASMIZE_KEYS, *_EXTENSION_KEYS])
            raise ValueError(
                f"{path}: [tool.wasmext.ext-modules] has no key {unknown[0]!r} (the keys are {', '.join(known)})"
            )
        if "module-list" not in entry:
            raise ValueError(
                f"{path}: [tool.wasmext.ext-modules] needs module-list (the .wasm files, as a glob pattern or a list of them)"
            )
        for key, value in entry.items():  # pyright: ignore[reportUnknownVariableType]
            _check_value(path, key, value)  # pyright: ignore[reportUnknownArgumentType]
        call = {_WASMIZE_KEYS[key]: value for key, value in entry.items() if key in _WASMIZE_KEYS}
        if isinstance(call.get("exclude"), str):
            call["exclude"] = [call["exclude"]]  # a lone pattern: not the characters of a string
        extension = {_EXTENSION_KEYS[key]: value for key, value in entry.items() if key in _EXTENSION_KEYS}
        if "define_macros" in extension:
            extension["define_macros"] = [_macro(m) for m in extension["define_macros"]]
        if extension:
            call["extension"] = extension
        calls.append(call)
    return calls


def _add_extensions_from_pyproject(dist: Any) -> None:
    """Put the extensions of `[tool.wasmext.ext-modules]` into `dist.ext_modules`, after those that a `setup.py` gave (it is not needed;
    one that has an extension of its own, a hand-written C one, goes with the table)."""
    root = Path(getattr(dist, "src_root", None) or os.getcwd())
    calls = pyproject_calls(root)
    if not calls:
        return
    extensions: list[Any] = list(getattr(dist, "ext_modules", None) or [])
    if any(getattr(e, "_wasmext_made", False) for e in extensions):
        raise ValueError(
            "setup.py calls natify() and pyproject.toml has [tool.wasmext.ext-modules]: use one of them "
            "(an extension of another kind in setup.py goes with the table)"
        )
    for call in calls:
        settings = call.pop("extension", {})
        for extension in natify(**call):
            for attribute, value in settings.items():
                setattr(extension, attribute, [*(getattr(extension, attribute, None) or []), *value])
            extensions.append(extension)
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
    """A `build_ext` that compiles the sources of an extension from `natify()` that is split into files at the same time.

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
