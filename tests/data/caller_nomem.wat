;; A module without a memory: the Caller's memory is None.
(module
  (import "env" "who" (func $who (result i32)))
  (func (export "go") (result i32) call $who))
