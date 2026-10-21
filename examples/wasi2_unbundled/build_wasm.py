"""Build src/wasi2demo/_hello.wasm and _sock.wasm from c/*.c, and src/wasi2demo/_imports.py.

Each program is built as a WASI 0.2 component (`clang --target=wasm32-wasip2`), and the core module of the component is taken out of it with
`wasm-tools component unbundle`: that module is what `wasm2c` reads (it does not read a component).

    WASI_SDK_PATH=/opt/wasi-sdk-34.0 python build_wasm.py

Needs wasi-sdk 34 (`clang` for `wasm32-wasip2`), `wasm-tools` on the PATH (`uv tool install wasm-tools-package`) and the wabt-package
(`wasm-objdump`, to list the imports).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import wabt_package

HERE = Path(__file__).resolve().parent
PACKAGE = HERE / "src" / "wasi2demo"


def build(source: Path, out: Path) -> None:
    sdk = os.environ.get("WASI_SDK_PATH")
    if sdk is None:
        raise SystemExit("set WASI_SDK_PATH to the directory of wasi-sdk 34")
    if shutil.which("wasm-tools") is None:
        raise SystemExit("wasm-tools is not on the PATH (uv tool install wasm-tools-package)")
    with tempfile.TemporaryDirectory() as tmp:
        component = Path(tmp) / "component.wasm"
        subprocess.run(
            [f"{sdk}/bin/clang", "--target=wasm32-wasip2", "-O1", str(source), "-o", str(component)], check=True
        )
        modules = Path(tmp) / "modules"
        modules.mkdir()
        subprocess.run(
            [
                "wasm-tools",
                "component",
                "unbundle",
                str(component),
                "--module-dir",
                str(modules),
                "-o",
                str(Path(tmp) / "rest.wasm"),
            ],
            check=True,
        )
        shutil.copyfile(modules / "unbundled-module0.wasm", out)


def imports_of(module: Path) -> dict[str, list[str]]:
    """The imports of a core module, by module name, as `wasm-objdump -x` lists them."""
    dump = subprocess.run(
        [str(wabt_package.get_executable("wasm-objdump")), "-x", str(module)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    found: dict[str, list[str]] = {}
    for match in re.finditer(r"<- (wasi:[^@\s]+@[\d.]+)\.(\S.*)$", dump, re.MULTILINE):
        found.setdefault(match.group(1), []).append(match.group(2))
    return found


def main() -> None:
    union: dict[str, list[str]] = {}
    for source in sorted((HERE / "c").glob("*.c")):
        out = PACKAGE / f"_{source.stem}.wasm"
        build(source, out)
        print(f"{source.name} -> {out.relative_to(HERE)} ({out.stat().st_size} bytes)")
        for module, names in imports_of(out).items():
            known = union.setdefault(module, [])
            known.extend(name for name in names if name not in known)
    lines = [
        '"""The imports of the core modules of this package, by module: made by build_wasm.py, do not edit."""',
        "",
        "IMPORTS: dict[str, list[str]] = {",
    ]
    for module, names in sorted(union.items()):
        lines.append(f"    {module!r}: [")
        lines.extend(f"        {name!r}," for name in names)
        lines.append("    ],")
    lines.append("}")
    (PACKAGE / "_imports.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"_imports.py: {sum(len(v) for v in union.values())} imports of {len(union)} modules")


if __name__ == "__main__":
    main()
