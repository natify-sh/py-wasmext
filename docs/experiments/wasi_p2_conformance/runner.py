"""Runs the scripts on the guest in Wasmtime (wasmtime-py) and on the Python host of wasmext, and shows the lines that differ.

    uv run python docs/experiments/wasi_p2_conformance/runner.py [script_fs.txt]

Needs: `pip install wasmtime`, `rustup target add wasm32-wasip2`, and `cargo build --release --target wasm32-wasip2` in guest/. Not part of the tests (CI has none of that).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import wasmtime as w
import wasmtime.component as c

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))
import ours

WASM = HERE / "guest" / "target" / "wasm32-wasip2" / "release" / "conf.wasm"


def make_tree(root: Path) -> None:
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "f").write_text("data")
    (root / "sub" / "g").write_text("")
    (root / "empty").mkdir()
    (root / "hello.txt").write_text("hello world\n")
    (root / "ro.txt").write_text("fixed")
    (root / "ro.txt").chmod(0o444)
    os.symlink("sub", root / "ln")
    os.symlink("hello.txt", root / "filelink")
    os.symlink("/etc", root / "abs")
    os.symlink("../x", root / "up")
    os.symlink("loop2", root / "loop1")
    os.symlink("loop1", root / "loop2")
    os.symlink("sub/../sub", root / "deep")
    os.symlink("nothing", root / "dangling")
    (root.parent / "outdir").mkdir(exist_ok=True)
    (root.parent / "outdir" / "secret").write_text("secret")
    os.symlink("../outdir", root / "lkout")
    os.mkfifo(root / "fifo")


def fresh(base: Path) -> tuple[Path, Path]:
    if base.exists():
        shutil.rmtree(base)
    rw, ro = base / "rw" / "world", base / "ro" / "world"
    make_tree(rw)
    make_tree(ro)
    return rw, ro


def wasmtime_lines(script: Path, base: Path) -> list[str]:
    rw, ro = fresh(base)
    out = base / "out.txt"
    engine = w.Engine()
    component = c.Component.from_file(engine, str(WASM))
    linker = c.Linker(engine)
    linker.add_wasip2()
    store = w.Store(engine)
    cfg = w.WasiConfig()
    cfg.argv = ["conf", str(script)]
    cfg.stdout_file = str(out)
    cfg.preopen_dir(str(rw), "/world")
    cfg.preopen_dir(str(ro), "/ro", False)
    cfg.preopen_dir(str(script.parent), str(script.parent), False)
    store.set_wasi(cfg)
    instance = linker.instantiate(store, component)
    run = instance.get_func(store, instance.get_export_index(store, "run", instance.get_export_index(store, "wasi:cli/run@0.2.4")))
    assert run is not None
    run(store)
    return out.read_text().splitlines()


def ours_lines(script: Path, base: Path) -> list[str]:
    rw, ro = fresh(base)
    return ours.run(script, [(str(rw), "/world", True), (str(ro), "/ro", False)])


def main() -> int:
    script = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "script_fs.txt").resolve()
    work = Path(tempfile.mkdtemp(prefix="p2conf"))
    theirs = wasmtime_lines(script, work / "wasmtime")
    mine = ours_lines(script, work / "ours")
    source = [x.strip() for x in script.read_text().splitlines() if x.strip() and not x.strip().startswith("#")]
    bad = known = 0
    for i, (a, b) in enumerate(zip(theirs, mine, strict=False)):
        if a != b:
            if "#~" in source[i]:
                known += 1
                continue
            bad += 1
            print(f"DIFFERENT  {source[i]}\n    wasmtime: {a}\n    ours:     {b}")
    if len(theirs) != len(mine):
        print(f"lengths differ: wasmtime {len(theirs)}, ours {len(mine)}")
        bad += 1
    print(f"{len(source)} operations, {bad} different, {known} known differences (marked #~ in the script)")
    shutil.rmtree(work, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
