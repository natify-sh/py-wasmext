"""python -m wasi2python [--preopen HOST=GUEST]... [--env NAME=VALUE]... [--pip-shims] -- ARGUMENTS...

The first preopen should be the directory made by tools/make_stdlib.py, as /py; /tmp is the host's temporary directory unless given.
"""

import argparse
import sys
import tempfile

from . import run


def main() -> int:
    parser = argparse.ArgumentParser(prog="wasi2python")
    parser.add_argument("--preopen", action="append", default=[], metavar="HOST=GUEST")
    parser.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("arguments", nargs="*")
    options = parser.parse_args()
    preopens = [tuple(p.split("=", 1)) for p in options.preopen]
    if not any(guest == "/tmp" for _, guest in preopens):
        preopens.append((tempfile.mkdtemp(), "/tmp"))
    environment = {"PYTHONHOME": "/py", "PYTHONDONTWRITEBYTECODE": "1", **dict(e.split("=", 1) for e in options.env)}
    return run(options.arguments, preopens, environment=environment, stdout=sys.stdout.buffer, stderr=sys.stderr.buffer)


if __name__ == "__main__":
    sys.exit(main())
