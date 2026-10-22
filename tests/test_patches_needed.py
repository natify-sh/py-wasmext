"""Do the patches of wasmext (docs/patch_policy.md) still have something to repair?

Each test gives the *plain* `wasm2c` (before any repair of ours) a small module that shows a defect of WABT, and says that the defect is still in its output. The day a
release of WABT fixes it the test fails, and the message says what to take away: the patch (a regular expression of `_natify.py`) and the test, and the row in
docs/wasm2c_limits.md. The other side, a patch that no longer matches a text that WABT changed, is caught by the tests that run the module (tests/test_features.py).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from wasmext._natify import (  # pyright: ignore[reportPrivateUsage]
    _ELEM_ENTRY,  # pyright: ignore[reportPrivateUsage]
    _ELEM_REF_FUNC,  # pyright: ignore[reportPrivateUsage]
    _MSVC_ADDCARRY,  # pyright: ignore[reportPrivateUsage]
    _TAIL_CALL_LOCALS,  # pyright: ignore[reportPrivateUsage]
    _TAIL_CALL_RESULT,  # pyright: ignore[reportPrivateUsage]
)

_GONE = "wasm2c no longer has the defect of {issue}: remove {patch} from _natify.py, this test, and the row in docs/wasm2c_limits.md (and FEATURES.md)"


@pytest.fixture(scope="module")
def plain_c(wabt: Path, tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], bytes]:
    """The C that the wasm2c of the toolchain writes for a WAT module, as it is, all the files joined."""

    def run(wat: str) -> bytes:
        work = tmp_path_factory.mktemp("plain")
        (work / "m.wat").write_text(wat, encoding="utf-8")
        subprocess.run([wabt / "bin" / "wat2wasm", work / "m.wat", "-o", work / "m.wasm"], check=True)
        subprocess.run([wabt / "bin" / "wasm2c", work / "m.wasm", "-o", work / "m.c"], check=True)
        return b"\n".join(p.read_bytes() for p in sorted(work.glob("m*.[ch]")))

    return run


def test_msvc_addcarry_is_still_in_the_c_of_a_64_bit_memory(plain_c: Callable[[str], bytes]) -> None:
    c = plain_c('(module (memory i64 1) (func (export "f") (result i32) i64.const 0 i32.load))')
    assert _MSVC_ADDCARRY.search(c), _GONE.format(issue="WABT #2885", patch="_MSVC_ADDCARRY")


def test_the_locals_of_a_return_call_are_still_written_without_a_type(plain_c: Callable[[str], bytes]) -> None:
    c = plain_c(
        "(module (func $a (param i32) (result i32) local.get 0)"
        ' (func (export "f") (param i32) (result i32) (local i32) local.get 0 local.set 1 local.get 1 return_call $a))'
    )
    assert _TAIL_CALL_LOCALS.search(c), _GONE.format(issue="WABT #2884", patch="_TAIL_CALL_LOCALS")


def test_the_result_of_a_return_call_indirect_chain_is_still_dropped(plain_c: Callable[[str], bytes]) -> None:
    c = plain_c(
        "(module (type $t (func (result i32))) (table $tab 4 funcref)"
        " (func $ok (type $t) i32.const 5)"
        " (func $tc (type $t) i32.const 0 return_call_indirect $tab (type $t))"
        " (elem (table $tab) (i32.const 0) func $ok $tc)"
        ' (func (export "f") (result i32) i32.const 1 return_call_indirect $tab (type $t)))'
    )
    assert _TAIL_CALL_RESULT.search(c), _GONE.format(issue="WABT #2893", patch="_TAIL_CALL_RESULT")


def test_an_imported_function_in_an_element_segment_still_has_the_wrong_offset(plain_c: Callable[[str], bytes]) -> None:
    c = plain_c(
        '(module (import "env" "g" (func $g (result i32))) (table $tab 1 funcref) (elem (table $tab) (i32.const 0) func $g)'
        ' (func (export "f") (result i32) i32.const 0 call_indirect $tab (result i32)))'
    )
    assert _ELEM_REF_FUNC.search(c) and _ELEM_ENTRY.search(c), _GONE.format(
        issue="WABT #2896", patch="_repair_imported_elements"
    )


@pytest.mark.parametrize(
    ("issue", "body", "flags"),
    [
        (
            "#2886",
            "v128.const i32x4 1 2 3 4 v128.const i32x4 1 2 3 4 v128.const i32x4 1 2 3 4 f32x4.relaxed_madd drop",
            (),
        ),
        (
            "#2895",
            "i64.const 1 i64.const 2 i64.const 3 i64.const 4 i64.add128 drop drop",
            (),
        ),
    ],
)
def test_wasm2c_still_aborts_on_what_it_cannot_translate(
    issue: str, body: str, flags: tuple[str, ...], wabt: Path, tmp_path: Path
) -> None:
    (tmp_path / "m.wat").write_text(f'(module (func (export "f") {body}))', encoding="utf-8")
    made = subprocess.run(
        [wabt / "bin" / "wat2wasm", "--enable-all", tmp_path / "m.wat", "-o", tmp_path / "m.wasm"],
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("wat2wasm of the toolchain does not read this instruction")
    ran = subprocess.run(
        [wabt / "bin" / "wasm2c", *flags, tmp_path / "m.wasm", "-o", tmp_path / "m.c"],
        capture_output=True,
        check=False,
    )
    assert ran.returncode in (-6, 134), (
        f"wasm2c no longer fails on the module of WABT {issue}: the feature may be supported now; see FEATURES.md and docs/wasm2c_limits.md"
    )
