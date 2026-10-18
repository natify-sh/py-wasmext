;; The same function imported twice, as AssemblyScript does: both are one function of the module.
(module
  (import "wasi_snapshot_preview1" "fd_write" (func $first (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_write" (func $second (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") 1)
  (func (export "first") (param i32) (result i32) local.get 0 i32.const 0 i32.const 0 i32.const 0 call $first)
  (func (export "second") (param i32) (result i32) local.get 0 i32.const 0 i32.const 0 i32.const 0 call $second))
