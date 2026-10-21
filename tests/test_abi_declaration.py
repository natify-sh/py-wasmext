"""The declaration of the public surface of the ABI (abi/current.json, docs/abi_policy.md) against the code, and the rule that says what version a change needs.

The fingerprint of the files of `src/wasmext/c/` (tests/test_abi.py) fails on any change of those files; this one fails on a change of what a module or a host
built apart can see: a constant, the order or the text of a field, a signature, a name of a capsule, a line of the stub. It is read from `wasmext_glue.h` and from
what the generator makes for the fixed modules of tests/data, so a change of the generator that changes those shows here too.
"""

from __future__ import annotations

import copy
import ctypes
import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.abi_surface import (
    DATA,
    DECLARATION,
    FIXTURE_NAME,
    FIXTURES,
    Surface,
    describe,
    extract,
    generated_of,
    required_bump,
    surface_of,
)
from wasmext._exe import build_shared  # pyright: ignore[reportPrivateUsage]

BASIC = FIXTURES[0]


@pytest.fixture(scope="module")
def now(wabt: Path, tmp_path_factory: pytest.TempPathFactory) -> Surface:
    generated: dict[str, tuple[str, str]] = {}
    for name in FIXTURES:
        wasm = tmp_path_factory.mktemp("abi") / (name + ".wasm")
        subprocess.run([wabt / "bin" / "wat2wasm", DATA / name, "-o", wasm], check=True)
        generated[name] = generated_of(wasm.read_bytes())
    return extract(generated)


@pytest.fixture(scope="module")
def declared() -> Surface:
    return json.loads(DECLARATION.read_text(encoding="utf-8"))


def test_the_declaration_is_the_code(declared: Surface, now: Surface) -> None:
    """Fails when the public surface differs from abi/current.json: check the compatibility by hand, update the declaration and set the version."""
    assert declared == now, (
        "the public surface of the ABI is not the one that abi/current.json declares. What differs "
        f"(the version it needs: x if something was removed or changed, y if only something was added):\n\n{describe(declared, now)}\n\n"
        f"By the rule that is a change that needs: {required_bump(declared, now)!r} (none: z or a serial of a pre-release).\n"
        "Check by hand that modules built before still link and work (docs/abi_policy.md), update the declaration with "
        "`python -m tests.abi_surface --update`, and set the version that fits the change."
    )


def test_the_declaration_has_what_a_contract_needs(declared: Surface) -> None:
    """A declaration that is empty (the reading found nothing) would agree with an empty reading: these are the things that cannot be missing."""
    x = int(declared["version"]["WASMEXT_ABI"], 16) >> 24
    assert declared["capsules"] == {"export": f"wasmext.export.v{x}", "traps": f"wasmext.traps.v{x}"}
    glue = declared["glue"]
    assert {
        "WASMEXT_FUNC",
        "WASMEXT_TABLE",
        "WASMEXT_MEMORY",
        "WASMEXT_GLOBAL",
        "WASMEXT_TRAP_HOST",
        "WASMEXT_TRAP_LINKED",
    } <= set(glue["constants"])
    assert [field.split()[-1].lstrip("*") for field in glue["structs"]["wasmext_export"]][:3] == ["size", "abi", "kind"]
    assert {"wasmext_export", "wasmext_traps", "wasmext_entry", "wasmext_value"} <= set(glue["structs"])
    assert "WASMEXT_RUNTIME" not in glue["constants"]  # the fingerprint of the toolchain is not a part of the contract
    assert set(declared["api"]) == set(FIXTURES)
    api = declared["api"][BASIC]
    for name in (
        "new",
        "free",
        "instantiate",
        "export_find",
        "traps",
        "traps_use",
        "unlink_tables",
        "table_new",
        "funcref_call0",
        "add",
        "pick",
    ):
        assert f"<name>_{name}" in api["functions"], name
    assert {"<name>_export", "<name>_config"} <= set(api["structs"]) and "<name>_t" in api["opaque"]
    assert (
        "<name>_import0_fn" in api["typedefs"]
    )  # the pointer to the function of an import is part of the signature of the one that sets it
    assert any(line.startswith("class Instance") for line in api["stub"]) and any(
        "class Trap" in line for line in api["stub"]
    )
    more = declared["api"][FIXTURES[1]]
    assert "<name>_vadd" in more["functions"] and "uint8_t" in more["functions"]["<name>_vadd"]  # v128 as 16 bytes
    assert "<name>_memory_big" in more["functions"] and "<name>_link_memory_import0" in more["functions"]


@pytest.mark.parametrize("fixture", FIXTURES)
def test_every_declared_function_is_a_symbol_of_the_library(
    declared: Surface, wabt: Path, tmp_path: Path, fixture: str
) -> None:
    """The declaration is read from the header; this is the other side: the library built from the same module shows each of those names, and
    ctypes finds it (what a host that is not C sees). A function declared and not exported, or renamed in one place only, fails here."""
    wasm = tmp_path / (fixture + ".wasm")
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / fixture, "-o", wasm], check=True)
    suffix = ".dll" if sys.platform == "win32" else ".dylib" if platform.system() == "Darwin" else ".so"
    library = build_shared(
        wasm, tmp_path / f"lib{FIXTURE_NAME}{suffix}", name=FIXTURE_NAME, optimize=False, quiet=True, flags=None
    )
    loaded = ctypes.CDLL(str(library))
    names = [n.replace("<name>", FIXTURE_NAME) for n in declared["api"][fixture]["functions"]]
    assert names
    missing = [n for n in names if not hasattr(loaded, n)]
    assert not missing, f"declared in the C API, not exported by the library: {missing}"
    if sys.platform != "win32" and shutil.which(
        "nm"
    ):  # the other side: nothing is shown that the declaration does not have
        listing = subprocess.run(
            [
                "nm",
                "-gU" if platform.system() == "Darwin" else "-D",
                *([] if platform.system() == "Darwin" else ["--defined-only"]),
                str(library),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        shown = {
            line.split()[-1].removeprefix("_" if platform.system() == "Darwin" else "")
            for line in listing.splitlines()
            if line.split()
        }
        assert not shown - set(names), f"shown by the library, not declared: {sorted(shown - set(names))}"


def test_the_reading_stops_at_a_form_it_does_not_know() -> None:
    """Every statement of a header is read or is on the short list of what is not part of the surface; any other stops the reading, so that
    a new form of declaration cannot slip by."""
    assert surface_of("typedef struct { int a; } t;")["structs"] == {"t": ["int a"]}
    assert surface_of("typedef int (*cb)(int);")["typedefs"] == {"cb": "typedef int (*cb)(int)"}
    assert surface_of("static inline int f(void) { return 1; }\nenum { A = 1, B };")["constants"] == {
        "A": "1",
        "B": "2",
    }
    for unknown in ("int a_variable = 1;", "struct s { int a; };", "WASMEXT_NOT_AN_EXPORT int f(void);"):
        with pytest.raises(ValueError, match="does not know"):
            surface_of(unknown)


def _basic(s: Surface) -> Surface:
    return s["api"][BASIC]


def test_a_surface_that_is_the_same_needs_no_bump(declared: Surface) -> None:
    assert required_bump(declared, copy.deepcopy(declared)) == "none"


def test_what_is_added_needs_y(declared: Surface) -> None:
    new = copy.deepcopy(declared)
    _basic(new)["functions"]["<name>_a_new_call"] = "int <name>_a_new_call(<name>_t *m)"
    assert required_bump(declared, new) == "y"
    new = copy.deepcopy(declared)
    new["glue"]["constants"]["WASMEXT_A_NEW_KIND"] = "4"
    assert required_bump(declared, new) == "y"
    new = copy.deepcopy(declared)
    new["glue"]["structs"]["wasmext_export"].append("uint32_t floor")  # a field at the end
    assert required_bump(declared, new) == "y"
    new = copy.deepcopy(declared)
    new["glue"]["structs"]["wasmext_a_new_struct"] = ["uint32_t size"]
    assert required_bump(declared, new) == "y"
    new = copy.deepcopy(declared)
    _basic(new)["stub"].append("    def a_new_method(self) -> None: ...")
    assert required_bump(declared, new) == "y"


def _function_is_gone(s: Surface) -> None:
    del _basic(s)["functions"]["<name>_add"]


def _signature_changed(s: Surface) -> None:
    _basic(s)["functions"]["<name>_add"] = "int <name>_add(<name>_t *m, int64_t a0)"


def _callback_signature_changed(s: Surface) -> None:
    _basic(s)["typedefs"]["<name>_import0_fn"] = (
        "typedef int64_t (*<name>_import0_fn)(void *user, int64_t a0, int *trapped)"
    )


def _value_changed(s: Surface) -> None:
    s["glue"]["constants"]["WASMEXT_TRAP_HOST"] = "((wasm_rt_trap_t)0x7777)"


def _constant_is_gone(s: Surface) -> None:
    del s["glue"]["constants"]["WASMEXT_FUNC"]


def _field_in_the_middle(s: Surface) -> None:
    s["glue"]["structs"]["wasmext_export"].insert(1, "uint32_t floor")  # the others moved


def _fields_swapped(s: Surface) -> None:
    fields = s["glue"]["structs"]["wasmext_export"]
    fields[0], fields[1] = fields[1], fields[0]


def _field_changed(s: Surface) -> None:
    s["glue"]["structs"]["wasmext_export"][0] = "uint64_t size"


def _field_at_the_end_is_gone(s: Surface) -> None:
    s["glue"]["structs"]["wasmext_export"].pop()


def _struct_is_gone(s: Surface) -> None:
    del s["glue"]["structs"]["wasmext_traps"]


def _opaque_type_is_gone(s: Surface) -> None:
    _basic(s)["opaque"].clear()


def _capsule_renamed(s: Surface) -> None:
    s["capsules"]["export"] = "wasmext.export.v2"


def _stub_line_changed(s: Surface) -> None:
    stub = _basic(s)["stub"]
    stub[next(i for i, line in enumerate(stub) if "def cabi" in line or "__exports__" in line)] = (
        "    def renamed(self) -> None: ..."
    )


def _a_fixture_is_gone(s: Surface) -> None:
    del s["api"][FIXTURES[1]]


@pytest.mark.parametrize(
    "change",
    [
        _function_is_gone,
        _signature_changed,
        _callback_signature_changed,
        _value_changed,
        _constant_is_gone,
        _field_in_the_middle,
        _fields_swapped,
        _field_changed,
        _field_at_the_end_is_gone,
        _struct_is_gone,
        _opaque_type_is_gone,
        _capsule_renamed,
        _stub_line_changed,
        _a_fixture_is_gone,
    ],
)
def test_what_is_removed_or_changed_needs_x(declared: Surface, change: Callable[[Surface], None]) -> None:
    new = copy.deepcopy(declared)
    change(new)
    assert required_bump(declared, new) == "x"


def test_x_wins_over_y(declared: Surface) -> None:
    new = copy.deepcopy(declared)
    _basic(new)["functions"]["<name>_a_new_call"] = "int <name>_a_new_call(<name>_t *m)"
    del _basic(new)["functions"]["<name>_add"]
    assert required_bump(declared, new) == "x"


def test_the_difference_says_what_it_is(declared: Surface) -> None:
    new = copy.deepcopy(declared)
    _fields_swapped(new)
    new["glue"]["constants"]["WASMEXT_A_NEW_KIND"] = "4"
    text = describe(declared, new)
    assert "[x] glue: the fields of struct wasmext_export were put in another order" in text
    assert "[y] glue: constant WASMEXT_A_NEW_KIND was added" in text
