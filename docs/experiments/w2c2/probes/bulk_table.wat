(module (table 4 funcref) (func $f) (elem $e func $f)
  (func (export "go") (table.init $e (i32.const 0) (i32.const 0) (i32.const 1)) (elem.drop $e) (table.copy (i32.const 1) (i32.const 0) (i32.const 1))))
