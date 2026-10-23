;; Writes the filetype that fd_fdstat_get says the standard output is, as a digit and a newline (0 unknown, 2 character device, 4 regular file).
(module
  (import "wasi_snapshot_preview1" "fd_fdstat_get" (func $fdstat (param i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_write" (func $write (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") 1)
  (func (export "_start")
    (drop (call $fdstat (i32.const 1) (i32.const 100)))
    (i32.store8 (i32.const 200) (i32.add (i32.const 48) (i32.load8_u (i32.const 100))))
    (i32.store8 (i32.const 201) (i32.const 10))
    (i32.store (i32.const 300) (i32.const 200))
    (i32.store (i32.const 304) (i32.const 2))
    (drop (call $write (i32.const 1) (i32.const 300) (i32.const 1) (i32.const 308)))))
