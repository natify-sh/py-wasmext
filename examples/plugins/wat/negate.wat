;; Another plugin: `negate` in slot 2, and `boom` in slot 3, which traps (a trap in a function of one module that another module called
;; through the table comes back to the caller as its own Trap).
(module
  (type $unary (func (param i32) (result i32)))
  (import "env" "table" (table 4 16 funcref))
  (func $negate (type $unary) i32.const 0 local.get 0 i32.sub)
  (func $boom (type $unary) unreachable)
  (elem (i32.const 2) func $negate $boom)
  (func (export "negate") (type $unary) i32.const 0 local.get 0 i32.sub))
