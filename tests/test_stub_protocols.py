"""The stub of a module of WASI 0.1 types its imports with the Protocols of fusedwasi (named parameters), and each is accepted with or without the Caller first."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from wasmext._gen import generate  # pyright: ignore[reportPrivateUsage]
from wasmext._wasm import parse  # pyright: ignore[reportPrivateUsage]

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def stub(wabt: Path, tmp_path_factory: pytest.TempPathFactory) -> str:
    wasm = tmp_path_factory.mktemp("wasm") / "wasi_probe.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "wasi_probe.wat", "-o", wasm], check=True)
    return generate(parse(wasm.read_bytes()), "wasi_probe", host="wasm32-wasip1").stub


def test_the_imports_of_wasi_have_protocols_with_the_names_of_the_parameters(stub: str) -> None:
    assert "class FdWrite(Protocol):" in stub and "class FdWriteWithCaller(Protocol):" in stub
    assert "def __call__(self, fd: int, iovs: int, iovs_len: int, retptr: int, /) -> int: ..." in stub
    assert "def __call__(self, caller: Caller, fd: int, iovs: int, iovs_len: int, retptr: int, /) -> int: ..." in stub
    assert "'fd_write': NotRequired[FdWrite | FdWriteWithCaller | None]" in stub  # what the caller gives
    assert "'fd_write': FdWrite," in stub  # the original of the host takes no Caller
    assert "Callable[[int, int, int, int], int]" not in stub
    compile(stub, "wasi_probe.pyi", "exec")


def test_the_wrapper_for_ctypes_has_the_same_stub(stub: str, build_ctypes: Callable[..., ModuleType]) -> None:
    mod = build_ctypes(DATA / "wasi_probe.wat", "wasi_probe", host="wasm32-wasip1")
    assert Path(str(mod.__file__)).with_suffix(".pyi").read_text(encoding="utf-8") == stub


def test_the_protocols_do_not_import_fusedwasi(stub: str) -> None:
    assert "fusedwasi" not in stub.replace("(from fusedwasi)", "")


@pytest.mark.skipif(shutil.which("pyright") is None, reason="pyright is not installed")
def test_pyright_accepts_other_names_and_the_caller_and_rejects_the_wrong_arity(stub: str, tmp_path: Path) -> None:
    (tmp_path / "wasi_probe.pyi").write_text(stub, encoding="utf-8")
    (tmp_path / "good.py").write_text(
        """import wasi_probe

WASI = "wasi_snapshot_preview1"


def with_other_names(a: int, b: int, c: int, d: int) -> int:
    return 0


def with_the_caller(caller: wasi_probe.Caller, a: int, b: int, c: int, d: int) -> int:
    return int(caller.memory is None)


store = wasi_probe.Store()
wasi_probe.Instance(store, imports={WASI: {"fd_write": with_other_names}})
wasi_probe.Instance(store, imports={WASI: {"fd_write": with_the_caller}})
""",
        encoding="utf-8",
    )
    (tmp_path / "bad.py").write_text(
        """import wasi_probe


def too_few(a: int, b: int) -> int:
    return 0


wasi_probe.Instance(wasi_probe.Store(), imports={"wasi_snapshot_preview1": {"fd_write": too_few}})
""",
        encoding="utf-8",
    )
    (tmp_path / "pyrightconfig.json").write_text(
        '{"typeCheckingMode": "strict", "pythonVersion": "3.11"}', encoding="utf-8"
    )

    def run(name: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pyright", name], cwd=tmp_path, capture_output=True, text=True, check=False
        )

    good, bad = run("good.py"), run("bad.py")
    assert good.returncode == 0, good.stdout[-1500:]
    assert bad.returncode != 0 and "reportArgumentType" in bad.stdout and "(a: int, b: int) -> int" in bad.stdout, (
        bad.stdout[-1500:]
    )


def test_the_imports_of_wasi_p2_have_protocols_too() -> None:
    hello = Path(__file__).parent.parent / "examples" / "wasi2_unbundled" / "src" / "wasi2demo" / "_hello.wasm"
    stub = generate(parse(hello.read_bytes()), "m", host="wasm32-wasip2").stub
    assert "class CliStdoutGetStdout(Protocol):" in stub and "class CliStdoutGetStdoutWithCaller(Protocol):" in stub
    assert "'get-stdout': NotRequired[CliStdoutGetStdout | CliStdoutGetStdoutWithCaller | None]" in stub
    assert "Callable[[], int]" not in stub  # no import is typed by arity alone
    assert "fusedwasi" not in stub.replace("(from fusedwasi)", "")
    compile(stub, "m.pyi", "exec")
