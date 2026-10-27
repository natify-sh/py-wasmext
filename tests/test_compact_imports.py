"""Compact imports (the import section in the forms 0x7F and 0x7E): read as the proposal says, written with ordinary imports for `wasm2c`, and built in every product and by `wasmimport`.

The encodings are those of the proposal (`proposals/compact-import-section/Overview.md`, the decoder of its interpreter and `test/core/compact-import-section/binary-compact-imports.wast`):
the number in front of the section counts entries (a group is one, and may have no imports); 0x7F is a module and then a name and a type (with its kind) for each import; 0x7E is a module,
one type (with its kind) and then a name for each import. WABT 1.0.42 reads 0x7E and the number differently, which is why `wasm2c` is given ordinary imports.
The module is a WASI command written byte by byte, because `wat2wasm` does not read the text form of the proposal yet.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from wasmext import Import, WasmError, parse
from wasmext._setuptools import product_filename  # pyright: ignore[reportPrivateUsage]
from wasmext._wasm import expand_compact_imports  # pyright: ignore[reportPrivateUsage]

WASI = "wasi_snapshot_preview1"
# the types of the module: 0 fd_write, 1 proc_exit, 2 _start, 3 args_sizes_get and environ_sizes_get
TYPES = bytes([4, 0x60, 4, 0x7F, 0x7F, 0x7F, 0x7F, 1, 0x7F, 0x60, 1, 0x7F, 0, 0x60, 0, 0, 0x60, 2, 0x7F, 0x7F, 1, 0x7F])
FD_WRITE, PROC_EXIT, ARGS, ENVIRON = ("fd_write", 0), ("proc_exit", 1), ("args_sizes_get", 3), ("environ_sizes_get", 3)


def _name(text: str) -> bytes:
    return bytes([len(text)]) + text.encode()


def _leb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _section(section_id: int, body: bytes) -> bytes:
    return bytes([section_id]) + _leb(len(body)) + body


def _func(item: tuple[str, int]) -> bytes:
    """The kind and type of a function import: `0x00 typeidx`."""
    return bytes([0, item[1]])


def _each(*items: tuple[str, int], empty: bytes = b"\0") -> bytes:
    """A group 0x7F: the module, an empty name, then the name and type of each."""
    return _name(WASI) + empty + bytes([0x7F, len(items)]) + b"".join(_name(n) + _func((n, t)) for n, t in items)


def _kind(type_index: int, *names: str) -> bytes:
    """A group 0x7E: the module, an empty name, one type, then the name of each."""
    return _name(WASI) + b"\0" + bytes([0x7E, 0, type_index, len(names)]) + b"".join(_name(n) for n in names)


def _plain(item: tuple[str, int]) -> bytes:
    return _name(WASI) + _name(item[0]) + _func(item)


# name -> (number in front, the entries, the functions imported); the twin without compact entries is `PLAIN[name]`
VARIANTS: dict[str, tuple[int, bytes, int]] = {
    "plain": (2, _plain(FD_WRITE) + _plain(PROC_EXIT), 2),
    "each": (1, _each(FD_WRITE, PROC_EXIT), 2),
    "kind": (2, _kind(0, "fd_write") + _kind(1, "proc_exit"), 2),
    "empty": (4, _each() + _plain(FD_WRITE) + _kind(0) + _each(PROC_EXIT), 2),  # groups with no imports are valid
    "overlong": (1, _each(FD_WRITE, PROC_EXIT, empty=b"\x80\x80\x80\x00"), 2),  # so is an empty name in more bytes
    "mixed": (3, _plain(FD_WRITE) + _kind(1, "proc_exit") + _kind(3, "args_sizes_get", "environ_sizes_get"), 4),
    "mixed_plain": (4, _plain(FD_WRITE) + _plain(PROC_EXIT) + _plain(ARGS) + _plain(ENVIRON), 4),
}
PLAIN = {name: ("mixed_plain" if name == "mixed" else "plain") for name in VARIANTS}


def _command(form: str) -> bytes:
    """A WASI command that writes `hello, wasi` and ends with `proc_exit(3)`, its imports in the given form."""
    count, entries, functions = VARIANTS[form]
    return _build(bytes([count]) + entries, functions)


def _build(imports: bytes, functions: int) -> bytes:
    """The command with the given body of the import section, which makes `functions` functions."""
    start = bytes([0]) + bytes(
        [0x41, 0, 0x41, 8, 0x36, 2, 0, 0x41, 4, 0x41, 12, 0x36, 2, 0, 0x41, 1, 0x41, 0, 0x41, 1, 0x41, 24]
    )
    start += bytes(
        [0x10, 0, 0x1A, 0x41, 3, 0x10, 1, 0x0B]
    )  # fd_write and proc_exit are the first two imports in every form
    exports = bytes([2]) + _name("memory") + bytes([2, 0]) + _name("_start") + bytes([0, functions])
    return (
        b"\0asm\1\0\0\0"
        + _section(1, TYPES)
        + _section(2, imports)
        + _section(3, bytes([1, 2]))
        + _section(5, bytes([1, 0, 1]))
        + _section(7, exports)
        + _section(10, bytes([1, len(start)]) + start)
        + _section(11, bytes([1, 0, 0x41, 8, 0x0B, 12]) + b"hello, wasi\n")
    )


@pytest.mark.parametrize("form", ["each", "kind", "empty", "overlong", "mixed"])
def test_every_form_has_the_imports_of_its_ordinary_twin(form: str) -> None:
    twin = parse(_command(PLAIN[form]))
    got = parse(_command(form))
    assert got.imports == twin.imports
    assert [(i.module, i.name, i.kind) for i in got.imports][:2] == [
        (WASI, "fd_write", "func"),
        (WASI, "proc_exit", "func"),
    ]


def test_a_group_of_the_second_form_shares_its_type() -> None:
    imports: list[Import] = parse(_command("mixed")).imports
    assert [i.name for i in imports] == ["fd_write", "proc_exit", "args_sizes_get", "environ_sizes_get"]
    assert imports[2].type is imports[3].type  # one type for the group


@pytest.mark.parametrize("form", ["each", "kind", "empty", "overlong", "mixed"])
def test_wasm2c_is_given_the_twin_byte_for_byte(form: str) -> None:
    data = _command(form)
    assert expand_compact_imports(data, parse(data)) == _command(PLAIN[form])


def test_a_module_with_ordinary_imports_is_given_as_it_is() -> None:
    data = _command("plain")
    assert expand_compact_imports(data, parse(data)) is data


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (bytes([1]) + _name(WASI) + _name("b") + bytes([0x7F, 0]), "unknown import kind 127"),  # a name before the mark
        (bytes([1]) + _name(WASI) + _name("b") + bytes([0x7E, 0, 0, 0]), "unknown import kind 126"),
        (
            bytes([1]) + _name(WASI) + b"\0" + bytes([0xFF, 0x80, 0x80, 0]) + bytes([0]),
            "unknown import kind 255",
        ),  # the mark is not LEB128
        (
            bytes([1]) + _name(WASI) + b"\0" + bytes([0x7F, 2]) + _name("fd_write") + bytes([0, 0]),
            "unexpected end of data",
        ),  # one item of two
        (bytes([1]) + _name(WASI) + b"\0" + bytes([0x7E, 0, 0, 2]) + _name("fd_write"), "unexpected end of data"),
        (bytes([3]) + _each(FD_WRITE) + _each(PROC_EXIT), "unexpected end of data"),  # 3 entries announced, 2 there
        (bytes([1]) + _each(FD_WRITE) + _each(PROC_EXIT), "unread bytes"),  # 1 announced, 2 there
    ],
)
def test_what_the_proposal_calls_malformed_is_refused(body: bytes, message: str) -> None:
    with pytest.raises(WasmError, match=message):
        parse(_build(body, 2))


def test_an_empty_name_without_a_mark_is_an_ordinary_import() -> None:
    body = bytes([1]) + _name(WASI) + b"\0" + _func(FD_WRITE)  # "" "" (func (type 0))
    assert [(i.module, i.name) for i in parse(_build(body, 1)).imports] == [(WASI, "")]


def _wasmext(cwd: Path, wabt: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "WASMEXT_WABT": str(wabt)}
    return subprocess.run(
        [sys.executable, "-m", "wasmext", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


def _module(tmp_path: Path, form: str) -> None:
    (tmp_path / "m.wasm").write_bytes(_command(form))


def _run_start(cwd: Path, wabt: Path, code: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "WASMEXT_WABT": str(wabt), "WASMIMPORT_BUILD_DIR": str(cwd / "cache")}
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=600
    )


START = "try:\n    m.Instance(m.Store())._start()\nexcept m.WasiExit as exc:\n    print('exit', exc.code)\n"


@pytest.mark.parametrize("form", ["each", "kind", "empty", "overlong", "mixed"])
def test_a_python_extension_runs(tmp_path: Path, wabt: Path, form: str) -> None:
    _module(tmp_path, form)
    done = _wasmext(tmp_path, wabt, "natify", "-i", "-q", "--host", "wasm32-wasip1", "m.wasm")
    assert done.returncode == 0, done.stderr[-800:]
    ran = _run_start(tmp_path, wabt, "import m\n" + START)
    assert ran.returncode == 0, ran.stderr[-800:]
    assert ran.stdout == "hello, wasi\nexit 3\n"


@pytest.mark.parametrize("form", ["each", "mixed"])
def test_a_shared_library_is_built(tmp_path: Path, wabt: Path, form: str) -> None:
    _module(tmp_path, form)
    done = _wasmext(tmp_path, wabt, "natify", "-i", "-q", "--host", "wasm32-wasip1", "--shared", "m.wasm")
    assert done.returncode == 0, done.stderr[-800:]
    assert (tmp_path / product_filename("m", "shared")).is_file()
    assert (tmp_path / "m_ctypes.py").is_file()


@pytest.mark.parametrize("form", ["each", "mixed"])
def test_a_program_runs(tmp_path: Path, wabt: Path, form: str) -> None:
    _module(tmp_path, form)
    done = _wasmext(tmp_path, wabt, "natify", "-i", "-q", "--host", "wasm32-wasip1", "--exe", "m.wasm")
    assert done.returncode == 0, done.stderr[-800:]
    ran = subprocess.run([tmp_path / product_filename("m", "exe")], capture_output=True, check=False)
    assert ran.stdout == b"hello, wasi\n" and ran.returncode == 3


@pytest.mark.parametrize("form", ["each", "mixed"])
def test_wasmimport_imports_it(tmp_path: Path, wabt: Path, form: str) -> None:
    _module(tmp_path, form)
    ran = _run_start(tmp_path, wabt, 'import wasmimport\nwasmimport.install(host="wasm32-wasip1")\nimport m\n' + START)
    assert ran.returncode == 0, ran.stderr[-800:]
    assert ran.stdout == "hello, wasi\nexit 3\n"


def test_the_c_is_that_of_the_ordinary_twin(tmp_path: Path, wabt: Path) -> None:
    for form in ("mixed", "mixed_plain"):
        folder = tmp_path / form
        folder.mkdir()
        _module(folder, form)
        done = _wasmext(folder, wabt, "natify", "-q", "m.wasm")
        assert done.returncode == 0, done.stderr[-800:]
    [made] = [p for p in (tmp_path / "mixed" / "build" / "wasmext").iterdir() if p.is_dir()]
    twin = tmp_path / "mixed_plain" / "build" / "wasmext" / made.name

    def code(folder: Path) -> list[str]:  # the C without the head that says which .wasm it was made from
        lines = (folder / "m_w2c.c").read_text("utf-8").splitlines()
        return [line for line in lines if not line.startswith("#define WASMEXT_GENERATED")]

    assert code(made) == code(twin)
