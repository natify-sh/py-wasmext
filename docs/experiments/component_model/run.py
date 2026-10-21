"""Attach host functions built by wit-bindgen (an unbundled provider module) to an unbundled guest extension."""

import json
import struct
import sys

import _guest
import _provider

HOST = "demo:text/host@0.1.0"
IMPORTS = json.load(open("guest_imports.json"))


def wasi_stubs():
    out = {}
    for mod, name in IMPORTS:
        if mod == HOST:
            continue

        def stub(*a, _n=f"{mod}.{name}"):
            if "[resource-drop]" in _n:
                return None
            raise NotImplementedError(_n)

        out.setdefault(mod, {})[name] = stub
    return out


def lift_string(inst, ptr, ln):
    return bytes(inst.memory[ptr : ptr + ln]).decode()


def lower_string(inst, s):
    b = s.encode()
    p = inst.cabi_realloc(0, 0, 1, len(b))
    inst.memory[p : p + len(b)] = b
    return p, len(b)


def call_greet(guest, name):  # canon lower of the argument, lift of the result, post-return
    p, n = lower_string(guest, name)
    ret = getattr(guest, "demo:text/api@0.1.0#greet")(p, n)
    sp, sl = struct.unpack_from("<II", guest.memory, ret)
    s = lift_string(guest, sp, sl)
    getattr(guest, "cabi_post_demo:text/api@0.1.0#greet")(ret)
    return s


mode = sys.argv[1]
prov = _provider.Instance()
prov._initialize()

if mode == "direct":
    # A: the provider's core exports straight into the guest's imports (C to C, no Python between)
    host = {"lookup": prov[f"{HOST}#lookup"], "log": prov[f"{HOST}#log"]}
elif mode == "adapter":
    # B: canon lower/lift by hand in Python: copy the string from the guest's memory into the provider's
    box = {}

    def lookup(ptr, ln):
        p, n = lower_string(prov, lift_string(box["g"], ptr, ln))
        return getattr(prov, f"{HOST}#lookup")(p, n)

    def log(ptr, ln):
        p, n = lower_string(prov, lift_string(box["g"], ptr, ln))
        getattr(prov, f"{HOST}#log")(p, n)

    host = {"lookup": lookup, "log": log}
elif mode == "wasm-adapter":
    # C: the same copy in a third wasm module (multi-memory); see 2.6
    import _adapter
    import _guest2
    import _memhold

    hold = _memhold.Instance()
    adapter = _adapter.Instance(
        {
            "guest": {"memory": hold["memory"]},
            "prov": {
                "memory": prov["memory"],
                "cabi_realloc": prov["cabi_realloc"],
                "lookup": prov[f"{HOST}#lookup"],
                "log": prov[f"{HOST}#log"],
            },
        }
    )
    host = {"lookup": adapter["lookup"], "log": adapter["log"]}

if mode == "wasm-adapter":
    guest = _guest2.Instance({HOST: host, "env": {"memory": hold["memory"]}, **wasi_stubs()})
else:
    guest = _guest.Instance({HOST: host, **wasi_stubs()})
if mode == "adapter":
    box["g"] = guest
guest._initialize()
