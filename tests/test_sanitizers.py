"""A canary for the job of .github/workflows/sanitizers.yml: when the tests are run with sanitizer flags (WASMEXT_TEST_CFLAGS), a program with a bug must really
be stopped by them. If it is not, the job would pass for the wrong reason (the flags not given to the compiler, the runtime of ASan not loaded), and this test says so.
Without the flags it is skipped."""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_FLAGS = shlex.split(os.environ.get("WASMEXT_TEST_CFLAGS", ""))

pytestmark = pytest.mark.skipif(
    not any(f.startswith("-fsanitize") for f in _FLAGS), reason="WASMEXT_TEST_CFLAGS has no -fsanitize flag"
)

_OVERFLOW = """
#include <stdlib.h>
int main(int argc, char **argv) {
    char *p = malloc(8);
    p[8 + argc] = 1;  /* one past the end of the block */
    int r = p[0];
    free(p);
    return r;
}
"""

_SIGNED_OVERFLOW = """
#include <limits.h>
int main(int argc, char **argv) {
    int x = INT_MAX - 1 + argc;  /* argc is 1: INT_MAX */
    x += argc;                   /* signed overflow */
    return x != 0;
}
"""


def _run(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    assert cc is not None
    c = tmp_path / "bug.c"
    c.write_text(source, encoding="utf-8")
    exe = tmp_path / "bug"
    subprocess.run([cc, "-O1", *_FLAGS, str(c), "-o", str(exe)], check=True)
    env = {k: v for k, v in os.environ.items() if k != "LD_PRELOAD"}  # the program is instrumented itself
    return subprocess.run([str(exe)], capture_output=True, text=True, check=False, env=env, timeout=60)


def test_a_heap_buffer_overflow_stops_the_program(tmp_path: Path) -> None:
    ran = _run(tmp_path, _OVERFLOW)
    # UBSan (object-size) may report it before ASan does: either is the loud stop that is wanted
    assert ran.returncode != 0 and ("AddressSanitizer" in ran.stderr or "runtime error" in ran.stderr), (
        ran.returncode,
        ran.stderr[-300:],
    )


def test_undefined_behaviour_stops_the_program(tmp_path: Path) -> None:
    if not any("undefined" in f for f in _FLAGS):
        pytest.skip("UBSan is not in the flags")
    ran = _run(tmp_path, _SIGNED_OVERFLOW)
    assert ran.returncode != 0 and "runtime error" in ran.stderr, (ran.returncode, ran.stderr[-300:])


def test_the_runtime_of_the_sanitizer_is_loaded_into_the_interpreter() -> None:
    """The extensions are instrumented and the interpreter is not: the runtime of ASan has to be preloaded, or the extensions do not load."""
    if not any("address" in f for f in _FLAGS) or sys.platform != "linux":
        pytest.skip("ASan on Linux only")
    assert "libasan" in os.environ.get("LD_PRELOAD", ""), "LD_PRELOAD does not name libasan"
