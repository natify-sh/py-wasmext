"""WASI 0.2 built into the extension: `host = "wasm32-wasip2"` answers the imports of `wasi:*@0.2.x` with the C host of fusedwasi (p2/), configured by `wasi=`."""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from wasmext import GenError, generate, parse

from .conftest import DATA

Builder = Callable[..., ModuleType]
HELLO = Path(__file__).parent.parent / "examples" / "wasi2_unbundled" / "src" / "wasi2demo" / "_hello.wasm"
RUN = "wasi:cli/run@0.2.12#run"
P2 = "wasm32-wasip2"


def strings(inst: Any, at: int) -> list[str]:
    """A `list<string>` that the host wrote at `at` (pointer and length; each element a pointer and a length)."""
    mem = inst.memory
    ptr, count = struct.unpack("<II", bytes(mem[at : at + 8]))
    out: list[str] = []
    for i in range(count):
        p, n = struct.unpack("<II", bytes(mem[ptr + 8 * i : ptr + 8 * i + 8]))
        out.append(bytes(mem[p : p + n]).decode())
    return out


def test_a_command_of_wasi_p2_runs_with_no_host_of_python(build_front_end: Builder) -> None:
    mod = build_front_end(HELLO, "wasi2_hello", host=P2)
    assert mod.__host__ == P2
    out: list[bytes] = []
    inst = mod.Instance(wasi={"stdout": out.append})
    assert getattr(inst, RUN)() == 1  # the program returned 3, which is the err of the result of wasi:cli/run
    assert b"".join(out) == b"hello from wasip2\n"


def test_the_standard_output_goes_to_sys_stdout_when_it_is_not_given(
    build_front_end: Builder, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = build_front_end(HELLO, "wasi2_hello_sys", host=P2)
    getattr(mod.Instance(), RUN)()
    assert capsys.readouterr().out == "hello from wasip2\n"


def test_arguments_and_environment(build_front_end: Builder) -> None:
    mod = build_front_end(DATA / "wasi2_probe.wat", "wasi2_probe_args", host=P2)
    assert strings_of(mod.Instance(), "args") == ["wasi2_probe_args"]  # the name of the program, when there are none
    assert strings_of(mod.Instance(wasi={"args": ["prog", "-x", "é"]}), "args") == ["prog", "-x", "é"]
    assert strings_of(mod.Instance(wasi={"args": None}), "args") == []
    inst = mod.Instance(wasi={"env": {"A": "1", "B": "two words"}})
    inst.env(1000)
    mem = inst.memory
    ptr, count = struct.unpack("<II", bytes(mem[1000:1008]))
    pairs: list[tuple[str, str]] = []
    for i in range(count):
        a, an, b, bn = struct.unpack("<IIII", bytes(mem[ptr + 16 * i : ptr + 16 * i + 16]))
        pairs.append((bytes(mem[a : a + an]).decode(), bytes(mem[b : b + bn]).decode()))
    assert pairs == [("A", "1"), ("B", "two words")]


def strings_of(inst: Any, export: str) -> list[str]:
    getattr(inst, export)(1000)
    return strings(inst, 1000)


def test_exit_raises_the_exception_with_the_code(build_front_end: Builder) -> None:
    mod = build_front_end(DATA / "wasi2_probe.wat", "wasi2_probe_exit", host=P2)
    inst = mod.Instance()
    with pytest.raises(mod.WasiExit) as raised:
        inst.exit(1)  # the result of wasi:cli/exit is err (1)
    assert raised.value.code == 1
    inst.args(1000)  # the instance can be called again, as in Wasmtime: the end is what the call leaves
    with pytest.raises(mod.WasiExit):
        inst.exit(0)  # and it ends again


def test_the_clock_and_the_random_bytes_can_be_replaced(build_front_end: Builder) -> None:
    mod = build_front_end(DATA / "wasi2_probe.wat", "wasi2_probe_hooks", host=P2)
    seen: list[int] = []

    def clock(clock_id: int) -> int:
        seen.append(clock_id)
        return 123456789

    def random(n: int) -> bytes:
        return b"\x01" * n

    inst = mod.Instance(wasi={"clock": clock, "random": random})
    assert inst.now() == 123456789 and seen == [1]  # the monotonic clock is 1
    assert inst.rand() == 0x0101010101010101
    real = mod.Instance()
    assert real.now() > 0  # the clock of the system


def test_an_exception_of_a_hook_comes_out_of_the_call(build_front_end: Builder) -> None:
    mod = build_front_end(DATA / "wasi2_probe.wat", "wasi2_probe_raise", host=P2)

    def clock(clock_id: int) -> int:
        raise KeyError("no clock")

    with pytest.raises(KeyError, match="no clock"):
        mod.Instance(wasi={"clock": clock}).now()


def test_a_wrong_configuration_is_refused(build_front_end: Builder) -> None:
    mod = build_front_end(DATA / "wasi2_probe.wat", "wasi2_probe_config", host=P2)
    with pytest.raises(TypeError, match="unknown option"):
        mod.Instance(wasi={"nope": 1})
    with pytest.raises(TypeError, match="lists of strings"):
        mod.Instance(wasi={"args": "abc"})


def test_the_imports_of_wasi_p2_are_replaced_one_by_one(build_front_end: Builder) -> None:
    mod = build_front_end(DATA / "wasi2_probe.wat", "wasi2_probe_replace", host=P2)
    inst = mod.Instance({"wasi:clocks/monotonic-clock@0.2.12": {"now": lambda: 7}})
    assert inst.now() == 7
    nothing = mod.Instance(
        {"wasi:clocks/monotonic-clock@0.2.12": {"now": None}}
    )  # None is nothing given: a call with no errno traps
    with pytest.raises(mod.Trap, match="given as None"):
        nothing.now()


def test_the_stub_of_a_module_of_wasi_p2() -> None:
    module = parse((HELLO).read_bytes())
    stub = generate(module, "m", host=P2).stub
    assert "class WasiP2(TypedDict):" in stub and "Wasi = WasiP2" in stub and "wasi: Wasi | None = None" in stub
    assert (
        "_Imports_wasi_io_streams_0_2_12 = TypedDict(" in stub
        and "def __init__(self, imports: Imports | None = None" in stub
    )
    assert "class Host" not in stub  # the originals of the calls of 0.2 are not made yet
    compile(stub, "m.pyi", "exec")


def test_what_the_generator_refuses() -> None:
    wasm = DATA / "wasi2_probe.wat"
    assert wasm.is_file()
    with pytest.raises(GenError, match="does not export 'cabi_realloc'"):
        # the module of hello has it; one that does not is refused (a component's allocator)
        from .test_wasm_parser import I32, functype, leb, module, name, section, vec

        no_realloc = module(
            section(1, vec(functype([I32], []))),
            section(2, vec(name("wasi:cli/exit@0.2.12") + name("exit") + b"\x00" + leb(0))),
            section(5, vec(b"\x00" + leb(1))),
            section(7, vec(name("memory") + b"\x02" + leb(0))),
        )
        generate(parse(no_realloc), "m", host=P2)


class Fs:
    """The files of WASI 0.2 at the level of the canonical ABI, through `tests/data/wasi2_fs.wat`: the arguments laid out in the memory, the results read from it."""

    def __init__(self, mod: Any, **wasi: Any) -> None:
        self.inst = mod.Instance(wasi=wasi)
        self.mem = self.inst.memory

    def u32(self, at: int) -> int:
        return struct.unpack("<I", bytes(self.mem[at : at + 4]))[0]

    def text(self, at: int, text: str) -> tuple[int, int]:
        raw = text.encode()
        self.mem[at : at + len(raw)] = raw
        return at, len(raw)

    def directories(self) -> list[tuple[int, str]]:
        self.inst.dirs(1000)
        ptr, count = self.u32(1000), self.u32(1004)
        return [
            (
                self.u32(ptr + 12 * i),
                bytes(
                    self.mem[self.u32(ptr + 12 * i + 4) : self.u32(ptr + 12 * i + 4) + self.u32(ptr + 12 * i + 8)]
                ).decode(),
            )
            for i in range(count)
        ]

    def result(self, at: int) -> tuple[bool, int]:
        """A `result<handle, error-code>` at `at`: (ok, the handle or the code)."""
        return self.mem[at] == 0, self.u32(at + 4) if self.mem[at] == 0 else self.mem[at + 4]

    def open(self, directory: int, path: str, open_flags: int = 0, descriptor_flags: int = 1) -> tuple[bool, int]:
        ptr, n = self.text(2000, path)
        self.inst.open(directory, 1, ptr, n, open_flags, descriptor_flags, 3000)
        return self.result(3000)

    def read_file(self, directory: int, path: str) -> bytes:
        ok, fd = self.open(directory, path)
        assert ok, f"open {path}: error {fd}"
        self.inst.read_via(fd, 0, 3100)
        ok, stream = self.result(3100)
        assert ok
        self.inst.read(stream, 1000, 3200)
        assert self.mem[3200] == 0
        ptr, n = self.u32(3204), self.u32(3208)
        data = bytes(self.mem[ptr : ptr + n])
        self.inst.drop_input(stream)
        self.inst.drop_descriptor(fd)
        return data

    def write_file(self, directory: int, path: str, data: bytes) -> tuple[bool, int]:
        ok, fd = self.open(directory, path, open_flags=1 | 8, descriptor_flags=2)  # create, truncate
        if not ok:
            return ok, fd
        self.inst.write_via(fd, 0, 3100)
        ok, stream = self.result(3100)
        assert ok
        self.mem[4000 : 4000 + len(data)] = data
        self.inst.write(stream, 4000, len(data), 3300)
        assert self.mem[3300] == 0
        self.inst.drop_output(stream)
        self.inst.drop_descriptor(fd)
        return True, 0


def test_the_directories_a_program_is_given_are_listed_and_a_file_is_read(
    build_front_end: Builder, tmp_path: Path
) -> None:
    mod = build_front_end(DATA / "wasi2_fs.wat", "wasi2_fs_read", host=P2)
    (tmp_path / "hello.txt").write_bytes(b"hello, files\n")
    fs = Fs(mod, preopens={"/data": str(tmp_path)})
    [(root, name)] = fs.directories()
    assert name == "/data"
    assert fs.read_file(root, "hello.txt") == b"hello, files\n"
    ok, code = fs.open(root, "missing.txt")
    assert not ok and code == 20  # no-entry


def test_a_file_is_written_and_a_directory_made_and_removed(build_front_end: Builder, tmp_path: Path) -> None:
    mod = build_front_end(DATA / "wasi2_fs.wat", "wasi2_fs_write", host=P2)
    fs = Fs(mod, preopens={"/data": str(tmp_path)})
    [(root, _)] = fs.directories()
    assert fs.write_file(root, "out.txt", b"written by the guest") == (True, 0)
    assert (tmp_path / "out.txt").read_bytes() == b"written by the guest"
    ptr, n = fs.text(2000, "sub")
    fs.inst.mkdir(root, ptr, n, 3000)
    assert fs.mem[3000] == 0 and (tmp_path / "sub").is_dir()
    ptr, n = fs.text(2000, "out.txt")
    fs.inst.unlink(root, ptr, n, 3000)
    assert fs.mem[3000] == 0 and not (tmp_path / "out.txt").exists()


def test_a_directory_that_is_read_only_cannot_be_changed_and_a_path_cannot_leave_it(
    build_front_end: Builder, tmp_path: Path
) -> None:
    mod = build_front_end(DATA / "wasi2_fs.wat", "wasi2_fs_guard", host=P2)
    inside = tmp_path / "inside"
    inside.mkdir()
    (tmp_path / "secret.txt").write_text("outside")
    fs = Fs(mod, preopens={"/ro": str(inside)}, readonly=["/ro"])
    [(root, _)] = fs.directories()
    ok, _code = fs.write_file(root, "new.txt", b"x")
    assert not ok and not (inside / "new.txt").exists()
    ok, _code = fs.open(root, "../secret.txt")
    assert not ok  # a name cannot leave the directory it was given


def test_every_function_of_the_table_compiles_with_the_headers_the_glue_includes(tmp_path: Path) -> None:
    """All 201 functions of WASI 0.2 that fusedwasi has, taken by address in one file with the headers the glue includes (the sockets, http and files too), strictly:
    a module that imports only a few of them includes only a few headers, so this is where a typo in one of the others would show."""
    import platform
    import shutil
    import subprocess

    from wasmext._gen import _p2_headers  # pyright: ignore[reportPrivateUsage]
    from wasmext._natify import shared_header  # pyright: ignore[reportPrivateUsage]
    from wasmext._wasi_p2_table import FUNCS

    if platform.system() == "Windows":
        pytest.skip(
            "compiled by the examples of the files on Windows; the compiler of setuptools is not the one used here"
        )
    cc: str | None = shutil.which(os.environ.get("CC", "cc")) or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler of the cc kind")
    calls = {("wasi:test", name): name for name in FUNCS}
    for header in _p2_headers(calls):
        (tmp_path / header).write_bytes(shared_header(header).read_bytes())
    source = tmp_path / "all.c"
    includes = "".join(f'#include "{h}"\n' for h in _p2_headers(calls, include=True))
    table = ",\n".join(f"    (void *){name}" for name in sorted(FUNCS))
    source.write_text(
        f"#define _GNU_SOURCE\n{includes}\nvoid *const all_functions[] = {{\n{table}}};\n", encoding="utf-8"
    )
    done = subprocess.run(
        [cc, "-std=gnu11", "-Wall", "-Wextra", "-Wno-unused-parameter", "-Werror=incompatible-pointer-types",
         "-Werror=implicit-function-declaration", "-Werror=int-conversion", "-c", str(source), "-o", str(tmp_path / "all.o")],
        capture_output=True, text=True, check=False, cwd=tmp_path,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-2000:]


SOCK = HELLO.with_name("_sock.wasm")


def serve_pong(port: int) -> tuple[Any, list[bytes]]:
    """A TCP server on `port` of 127.0.0.1 that answers `pong` once; the listening socket and the bytes it got."""
    import socket
    import threading

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    for attempt in range(20):  # the port of an earlier connection may need a moment
        try:
            srv.bind(("127.0.0.1", port))
            break
        except OSError:
            if attempt == 19:
                srv.close()
                raise
            time.sleep(0.25)
    srv.listen(1)
    got: list[bytes] = []

    def run() -> None:
        conn, _ = srv.accept()
        with conn:
            got.append(conn.recv(16))
            conn.sendall(b"pong")

    threading.Thread(target=run, daemon=True).start()
    return srv, got


@pytest.fixture(scope="module")
def sock_module(build_front_end: Builder) -> ModuleType:
    return build_front_end(SOCK, "wasi2_sock", host=P2)


def test_the_network_is_refused_unless_the_caller_allows_it(sock_module: ModuleType) -> None:
    out: list[bytes] = []
    inst = sock_module.Instance(wasi={"stdout": out.append})
    assert getattr(inst, RUN)() == 1  # connect failed: sock.c returned 3
    assert b"reply" not in b"".join(out)


def test_a_policy_of_sockets_decides_each_use(sock_module: ModuleType) -> None:
    seen: list[tuple[str, int, str]] = []

    def policy(ip: str, port: int, use: str) -> bool:
        seen.append((ip, port, use))
        return port == 47123

    out: list[bytes] = []
    getattr(sock_module.Instance(wasi={"stdout": out.append, "sockets": policy}), RUN)()
    assert seen == [("127.0.0.1", 47123, "tcp-connect")]
    assert b"reply" not in b"".join(out)  # allowed, but nothing listens on 47123 (or not our server)


def test_a_program_talks_to_a_server_when_the_policy_allows_it(sock_module: ModuleType) -> None:
    try:
        srv, got = serve_pong(47123)  # sock.c connects to 127.0.0.1:47123
    except OSError as exc:
        pytest.skip(f"port 47123 is busy: {exc}")
    with srv:
        out: list[bytes] = []
        getattr(sock_module.Instance(wasi={"stdout": out.append, "sockets": True}), RUN)()
    assert b"".join(out) == b"reply: pong\n"
    assert got == [b"ping"]


def test_tcp_false_refuses_before_the_policy_is_asked(sock_module: ModuleType) -> None:
    def policy(ip: str, port: int, use: str) -> bool:
        raise AssertionError("not asked")

    out: list[bytes] = []
    inst = sock_module.Instance(wasi={"stdout": out.append, "sockets": policy, "tcp": False})
    getattr(inst, RUN)()
    assert b"reply" not in b"".join(out)


def test_an_exception_in_a_policy_comes_out_of_the_call(sock_module: ModuleType) -> None:
    def policy(ip: str, port: int, use: str) -> bool:
        raise KeyError("policy")

    with pytest.raises(KeyError):
        getattr(sock_module.Instance(wasi={"sockets": policy}), RUN)()


@pytest.mark.parametrize("key", ["sockets", "dns", "http", "tcp", "udp"])
def test_a_network_key_must_be_a_bool_or_a_callable(sock_module: ModuleType, key: str) -> None:
    with pytest.raises(TypeError, match=key):
        sock_module.Instance(wasi={key: "yes"})
    sock_module.Instance(wasi={key: None})


def exe(build_dir: Path, wasm: Path, name: str = "prog") -> Path:
    from wasmext._exe import build  # pyright: ignore[reportPrivateUsage]

    return build(wasm, build_dir / (name + (".exe" if sys.platform == "win32" else "")), optimize=False, host=P2)


def run_exe(program: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([program, *args], capture_output=True, check=False)


def test_a_command_of_wasi_p2_is_made_into_a_program(tmp_path: Path) -> None:
    ran = run_exe(exe(tmp_path, HELLO))
    assert ran.stdout == b"hello from wasip2\n"
    assert ran.returncode == 1  # main returned 3, the err of the result of wasi:cli/run


def test_the_options_give_a_program_of_wasi_p2_its_arguments_and_environment(wabt: Path, tmp_path: Path) -> None:
    wasm = tmp_path / "run.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "wasi2_run.wat", "-o", wasm], check=True)
    program = exe(tmp_path, wasm)
    assert run_exe(program).returncode == 1  # no arguments, no environment: err
    given = run_exe(program, "--env", "A=1", "--env", "B=2", "name", "x", "y")
    assert given.returncode == 0  # wasi:cli/exit(ok): the name of the program and two arguments, two variables


def test_a_program_of_wasi_p2_refuses_the_network_unless_it_is_told(tmp_path: Path) -> None:
    program = exe(tmp_path, SOCK)
    try:
        srv, got = serve_pong(47123)
    except OSError as exc:
        pytest.skip(f"port 47123 is busy: {exc}")
    with srv:
        refused = run_exe(program)
        assert b"reply" not in refused.stdout
        assert refused.returncode != 0
        allowed = run_exe(program, "--allow-net")
    assert allowed.stdout == b"reply: pong\n"
    assert allowed.returncode == 0
    assert got == [b"ping"]


def test_a_module_that_is_not_a_command_of_wasi_p2_is_not_made_into_a_program(wabt: Path, tmp_path: Path) -> None:
    from wasmext._exe import build  # pyright: ignore[reportPrivateUsage]

    wasm = tmp_path / "probe.wasm"
    subprocess.run([wabt / "bin" / "wat2wasm", DATA / "wasi2_probe.wat", "-o", wasm], check=True)
    with pytest.raises(GenError, match="does not export it"):  # no wasi:cli/run#run
        build(wasm, tmp_path / "x", optimize=False, host=P2)
    with pytest.raises(GenError, match="say host"):  # the host of a program is a WASI one
        build(HELLO, tmp_path / "y", optimize=False, host="wasm32")
