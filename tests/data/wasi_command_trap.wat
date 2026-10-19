;; A command (it exports _start) that traps, and a function to call afterwards; and the same without _start, a reactor, in wasi_reactor_trap.wat.
(module
  (import "wasi_snapshot_preview1" "sched_yield" (func $sched_yield (result i32)))
  (memory (export "memory") 1)
  (func (export "_start") unreachable)
  (func (export "ping") (result i32) i32.const 1))
