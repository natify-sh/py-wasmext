"""Make src/wasmext/_wasi_p2_table.py from the headers of WASI 0.2 in fusedwasi (`fusedwasi/p2/wasi_p2_*.h`).

    python tools/make_wasi_p2_table.py [path-to-fusedwasi-include-dir]

The table says, for each function that fusedwasi has for an import of WASI 0.2 (`fusedwasi_wasi_<interface>_<name>`), the header it is in, whether it takes
the number of the memory `comp` (a function that touches no memory does not), the types of its parameters beside the state and `comp` (`i32`, `i64`) and the type of
its result. The generator of wasmext takes the function for an import by name from it and checks the core signature of the import against it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

C_TYPES = {"uint32_t": "i32", "uint64_t": "i64"}
SKIP = ("fs_posix.h", "fs_win32.h")


def main(include: Path, out: Path) -> None:
    p2 = include / "fusedwasi" / "p2"
    funcs: dict[str, tuple[str, bool, tuple[str, ...], str]] = {}
    includes: dict[str, tuple[str, ...]] = {}
    for path in sorted(p2.glob("wasi_p2_*.h")):
        text = path.read_text(encoding="utf-8")
        includes[path.name] = tuple(re.findall(r'^#include "(wasi_p2_\w+\.h)"', text, re.MULTILINE))
        if path.name.endswith(SKIP):
            continue
        for m in re.finditer(
            r"^FUSEDWASI_P2_FN\s+([\w\s\*]+?)\s+(fusedwasi_wasi_\w+)\s*\(([^)]*)\)", text, re.MULTILINE
        ):
            ret, name, params = m.groups()
            items = [p.strip() for p in params.split(",")]
            assert items[0].startswith("fusedwasi_p2_state"), name
            has_comp = len(items) > 1 and items[1].endswith(" comp")
            rest = items[2 if has_comp else 1 :]
            types: list[str] = []
            for p in rest:
                ctype = p.rsplit(" ", 1)[0].strip()
                types.append(C_TYPES[ctype])
            result = "" if ret.strip() == "void" else C_TYPES[ret.strip()]
            funcs[name] = (path.name, has_comp, tuple(types), result)
    if not funcs:  # a wrong directory must not wipe the table that is committed
        raise SystemExit(f"no function of WASI 0.2 found in {p2}: the table is not written")
    lines = [
        '"""The functions of WASI 0.2 that fusedwasi has in C, made by tools/make_wasi_p2_table.py from the headers of fusedwasi: do not edit."""',
        "",
        "from __future__ import annotations",
        "",
        "# C name: (header, takes `comp`, types of the parameters beside the state and `comp`, type of the result or an empty string)",
        "FUNCS: dict[str, tuple[str, bool, tuple[str, ...], str]] = {",
    ]
    for name in sorted(funcs):
        header, comp, ptypes, result = funcs[name]
        lines.append(f"    {name!r}: ({header!r}, {comp}, {ptypes!r}, {result!r}),")
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
