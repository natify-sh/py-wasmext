"""wasi:cli of the host of WASI 0.2 (`wasmext.p2.wasi_p2_cli`, `c/p2/wasi_p2_cli.h`): the same scenario in Python and in C, the outputs are equal.

The standard streams are streams of the caller (memory) and, in one scenario, pipes; the default streams (the process, `sys.stdout`) are not touched.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import wasmext
from wasmext.p2 import wasi_p2_cli as cli
from wasmext.p2 import wasi_p2_io as io
from wasmext.p2.wasi_p2_core import Exit, Host, Trap, load_u32

C_P2 = Path(wasmext.__file__).parent / "c" / "p2"
DRIVER = Path(__file__).parent / "data" / "wasi_p2_cli_driver.c"
CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

SCENARIOS = ["main", "fd", "exit_ok", "exit_err", "exit_code"]
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the driver uses pipe() and poll()")


def python_output(scenario: str) -> str:
    memory = bytearray(256)
    memory[120:125] = b"hello"
    next_free = [160]

    def bump(comp: int, old_ptr: int, old_size: int, align: int, new_size: int) -> int:
        ptr = (next_free[0] + align - 1) // align * align
        next_free[0] = ptr + new_size
        return ptr

    lines: list[str] = []

    def dump(what: str) -> None:
        lines.append(f"{what} {bytes(memory).hex()}")

    common = {"realloc": bump, "args": ["prog", "-x"], "env": [("A", "1"), ("LONG", "value")], "initial_cwd": "/work"}
    try:
        if scenario == "main":
            stdin, stdout = io.MemoryInput(b"in!"), io.BufferOutput(100)
            host = Host([memory], stdin=stdin, stdout=stdout, terminals=["stdout"], **common)
            hi, ho = io.input_stream_new(host, stdin), io.output_stream_new(host, stdout)
            lines.append(f"handles {hi} {ho}")
            cli.wasi_cli_environment_get_arguments(host, 0, 0), dump("arguments")
            cli.wasi_cli_environment_get_environment(host, 0, 16), dump("environment")
            cli.wasi_cli_environment_initial_cwd(host, 0, 40), dump("cwd")
            cli.wasi_cli_terminal_stdin_get_terminal_stdin(host, 0, 56), dump("terminal stdin")
            cli.wasi_cli_terminal_stdout_get_terminal_stdout(host, 0, 64), dump("terminal stdout")
            cli.wasi_cli_terminal_output_terminal_output_drop(host, load_u32(host, 0, 68))
            a, b, c = (
                cli.wasi_cli_stdin_get_stdin(host),
                cli.wasi_cli_stdout_get_stdout(host),
                cli.wasi_cli_stdout_get_stdout(host),
            )
            lines.append(f"std handles {a} {b} {c}")
            io.wasi_io_streams_output_stream_write(host, 0, b, 120, 5, 80), dump("write")
            io.wasi_io_streams_output_stream_drop(host, b)
            (
                io.wasi_io_streams_output_stream_write(host, 0, c, 120, 5, 88),
                dump("write after the other handle was dropped"),
            )
            io.wasi_io_streams_output_stream_drop(host, c)
            io.wasi_io_streams_input_stream_read(host, 0, a, 10, 96), dump("read")
            io.wasi_io_streams_input_stream_drop(host, a)
            lines.append(f"stderr {cli.wasi_cli_stderr_get_stderr(host)}")
            lines.append(f"stdout {bytes(stdout.data).hex()}")
        elif scenario == "fd":
            in_r, in_w = os.pipe()
            out_r, out_w = os.pipe()
            os.write(in_w, b"pipe!")
            os.close(in_w)
            host = Host([memory], stdin=cli.FdInput(in_r), stdout=cli.FdOutput(out_w), **common)
            a, b = cli.wasi_cli_stdin_get_stdin(host), cli.wasi_cli_stdout_get_stdout(host)
            lines.append(f"std handles {a} {b}")
            io.wasi_io_streams_input_stream_read(host, 0, a, 16, 0), dump("read")
            io.wasi_io_streams_input_stream_read(host, 0, a, 16, 16), dump("read at the end")
            io.wasi_io_streams_output_stream_blocking_write_and_flush(host, 0, b, 120, 5, 32), dump("write")
            os.close(out_w)
            lines.append(f"pipe {os.read(out_r, 16).hex()}")
            os.close(in_r)
            os.close(out_r)
        else:
            host = Host([memory], **common)
            if scenario == "exit_ok":
                cli.wasi_cli_exit_exit(host, 0)
            elif scenario == "exit_err":
                cli.wasi_cli_exit_exit(host, 1)
            else:
                cli.wasi_cli_exit_exit_with_code(host, 0x1FF)
    except Exit as exc:
        lines.append(f"EXIT {exc.code}")
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
    binary = tmp_path_factory.mktemp("p2cli") / "driver"
    subprocess.run(
        [CC, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-I", str(C_P2), str(DRIVER), "-o", str(binary)], check=True
    )
    return binary


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_c_and_python_agree(driver: Path, scenario: str) -> None:
    assert python_output(scenario) == c_output(scenario, driver)


@posix_only
def test_values() -> None:
    lines = python_output("main").splitlines()
    assert "stdout 68656c6c6f68656c6c6f" in lines  # two writes through two handles, the first one dropped in between
    arguments = bytes.fromhex(lines[2].split()[-1])
    assert arguments[:8] == (160).to_bytes(4, "little") + (2).to_bytes(4, "little")  # the list is at 160, 2 long
    assert arguments[160:168] == (176).to_bytes(4, "little") + (4).to_bytes(
        4, "little"
    )  # "prog" is the first string, after the list
    assert arguments[176:180] == b"prog"
    assert python_output("fd").splitlines()[-1] == "pipe 68656c6c6f"
    assert [python_output(s).strip() for s in ("exit_ok", "exit_err", "exit_code")] == ["EXIT 0", "EXIT 1", "EXIT 255"]


def test_default_streams_are_python_ones(capfd: pytest.CaptureFixture[str]) -> None:
    """With no stream given the guest writes to `sys.stdout` of the moment, after the text layer is flushed."""
    memory = bytearray(64)
    memory[10:12] = b"ok"
    host = Host([memory])
    handle = cli.wasi_cli_stdout_get_stdout(host)
    print("before", end="")
    io.wasi_io_streams_output_stream_blocking_write_and_flush(host, 0, handle, 10, 2, 0)
    assert capfd.readouterr().out == "beforeok"
