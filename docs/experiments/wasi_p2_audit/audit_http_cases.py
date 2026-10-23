"""The table `CASES` of wasi_p2_http (the payloads of `error-code`) against the WIT (stable.json): names, order and the shape of each payload.
Run in this directory with stable.json beside it."""
import json, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))
from wasmext.p2.wasi_p2_http import CASES

wit = json.load(open("stable.json")); T = wit["types"]
def leaf(t):
    if isinstance(t, str): return t
    d = T[t]; (kind, v), = d["kind"].items()
    assert kind == "option", kind
    return {"u8": "n8", "u16": "n16", "u32": "n32", "u64": "n64", "string": "str"}[v]
(variant,) = [t for t in T if isinstance(t["kind"], dict) and "variant" in t["kind"] and t["name"] == "error-code"]
bad = 0
cases = variant["kind"]["variant"]["cases"]
assert len(cases) == len(CASES), (len(cases), len(CASES))
for c, (name, outer, kinds) in zip(cases, CASES):
    t = c["type"]; got_outer, got = False, []
    if t is not None:
        d = T[t] if not isinstance(t, str) else None
        (kind, v), = d["kind"].items()
        if kind == "option":                      # option<u64>, option<u32>, option<string>, option<record>
            inner = v; di = T[inner] if not isinstance(inner, str) else None
            if di is not None and "record" in di["kind"]:
                got_outer, got = True, [leaf(f["type"]) for f in di["kind"]["record"]["fields"]]
            else:
                got = [{"u32": "n32", "u64": "n64", "string": "str"}[inner]]
        elif kind == "record":
            got = [leaf(f["type"]) for f in v["fields"]]
        else: raise ValueError(kind)
    if c["name"] != name or got_outer != outer or tuple(got) != kinds:
        print("DIFFERENT", c["name"], name, got_outer, got, outer, kinds); bad += 1
print(f"{len(cases)} cases of error-code, {bad} different")
