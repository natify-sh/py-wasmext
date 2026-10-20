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


def test_a_host_in_c_uses_the_library_and_a_failing_host_function_is_a_trap_of_the_call(
    wabt: Path, tmp_path: Path
) -> None:
    ran = _library_and_host(
        wabt,
        tmp_path,
        (DATA / "shared_module.wat").read_text(encoding="utf-8"),
        (DATA / "shared_host.c").read_text(encoding="utf-8"),
        name="mod",
    )
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
    wabt: Path, tmp_path: Path, wat: str, host: str, *, libs: tuple[str, ...] = (), name: str = "m"
) -> subprocess.CompletedProcess[str]:
    """Make the shared library `name` of `wat`, compile the host C `host` against it, run it; the process. Where there is a `cc` it
    is that; on Windows it is the compiler of setuptools (MSVC), against the import library that `build_shared` leaves beside the dll."""
    cc = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    if cc is None and sys.platform != "win32":
        pytest.skip("no C compiler of the cc kind")
    (tmp_path / "m.wat").write_text(wat, encoding="utf-8")
    wasm = tmp_path / "m.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", tmp_path / "m.wat", "-o", wasm], check=True)
    suffix = ".dll" if sys.platform == "win32" else ".dylib" if platform.system() == "Darwin" else ".so"
    library = build_shared(wasm, tmp_path / f"lib{name}{suffix}", name=name, optimize=False, quiet=True)
    (tmp_path / "host.c").write_text(host, encoding="utf-8")
    include = tmp_path / f"{library.stem}_wasmext"
    if sys.platform == "win32":
        from wasmext._exe import _compiler  # pyright: ignore[reportPrivateUsage]

        compiler = _compiler()
        objects = compiler.compile(
            [str(tmp_path / "host.c")],
            output_dir=str(tmp_path / "hobj"),
            include_dirs=[str(include)],
            extra_postargs=["/w"],
        )
        compiler.link_executable(
            objects, str(tmp_path / "host"), library_dirs=[str(tmp_path)], libraries=[library.stem]
        )
        program = tmp_path / "host.exe"
    else:
        assert cc is not None
        program = tmp_path / "host"
        subprocess.run([cc, "-Wall", "-o", program, tmp_path / "host.c", f"-I{include}", library, *libs], check=True)
    env = {**os.environ, "LD_LIBRARY_PATH": str(tmp_path), "DYLD_LIBRARY_PATH": str(tmp_path)}
    return subprocess.run([program], capture_output=True, text=True, env=env, check=False, cwd=tmp_path)


_OOB_WAT = """(module (memory 1)
  (func (export "oob") (result i32) (i32.load (i32.const 70000)))
  (func (export "ok") (result i32) i32.const 1))"""

_OOB_HOST = r"""
#include <stdio.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <pthread.h>
#endif
#include "m_api.h"
static m_t *m;
static void report(void) {
    int32_t v = 0;
    int rc = m_oob(m, &v);
    printf("thread oob: %d (%s)\n", rc, m_trap_message(rc));
}
#ifdef _WIN32
static DWORD WINAPI other(LPVOID arg) { (void)arg; report(); return 0; }
#else
static void *other(void *arg) { report(); return arg; }
#endif
int main(void) {
    int e, rc;
    int32_t v = 0;
    m = m_new(NULL, &e);
    m_instantiate(m);
    rc = m_oob(m, &v);
    printf("oob: %d (%s)\n", rc, m_trap_message(rc));
    rc = m_ok(m, &v);
    printf("ok after: %d %d\n", rc, v);
#ifdef _WIN32
    HANDLE t = CreateThread(NULL, 0, other, NULL, 0, NULL);
    WaitForSingleObject(t, INFINITE);
#else
    pthread_t t;
    pthread_create(&t, NULL, other, NULL);
    pthread_join(t, NULL);
#endif
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


_HOOKS_WAT = """(module
  (import "wasi_snapshot_preview1" "clock_time_get" (func $clock (param i32 i64 i32) (result i32)))
  (import "wasi_snapshot_preview1" "random_get" (func $random (param i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "poll_oneoff" (func $poll (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") 1)
  ;; a subscription: userdata, tag 0 (a clock), clock id 1, timeout 5000000 ns, precision 0, flags 0
  (data (i32.const 256) "\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\01\\00\\00\\00\\00\\00\\00\\00\\40\\4b\\4c\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00\\00")
  (func (export "now") (param i32) (result i64)
    (drop (call $clock (local.get 0) (i64.const 0) (i32.const 0))) (i64.load (i32.const 0)))
  (func (export "rnd") (result i32)
    (drop (call $random (i32.const 8) (i32.const 4))) (i32.load (i32.const 8)))
  (func (export "nap") (result i32)
    (call $poll (i32.const 256) (i32.const 512) (i32.const 1) (i32.const 600))))"""

_HOOKS_HOST = r"""
#include <stdio.h>
#include <string.h>
#include "m_api.h"
static uint64_t slept;
static int clock_hook(void *user, uint32_t id, uint64_t *ns) { (void)user; *ns = 1000 + id; return 0; }
static int random_hook(void *user, uint8_t *buf, size_t n) { (void)user; memset(buf, 0xAB, n); return 0; }
static int sleep_hook(void *user, uint64_t ns) { (void)user; slept += ns; return 0; }
int main(void) {
    int e;
    m_config config;
    memset(&config, 0, sizeof config);
    config.clock = clock_hook;
    config.random = random_hook;
    config.sleep = sleep_hook;
    m_t *m = m_new(&config, &e);
    m_instantiate(m);
    int64_t t = 0;
    int32_t r = 0, errno_of_wasi = -1;
    m_now(m, 0, &t);
    printf("clock 0: %lld\n", (long long)t);
    m_now(m, 1, &t);
    printf("clock 1: %lld\n", (long long)t);
    m_rnd(m, &r);
    printf("random: %x\n", (unsigned)r);
    m_nap(m, &errno_of_wasi);
    printf("sleep: errno %d, slept %llu\n", errno_of_wasi, (unsigned long long)slept);
    m_free(m);
    return 0;
}
"""


def test_the_clock_the_random_bytes_and_the_sleep_of_wasi_are_hooks_of_the_host(wabt: Path, tmp_path: Path) -> None:
    ran = _library_and_host(wabt, tmp_path, _HOOKS_WAT, _HOOKS_HOST)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        "clock 0: 1000",
        "clock 1: 1001",
        "random: abababab",
        "sleep: errno 0, slept 5000000",
    ]


_REACTOR_WAT = """(module
  (memory (export "memory") 1)
  (global (export "version") i32 (i32.const 77))
  (global (export "counter") (mut i64) (i64.const 5))
  (global (export "ratio") (mut f64) (f64.const 0.5))
  (func (export "_initialize") (i32.store (i32.const 0) (i32.const 1234)) (global.set 1 (i64.const 6)))
  (func (export "peek") (result i32) (i32.load (i32.const 0)))
  (func (export "counter_plus") (param i64) (result i64) (global.get 1) (local.get 0) i64.add))"""

_REACTOR_HOST = r"""
#include <stdio.h>
#include "m_api.h"
int main(void) {
    int e;
    m_t *m = m_new(NULL, &e);
    int rc = m_instantiate(m);
    int32_t v = 0;
    m_peek(m, &v);
    printf("instantiate %d, peek %d (the _initialize was run)\n", rc, v);
    printf("version %d, counter %lld, ratio %g\n", m_global_version(m), (long long)m_global_counter(m), m_global_ratio(m));
    m_set_global_counter(m, 100);
    m_set_global_ratio(m, 2.5);
    int64_t r = 0;
    m_counter_plus(m, 1, &r);
    printf("after the set: counter %lld, plus 1 is %lld, ratio %g\n", (long long)m_global_counter(m), (long long)r, m_global_ratio(m));
    m_free(m);
    return 0;
}
"""


def test_a_reactor_is_initialized_by_the_library_and_its_globals_have_accessors(wabt: Path, tmp_path: Path) -> None:
    ran = _library_and_host(wabt, tmp_path, _REACTOR_WAT, _REACTOR_HOST)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        "instantiate 0, peek 1234 (the _initialize was run)",
        "version 77, counter 6, ratio 0.5",
        "after the set: counter 100, plus 1 is 101, ratio 2.5",
    ]
