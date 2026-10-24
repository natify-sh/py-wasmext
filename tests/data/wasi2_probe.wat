;; A core module as `wasm-tools component unbundle` leaves it, by hand: it imports a few functions of WASI 0.2, exports its memory and a `cabi_realloc` (a bump allocator),
;; and calls each import from an export of its own, so that a test can look at the memory.
(module
  (import "wasi:cli/environment@0.2.12" "get-arguments" (func $args (param i32)))
  (import "wasi:cli/environment@0.2.12" "get-environment" (func $env (param i32)))
  (import "wasi:cli/exit@0.2.12" "exit" (func $exit (param i32)))
  (import "wasi:clocks/monotonic-clock@0.2.12" "now" (func $now (result i64)))
  (import "wasi:random/random@0.2.12" "get-random-u64" (func $rand (result i64)))
  (memory (export "memory") 2)
  (global $heap (mut i32) (i32.const 8192))
  (func (export "cabi_realloc") (param $old i32) (param $old_size i32) (param $align i32) (param $size i32) (result i32)
    (local $p i32)
    (local.set $p
      (i32.and
        (i32.add (global.get $heap) (i32.sub (local.get $align) (i32.const 1)))
        (i32.xor (i32.sub (local.get $align) (i32.const 1)) (i32.const -1))))
    (global.set $heap (i32.add (local.get $p) (local.get $size)))
    (local.get $p))
  (func (export "args") (param i32) (call $args (local.get 0)))
  (func (export "env") (param i32) (call $env (local.get 0)))
  (func (export "exit") (param i32) (call $exit (local.get 0)))
  (func (export "now") (result i64) (call $now))
  (func (export "rand") (result i64) (call $rand)))
