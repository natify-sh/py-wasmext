"""A host built at -O0 that includes the headers of the core links without the symbols that only an artifact defines (S0008, 8b-2 review): gcc keeps a file-scope `static const` that nobody uses
(-fkeep-static-consts), and with it the functions it names, so a table of operations at file scope drags the thread state of the runtime into every host."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fusedwasi import get_include

from wasmext._toolchain import find_toolchain

from .c_build import compile_c, find_cc

HERE = Path(__file__).parent
WASMEXT_C = HERE.parent / "src" / "wasmext" / "c"
ARTIFACT_ONLY = ("wasmext_tls_", "wasmext_runtime_own_", "wasmext_artifact_", "wasm_rt_init")


@pytest.mark.parametrize("opt", ["-O0", "-O2"])
def test_a_host_at_o0_links_without_the_symbols_of_an_artifact(tmp_path: Path, opt: str) -> None:
    cc = find_cc()
    nm = shutil.which("nm")
    if cc is None or nm is None:
        pytest.skip("no C compiler or no nm")
    exe = tmp_path / "host_links"
    compile_c(
        [HERE / "c" / "host_links.c"],
        exe,
        include_dirs=[WASMEXT_C, Path(get_include()), find_toolchain().runtime],
        flags=[opt],
        defines=["WASMEXT_STORE_RUNTIME=1"],
        strict=False,
        std=None,
    )
    undefined = subprocess.run([nm, "-u", str(exe)], capture_output=True, text=True, check=True).stdout
    found = [name for name in ARTIFACT_ONLY if name in undefined]
    assert not found, f"the host needs {found}: a table of operations at file scope drags the close functions into it"
