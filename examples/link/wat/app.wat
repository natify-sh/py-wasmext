;; A program that uses the counter without knowing it is another module: it imports a memory, a variable and a function
;; from the shelf "env", and a function `log` that only the host can give.
(module
  (import "env" "memory" (memory 1))
  (import "env" "count" (global $count (mut i32)))
  (import "env" "bump" (func $bump (param i32) (result i32)))
  (import "env" "log" (func $log (param i32)))
  (func (export "tick") (result i32) (local $n i32)
    i32.const 1 call $bump local.set $n
    local.get $n call $log
    local.get $n)
  (func (export "count") (result i32) global.get $count)
  (func (export "reset") i32.const 0 global.set $count)
  (func (export "peek") (param i32) (result i32) local.get 0 i32.load8_u)
  (func (export "poke") (param i32 i32) local.get 0 local.get 1 i32.store8))
