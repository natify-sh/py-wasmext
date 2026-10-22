"""`natify()`: the `.wasm` files of a project become setuptools `Extension`s, as `cythonize()` does for `.pyx` files.

    # setup.py
    from setuptools import setup
    from wasmext import natify

    setup(ext_modules=natify(["src/mypkg/*.wasm"]))

The C of each module (the glue, the output of `wasm2c`, the wrappers of the runtime) is written to `build/wasmext/<module name>/`
(or under `build_dir`) when `natify()` runs, and is not written again while it was made from this `.wasm` by this wasmext and
WABT (the macros WASMEXT_GENERATED_* at the head of each file say so). It is a step of the build, not a source: it is not in a source distribution (the build
directory is not), so a build needs `wasm2c`, which `wabt-package` brings.
"""

from __future__ import annotations

import copy
import functools
import glob
import hashlib
import importlib.machinery
import importlib.metadata
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._gen import GenError, Glue, generate, module_prefix
from ._toolchain import Toolchain, find_toolchain
from ._wasm import WasmError, expand_compact_imports, parse, wasi_hint

if TYPE_CHECKING:
    from setuptools import Extension

__all__ = ["natify"]

DEFAULT_BUILD_DIR = "build/wasmext"  # the C of the modules of a project, the same for every platform and Python: what setuptools builds from it goes to build/temp.<tag>
GENERATED = "WASMEXT_GENERATED_"  # the prefix of the macros at the head of the C that wasmext made (WASMEXT_GENERATED_SOURCES, ...)
# the C of wasmext that a module is built with when it needs it (WASI): copied beside the C of the module
GLUE_SHARED = ("wasmext_glue.h",)  # the glue that is the same for every module
WASI_SHARED = (
    "wasi_core.h",
    "wasi_files_win32.h",
    "wasi_python.h",
)  # what both snapshots share: the core of WASI, its file backend for Windows, and its host, Python
C_DIR = Path(__file__).parent / "c"
# A big module is split into files that gcc and the others compile at the same time: one file of 3 million lines was not compiled
# in 33 minutes (FEATURES.md, "Build time of a large module"), 16 files of it were, on 4 cores, in 3. Splitting costs speed of the
# code (a call from one file to another is not inlined), so a small module stays whole.
AUTO_SPLIT_FROM = 1 << 20  # a module smaller than this (1 MiB) is one file
AUTO_PART_SIZE = (
    128 << 10
)  # and a larger one gets a file for each 128 KiB of it (measured: more files balance the cores better)
MAX_AUTO_PARTS = (
    256  # coreutils.wasm built as fast with 256 files as with 64; the number asked for by hand has no limit
)
# Below this much of the module in a file the work of reading the shared header and of the extra files starts to cost more
# than the parallelism gives (lua.wasm: from 128 files, 2.6 KB each, 12% more processor time; 256 files, 36% more).
WARN_PART_BYTES = 4096
# The oldest CPython an abi3 extension supports (3.11): the buffer protocol joined the limited API there.
LIMITED_API_VERSION = "0x030B0000"
PRODUCTS = ("extension", "shared", "exe")  # what natify(product=...) can make
# The C of wasm2c for a module with SIMD includes the headers of simde, which the wabt-package carries.
_ABI3_SUFFIX = re.compile(r"\.abi3[.-]")  # not ".abi3t.so" (abi3t, PEP 803)
_USES_SIMDE = re.compile(rb'^\s*#\s*include\s*[<"]simde/', re.MULTILINE)


def abi3_possible() -> str | None:
    """None if the interpreter that builds can make an abi3 extension, else why not (a native one is built then).

    Two different things, kept apart. *Can this interpreter load an abi3 extension at all* is told by the interpreter itself, as setuptools asks it
    (`get_abi3_suffix`): `importlib.machinery.EXTENSION_SUFFIXES` has `.abi3.so` (on Windows the plain `.pyd`) only where it does. CPython has it; PyPy and the
    free-threaded builds do not (PEP 703; 3.15 adds `.abi3t.so` for them, which this does not count); the check does not tell the free-threaded build on Windows, where `.pyd` is in the list all the same, so that is asked of the build.
    *Is it wise to ship a wheel of it* is a decision, not a capability, and is a list: Emscripten (Pyodide), Android and iOS pin one exact CPython in the runtime
    (the extension links libpython there, or the app embeds one build), so an abi3 wheel would promise what the platform cannot keep."""
    suffixes = importlib.machinery.EXTENSION_SUFFIXES
    # ".abi3." or ".abi3-<platform>." and not ".abi3": 3.15 also lists ".abi3t.so" (the stable ABI of a free-threaded build, PEP 803), which is not what Py_LIMITED_API=3.11 makes
    can_load = any(_ABI3_SUFFIX.match(suffix) for suffix in suffixes) or (
        sys.platform == "win32" and ".pyd" in suffixes
    )
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        # abi3t (3.15) is not built: it needs another tag that cibuildwheel does not give yet, and a glue without PyObject_HEAD
        return "a free-threaded build cannot use the limited API (abi3t is not built, the extension is native)"
    if sys.implementation.name != "cpython":
        return f"{sys.implementation.name} has no stable ABI"
    if not can_load:
        return f"this interpreter does not load abi3 extensions (its extension suffixes are {', '.join(suffixes)})"
    platform = sysconfig.get_platform()
    for target in ("emscripten", "android", "ios"):  # each pins one CPython: nothing stable about it
        if target in platform:
            return f"{target} wheels are for one exact CPython"
    return None


_ARCH_NAMES = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "i386": "x86",
    "i686": "x86",
    "x86": "x86",
    "win32": "x86",
    "aarch64": "arm64",
    "arm64": "arm64",
    "arm64_v8a": "arm64",
    "armv7": "armv7l",
    "armv7l": "armv7l",
    "armeabi_v7a": "armv7l",
}


def target_arch(platform: str | None = None) -> str:
    """The architecture the extension is built for, by one set of names (`x86_64`, `x86`, `arm64`, `armv7l`, `ppc64le`, `riscv64`, `s390x`, `wasm32`, ...):
    taken from `sysconfig.get_platform()`, which a cross build (cibuildwheel for Windows x86 or ARM64, macOS universal pieces, Android) sets to the target, not the host."""
    text = (platform or sysconfig.get_platform()).lower()
    if text == "win32":
        return "x86"
    for token in reversed(text.split("-")):
        if token in _ARCH_NAMES:
            return _ARCH_NAMES[token]
    return text.rsplit("-", 1)[-1]


def parse_guard_pages(text: str) -> bool | dict[str, bool]:
    """`1`/`0` (also yes, no, on, off, true, false), or a list for architectures: `x86=off,armv7l=off,default=on` (the names of `target_arch()`; `default` is for the others)."""
    truth = {"1": True, "true": True, "yes": True, "on": True, "0": False, "false": False, "no": False, "off": False}
    plain = text.strip().lower()
    if plain in truth:
        return truth[plain]
    result: dict[str, bool] = {}
    for item in plain.split(","):
        arch, sep, value = item.partition("=")
        if not sep or value.strip() not in truth or not arch.strip():
            raise ValueError(f"guard pages: {text!r} is neither on/off nor a list like x86=off,default=on")
        result[arch.strip()] = truth[value.strip()]
    return result


def _guard_pages(requested: bool | str | Mapping[str, bool] | None) -> bool:
    """Whether the memories of the modules are reserved with guard pages (the default of the runtime of wasm2c). It is decided when the C is compiled, for the architecture
    the extension is built for: a bool, or a mapping from architectures (see `target_arch()`) to bool with `default` for the others, as a list in text too
    (`x86=off,armv7l=off`). None takes WASMEXT_GUARD_PAGES in the same forms, else True.

    False builds the runtime with WASM_RT_USE_MMAP=0: a memory is allocated at the size it has and every access is checked, instead of 8 GiB of address
    space being reserved for each memory, which a process with a limit on its address space (ulimit -v, some containers) cannot do: the runtime then calls abort().
    Guard pages need a 64-bit address space: on a 32-bit target the runtime allocates the other way whatever is asked."""
    if requested is None:
        requested = parse_guard_pages(os.environ.get("WASMEXT_GUARD_PAGES", "1"))
    if isinstance(requested, str):
        requested = parse_guard_pages(requested)
    if isinstance(requested, Mapping):
        return bool(requested.get(target_arch(), requested.get("default", True)))
    return bool(requested)


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
    extra_include_dirs: tuple[str, ...] = ()
    parts: int = 1  # the files the C of the module is in
    glue: Any = None  # the Glue of the module (what is generated from it, for every target)
    parsed: Any = None  # the parsed module


@dataclass(frozen=True, slots=True)
class Target:
    """What one product of a module is built from: the sources to compile, or why the module has no such product."""

    sources: list[str]
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Generated:
    """The C that is made of a module, for **every** target it can have (an extension, a shared library, a program): the build only chooses which sources to compile,
    so what is generated never has to be made again for another product. `files` is everything made, for a source distribution."""

    last: str
    out_dir: Path
    prepared: _Prepared
    targets: dict[str, Target]
    files: list[str]
    skipped: list[str]  # what the module leaves out of its API, said in words


def _rel(path: Path) -> str:
    """Relative to the working directory (what setuptools wants in `sources`), with the separator of the system: the pruning of `build/` from an
    sdist (distutils, `egg_info`) matches by that separator, so with `/` on Windows the generated C went into the sdist."""
    try:
        return os.path.relpath(path)
    except ValueError:  # another drive on Windows
        return str(path)


def _absolute(paths: Iterable[str]) -> list[str]:
    """The generated files as `Extension.depends`, absolute. setuptools puts a relative dependency into the manifest of an sdist, always with `/`
    (`build_ext._get_internal_depends`), and the pruning of `build/` matches by the separator of the system, so on Windows the generated
    files went into the sdist; an absolute one is left out of the manifest (and still makes the extension be built again when it changes)."""
    return [os.path.abspath(p) for p in paths]


def _module_name(wasm: Path) -> str:
    """The dotted name from the path: the packages (directories with `__init__.py`) the file is in, then its stem."""
    parts = [wasm.stem]
    folder = wasm.resolve().parent
    while (folder / "__init__.py").is_file():
        parts.append(folder.name)
        folder = folder.parent
    return ".".join(reversed(parts))


def _version() -> str:
    try:
        return importlib.metadata.version("wasmext")
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


_RELEASE_VERSION = re.compile(r"\d+(\.\d+)*((a|b|rc)\d+)?")


def _release_version() -> str | None:
    """The version of wasmext if it is a release (1.2, 1.2a1, 1.2rc1): a development version (a tag and a number of commits, a date)
    changes with every commit, and what is written into a file that is committed must not."""
    version = _version()
    return version if _RELEASE_VERSION.fullmatch(version) else None


def wasm_digest(data: bytes) -> str:
    """What the C is made from, by its content (not by the time of the file, which a cache, a copy or an archive does not keep)."""
    return hashlib.sha256(data).hexdigest()


@functools.cache
def sources_digest() -> str:
    """A fingerprint of the sources of wasmext itself (its Python, and the C and headers it ships): what the C it made depends on. The C is made
    again when this changes, not when the version of the package does, so a development tree is not rebuilt by every commit and a release
    never reuses the C of another one; a wheel is the same bytes on every system, so the digest is the same there."""
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".c", ".h", ".inc") and "__pycache__" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def inputs_digest(sources: str, wabt: str, parts: int, name: str, wasm: str, share_tables: bool = False) -> str:
    """One fingerprint of everything the C is made from: the sources of wasmext, the WABT, the number of files, the name of the module and the
    content of the .wasm. A new input goes here and the C is made again when it changes, with no other place to remember."""
    return hashlib.sha256(
        "\0".join((sources, wabt, str(parts), name, wasm, str(int(share_tables)))).encode()
    ).hexdigest()


def _marker(wabt: str, parts: int = 1, digest: str = "", name: str = "", share_tables: bool = False) -> str:
    """The head of every file of the C that wasmext made. Macros and not a comment: they are read by name, so nothing depends on the place or the
    wording of a line. INPUTS is what decides whether the file is current; the others say what it was made from (VERSION is for people only)."""
    sources = sources_digest()
    lines = [
        f'#define {GENERATED}VERSION "{_version()}"',
        f'#define {GENERATED}INPUTS "{inputs_digest(sources, wabt, parts, name, digest, share_tables)}"',
        f'#define {GENERATED}SOURCES "{sources}"',
        f'#define {GENERATED}WABT "{wabt}"',
        f"#define {GENERATED}PARTS {parts}",
        f"#define {GENERATED}SHARE {int(share_tables)}",
    ]
    if digest:
        lines.append(f'#define {GENERATED}WASM "{digest}"')
    return "\n".join(lines) + "\n"


_GENERATED_MACRO = re.compile(rf'^#define {GENERATED}([A-Z]+) (?:"([^"\n]*)"|(\d+))$', re.MULTILINE)


def _generated_info(path: Path) -> dict[str, str] | None:
    """The macros at the head of a file of the C that wasmext made, or None where there are none (not made by wasmext, or by a version that wrote a comment)."""
    try:
        with path.open("r", encoding="utf-8") as f:
            head = f.read(2048)
    except (OSError, UnicodeDecodeError):
        return None
    found = {key: quoted or number for key, quoted, number in _GENERATED_MACRO.findall(head)}
    return found or None


def _choose_parts(size: int, requested: int | None) -> int:
    """How many files the C of a module of `size` bytes is written in: what was asked (the argument, else WASMEXT_PARTS), else
    one for a small module and more for a large one."""
    if requested is None:
        env = os.environ.get("WASMEXT_PARTS")
        if env:
            try:
                requested = int(env)
            except ValueError:
                raise ValueError(f"WASMEXT_PARTS must be a number, not {env!r}") from None
    if requested is not None:
        if requested < 1:
            raise ValueError(f"parts must be 1 or more, not {requested}")
        return requested  # what is asked for is done, with a warning where it is unwise (see _parts_warning)
    return 1 if size < AUTO_SPLIT_FROM else min(MAX_AUTO_PARTS, -(-size // AUTO_PART_SIZE))


def _parts_warning(parts: int, size: int, functions: int) -> str | None:
    """Why the number of files asked for is unwise, or None."""
    if parts > functions:
        return f"{parts} files for {functions} functions: some of the files stay empty"
    if parts > 1 and size // parts < WARN_PART_BYTES:
        return (
            f"{parts} files for a module of {size} bytes ({size // parts} bytes each): the work of every extra file "
            f"(the shared header is read by each) costs more than it gains below about {WARN_PART_BYTES} bytes"
        )
    return None


def _w2c_files(out_dir: Path, last: str, parts: int) -> list[Path]:
    return [out_dir / f"{last}_w2c.c"] if parts == 1 else [out_dir / f"{last}_w2c_{i}.c" for i in range(parts)]


def _existing_parts(out_dir: Path, last: str) -> int:
    """How many files of the C of the module are there (0: none, or not all of them)."""
    if (out_dir / f"{last}_w2c.c").is_file():
        return 1
    count = 0
    while (out_dir / f"{last}_w2c_{count}.c").is_file():
        count += 1
    return count


def _made_by_this_wasmext(path: Path, digest: str, name: str, share_tables: bool = False) -> bool:
    """The head of `path` says it was made from these inputs: these sources of wasmext, this .wasm, this name and, where a WABT is installed, this WABT."""
    info = _generated_info(path)
    if info is None or not {"INPUTS", "WABT", "PARTS", "SHARE", "WASM"} <= set(info):
        return False
    try:
        wabt = find_toolchain().version
    except RuntimeError:  # built where there is no WABT: what wasmext made from this .wasm stays, by the WABT it says
        wabt = info["WABT"]
    return info["INPUTS"] == inputs_digest(sources_digest(), wabt, int(info["PARTS"]), name, digest, share_tables)


# wasm2c 1.0.42 checks the sum of 64-bit addresses with `_addcarry_u64` whenever the compiler is MSVC, an intrinsic that only
# the x64 targets have: on ARM64 and on x86 (Win32) the C compiles but does not link (LNK2019, unresolved `_addcarry_u64`; WABT #2885). The `#else` branch it
# falls back to for other compilers is portable. Like the fix proposed upstream, the branch is kept to `_M_X64`.
_MSVC_ADDCARRY = re.compile(rb"#elif defined\(_MSC_VER\)(\s+if \(_addcarry_u64\()")
_MSVC_X64_ONLY = rb"#elif defined(_MSC_VER) && defined(_M_X64)\1"
# The runtime calls abort() when the first allocation of a memory fails (it cannot be allocated, or the process has not the
# address space for the 8 GiB that guard pages reserve): in the copy, that is a trap with this code, which the glue
# raises as MemoryError.
# The runtime of wasm2c is not copied: the files of the tree include the ones of the toolchain (found by -I), the original sources
# stay as they are. The only change is that wasm_rt_allocate_memory traps (NO_MEMORY) where it would abort(): the file that
# includes wasm-rt-mem-impl.c turns the abort() called from it into that trap.
_RUNTIME_WRAPPERS = {
    # a module that shares tables is built as an extension with WASMEXT_TRAP_HANDLER (wasmext_glue.h): its traps do not `longjmp` by themselves
    "impl": "#ifdef WASMEXT_TRAP_HANDLER\n#define WASM_RT_TRAP_HANDLER WASMEXT_TRAP_HANDLER\n#endif\n"
    # WASMEXT_CHAIN: the runtime sets up the alternate stack of a thread, but installs no handler of signals (the Python layer installs a link of a chain, see _gen.py)
    "#ifdef WASMEXT_CHAIN\n#include <signal.h>\n"
    "static inline int wasmext_noop_sigaction_(int sig, const void *act, void *old) { (void)sig; (void)act; (void)old; return 0; }\n"
    "#define sigaction(a, b, c) wasmext_noop_sigaction_((a), (b), (c))\n#endif\n"
    "#ifdef WASMEXT_STACK_LIMIT\n#include <stdint.h>\n"
    '__thread uintptr_t wasmext_stack_limit __attribute__((visibility("hidden")));\n#endif\n'
    "#include <wasm-rt-impl.c>\n",
    "exceptions": "#include <wasm-rt-exceptions-impl.c>\n",
    "mem": """#include <stdlib.h>
#include <string.h>
#include <wasm-rt.h>
static void wasmext_abort_in(const char *where) {
  if (strncmp(where, "wasm_rt_allocate_memory", 23) == 0) wasm_rt_trap((wasm_rt_trap_t)0x7001);
  abort();
}
#define abort() wasmext_abort_in(__func__)
#include <wasm-rt-mem-impl.c>
#undef abort
""",
}
_RUNTIME_WRAPPERS_TEXT = "\0".join(_RUNTIME_WRAPPERS.values())
# wasm2c 1.0.42 writes the C of a function that has locals and ends in `return_call` with the first group of locals cut in
# two: the type, then the declarations of the temporaries, then `var_l3 = 0, ...;` with no type (`u32   u32 var_i0;`).
# Put the type back in front of the locals. The pattern matches only that broken shape, so a wasm2c that is fixed passes through.
_W2C_TYPE = rb"(?:u32|u64|f32|f64|v128)"
_TAIL_CALL_LOCALS = re.compile(
    rb"^  (" + _W2C_TYPE + rb") ((?:  " + _W2C_TYPE + rb" var_[a-z]\d+(?:, var_[a-z]\d+)*;\n)+)"
    rb"(var_l\d+ = 0(?:,\s+var_l\d+ = 0)*;\n)",
    re.MULTILINE,
)
_TAIL_CALL_LOCALS_FIXED = rb"\2  \1 \3"


def signal_build_flags() -> tuple[list[tuple[str, str]], list[str]]:
    """The macros and link arguments of a build that does without a handler of signals of the runtime of wasm2c for the stack and shares the one for the memory (docs/patch_policy.md).
    `WASMEXT_CHAIN`: the runtime installs no handler of SIGSEGV/SIGBUS of its own, because the runtimes of several modules would replace each other's (see wasmext_glue.h).
    `WASMEXT_STACK_LIMIT`: the stack running out is seen by a comparison in each function (`_stack_limit_prologue`), so the runtime takes neither the counter of the depth nor the
    handler on an alternate stack. Not on Windows (it calls every vectored handler; the stack is the counter there) and not where there are no such signals or no thread stack to
    measure (Emscripten, WASI). The limit is a thread-local variable and the handler reads thread-local data, so on Linux the library is linked with `-z now`: with lazy binding the first
    access resolves `__tls_get_addr` inside the handler, which hangs. `WASMEXT_STACK_CHECK=guard` in the environment of the build keeps the chain but sees the stack by the guard page (the handler on an alternate stack), which is faster (CoreMark 98% of native against 91%) and is warned about when asked for (see docs/experiments/stack_limit/). The target is read from `sysconfig.get_platform()`, which a cross build sets to the target and not the host."""
    platform = sysconfig.get_platform().lower()
    if os.name == "nt" or platform.startswith("win") or any(t in platform for t in ("emscripten", "wasi")):
        return [], []
    macros = [("WASMEXT_CHAIN", "1")]
    choice = os.environ.get("WASMEXT_STACK_CHECK", "limit").lower()
    if choice not in ("limit", "guard"):
        raise ValueError(f"WASMEXT_STACK_CHECK is {choice!r}: it is 'limit' (the default) or 'guard'")
    if choice == "guard":
        warnings.warn(
            "WASMEXT_STACK_CHECK=guard: the stack running out is seen by the guard page and a handler of SIGSEGV on an alternate stack kept for every thread "
            "(about 8% faster than the default on CoreMark, up to 1.8 times on a program that is all calls). A stack overflow in a thread other than "
            "the main one is reported as an out-of-bounds access, and a thread that ends gives its stack back through the Python layer only. "
            "See docs/experiments/stack_limit/README.md",
            stacklevel=2,
        )
    else:
        macros += [("WASMEXT_STACK_LIMIT", "1"), ("WASM_RT_NONCONFORMING_UNCHECKED_STACK_EXHAUSTION", "1")]
    return macros, (["-Wl,-z,now"] if platform.startswith("linux") else [])


def _portable_off_x64(c_source: bytes) -> bytes:
    return _MSVC_ADDCARRY.sub(_MSVC_X64_ONLY, c_source)


def _portable(c_source: bytes) -> bytes:
    """The repairs that every file of the C of a module gets, the code and the declarations they share (see above)."""
    return _stack_limit_prologue(_portable_off_x64(c_source))


# wasm2c 1.0.42 knows two ways to see that the native stack runs out: a counter of the depth (`WASM_RT_STACK_DEPTH_COUNT`: `++depth`/`--depth` in each function, a limit of 500
# calls) and a handler of the signal of the guard page (`WASM_RT_STACK_EXHAUSTION_HANDLER`: a handler on an alternate stack in every thread). The third, a comparison of the
# address of the frame with the lowest address that is still safe, kept per thread, is one load and one compare in the prologue and nothing in the epilogue (measured at 1.06 of
# the guard page, against 2 to 3.4 of the counter: docs/experiments/stack_limit/). Where neither option is chosen the runtime defines the prologue empty; this puts the check there,
# for a build that defines WASMEXT_STACK_LIMIT (see `signal_build_flags`, and wasmext_glue.h for the limit of the thread). Any other build keeps the empty prologue.
# The pattern matches only the text of 1.0.42, so a wasm2c that has the branch written otherwise passes through (and the build has no limit: test_patches_needed.py).
_STACK_LIMIT_BRANCH = re.compile(rb"#else\n#define FUNC_PROLOGUE\n\n#define FUNC_EPILOGUE\n#endif")
_STACK_LIMIT_CHECKED = (
    b"#elif defined(WASMEXT_STACK_LIMIT)\n"
    b'extern __thread uintptr_t wasmext_stack_limit __attribute__((visibility("hidden")));\n'
    b"#define FUNC_PROLOGUE \\\n"
    b"  if (__builtin_expect((uintptr_t)__builtin_frame_address(0) < wasmext_stack_limit, 0)) TRAP(EXHAUSTION);\n\n"
    b"#define FUNC_EPILOGUE\n"
    b"#else\n#define FUNC_PROLOGUE\n\n#define FUNC_EPILOGUE\n#endif"
)


def _stack_limit_prologue(c_source: bytes) -> bytes:
    return _STACK_LIMIT_BRANCH.sub(lambda _m: _STACK_LIMIT_CHECKED, c_source)


def _tail_call_locals(c_source: bytes) -> bytes:
    return _TAIL_CALL_LOCALS.sub(_TAIL_CALL_LOCALS_FIXED, c_source)


# wasm2c 1.0.42 loses the result of a `return_call_indirect` in the tail-callable form of a function when the function it calls has no
# tail-callable form of its own: it calls it as a plain function, keeps the result in `var_i0`, and returns without putting it in
# `tail_call_stack`, so the caller of the chain reads garbage. The label `var_Bfunc` is where the form puts its results there; go to it. The
# pattern matches only that shape (the `next->fn = NULL;` after a plain `CALL_INDIRECT` in a `func_tailcallee` test), so a wasm2c that is fixed passes through.
_TAIL_CALL_RESULT = re.compile(
    rb"^(    [^\n]*CALL_INDIRECT\([^\n]*\);\n)    next->fn = NULL;\n(  \} else \{\n)",
    re.MULTILINE,
)
_TAIL_CALL_RESULT_FIXED = rb"\1    goto var_Bfunc;\n\2"


def _tail_call_result(c_source: bytes) -> bytes:
    return _TAIL_CALL_RESULT.sub(_TAIL_CALL_RESULT_FIXED, c_source)


def _repair_tail_calls(c_source: bytes) -> bytes:
    """The two repairs of the C of `return_call` and `return_call_indirect` that wasm2c 1.0.42 writes."""
    return _tail_call_result(_tail_call_locals(c_source))


# wasm2c 1.0.42 and `main` (read on 2026-10-22) give an *imported* function that an element segment puts into a table the wrong module instance: the entry is
# `{RefFunc, type, wrapper, {tailcall}, offsetof(w2c_m, w2c_<import>_instance)}` and `funcref_table_init` stores `(char*)module_instance + module_offset`, the address
# of the field that holds the pointer to the import's instance (with offset 0, the first field, the module instance itself). A `call_indirect` of that entry hands the wrapper
# of the import a pointer to something else. (`ref.func` as an expression is right: it writes `instance->w2c_<import>`.) The output of `meld fuse` has such a table.
# The repair gives the imports a kind of entry of their own that reads the pointer, as `GlobalGet` does. The template (an enum and a `switch`, in the file that has
# `funcref_table_init`: the one file, or `<name>_w2c-impl.h`) is looked for in all the files, and the entries (in the files of the code) are rewritten only if it is
# found in this shape, so a wasm2c that is fixed passes through. Entries of defined functions have the literal offset `0` and are not touched.
# Reported: [WABT #2896](https://github.com/WebAssembly/wabt/issues/2896).
_ELEM_KINDS = re.compile(rb"typedef enum \{ RefFunc, RefNull, GlobalGet \} wasm_elem_segment_expr_type_t;")
_ELEM_REF_FUNC = re.compile(
    rb"      case RefFunc:\n"
    rb"        \*dest_val = \(wasm_rt_funcref_t\)\{\n"
    rb"            src_expr->type, src_expr->func, src_expr->func_tailcallee,\n"
    rb"            \(char\*\)module_instance \+ src_expr->module_offset\};\n"
    rb"        break;\n"
)
_ELEM_IMPORT_CASE = (
    b"      case RefImportFunc:\n"
    b"        *dest_val = (wasm_rt_funcref_t){\n"
    b"            src_expr->type, src_expr->func, src_expr->func_tailcallee,\n"
    b"            *(void**)((char*)module_instance + src_expr->module_offset)};\n"
    b"        break;\n"
)
_ELEM_ENTRY = re.compile(rb"^(  \{)RefFunc(, [^\n]*, offsetof\()", re.MULTILINE)


def _repair_imported_elements(c_sources: Sequence[bytes]) -> list[bytes]:
    """The files of the C of one module, with the element segments that hold imported functions repaired (see above); all the files, because the template and the entries are not in the same one."""
    if not any(_ELEM_REF_FUNC.search(text) for text in c_sources):
        return list(c_sources)
    repaired: list[bytes] = []
    for text in c_sources:
        if b"RefImportFunc" not in text:
            text = _ELEM_KINDS.sub(
                b"typedef enum { RefFunc, RefNull, GlobalGet, RefImportFunc } wasm_elem_segment_expr_type_t;", text
            )
            text = _ELEM_REF_FUNC.sub(lambda m: m.group(0) + _ELEM_IMPORT_CASE, text)
            text = _ELEM_ENTRY.sub(rb"\1RefImportFunc\2", text)
        repaired.append(text)
    return repaired


# the tags of the module, as wasm2c declares them (in the order of the tags): `static` in a file of its own, a definition in the first of
# several (the others see them as extern in <name>_w2c-impl.h)
_TAG_PLACEHOLDER = re.compile(rb"^(?:static )?const wasm_tag_placeholder_t (\w+);$", re.MULTILINE)


def _export_tags(c_source: bytes, prefix: str) -> bytes:
    """Where wasm2c defines the tags of a module, the identities of them in a table `wasmext_tags_<prefix>` that the glue can name (the
    tags themselves are `static`, or have names that depend on the export): the glue tells an exception that nothing caught by it."""
    names = _TAG_PLACEHOLDER.findall(c_source)
    if not names:
        return c_source
    plain = _TAG_PLACEHOLDER.sub(rb"const wasm_tag_placeholder_t \1;", c_source)
    entries = b", ".join(b"&" + n for n in names)
    table = f"\nconst wasm_rt_tag_t wasmext_tags_{prefix}[{len(names)}] = {{".encode() + entries + b"};\n"
    return plain.rstrip(b"\n") + b"\n" + table


def _simde_include(w2c_files: list[Path]) -> tuple[str, ...]:
    """The directory with `simde/` when the C of the module includes it, else nothing. It is looked for in the toolchain
    only then, so a tree that ships its C and has no SIMD still builds without the wabt-package."""
    w2c_c = w2c_files[0]
    headers_of = [w2c_c.with_suffix(".h")]
    if len(w2c_files) > 1:  # the first part is `<name>_w2c_0.c`: the headers are `<name>_w2c.h` and `<name>_w2c-impl.h`
        stem = w2c_c.name[: -len("_0.c")]
        headers_of = [w2c_c.with_name(f"{stem}.h"), w2c_c.with_name(f"{stem}-impl.h")]
    if not any(_USES_SIMDE.search(p.read_bytes()) for p in (*w2c_files, *headers_of) if p.is_file()):
        return ()
    headers = find_toolchain().include
    if headers is None or not (headers / "simde").is_dir():
        raise RuntimeError(
            f"{w2c_c} includes simde (the module uses SIMD), but the headers of simde are not there: they come with "
            "wabt-package 1.0.42.0 or later (or an `include/simde` in the directory of WASMEXT_WABT)"
        )
    return (str(headers),)


def _shared_headers(glue: Glue) -> tuple[str, ...]:
    """The headers of wasmext that the glue includes: the glue that every module has, and for WASI the ones that the snapshots share."""
    return (*GLUE_SHARED, *WASI_SHARED, *glue.wasi_headers) if glue.wasi_headers else GLUE_SHARED


def _write_atomic(path: Path, data: bytes) -> None:
    """Whole or not at all: two builds of one project (several Pythons, in parallel) share build/wasmext/ and must never read half a file."""
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def _write_if_changed(path: Path, data: bytes) -> None:
    if not path.is_file() or path.read_bytes() != data:
        _write_atomic(path, data)


def _prepare(
    wasm: Path,
    name: str,
    out_dir: Path,
    *,
    force: bool,
    quiet: bool,
    stubs: bool,
    parts: int | None,
    share_tables: bool = False,
) -> _Prepared:
    last = name.rsplit(".", 1)[-1]
    data = wasm.read_bytes()
    digest = wasm_digest(data)
    glue_c = out_dir / f"{last}_py.c"  # the Python layer; the glue of the module, {last}_glue.h, is beside it
    wanted = _choose_parts(len(data), parts)

    def outputs(skipped: list[str], count: int) -> _Prepared:
        files = _w2c_files(out_dir, last, count)
        sources = [glue_c, *files, *(out_dir / f"{last}_rt_{key}.c" for key in _RUNTIME_WRAPPERS)]
        depends = [
            out_dir / f"{last}_w2c.h",
            out_dir / f"{last}_glue.h",
            wasm,
        ]
        if count > 1:
            depends.append(out_dir / f"{last}_w2c-impl.h")
        depends.extend(out_dir / n for n in _shared_headers(glue))  # headers only: the glue includes them
        return _Prepared(
            [_rel(p) for p in sources],
            [_rel(p) for p in depends],
            _rel(out_dir),
            skipped,
            (str(find_toolchain().runtime), *_simde_include(files)),
            count,
            glue,
            parsed,
        )

    # The glue and the stub come from the module alone (no wasm2c, no compiler), so they are always made: a module that
    # cannot be wrapped is reported on every run, and a stub deleted from a tree that ships its C is written again.
    try:
        parsed = parse(data)
        glue = generate(parsed, name, version=_release_version(), share_tables=share_tables)
    except (WasmError, GenError) as exc:
        raise type(exc)(f"{wasm}: {exc}") from None
    if not quiet and (hint := wasi_hint(data)):
        print(f"wasmext: {wasm}: {hint}", file=sys.stderr)
    if (
        not quiet
        and (note := _parts_warning(wanted, len(data), len(parsed.functions)))
        and (parts or os.environ.get("WASMEXT_PARTS"))
    ):
        print(f"wasmext: {wasm}: {note}", file=sys.stderr)  # only for a number somebody asked for
    out_dir.mkdir(parents=True, exist_ok=True)
    if (
        stubs
    ):  # a part of the extension: the build puts it beside the extension, where it is built (build/lib.*, or in place)
        _write_if_changed(out_dir / f"{last}.pyi", glue.stub.encode("utf-8"))
    # the C that wasmext brings, and the glue of the module, beside the C of the module (not made by wasm2c, so always put there)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_if_changed(out_dir / f"{last}_glue.h", glue.header.encode("utf-8"))
    for c_name in _shared_headers(glue):
        _write_if_changed(out_dir / c_name, (C_DIR / c_name).read_bytes())

    # As cythonize() does, but by the content of the .wasm and not by its time (a cache, a copy or an archive does not keep the times): the C is made
    # again when it is missing, was made by another wasmext (or WABT) or from another .wasm, or when forced (`force`, or WASMEXT_FORCE_REGEN=1 for build systems). A tree that has the C in a
    # number of files other than the one wanted is made again too, where there is a wasm2c to do it; where there is none,
    # what is there is used.
    force = force or os.environ.get("WASMEXT_FORCE_REGEN") == "1"
    have = _existing_parts(out_dir, last)
    first = _w2c_files(out_dir, last, have)[0] if have else None
    complete = bool(have) and all(p.is_file() for p in (glue_c, out_dir / f"{last}_rt_impl.c"))
    if not force and complete and first is not None and _made_by_this_wasmext(first, digest, name, share_tables):
        if have == wanted:
            return outputs(glue.skipped, have)
        try:
            find_toolchain()
        except RuntimeError:
            return outputs(glue.skipped, have)

    toolchain: Toolchain = find_toolchain()
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in (out_dir / f"{last}_w2c.c", *out_dir.glob(f"{last}_w2c_*.c"), out_dir / f"{last}_w2c-impl.h"):
        old.unlink(missing_ok=True)  # what a run with another number of files left
    # wasm2c is given the module with ordinary imports where it has compact ones: WABT reads them differently from the proposal (see expand_compact_imports)
    with tempfile.TemporaryDirectory() as scratch:
        source = wasm
        if (plain := expand_compact_imports(data, parsed)) is not data:
            source = Path(scratch) / wasm.name
            source.write_bytes(plain)
        command = [str(toolchain.wasm2c), str(source), "-o", str(out_dir / f"{last}_w2c.c"), f"--module-name={last}"]
        if wanted > 1:
            command.append(f"--num-outputs={wanted}")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"wasm2c failed on {wasm}:\n{result.stderr.strip()}")
    shared = out_dir / f"{last}_w2c-impl.h"  # the code every file includes, when there are several
    code_files = _w2c_files(out_dir, last, wanted)
    # the repair of imported functions in element segments looks at all the files of the module (the template may be in `shared`, the entries in the others)
    all_files = [*code_files, *([shared] if shared.is_file() else [])]
    repaired = dict(zip(all_files, _repair_imported_elements([f.read_bytes() for f in all_files]), strict=True))
    for part in code_files:
        _write_atomic(
            part,
            _marker(toolchain.version, wanted, digest, name, share_tables).encode()
            + _export_tags(_repair_tail_calls(_portable(repaired[part])), module_prefix(name)),
        )
    if shared.is_file():
        _write_atomic(shared, _portable(repaired[shared]))
    _write_if_changed(
        glue_c, (_marker(toolchain.version, wanted, digest, name, share_tables) + glue.source).encode("utf-8")
    )
    for key, text in _RUNTIME_WRAPPERS.items():
        _write_if_changed(out_dir / f"{last}_rt_{key}.c", text.encode())
    if glue.skipped and not quiet:
        for item in glue.skipped:
            print(f"wasmext: {wasm}: not exposed: {item}", file=sys.stderr)
    if glue.notes and not quiet:
        for item in glue.notes:
            print(f"wasmext: {wasm}: {item}", file=sys.stderr)
    return outputs(glue.skipped, wanted)


def generate_c(
    wasm: Path,
    name: str,
    out_dir: Path,
    *,
    force: bool,
    quiet: bool,
    stubs: bool,
    parts: int | None,
    share_tables: bool = False,
) -> Generated:
    """The C of `wasm` for every target that the module can have, written in `out_dir`: the C of wasm2c, its runtime and the glue (the same for all of them), and the front end of each
    target: `<name>_py.c` (an extension), `<name>_api.h` and `<name>_shared.c` (a shared library), `<name>_main.c` (a program). A target that the module cannot have is left out and the reason is
    kept in `targets` (a library of a module whose import has no type in C; a program of a module that is not a WASI command). Nothing is compiled: the build chooses the sources of its product, so
    the C that is made for one product is the C of the others too, and a source distribution carries all of it."""
    from ._exe import main_c, program_problem

    prepared = _prepare(
        wasm, name, out_dir, force=force, quiet=quiet, stubs=stubs, parts=parts, share_tables=share_tables
    )
    last = name.rsplit(".", 1)[-1]
    glue, parsed = prepared.glue, prepared.parsed
    common = [
        s for s in prepared.sources if not s.endswith(f"{last}_py.c")
    ]  # the C of wasm2c and the runtime: every target compiles it
    written: list[Path] = []

    def put(file: str, text: str) -> Path:
        target = out_dir / file
        if not target.is_file() or target.read_text("utf-8") != text:
            target.write_text(text, encoding="utf-8")
        written.append(target)
        return target

    targets = {"extension": Target(list(prepared.sources))}
    if glue.shared_unsupported or not glue.shared:
        targets["shared"] = Target(
            [], f"no shared library yet: {glue.shared_unsupported or 'the module has no API in C'}"
        )
    else:
        put(f"{last}_api.h", glue.api_header)
        shared_c = put(f"{last}_shared.c", glue.shared)
        targets["shared"] = Target([*common, shared_c.as_posix()])
    problem = program_problem(parsed)
    if problem:
        targets["exe"] = Target([], problem)
    else:
        main_path = put(f"{last}_main.c", main_c(last, module_prefix(last)))
        targets["exe"] = Target([*common, main_path.as_posix()])
    files = [*prepared.sources, *prepared.depends, *(_rel(p) for p in written)]
    skipped = [item for item in glue.skipped if "is not an attribute" not in item]
    return Generated(last, out_dir, prepared, targets, list(dict.fromkeys(files)), skipped)


def natify(
    module_list: str | os.PathLike[str] | Extension | Iterable[str | os.PathLike[str] | Extension],
    exclude: Iterable[str] | None = None,
    *,
    build_dir: str | os.PathLike[str] | None = None,
    force: bool = False,
    quiet: bool = False,
    stubs: bool = True,
    limited_api: bool | None = None,
    guard_pages: bool | str | Mapping[str, bool] | None = None,
    parts: int | None = None,
    share_tables: bool = False,
    product: str = "extension",
) -> list[Extension]:
    """The extensions for the `.wasm` modules in `module_list`, ready for `setup(ext_modules=...)`.

    `module_list` is a glob pattern, a list of them, or `Extension` objects whose `sources` have one `.wasm` (it may
    also have glob patterns, and more sources, which are kept): the other settings of the `Extension` (`libraries`,
    `define_macros`, ...) are kept too and its `name` is the module's name. Without an `Extension` the name is made of
    the path: the packages the file is in (directories with `__init__.py`), then its stem.

    `exclude` is glob patterns of files to leave out. The C is written in `build/wasmext/<module name>/` or, with
    `build_dir`, in `build_dir/<module name>/`. It is made again when it is missing, was made by another wasmext or WABT or
    from another `.wasm` (the macros WASMEXT_GENERATED_* at the head of the file say which), or with `force` (or WASMEXT_FORCE_REGEN=1). `quiet` stops the notes about exports that are not exposed.

    `limited_api` chooses between the stable ABI (abi3: one wheel for CPython 3.11 and later, tagged `cp311-abi3` by
    wasmext itself) and one native extension per interpreter. None, the default, is abi3 wherever the interpreter that builds
    has a stable ABI (not PyPy, free-threaded, Emscripten, Android, iOS): with `cibuildwheel`, the selector `cp311-*` makes
    the abi3 wheel and `cp314t-*` a native one. WASMEXT_LIMITED_API=0 turns abi3 off for a None; True and False decide in
    the code (True still builds native where abi3 is impossible, and says so).

    `guard_pages` (None, the default, is True unless WASMEXT_GUARD_PAGES says otherwise; a bool, or a mapping `{"x86": False, "armv7l": False, "default": True}` of the architectures
    the extension is built for, as text `x86=off,default=on` too) is how the memories of the modules are checked
    and allocated. True reserves 8 GiB of address space for each memory and catches out-of-bounds accesses with the
    MMU (fast), which fails, with an abort() of the runtime, in a process whose address space is limited. False
    allocates what the memory needs and checks every access in code (a bit slower).

    `parts` is how many files the C of a module is written in (`wasm2c --num-outputs`), which setuptools then compiles at the same
    time (WASMEXT_JOBS sets how many at once; the default is the number of processors). None, the default, is WASMEXT_PARTS if
    that is set, else one file for a module smaller than 1 MiB and a file for each 128 KiB of a larger one (at most 256); 1 turns
    the splitting off, and a number asked for has no upper limit (a warning says when it is unwise: more files than functions,
    or less than 4 KiB of the module in a file). A split costs some speed of the code (a call from one file to another is not inlined), so a small
    module is better whole; for a big one it is the difference between minutes and an hour.

    `share_tables` builds the modules with the stack of entries for traps that modules with a `funcref` table share, whether or not they have one, so
    that a function of such a module can be put in a table (`Table.set`) and a trap in it comes back to the caller. A module that imports or exports a
    funcref table shares tables whatever this says. The option is an input of the C (a change makes it again), costs a call into the module a few
    nanoseconds more, and gives the module the class `Table`.

    `product` is what is made of each module: `"extension"` (the default, a Python extension), `"shared"` (a shared library with a C API, and
    beside it a `<stem>_ctypes.py` wrapper with the interface of the extension) or `"exe"` (a program, for a command with a `_start`). One product
    for each call: a module that is wanted in two ways is two calls (or two tables of `pyproject.toml`). The result is still `Extension` objects, marked
    for `wasmext._setuptools`, whose `build_ext` makes the file and puts it where an extension would go; the settings of the extension
    (`libraries`, `define_macros`, `extra_compile_args`, ...) are the flags of the build. A shared library is `lib<stem>.so`, `lib<stem>.dylib`
    or `<stem>.dll`; a program is `<stem>` or `<stem>.exe`. `limited_api` and `stubs` are for extensions and do nothing for the other products.

    With `stubs` (the default) a `<stem>.pyi` is made with the C and the build puts it beside the extension: the types of the extension for editors and type
    checkers (ship it in the wheel with `package-data`).
    """
    return [
        ext
        for _, ext in _natify(
            module_list,
            exclude,
            build_dir=build_dir,
            force=force,
            quiet=quiet,
            stubs=stubs,
            limited_api=limited_api,
            guard_pages=guard_pages,
            parts=parts,
            share_tables=share_tables,
            product=product,
        )
    ]


def _natify(
    module_list: str | os.PathLike[str] | Extension | Iterable[str | os.PathLike[str] | Extension],
    exclude: Iterable[str] | None,
    *,
    build_dir: str | os.PathLike[str] | None,
    force: bool,
    quiet: bool,
    stubs: bool,
    limited_api: bool | None,
    guard_pages: bool | str | Mapping[str, bool] | None = None,
    parts: int | None = None,
    share_tables: bool = False,
    product: str = "extension",
) -> list[tuple[Path | None, Extension]]:
    """`natify()` with the `.wasm` file of each extension (None for an ordinary extension that passed through)."""
    from setuptools import Extension  # a build-time dependency of the projects that call this

    if product not in PRODUCTS:
        raise ValueError(f"product must be one of {', '.join(map(repr, PRODUCTS))}, not {product!r}")
    use_limited_api = _use_limited_api(limited_api, quiet) if product == "extension" else False
    use_guard_pages = _guard_pages(guard_pages)

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
        out_dir = Path(build_dir if build_dir is not None else DEFAULT_BUILD_DIR) / name
        # The C of every target is made now (so a source distribution carries it, and a file of it can be named in package-data on the first build);
        # the build, here or in wasmext._setuptools, only chooses the sources of the product that was asked for.
        generated = generate_c(
            wasm,
            name,
            out_dir,
            force=force,
            quiet=quiet,
            stubs=stubs and product == "extension",
            parts=parts,
            share_tables=share_tables,
        )
        prepared = generated.prepared
        chosen = generated.targets[product]
        if chosen.reason:
            raise GenError(f"{wasm}: {chosen.reason}")
        if product != "extension":
            ext = copy.copy(template) if template else Extension(name, [])
            ext.name = name
            ext.sources = [wasm.as_posix()]
            ext.depends = [*ext.depends, *_absolute(generated.files)]
            if not use_guard_pages:
                ext.define_macros = [*ext.define_macros, ("WASM_RT_USE_MMAP", "0")]
            ext._wasmext_made = True  # type: ignore[attr-defined]
            ext._wasmext_product = product  # type: ignore[attr-defined]
            ext._wasmext_generated = generated  # type: ignore[attr-defined]
            settings = {
                "work": out_dir.resolve(),
                "parts": parts,
                "share_tables": share_tables,
                "quiet": quiet,
                "force": force,
            }
            ext._wasmext_settings = settings  # type: ignore[attr-defined]
            result.append((wasm, ext))
            return
        ext = copy.copy(template) if template else Extension(name, [])
        ext.name = name
        if stubs:
            ext._wasmext_stub = str((out_dir / f"{wasm.stem}.pyi").resolve())  # type: ignore[attr-defined]
        ext._wasmext_wasm = wasm.as_posix()  # type: ignore[attr-defined]  # a source of the extension that is not in `sources` (they are the generated C): the sdist has to carry it
        ext._wasmext_limited_api = limited_api  # type: ignore[attr-defined]  # what was asked (None: whatever the interpreter allows), for wasmext._setuptools to make the wheel consistent
        rest = [s for s in (template.sources if template else []) if not str(s).endswith(".wasm")]
        ext.sources = [*rest, *chosen.sources]
        ext._wasmext_parallel = prepared.parts > 1  # type: ignore[attr-defined]  # wasmext._setuptools compiles the files at once
        ext._wasmext_made = True  # type: ignore[attr-defined]  # made by natify(): the table of pyproject.toml is not for a project that calls it
        ext.depends = [*ext.depends, *_absolute(f for f in generated.files if f not in chosen.sources)]
        ext.include_dirs = [
            *ext.include_dirs,
            *prepared.extra_include_dirs,
            prepared.include_dir,
        ]  # the C dir stays last
        if not use_guard_pages:
            ext.define_macros = [*ext.define_macros, ("WASM_RT_USE_MMAP", "0")]
        chain_macros, chain_link = signal_build_flags()
        ext.define_macros = [*ext.define_macros, *chain_macros]
        if chain_link:
            ext.extra_link_args = [*(ext.extra_link_args or []), *chain_link]
        if prepared.glue.trap_handler:  # the module shares tables with other instances
            ext.define_macros = [*ext.define_macros, ("WASMEXT_TRAP_HANDLER", prepared.glue.trap_handler)]
        if sys.byteorder == "big":  # the C of wasm2c reads this to lay the memory out reversed; nothing else sets it
            ext.define_macros = [*ext.define_macros, ("WABT_BIG_ENDIAN", "1")]
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
