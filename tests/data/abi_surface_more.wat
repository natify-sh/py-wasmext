;; More forms of the C API of a library than abi_surface.wat has: a v128 in a signature, a 64-bit memory, an imported memory, a tag (an exception that nothing
;; catches), several results. Its declarations are in abi/current.json with the others (tests/test_abi_declaration.py).
(module
  (import "env" "mem" (memory $imem 1))
  (import "env" "vhost" (func $vhost (param v128) (result v128)))
  (tag $t (param i32))
  (memory (export "big") i64 1 2)
  (func (export "vadd") (param v128 v128) (result v128)
    local.get 0
    local.get 1
    i32x4.add)
  (func (export "boom") (param i32)
    local.get 0
    throw $t)
  (func (export "two") (param i32) (result i32 i32)
    local.get 0
    local.get 0)
  (func (export "call_vhost") (param v128) (result v128)
    local.get 0
    call $vhost))
