;; An import that the host answers with a function that asks for the Caller (`fn.__wasm_caller__ = True`): it reads the memory of the instance that called.
(module
  (import "env" "peek" (func $peek (param i32) (result i32)))
  (memory (export "memory") 1)
  (func (export "go") (param i32) (result i32) local.get 0 call $peek)
  (func (export "poke") (param i32 i32) local.get 0 local.get 1 i32.store8))
