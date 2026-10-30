"""Step 8a-1 of docs/specs/S0008-shared-store.md: two artifacts built apart (two shared libraries, each with its own copy of the core and of the runtime of wasm2c) share ONE
store through the checked head of the store and `wasmext_store_attach`. The libraries are built as the product builds a module (the repairs of `_natify`, its wrappers of the runtime);
the host, tests/c/test_artifacts.c, calls the core only through the table that each library returns."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from fusedwasi import get_include

from wasmext import parse
from wasmext._binding import generate_binding
from wasmext._descriptor import generate_descriptor
from wasmext._gen import module_prefix
from wasmext._model import build_model
from wasmext._natify import (
    _RUNTIME_WRAPPERS,
    _export_tags,
    _portable,
    _repair_imported_elements,
    _repair_tail_calls,
    signal_build_flags,
)
from wasmext._toolchain import find_toolchain

from .c_build import compile_c, find_cc, supports_flag
from .conftest import SANITIZED

HERE = Path(__file__).parent
C_DIR = HERE / "c"
WASMEXT_C = HERE.parent / "src" / "wasmext" / "c"

# artifact A
LIBA = """(module
  (type $t (func (result i32)))
  (memory (export "mem") 1 4)
  (global $counter (export "counter") (mut i32) (i32.const 10))
  (global $gf (export "gf") (mut funcref) (ref.null func))
  (table $tab (export "tab") 4 8 funcref)
  (func $seven (export "seven") (result i32) i32.const 7)
  (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add)
  (func (export "load") (param i32) (result i32) local.get 0 i32.load8_u)
  (func (export "get_counter") (result i32) global.get $counter)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t))
  (elem (i32.const 0) $seven))"""
USEA = """(module (import "libt" "tab" (table 2 funcref)) (func (export "f")))"""
# artifact B
APPB = """(module
  (import "libx" "add" (func $add (param i32 i32) (result i32)))
  (import "libx" "mem" (memory 1 4))
  (import "libx" "counter" (global $counter (mut i32)))
  (func (export "call_add") (param i32 i32) (result i32) local.get 0 local.get 1 call $add)
  (func (export "poke") (param i32 i32) local.get 0 local.get 1 i32.store8)
  (func (export "inc") (result i32) global.get $counter i32.const 1 i32.add global.set $counter global.get $counter))"""
TABB = """(module (import "libt" "tab" (table 2 funcref)) (func (export "f")))"""
GLB = """(module (import "libg" "gf" (global (mut funcref))) (func (export "f")))"""
HOSTB = """(module
  (import "env" "visit" (func $visit (param funcref) (result funcref)))
  (func (export "via") (param funcref) (result funcref) local.get 0 call $visit))"""
IFB = """(module (import "genv" "if" (global funcref)) (func (export "f")))"""
OWNB = """(module
  (type $t (func (result i32)))
  (table $tab (export "tab") 4 8 funcref)
  (global $gf (export "gf") (mut funcref) (ref.null func))
  (func $nine (export "nine") (result i32) i32.const 9)
  (func (export "ident") (param funcref) (result funcref) local.get 0)
  (func (export "plus") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t)))"""


def _library(
    wabt: Path, out: Path, name: str, modules: dict[str, str], flags: Sequence[str], defines: Sequence[str] = ()
) -> Path:
    """The artifact `name`: tests/c/artifact.c, the modules (built as the fixture `build` of test_instance_core.py builds them) and the runtime, as a shared library."""
    cc = find_cc()
    assert cc is not None
    toolchain = find_toolchain()
    simde = [toolchain.include] if toolchain.include is not None and (toolchain.include / "simde").is_dir() else []
    d = out / name
    d.mkdir()
    sources: list[Path] = [C_DIR / "artifact.c", C_DIR / "artifact_store_only.c"]
    for module, wat in modules.items():
        (d / f"{module}.wat").write_text(wat, encoding="utf-8")
        wasm = d / f"{module}.wasm"
        subprocess.run([wabt / "bin" / "wat2wasm", d / f"{module}.wat", "-o", wasm], check=True)
        subprocess.run(
            [wabt / "bin" / "wasm2c", wasm, "-o", d / f"{module}_w2c.c", f"--module-name={module}"], check=True
        )
        raw = (d / f"{module}_w2c.c").read_bytes()
        repaired = _repair_imported_elements([raw])[0]
        (d / f"{module}_w2c.c").write_bytes(
            _export_tags(_repair_tail_calls(_portable(repaired)), module_prefix(module))
        )
        model = build_model(parse(wasm.read_bytes()), module, host="wasm32")
        (d / f"{module}_descriptor.c").write_text(generate_descriptor(model), encoding="utf-8")
        (d / f"{module}_binding.c").write_text(generate_binding(model), encoding="utf-8")
        sources += [d / f"{module}_binding.c", d / f"{module}_descriptor.c", d / f"{module}_w2c.c"]
    (d / "modules.inc").write_text("".join(f"MODULE({m})\n" for m in modules), encoding="utf-8")
    for key in ("impl", "mem", "exceptions"):  # the runtime is the product's: wrapped
        (d / f"rt_{key}.c").write_text(_RUNTIME_WRAPPERS[key], encoding="utf-8")
        sources.append(d / f"rt_{key}.c")
    chain_macros, chain_link = (
        signal_build_flags()
    )  # the product's: WASMEXT_CHAIN, the stack limit in place of the guard page, -z now
    library = out / f"libartifact_{name}{'.dylib' if sys.platform == 'darwin' else '.so'}"
    subprocess.run(
        [
            cc, "-shared", "-fPIC", "-fvisibility=hidden", "-w", "-pthread", *flags, f"-DARTIFACT_NAME={name}", *(f"-D{k}={v}" for k, v in chain_macros), *(f"-D{x}" for x in defines), *chain_link,
            *(f"-I{p}" for p in (d, C_DIR, WASMEXT_C, Path(get_include()), toolchain.runtime, *simde)),
            *map(str, sources), "-lm", "-o", str(library),
        ],
        check=True,
    )  # fmt: skip
    return library


def _run(wabt: Path, tmp_path: Path, flags: Sequence[str] = (), defines: Sequence[str] = ()) -> None:
    if sys.platform == "win32" or find_cc() is None:
        pytest.skip("shared libraries with hidden visibility and pthreads: Linux and macOS with a cc")
    a = _library(wabt, tmp_path, "a", {"liba": LIBA, "usea": USEA}, flags, defines)
    b = _library(
        wabt,
        tmp_path,
        "b",
        {"appb": APPB, "tabb": TABB, "glb": GLB, "ownb": OWNB, "hostb": HOSTB, "ifb": IFB},
        flags,
        defines,
    )
    exe = tmp_path / "test_artifacts"
    compile_c(
        [C_DIR / "test_artifacts.c", a, b],
        exe,
        include_dirs=[C_DIR, WASMEXT_C, Path(get_include()), find_toolchain().runtime],
        flags=[*flags, f"-Wl,-rpath,{tmp_path}"],
        defines=defines,
        threads=True,
        strict=False,
        std=None,
    )
    env = {**os.environ, "LD_LIBRARY_PATH": str(tmp_path), "DYLD_LIBRARY_PATH": str(tmp_path)}
    result = subprocess.run([str(exe)], check=False, capture_output=True, text=True, timeout=300, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_two_artifacts_share_one_store(wabt: Path, tmp_path: Path) -> None:
    _run(wabt, tmp_path)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
def test_two_artifacts_under_addresssanitizer(wabt: Path, tmp_path: Path) -> None:
    if SANITIZED or not supports_flag("-fsanitize=address,undefined"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(wabt, tmp_path, ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"])


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ThreadSanitizer is checked on Linux")
def test_two_artifacts_under_threadsanitizer(wabt: Path, tmp_path: Path) -> None:
    if SANITIZED or not supports_flag("-fsanitize=thread"):
        pytest.skip("no ThreadSanitizer, or another sanitizer is on for the whole run")
    _run(wabt, tmp_path, ["-fsanitize=thread", "-g"])


def _layout(tmp_path: Path, swap: tuple[str, str, int, str, int] | None) -> tuple[int, int]:
    """The hashes of the layout of the core and of the host, from a copy of the headers in which two fields (`a` in the `ia`-th line that starts with it, `b` likewise) swapped places."""
    import shutil

    cc = find_cc()
    if cc is None:
        pytest.skip("no C compiler of the cc kind")
    d = tmp_path / ("swapped" if swap else "plain")
    d.mkdir()
    for h in WASMEXT_C.glob("*.h"):
        shutil.copy(h, d / h.name)
    if swap:
        name, a, ia, b, ib = swap
        lines = (d / name).read_text(encoding="utf-8").split("\n")
        at = [k for k, line in enumerate(lines) if line.strip().startswith(a)][ia]
        bt = [k for k, line in enumerate(lines) if line.strip().startswith(b)][ib]
        lines[at], lines[bt] = lines[bt], lines[at]
        (d / name).write_text("\n".join(lines), encoding="utf-8")
    exe = d / "layout_hash"
    subprocess.run(
        [cc, "-O2", "-w", f"-I{d}", f"-I{Path(get_include())}", f"-I{find_toolchain().runtime}", str(C_DIR / "layout_hash.c"), "-lm", "-pthread", "-o", str(exe)],
        check=True,
    )  # fmt: skip
    core, host = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split()
    return int(core), int(host)


# (header, first field, which line of that text, second field, which line): the fields that another copy of the core reads inline
_SWAPS = {
    "registry-slots-table": ("wasmext_registry.h", "wasmext_slot *slots;", 0, "uint32_t *table;", 0),
    "slot-key-object": ("wasmext_registry.h", "void *key;", 0, "void *object;", 0),
    "owner-ops-retain-release": (
        "wasmext_registry.h",
        "void (*retain)(void *object);",
        0,
        "void (*release)(void *object);",
        0,
    ),
    "store-closing-closed": ("wasmext_store.h", "wasmext_counter closing;", 0, "wasmext_counter closed;", 0),
    "arena-object-release": ("wasmext_store.h", "void *object;", 0, "void (*release)(void *object);", 0),
    "rlock-owner-depth": ("wasmext_rlock.h", "wasmext_counter owner;", 0, "long depth;", 0),
    "instance-binding-store": ("wasmext_instance.h", "const wasmext_binding *binding;", 0, "wasmext_store *store;", 0),
    "import-slot-host-typed": ("wasmext_instance.h", "wasmext_host_fn host;", 0, "void *typed;", 0),
    "extern-user-release": ("wasmext_instance.h", "void *user;", 1, "void (*release)(void *user);", 0),
    "host-func-slot-store": ("wasmext_instance.h", "wasmext_import_slot slot;", 0, "wasmext_store *store;", 2),
    "tab-elem-live": ("wasmext_instance.h", "int elem;", 0, "int live;", 0),
}


@pytest.mark.parametrize("swap", list(_SWAPS.values()), ids=list(_SWAPS))
def test_the_layout_hash_follows_every_field_that_another_copy_reads(
    tmp_path: Path, swap: tuple[str, str, int, str, int]
) -> None:
    """Two fields swapped (a reorder that no `sizeof` sees) change the hash of the layout that `attach` and `instance_new` compare: a copy built with the other order is refused."""
    base = _layout(tmp_path, None)
    assert _layout(tmp_path, swap)[0] != base[0], (
        f"swapping {swap[1]!r} and {swap[3]!r} in {swap[0]} left WASMEXT_CORE_LAYOUT as it was"
    )


def test_the_layout_hash_follows_the_host(tmp_path: Path) -> None:
    """The host of the store is read by the binding of another artifact; its layout has a word of its own in the head of the store."""
    base = _layout(tmp_path, None)
    swapped = _layout(
        tmp_path,
        (
            "wasmext_host.h",
            "int (*clock)(void *user, uint32_t id, uint64_t *ns);",
            1,
            "int (*random)(void *user, uint8_t *buf, size_t n);",
            1,
        ),
    )
    assert swapped[1] != base[1], "swapping two fields of wasmext_host left WASMEXT_HOST_LAYOUT as it was"
