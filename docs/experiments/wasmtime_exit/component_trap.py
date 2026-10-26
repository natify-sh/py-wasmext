import wasmtime
from wasmtime import Engine, Store
from wasmtime.component import Component, Linker

WAT = r'''
(component
  (core module $m
    (func (export "boom") unreachable)
    (func (export "five") (result i32) i32.const 5))
  (core instance $i (instantiate $m))
  (func (export "boom") (canon lift (core func $i "boom")))
  (func (export "five") (result u32) (canon lift (core func $i "five"))))
'''
engine = Engine()
store = Store(engine)
comp = Component(engine, WAT)
linker = Linker(engine)
inst = linker.instantiate(store, comp)
def get(name):
    idx = inst.get_export_index(store, name) if hasattr(inst, "get_export_index") else None
    return inst.get_func(store, idx if idx is not None else name)
five = get("five"); boom = get("boom")
print("five before:", five(store))
try:
    boom(store)
except Exception as e:
    print("boom ->", type(e).__name__, str(e).splitlines()[0][:90])
try:
    print("five after the trap:", five(store))
except Exception as e:
    print("five after the trap -> EXC", type(e).__name__, str(e).splitlines()[0][:120])
inst2 = linker.instantiate(store, comp)
five2 = inst2.get_func(store, inst2.get_export_index(store, "five")) if hasattr(inst2, "get_export_index") else None
try:
    print("a new instance of the component in the same store:", five2(store))
except Exception as e:
    print("new instance -> EXC", type(e).__name__, str(e).splitlines()[0][:120])

print("--- two instances made BEFORE the trap, same store")
store = Store(engine)
linker = Linker(engine)
i1 = linker.instantiate(store, comp); i2 = linker.instantiate(store, comp)
g = lambda inst, n: inst.get_func(store, inst.get_export_index(store, n))
try: g(i1, "boom")(store)
except Exception as e: print("i1.boom ->", str(e).splitlines()[0][:60])
for label, inst in (("i1.five after its trap", i1), ("i2.five (another instance, same store)", i2)):
    try: print(label, g(inst, "five")(store))
    except Exception as e: print(label, "-> EXC", str(e).splitlines()[0][:100])
print("--- a new store")
s3 = Store(engine); i3 = Linker(engine).instantiate(s3, comp)
print("new store, five:", i3.get_func(s3, i3.get_export_index(s3, "five"))(s3))

print("--- two DIFFERENT components in one store")
WAT2 = WAT.replace('"five") (result i32) i32.const 5', '"five") (result i32) i32.const 6')
comp2 = Component(engine, WAT2)
store = Store(engine)
a = Linker(engine).instantiate(store, comp); b = Linker(engine).instantiate(store, comp2)
try: g(a, "boom")(store)
except Exception as e: print("a.boom ->", str(e).splitlines()[0][:50])
try: print("b.five (another component, same store):", g(b, "five")(store))
except Exception as e: print("b.five -> EXC", str(e).splitlines()[0][:100])
