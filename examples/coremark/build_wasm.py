"""Build src/coremark/_core.wasm from the CoreMark of EEMBC with `zig cc` (the `ziglang` package), as wasm32-freestanding.

    uv run --group wasm python examples/coremark/build_wasm.py                 # clones https://github.com/eembc/coremark
    uv run --group wasm python examples/coremark/build_wasm.py --coremark DIR  # a checkout you already have

The port in port/ is the `barebones` port of CoreMark with the two imports of the module (wiring.millis, wiring.print)
and one export (setup). The files of EEMBC are used as they are, except ee_printf.c, whose uart_send_char is ours,
and barebones/cvt.c (the floating point of ee_printf).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "src" / "coremark" / "_core.wasm"
REPO = "https://github.com/eembc/coremark"
SOURCES = ("core_list_join.c", "core_main.c", "core_matrix.c", "core_state.c", "core_util.c")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--coremark", type=Path, help="a checkout of github.com/eembc/coremark (default: a fresh clone)"
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        src = args.coremark
        if src is None:
            src = Path(tmp) / "coremark"
            subprocess.run(["git", "clone", "--depth", "1", REPO, str(src)], check=True)
        printf = (src / "barebones" / "ee_printf.c").read_text(encoding="utf-8")
        printf = printf.replace('#error "You must implement the method uart_send_char to use this file!\\n";', "")
        printf = printf.replace("void\nuart_send_char(char c)", "static void unused_uart_send_char(char c)")
        patched = Path(tmp) / "ee_printf.c"
        patched.write_text(printf, encoding="utf-8")
        cmd = [
            sys.executable, "-m", "ziglang", "cc", "-target", "wasm32-freestanding", "-O3", "-nostdlib", "-w",
            "-DPERFORMANCE_RUN=1", "-DITERATIONS=0", "-DTOTAL_DATA_SIZE=2000",
            f"-I{src}", f"-I{HERE / 'port'}",
            *(str(src / name) for name in SOURCES), str(patched), str(src / "barebones" / "cvt.c"), str(HERE / "port" / "core_portme.c"),
            "-Wl,--no-entry", "-Wl,--export=setup", "-Wl,--strip-all", "-o", str(OUT),
        ]  # fmt: skip
        subprocess.run(cmd, check=True)
    print(f"{OUT.relative_to(HERE)}: {OUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
