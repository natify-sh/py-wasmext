(module
  (tag $one (param i32))
  (tag $many (param i64 f32 f64 i32))
  (tag $bare)
  (func (export "throw_one") (param i32) local.get 0 throw $one)
  (func (export "throw_many") i64.const -5 f32.const 1.5 f64.const 2.25 i32.const -1 throw $many)
  (func (export "throw_bare") throw $bare)
  (func (export "caught") (result i32)
    try (result i32)
      i32.const 7
      throw $one
    catch $one
      i32.const 1
      i32.add
    end)
  (func (export "ok") (result i32) i32.const 5))
