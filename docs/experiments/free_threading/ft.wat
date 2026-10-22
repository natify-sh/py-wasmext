(module
  (memory (export "memory") 1)
  (type $t (func (param i32) (result i32)))
  (table 3 funcref)
  (elem (i32.const 0) $rec $recc $fib)
  ;; a call through a table: the C compiler cannot turn this recursion into a loop
  (func $rec (export "recurse") (param i32) (result i32)
    (i32.add (call_indirect (type $t) (i32.add (local.get 0) (i32.const 1)) (i32.const 0)) (i32.const 1)))
  ;; the same, and it keeps its depth in memory[0], so that the depth reached before the trap can be read
  (func $recc (export "recurse_count") (param i32) (result i32)
    (i32.store (i32.const 0) (local.get 0))
    (i32.add (call_indirect (type $t) (i32.add (local.get 0) (i32.const 1)) (i32.const 1)) (i32.const 1)))
  ;; calls inside the module, through the table so that the C compiler cannot turn them into a loop: what a counter of the depth of the stack costs
  ;; is paid in the entry of each of them
  (func $fib (export "fib") (param i32) (result i32)
    (if (result i32) (i32.lt_u (local.get 0) (i32.const 2))
      (then (local.get 0))
      (else (i32.add (call_indirect (type $t) (i32.sub (local.get 0) (i32.const 1)) (i32.const 2))
                     (call_indirect (type $t) (i32.sub (local.get 0) (i32.const 2)) (i32.const 2))))))
  (func (export "add") (param i32 i32) (result i32) (i32.add (local.get 0) (local.get 1)))
  ;; a xorshift: each step needs the one before, so the C compiler cannot turn the loop into a formula (about 1 ns a step)
  (func (export "work") (param $n i32) (result i32)
    (local $i i32) (local $acc i32)
    (local.set $acc (i32.const 1))
    (loop $l
      (local.set $acc (i32.xor (local.get $acc) (i32.shl (local.get $acc) (i32.const 13))))
      (local.set $acc (i32.xor (local.get $acc) (i32.shr_u (local.get $acc) (i32.const 17))))
      (local.set $acc (i32.xor (local.get $acc) (i32.shl (local.get $acc) (i32.const 5))))
      (local.set $i (i32.add (local.get $i) (i32.const 1)))
      (br_if $l (i32.lt_u (local.get $i) (local.get $n))))
    (local.get $acc))
  (func (export "trap") (result i32) unreachable)
  (func (export "oob") (result i32) (i32.load (i32.const 0x7ffffff0))))
