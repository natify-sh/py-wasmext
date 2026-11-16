(module
  (memory (export "mem") 1)
  (func (export "kernel") (param $n i32) (result i32)
    (local $i i32) (local $acc i32)
    (local.set $acc (i32.const 1))
    (loop $L
      (local.set $acc
        (i32.add
          (i32.add (i32.mul (local.get $acc) (i32.const 31))
                   (i32.load8_u (i32.and (local.get $i) (i32.const 1023))))
          (local.get $i)))
      (i32.store8 (i32.and (i32.mul (local.get $i) (i32.const 7)) (i32.const 1023)) (local.get $acc))
      (local.set $i (i32.add (local.get $i) (i32.const 1)))
      (br_if $L (i32.lt_u (local.get $i) (local.get $n))))
    (local.get $acc)))
