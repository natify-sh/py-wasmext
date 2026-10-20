"""Check (a) of the "C first" plan for the glue: writes the files that wasmext makes for a few modules (the glue `<name>_glue.h`, the C API `<name>_api.h` and
`<name>_shared.c`, the `main()` of a program `<name>_main.c`) and prints the C files to compile, so that the workflow can compile them strictly with no Python on the include
path. (The tests do compile them, but with the warnings off, as the C of wasm2c needs.)

    python glue_without_python.py OUT_DIR   ->  one path of a .c file to check on each line; the headers are beside them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from wasmext import generate, parse
from wasmext._exe import main_c
from wasmext._gen import module_prefix

DATA = Path(__file__).resolve().parents[2] / "tests" / "data"
# a WASI command, a module with imports and exports of every kind, and a reactor
MODULES = ("wasi_hello.wat", "shared_module.wat", "features.wat")


def main(out: Path) -> int:
    import wabt_package  # noqa: PLC0415

    wabt = Path(wabt_package.__file__).parent
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for source in MODULES:
        name = Path(source).stem
        wasm = out / f"{name}.wasm"
        subprocess.run([wabt / "bin" / "wat2wasm", DATA / source, "-o", wasm], check=True)
        glue = generate(parse(wasm.read_bytes()), name)
        (out / f"{name}_glue.h").write_text(glue.header, encoding="utf-8")
        subprocess.run(
            [wabt / "bin" / "wasm2c", wasm, "-o", out / f"{name}_w2c.c", f"--module-name={name}"], check=True
        )
        if glue.api_header:
            (out / f"{name}_api.h").write_text(glue.api_header, encoding="utf-8")
            (out / f"{name}_shared.c").write_text(glue.shared, encoding="utf-8")
            files.append(out / f"{name}_shared.c")
        if f"{name.upper()}_START" in glue.header:
            (out / f"{name}_main.c").write_text(main_c(name, module_prefix(name)), encoding="utf-8")
            files.append(out / f"{name}_main.c")
    for path in files:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
