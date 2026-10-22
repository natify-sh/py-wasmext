(module
  (memory (export "memory") 2)
  ;; memory-heavy: store a word, load it back, sum; n words, repeated r times (a dependent chain: the sum feeds the next address)
  (func (export "memsum") (param $n i32) (param $r i32) (result i32)
    (local $i i32) (local $acc i32)
    (loop $outer
      (local.set $i (i32.const 0))
      (loop $l
        (i32.store (i32.shl (local.get $i) (i32.const 2)) (i32.add (local.get $i) (local.get $acc)))
        (local.set $acc (i32.add (local.get $acc) (i32.load (i32.shl (local.get $i) (i32.const 2)))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br_if $l (i32.lt_u (local.get $i) (local.get $n))))
      (local.set $r (i32.sub (local.get $r) (i32.const 1)))
      (br_if $outer (local.get $r)))
    (local.get $acc)))
