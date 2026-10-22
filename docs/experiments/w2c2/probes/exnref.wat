(module (tag $e)
  (func (export "re") (throw_ref (block $h (result exnref) (try_table (catch_all_ref $h) (throw $e)) (unreachable)))))
