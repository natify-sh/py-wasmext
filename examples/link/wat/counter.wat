;; A counter: a variable, a function that adds to it, and a memory with a greeting in it.
(module
  (memory (export "memory") 1 4)
  (data (i32.const 0) "hello from counter")
  (global (export "count") (mut i32) (i32.const 0))
  (func (export "bump") (param i32) (result i32)
    global.get 0 local.get 0 i32.add global.set 0 global.get 0))
