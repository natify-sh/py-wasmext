(module
  (import "env" "twice" (func $twice (param v128) (result v128)))
  (import "env" "split" (func $split (param v128 i32) (result i32 v128)))
  (func (export "double") (param v128) (result v128) local.get 0 local.get 0 i32x4.add)
  (func (export "pair") (param i32 v128) (result v128 i32) local.get 1 local.get 0)
  (func (export "via_import") (param v128) (result v128) local.get 0 call $twice)
  (func (export "via_split") (param v128 i32) (result i32 v128) local.get 0 local.get 1 call $split)
  (func (export "lane") (param v128) (result i32) local.get 0 i32x4.extract_lane 3))
