from __future__ import annotations

import gc
import weakref

import plugindemo
import pytest
from plugindemo import _double, _host, _negate


def test_the_plugins_put_their_functions_in_the_table_of_the_host() -> None:
    host, double, negate = plugindemo.make()
    assert host.size() == double.size() == 8  # one table
    assert negate.negate(5) == -5
    assert host.call(0, 41) == 42  # the function of the host
    assert host.call(1, 21) == 42  # put there by _double
    assert host.call(2, 20) == -20  # put there by _negate
    assert double.call(2, 5) == -5  # a plugin calls the function of another plugin


def test_a_trap_in_a_plugin_comes_back_to_the_caller_and_everything_goes_on() -> None:
    host, double, _negate_instance = plugindemo.make()
    with pytest.raises(_host.Trap, match="Unreachable"):
        host.call(3, 1)
    with pytest.raises(_double.Trap, match="Unreachable"):
        double.call(3, 1)
    assert host.call(0, 1) == 2 and double.call(1, 3) == 6


def test_an_empty_slot_and_a_slot_of_another_type_are_traps() -> None:
    host, _double_instance, _negate_instance = plugindemo.make()
    with pytest.raises(_host.Trap):
        host.call(5, 1)  # nothing there


def test_the_table_of_the_host_is_a_table_that_python_can_read_and_grow() -> None:
    host, double, _negate_instance = plugindemo.make()
    table = host["table"]
    assert isinstance(table, _host.Table)
    assert (table.size, table.maximum) == (8, 16)
    inc, double_function = table.get(0), table.get(1)  # put by elem segments (of the host, of a plugin)
    assert inc.signature == (("i32",), ("i32",))
    # wasm2c puts a wrapper of its own in the table, which is no export, so there is no name; but a linker that folds identical code (MSVC on x86 and
    # ARM64) can give the wrapper the address of the export, and then the export is found and named
    assert inc.name in (None, "inc")
    assert inc(3) == 4 and double_function(21) == 42  # but a Function of a type the host declares is called
    assert table.get(5) is None
    assert table.grow(4) == 8
    assert host.size() == double.size() == 12
    with pytest.raises(ValueError, match="cannot grow"):
        table.grow(5)  # the maximum is 16


def test_a_table_of_its_own_with_a_function_put_in_it_from_python() -> None:
    table, _host_instance, plugin = plugindemo.standalone()
    assert (table.size, table.maximum) == (4, 16)
    assert table.get(0)(1) == 2 and table.get(0).name == "inc"  # the host's `inc`, as a Function that knows its name
    assert plugin.call(0, 9) == 10  # the plugin calls the host's function through a table nobody owns
    assert plugin.call(1, 9) == 18
    table.grow(2)
    assert plugin.size() == 6


def test_the_table_keeps_the_instances_whose_functions_it_holds_alive() -> None:
    table, host, plugin = plugindemo.standalone()
    ref = weakref.ref(host)
    del host
    gc.collect()
    assert ref() is not None  # its function is in slot 0
    assert plugin.call(0, 1) == 2
    del table, plugin
    gc.collect()
    assert ref() is None


def test_a_table_that_is_too_small_is_a_link_error() -> None:
    small = _negate.Table(2, 16)  # the plugins need 4 slots at least
    with pytest.raises(_negate.LinkError, match="at least 4"):
        _negate.Instance(_negate.Store(), imports={"env": {"table": small}})
    with pytest.raises(_negate.LinkError, match="may grow to"):
        _negate.Instance(
            _negate.Store(), imports={"env": {"table": _negate.Table(4)}}
        )  # no maximum, the plugin allows 16
