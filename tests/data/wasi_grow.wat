;; fd_write and memory.grow, each exported, for the test of two instances in one store: the base and the size of the memory change
;; when it grows, and the host must read the new ones of the instance that calls.
(module
  (import "wasi_snapshot_preview1" "fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") 1 4)
  (func (export "fd_write") (param i32 i32 i32 i32) (result i32) local.get 0 local.get 1 local.get 2 local.get 3 call $fd_write)
  (func (export "grow") (param i32) (result i32) local.get 0 memory.grow))
