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
GENERATOR_VERSION = 2
STAMP = "stamp.json"
# Of the runtime, these are compiled; the rest (headers, .inc) is only included.
RUNTIME_SOURCES = ("wasm-rt-impl.c", "wasm-rt-mem-impl.c")


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


def _prepare(wasm: Path, name: str, out_dir: Path, *, force: bool, quiet: bool) -> _Prepared:
    last = name.rsplit(".", 1)[-1]
    data = wasm.read_bytes()
    key = _key(data, name)
    glue_c, w2c_c = out_dir / f"{last}_glue.c", out_dir / f"{last}_w2c.c"
    stamp = out_dir / STAMP

    def outputs() -> _Prepared:
        runtime = sorted(p for p in out_dir.glob("wasm-rt*") if p.suffix in (".c", ".h", ".inc"))
        sources = [glue_c, w2c_c, *(out_dir / n for n in RUNTIME_SOURCES)]
        depends = [*(p for p in runtime if p.name not in RUNTIME_SOURCES), out_dir / f"{last}_w2c.h", wasm]
        skipped = json.loads(stamp.read_text(encoding="utf-8")).get("skipped", [])
        return _Prepared([_rel(p) for p in sources], [_rel(p) for p in depends], _rel(out_dir), skipped)

    complete = stamp.is_file() and all(p.is_file() for p in (glue_c, w2c_c, out_dir / RUNTIME_SOURCES[0]))
    if not force and complete and json.loads(stamp.read_text(encoding="utf-8")).get("key") == key:
        return outputs()

    try:
        glue = generate(parse(data), name)
    except (WasmError, GenError) as exc:
        raise type(exc)(f"{wasm}: {exc}") from None
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
    stamp.write_text(json.dumps({"key": key, "wabt": toolchain.version, "skipped": glue.skipped}), encoding="utf-8")
    if glue.skipped and not quiet:
        for item in glue.skipped:
            print(f"wasmext: {wasm}: not exposed: {item}", file=sys.stderr)
    return outputs()


def wasmize(
    module_list: str | os.PathLike[str] | Extension | Iterable[str | os.PathLike[str] | Extension],
    exclude: Iterable[str] | None = None,
    *,
    build_dir: str | os.PathLike[str] | None = None,
    force: bool = False,
    quiet: bool = False,
) -> list[Extension]:
    """The extensions for the `.wasm` modules in `module_list`, ready for `setup(ext_modules=...)`.

    `module_list` is a glob pattern, a list of them, or `Extension` objects whose `sources` have one `.wasm` (it may
    also have glob patterns, and more sources, which are kept): the other settings of the `Extension` (`libraries`,
    `define_macros`, ...) are kept too and its `name` is the module's name. Without an `Extension` the name is made of
    the path: the packages the file is in (directories with `__init__.py`), then its stem.

    `exclude` is glob patterns of files to leave out. The C is written beside each `.wasm` in `<stem>_wasmext/` or, with
    `build_dir`, in `build_dir/<module name>/`. It is not written again while the `.wasm` is the same, unless `force`,
    and then `wasm2c` is not needed at all. `quiet` stops the notes about exports that are not exposed.
    """
    return [ext for _, ext in _wasmize(module_list, exclude, build_dir=build_dir, force=force, quiet=quiet)]


def _wasmize(
    module_list: str | os.PathLike[str] | Extension | Iterable[str | os.PathLike[str] | Extension],
    exclude: Iterable[str] | None,
    *,
    build_dir: str | os.PathLike[str] | None,
    force: bool,
    quiet: bool,
) -> list[tuple[Path | None, Extension]]:
    """`wasmize()` with the `.wasm` file of each extension (None for an ordinary extension that passed through)."""
    from setuptools import Extension  # a build-time dependency of the projects that call this

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
        prepared = _prepare(wasm, name, out_dir, force=force, quiet=quiet)
        ext = copy.copy(template) if template else Extension(name, [])
        ext.name = name
        rest = [s for s in (template.sources if template else []) if not str(s).endswith(".wasm")]
        ext.sources = [*rest, *prepared.sources]
        ext.depends = [*ext.depends, *prepared.depends]
        ext.include_dirs = [*ext.include_dirs, prepared.include_dir]
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
