"""wasi:random of the host of WASI 0.2 (`wasmext.p2.wasi_p2_random`, `c/p2/wasi_p2_random.h`): the same scenario in Python and in C, the outputs are equal.

The sources are counters (the secure one starts at 0, the insecure one at 128), so the bytes are known.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import wasmext
from wasmext.p2 import wasi_p2_random as rnd
from wasmext.p2.wasi_p2_core import Host, Trap

C_P2 = Path(wasmext.__file__).parent / "c" / "p2"
DRIVER = Path(__file__).parent / "data" / "wasi_p2_random_driver.c"
CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")

SCENARIOS = ["main", "too_many", "failing"]


def counter(start: int):
    state = [start]

    def source(n: int) -> bytes:
        data = bytes((state[0] + i) & 0xFF for i in range(n))
        state[0] += n
        return data

    return source


def python_output(scenario: str) -> str:
    memory = bytearray(128)
    next_free = [64]

    def bump(comp: int, old_ptr: int, old_size: int, align: int, new_size: int) -> int:
        ptr = (next_free[0] + align - 1) // align * align
        next_free[0] = ptr + new_size
        return ptr

    def failing(n: int) -> bytes:
        raise Trap("the source of random bytes failed")

    host = Host([memory], realloc=bump, random_bytes=counter(0), insecure_random_bytes=counter(128))
    lines: list[str] = []

    def dump(what: str) -> None:
        lines.append(f"{what} {bytes(memory).hex()}")

    try:
        if scenario == "main":
            rnd.wasi_random_random_get_random_bytes(host, 0, 5, 0), dump("bytes")
            lines.append(f"u64 {rnd.wasi_random_random_get_random_u64(host)}")
            rnd.wasi_random_insecure_get_insecure_random_bytes(host, 0, 3, 8), dump("insecure bytes")
            lines.append(f"insecure u64 {rnd.wasi_random_insecure_get_insecure_random_u64(host)}")
            rnd.wasi_random_insecure_seed_insecure_seed(host, 0, 16), dump("seed")
            rnd.wasi_random_random_get_random_bytes(host, 0, 0, 32), dump("empty")
        elif scenario == "too_many":
            rnd.wasi_random_random_get_random_bytes(host, 0, 1 << 40, 0)
        elif scenario == "failing":
            host.random_bytes = failing
            rnd.wasi_random_random_get_random_u64(host)
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
    binary = tmp_path_factory.mktemp("p2random") / "driver"
    subprocess.run(
        [CC, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-I", str(C_P2), str(DRIVER), "-o", str(binary)], check=True
    )
    return binary


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_c_and_python_agree(driver: Path, scenario: str) -> None:
    assert python_output(scenario) == c_output(scenario, driver)


def test_values() -> None:
    lines = python_output("main").splitlines()
    first = bytes.fromhex(lines[0].split()[1])
    assert first[:8] == (64).to_bytes(4, "little") + (5).to_bytes(4, "little")  # the list is at 64, 5 long
    assert first[64:69] == bytes(range(5))  # the secure counter
    assert lines[1] == "u64 " + str(int.from_bytes(bytes(range(5, 13)), "little"))
    insecure = bytes.fromhex(lines[2].split()[-1])
    assert insecure[8:16] == (69).to_bytes(4, "little") + (3).to_bytes(4, "little")
    assert insecure[69:72] == bytes([128, 129, 130])  # the insecure counter is a source of its own
    assert lines[3] == "insecure u64 " + str(int.from_bytes(bytes(range(131, 139)), "little"))


@pytest.mark.parametrize("scenario", ["too_many", "failing"])
def test_traps(scenario: str) -> None:
    assert python_output(scenario).splitlines()[-1] == "TRAP"
