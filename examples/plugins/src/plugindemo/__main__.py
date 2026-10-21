from __future__ import annotations

from . import make, standalone
from ._host import Trap


def main() -> None:
    host, double, _negate = make()
    print("the table has", host["table"].size, "slots; the plugins put double in slot 1, negate in 2 and boom in 3")
    for slot, name in ((0, "inc"), (1, "double"), (2, "negate")):
        print(f"host.call({slot}, 20) = {host.call(slot, 20)}   # {name}")
    print("double.call(2, 5) =", double.call(2, 5), "  # a plugin calls the function of another plugin")
    try:
        host.call(3, 1)
    except Trap as trap:
        print("host.call(3, 1) trapped:", trap, "  # the trap of a function of another module")
    print("the host goes on:", host.call(0, 1))

    table, inc_host, plugin = standalone()
    print("a table of its own: size", table.size, "maximum", table.maximum)
    print("slot 0 is", table.get(0).name, "put there from Python; plugin.call(0, 9) =", plugin.call(0, 9))
    table.grow(2)
    print("after grow(2) the plugin sees", plugin.size(), "slots")
    del inc_host


if __name__ == "__main__":
    main()
