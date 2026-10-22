(module
  (memory 1)
  (func (export "oob") (result i32) (i32.load (i32.const 0x7ffffff0)))
  (func (export "ok") (result i32) (i32.const 1)))
