;; writes the arguments and then the environment, each ended by a NUL, to stdout; exits with the number of arguments
(module
  (import "wasi_snapshot_preview1" "args_sizes_get" (func $asg (param i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "args_get" (func $ag (param i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "environ_sizes_get" (func $esg (param i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "environ_get" (func $eg (param i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_write" (func $fw (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "proc_exit" (func $exit (param i32)))
  (memory (export "memory") 1)
  (func $out (param $p i32) (param $n i32)
    (i32.store (i32.const 16) (local.get $p))
    (i32.store (i32.const 20) (local.get $n))
    (drop (call $fw (i32.const 1) (i32.const 16) (i32.const 1) (i32.const 24))))
  (func (export "_start")
    (drop (call $asg (i32.const 0) (i32.const 4)))        ;; argc at 0, size at 4
    (drop (call $esg (i32.const 8) (i32.const 12)))       ;; envc at 8, size at 12
    (drop (call $ag (i32.const 1024) (i32.const 2048)))   ;; pointers at 1024, text at 2048
    (call $out (i32.const 2048) (i32.load (i32.const 4)))
    (drop (call $eg (i32.const 4096) (i32.const 6144)))
    (call $out (i32.const 6144) (i32.load (i32.const 12)))
    (call $exit (i32.load (i32.const 0)))))
