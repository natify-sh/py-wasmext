(module (memory (export "m") 1) (table 2 funcref) (type $t (func (param i32) (result i32)))
  (func $f (type $t) local.get 0 i32.const 1 i32.add)
  (elem (i32.const 0) $f)
  (func (export "go") (param i32) (result i32) local.get 0 i32.const 0 call_indirect (type $t)))
