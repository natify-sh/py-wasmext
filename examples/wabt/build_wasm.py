"""Build `wat2wasm` and `wasm2c` of WABT as WASI programs (`src/wabtwasm/_wat2wasm.wasm`, `_wasm2c.wasm`) with `zig c++` (the `ziglang`
package) as wasm32-wasi.

    uv run --group wasm python examples/wabt/build_wasm.py                 # clones https://github.com/WebAssembly/wabt
    uv run --group wasm python examples/wabt/build_wasm.py --wabt DIR      # a checkout you already have (with third_party/picosha2)

The sources are those of the tag below, as they are. What CMake does is done here: `config.h` is made from `src/config.h.in` (for clang, 32-bit,
no exceptions), the flags are those of the CMake build (C++20, `-fno-exceptions`), and the files of the library are compiled once and linked into
each tool. The interpreter (`src/interp`) is left out: these tools do not use it. The stack is 8 MiB, as the CMake build asks of MSVC: the parser
of the text format is recursive and a real module nests deeply.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "src" / "wabtwasm"
REPO = "https://github.com/WebAssembly/wabt"
TAG = "1.0.42"

LIBRARY = [
    "apply-names",
    "binary-reader-ir",
    "binary-reader-logging",
    "binary-reader",
    "binary-writer-spec",
    "binary-writer",
    "binary",
    "binding-hash",
    "color",
    "common",
    "config",
    "error-formatter",
    "expr-visitor",
    "feature",
    "filenames",
    "generate-names",
    "ir-util",
    "ir",
    "leb128",
    "lexer-source-line-finder",
    "lexer-source",
    "literal",
    "opcode",
    "option-parser",
    "resolve-names",
    "sha256",
    "shared-validator",
    "stream",
    "token",
    "tracing",
    "type-checker",
    "utf8",
    "validator",
    "wast-lexer",
    "wast-parser",
    "wat-writer",
    "c-writer",
]
EXTRA = ["opcode-code-table.c"]  # C, not C++
PREBUILT = [
    "wasm2c_header_top",
    "wasm2c_header_bottom",
    "wasm2c_source_includes",
    "wasm2c_source_declarations",
    "wasm2c_simd_source_declarations",
    "wasm2c_atomicops_source_declarations",
]
TOOLS = {"wat2wasm": ["src/tools/wat2wasm.cc"], "wasm2c": ["src/tools/wasm2c.cc"]}
DEFINES = [
    "__STDC_LIMIT_MACROS=1",
    "__STDC_FORMAT_MACROS=1",
    "_POSIX_C_SOURCE=200809L",
    "_WASI_EMULATED_PROCESS_CLOCKS",
    "_WASI_EMULATED_SIGNAL",
]
CXXFLAGS = ["-std=c++20", "-O2", "-fno-exceptions", "-Wno-deprecated-declarations", "-w"]
CONFIG = {
    "HAVE_ALLOCA_H": 1, "HAVE_UNISTD_H": 1, "HAVE_SNPRINTF": 1, "HAVE_SSIZE_T": 1, "HAVE_STRCASECMP": 1, "HAVE_WIN32_VT100": 0,
    "WABT_BIG_ENDIAN": 0, "HAVE_OPENSSL_SHA_H": 0, "COMPILER_IS_CLANG": 1, "COMPILER_IS_GNU": 0, "COMPILER_IS_MSVC": 0, "WITH_EXCEPTIONS": 0,
}  # fmt: skip


def make_config(src: Path, build: Path) -> Path:
    """`wabt/config.h` of the CMake build, for this target."""
    text = (src / "src" / "config.h.in").read_text(encoding="utf-8")
    text = text.replace(
        '#cmakedefine WABT_VERSION_STRING "@WABT_VERSION_STRING@"', f'#define WABT_VERSION_STRING "{TAG}"'
    )
    text = text.replace("#cmakedefine WABT_DEBUG @WABT_DEBUG@", "")
    text = re.sub(r"#cmakedefine01 (\w+)", lambda m: f"#define {m.group(1)} {CONFIG[m.group(1)]}", text)
    text = text.replace("@SIZEOF_SIZE_T@", "4")
    include = build / "include" / "wabt"
    include.mkdir(parents=True, exist_ok=True)
    (include / "config.h").write_text(text, encoding="utf-8")
    make_picosha2(src, build / "include")
    return build / "include"


# picosha2 (a header of WABT, in third_party) has a function that hashes a std::ifstream, which the libc++ of wasm32-wasi does not accept
# (`std::istreambuf_iterator<char>(std::ifstream)`); WABT hashes bytes and never calls it. The copy of the header that is compiled has no such function.
_IFSTREAM_OVERLOAD = re.compile(
    r"template<typename OutIter>void hash256\(std::ifstream& f, OutIter first, OutIter last\)\{\s*"
    r"hash256\(std::istreambuf_iterator<char>\(f\), std::istreambuf_iterator<char>\(\), first,last\);\s*\}"
)


def make_picosha2(src: Path, include: Path) -> None:
    text = (src / "third_party" / "picosha2" / "picosha2.h").read_text(encoding="utf-8")
    text, count = _IFSTREAM_OVERLOAD.subn("", text)
    if count != 1:
        raise RuntimeError(
            "picosha2.h is not the one this script knows (the overload for std::ifstream is not there once)"
        )
    (include / "picosha2.h").write_text(text, encoding="utf-8")


def zig(*args: str | Path) -> list[str]:
    return [sys.executable, "-m", "ziglang", *map(str, args)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--wabt", type=Path, help=f"a checkout of {REPO} at {TAG}, with third_party/picosha2 (default: a fresh clone)"
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        src = args.wabt
        if src is None:
            src = build / "wabt"
            subprocess.run(["git", "clone", "--depth", "1", "--branch", TAG, REPO, str(src)], check=True)
            subprocess.run(
                ["git", "submodule", "update", "--init", "--depth", "1", "third_party/picosha2"], cwd=src, check=True
            )
        generated = make_config(src, build)
        includes = [f"-I{src / 'include'}", f"-I{generated}", f"-I{src / 'src'}"]
        defines = [f"-D{d}" for d in DEFINES]
        sources = (
            [f"src/{name}.cc" for name in LIBRARY]
            + [f"src/{name}" for name in EXTRA]
            + [f"src/prebuilt/{name}.cc" for name in PREBUILT]
        )
        sources += [s for tool in TOOLS.values() for s in tool]
        objects = build / "obj"
        objects.mkdir()

        def compile_one(source: str) -> Path:
            target = objects / (source.replace("/", "_") + ".o")
            language = [] if source.endswith(".c") else CXXFLAGS
            tool = "cc" if source.endswith(".c") else "c++"
            subprocess.run(
                zig(tool, "-target", "wasm32-wasi", *language, *defines, *includes, "-c", src / source, "-o", target),
                check=True,
            )
            return target

        with ThreadPoolExecutor() as pool:
            compiled = dict(zip(sources, pool.map(compile_one, sources), strict=True))
        tool_sources = {s for tool in TOOLS.values() for s in tool}
        library = [o for s, o in compiled.items() if s not in tool_sources]
        for name, parts in TOOLS.items():
            out = OUT / f"_{name}.wasm"
            subprocess.run(
                zig("c++", "-target", "wasm32-wasi", "-O2", "-s", "-Wl,-z,stack-size=8388608",
                    *[compiled[p] for p in parts], *library,
                    "-lwasi-emulated-process-clocks", "-lwasi-emulated-signal", "-o", out),
                check=True,
            )  # fmt: skip
            print(f"{out} ({out.stat().st_size} bytes)")
        # The runtime of the C that wasm2c writes (wasm-rt.h, ...), of the same version: the package carries it, so that a directory for WASMEXT_WABT can
        # be made of it (`python -m wabtwasm toolchain DIR`).
        runtime = OUT / "runtime"
        runtime.mkdir(exist_ok=True)
        for old in runtime.iterdir():
            old.unlink()
        for file in sorted((src / "wasm2c").glob("wasm-rt*")):
            (runtime / file.name).write_bytes(file.read_bytes())
        (runtime / "WABT_VERSION").write_text(TAG + "\n", encoding="utf-8")
        print(f"{runtime} ({len(list(runtime.iterdir()))} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
