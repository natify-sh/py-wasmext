(module (type $t (func (param i32) (result i32))) (table 1 funcref) (elem (i32.const 0) $r)
  (func $r (type $t) (param i32) (result i32) (i32.add (call_indirect (type $t) (i32.add (local.get 0) (i32.const 1)) (i32.const 0)) (i32.const 1)))
  (func (export "recurse") (result i32) (call $r (i32.const 0))))
