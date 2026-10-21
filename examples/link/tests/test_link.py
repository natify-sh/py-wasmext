from __future__ import annotations

import linkdemo
import pytest
from linkdemo import _app


def test_app_calls_counter_and_shares_its_variable_and_memory() -> None:
    said: list[int] = []
    counter, app = linkdemo.make(said.append)
    assert app.tick() == 1
    assert app.tick() == 2
    assert said == [1, 2]  # `log` is the only thing that went through Python
    assert counter.count == app.count() == 2  # one variable, seen from both
    app.reset()
    assert counter.count == 0
    counter.count = 40
    assert app.tick() == 41

    assert bytes(app.peek(i) for i in range(5)) == b"hello"  # app reads the memory of counter
    app.poke(0, ord("H"))
    assert bytes(counter.memory[:5]) == b"Hello"


def test_what_is_not_the_right_kind_is_a_link_error() -> None:
    counter, _ = linkdemo.make()
    exports = {**counter.__exports__, "log": print}
    with pytest.raises(_app.LinkError):
        _app.Instance({"env": {**exports, "count": 0}})  # a number is not a variable that two modules can share
    with pytest.raises(_app.LinkError):
        _app.Instance({"env": {**exports, "bump": exports["memory"]}})
