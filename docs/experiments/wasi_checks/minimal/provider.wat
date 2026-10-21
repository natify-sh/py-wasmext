(module
  (memory (export "memory") 1)
  (global $bump (mut i32) (i32.const 1024))
  (func (export "cabi_realloc") (param i32 i32 i32 i32) (result i32)
    (local $p i32)
    (local.set $p (global.get $bump))
    (global.set $bump (i32.add (global.get $bump) (local.get 3)))
    (local.get $p))
  ;; lookup(ptr,len) -> sum of the bytes of the string
  (func (export "demo:text/host@0.1.0#lookup") (param $ptr i32) (param $len i32) (result i32)
    (local $i i32) (local $s i32)
    (block $done
      (loop $l
        (br_if $done (i32.ge_u (local.get $i) (local.get $len)))
        (local.set $s (i32.add (local.get $s) (i32.load8_u (i32.add (local.get $ptr) (local.get $i)))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $l)))
    (local.get $s)))
