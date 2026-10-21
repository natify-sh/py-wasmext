import struct, sys
import _guest, _provider

HOST = "demo:text/host@0.1.0"
prov = _provider.Instance()

def put(inst, s):
    b = s.encode()
    p = getattr(inst, "cabi_realloc")(0, 0, 1, len(b))
    inst.memory[p : p + len(b)] = b
    return p, len(b)

# the answer is the sum of the bytes of "ab" (97 + 98) + 1 = 196
mode = sys.argv[1]
if mode == "direct":
    guest = _guest.Instance({HOST: {"lookup": prov["demo:text/host@0.1.0#lookup"]}})
else:
    box = {}
    def lookup(ptr, ln):
        s = bytes(box["g"].memory[ptr : ptr + ln]).decode()
        p, n = put(prov, s)                       # canon lower by hand: copy into the provider's memory
        return getattr(prov, "demo:text/host@0.1.0#lookup")(p, n)
    guest = _guest.Instance({HOST: {"lookup": lookup}})
    box["g"] = guest
p, n = put(guest, "ab")
print(mode, "->", getattr(guest, "demo:text/api@0.1.0#run")(p, n))
