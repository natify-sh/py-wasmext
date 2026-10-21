;; A module with every kind of thing the C API of a library has a function for: it is turned into a header whose public declarations are the
;; ones that abi/current.json declares (tests/test_abi_declaration.py). Changing it changes the declaration.
(module
  (import "env" "host" (func $host (param i32) (result i32)))
  (import "env" "itab" (table $itab 2 funcref))
  (import "env" "iglobal" (global $iglobal (mut i32)))
  (memory (export "mem") 1 2)
  (global (export "counter") (mut i32) (i32.const 1))
  (global (export "limit") i32 (i32.const 2))
  (table $tab (export "tab") 4 8 funcref)
  (func $add (export "add") (param i32 i32) (result i32)
    local.get 0
    local.get 1
    i32.add)
  (func (export "wide") (param i64 f32 f64) (result i64 i32)
    local.get 0
    i32.const 0)
  (func (export "pick") (param funcref) (result funcref)
    local.get 0)
  (func (export "call_host") (param i32) (result i32)
    local.get 0
    call $host)
  (elem (table $tab) (i32.const 0) func $add))
