import _fused as f

inst = f.Instance()
b = b"ab"
p = getattr(inst, "cabi_realloc$1")(0, 0, 1, len(b))
mem = getattr(inst, "memory$0")
mem[p : p + len(b)] = b
print("run('ab') ->", getattr(inst, "demo:text/api@0.1.0#run")(p, len(b)), "(expected 97+98+1 = 196)")
print("memories are different objects:", getattr(inst, "memory$0") is not None, "| exports:", [n for n in dir(inst) if "memory" in n or "realloc" in n])
