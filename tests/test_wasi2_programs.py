"""Programs of WASI 0.2 as a toolchain makes them, not written by hand: a C program (wasi-sdk, `tests/data/wasi2_real/prog_c.wasm`, the core module of the component:
`clang --target=wasm32-wasip2 -O1 prog.c`, then `wasm-tools component unbundle --threshold 0`) and a Rust program (`rustc --target wasm32-wasip2`, built here when the
toolchain is there). Each runs as a program, as an extension and through the wrapper for ctypes: arguments, environment, stdin, files, directories, the clock."""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from wasmext._exe import build  # pyright: ignore[reportPrivateUsage]

from .conftest import DATA

Builder = Callable[..., ModuleType]
P2 = "wasm32-wasip2"
RUN = "wasi:cli/run@0.2.12#run"  # the version of the world is the toolchain's: wasi-sdk 34 says 0.2.12
RUN_RUST = "wasi:cli/run@0.2.0#run"
C_MODULE = DATA / "wasi2_real" / "prog_c.wasm"
RUST_SOURCE = DATA / "wasi2_real" / "prog.rs"


def rust_module(tmp_path: Path) -> Path:
    """The core module of the Rust program, or a skip when the toolchain is not there."""
    rustc = shutil.which("rustc")
    wasm_tools = shutil.which("wasm-tools")
    if rustc is None or wasm_tools is None:
        pytest.skip("rustc and wasm-tools are needed")
    component = tmp_path / "prog_rs.component.wasm"
    done = subprocess.run(
        [rustc, "--target", "wasm32-wasip2", "-O", "-o", str(component), str(RUST_SOURCE)],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip(f"rustc cannot build for wasm32-wasip2: {done.stderr.strip().splitlines()[-1:]}")
    modules = tmp_path / "modules"
    modules.mkdir()
    subprocess.run(
        [
            wasm_tools,
            "component",
            "unbundle",
            str(component),
            "--module-dir",
            str(modules),
            "-o",
            str(tmp_path / "stub.wasm"),
            "--threshold",
            "0",
        ],
        check=True,
        capture_output=True,
    )
    return modules / "unbundled-module0.wasm"


def program(tmp_path: Path, wasm: Path) -> Path:
    return build(wasm, tmp_path / ("prog.exe" if sys.platform == "win32" else "prog"), optimize=False, host=P2)


def test_a_c_program_runs_as_a_program(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    ran = subprocess.run(
        [program(tmp_path, C_MODULE), "--env", "GREETING=hi", "--dir", f"{data}::/data", "prog", "extra"],
        input=b"hello stdin\n",
        capture_output=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    lines = ran.stdout.decode().splitlines()
    assert lines[0] == "argc=2 argv0=prog"
    assert "arg 1=extra" in lines
    assert "GREETING=hi" in lines
    assert "stdin line: hello stdin" in lines
    assert "read back: written by wasip2" in lines
    assert "entries=2" in lines and "clock ok=1" in lines
    assert ran.stderr.decode().strip() == "to stderr"
    assert (data / "out.txt").read_text(encoding="utf-8") == "written by wasip2\n"
    assert (data / "sub").is_dir()


def test_a_c_program_runs_in_python(build_front_end: Builder, tmp_path: Path) -> None:
    mod = build_front_end(C_MODULE, "wasi2_prog_c", host=P2)
    data = tmp_path / "data"
    data.mkdir()
    out: list[bytes] = []
    err: list[bytes] = []
    wasi: dict[str, Any] = {
        "args": ["prog", "extra"],
        "env": {"GREETING": "hi"},
        "stdin": io.BytesIO(b"hello stdin\n"),
        "stdout": out.append,
        "stderr": err.append,
        "preopens": {"/data": data},
    }
    assert getattr(mod.Instance(wasi=wasi), RUN)() == 0
    lines = b"".join(out).decode().splitlines()
    assert lines[0] == "argc=2 argv0=prog" and "GREETING=hi" in lines and "stdin line: hello stdin" in lines
    assert "read back: written by wasip2" in lines and "entries=2" in lines
    assert b"".join(err) == b"to stderr\n"
    assert (data / "out.txt").read_text(encoding="utf-8") == "written by wasip2\n"


def test_a_rust_program_runs_as_a_program(tmp_path: Path) -> None:
    wasm = rust_module(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    ran = subprocess.run(
        [program(tmp_path, wasm), "--env", "GREETING=hi", "--dir", f"{data}::/data", "prog", "b"],
        input=b"first\nsecond\nthird\n",
        capture_output=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    lines = ran.stdout.decode().splitlines()
    assert lines[0] == 'args=["prog", "b"]'
    assert lines[1] == 'GREETING=Ok("hi")'
    assert "stdin: first" in lines and "rest bytes=13" in lines
    assert "lines=1000" in lines and 'dir=["deep", "moved.txt"]' in lines
    assert "missing is err=true" in lines and "slept>=20ms=true" in lines
    assert ran.stderr.decode().strip() == "to stderr"


def test_a_rust_program_runs_in_python(build_front_end: Builder, tmp_path: Path) -> None:
    wasm = rust_module(tmp_path)
    mod = build_front_end(wasm, "wasi2_prog_rs", host=P2)
    data = tmp_path / "data"
    data.mkdir()
    out: list[bytes] = []
    wasi: dict[str, Any] = {
        "args": ["prog", "b"],
        "env": {"GREETING": "hi"},
        "stdin": io.BytesIO(b"first\nsecond\nthird\n"),
        "stdout": out.append,
        "stderr": None,
        "preopens": {"/data": data},
    }
    inst = mod.Instance(wasi=wasi)
    with pytest.raises(mod.WasiExit) as ended:  # a Rust program ends with process::exit
        getattr(inst, RUN_RUST)()
    assert ended.value.code == 0  # std::process::exit(0) is wasi:cli/exit(ok)
    lines = b"".join(out).decode().splitlines()
    assert "lines=1000" in lines and 'dir=["deep", "moved.txt"]' in lines and "stdin: first" in lines


NET_MODULE = (
    DATA / "wasi2_real" / "net_c.wasm"
)  # net.c: a TCP server and client, UDP, and a name lookup, all on the loopback
NET_OUTPUT = ["tcp port>0=1", "server got ping", "client got pong", "udp got dgram", "localhost=127.0.0.1"]


def test_a_program_that_serves_tcp_sends_udp_and_looks_up_a_name_needs_the_network_allowed(tmp_path: Path) -> None:
    net = program(tmp_path, NET_MODULE)
    refused = subprocess.run([net], capture_output=True, check=False)
    assert refused.returncode != 0 and b"Permission denied" in refused.stderr
    allowed = subprocess.run([net, "--allow-net"], capture_output=True, check=False)
    assert allowed.returncode == 0, allowed.stderr
    assert allowed.stdout.decode().splitlines() == NET_OUTPUT


def test_the_network_policies_see_each_use_in_python(build_front_end: Builder) -> None:
    mod = build_front_end(NET_MODULE, "wasi2_net_c", host=P2)
    seen: list[tuple[str, str]] = []

    def sockets(ip: str, port: int, use: str) -> bool:
        seen.append((ip, use))
        return True

    out: list[bytes] = []
    assert getattr(mod.Instance(wasi={"stdout": out.append, "sockets": sockets, "dns": True}), RUN)() == 0
    assert b"".join(out).decode().splitlines() == NET_OUTPUT
    uses = {use for _ip, use in seen}
    assert {
        "tcp-bind",
        "tcp-connect",
        "udp-bind",
    } <= uses  # and the UDP send, whichever of the two ways the library takes
    assert {ip for ip, _use in seen} == {
        "127.0.0.1",
        "0.0.0.0",
    }  # 0.0.0.0: the socket that sends without a bind is bound by the libc first


def test_udp_can_be_refused_while_tcp_is_allowed(build_front_end: Builder) -> None:
    mod = build_front_end(NET_MODULE, "wasi2_net_c", host=P2)
    out: list[bytes] = []
    err: list[bytes] = []
    inst = mod.Instance(wasi={"stdout": out.append, "stderr": err.append, "sockets": True, "udp": False, "dns": True})
    assert getattr(inst, RUN)() == 1  # main returned 1: the bind of the UDP socket failed
    assert b"".join(out).decode().splitlines() == NET_OUTPUT[:3]
    assert b"udp bind" in b"".join(err)


def test_names_are_not_resolved_unless_dns_is_allowed(build_front_end: Builder) -> None:
    mod = build_front_end(NET_MODULE, "wasi2_net_c", host=P2)
    out: list[bytes] = []
    assert (
        getattr(mod.Instance(wasi={"stdout": out.append, "sockets": True}), RUN)() == 1
    )  # the lookup is refused: main returned 2, the err of run
    assert b"".join(out).decode().splitlines()[:4] == NET_OUTPUT[:4]
    assert b"getaddrinfo" in b"".join(out)


HTTP_MODULE = (
    DATA / "wasi2_real" / "httpc_rs.wasm"
)  # httpc/main.rs: GET http://<authority><path> over wasi:http, prints the status and the body
SERVER = (
    "import http.server, sys\n"
    "class H(http.server.BaseHTTPRequestHandler):\n"
    "    def do_GET(self):\n"
    "        body = b'served ' + self.path.encode()\n"
    "        self.send_response(200)\n"
    "        self.send_header('Content-Length', str(len(body)))\n"
    "        self.end_headers()\n"
    "        self.wfile.write(body)\n"
    "    def log_message(self, *a): pass\n"
    "s = http.server.HTTPServer(('127.0.0.1', 0), H)\n"
    "print(s.server_address[1], flush=True)\n"
    "s.serve_forever()\n"
)


@pytest.fixture
def http_port() -> Any:
    """A web server on a free port of 127.0.0.1, in a process of its own (the client in these tests may hold the GIL of this one)."""
    server = subprocess.Popen([sys.executable, "-c", SERVER], stdout=subprocess.PIPE)
    assert server.stdout is not None
    port = int(server.stdout.readline())
    yield port
    server.kill()
    server.wait()


def test_a_program_gets_a_page_over_wasi_http_when_the_network_is_allowed(tmp_path: Path, http_port: int) -> None:
    client = program(tmp_path, HTTP_MODULE)
    refused = subprocess.run([client, "x", f"127.0.0.1:{http_port}", "/a"], capture_output=True, check=False)
    assert refused.returncode != 0 and b"HttpRequestDenied" in refused.stdout
    served = subprocess.run(
        [client, "--allow-net", "x", f"127.0.0.1:{http_port}", "/a?b=1"], capture_output=True, check=False
    )
    assert served.returncode == 0, served.stdout
    assert served.stdout.decode().splitlines() == ["status=200", "body=served /a?b=1"]


def test_the_policy_of_http_sees_the_scheme_and_the_authority_in_python(
    build_front_end: Builder, http_port: int
) -> None:
    mod = build_front_end(HTTP_MODULE, "wasi2_httpc", host=P2)
    seen: list[tuple[str, str]] = []

    def policy(scheme: str, authority: str) -> bool:
        seen.append((scheme, authority))
        return True

    out: list[bytes] = []
    # the transport of the host is a socket, and it is the policy of http that decides (the one of sockets is not asked)
    inst = mod.Instance(wasi={"args": ["x", f"127.0.0.1:{http_port}", "/p"], "stdout": out.append, "http": policy})
    getattr(inst, RUN_RUST)()
    assert seen == [("http", f"127.0.0.1:{http_port}")]
    assert b"".join(out).decode().splitlines() == ["status=200", "body=served /p"]


FS_MODULE = (
    DATA / "wasi2_real" / "fs2_c.wasm"
)  # fs2.c: the rest of the files: positions, truncate, links, times, errors
FS_OUTPUT = [
    "pread=0123AB6789",
    "tail=789",
    "size=4",
    "readlink=f.bin",
    "nlink=2",
    "mtime=1500000000",
    "rmdir non-empty fails=1",
    "open missing=-1 enoent=1",
    "escape refused=1",
]


@pytest.mark.skipif(sys.platform == "win32", reason="links and times as POSIX has them")
def test_positions_links_times_and_errors_of_files_as_a_program(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    ran = subprocess.run([program(tmp_path, FS_MODULE), "--dir", f"{data}::/data"], capture_output=True, check=False)
    assert ran.returncode == 0, ran.stdout
    assert ran.stdout.decode().splitlines() == FS_OUTPUT
    assert list(data.iterdir()) == []  # the program removed all it made


@pytest.mark.skipif(sys.platform == "win32", reason="links and times as POSIX has them")
def test_positions_links_times_and_errors_of_files_in_python(build_front_end: Builder, tmp_path: Path) -> None:
    mod = build_front_end(FS_MODULE, "wasi2_fs2_c", host=P2)
    data = tmp_path / "data"
    data.mkdir()
    out: list[bytes] = []
    assert getattr(mod.Instance(wasi={"stdout": out.append, "preopens": {"/data": data}}), RUN)() == 0
    assert b"".join(out).decode().splitlines() == FS_OUTPUT
