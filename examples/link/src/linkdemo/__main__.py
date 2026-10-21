from __future__ import annotations

from . import make


def main() -> None:
    counter, app = make(lambda n: print(f"app says the count is {n}"))
    app.tick()
    app.tick()
    print("the variable of counter:", counter.count)
    print("the memory of counter, read by app:", bytes(app.peek(i) for i in range(18)).decode())
    app.poke(0, ord("H"))
    print("after app wrote to it, counter's memory starts with:", bytes(counter.memory[:5]).decode())


if __name__ == "__main__":
    main()
