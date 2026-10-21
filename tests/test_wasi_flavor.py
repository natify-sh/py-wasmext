"""`wasi_flavor` tells what kind of WASI file some bytes are, and `inspect`, `natify` and `parse` say so instead of failing blind."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from wasmext import WasmError, parse, wasi_flavor

HEADER = b"\0asm\1\0\0\0"


def _name(text: str) -> bytes:
    return bytes([len(text)]) + text.encode()


def _section(section_id: int, body: bytes) -> bytes:
    return bytes([section_id, len(body)]) + body


def _module(*, imports: tuple[str, ...] = (), exports: tuple[str, ...] = (), custom: tuple[str, ...] = ()) -> bytes:
    """A core module whose imports are functions `() -> ()` of the given module names, with the given exports and custom sections."""
    out = HEADER
    if imports or exports:
        out += _section(1, bytes([1, 0x60, 0, 0]))
    if imports:
        out += _section(2, bytes([len(imports)]) + b"".join(_name(m) + _name("f") + bytes([0, 0]) for m in imports))
    if exports:
        out += _section(3, bytes([len(exports)]) + bytes([0]) * len(exports))
        out += _section(
            7, bytes([len(exports)]) + b"".join(_name(e) + bytes([0, len(imports) + i]) for i, e in enumerate(exports))
        )
        out += _section(10, bytes([len(exports)]) + bytes([2, 0, 0x0B]) * len(exports))
    for c in custom:
        out += _section(0, _name(c) + b"x")
    return out


COMPONENT = b"\0asm\x0d\0\1\0"


@pytest.mark.parametrize(
    ("data", "flavor"),
    [
        (_module(), "none"),
        (_module(imports=("env",)), "none"),
        (_module(imports=("wasi_snapshot_preview1",)), "core-0.1"),
        (_module(imports=("wasi_unstable",)), "core-0.1"),
        (_module(imports=("wasi:cli/environment@0.2.12",)), "core-0.2"),
        (_module(imports=("wasi:cli/environment@0.3.0-rc-2026-01-06",)), "core-0.3"),
        (_module(imports=("wasi:io/streams@0.2.3", "wasi:clocks/wall-clock@0.3.0")), "core-0.3"),  # the newest wins
        (_module(imports=("wasi_snapshot_preview1", "wasi:io/streams@0.2.3")), "core-0.2"),
        (
            _module(imports=("env",), exports=("wasi:cli/run@0.2.12#run",)),
            "core-0.2",
        ),  # the imports say nothing, the export does
        (_module(imports=("wasi:cli/environment@0.2.12",), custom=("meld.fusion",)), "fused"),
        (_module(custom=("name",)), "none"),
        (COMPONENT + b"\1\2", "component"),
        (b"not wasm", "unknown"),
        (HEADER[:4] + b"\2\0\0\0", "unknown"),
        (b"", "unknown"),
    ],
)
def test_wasi_flavor_is_told_from_the_bytes(data: bytes, flavor: str) -> None:
    assert wasi_flavor(data) == flavor


def test_a_component_is_refused_with_what_to_do() -> None:
    with pytest.raises(WasmError, match=r"component.*wasm-tools component unbundle.*meld fuse"):
        parse(COMPONENT)


def test_another_version_is_still_just_unsupported() -> None:
    with pytest.raises(WasmError, match="unsupported WebAssembly binary version 02000000"):
        parse(HEADER[:4] + b"\2\0\0\0")


def test_the_custom_sections_are_listed() -> None:
    assert parse(_module(custom=("name", "meld.x"))).custom == ["name", "meld.x"]


def _run(tmp_path: Path, command: str, data: bytes, *args: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "m.wasm").write_bytes(data)
    return subprocess.run(
        [sys.executable, "-m", "wasmext", command, *args, "m.wasm"],
        cwd=tmp_path,
        env={**os.environ},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_inspect_names_the_flavor(tmp_path: Path) -> None:
    done = _run(tmp_path, "inspect", _module(imports=("wasi:io/streams@0.2.3",)))
    assert "wasi: core-0.2: imports WASI 0.2" in done.stdout
    assert "wasi:" not in _run(tmp_path, "inspect", _module(imports=("env",))).stdout.replace("wasi:io", "")


def test_inspect_says_what_to_do_about_a_component(tmp_path: Path) -> None:
    done = _run(tmp_path, "inspect", COMPONENT)
    assert done.returncode == 1
    assert "wasm-tools component unbundle" in done.stdout


def test_natify_warns_about_wasi_it_does_not_provide(tmp_path: Path, wabt: Path) -> None:
    data = _module(imports=("wasi:io/streams@0.2.3",), exports=("f",))
    (tmp_path / "m.wasm").write_bytes(data)
    env = {**os.environ, "WASMEXT_WABT": str(wabt)}
    loud = subprocess.run(
        [sys.executable, "-m", "wasmext", "natify", "m.wasm"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert "imports WASI 0.2" in loud.stderr, loud.stderr[-500:]
    quiet = subprocess.run(
        [sys.executable, "-m", "wasmext", "natify", "-q", "m.wasm"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert "imports WASI 0.2" not in quiet.stderr
