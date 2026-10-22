(module
  (import "env" "f" (func $f (param i32) (result i32)))
  (type $t (func (param i32) (result i32)))
  (table 2 2 funcref)
  (elem (i32.const 0) func $f)
  (func (export "run") (param i32) (result i32) local.get 0 i32.const 0 call_indirect (type $t)))
