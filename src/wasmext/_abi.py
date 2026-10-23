"""The version of the ABI of wasmext: the record that two instances pass between them (`wasmext_export` in `wasmext_glue.h`), the capsule that carries it,
and the C that a module is built with (`src/wasmext/c/`). It is one number made as `PY_VERSION_HEX` of CPython, `0xXXYYZZLS` (docs/abi_policy.md): x (XX) goes up
when something a module already built relies on is broken, y (YY) when something is added that breaks nothing, z (ZZ) for fixes only; L is the level of a
pre-release (A alpha, B beta, C release candidate, F final) and S its serial. It is not the version of the package, but at a release the two agree in the
numeric part. Modules built by different versions of wasmext link to each other where their x is the same, the reader is not below the `floor` of the
record. (The layout of the structs of the runtime of wasm2c is checked when a module is built, not when it is linked.)

The number is in `wasmext_glue.h` (`WASMEXT_ABI_X`, `_Y`, `_Z`, `_LS`), the one place; this module reads it from there. `tests/test_abi.py` holds the fingerprint of
the files of the ABI and fails when they change, and `tests/test_abi_declaration.py` holds the declaration of the public surface (abi/current.json), so that
nobody changes them without deciding what the version is.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

__all__ = ["ABI", "ABI_FINGERPRINT", "ABI_X", "abi_fingerprint", "capsule_name"]

C_DIR = Path(__file__).parent / "c"


def _read_abi() -> tuple[int, int]:
    """(the number, x) from the four `#define`s of the header."""
    text = (C_DIR / "wasmext_glue.h").read_text(encoding="utf-8")
    parts: list[int] = []
    for name in ("X", "Y", "Z", "LS"):
        found = re.search(rf"^#define WASMEXT_ABI_{name} (0x[0-9A-Fa-f]+|\d+)\s*$", text, re.MULTILINE)
        if found is None:
            raise RuntimeError(f"wasmext_glue.h does not define WASMEXT_ABI_{name}")
        parts.append(int(found.group(1), 0))
    x, y, z, ls = parts
    return (x << 24) | (y << 16) | (z << 8) | ls, x


ABI, ABI_X = _read_abi()


def capsule_name(x: int = ABI_X) -> str:
    """The name of the capsule that carries a record of this x: another x is another name, so a module of another x is not seen at all."""
    return f"wasmext.export.v{x}"


def abi_fingerprint(directory: Path = C_DIR) -> str:
    """The SHA-256 of all the files of `directory` (the C that every module is built with), by name and by content, with `\\r\\n` as `\\n`: a checkout on
    Windows may have the other line ends. Every file is taken, so a file that is added is in the fingerprint without anybody remembering it."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.iterdir() if p.is_file()):
        digest.update(path.name.encode() + b"\0" + path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


# The fingerprint of `src/wasmext/c/` for the ABI above. When `tests/test_abi.py` says it differs: if the change breaks what a module already built
# reads (a field moved, removed or changed in meaning, a trap code, the name of the capsule), raise WASMEXT_ABI in wasmext_glue.h; if the change
# only adds (a field at the end of the record) or does not touch the ABI at all (a fix in WASI, a comment, formatting), leave the number. Then put the new
# fingerprint here.
ABI_FINGERPRINT = "5d6b220b83336444473bf000909fc19cdeead46d218fc806c7a81c1f5361e7ca"
