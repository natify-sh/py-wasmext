(module (memory $a 1) (memory $b 1)
  (func (export "go") (result i32) (i32.store $b (i32.const 0) (i32.const 9)) (i32.load $b (i32.const 0))))
