"""Tables between instances (TABLES_PLAN.md): a funcref table that one module exports and another imports, with functions of both in it, called from either, with
traps, exceptions and lifetimes. On every pair of front ends (an extension or the wrapper for ctypes over a shared library, for the owner and for the user of the
table), and from a C host that links two libraries. The executable has no imports to share."""

from __future__ import annotations

import gc
import os
import weakref
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

Builder = Callable[..., ModuleType]

# the exporter: a table of 6 (at most 8) with five functions in it (slot 3 is left for the user), a memory, a tag
_OWNER = """
(module
  (type $t (func (result i32)))
  (tag $e)
  (table (export "tab") 6 8 funcref)
  (memory (export "mem") 1)
  (func $five (type $t) i32.const 5)
  (func $bad (type $t) unreachable)
  (func $oob (type $t) i32.const 0x7ffffff0 i32.load)
  (func $rec (type $t) call $rec call $rec i32.add)
  (func $throws (type $t) throw $e)
  (elem (i32.const 0) func $five $bad $oob)
  (elem (i32.const 4) func $rec $throws)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t))
  (func (export "size") (result i32) table.size 0)
  (func (export "grow") (param i32) (result i32) ref.null func local.get 0 table.grow 0)
  (func (export "five") (result i32) i32.const 5))
"""

# the importer: calls through the table, and puts a function of its own in slot 3
_USER = """
(module
  (type $t (func (result i32)))
  (type $other (func (param i32) (result i32)))
  (import "env" "tab" (table 4 8 funcref))
  (func $seven (type $t) i32.const 7)
  (elem (i32.const 3) func $seven)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t))
  (func (export "call_other") (param i32) (result i32) i32.const 0 local.get 0 call_indirect (type $other))
  (func (export "size") (result i32) table.size 0))
"""


PAIRS = [("extension", "extension"), ("ctypes", "ctypes"), ("extension", "ctypes"), ("ctypes", "extension")]


@pytest.fixture(params=PAIRS, ids=["-".join(p) for p in PAIRS])
def pair(request: pytest.FixtureRequest) -> tuple[str, str]:
    """(the front end of the owner of the table, the front end of the module that uses it)."""
    return request.param  # type: ignore[no-any-return]


@pytest.fixture
def build(
    pair: tuple[str, str], request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Callable[..., ModuleType]:
    """`build(name, wat, role)`: the module, in the front end of the role ("owner" or "user") in this pair."""
    builders = {
        "extension": request.getfixturevalue("build_extension"),
        "ctypes": request.getfixturevalue("build_ctypes"),
    }
    out = tmp_path_factory.mktemp("tables")
    cache: dict[str, ModuleType] = {}

    def make(name: str, wat: str, role: str = "user") -> ModuleType:
        front = pair[0] if role == "owner" else pair[1]
        key = f"{name}_{front}"
        if key not in cache:
            source = out / f"{key}.wat"
            source.write_text(wat, encoding="utf-8")
            cache[key] = builders[front](source, key)
        return cache[key]

    return make


@pytest.fixture
def owner_mod(build: Callable[..., ModuleType]) -> ModuleType:
    return build("tbl_owner", _OWNER, "owner")


@pytest.fixture
def user_mod(build: Callable[..., ModuleType]) -> ModuleType:
    return build("tbl_user", _USER, "user")


def test_one_instance_calls_the_functions_of_the_table_of_another(owner_mod: Any, user_mod: Any) -> None:
    a = owner_mod.Instance(owner_mod.Store())
    b = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": a["tab"]}})
    assert b.call(0) == 5  # a function of the owner
    assert b.call(3) == 7  # b's own, put there by its elem segment
    assert a.call(3) == 7  # and the owner calls it: one table
    assert (a.size(), b.size()) == (6, 6)


def test_the_whole_instance_can_stand_for_its_table(owner_mod: Any, user_mod: Any) -> None:
    a = owner_mod.Instance(owner_mod.Store())
    assert "tab" in a.__exports__
    b = user_mod.Instance(user_mod.Store(), imports={"env": a})
    assert b.call(0) == 5


def test_a_table_that_grows_grows_for_both(owner_mod: Any, user_mod: Any) -> None:
    a = owner_mod.Instance(owner_mod.Store())
    b = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": a["tab"]}})
    assert a.grow(2) == 6  # the old size
    assert (a.size(), b.size()) == (8, 8)
    with pytest.raises(user_mod.Trap, match="Invalid call_indirect"):
        b.call(7)  # the new slots are empty
    assert a.grow(1) == -1  # more than the maximum of 8
    assert b.size() == 8


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        ("7 funcref", "the table has 6 elements, the module needs at least 7"),
        ("4 4 funcref", "the table may grow to 8 elements, the module allows 4"),
    ],
)
def test_a_table_of_another_size_is_not_linked(
    build: Callable[..., ModuleType], owner_mod: Any, limits: str, message: str
) -> None:
    wat = f'(module (import "env" "tab" (table {limits})) (func (export "f") (result i32) i32.const 0))'
    mod = build(f"tbl_limits_{abs(hash(wat)) % 10**6}", wat)
    a = owner_mod.Instance(owner_mod.Store())
    with pytest.raises(mod.LinkError, match=message):
        mod.Instance(mod.Store(), imports={"env": {"tab": a["tab"]}})


def test_an_import_with_no_maximum_takes_a_table_with_one(build: Callable[..., ModuleType], owner_mod: Any) -> None:
    mod = build(
        "tbl_nomax", '(module (import "env" "tab" (table 2 funcref)) (func (export "f") (result i32) i32.const 0))'
    )
    assert mod.Instance(mod.Store(), imports={"env": {"tab": owner_mod.Instance(owner_mod.Store())["tab"]}}).f() == 0


def test_what_is_not_a_table_is_not_linked_as_one(owner_mod: Any, user_mod: Any) -> None:
    a = owner_mod.Instance(owner_mod.Store())
    with pytest.raises(user_mod.LinkError, match="is a table: the export given is not"):
        user_mod.Instance(user_mod.Store(), imports={"env": {"tab": a["mem"]}})
    with pytest.raises(user_mod.LinkError, match="is a table: pass a Table, or the table of another instance"):
        user_mod.Instance(user_mod.Store(), imports={"env": {"tab": print}})
    with pytest.raises(user_mod.LinkError, match="tab"):
        user_mod.Instance(user_mod.Store(), imports={"env": {}})


def test_an_element_of_another_type_is_a_trap(owner_mod: Any, user_mod: Any) -> None:
    a = owner_mod.Instance(owner_mod.Store())
    b = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": a["tab"]}})
    with pytest.raises(user_mod.Trap, match="Invalid call_indirect"):
        b.call_other(0)
    assert b.call(0) == 5


@pytest.mark.parametrize(
    ("slot", "message"),
    [
        (1, "Unreachable instruction executed"),  # in the function of the owner
        (2, "Out-of-bounds access"),  # a fault of the guard pages, in the function of the owner
        (5, "Uncaught exception"),  # a `throw` nothing catches: the unwind target of the owner's runtime
    ],
)
def test_a_trap_in_a_function_of_another_instance_is_a_trap_of_the_caller(
    owner_mod: Any, user_mod: Any, slot: int, message: str
) -> None:
    a = owner_mod.Instance(owner_mod.Store())
    b = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": a["tab"]}})
    with pytest.raises(user_mod.Trap, match=message):
        b.call(slot)
    assert b.call(0) == 5  # the instances are fine afterwards
    assert a.call(0) == 5
    assert a.call(3) == 7


_EXHAUST = """
import sys
for p in {paths!r}:
    sys.path.insert(0, p)
import {owner}, {user}
a = {owner}.Instance({owner}.Store())
b = {user}.Instance({user}.Store(), imports={{"env": {{"tab": a["tab"]}}}})
try:
    b.call(4)
except {user}.Trap as exc:
    print("trap:", exc)
print("after:", b.call(0), a.call(0))
"""

_EXHAUST_ONE = """
import sys
for p in {paths!r}:
    sys.path.insert(0, p)
import {mod}
inst = {mod}.Instance({mod}.Store())
try:
    inst.rec()
except {mod}.Trap as exc:
    print("trap:", exc)
print("after:", inst.five())
"""


def _run_exhaustion(script: str, what: str) -> None:
    """Stack exhaustion is the signal of the stack on the alternate stack of the runtime; where the process dies of it, that must not take the other tests with it."""
    import platform
    import subprocess
    import sys

    ran = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=120)
    if ran.returncode != 0 and platform.system() == "Darwin":
        # On macOS the entry saves the signal mask (WASMEXT_TRY in wasmext_glue.h), which is what lets the thread leave the alternate stack of the
        # runtime after a trap by a signal; without it the process died here (SIGILL), or in the next import (abort in sigaltstack).
        pytest.xfail(f"{what}: the process ended with {ran.returncode} on macOS: {ran.stderr.strip()[-200:]}")
    assert ran.returncode == 0, ran.stderr
    # macOS merges the traps of an access out of bounds and of the stack running out in one message ("..., or call stack exhausted")
    assert "trap:" in ran.stdout and "call stack exhausted" in ran.stdout.lower() and "after: 5" in ran.stdout


def test_stack_exhaustion_in_a_function_of_another_instance_is_a_trap(owner_mod: Any, user_mod: Any) -> None:
    assert owner_mod.__file__ is not None and user_mod.__file__ is not None
    paths = [str(Path(owner_mod.__file__).parent), str(Path(user_mod.__file__).parent)]
    _run_exhaustion(
        _EXHAUST.format(paths=paths, owner=owner_mod.__name__, user=user_mod.__name__), "through a shared table"
    )


def test_stack_exhaustion_in_a_module_with_no_table_is_a_trap(build: Callable[..., ModuleType]) -> None:
    mod = build(
        "tbl_exhaust_plain",
        '(module (type $t (func (result i32))) (func $rec (export "rec") (type $t) call $rec call $rec i32.add)'
        ' (func (export "five") (result i32) i32.const 5))',
        "owner",
    )
    assert mod.__file__ is not None
    paths = [str(Path(mod.__file__).parent)]
    _run_exhaustion(_EXHAUST_ONE.format(paths=paths, mod=mod.__name__), "in one module, no table")


def test_the_owner_keeps_the_instances_that_use_its_table_alive(owner_mod: Any, user_mod: Any) -> None:
    a = owner_mod.Instance(owner_mod.Store())
    b = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": a["tab"]}})
    ref_a, ref_b = weakref.ref(a), weakref.ref(b)
    del b
    gc.collect()
    assert ref_b() is not None  # the table of a holds a function of b
    assert a.call(3) == 7
    del a
    gc.collect()
    assert ref_a() is None and ref_b() is None  # nothing refers to either from outside


def test_the_user_of_a_table_keeps_its_owner_alive(owner_mod: Any, user_mod: Any) -> None:
    a = owner_mod.Instance(owner_mod.Store())
    b = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": a["tab"]}})
    ref_a = weakref.ref(a)
    del a
    gc.collect()
    assert ref_a() is not None
    assert b.call(0) == 5 and b.call(3) == 7
    del b
    gc.collect()
    assert ref_a() is None


def test_an_instance_that_fails_to_instantiate_takes_back_what_it_put_in_the_table(
    build: Callable[..., ModuleType], owner_mod: Any
) -> None:
    wat = """
    (module
      (type $t (func (result i32)))
      (import "env" "tab" (table 4 8 funcref))
      (func $nine (type $t) i32.const 9)
      (elem (i32.const 3) func $nine)
      (elem (i32.const 100) func $nine))
    """
    bad = build("tbl_bad_writer", wat)
    a = owner_mod.Instance(owner_mod.Store())
    with pytest.raises(bad.Trap):
        bad.Instance(bad.Store(), imports={"env": {"tab": a["tab"]}})
    gc.collect()
    with pytest.raises(owner_mod.Trap, match="Invalid call_indirect"):
        a.call(3)  # the slot it filled is empty again, not a function of an instance that is gone
    assert a.call(0) == 5


def test_two_extensions_that_share_a_table_do_not_disturb_one_that_does_not(
    build: Callable[..., ModuleType], owner_mod: Any, user_mod: Any
) -> None:
    plain = build("tbl_plain", '(module (func (export "f") (result i32) unreachable))')
    a = owner_mod.Instance(owner_mod.Store())
    b = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": a["tab"]}})
    with pytest.raises(plain.Trap, match="Unreachable"):
        plain.Instance(plain.Store()).f()
    with pytest.raises(user_mod.Trap, match="Unreachable"):
        b.call(1)
    assert b.call(0) == 5


def test_a_module_that_shares_tables_needs_the_trap_handler(tmp_path: Path, wabt: Path) -> None:
    import subprocess

    from wasmext._gen import generate  # pyright: ignore[reportPrivateUsage]
    from wasmext._wasm import parse  # pyright: ignore[reportPrivateUsage]

    wat = tmp_path / "t.wat"
    wasm = tmp_path / "t.wasm"
    wat.write_text(_OWNER, encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    glue = generate(parse(wasm.read_bytes()), "t")
    assert glue.trap_handler == "wasmext_trap_t"
    assert "#error" in glue.source and "WASMEXT_TRAP_HANDLER" in glue.source
    plain = generate(parse(b"\0asm\1\0\0\0"), "t")
    assert plain.trap_handler == "" and "WASMEXT_TRAP_HANDLER" not in plain.source


_HOST = r"""
#include <stdio.h>
#include <string.h>
#include "ta_api.h"
#include "tb_api.h"
int main(void) {
    int err = 0;
    if (tb_traps_use(ta_traps())) { puts("traps_use failed"); return 1; }
    ta_store_t *a_s = ta_store_new(NULL, &err);
    ta_t *a = ta_new(a_s, &err);
    if (ta_instantiate(a)) { puts("a instantiate failed"); return 1; }
    ta_export rec;
    if (ta_export_find(a, "tab", a, &rec)) { puts("no tab"); return 1; }
    tb_store_t *b_s = tb_store_new(NULL, &err);
    tb_t *b = tb_new(b_s, &err);
    char msg[256] = "";
    printf("instantiate before the link: %s\n", tb_instantiate(b) == TB_LINK_ERROR ? "LINK_ERROR" : "?");
    if (tb_link_table_import0(b, (const tb_export *)&rec, msg, sizeof msg)) { printf("link: %s\n", msg); return 1; }
    printf("instantiate: %d\n", tb_instantiate(b));
    int32_t r = -1; int t;
    r = tb_call(b, 0); t = tb_status(b); printf("b slot 0: %d %d\n", t, r);
    r = tb_call(b, 3); t = tb_status(b); printf("b slot 3: %d %d\n", t, r);
    r = ta_call(a, 3); t = ta_status(a); printf("a slot 3: %d %d\n", t, r);
    r = tb_call(b, 1); t = tb_status(b); printf("b slot 1: %d (%s)\n", t, t ? tb_trap_message(t) : "");
    r = tb_call(b, 0); t = tb_status(b); printf("b slot 0 again: %d %d\n", t, r);
    tb_unlink_tables(b);
    r = ta_call(a, 3); t = ta_status(a); printf("a slot 3 after the unlink: %d (%s)\n", t, t ? ta_trap_message(t) : "");
    tb_free(b);
    tb_store_free(b_s);
    r = ta_call(a, 0); t = ta_status(a); printf("a slot 0: %d %d\n", t, r);
    ta_free(a);
    ta_store_free(a_s);
    return 0;
}
"""


def test_two_libraries_share_a_table_from_a_c_host(tmp_path: Path, wabt: Path) -> None:
    """The C API: one library exports a table, another imports it, the host gives the second the stack of entries of the first (`traps_use`)
    and links them; a trap in a function of one library that the other called comes back to the caller; `unlink_tables` takes a library out of a table."""
    import platform
    import shutil
    import subprocess
    import sys

    from wasmext._exe import build_shared  # pyright: ignore[reportPrivateUsage]

    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    if cc is None or sys.platform == "win32":
        pytest.skip("a C host over two libraries is tested where there is a cc and the libraries can be found by rpath")
    suffix = ".dylib" if platform.system() == "Darwin" else ".so"
    for stem, wat in (("ta", _C_OWNER), ("tb", _C_USER)):
        (tmp_path / f"{stem}.wat").write_text(wat, encoding="utf-8")
        subprocess.run(
            [wabt / "bin" / "wat2wasm", tmp_path / f"{stem}.wat", "-o", tmp_path / f"{stem}.wasm"], check=True
        )
        build_shared(tmp_path / f"{stem}.wasm", tmp_path / f"lib{stem}{suffix}", name=stem, optimize=False, quiet=True)
    (tmp_path / "host.c").write_text(_HOST, encoding="utf-8")
    subprocess.run(
        [cc, "-O1", "-Wall", f"-I{tmp_path / 'libta_wasmext'}", f"-I{tmp_path / 'libtb_wasmext'}", "-o", tmp_path / "host", tmp_path / "host.c",
         f"-L{tmp_path}", "-lta", "-ltb", f"-Wl,-rpath,{tmp_path}"],
        check=True,
    )  # fmt: skip
    ran = subprocess.run([tmp_path / "host"], capture_output=True, text=True, check=False, timeout=120)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        "instantiate before the link: LINK_ERROR",
        "instantiate: 0",
        "b slot 0: 0 5",
        "b slot 3: 0 7",
        "a slot 3: 0 7",
        "b slot 1: 5 (Unreachable instruction executed)",
        "b slot 0 again: 0 5",
        "a slot 3 after the unlink: 6 (Invalid call_indirect or return_call_indirect)",
        "a slot 0: 0 5",
    ]


_C_OWNER = """
(module
  (type $t (func (result i32)))
  (table (export "tab") 6 8 funcref)
  (func $five (type $t) i32.const 5)
  (func $bad (type $t) unreachable)
  (elem (i32.const 0) func $five $bad)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t)))
"""

_C_USER = """
(module
  (type $t (func (result i32)))
  (import "env" "tab" (table 4 8 funcref))
  (func $seven (type $t) i32.const 7)
  (elem (i32.const 3) func $seven)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t)))
"""


_PROVIDER = """
(module
  (table (export "tab") 4 8 funcref)
  (memory (export "mem") 1)
  (global (export "g") (mut i32) (i32.const 7)))
"""

_PROVIDER_USER = """
(module
  (type $t (func (result i32)))
  (import "env" "tab" (table 4 8 funcref))
  (import "env" "mem" (memory 1))
  (import "env" "g" (global (mut i32)))
  (func $nine (type $t) i32.const 9)
  (elem (i32.const 2) func $nine)
  (data (i32.const 8) "hi")
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t))
  (func (export "bump") (result i32) global.get 0 i32.const 1 i32.add global.set 0 global.get 0)
  (func (export "peek") (result i32) i32.const 8 i32.load8_u))
"""


def test_a_table_a_memory_and_a_global_with_no_code_behind_them_are_a_module_that_only_declares_them(
    build: Callable[..., ModuleType],
) -> None:
    """What the host would make by itself (a table, a memory, a global) is, in a compiler, a module that only declares them: built ahead of time like any other, linked as any other.
    wasmext has no object for it at run time (DESIGN.md, "linking instances")."""
    provider = build("tbl_provider", _PROVIDER, "owner")
    user = build("tbl_provider_user", _PROVIDER_USER, "user")
    a = provider.Instance(provider.Store())
    b = user.Instance(
        user.Store(), imports={"env": a}
    )  # the shelf of the provider: its table, its memory and its global
    assert b.call(2) == 9  # the user filled the table of the provider
    assert bytes(a.mem[8:10]) == b"hi"  # ... and wrote to its memory
    assert (a.g, b.bump(), a.g) == (7, 8, 8)  # ... and shares its global
    assert b.peek() == ord("h")
