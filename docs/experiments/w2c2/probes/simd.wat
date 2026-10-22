(module (func (export "add") (param v128 v128) (result v128) local.get 0 local.get 1 i32x4.add)
  (func (export "splat") (param i32) (result v128) local.get 0 i32x4.splat))
