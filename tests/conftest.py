"""Builds extensions from WAT for the tests: `wat2wasm` and `wasm2c` from the wabt-package (or WASMEXT_WABT, a
directory with its `bin/` and `wasm2c/`) and the C compiler of the machine. Skipped where one of them is missing."""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from wasmext import generate, parse
from wasmext._gen import module_prefix
from wasmext._natify import (
    _RUNTIME_WRAPPERS,  # pyright: ignore[reportPrivateUsage]
    _export_tags,  # pyright: ignore[reportPrivateUsage]
    _repair_imported_elements,  # pyright: ignore[reportPrivateUsage]
    _repair_tail_calls,  # pyright: ignore[reportPrivateUsage]
    _stack_limit_prologue,  # pyright: ignore[reportPrivateUsage]
    shared_header,
)

# the free-threaded build has no abi3 (3.15 has abi3t, which wasmext does not build: cibuildwheel does not tag it yet): there the extension is native


# Under a sanitizer (.github/workflows/sanitizers.yml) the tests that depend on signals or on the address space of the process cannot run: ASan takes the
# signals and reserves terabytes of shadow memory.
SANITIZED = any(f.startswith("-fsanitize") for f in shlex.split(os.environ.get("WASMEXT_TEST_CFLAGS", "")))


def is_abi3_file(name: str) -> bool:
    """Whether a file name is that of an abi3 extension: `.abi3.so`, or `.abi3-<platform>.so` as the newest interpreters name it (not `.abi3t.so`)."""
    return re.search(r"\.abi3[.-]", name) is not None


needs_abi3 = pytest.mark.skipif(
    bool(sysconfig.get_config_var("Py_GIL_DISABLED")), reason="no abi3 on a free-threaded build"
)

DATA = Path(__file__).parent / "data"
WASMEXT_C = Path(__file__).parent.parent / "src" / "wasmext" / "c"


def _wabt_dir() -> Path | None:
    env = os.environ.get("WASMEXT_WABT")
    if env:
        return Path(env)
    spec = importlib.util.find_spec("wabt_package")
    return Path(spec.origin).parent if spec and spec.origin else None


@pytest.fixture(scope="session")
def wabt() -> Path:
    path = _wabt_dir()
    if path is None or not (path / "bin").is_dir():
        pytest.skip("no wabt-package: set WASMEXT_WABT to a directory with bin/ and wasm2c/")
    return path


@pytest.fixture(scope="session")
def build_extension(wabt: Path, tmp_path_factory: pytest.TempPathFactory) -> Callable[..., ModuleType]:
    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    # platform.system(), not sys.platform: pyright takes a comparison with sys.platform as fixed and then does not
    # type-check what follows the skip when it runs on that platform.
    # Windows (and anywhere with WASMEXT_TEST_SETUPTOOLS=1) builds by setuptools, with the compiler of Python (MSVC): the way a user builds
    by_setuptools = platform.system() == "Windows" or os.environ.get("WASMEXT_TEST_SETUPTOOLS") == "1"
    if cc is None and not by_setuptools:
        pytest.skip("no C compiler of the cc kind")
    # a macOS extension finds the Python symbols in the interpreter that imports it
    link_flags: list[str] = ["-undefined", "dynamic_lookup"] if platform.system() == "Darwin" else []
    out = tmp_path_factory.mktemp("ext")
    sys.path.insert(0, str(out))

    built: dict[
        str, ModuleType
    ] = {}  # a loaded extension is not made again under the feet of the process (Windows cannot overwrite a loaded .pyd)

    def build(
        source: Path,
        name: str,
        *,
        abi3: bool = False,
        defines: tuple[str, ...] = (),
        share_tables: bool = False,
        host: str = "wasm32",
    ) -> ModuleType:
        if name in built:
            return built[name]
        wasm = source
        if source.suffix == ".wat":
            wasm = out / f"{name}.wasm"
            subprocess.run([wabt / "bin" / "wat2wasm", source, "-o", wasm], check=True)
        glue = generate(parse(wasm.read_bytes()), name, share_tables=share_tables, host=host)
        if glue.trap_handler:  # the module shares tables: what natify() defines for it
            defines = (
                *defines,
                f"WASMEXT_TRAP_HANDLER={glue.trap_handler}",
                f"WASM_RT_TRAP_HANDLER={glue.trap_handler}",
            )
        (out / f"{name}_py.c").write_text(glue.source, encoding="utf-8")
        (out / f"{name}_glue.h").write_text(glue.header, encoding="utf-8")
        for c_name in (
            "wasmext_glue.h",
            *(("wasi_p1_core.h", "wasi_python.h", *glue.wasi_headers) if glue.wasi_headers else ()),
        ):  # beside the glue, which includes them
            (out / c_name).write_bytes(shared_header(c_name).read_bytes())
        subprocess.run(
            [wabt / "bin" / "wasm2c", wasm, "-o", out / f"{name}_w2c.c", f"--module-name={name}"], check=True
        )
        w2c = out / f"{name}_w2c.c"
        w2c.write_bytes(
            _export_tags(
                _repair_tail_calls(_stack_limit_prologue(_repair_imported_elements([w2c.read_bytes()])[0])),
                module_prefix(name),
            )
        )  # the repairs that natify() makes
        runtime = wabt / "wasm2c"
        if by_setuptools:
            _build_by_setuptools(name, out, runtime, abi3, defines)
            built[name] = importlib.import_module(name)
            return built[name]
        assert cc is not None
        limited = ["-DPy_LIMITED_API=0x030B0000"] if abi3 else []
        so = out / (name + str(sysconfig.get_config_var("EXT_SUFFIX")))
        include = [f"-I{runtime}", f"-I{out}", f"-I{sysconfig.get_paths()['include']}", *(f"-I{d}" for d in _simde())]
        extra = shlex.split(
            os.environ.get("WASMEXT_TEST_CFLAGS", "")
        )  # for a build with a sanitizer (.github/workflows/sanitizers.yml)
        # as natify() does off Windows: the runtime installs no handler of signals and the Python layer installs a link of a chain (WASMEXT_CHAIN, see _gen.py)
        chain = os.name != "nt"
        impl = runtime / "wasm-rt-impl.c"
        if chain:
            impl = out / f"{name}_rt_impl.c"
            impl.write_text(
                _RUNTIME_WRAPPERS["impl"].replace("#include <wasm-rt-impl.c>", '#include "wasm-rt-impl.c"'),
                encoding="utf-8",
            )
            extra = [
                *extra,
                "-DWASMEXT_CHAIN=1",
                "-DWASMEXT_STACK_LIMIT=1",
                "-DWASM_RT_NONCONFORMING_UNCHECKED_STACK_EXHAUSTION=1",
            ]
        link_extra = ["-Wl,-z,now"] if chain and sys.platform.startswith("linux") else []
        glue_object = out / f"{name}_py.o"
        # The glue is ours, so it is built strictly: GCC 14 makes these errors (older ones warn), and the manylinux and
        # user machines have it. The C of wasm2c and its runtime are not ours to police.
        strict = [
            "-Wall",
            "-Werror=incompatible-pointer-types",
            "-Werror=implicit-function-declaration",
            "-Werror=int-conversion",
        ]
        subprocess.run(
            [
                cc,
                "-O1",
                "-fPIC",
                *extra,
                *strict,
                *limited,
                *(f"-D{d}" for d in defines),
                *include,
                "-c",
                out / f"{name}_py.c",
                "-o",
                glue_object,
            ],
            check=True,
        )
        subprocess.run(
            [
                cc, "-O1", "-w", "-shared", "-fPIC", *extra, *link_extra, *link_flags, *limited, *(f"-D{d}" for d in defines), *include,
                glue_object, out / f"{name}_w2c.c", impl, runtime / "wasm-rt-mem-impl.c",
                runtime / "wasm-rt-exceptions-impl.c",
                "-o", so,
            ],
            check=True,
        )  # fmt: skip
        built[name] = importlib.import_module(name)
        return built[name]

    return build


def _simde() -> list[str]:
    """The headers of simde, which the C of wasm2c for a module with SIMD includes (they come with the wabt-package)."""
    from wasmext._toolchain import find_toolchain  # pyright: ignore[reportPrivateUsage]

    headers = find_toolchain().include
    return [str(headers)] if headers is not None and (headers / "simde").is_dir() else []


def _build_by_setuptools(name: str, out: Path, runtime: Path, abi3: bool, defines: tuple[str, ...]) -> None:
    """The extension `name`, whose C is in `out`, built as a user builds one: an `Extension` and the `build_ext` of setuptools."""
    from setuptools import Extension, setup

    macros = [(d.partition("=")[0], d.partition("=")[2] or None) for d in defines]
    if abi3:
        macros.append(("Py_LIMITED_API", "0x030B0000"))
    # as natify() does: the runtime is copied beside the C of the module and the sources are relative, so that the objects of MSVC are not under a
    # copy of the whole path of each source (past the 260 characters of Windows in the directory of a test)
    for runtime_file in ("wasm-rt-impl.c", "wasm-rt-mem-impl.c", "wasm-rt-exceptions-impl.c"):
        shutil.copyfile(runtime / runtime_file, out / runtime_file)
    for header in runtime.glob("wasm-rt*"):
        if header.suffix in (".h", ".inc"):
            shutil.copyfile(header, out / header.name)
    sources = [f"{name}_py.c", f"{name}_w2c.c", "wasm-rt-impl.c", "wasm-rt-mem-impl.c", "wasm-rt-exceptions-impl.c"]
    extension = Extension(
        name,
        sources,
        include_dirs=[".", *_simde()],
        define_macros=macros,
        py_limited_api=abi3,
    )
    cwd = os.getcwd()
    os.chdir(out)
    try:
        setup(
            name=name,
            ext_modules=[extension],
            script_args=["-q", "build_ext", "--build-lib", ".", "--build-temp", f"{name}_build"],
        )
    finally:
        os.chdir(cwd)


@pytest.fixture(scope="session")
def build_ctypes(wabt: Path, tmp_path_factory: pytest.TempPathFactory) -> Callable[..., ModuleType]:
    """The other front end of a module: the shared library and its wrapper for ctypes (`<name>_ctypes.py`), imported; the same arguments as `build_extension`."""
    from wasmext._exe import BuildFlags, build_shared  # pyright: ignore[reportPrivateUsage]

    out = tmp_path_factory.mktemp("ctypes")
    sys.path.insert(0, str(out))

    built: dict[str, ModuleType] = {}  # a loaded library is not made again under the feet of the process

    def build(
        source: Path,
        name: str,
        *,
        abi3: bool = False,
        defines: tuple[str, ...] = (),
        share_tables: bool = False,
        host: str = "wasm32",
    ) -> ModuleType:
        del abi3  # of the extension
        if name in built:
            return built[name]
        wasm = source
        if source.suffix == ".wat":
            wasm = out / f"{name}.wasm"
            subprocess.run([wabt / "bin" / "wat2wasm", source, "-o", wasm], check=True)
        suffix = ".dll" if platform.system() == "Windows" else ".dylib" if platform.system() == "Darwin" else ".so"
        macros = [(d.partition("=")[0], d.partition("=")[2] or None) for d in defines]
        build_shared(
            wasm,
            out / f"lib{name}{suffix}",
            name=name,
            work=out / f"{name}_work",
            share_tables=share_tables,
            host=host,
            optimize=False,
            quiet=True,
            flags=BuildFlags(define_macros=macros),
        )
        built[name] = importlib.import_module(f"{name}_ctypes")
        return built[name]

    return build


@pytest.fixture(scope="session", params=["extension", "ctypes"])
def front_end(request: pytest.FixtureRequest) -> str:
    """Which front end a test of the interface runs on: the extension of CPython, or the wrapper for ctypes over the shared library."""
    return str(request.param)


@pytest.fixture(scope="session")
def build_front_end(front_end: str, request: pytest.FixtureRequest) -> Callable[..., ModuleType]:
    """The builder of the front end: `build_extension` or `build_ctypes` (the same call, the same module interface)."""
    return request.getfixturevalue("build_extension" if front_end == "extension" else "build_ctypes")  # type: ignore[no-any-return]
