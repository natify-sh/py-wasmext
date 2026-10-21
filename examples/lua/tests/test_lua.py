from __future__ import annotations

from pathlib import Path

import luawasm


def test_a_snippet_prints() -> None:
    result = luawasm.run(["-e", "print(2^10, _VERSION)"])
    assert result == luawasm.Result(0, b"1024.0\tLua 5.4\n", b"")


def test_a_script_is_read_from_the_directory_it_was_given(tmp_path: Path) -> None:
    (tmp_path / "hello.lua").write_text('print("hello from lua", 1 + 1)\n', encoding="utf-8")
    result = luawasm.run(["hello.lua"], root=tmp_path)
    assert (result.code, result.stdout) == (0, b"hello from lua\t2\n")


def test_stdin_is_read_by_the_script() -> None:
    result = luawasm.run(["-e", "for l in io.lines() do print(l * 2) end"], stdin=b"1\n2\n3\n")
    assert result.stdout == b"2\n4\n6\n"


def test_files_are_written_appended_read_and_removed(tmp_path: Path) -> None:
    script = """
local f = assert(io.open("out.txt", "w"))
f:write("one\\n")
f:close()
f = assert(io.open("out.txt", "a"))
f:write("two\\n")
f:close()
for l in io.lines("out.txt") do print("read:", l) end
print(os.remove("out.txt"))
print(io.open("out.txt"))
"""
    (tmp_path / "w.lua").write_text(script, encoding="utf-8")
    result = luawasm.run(["w.lua"], root=tmp_path)
    assert result.code == 0
    assert result.stdout.splitlines() == [
        b"read:\tone",
        b"read:\ttwo",
        b"true",
        b"nil\tout.txt: No such file or directory\t44",
    ]
    assert not (tmp_path / "out.txt").exists()


def test_a_script_cannot_leave_its_directory(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    world = tmp_path / "world"
    world.mkdir()
    result = luawasm.run(["-e", 'print(io.open("../secret.txt"))'], root=world)
    assert result.stdout == b"nil\t../secret.txt: Capabilities insufficient\t76\n"  # ENOTCAPABLE, not the content


def test_a_program_that_sees_no_files_cannot_open_any() -> None:
    result = luawasm.run(["-e", 'print(io.open("anything"))'])
    assert result.stdout.startswith(b"nil\tanything:")


def test_an_error_of_the_script_stops_the_interpreter() -> None:
    # built without longjmp: the interpreter traps, and there is no message
    assert luawasm.run(["-e", 'error("boom")']).code == luawasm.ABORTED
