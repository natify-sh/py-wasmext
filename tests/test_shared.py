"""The C API of a module as a shared library (wasmext._shared, built by wasmext._exe.build_shared): checked with a host in C, with no Python anywhere in it —
the protocol of errors of host functions (stage 6a of the plan)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from wasmext._exe import build_shared  # pyright: ignore[reportPrivateUsage]

from .conftest import DATA


@pytest.mark.skipif(sys.platform == "win32", reason="the host is linked with cc; Windows is tried in CI")
def test_a_host_in_c_uses_the_library_and_a_failing_host_function_is_a_trap_of_the_call(
    wabt: Path, tmp_path: Path
) -> None:
    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler of the cc kind")
    wasm = tmp_path / "mod.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "shared_module.wat", "-o", wasm], check=True)
    suffix = ".dylib" if platform.system() == "Darwin" else ".so"
    library = build_shared(wasm, tmp_path / f"libmod{suffix}", name="mod", optimize=False)
    host = tmp_path / "host"
    subprocess.run(
        [cc, "-Wall", "-o", host, DATA / "shared_host.c", f"-I{tmp_path / 'libmod_wasmext'}", library],
        check=True,
    )
    env = {**os.environ, "LD_LIBRARY_PATH": str(tmp_path), "DYLD_LIBRARY_PATH": str(tmp_path)}
    ran = subprocess.run([host], capture_output=True, text=True, env=env, check=False)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        "instantiate without the import: LINK_ERROR",
        "instantiate: 0",
        "add: 0 5",
        "twice: 0 7 7",
        "call_log: 0 101",
        "call_log again: 0 102",
        "call_log failing: TRAP_HOST, host calls 3",
        "add after the failure: 0 42",
        "trap: 1 (Unreachable instruction executed)",
        "boom: exception 1 tag 0 count 1 value -9",
        "memory: 65536 hi",
    ]


def test_a_module_that_imports_a_global_has_no_shared_library_yet(wabt: Path, tmp_path: Path) -> None:
    from wasmext import GenError

    wat = tmp_path / "g.wat"
    wat.write_text(
        '(module (import "env" "g" (global i32)) (func (export "f") (result i32) global.get 0))', encoding="utf-8"
    )
    wasm = tmp_path / "g.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    with pytest.raises(GenError, match="imports a global"):
        build_shared(wasm, tmp_path / "libg.so", name="g", optimize=False)


def _library_and_host(
    wabt: Path, tmp_path: Path, wat: str, host: str, *, libs: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """Make the shared library `m` of `wat`, compile the host C `host` against it, run it; the process."""
    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    if cc is None or sys.platform == "win32":
        pytest.skip("the host is linked with cc; Windows is tried in CI")
    (tmp_path / "m.wat").write_text(wat, encoding="utf-8")
    wasm = tmp_path / "m.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", tmp_path / "m.wat", "-o", wasm], check=True)
    suffix = ".dylib" if platform.system() == "Darwin" else ".so"
    library = build_shared(wasm, tmp_path / f"libm{suffix}", name="m", optimize=False, quiet=True)
    (tmp_path / "host.c").write_text(host, encoding="utf-8")
    subprocess.run(
        [cc, "-Wall", "-o", tmp_path / "host", tmp_path / "host.c", f"-I{tmp_path / 'libm_wasmext'}", library, *libs],
        check=True,
    )
    env = {**os.environ, "LD_LIBRARY_PATH": str(tmp_path), "DYLD_LIBRARY_PATH": str(tmp_path)}
    return subprocess.run([tmp_path / "host"], capture_output=True, text=True, env=env, check=False, cwd=tmp_path)


_OOB_WAT = """(module (memory 1)
  (func (export "oob") (result i32) (i32.load (i32.const 70000)))
  (func (export "ok") (result i32) i32.const 1))"""

_OOB_HOST = r"""
#include <pthread.h>
#include <stdio.h>
#include "m_api.h"
static m_t *m;
static void *other(void *arg) {
    int32_t v = 0;
    int rc = m_oob(m, &v);
    printf("thread oob: %d (%s)\n", rc, m_trap_message(rc));
    return arg;
}
int main(void) {
    int e, rc;
    int32_t v = 0;
    m = m_new(NULL, &e);
    m_instantiate(m);
    rc = m_oob(m, &v);
    printf("oob: %d (%s)\n", rc, m_trap_message(rc));
    rc = m_ok(m, &v);
    printf("ok after: %d %d\n", rc, v);
    pthread_t t;
    pthread_create(&t, NULL, other, NULL);
    pthread_join(t, NULL);
    rc = m_ok(m, &v);
    printf("ok after thread: %d %d\n", rc, v);
    m_free(m);
    return 0;
}
"""


def test_an_out_of_bounds_access_is_a_trap_of_the_call_not_a_crash_of_the_host(wabt: Path, tmp_path: Path) -> None:
    """The runtime of wasm2c is set up by the library itself (the extension and the executable do it in their own ways): without it the host dies of SIGSEGV."""
    ran = _library_and_host(wabt, tmp_path, _OOB_WAT, _OOB_HOST, libs=("-lpthread",))
    assert ran.returncode == 0, (ran.returncode, ran.stdout, ran.stderr)
    lines = ran.stdout.splitlines()
    assert len(lines) == 4, ran.stdout
    assert lines[0].startswith("oob: ") and "(Out-of-bounds access" in lines[0]
    assert lines[1] == "ok after: 0 1"
    assert lines[2].startswith("thread oob: ") and "(Out-of-bounds access" in lines[2]
    assert lines[3] == "ok after thread: 0 1"


_HELLO_HOST = r"""
#include <stdio.h>
#include <string.h>
#include "m_api.h"
static char out[64];
static size_t n;
static int write_hook(void *user, int fd, const uint8_t *buf, size_t k) {
    (void)user; (void)fd;
    memcpy(out + n, buf, k);
    n += k;
    return 0;
}
int main(void) {
    int e;
    m_config config;
    memset(&config, 0, sizeof config);
    config.stdout_write = write_hook;
    m_t *m = m_new(&config, &e);
    m_instantiate(m);
    int rc = m__start(m);
    uint32_t value = 0;
    int how = m_wasi_end(m, &value);
    printf("start: %s, end %d, value %u, wrote [%.*s]\n", rc == M_TRAP_ENDED ? "ENDED" : "other", how, value, (int)(n - 1), out);
    printf("again: %s\n", m__start(m) == M_TRAP_ENDED ? "ENDED" : "other");
    m_free(m);
    return 0;
}
"""


def test_the_call_in_which_a_wasi_program_ends_answers_the_end_not_a_failure_of_the_host(
    wabt: Path, tmp_path: Path
) -> None:
    ran = _library_and_host(wabt, tmp_path, (DATA / "wasi_hello.wat").read_text(encoding="utf-8"), _HELLO_HOST)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == ["start: ENDED, end 1, value 3, wrote [hello, wasi]", "again: ENDED"]


def test_an_export_that_cannot_be_in_the_library_is_said_in_the_header_and_on_stderr(
    wabt: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wat = tmp_path / "m.wat"
    wat.write_text(
        '(module (table (export "t") 1 funcref) (func (export "r") (param funcref)) (func (export "f") (result i32) i32.const 1))',
        encoding="utf-8",
    )
    wasm = tmp_path / "m.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", wat, "-o", wasm], check=True)
    build_shared(wasm, tmp_path / ("libm.dll" if sys.platform == "win32" else "libm.so"), name="m", optimize=False)
    header = (tmp_path / "libm_wasmext" / "m_api.h").read_text(encoding="utf-8")
    assert "not here: table 't'" in header
    assert "not here: function 'r'" in header
    assert "m_f(" in header
    err = capsys.readouterr().err
    assert "table 't'" in err and "function 'r'" in err
