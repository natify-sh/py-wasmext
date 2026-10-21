;; The main module of dynamic linking: a table of 8 slots (at most 16) with one function in it, `inc`, and `call`, which calls
;; a slot of the table. Other modules import the table and put functions of their own in it.
(module
  (type $unary (func (param i32) (result i32)))
  (table (export "table") 8 16 funcref)
  (func $inc (export "inc") (type $unary) local.get 0 i32.const 1 i32.add)
  (elem (i32.const 0) func $inc)
  (func (export "call") (param i32 i32) (result i32)
    local.get 1 local.get 0 call_indirect (type $unary))
  (func (export "size") (result i32) table.size 0))
