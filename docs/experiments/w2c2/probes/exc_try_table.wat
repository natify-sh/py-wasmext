(module (tag $e (param i32))
  (func (export "tt") (result i32) (block $out (result i32) (try_table (catch $e $out) (throw $e (i32.const 3)) (i32.const -1) (br 1)) (i32.const -2))))
