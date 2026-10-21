;; Not a command (no _start): a trap is a trap, the instance goes on.
(module
  (import "wasi_snapshot_preview1" "sched_yield" (func $sched_yield (result i32)))
  (memory (export "memory") 1)
  (func (export "boom") unreachable)
  (func (export "ping") (result i32) i32.const 1))
