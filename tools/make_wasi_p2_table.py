"""Make src/wasmext/_wasi_p2_table.py from the public data of fusedwasi: the table of signatures (`fusedwasi.signatures`) and the headers of WASI 0.2.

    python tools/make_wasi_p2_table.py [path-to-fusedwasi-include-dir]

The table says, for each function that fusedwasi has for an import of WASI 0.2 (the `c_name` of the table of signatures, `fusedwasi_wasi_<interface>_<name>`), the header it
is in (`wasi_p2_<package>.h`), whether it takes the number of the memory `comp` (`takes_comp`: a function that touches no memory does not), the types of its flat parameters
beside the guest and `comp` (`i32`, `i64`) and the type of its result; and, for each import (the module without its version, and the name), the function that answers it. The
generator of wasmext takes the function of an import from it and checks the core signature of the import against it. The headers that a header includes (`#include "wasi_p2_*.h"`
of the same directory) are read from the headers, to copy them all beside the glue.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main(include: Path, out: Path) -> None:
    from fusedwasi.signatures import load

    p2 = include / "fusedwasi" / "p2"
    funcs: dict[str, tuple[str, bool, tuple[str, ...], str]] = {}
    imports: dict[tuple[str, str], str] = {}
    for f in load("p2").functions:
        if f.c_name is None:  # a function that fusedwasi leaves out on purpose (null in the table)
            continue
        header = f"wasi_p2_{f.package.split(':', 1)[1]}.h"
        if not (p2 / header).is_file():
            raise SystemExit(f"{f.c_name}: the package {f.package} has no header {header} in {p2}")
        funcs[f.c_name] = (
            header,
            f.takes_comp,
            tuple(p.type for p in f.params),
            f.results[0].type if f.results else "",
        )
        imports[(f.module.split("@")[0], f.name)] = f.c_name
    if not funcs:  # a wrong table must not wipe the one that is committed
        raise SystemExit("no function of WASI 0.2 in the table of signatures: the table is not written")
    includes: dict[str, tuple[str, ...]] = {}
    for path in sorted(p2.glob("wasi_p2_*.h")):
        text = path.read_text(encoding="utf-8")
        includes[path.name] = tuple(re.findall(r'^#include "(wasi_p2_\w+\.h)"', text, re.MULTILINE))
    lines = [
        '"""The functions of WASI 0.2 that fusedwasi has in C, made by tools/make_wasi_p2_table.py from the table of signatures and the headers of fusedwasi: do not edit."""',
        "",
        "from __future__ import annotations",
        "",
        "# C name: (header, takes `comp`, types of the flat parameters beside the guest and `comp`, type of the result or an empty string)",
        "FUNCS: dict[str, tuple[str, bool, tuple[str, ...], str]] = {",
    ]
    for name in sorted(funcs):
        header, comp, ptypes, result = funcs[name]
        lines.append(f"    {name!r}: ({header!r}, {comp}, {ptypes!r}, {result!r}),")
    lines += [
        "}",
        "",
        "# (the module of an import without its version, its name): the C name of the function that answers it",
        "IMPORTS: dict[tuple[str, str], str] = {",
    ]
    for key in sorted(imports):
        lines.append(f"    {key!r}: {imports[key]!r},")
    lines += [
        "}",
        "",
        "# header: the headers of the same directory it includes",
        "INCLUDES: dict[str, tuple[str, ...]] = {",
    ]
    for name in sorted(includes):
        lines.append(f"    {name!r}: {includes[name]!r},")
    lines += ["}", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(funcs)} functions, {len(includes)} headers -> {out}")


if __name__ == "__main__":
    inc = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if inc is None:
        from fusedwasi import get_include

        inc = Path(get_include())
    main(inc, Path(__file__).resolve().parent.parent / "src" / "wasmext" / "_wasi_p2_table.py")
