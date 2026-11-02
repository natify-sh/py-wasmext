"""Step 8b-1 of docs/specs/S0008-shared-store.md: the table of the runtime of a store and the forwarders `wasm_rt_*`.

The C test is tests/c/test_runtime.c (built as the product builds, with the wrappers of `_natify`); the rest checks what the wrappers rest on: the names of wasm2c 1.0.42 (D6: tied to the version, loud
when it changes), the text the wrapper tests in `__func__`, the old layer 3 wrappers (unchanged without the macro) and the symbols of a library."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from wasmext._natify import _RENAMED, _RUNTIME_WRAPPERS
from wasmext._toolchain import find_toolchain

from .c_build import find_cc
from .test_artifacts import LIBA, WASMEXT_C, _library
from .test_instance_core import OPS, _run, build  # noqa: F401  # pyright: ignore[reportUnusedImport]  (a fixture is found by name in the module that imports it)

# the functions of wasm2c 1.0.42 that generated code and the core do not call through the runtime of the store: the set-up of a thread (D44, 8b-3b), the strings of a trap, the
# segue base of x86-64 (a register of the thread, nothing to forward)
_NOT_FORWARDED = {
    "wasm_rt_init",
    "wasm_rt_free",
    "wasm_rt_init_thread",
    "wasm_rt_free_thread",
    "wasm_rt_is_initialized",
    "wasm_rt_strerror",
    "wasm_rt_syscall_set_segue_base",
    "wasm_rt_syscall_get_segue_base",
}
_WRAPPED_NAMES = [f"wasm_rt_{n}" for names in _RENAMED.values() for n in names]
_VERSION = "1.0.42"


def test_the_forwarders_reach_the_runtime_of_the_table(build: Callable[..., Path]) -> None:  # noqa: F811
    """With a stub runtime in `tls.rt` each of the 23 `wasm_rt_*` goes to the stub's function and to no other; with it NULL the copy's own function runs."""
    _run(build(OPS, "ops", "test_runtime.c"))


def test_the_renaming_rests_on_the_names_of_this_version_of_wasm2c() -> None:
    """The renaming is written for the runtime of wasm2c 1.0.42 (D6). A new version may add or rename a function that generated code or the core calls: then it must be forwarded too (D-6)."""
    toolchain = find_toolchain()
    assert toolchain.version == _VERSION, (
        f"the wrappers of the runtime (_RENAMED in _natify.py) were written for wasm2c {_VERSION}, the toolchain is {toolchain.version}: read the runtime again "
        "(wasm-rt.h, wasm-rt-exceptions.h, the three *-impl.c files) and update _RENAMED, the table wasmext_runtime and the forwarders"
    )
    declared: set[str] = set()
    for header in ("wasm-rt.h", "wasm-rt-exceptions.h"):
        text = (toolchain.runtime / header).read_text(encoding="utf-8")
        declared |= set(
            re.findall(r"^(?:WASM_RT_NO_RETURN\s+)?[A-Za-z_][\w\s\*]*?\b(wasm_rt_\w+)\s*\(", text, re.MULTILINE)
        )
    assert sorted(set(_WRAPPED_NAMES)) == sorted(declared - _NOT_FORWARDED), (
        f"the functions the runtime declares and the ones _natify._RENAMED forwards differ: only declared {sorted(declared - _NOT_FORWARDED - set(_WRAPPED_NAMES))}, "
        f"only renamed {sorted(set(_WRAPPED_NAMES) - declared)}"
    )
    assert len(_WRAPPED_NAMES) == 23
    sources = {
        "impl": ["wasm-rt-impl.c", "wasm-rt-impl-tableops.inc"],
        "exceptions": ["wasm-rt-exceptions-impl.c", "wasm-rt-impl-tableops.inc"],
        "mem": ["wasm-rt-mem-impl.c", "wasm-rt-mem-impl-helper.inc"],
    }
    for key, files in sources.items():
        text = "".join((toolchain.runtime / f).read_text(encoding="utf-8") for f in files)
        for name in _RENAMED[key]:
            # the table functions and the memory ones are named by a macro: `wasm_rt_allocate` + `_funcref_table`, `MEMORY_API_NAME(wasm_rt_allocate_memory)`
            stem = re.sub(r"_(funcref|externref|exnref)_table$", "", f"wasm_rt_{name}")
            stem = re.sub(r"_shared$", "", stem)
            assert stem in text, (
                f"the {key} file of the runtime has no {stem!r}: the name changed in this wasm2c, update _RENAMED"
            )
    exceptions = (toolchain.runtime / "wasm-rt-exceptions-impl.c").read_text(encoding="utf-8")
    assert "static WASM_RT_THREAD_LOCAL wasm_rt_jmp_buf* g_unwind_target;" in exceptions, (
        "g_unwind_target is no longer a static of the exceptions file: the same-file accessors of the wrapper (8b-2) were written for that"
    )


def test_the_nomemory_test_names_the_renamed_function() -> None:
    """The wrapper of the memory file turns the abort() of a failed allocation into the trap NO_MEMORY by the name of the function it is in (`__func__`), which the renaming changed: the name it compares
    and the length must be those of the renamed function, or the process aborts again (tests/c/test_nomemory.c is the proof; this is the cause)."""
    text = _RUNTIME_WRAPPERS["mem"]
    found = re.findall(r'strncmp\(where, "(\w+)", (\d+)\)', text)
    assert ("wasmext_own_wasm_rt_allocate_memory", "35") in found and ("wasm_rt_allocate_memory", "23") in found
    for name, length in found:
        assert len(name) == int(length), f"strncmp compares {length} characters of {name!r}, which has {len(name)}"


def _preprocess(key: str, tmp_path: Path, defines: list[str]) -> str:
    cc = find_cc()
    if cc is None:
        pytest.skip("no C compiler of the cc kind")
    path = tmp_path / f"rt_{key}.c"
    path.write_text(_RUNTIME_WRAPPERS[key], encoding="utf-8")
    done = subprocess.run(
        [cc, "-E", "-P", *(f"-D{d}" for d in defines), f"-I{find_toolchain().runtime}", f"-I{WASMEXT_C}", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


@pytest.mark.parametrize("key", list(_RUNTIME_WRAPPERS))
def test_the_wrappers_of_the_old_layer_3_are_not_renamed(key: str, tmp_path: Path) -> None:
    """Without WASMEXT_STORE_RUNTIME (natify, build_shared and the executable) the wrapper preprocesses to the runtime as it was: no forwarder, no `wasmext_own_` name, no header of the core."""
    text = _preprocess(key, tmp_path, [])
    assert "wasmext_own_" not in text and "wasmext_runtime" not in text and "wasmext_tls_" not in text
    with_trap_handler = _preprocess(key, tmp_path, ["WASMEXT_TRAP_HANDLER=wasmext_trap_add"])
    assert "wasmext_own_" not in with_trap_handler
    renamed = _preprocess(key, tmp_path, ["WASMEXT_STORE_RUNTIME=1"])
    assert all(f"wasmext_own_{n}" in renamed for n in (f"wasm_rt_{m}" for m in _RENAMED[key]))


def test_the_core_stops_without_the_macro(tmp_path: Path) -> None:
    """A builder of the core that forgets WASMEXT_STORE_RUNTIME gets an error that names it, not a program whose runtime functions are not forwarded."""
    cc = find_cc()
    if cc is None:
        pytest.skip("no C compiler of the cc kind")
    source = tmp_path / "core.c"
    source.write_text('#include "wasmext_instance.h"\nint main(void) { return 0; }\n', encoding="utf-8")
    from fusedwasi import get_include

    cmd = [cc, "-fsyntax-only", f"-I{WASMEXT_C}", f"-I{get_include()}", f"-I{find_toolchain().runtime}", str(source)]
    refused = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert refused.returncode != 0 and "WASMEXT_STORE_RUNTIME" in refused.stderr
    assert (
        subprocess.run([*cmd, "-DWASMEXT_STORE_RUNTIME=1"], capture_output=True, text=True, check=False).returncode == 0
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the dynamic symbols are read with nm on Linux")
def test_a_library_defines_the_forwarders_and_the_own_functions_and_keeps_its_runtime_to_itself(
    wabt: Path, tmp_path: Path
) -> None:
    """Built with the default visibility for everything else, a library defines every `wasm_rt_*` name (the forwarder) and every `wasmext_own_wasm_rt_*` (the function of the copy) at different addresses, and
    keeps its table of the runtime and the thread record to itself: if either were exported, the dynamic linker could make one library's stand for another's."""
    nm = shutil.which("nm")
    if nm is None or find_cc() is None:
        pytest.skip("no nm, or no C compiler")
    library = _library(wabt, tmp_path, "a", {"liba": LIBA}, [], hidden=False)
    symbols: dict[str, str] = {}
    for line in subprocess.run(
        [nm, "-D", "--defined-only", str(library)], capture_output=True, text=True, check=True
    ).stdout.splitlines():
        address, kind, name = line.split()[:3]
        if kind in "Tt":
            symbols[name] = address
    for name in _WRAPPED_NAMES:
        assert name in symbols, f"{name} (the forwarder) is not defined by the library"
        assert f"wasmext_own_{name}" in symbols, f"wasmext_own_{name} is not defined by the library"
        assert symbols[name] != symbols[f"wasmext_own_{name}"], f"{name} and wasmext_own_{name} are one function"
    everything = subprocess.run(
        [nm, "-D", "--defined-only", str(library)], capture_output=True, text=True, check=True
    ).stdout
    for hidden in ("wasmext_runtime_own_", "wasmext_tls_", "wasmext_artifact_", "wasmext_runtime_fix_seed_"):
        assert hidden not in everything, f"{hidden} is exported by a library built with the default visibility"
