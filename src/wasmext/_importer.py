"""The import hook behind `wasmimport`, made after `pyximport`: `import mod` finds `mod.wasm`, makes an extension of it and loads that.

    import wasmimport

    wasmimport.install()
    import fast  # fast.wasm, in the working directory or anywhere on sys.path, or pkg/fast.wasm for `import pkg.fast`

It is a tool for development, as `pyximport` is: the first import of a module (and the first one after the `.wasm` or wasmext
changed) runs `wasm2c` and a C compiler, and the result is kept in a cache directory (`~/.wasmbld`, or `build_dir`), so that
the next imports only load it (until the file, wasmext, or how it is built, `guard_pages`, `limited_api`, `parts`, the flags of the
compiler, changes: a stamp of those settings is kept beside the extension). A `.py` file or an extension of the same name wins over the `.wasm`: the finder is put at the end of
`sys.meta_path`. Importing a `.wasm` compiles code that came with it, so it is for files you trust.

As with `pyximport`, a file `<module>.wasmbld` beside the `.wasm` can say how the extension is made:

    # fast.wasmbld
    def make_ext(modname, wasmfilename):      # a setuptools Extension whose sources are the .wasm
        from setuptools import Extension
        return Extension(modname, [wasmfilename], libraries=["m"])

    def make_setup_args():                    # arguments for setup()
        return {"script_args": ["--verbose"]}
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import sysconfig
from collections.abc import Callable, Generator, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

from ._natify import _natify  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from setuptools import Extension

__all__ = ["WasmFinder", "WasmImportLoader", "clean", "install", "uninstall"]

WASM_EXT = ".wasm"
WASMBLD_EXT = ".wasmbld"


def _default_build_dir() -> str:
    return os.environ.get("WASMIMPORT_BUILD_DIR") or os.path.join(os.path.expanduser("~"), ".wasmbld")


def _load_source(path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location("wasmbld", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def handle_special_build(modname: str, wasmfilename: str) -> tuple[Extension | None, dict[str, Any]]:
    """The Extension and the setup() arguments that `<module>.wasmbld` asks for, if there is such a file."""
    special = os.path.splitext(wasmfilename)[0] + WASMBLD_EXT
    ext: Extension | None = None
    setup_args: dict[str, Any] = {}
    if os.path.exists(special):
        module = _load_source(special)
        make_ext = cast("Callable[[str, str], Extension] | None", getattr(module, "make_ext", None))
        make_setup_args = cast("Callable[[], dict[str, Any]] | None", getattr(module, "make_setup_args", None))
        if make_ext is not None:
            ext = make_ext(modname, wasmfilename)
            if not ext or not ext.sources:
                raise ValueError(f"make_ext in {special} did not return an Extension with sources")
            base = os.path.dirname(special)
            ext.sources = [os.path.join(base, str(s)) for s in ext.sources]
        if make_setup_args is not None:
            setup_args = make_setup_args()
            if not isinstance(setup_args, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise TypeError(f"make_setup_args in {special} did not return a dict")
        if ext is None and not setup_args:
            raise ValueError(f"neither make_ext nor make_setup_args in {special}")
    return ext, setup_args


class _Options:
    """What `install()` was given; the finders and loaders share it, as `pyxargs` is shared in pyximport."""

    def __init__(
        self,
        build_dir: str,
        inplace: bool,
        build_in_temp: bool,
        setup_args: dict[str, Any],
        guard_pages: bool | str | Mapping[str, bool] | None,
        limited_api: bool | None,
        stubs: bool,
        parts: int | None = None,
        share_tables: bool = False,
    ) -> None:
        self.build_dir = build_dir
        self.inplace = inplace
        self.build_in_temp = build_in_temp
        self.setup_args = setup_args
        self.guard_pages = guard_pages
        self.limited_api = limited_api
        self.stubs = stubs
        self.parts = parts
        self.share_tables = share_tables


def _workdir(options: _Options, wasm: Path, name: str) -> Path:
    """One directory for each file and each Python: the same name in two places, or two Pythons, do not meet."""
    tag = f"{sys.implementation.cache_tag}-{sysconfig.get_platform()}"
    digest = hashlib.sha256(str(wasm).encode()).hexdigest()[:12]
    return Path(options.build_dir) / tag / f"{name}-{digest}"


def build_module(name: str, wasmfilename: str, options: _Options) -> str:
    """Make the extension of `wasmfilename` as the module `name`, unless it is made already, and give its path."""
    from setuptools import Extension as _Extension
    from setuptools import setup

    wasm = Path(wasmfilename).resolve()
    template, special_args = handle_special_build(name, str(wasm))
    template = template or _Extension(name, [str(wasm)])
    template.name = name
    work = _workdir(options, wasm, name)
    [(_, ext)] = _natify(
        template,
        None,
        build_dir=work / "c" if options.build_in_temp else wasm.parent / "build" / "wasmext",
        force=False,
        quiet=True,
        stubs=options.stubs,
        limited_api=options.limited_api,
        guard_pages=options.guard_pages,
        parts=options.parts,
        share_tables=options.share_tables,
    )
    lib = _package_root(wasm, name) if options.inplace else work / "lib"
    stamp = work / "options"
    fingerprint = _fingerprint(options, ext, special_args)
    existing = _find_built(lib, name)
    if existing is not None and _up_to_date(existing, ext) and _stamp_is(stamp, fingerprint):
        return str(existing)

    lib.mkdir(parents=True, exist_ok=True)
    args: dict[str, Any] = {
        "name": "wasmimport",
        "packages": [],
        "py_modules": [],
        **options.setup_args,
        **special_args,
    }
    args["ext_modules"] = [ext]
    args["script_args"] = [
        *args.get("script_args", []),
        "-q",
        "build_ext",
        "--build-lib",
        str(lib),
        "--build-temp",
        str(work / "tmp"),
        "--force",
    ]
    try:
        with _compiler_output_to_stderr():
            setup(**args)
    except SystemExit as exc:  # distutils reports a failed compile by exiting
        raise RuntimeError(f"the C compiler failed ({exc})") from None
    built = _find_built(lib, name)
    if built is None:
        raise RuntimeError(f"the build left no extension for {name} in {lib}")
    stub = getattr(ext, "_wasmext_stub", None)
    if options.stubs and stub and Path(stub).is_file():  # asked for: the types go beside the .wasm that is imported
        shutil.copyfile(stub, wasm.with_suffix(".pyi"))
    from ._cli import _prune_stale  # pyright: ignore[reportPrivateUsage]

    _prune_stale(
        lib, name
    )  # a native file and an abi3 one of earlier builds: only the newest is left, as Python would pick the first
    built = _find_built(lib, name) or built
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(fingerprint, encoding="utf-8")
    return str(built)


@contextlib.contextmanager
def _compiler_output_to_stderr() -> Generator[None]:
    """MSVC (`cl`, `link`) writes the names of the files it compiles and its warnings to the standard output, which would
    become part of the output of the program that did `import mod`: during the build it goes to the standard error."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)


def _package_root(wasm: Path, name: str) -> Path:
    """The directory above the topmost package of the module: where an in-place build puts the extension."""
    return wasm.parent.parents[len(name.split(".")) - 2] if "." in name else wasm.parent


def _find_built(lib: Path, name: str) -> Path | None:
    *package, stem = name.split(".")
    folder = lib.joinpath(*package)
    if not folder.is_dir():
        return None
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        candidate = folder / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


# the environment that changes what the compiler is given
_BUILD_ENVIRONMENT = (
    "WASMEXT_GUARD_PAGES",
    "WASMEXT_LIMITED_API",
    "WASMEXT_PARTS",
    "CC",
    "CFLAGS",
    "LDFLAGS",
    "CPPFLAGS",
)


# the lists of an Extension that hold paths, which natify() gives relative to the working directory
_PATH_LISTS = ("library_dirs", "include_dirs")


def _absolute(paths: list[str] | None) -> list[str] | None:
    """The same directories whatever the working directory is: the fingerprint must not change with the place `import` is run from."""
    return None if paths is None else [os.path.abspath(p) for p in paths]


def _fingerprint(options: _Options, ext: Extension, special_args: dict[str, Any]) -> str:
    """What the extension was built with besides the files: a change of any of it makes the cached one stale (the files say nothing of it)."""
    settings = {
        "guard_pages": options.guard_pages,
        "limited_api": options.limited_api,
        "parts": options.parts,
        "share_tables": options.share_tables,
        "setup_args": options.setup_args,
        "special_args": special_args,
        "extension": {
            key: _absolute(getattr(ext, key, None)) if key in _PATH_LISTS else getattr(ext, key, None)
            for key in (
                "libraries",
                "library_dirs",
                "include_dirs",
                "define_macros",
                "undef_macros",
                "extra_compile_args",
                "extra_link_args",
                "py_limited_api",
            )
        },
        "environment": {key: os.environ.get(key) for key in _BUILD_ENVIRONMENT},
    }
    return json.dumps(settings, sort_keys=True, default=repr)


def _stamp_is(stamp: Path, fingerprint: str) -> bool:
    try:
        return stamp.read_text(encoding="utf-8") == fingerprint
    except OSError:
        return False


def _up_to_date(so: Path, ext: Extension) -> bool:
    built = so.stat().st_mtime
    return all(Path(p).stat().st_mtime <= built for p in [*ext.sources, *ext.depends] if Path(p).exists())


class WasmImportLoader(importlib.machinery.ExtensionFileLoader):
    """Makes the extension when the module is created and loads it as an ordinary one."""

    def __init__(self, filename: str, options: _Options) -> None:
        super().__init__(os.path.splitext(os.path.basename(filename))[0], filename)
        self._options = options

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        try:
            so_path = build_module(spec.name, str(spec.origin), self._options)
        except Exception as failure:
            raise ImportError(
                f"Building module {spec.name} failed: {failure}", name=spec.name, path=spec.origin
            ) from failure
        self.path = so_path
        spec.origin = so_path
        return super().create_module(spec)

    def exec_module(self, module: ModuleType) -> None:
        try:
            super().exec_module(module)
        except Exception as failure:
            raise ImportError(f"Executing module {module.__file__} failed: {failure}") from failure


class WasmFinder(importlib.abc.MetaPathFinder):
    """Finds `<name>.wasm` where `<name>.py` would be, and gives a spec whose loader makes the extension."""

    def __init__(self, options: _Options, extension: str = WASM_EXT) -> None:
        self.options = options
        self.extension = extension

    def find_spec(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        entries = (
            list(path) if path else [os.getcwd(), *sys.path]
        )  # a top level import: as pyximport, the working directory first
        name = fullname.rpartition(".")[2]
        for entry in entries:
            filename = os.path.join(entry or os.getcwd(), name + self.extension)
            if os.path.exists(filename):
                return importlib.util.spec_from_file_location(
                    fullname, filename, loader=WasmImportLoader(filename, self.options)
                )
        return None  # we don't know how to import this


def install(
    build_dir: str | os.PathLike[str] | None = None,
    *,
    build_in_temp: bool = True,
    setup_args: dict[str, Any] | None = None,
    inplace: bool = False,
    guard_pages: bool | str | Mapping[str, bool] | None = None,
    limited_api: bool | None = None,
    stubs: bool = False,
    parts: int | None = None,
    share_tables: bool = False,
) -> WasmFinder:
    """Main entry point: let `import` find `.wasm` files, for this process. Returns the finder (to hand to `uninstall()`).

    :param build_dir: where the modules are made; by default `.wasmbld` in the home directory (or `WASMIMPORT_BUILD_DIR`).
    :param build_in_temp: if False the C is written in `build/wasmext/` beside the `.wasm`, as `wasmext` does, instead of into
        `build_dir`: easier to look at when something goes wrong, and it can meet files of the same name.
    :param setup_args: arguments for `setuptools.setup()`; a `.wasmbld` file can add to them.
    :param inplace: put the built extension (`.so` or `.pyd`) next to the `.wasm`.
    :param guard_pages: and :param limited_api: and :param parts: and :param share_tables: as for `natify()`.
    :param stubs: write a `<name>.pyi` beside each `.wasm` (not by default: the directory you import from stays as it is).

    A second call replaces the finder of the first (where `pyximport` keeps the first one).
    """
    uninstall()
    options = _Options(
        str(build_dir) if build_dir is not None else _default_build_dir(),
        inplace,
        build_in_temp,
        dict(setup_args or {}),
        guard_pages,
        limited_api,
        stubs,
        parts,
        share_tables,
    )
    finder = WasmFinder(options)
    sys.meta_path.append(finder)
    return finder


def uninstall(finder: WasmFinder | None = None) -> None:
    """Take the finder out again (all of ours, without an argument). Modules already imported stay."""
    sys.meta_path[:] = [f for f in sys.meta_path if not (isinstance(f, WasmFinder) and (finder is None or f is finder))]


def clean(build_dir: str | os.PathLike[str] | None = None) -> None:
    """Delete the cache."""
    shutil.rmtree(build_dir if build_dir is not None else _default_build_dir(), ignore_errors=True)
