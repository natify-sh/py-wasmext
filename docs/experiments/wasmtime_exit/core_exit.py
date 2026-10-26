import tempfile, os
import wasmtime
from wasmtime import Engine, Store, Linker, Module, WasiConfig, ExitTrap, Trap

WAT = r'''
(module
  (import "wasi_snapshot_preview1" "proc_exit" (func $exit (param i32)))
  (import "wasi_snapshot_preview1" "path_open" (func $open (param i32 i32 i32 i32 i32 i64 i64 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_write" (func $write (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") 1)
  (data (i32.const 100) "f.txt")
  (data (i32.const 400) "hello")
  (data (i32.const 300) "\90\01\00\00\05\00\00\00")
  (func (export "open_file") (result i32)
    (call $open (i32.const 3) (i32.const 0) (i32.const 100) (i32.const 5) (i32.const 1) (i64.const 536870911) (i64.const 536870911) (i32.const 0) (i32.const 200)))
  (func (export "write_fd") (result i32)
    (call $write (i32.load (i32.const 200)) (i32.const 300) (i32.const 1) (i32.const 500)))
  (func (export "hello") (result i32) (i32.const 42))
  (func (export "quit") (call $exit (i32.const 7))))
'''
d = tempfile.mkdtemp(dir="/tmp/claude-0/wt")
engine = Engine()
store = Store(engine)
linker = Linker(engine)
linker.define_wasi()
cfg = WasiConfig()
cfg.preopen_dir(d, "/")
store.set_wasi(cfg)
module = Module(engine, WAT)
A = linker.instantiate(store, module)
B = linker.instantiate(store, module)
f = lambda inst, name: inst.exports(store)[name](store)
print("B.hello before:", f(B, "hello"))
print("B.open_file errno:", f(B, "open_file"))
try:
    f(A, "quit")
    print("A.quit returned (no exception)")
except ExitTrap as e:
    print("A.quit -> ExitTrap, code", e.code)
except Trap as e:
    print("A.quit -> other trap:", type(e).__name__, e)
for label, inst, name in (("B.hello after A exit", B, "hello"), ("A.hello after A exit (same instance)", A, "hello"), ("B.write_fd after A exit (descriptor B opened)", B, "write_fd"), ("A.write_fd (descriptor B opened, shared table)", A, "write_fd")):
    try:
        print(f"{label}:", f(inst, name))
    except Exception as e:
        print(f"{label}: EXC", type(e).__name__, str(e)[:100])
print("file content:", open(os.path.join(d, "f.txt")).read())
try:
    f(A, "quit")
except ExitTrap as e:
    print("A.quit again -> ExitTrap", e.code)
print("B.hello at the end:", f(B, "hello"))
