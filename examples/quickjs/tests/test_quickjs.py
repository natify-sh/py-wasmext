from __future__ import annotations

from pathlib import Path

import qjswasm


def test_a_snippet_prints() -> None:
    result = qjswasm.run(
        ["-e", "console.log(2 ** 10, typeof BigInt, [1, 2, 3].map(x => x * 2), JSON.stringify({a: 1}))"]
    )
    assert result == qjswasm.Result(0, b'1024 function 2,4,6 {"a":1}\n', b"")


def test_a_script_is_read_from_the_directory_it_was_given(tmp_path: Path) -> None:
    (tmp_path / "hello.js").write_text('console.log("hello from quickjs", 1 + 1)\n', encoding="utf-8")
    result = qjswasm.run(["hello.js"], root=tmp_path)
    assert (result.code, result.stdout) == (0, b"hello from quickjs 2\n")


def test_a_module_can_import_another_from_the_directory(tmp_path: Path) -> None:
    (tmp_path / "lib.mjs").write_text("export const twice = (x) => x * 2;\n", encoding="utf-8")
    (tmp_path / "main.mjs").write_text(
        'import { twice } from "./lib.mjs";\nconsole.log(twice(21));\n', encoding="utf-8"
    )
    result = qjswasm.run(["main.mjs"], root=tmp_path)
    assert (result.code, result.stdout) == (0, b"42\n")


def test_stdin_is_read_by_the_script() -> None:
    result = qjswasm.run(["--std", "-e", "console.log(std.in.readAsString().toUpperCase())"], stdin=b"abc\n")
    assert result.stdout == b"ABC\n\n"


def test_an_error_of_the_script_is_a_message_and_a_code() -> None:
    result = qjswasm.run(["-e", "throw new Error('boom')"])
    assert result.code == 1 and result.stdout == b""
    assert result.stderr.startswith(b"Error: boom")


def test_files_are_written_read_and_removed(tmp_path: Path) -> None:
    script = """
import * as std from "qjs:std";
import * as os from "qjs:os";
const f = std.open("out.txt", "w");
f.puts("one\\n");
f.close();
console.log(std.loadFile("out.txt").trim());
console.log(os.remove("out.txt"));
console.log(std.loadFile("out.txt"));
"""
    (tmp_path / "w.mjs").write_text(script, encoding="utf-8")
    result = qjswasm.run(["w.mjs"], root=tmp_path)
    assert result.code == 0
    assert result.stdout.splitlines() == [b"one", b"0", b"null"]
    assert not (tmp_path / "out.txt").exists()


def test_a_script_cannot_leave_its_directory(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    world = tmp_path / "world"
    world.mkdir()
    result = qjswasm.run(["--std", "-e", 'console.log(std.loadFile("../secret.txt"))'], root=world)
    assert result.stdout == b"null\n"  # not the content


def test_a_program_that_sees_no_files_cannot_open_any() -> None:
    result = qjswasm.run(["--std", "-e", 'console.log(std.loadFile("anything"))'])
    assert result.stdout == b"null\n"


def test_runs_are_independent() -> None:
    first = qjswasm.run(["-e", "globalThis.x = 1; console.log(x)"])
    second = qjswasm.run(["-e", "console.log(typeof x)"])
    assert (first.stdout, second.stdout) == (b"1\n", b"undefined\n")
