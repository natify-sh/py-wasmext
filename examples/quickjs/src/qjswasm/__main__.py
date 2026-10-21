"""python -m qjswasm [qjs options] [script.js]: QuickJS, with the current directory as its whole world."""

from __future__ import annotations

import sys

from . import run


def main() -> int:
    stdin = b"" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.buffer.read()
    result = run(sys.argv[1:], stdin=stdin, root=".")
    sys.stdout.buffer.write(result.stdout)
    sys.stdout.flush()
    sys.stderr.buffer.write(result.stderr)
    return result.code


if __name__ == "__main__":
    raise SystemExit(main())
