(module (tag $e (param i32))
  (func (export "caught") (result i32) try (result i32) i32.const 7 throw $e catch $e i32.const 1 i32.add end))
