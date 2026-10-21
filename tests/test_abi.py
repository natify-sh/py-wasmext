"""The ABI of wasmext: the number 0xXXYYZZLS in wasmext_glue.h, the fingerprint of the C of the ABI, and what is built from them."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from wasmext._abi import ABI, ABI_FINGERPRINT, ABI_X, C_DIR, abi_fingerprint, capsule_name  # pyright: ignore[reportPrivateUsage]


def test_the_abi_is_read_from_the_header_and_names_the_capsule() -> None:
    """The number is 0xXXYYZZLS made of four defines; only x is in the name of the capsule."""
    header = (C_DIR / "wasmext_glue.h").read_text(encoding="utf-8")
    parts: list[int] = []
    for n in ("X", "Y", "Z", "LS"):
        found = re.search(rf"^#define WASMEXT_ABI_{n} (0x[0-9A-Fa-f]+|\d+)$", header, re.MULTILINE)
        assert found
        parts.append(int(found.group(1), 0))
    assert ABI == (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]
    assert ABI_X == parts[0] == ABI >> 24
    assert 0 <= parts[3] <= 0xFF and parts[3] >> 4 in (0xA, 0xB, 0xC, 0xF), "the level is A, B, C or F"
    assert capsule_name() == f"wasmext.export.v{ABI_X}"
    assert capsule_name(2) == "wasmext.export.v2"
    assert '"wasmext.traps.v" WASMEXT_STRING(WASMEXT_ABI_X)' in header


def test_the_c_of_the_abi_is_the_c_that_was_fingerprinted() -> None:
    """Fails when a file of src/wasmext/c/ changed: decide whether the ABI goes up, then put the new fingerprint in _abi.py."""
    now = abi_fingerprint()
    assert now == ABI_FINGERPRINT, (
        f"the files of src/wasmext/c/ changed (fingerprint {now}).\n"
        "If the change breaks what a module already built reads (a field of wasmext_export moved, removed or changed in meaning, a trap code, "
        "the name of the capsule), raise WASMEXT_ABI in wasmext_glue.h. If it only adds at the end of the record, or does not touch the ABI "
        "(a fix in WASI, a comment, formatting), leave it. Then set ABI_FINGERPRINT in src/wasmext/_abi.py to the fingerprint above."
    )


def test_the_fingerprint_does_not_depend_on_the_line_ends(tmp_path: Path) -> None:
    copy = tmp_path / "c"
    shutil.copytree(C_DIR, copy)
    for path in copy.iterdir():
        if path.is_file():
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))  # a checkout on Windows
    assert abi_fingerprint(copy) == abi_fingerprint(C_DIR)


def test_the_fingerprint_covers_every_file_and_every_byte(tmp_path: Path) -> None:
    copy = tmp_path / "c"
    shutil.copytree(C_DIR, copy)
    base = abi_fingerprint(copy)
    (copy / "a_new_header.h").write_text(
        "/* new */\n", encoding="utf-8"
    )  # whatever the name, a file that is added is in
    added = abi_fingerprint(copy)
    assert added != base
    (copy / "a_new_header.h").write_text("/* new! */\n", encoding="utf-8")
    assert abi_fingerprint(copy) != added
    (copy / "a_new_header.h").unlink()
    glue = copy / "wasmext_glue.h"
    glue.write_bytes(glue.read_bytes() + b"\n")  # a space, a comment, a format: the fingerprint is of the bytes
    assert abi_fingerprint(copy) != base


def test_what_is_generated_names_the_abi_and_not_a_number() -> None:
    """The record is made with WASMEXT_ABI (extension and library) and the wrapper for ctypes has the number of this wasmext."""
    from wasmext._ctypes_gen import _TEMPLATE  # pyright: ignore[reportPrivateUsage]
    from wasmext._gen import generate
    from wasmext._wasm import parse

    assert "@ABI@" in _TEMPLATE
    wasm = (Path(__file__).parent / "data" / "simple.wasm").read_bytes()
    glue = generate(parse(wasm), "pkg.add")
    assert "e->abi = WASMEXT_ABI;" in glue.source and "e->version" not in glue.source


def _fields(declarations: str) -> list[str]:
    """The names of the fields of a struct body: `uint32_t size, abi;` and `void *owner;` give size, abi, owner."""
    names: list[str] = []
    for declaration in re.sub(r"/\*.*?\*/", "", declarations, flags=re.DOTALL).split(";"):
        if declaration.strip():
            names += [part.split()[-1].lstrip("*") for part in declaration.split(",") if part.strip()]
    return names


def test_the_record_in_the_header_of_a_library_is_the_record_of_the_glue() -> None:
    """`<name>_export` in `<name>_api.h` is public and is read as `wasmext_export`: the same fields, the same order."""
    from wasmext._shared import generate_shared  # pyright: ignore[reportPrivateUsage]

    header = generate_shared("m", "m", [], [], [], False, 0)[0]
    api = re.search(r"typedef struct \{(.*?)\} m_export;", header, re.DOTALL)
    glue = re.search(
        r"typedef struct \{([^{}]*?)\} wasmext_export;",
        (C_DIR / "wasmext_glue.h").read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert api and glue
    assert _fields(api.group(1)) == _fields(glue.group(1))
    assert "public and versioned by WASMEXT_ABI" in header


_LAYOUT_PROBE = """#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "wasm-rt.h"
#include "wasm-rt-impl.h"
#include "wasm-rt-exceptions.h"
#include "wasmext_glue.h"
int main(void) { return 0; }
"""


def _builds_with(cc: str, include: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    (tmp_path / "probe.c").write_text(_LAYOUT_PROBE, encoding="utf-8")
    return subprocess.run(
        [cc, "-fsyntax-only", f"-I{include}", f"-I{C_DIR}", tmp_path / "probe.c"],
        capture_output=True,
        text=True,
        check=False,
    )


def _cc() -> str:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler of the cc kind")
    return cc


def test_the_runtime_of_the_toolchain_has_the_layout_of_the_abi(wabt: Path, tmp_path: Path) -> None:
    """The structs of the runtime of wasm2c that the toolchain brings are the ones that the glue checks (WASMEXT_LAYOUT). This is the test that the
    job "WABT main" of the CI runs: it fails when a WABT changes a layout, and then a maintainer decides (support both, or keep to the older WABT;
    docs/abi_policy.md, "WASMEXT_RUNTIME")."""
    built = _builds_with(_cc(), wabt / "wasm2c", tmp_path)
    assert built.returncode == 0, (
        "the runtime of this WABT has another layout than the ABI promises:\n" + built.stderr[-1500:]
    )


def test_a_runtime_with_another_layout_cannot_build_a_module(wabt: Path, tmp_path: Path) -> None:
    """The layout of the structs of the wasm2c runtime is checked when a module is built: a runtime with a memory that has no `data_end` and
    `page_size` (as WABT `main` has it, 48 bytes against 56) does not build."""
    cc = _cc()
    runtime = wabt / "wasm2c"
    if _builds_with(cc, runtime, tmp_path).returncode != 0:
        pytest.skip("the runtime of this toolchain is refused itself (see the test above)")
    other = tmp_path / "other"
    other.mkdir()
    for header in runtime.glob("*.h"):
        text = header.read_text(encoding="utf-8")
        if header.name == "wasm-rt.h":
            text = text.replace("  uint8_t* data_end;\n", "", 1).replace("  uint32_t page_size;\n", "", 1)
        (other / header.name).write_text(text, encoding="utf-8")
    refused = _builds_with(cc, other, tmp_path)
    assert refused.returncode != 0
    assert "data_end" in refused.stderr or "page_size" in refused.stderr
