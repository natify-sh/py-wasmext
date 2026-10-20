# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# (the class below is derived from the build_ext of whichever setuptools is there, which has no types)
"""setuptools hooks (entry points of wasmext): the wheel of an abi3 extension is tagged for it without any setting, and the files
of a module whose C is split are compiled at the same time.

`natify()` marks an abi3 extension with `py_limited_api` and the Py_LIMITED_API macro; setuptools names the file `.abi3.so`
but tags the wheel `cp311-cp311` unless `bdist_wheel --py-limited-api=cp311` says otherwise. This does that, for a project
that has not said anything itself (a `[tool.distutils.bdist_wheel]` setting wins).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ._natify import LIMITED_API_VERSION, PRODUCTS, natify


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
    "guard-pages": "guard_pages",
    "parts": "parts",
    "product": "product",
}
# ... and what holds for the whole project, because the wheel has one tag: [tool.wasmext] limited-api
_PROJECT_KEYS = {"limited-api": "limited_api"}


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
    "guard-pages": "guard",
    "parts": "int",
    "product": "product",
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
    where = f"{path}: [tool.wasmext] {key}" if key in _PROJECT_KEYS else f"{path}: [tool.wasmext.ext-modules] {key}"
    strings = isinstance(value, list) and all(isinstance(v, str) for v in value)  # pyright: ignore[reportUnknownVariableType]
    if kind == "product" and value not in PRODUCTS:
        raise ValueError(f"{where} must be one of {', '.join(PRODUCTS)}, not {value!r}")
    if kind == "guard":  # true/false, or a table of architectures
        table = isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, bool) for k, v in value.items())  # pyright: ignore[reportUnknownVariableType]
        if not (isinstance(value, bool) or table):
            raise TypeError(
                f"{where} must be true or false, or a table of architectures to true or false (x86 = false), not {value!r}"
            )
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
        if key != "ext-modules" and key not in _PROJECT_KEYS:
            raise ValueError(
                f"{path}: [tool.wasmext.{key}] is not something wasmext knows (it has [tool.wasmext.ext-modules] and, for the whole project, "
                f"{', '.join(_PROJECT_KEYS)})"
            )
    project = {_PROJECT_KEYS[key]: value for key, value in table.items() if key in _PROJECT_KEYS}
    for key, value in table.items():
        if key in _PROJECT_KEYS:
            _check_value(path, key, value)
    wanted = table.get("ext-modules", [])
    entries: list[Any] = [wanted] if isinstance(wanted, dict) else wanted
    calls: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError(f"{path}: [tool.wasmext.ext-modules] must be a table, or an array of tables")
        if "limited-api" in entry:
            raise ValueError(
                f"{path}: limited-api is one setting for the whole project (the wheel has one tag): put it in [tool.wasmext], not in an entry of ext-modules"
            )
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
        call.update(project)
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
    if os.environ.get(
        "WASMEXT_NO_PYPROJECT"
    ):  # the command line builds what it was asked, not what the table of the project says
        return
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


def wheel_without_python(base: type) -> type:
    """A `bdist_wheel` that tags the wheel of a package whose compiled files are libraries and programs, none of them a Python extension: any Python 3
    (`py3-none-<platform>`), not the interpreter that built it."""

    class WasmextBdistWheel(base):  # type: ignore[misc, valid-type]
        def get_tag(self) -> tuple[str, str, str]:
            _impl, _abi, platform_tag = super().get_tag()
            return "py3", "none", platform_tag

    return WasmextBdistWheel


def _same_abi_for_the_wheel(extensions: list[Any]) -> None:
    """A wheel has one tag, so its Python extensions are all abi3 or all native. When what was asked, or what the others are, does not allow abi3 for all of them, the
    modules of wasmext that took the default are made native (the tag is then the normal one); two settings that contradict each other are an error."""
    ours = [e for e in extensions if getattr(e, "_wasmext_made", False) and not getattr(e, "_wasmext_product", None)]
    others = [e for e in extensions if e not in ours and not getattr(e, "_wasmext_product", None)]
    asked = {e._wasmext_limited_api for e in ours if getattr(e, "_wasmext_limited_api", None) is not None}
    if len(asked) > 1:
        raise ValueError(
            "limited_api is True for some modules of this project and False for others: a wheel has one tag, so it is one setting for all of them"
        )
    foreign = next((e for e in others if not _is_abi3(e)), None)
    if True in asked and foreign is not None:
        raise ValueError(
            f"limited_api=True, but the extension {foreign.name} is not abi3: the wheel would be tagged for one interpreter"
        )
    if (False in asked or foreign is not None) and any(_is_abi3(e) for e in ours):
        for e in ours:  # the others are built native already; these took the default, so they follow
            if _is_abi3(e):
                e.py_limited_api = False
                e.define_macros = [m for m in (e.define_macros or []) if m[0] != "Py_LIMITED_API"]


def finalize_distribution_options(dist: Any) -> None:
    _add_extensions_from_pyproject(dist)
    extensions: list[Any] = getattr(dist, "ext_modules", None) or []
    _same_abi_for_the_wheel(extensions)
    if (
        extensions
        and all(getattr(e, "_wasmext_product", None) for e in extensions)
        and "bdist_wheel" not in dist.cmdclass
    ):
        with contextlib.suppress(Exception):  # no bdist_wheel (no wheel package): there is no wheel to tag
            dist.cmdclass["bdist_wheel"] = wheel_without_python(dist.get_command_class("bdist_wheel"))
    if (
        any(getattr(e, "_wasmext_parallel", False) or getattr(e, "_wasmext_product", None) for e in extensions)
        and "build_ext" not in dist.cmdclass
    ):
        dist.cmdclass["build_ext"] = parallel_build_ext(dist.get_command_class("build_ext"))
    # The wheel is abi3 only if every Python extension in it is: one native extension (a hand-written one, or a module made with limited_api=False) ties the whole wheel
    # to the interpreter, and a wheel tagged cp311-abi3 that holds it would be installed, and fail, on another Python. Libraries and programs do not count.
    python_extensions = [e for e in extensions if not getattr(e, "_wasmext_product", None)]
    if python_extensions and all(_is_abi3(e) for e in python_extensions):
        dist.get_option_dict("bdist_wheel").setdefault("py_limited_api", ("wasmext", wheel_tag()))


def product_filename(stem: str, product: str) -> str:
    """The file of a product that is not a Python extension, by the convention of the system."""
    if product == "exe":
        return f"{stem}.exe" if sys.platform == "win32" else stem
    if sys.platform == "win32":
        return f"{stem}.dll"
    return f"lib{stem}.dylib" if sys.platform == "darwin" else f"lib{stem}.so"


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
        def _product_of(self, ext_name: str) -> Any:
            # distutils asks for the file of the last part of the name (`get_ext_fullpath`), setuptools for the whole name (editable installs)
            for e in self.extensions:
                if getattr(e, "_wasmext_product", None) and ext_name in (e.name, e.name.rpartition(".")[2]):
                    return e
            return None

        def get_ext_filename(self, ext_name: str) -> str:
            """The name of a product that is not an extension: `lib<stem>.so`, `lib<stem>.dylib`, `<stem>.dll` or the program."""
            ext = self._product_of(ext_name)
            if ext is None:
                return super().get_ext_filename(ext_name)
            *package, stem = ext_name.split(".")
            return os.path.join(*package, product_filename(stem, ext._wasmext_product))

        def build_extension(self, ext: Any) -> None:
            if getattr(ext, "_wasmext_product", None):
                return self._build_product(ext)
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

        def _build_product(self, ext: Any) -> None:
            """A shared library or a program: made by `wasmext._exe` from the `.wasm` and put where the extension would be."""
            from ._exe import BuildFlags, build, build_shared

            wasm = Path(ext.sources[0])
            target = Path(self.get_ext_fullpath(ext.name))
            settings = ext._wasmext_settings
            if (
                not (self.force or settings["force"])
                and target.is_file()
                and target.stat().st_mtime_ns >= wasm.stat().st_mtime_ns
            ):
                return  # up to date
            flags = BuildFlags(
                extra_compile_args=ext.extra_compile_args or (),
                extra_link_args=ext.extra_link_args or (),
                define_macros=ext.define_macros or (),
                undef_macros=ext.undef_macros or (),
                include_dirs=ext.include_dirs or (),
                libraries=ext.libraries or (),
                library_dirs=ext.library_dirs or (),
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            work = settings["work"]
            if ext._wasmext_product == "shared":
                build_shared(wasm, target, work=work, parts=settings["parts"], quiet=settings["quiet"], flags=flags)
            else:
                build(wasm, target, work=work, parts=settings["parts"], flags=flags)

        def copy_extensions_to_source(self) -> None:
            super().copy_extensions_to_source()
            for ext in self.extensions:  # the wrapper of a library goes to the source folder with it
                if getattr(ext, "_wasmext_product", None) != "shared":
                    continue
                *package, stem = ext.name.split(".")
                source = Path(self.get_finalized_command("build_py").get_package_dir(".".join(package))).resolve()
                built = Path(self.build_lib).joinpath(*package)
                for extra in built.glob(f"{stem}_ctypes.py*"):
                    shutil.copyfile(extra, source / extra.name)

    return WasmextBuildExt
