(module (func (export "pair") (result i32 i32) i32.const 1 i32.const 2)
  (func (export "swap") (param i32 i32) (result i32 i32) local.get 1 local.get 0)
  (func (export "blk") (result i32) i32.const 5 (block (param i32) (result i32) i32.const 1 i32.add)))
