"""Run the complex component fused by meld (500 KB core module, two memories) from Python. See docs/WASI_COMPONENTS.md.

Expected by construction: get=apple,3,[red,big]. meld 0.64.0 gives get=apple,3,[,] (checked 2026-10-21; jco in Node gives [red,big])."""

import json
import struct

import _cx
from wasmext._wasm import parse  # private: the list of the imports of the module

info = json.load(open("cx.imports.json"))["imports"]
box = {}
table = {}
counter = {"n": 0, "new": 0, "rep": 0, "drop": 0}


def new(rep):
    counter["new"] += 1
    counter["n"] += 1
    table[counter["n"]] = rep
    return counter["n"]


def rep(h):
    counter["rep"] += 1
    return table[h]


def drop(h):
    counter["drop"] += 1
    r = table.pop(h)
    getattr(box["i"], "demo:cx/store@0.1.0#[dtor]counter")(r)


def stub(name):
    def f(*a):
        if "[resource-drop]" in name:
            return None
        raise NotImplementedError(name)

    return f


imports = {}

mod = parse(open("_cx.wasm", "rb").read())
for imp in mod.imports:
    key = (imp.module, imp.name)
    if imp.name.startswith("[resource-new]"):
        fn = new
    elif imp.name.startswith("[resource-rep]"):
        fn = rep
    elif imp.module == "demo:cx/store@0.1.0" and imp.name == "[resource-drop]counter":
        fn = drop
    else:
        fn = stub(f"{imp.module}.{imp.name}")
    imports.setdefault(imp.module, {})[imp.name] = fn

inst = _cx.Instance(imports)
box["i"] = inst
rp = getattr(inst, "demo:cx/app@0.1.0#run-all")()
mem = getattr(inst, "memory$0")
ptr, ln = struct.unpack_from("<II", mem, rp)
print(bytes(mem[ptr : ptr + ln]).decode())
print("resource new/rep/drop:", counter["new"], counter["rep"], counter["drop"])
