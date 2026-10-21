(module
  ;; The search keeps its progress in exported globals, so the host can read them
  ;; while the call is paused
  (global $n        (export "n")        (mut i32) (i32.const 1))
  (global $best_n   (export "best_n")   (mut i32) (i32.const 1))
  (global $best_len (export "best_len") (mut i32) (i32.const 0))

  ;; The number of steps it takes $x to reach 1
  (func $chain_length (param $x i64) (result i32)
    (local $len i32)
    (block $done
      (loop $step
        (br_if $done (i64.eq (local.get $x) (i64.const 1)))
        (local.set $x
          (if (result i64) (i64.eqz (i64.and (local.get $x) (i64.const 1)))
            (then (i64.shr_u (local.get $x) (i64.const 1)))
            (else (i64.add (i64.mul (local.get $x) (i64.const 3)) (i64.const 1)))))
        (local.set $len (i32.add (local.get $len) (i32.const 1)))
        (br $step)))
    (local.get $len))

  ;; The number below $limit with the longest chain
  (func (export "search") (param $limit i32) (result i32)
    (local $len i32)
    (loop $next
      (local.set $len (call $chain_length (i64.extend_i32_u (global.get $n))))
      (if (i32.gt_u (local.get $len) (global.get $best_len))
        (then
          (global.set $best_len (local.get $len))
          (global.set $best_n (global.get $n))))
      (global.set $n (i32.add (global.get $n) (i32.const 1)))
      (br_if $next (i32.lt_u (global.get $n) (local.get $limit))))
    (global.get $best_n))
)
