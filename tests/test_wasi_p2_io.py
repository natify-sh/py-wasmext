"""wasi:io of the host of WASI 0.2 (`wasmext.p2.wasi_p2_io`, `c/p2/wasi_p2_io.h`): the same scenario in Python and in C, the outputs are equal.

No wasm2c and no module: a fake memory of 256 bytes, a bump allocator for `cabi_realloc`, the flat arguments as the core module gives them.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import wasmext
from wasmext.p2 import wasi_p2_io as io
from wasmext.p2.wasi_p2_core import Host, Trap, load_u32, store_u32

C_P2 = Path(wasmext.__file__).parent / "c" / "p2"
DRIVER = Path(__file__).parent / "data" / "wasi_p2_io_driver.c"
CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

SCENARIOS = ["streams", "failure", "bad_handle", "oversize", "empty_poll", "no_realloc"]


class FailingInput(io.InputStream):
    def read(self, n: int) -> bytes:
        raise io.StreamFailed("boom")

    def ready(self) -> bool:
        return False


class FailingOutput(io.OutputStream):
    def check_write(self) -> int:
        raise io.StreamFailed("boom")

    def ready(self) -> bool:
        return False


def python_output(scenario: str) -> str:
    memory = bytearray(256)
    memory[100:105] = b"hello"
    next_free = [160]

    def bump(comp: int, old_ptr: int, old_size: int, align: int, new_size: int) -> int:
        ptr = (next_free[0] + align - 1) // align * align
        next_free[0] = ptr + new_size
        return ptr

    host = Host([memory], realloc=None if scenario == "no_realloc" else bump)
    lines: list[str] = []

    def dump(what: str) -> None:
        lines.append(f"{what} {bytes(memory).hex()}")

    i = io.input_stream_new(host, io.MemoryInput(b"abcdefghij"))
    j = io.input_stream_new(host, io.MemoryInput(b"xyz"))
    out, out2 = io.BufferOutput(8), io.BufferOutput(100)
    o, o2 = io.output_stream_new(host, out), io.output_stream_new(host, out2)
    lines.append(f"handles {i} {j} {o} {o2}")
    try:
        if scenario == "streams":
            io.wasi_io_streams_input_stream_read(host, 0, i, 4, 0)
            dump("read")
            io.wasi_io_streams_input_stream_skip(host, 0, i, 2, 16)
            dump("skip")
            io.wasi_io_streams_output_stream_check_write(host, 0, o, 32)
            dump("check_write")
            io.wasi_io_streams_output_stream_write(host, 0, o, 100, 5, 48)
            dump("write")
            io.wasi_io_streams_output_stream_check_write(host, 0, o, 64)
            dump("check_write")
            io.wasi_io_streams_output_stream_write_zeroes(host, 0, o, 3, 80)
            dump("write_zeroes")
            io.wasi_io_streams_output_stream_check_write(host, 0, o, 96)
            dump("check_write")
            io.wasi_io_streams_output_stream_flush(host, 0, o, 112)
            dump("flush")
            io.wasi_io_streams_output_stream_splice(host, 0, o2, j, 10, 120)
            dump("splice")
            io.wasi_io_streams_output_stream_splice(host, 0, o2, j, 10, 136)
            dump("splice")
            io.wasi_io_streams_input_stream_read(host, 0, i, 100, 0)
            dump("read")
            io.wasi_io_streams_input_stream_read(host, 0, i, 100, 16)
            dump("read")
            p = io.wasi_io_streams_input_stream_subscribe(host, i)
            lines.append(f"pollable {p} ready {io.wasi_io_poll_pollable_ready(host, p)}")
            store_u32(host, 0, 90, p)
            io.wasi_io_poll_poll(host, 0, 90, 1, 32)
            dump("poll")
            io.wasi_io_poll_pollable_block(host, p)
            e = io.error_new(host, "boom")
            io.wasi_io_error_error_to_debug_string(host, 0, e, 48)
            dump("to_debug_string")
            io.wasi_io_error_error_drop(host, e)
            io.wasi_io_streams_output_stream_blocking_write_and_flush(host, 0, o2, 100, 5, 64)
            dump("blocking_write_and_flush")
            io.wasi_io_streams_output_stream_blocking_write_zeroes_and_flush(host, 0, o2, 50, 64)
            dump("blocking_write_zeroes_and_flush")
            io.wasi_io_streams_input_stream_blocking_read(host, 0, j, 5, 16)
            dump("blocking_read")
            lines.append(f"o {bytes(out.data).hex()}")
            lines.append(f"o2 {len(out2.data)}")
            lines.append(f"o2 {bytes(out2.data[:16]).hex()}")
            io.wasi_io_poll_pollable_drop(host, p)
            io.wasi_io_streams_input_stream_drop(host, i)
            io.wasi_io_streams_output_stream_drop(host, o)
        elif scenario == "failure":
            hfi, hfo = io.input_stream_new(host, FailingInput()), io.output_stream_new(host, FailingOutput())
            lines.append(f"failing {hfi} {hfo}")
            io.wasi_io_streams_input_stream_read(host, 0, hfi, 4, 0)
            dump("read fails")
            io.wasi_io_streams_input_stream_read(host, 0, hfi, 4, 16)
            dump("read after the failure")
            p = io.wasi_io_streams_input_stream_subscribe(host, hfi)
            lines.append(f"pollable of a closed stream: ready {io.wasi_io_poll_pollable_ready(host, p)}")
            io.wasi_io_error_error_to_debug_string(host, 0, load_u32(host, 0, 8), 80)
            dump("message")
            io.wasi_io_streams_output_stream_check_write(host, 0, hfo, 96)
            dump("check_write fails")
            io.wasi_io_streams_output_stream_write(host, 0, hfo, 100, 1, 112)
            dump("write after the failure")
            io.wasi_io_streams_output_stream_flush(host, 0, hfo, 128)
            dump("flush after the failure")
        elif scenario == "bad_handle":
            io.wasi_io_streams_input_stream_read(host, 0, o, 4, 0)
        elif scenario == "oversize":
            io.wasi_io_streams_output_stream_write(host, 0, o, 100, 5, 0)
            io.wasi_io_streams_output_stream_write(host, 0, o, 100, 5, 0)
        elif scenario == "empty_poll":
            io.wasi_io_poll_poll(host, 0, 90, 0, 32)
        elif scenario == "no_realloc":
            io.wasi_io_streams_input_stream_read(host, 0, i, 4, 0)
    except Trap:
        lines.append("TRAP")
    return "\n".join(lines) + "\n"


def c_output(scenario: str, binary: Path) -> str:
    out = subprocess.run([str(binary), scenario], capture_output=True, text=True, check=True, timeout=60).stdout
    return "\n".join("TRAP" if line.startswith("TRAP") else line for line in out.splitlines()) + "\n"


@pytest.fixture(scope="module")
def driver(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if CC is None or sys.platform == "win32":
        pytest.skip("no C compiler of the POSIX kind")
    binary = tmp_path_factory.mktemp("p2io") / "driver"
    subprocess.run(
        [CC, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-I", str(C_P2), str(DRIVER), "-o", str(binary)], check=True
    )
    return binary


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_c_and_python_agree(driver: Path, scenario: str) -> None:
    assert python_output(scenario) == c_output(scenario, driver)


def test_values() -> None:
    lines = python_output("streams").splitlines()
    # the output with the limit of 8 took "hello" and three zeroes; the other one took "xyz" (a splice), "hello" and 50 zeroes
    assert "o 68656c6c6f000000" in lines
    assert "o2 58" in lines
    assert lines[1].startswith("read ")  # a read of 4 bytes: ok, the list at 160 (a0000000), length 4
    assert lines[1].split()[1].startswith("00000000a000000004000000")


def test_a_failed_stream_is_closed() -> None:
    lines = python_output("failure").splitlines()
    first, second = (
        bytes.fromhex(line.split()[-1]) for line in lines if line.startswith(("read fails", "read after the failure"))
    )
    assert first[0] == 1 and first[4] == 0  # err, last-operation-failed (with an error resource)
    assert second[16] == 1 and second[20] == 1  # err, closed
    assert "pollable of a closed stream: ready 1" in lines  # ready although its own ready() says no
    check, write, flush = (
        bytes.fromhex(next(x for x in lines if x.startswith(k)).split()[-1])
        for k in ("check_write fails", "write after", "flush after")
    )
    assert check[96] == 1 and check[104] == 0  # last-operation-failed
    assert write[112] == 1 and write[116] == 1  # closed
    assert flush[128] == 1 and flush[132] == 1  # closed


@pytest.mark.parametrize("scenario", ["bad_handle", "oversize", "empty_poll", "no_realloc"])
def test_traps(scenario: str) -> None:
    assert python_output(scenario).splitlines()[-1] == "TRAP"
