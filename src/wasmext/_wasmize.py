"""`wasmize()`: the `.wasm` files of a project become setuptools `Extension`s, as `cythonize()` does for `.pyx` files.

    # setup.py
    from setuptools import setup
    from wasmext import wasmize

    setup(ext_modules=wasmize(["src/mypkg/*.wasm"]))

The C of each module (the glue, the output of `wasm2c`, the runtime of the same version) is written to a directory
beside the `.wasm` (`<name>_wasmext/`, or under `build_dir`) when `wasmize()` runs, and is not written again while the
`.wasm` is the same. A project that ships those directories in its sdist builds without `wasm2c`, with a C compiler only.
"""

from __future__ import annotations

import copy
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._gen import GenError, generate
from ._toolchain import Toolchain, find_toolchain
from ._wasm import WasmError, parse

if TYPE_CHECKING:
    from setuptools import Extension

__all__ = ["wasmize"]

# Bump when the generated C changes, so that a stamp of an older generator does not stop the files being rewritten.
GENERATOR_VERSION = 3
STAMP = "stamp.json"
# Of the runtime, these are compiled; the rest (headers, .inc) is only included.
RUNTIME_SOURCES = ("wasm-rt-impl.c", "wasm-rt-mem-impl.c")
# The oldest CPython an abi3 extension supports (3.11): the buffer protocol joined the limited API there.
LIMITED_API_VERSION = "0x030B0000"


def abi3_possible() -> str | None:
    """None if the interpreter that builds can make an abi3 extension, else why not (a native one is built then)."""
    platform = sysconfig.get_platform()
    if sys.implementation.name != "cpython":
        return f"{sys.implementation.name} has no stable ABI"
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        return "a free-threaded build cannot use the limited API"
    for target in ("emscripten", "android", "ios"):  # each pins one CPython: nothing stable about it
        if target in platform:
            return f"{target} wheels are for one exact CPython"
    return None


def _use_limited_api(requested: bool | None, quiet: bool) -> bool:
    """True forces abi3 where it is possible, False never; None takes WASMEXT_LIMITED_API (1/0), else abi3 where possible."""
    if requested is None:
        env = os.environ.get("WASMEXT_LIMITED_API", "").strip().lower()
        if env in ("0", "false", "no", "off"):
            return False
        requested = True  # "1" or not set: the stable ABI wherever this interpreter has one
    if not requested:
        return False
    why_not = abi3_possible()
    if why_not and not quiet:
        print(f"wasmext: building a native extension: {why_not}", file=sys.stderr)
    return why_not is None


@dataclass(frozen=True, slots=True)
class _Prepared:
    sources: list[str]
    depends: list[str]
    include_dir: str
    skipped: list[str]


def _rel(path: Path) -> str:
    """Relative to the working directory (what setuptools wants in `sources`), with forward slashes."""
    try:
        return Path(os.path.relpath(path)).as_posix()
    except ValueError:  # another drive on Windows
        return path.as_posix()


def _module_name(wasm: Path) -> str:
    """The dotted name from the path: the packages (directories with `__init__.py`) the file is in, then its stem."""
    parts = [wasm.stem]
    folder = wasm.resolve().parent
    while (folder / "__init__.py").is_file():
        parts.append(folder.name)
        folder = folder.parent
    return ".".join(reversed(parts))


def _key(data: bytes, name: str) -> str:
    h = hashlib.sha256()
    h.update(data)
    h.update(b"\0" + name.encode() + b"\0" + str(GENERATOR_VERSION).encode())
    return h.hexdigest()


# wasm2c 1.0.42 checks the sum of 64-bit addresses with `_addcarry_u64` whenever the compiler is MSVC, an intrinsic that only
# the x64 targets have: on ARM64 the C does not link. The `#else` branch it falls back to for other compilers is portable.
_MSVC_ADDCARRY = re.compile(rb"#elif defined\(_MSC_VER\)(\s+if \(_addcarry_u64\()")


def _portable_on_arm64(c_source: bytes) -> bytes:
    return _MSVC_ADDCARRY.sub(rb"#elif defined(_MSC_VER) && defined(_M_X64)\1", c_source)


def _write_if_changed(path: Path, data: bytes) -> None:
    if not path.is_file() or path.read_bytes() != data:
        path.write_bytes(data)


def _same_wabt(written: object) -> bool:
    """False when the C was made by another WABT than the one installed. Without a WABT (a tree that ships its C) the C is kept."""
    try:
        return find_toolchain().version == written
    except RuntimeError:
        return True


def _prepare(wasm: Path, name: str, out_dir: Path, *, force: bool, quiet: bool, stubs: bool) -> _Prepared:
    last = name.rsplit(".", 1)[-1]
    data = wasm.read_bytes()
    key = _key(data, name)
    glue_c, w2c_c = out_dir / f"{last}_glue.c", out_dir / f"{last}_w2c.c"
    stamp = out_dir / STAMP

    def outputs(skipped: list[str]) -> _Prepared:
        runtime = sorted(p for p in out_dir.glob("wasm-rt*") if p.suffix in (".c", ".h", ".inc"))
        sources = [glue_c, w2c_c, *(out_dir / n for n in RUNTIME_SOURCES)]
        depends = [*(p for p in runtime if p.name not in RUNTIME_SOURCES), out_dir / f"{last}_w2c.h", wasm]
        return _Prepared([_rel(p) for p in sources], [_rel(p) for p in depends], _rel(out_dir), skipped)

    # The glue and the stub come from the module alone (no wasm2c, no compiler), so they are always made: a module that
    # cannot be wrapped is reported on every run, and a stub deleted from a tree that ships its C is written again.
    try:
        glue = generate(parse(data), name)
    except (WasmError, GenError) as exc:
        raise type(exc)(f"{wasm}: {exc}") from None
    if stubs:
        stub = wasm.with_suffix(".pyi")
        _write_if_changed(stub, glue.stub.encode("utf-8"))

    complete = stamp.is_file() and all(p.is_file() for p in (glue_c, w2c_c, out_dir / RUNTIME_SOURCES[0]))
    if not force and complete:
        written = json.loads(stamp.read_text(encoding="utf-8"))
        if written.get("key") == key and _same_wabt(written.get("wabt")):
            return outputs(glue.skipped)

    toolchain: Toolchain = find_toolchain()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(toolchain.wasm2c), str(wasm), "-o", str(w2c_c), f"--module-name={last}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"wasm2c failed on {wasm}:\n{result.stderr.strip()}")
    w2c_c.write_bytes(_portable_on_arm64(w2c_c.read_bytes()))
    _write_if_changed(glue_c, glue.source.encode("utf-8"))
    for src in toolchain.runtime.glob("wasm-rt*"):
        if src.suffix in (".c", ".h", ".inc"):
            shutil.copyfile(src, out_dir / src.name)
    stamp.write_text(json.dumps({"key": key, "wabt": toolchain.version}), encoding="utf-8")
    if glue.skipped and not quiet:
        for item in glue.skipped:
            print(f"wasmext: {wasm}: not exposed: {item}", file=sys.stderr)
    return outputs(glue.skipped)


def wasmize(
    module_list: str | os.PathLike[str] | Extension | Iterable[str | os.PathLike[str] | Extension],
    exclude: Iterable[str] | None = None,
    *,
    build_dir: str | os.PathLike[str] | None = None,
    force: bool = False,
    quiet: bool = False,
    stubs: bool = True,
    limited_api: bool | None = None,
) -> list[Extension]:
    """The extensions for the `.wasm` modules in `module_list`, ready for `setup(ext_modules=...)`.

    `module_list` is a glob pattern, a list of them, or `Extension` objects whose `sources` have one `.wasm` (it may
    also have glob patterns, and more sources, which are kept): the other settings of the `Extension` (`libraries`,
    `define_macros`, ...) are kept too and its `name` is the module's name. Without an `Extension` the name is made of
    the path: the packages the file is in (directories with `__init__.py`), then its stem.

    `exclude` is glob patterns of files to leave out. The C is written beside each `.wasm` in `<stem>_wasmext/` or, with
    `build_dir`, in `build_dir/<module name>/`. It is not written again while the `.wasm` is the same, unless `force`,
    and then `wasm2c` is not needed at all. `quiet` stops the notes about exports that are not exposed.

    `limited_api` chooses between the stable ABI (abi3: one wheel for CPython 3.11 and later, tagged `cp311-abi3` by
    wasmext itself) and one native extension per interpreter. None, the default, is abi3 wherever the interpreter that builds
    has a stable ABI (not PyPy, free-threaded, Emscripten, Android, iOS): with `cibuildwheel`, the selector `cp311-*` makes
    the abi3 wheel and `cp314t-*` a native one. WASMEXT_LIMITED_API=0 turns abi3 off for a None; True and False decide in
    the code (True still builds native where abi3 is impossible, and says so).

    With `stubs` (the default) a `<stem>.pyi` is written beside each `.wasm`: the types of the extension for editors and type
    checkers (ship it in the wheel with `package-data`).
    """
    return [
        ext
        for _, ext in _wasmize(
            module_list, exclude, build_dir=build_dir, force=force, quiet=quiet, stubs=stubs, limited_api=limited_api
        )
    ]


def _wasmize(
    module_list: str | os.PathLike[str] | Extension | Iterable[str | os.PathLike[str] | Extension],
    exclude: Iterable[str] | None,
    *,
    build_dir: str | os.PathLike[str] | None,
    force: bool,
    quiet: bool,
    stubs: bool,
    limited_api: bool | None,
) -> list[tuple[Path | None, Extension]]:
    """`wasmize()` with the `.wasm` file of each extension (None for an ordinary extension that passed through)."""
    from setuptools import Extension  # a build-time dependency of the projects that call this

    use_limited_api = _use_limited_api(limited_api, quiet)

    if isinstance(module_list, (str, os.PathLike, Extension)):
        items: list[str | os.PathLike[str] | Extension] = [module_list]
    else:
        items = list(module_list)
    excluded = {Path(p).resolve() for pattern in (exclude or ()) for p in glob.glob(pattern, recursive=True)}
    result: list[tuple[Path | None, Extension]] = []
    names: dict[str, str] = {}

    def convert(wasm: Path, name: str, template: Extension | None) -> None:
        if name in names:
            raise ValueError(f"two modules are named {name!r}: {names[name]} and {wasm}")
        names[name] = str(wasm)
        if not name.rsplit(".", 1)[-1].isidentifier():
            raise ValueError(f"{wasm}: {name!r} is not a module name; give the module an Extension with a name")
        out_dir = Path(build_dir) / name if build_dir else wasm.parent / f"{wasm.stem}_wasmext"
        prepared = _prepare(wasm, name, out_dir, force=force, quiet=quiet, stubs=stubs)
        ext = copy.copy(template) if template else Extension(name, [])
        ext.name = name
        rest = [s for s in (template.sources if template else []) if not str(s).endswith(".wasm")]
        ext.sources = [*rest, *prepared.sources]
        ext.depends = [*ext.depends, *prepared.depends]
        ext.include_dirs = [*ext.include_dirs, prepared.include_dir]
        if use_limited_api:  # one wheel for every CPython from 3.11 on (wasmext._setuptools tags the wheel)
            ext.py_limited_api = True
            ext.define_macros = [*ext.define_macros, ("Py_LIMITED_API", LIMITED_API_VERSION)]
        result.append((wasm, ext))

    for item in items:
        if isinstance(item, Extension):
            patterns = [str(s) for s in item.sources if str(s).endswith(".wasm")]
            if not patterns:
                result.append((None, item))  # an ordinary extension: not ours
                continue
            files = sorted({Path(p) for pat in patterns for p in glob.glob(pat, recursive=True)} - excluded)
            if len(files) != 1:
                raise ValueError(f"Extension {item.name!r}: its sources name {len(files)} .wasm files, one is wanted")
            convert(files[0], item.name, item)
        else:
            pattern = os.fspath(item)
            matches = sorted(Path(m) for m in glob.glob(pattern, recursive=True))
            if not matches and not quiet:
                print(f"wasmext: {pattern!r} does not match any files", file=sys.stderr)
            for wasm in matches:
                if wasm.resolve() not in excluded:
                    convert(wasm, _module_name(wasm), None)
    return result
