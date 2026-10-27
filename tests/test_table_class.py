"""The class `Table` (TABLES_PLAN.md, step 3): made by the glue of a module that imports or exports a funcref table, in the extension and in the wrapper for ctypes with the
same interface, shared with other modules by the capsule of the record like every export. No module owns a `Table(initial, maximum)`; `instance['name']` gives a `Table` for
a table the module exports."""

from __future__ import annotations

import gc
import weakref
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

Builder = Callable[..., ModuleType]

# a module that imports a table of 4 (at most 8), puts a function of its own in slot 3 and calls through the table
_USER = """
(module
  (type $t (func (result i32)))
  (import "env" "tab" (table 4 8 funcref))
  (func $seven (type $t) i32.const 7)
  (elem (i32.const 3) func $seven)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t))
  (func (export "size") (result i32) table.size 0))
"""

# a module that exports a table of 6 (at most 8) with a function in slot 0
_OWNER = """
(module
  (type $t (func (result i32)))
  (table (export "tab") 6 8 funcref)
  (func $five (type $t) i32.const 5)
  (elem (i32.const 0) func $five)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t))
  (func (export "size") (result i32) table.size 0)
  (func (export "grow") (param i32) (result i32) ref.null func local.get 0 table.grow 0))
"""

FRONTS = ["extension", "ctypes"]


@pytest.fixture(params=FRONTS)
def front(request: pytest.FixtureRequest) -> str:
    return request.param  # type: ignore[no-any-return]


@pytest.fixture
def make(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Callable[..., ModuleType]:
    """`make(front, name, wat, share_tables=False)`: the module in that front end."""
    builders = {
        "extension": request.getfixturevalue("build_extension"),
        "ctypes": request.getfixturevalue("build_ctypes"),
    }
    out = tmp_path_factory.mktemp("tableclass")
    cache: dict[str, ModuleType] = {}

    def build(front: str, name: str, wat: str, share_tables: bool = False) -> ModuleType:
        key = f"{name}_{front}"
        if key not in cache:
            source: Path = out / f"{key}.wat"
            source.write_text(wat, encoding="utf-8")
            cache[key] = builders[front](source, key, share_tables=share_tables)
        return cache[key]

    return build


def test_a_table_of_its_own_has_a_size_a_maximum_and_grows(front: str, make: Callable[..., ModuleType]) -> None:
    mod = make(front, "tc_user", _USER)
    table = mod.Table(4, 8)
    assert (table.size, table.maximum, len(table)) == (4, 8, 4)
    assert table.grow(2) == 4
    assert (table.size, len(table)) == (6, 6)
    with pytest.raises(ValueError, match="cannot grow"):
        table.grow(3)  # 9 is more than the maximum
    assert table.size == 6
    assert table.grow(0) == 6
    assert mod.Table(3).maximum is None


def test_the_arguments_of_a_table_are_checked(front: str, make: Callable[..., ModuleType]) -> None:
    mod = make(front, "tc_user", _USER)
    with pytest.raises(ValueError, match="more than maximum"):
        mod.Table(5, 2)
    with pytest.raises(ValueError):
        mod.Table(-1)
    with pytest.raises(ValueError):
        mod.Table(2**32)
    with pytest.raises(TypeError):
        mod.Table("a")
    with pytest.raises(TypeError):
        mod.Table(1.5)
    with pytest.raises(TypeError):
        mod.Table(1, 2, 3)
    with pytest.raises(TypeError):
        mod.Table(initial=1)
    table = mod.Table(1, 2)
    with pytest.raises(TypeError):
        table.grow("a")


def test_a_module_imports_a_table_that_has_no_module_and_fills_it(front: str, make: Callable[..., ModuleType]) -> None:
    mod = make(front, "tc_user", _USER)
    table = mod.Table(4, 8)
    user = mod.Instance(mod.Store(), imports={"env": {"tab": table}})
    assert user.call(3) == 7  # its own function, put there by its elem segment
    assert user.size() == 4
    table.grow(2)  # one table: the module sees it
    assert user.size() == 6


def test_a_table_is_shared_by_modules_through_the_record_whatever_the_class(
    front: str, make: Callable[..., ModuleType]
) -> None:
    # the table of one module's class is imported by a module of the other front end (no class in common, the capsule is)
    ext = make("extension", "tc_user", _USER)
    other = make("ctypes", "tc_user", _USER)
    table = ext.Table(4, 8)
    one = ext.Instance(ext.Store(), imports={"env": {"tab": table}})
    two = other.Instance(other.Store(), imports={"env": {"tab": table}})
    assert one.call(3) == 7 and two.call(3) == 7
    table.grow(1)
    assert one.size() == two.size() == 5
    back = other.Table(4, 8)
    assert ext.Instance(ext.Store(), imports={"env": {"tab": back}}).call(3) == 7


def test_the_limits_of_a_table_of_its_own_are_checked_at_the_link(front: str, make: Callable[..., ModuleType]) -> None:
    mod = make(front, "tc_user", _USER)
    with pytest.raises(mod.LinkError, match="at least 4"):
        mod.Instance(mod.Store(), imports={"env": {"tab": mod.Table(3, 8)}})
    with pytest.raises(mod.LinkError, match="may grow to"):
        mod.Instance(mod.Store(), imports={"env": {"tab": mod.Table(4)}})  # no maximum, the import allows 8
    with pytest.raises(mod.LinkError, match="is a table"):
        mod.Instance(mod.Store(), imports={"env": {"tab": 5}})


def test_instance_item_of_a_table_is_a_table(front: str, make: Callable[..., ModuleType]) -> None:
    owner_mod = make(front, "tc_owner", _OWNER)
    user_mod = make(front, "tc_user", _USER)
    owner = owner_mod.Instance(owner_mod.Store())
    table = owner["tab"]
    assert type(table).__name__ == "Table"
    assert (table.size, table.maximum) == (6, 8)
    assert owner.__exports__["tab"].size == 6
    user = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": table}})
    assert user.call(3) == 7 and user.call(0) == 5  # a function of the owner and one of the user
    table.grow(1)  # through the Table: the owner and the user see it
    assert owner.size() == user.size() == 7
    assert owner.grow(1) == 7 and table.size == 8
    user2 = user_mod.Instance(user_mod.Store(), imports={"env": owner})  # the whole shelf from the instance
    assert user2.call(0) == 5


def test_a_table_keeps_the_modules_that_put_functions_in_it_alive(front: str, make: Callable[..., ModuleType]) -> None:
    mod = make(front, "tc_user", _USER)
    table = mod.Table(4, 8)
    user: Any = mod.Instance(mod.Store(), imports={"env": {"tab": table}})
    ref = weakref.ref(user)
    del user
    gc.collect()
    alive: Any = ref()
    assert alive is not None  # its function is in the table
    assert alive.call(3) == 7
    del alive, table
    gc.collect()
    assert ref() is None


def test_a_table_outlives_the_instance_that_has_it(front: str, make: Callable[..., ModuleType]) -> None:
    owner_mod = make(front, "tc_owner", _OWNER)
    user_mod = make(front, "tc_user", _USER)
    owner = owner_mod.Instance(owner_mod.Store())
    table = owner["tab"]
    user = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": table}})
    ref = weakref.ref(owner)
    del owner
    gc.collect()
    assert ref() is not None  # the Table of its table holds it
    assert user.call(0) == 5
    del table, user
    gc.collect()
    assert ref() is None


def test_the_table_has_the_same_public_interface_in_the_extension_the_wrapper_and_the_stub(
    make: Callable[..., ModuleType], tmp_path: Path, wabt: Path
) -> None:
    """The extension, the wrapper for ctypes and the `.pyi` (which is the same text for both) name the same public members of `Table`."""
    import ast

    from wasmext import generate, parse

    stub = ast.parse(generate(parse(_wasm(tmp_path, wabt, _USER)), "tc_user").stub)
    members = {
        node.name
        for cls in stub.body
        if isinstance(cls, ast.ClassDef) and cls.name == "Table"
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("__")
    }
    assert members == {"size", "maximum", "grow", "get", "set"}
    for front in FRONTS:
        table = make(front, "tc_user", _USER).Table
        assert {name for name in dir(table) if not name.startswith("_")} == members, front
        assert {"__len__", "__init__", "__wasmext_ref__", "__wasmext_keep__"} <= set(dir(table)), front


def _wasm(tmp_path: Path, wabt: Path, wat: str) -> bytes:
    import subprocess

    source = tmp_path / "t.wat"
    source.write_text(wat, encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", source, "-o", tmp_path / "t.wasm"], check=True)
    return (tmp_path / "t.wasm").read_bytes()


_HOST = r"""
#include <stdio.h>
#include "tu_api.h"
#include "tf_api.h"
int main(void) {
    int err = 0, trapped;
    if (tu_traps_use(tf_traps())) { puts("traps_use failed"); return 1; }
    void *table = tu_table_new(4, 8);
    if (table == NULL) { puts("no table"); return 1; }
    printf("size %u maximum %u\n", (unsigned)tu_table_size(table), (unsigned)tu_table_maximum(table));
    tu_export rec;
    tu_table_export(table, table, &rec);
    tu_store_t *u_s = tu_store_new(NULL, &err);
    tu_t *u = tu_new(u_s, &err);
    char msg[256] = "";
    if (tu_link_table_import0(u, &rec, msg, sizeof msg)) { printf("link: %s\n", msg); return 1; }
    if (tu_instantiate(u)) { puts("instantiate failed"); return 1; }
    int32_t r = -1;
    r = tu_call(u, 3);
    trapped = tu_status(u);
    printf("slot 3: %d %d\n", trapped, r);
    tf_store_t *f_s = tf_store_new(NULL, &err);
    tf_t *f = tf_new(f_s, &err);
    if (tf_instantiate(f)) { puts("f instantiate failed"); return 1; }
    tf_export five;
    if (tf_export_find(f, "five", f, &five)) { puts("no five"); return 1; }
    printf("slot 0 empty: %d\n", tu_table_is_null(table, 0));
    printf("set: %d\n", tu_table_set(table, 0, five.funcref));
    printf("slot 0 is five: %d, empty: %d\n", tu_table_is(table, 0, five.funcref), tu_table_is_null(table, 0));
    r = tu_call(u, 0);
    trapped = tu_status(u);
    printf("slot 0: %d %d\n", trapped, r);
    void *ref = tu_table_get_ref(table, 0);
    int k = tu_funcref_type(ref);
    int32_t got = -1;
    int code = k == 0 ? tu_funcref_call0(ref, &got) : -99;
    printf("funcref of slot 0: type %d, call %d %d\n", k, code, (int)got);
    tu_funcref_free(ref);
    printf("slot 1 has a function: %d\n", tu_table_get_ref(table, 1) != NULL);
    printf("set out of range: %d\n", tu_table_set(table, 9, five.funcref));
    tu_table_set(table, 0, NULL);
    printf("slot 0 emptied: %d\n", tu_table_is_null(table, 0));
    int64_t before = tu_table_grow(table, 2);
    printf("grow: %d size %u\n", (int)before, (unsigned)tu_table_size(table));
    printf("grow too much: %d\n", (int)tu_table_grow(table, 9));
    tu_unlink_tables(u);
    tu_call(u, 3);
    trapped = tu_status(u);
    printf("slot 3 after the unlink: %d\n", trapped);
    tu_free(u);
    tu_store_free(u_s);
    tf_free(f);
    tf_store_free(f_s);
    tu_table_free(table);
    tu_table_free(NULL);
    return 0;
}
"""


def test_a_c_host_makes_a_table_with_the_api_of_a_library_and_links_a_module_to_it(tmp_path: Path, wabt: Path) -> None:
    import platform
    import shutil
    import subprocess
    import sys

    from wasmext._exe import build_shared  # pyright: ignore[reportPrivateUsage]

    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None or sys.platform == "win32":
        pytest.skip("a C host is tested where there is a cc and the library can be found by rpath")
    suffix = ".dylib" if platform.system() == "Darwin" else ".so"
    for stem, wat in (("tu", _USER), ("tf", _FUNCS)):
        (tmp_path / f"{stem}.wat").write_text(wat, encoding="utf-8")
        subprocess.run(
            [wabt / "bin" / "wat2wasm", tmp_path / f"{stem}.wat", "-o", tmp_path / f"{stem}.wasm"], check=True
        )
        build_shared(
            tmp_path / f"{stem}.wasm",
            tmp_path / f"lib{stem}{suffix}",
            name=stem,
            share_tables=stem == "tf",
            optimize=False,
            quiet=True,
        )
    (tmp_path / "host.c").write_text(_HOST, encoding="utf-8")
    subprocess.run(
        [cc, "-O1", "-Wall", f"-I{tmp_path / 'libtu_wasmext'}", f"-I{tmp_path / 'libtf_wasmext'}", "-o", tmp_path / "host", tmp_path / "host.c",
         f"-L{tmp_path}", "-ltu", "-ltf", f"-Wl,-rpath,{tmp_path}"],
        check=True,
    )  # fmt: skip
    ran = subprocess.run([tmp_path / "host"], capture_output=True, text=True, check=False, timeout=120)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert ran.stdout.splitlines() == [
        "size 4 maximum 8",
        "slot 3: 0 7",
        "slot 0 empty: 1",
        "set: 0",
        "slot 0 is five: 1, empty: 0",
        "slot 0: 0 5",
        "funcref of slot 0: type 0, call 0 5",
        "slot 1 has a function: 0",
        "set out of range: -1",
        "slot 0 emptied: 1",
        "grow: 4 size 6",
        "grow too much: -1",
        "slot 3 after the unlink: 6",
    ]


# a module whose functions go in tables: no table of its own, so it is built with share_tables (see `funcs_module`)
_FUNCS = """
(module
  (func (export "five") (result i32) i32.const 5)
  (func (export "six") (result i32) i32.const 6)
  (func (export "bad") (result i32) unreachable)
  (func (export "id") (param i32) (result i32) local.get 0)
  (func (export "wide") (param i64) (result i64) local.get 0))
"""

COMBOS = [("extension", "extension"), ("ctypes", "ctypes"), ("extension", "ctypes"), ("ctypes", "extension")]


@pytest.fixture(params=COMBOS, ids=["-".join(c) for c in COMBOS])
def combo(request: pytest.FixtureRequest) -> tuple[str, str]:
    """(the front end of the Table and of the module that uses it, the front end of the module whose functions go in it)."""
    return request.param  # type: ignore[no-any-return]


def test_the_elements_of_a_table_are_set_and_read_from_python(
    combo: tuple[str, str], make: Callable[..., ModuleType]
) -> None:
    table_front, funcs_front = combo
    user_mod = make(table_front, "tc_user", _USER)
    funcs = (_mod17 := make(funcs_front, "tc_funcs", _FUNCS, share_tables=True)).Instance(_mod17.Store())
    table = user_mod.Table(4, 8)
    user = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": table}})
    assert [table.get(i) for i in (0, 1, 2)] == [None, None, None]
    table.set(0, funcs.five)  # a method of the instance
    table.set(1, funcs["six"])  # the reference to the export
    assert table.get(0)() == 5 and table.get(1)() == 6
    assert table.get(0).name == "five" and table.get(0).signature == ((), ("i32",))
    assert user.call(0) == 5 and user.call(1) == 6  # the module that imports the table calls them
    table.set(1, None)
    assert table.get(1) is None
    with pytest.raises(user_mod.Trap):
        user.call(1)  # an empty slot
    table.set(2, funcs.bad)
    with pytest.raises(user_mod.Trap, match="Unreachable"):
        user.call(2)  # a trap in a function of another instance is a trap of the caller
    assert user.call(0) == 5  # and everything goes on


def test_an_element_put_by_an_elem_segment_is_a_function_with_no_name(
    front: str, make: Callable[..., ModuleType]
) -> None:
    mod = make(front, "tc_user", _USER)
    table = mod.Table(4, 8)
    user = mod.Instance(mod.Store(), imports={"env": {"tab": table}})
    assert user.call(3) == 7
    seven = table.get(3)  # put by the elem segment of the module: it is no export, so it has no name
    assert (seven.name, seven.signature) == (None, ((), ("i32",)))
    assert seven() == 7
    assert table.get(3) == seven and hash(table.get(3)) == hash(seven)


def test_the_elements_are_checked(front: str, make: Callable[..., ModuleType]) -> None:
    mod = make(front, "tc_user", _USER)
    funcs = (_mod16 := make(front, "tc_funcs", _FUNCS, share_tables=True)).Instance(_mod16.Store())
    table = mod.Table(4, 8)
    with pytest.raises(IndexError):
        table.get(4)
    with pytest.raises(IndexError):
        table.set(4, funcs.five)
    with pytest.raises(ValueError):
        table.get(-1)
    with pytest.raises(TypeError):
        table.set(0, 5)
    with pytest.raises(TypeError):
        table.set(0, print)  # a function of Python cannot be in a table
    with pytest.raises(TypeError):
        table.set(0, funcs)  # an instance is not a function
    other = (_mod15 := make(front, "tc_owner", _OWNER)).Instance(_mod15.Store())
    with pytest.raises(TypeError, match="not one"):
        table.set(0, other["tab"])  # a table is not a function


def test_a_table_of_an_instance_has_elements_too(combo: tuple[str, str], make: Callable[..., ModuleType]) -> None:
    table_front, funcs_front = combo
    owner = (_mod14 := make(table_front, "tc_owner", _OWNER)).Instance(_mod14.Store())
    funcs = (_mod13 := make(funcs_front, "tc_funcs", _FUNCS, share_tables=True)).Instance(_mod13.Store())
    table = owner["tab"]
    table.set(1, funcs.six)
    assert owner.call(1) == 6 and table.get(1)() == 6
    table.set(0, funcs.five)  # over the function of the owner
    assert owner.call(0) == 5


def test_a_table_keeps_the_instance_whose_function_it_holds_alive(
    combo: tuple[str, str], make: Callable[..., ModuleType]
) -> None:
    table_front, funcs_front = combo
    user_mod = make(table_front, "tc_user", _USER)
    table = user_mod.Table(4, 8)
    user = user_mod.Instance(user_mod.Store(), imports={"env": {"tab": table}})
    funcs: Any = (_mod12 := make(funcs_front, "tc_funcs", _FUNCS, share_tables=True)).Instance(_mod12.Store())
    ref = weakref.ref(funcs)
    table.set(0, funcs.five)
    del funcs
    gc.collect()
    assert ref() is not None
    assert user.call(0) == 5
    del table, user
    gc.collect()
    assert ref() is None


def test_a_function_of_a_module_with_no_table_cannot_be_put_in_a_table(
    front: str, make: Callable[..., ModuleType]
) -> None:
    mod = make(front, "tc_user", _USER)
    plain = (_mod11 := make(front, "tc_plain", '(module (func (export "five") (result i32) i32.const 5))')).Instance(
        _mod11.Store()
    )
    with pytest.raises(TypeError, match="share tables"):
        mod.Table(2).set(0, plain.five)


# a module with several types, whose table holds one function of each (put by its elem segment) and which declares them all
_TYPES = """
(module
  (type $a (func (result i32)))
  (type $b (func (param i32 i64) (result f64)))
  (type $c (func (param i32) (result i32 i32)))
  (type $d (func))
  (type $e (func (param f32) (result f32)))
  (table (export "tab") 8 funcref)
  (func $a (type $a) i32.const 5)
  (func $b (type $b) local.get 0 f64.convert_i32_s local.get 1 f64.convert_i64_s f64.add)
  (func $c (type $c) local.get 0 local.get 0 i32.const 1 i32.add)
  (func $d (type $d) nop)
  (func $e (type $e) local.get 0 f32.const 2 f32.mul)
  (func $boom (type $a) unreachable)
  (elem (i32.const 0) func $a $b $c $d $e $boom)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $a)))
"""


def test_a_function_is_called_with_the_arguments_and_the_results_of_its_type(
    front: str, make: Callable[..., ModuleType]
) -> None:
    mod = make(front, "tc_types", _TYPES)
    owner = mod.Instance(mod.Store())
    table = owner["tab"]
    functions = [table.get(i) for i in range(6)]
    assert [f.signature for f in functions] == [
        ((), ("i32",)),
        (("i32", "i64"), ("f64",)),
        (("i32",), ("i32", "i32")),
        ((), ()),
        (("f32",), ("f32",)),
        ((), ("i32",)),
    ]
    assert functions[0]() == 5
    assert functions[1](40, 2) == 42.0
    assert functions[2](9) == (9, 10)
    assert functions[3]() is None
    assert functions[4](1.5) == 3.0
    with pytest.raises(TypeError, match="exactly 2 arguments"):
        functions[1](1)
    with pytest.raises(TypeError, match="exactly 0 arguments"):
        functions[0](1)
    with pytest.raises(mod.Trap, match="Unreachable"):
        functions[5]()  # a trap in the function comes back to the caller
    assert functions[0]() == 5  # and everything goes on
    assert repr(functions[0]).startswith("<Function")
    assert table.get(6) is None


def test_a_function_is_equal_to_the_same_function_and_a_function_goes_into_another_table(
    front: str, make: Callable[..., ModuleType]
) -> None:
    mod = make(front, "tc_types", _TYPES)
    owner = mod.Instance(mod.Store())
    table = owner["tab"]
    other = mod.Table(8, 8)
    assert table.get(0) == table.get(0) and table.get(0) != table.get(1)
    assert len({table.get(0), table.get(0), table.get(1)}) == 2
    other.set(2, table.get(0))  # a Function is accepted as the function to put in a slot
    assert other.get(2) == table.get(0) and other.get(2)() == 5
    other.set(3, table.get(2))
    assert other.get(3)(1) == (1, 2)


def test_a_function_of_a_type_the_module_does_not_declare_is_told_and_not_called(
    front: str, make: Callable[..., ModuleType]
) -> None:
    mod = make(front, "tc_user", _USER)  # declares () -> i32 and (i32) -> i32
    funcs = (_mod10 := make(front, "tc_funcs", _FUNCS, share_tables=True)).Instance(_mod10.Store())
    table = mod.Table(4, 8)
    table.set(0, funcs.wide)  # (i64) -> i64
    function = table.get(0)
    assert function.signature is None and function.name == "wide"
    with pytest.raises(TypeError, match="does not declare the type"):
        function(1)
    table.set(1, funcs.id)  # (i32) -> i32: declared (by `call`)
    assert table.get(1).signature == (("i32",), ("i32",)) and table.get(1)(7) == 7


def test_a_function_cannot_be_made_by_hand(front: str, make: Callable[..., ModuleType]) -> None:
    mod = make(front, "tc_user", _USER)
    with pytest.raises(TypeError):
        mod.Function()


def test_a_function_keeps_the_table_and_so_the_instances_alive(front: str, make: Callable[..., ModuleType]) -> None:
    mod = make(front, "tc_user", _USER)
    funcs: Any = (_mod9 := make(front, "tc_funcs", _FUNCS, share_tables=True)).Instance(_mod9.Store())
    ref = weakref.ref(funcs)
    table = mod.Table(4, 8)
    table.set(0, funcs.five)
    function = table.get(0)
    del funcs, table
    gc.collect()
    assert ref() is not None and function() == 5
    del function
    gc.collect()
    assert ref() is None


# a funcref in the signature of a function: the parameters and the results of exports
_REFS = """
(module
  (type $a (func (result i32)))
  (table (export "tab") 4 funcref)
  (func $five (type $a) i32.const 5)
  (elem declare func $five)
  (func (export "id") (param funcref) (result funcref) local.get 0)
  (func (export "pair") (param i32 funcref) (result i32 funcref) local.get 0 local.get 1)
  (func (export "five") (result funcref) ref.func $five)
  (func (export "store") (param i32 funcref) local.get 0 local.get 1 table.set 0)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $a))
  (func (export "isnull") (param funcref) (result i32) local.get 0 ref.is_null))
"""


def test_a_funcref_is_a_parameter_and_a_result(combo: tuple[str, str], make: Callable[..., ModuleType]) -> None:
    refs_front, funcs_front = combo
    refs = (_mod8 := make(refs_front, "tc_refs", _REFS)).Instance(_mod8.Store())
    funcs = (_mod7 := make(funcs_front, "tc_funcs", _FUNCS, share_tables=True)).Instance(_mod7.Store())
    assert refs.id(None) is None and refs.isnull(None) == 1
    given = refs.id(funcs.five)  # a function of an instance, and back as a Function
    assert given() == 5 and given.signature == ((), ("i32",)) and given == refs.id(funcs["five"])
    assert refs.isnull(funcs.five) == 0 and refs.isnull(given) == 0  # a Function is a funcref too
    number, function = refs.pair(7, funcs.six)
    assert number == 7 and function() == 6
    own = refs.five()  # a function of the module itself (ref.func)
    assert (own.name, own.signature) == (None, ((), ("i32",))) and own() == 5
    refs.store(1, funcs.six)  # the module puts it in its own table
    refs.store(2, own)
    assert refs.call(1) == 6 and refs.call(2) == 5


def test_a_funcref_that_the_module_keeps_keeps_its_instance_alive(
    combo: tuple[str, str], make: Callable[..., ModuleType]
) -> None:
    refs_front, funcs_front = combo
    refs = (_mod6 := make(refs_front, "tc_refs", _REFS)).Instance(_mod6.Store())
    funcs: Any = (_mod5 := make(funcs_front, "tc_funcs", _FUNCS, share_tables=True)).Instance(_mod5.Store())
    ref = weakref.ref(funcs)
    refs.store(3, funcs.six)
    del funcs
    gc.collect()
    assert ref() is not None and refs.call(3) == 6  # the instance was given: it lives as long as the one that got it
    del refs
    gc.collect()
    assert ref() is None


def test_a_funcref_takes_only_a_function_of_a_module_that_shares_tables(
    front: str, make: Callable[..., ModuleType]
) -> None:
    refs = (_mod4 := make(front, "tc_refs", _REFS)).Instance(_mod4.Store())
    plain = (_mod3 := make(front, "tc_plain", '(module (func (export "five") (result i32) i32.const 5))')).Instance(
        _mod3.Store()
    )
    with pytest.raises(TypeError):
        refs.id(5)
    with pytest.raises(TypeError, match="shares tables"):
        refs.id(plain.five)


def test_the_stub_and_the_c_api_have_the_funcrefs(tmp_path: Path, wabt: Path) -> None:
    from wasmext import generate, parse

    glue = generate(parse(_wasm(tmp_path, wabt, _REFS)), "tc_refs")
    assert glue.skipped == [] or all("is not an attribute" in item for item in glue.skipped)
    assert "def id(self, arg0: Function | Callable[..., object] | None, /) -> Function | None: ..." in glue.stub
    assert (
        "def pair(self, arg0: int, arg1: Function | Callable[..., object] | None, /) -> tuple[int, Function | None]: ..."
        in glue.stub
    )
    assert "int tc_refs_id(tc_refs_t *m, const void *a0, void **r0);" in glue.api_header
