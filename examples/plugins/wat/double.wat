;; A plugin: it imports the table of the host and puts `double` in slot 1. It can call every slot too, the functions of the others included.
(module
  (type $unary (func (param i32) (result i32)))
  (import "env" "table" (table 4 16 funcref))
  (func $double (type $unary) local.get 0 i32.const 2 i32.mul)
  (elem (i32.const 1) func $double)
  (func (export "double") (type $unary) local.get 0 i32.const 2 i32.mul)
  (func (export "call") (param i32 i32) (result i32)
    local.get 1 local.get 0 call_indirect (type $unary))
  (func (export "size") (result i32) table.size 0))
