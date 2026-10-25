;; A command of WASI 0.2 as `wasm-tools component unbundle` leaves it, by hand: `wasi:cli/run@0.2.12#run` calls wasi:cli/exit with ok when it was given three arguments and
;; two environment variables, and answers err (1) when it was not; the code of `exit` is ok or err (the status of wasi:cli/exit).
(module
  (import "wasi:cli/environment@0.2.12" "get-arguments" (func $args (param i32)))
  (import "wasi:cli/environment@0.2.12" "get-environment" (func $env (param i32)))
  (import "wasi:cli/exit@0.2.12" "exit" (func $exit (param i32)))
  (memory (export "memory") 2)
  (global $bump (mut i32) (i32.const 4096))
  (func (export "cabi_realloc") (param $old i32) (param $old_size i32) (param $align i32) (param $size i32) (result i32)
    (local $p i32)
    (local.set $p (global.get $bump))
    (global.set $bump (i32.add (global.get $bump) (local.get $size)))
    (local.get $p))
  (func (export "wasi:cli/run@0.2.12#run") (result i32)
    (call $args (i32.const 100))
    (call $env (i32.const 200))
    (if (i32.and
          (i32.eq (i32.load (i32.const 104)) (i32.const 3))
          (i32.eq (i32.load (i32.const 204)) (i32.const 2)))
      (then (call $exit (i32.const 0))))
    (i32.const 1)))
