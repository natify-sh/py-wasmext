(module (type $t (func (param i32) (result i32))) (table 1 funcref) (elem (i32.const 0) $loop)
  (func $loop (type $t) (param i32) (result i32) (if (result i32) (i32.eqz (local.get 0)) (then (i32.const 7)) (else (return_call $loop (i32.sub (local.get 0) (i32.const 1))))))
  (func (export "go") (param i32) (result i32) (return_call_indirect (type $t) (local.get 0) (i32.const 0))))
