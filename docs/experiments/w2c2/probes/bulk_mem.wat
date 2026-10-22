(module (memory 1) (data $d "abcd")
  (func (export "go") (memory.fill (i32.const 0) (i32.const 7) (i32.const 8)) (memory.copy (i32.const 16) (i32.const 0) (i32.const 8)) (memory.init $d (i32.const 32) (i32.const 0) (i32.const 4)) (data.drop $d)))
