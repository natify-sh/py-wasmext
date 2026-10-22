;; An imported function put into a table by an element segment and called with call_indirect: wasm2c 1.0.42 gives the entry the wrong module instance.
(module
  (import "env" "f" (func $f (param i32) (result i32)))
  (type $t (func (param i32) (result i32)))
  (table 2 2 funcref)
  (func $twice (type $t) local.get 0 i32.const 2 i32.mul)
  (elem (i32.const 0) func $f $twice)
  (func (export "via_import") (param i32) (result i32) local.get 0 i32.const 0 call_indirect (type $t))
  (func (export "via_defined") (param i32) (result i32) local.get 0 i32.const 1 call_indirect (type $t)))
