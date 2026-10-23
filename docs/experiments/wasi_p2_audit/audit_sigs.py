"""Expected flat core signatures of every import of WASI 0.2 (Canonical ABI) against the Python and C functions of wasmext.p2 / c/p2."""
import inspect, json, re, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))
from wasmext.p2 import wasi_p2_clocks, wasi_p2_cli, wasi_p2_io, wasi_p2_random, wasi_p2_filesystem

wit = json.load(open("stable.json"))
T = wit["types"]
PRIM = {"bool": ("i32",), "u8": ("i32",), "s8": ("i32",), "u16": ("i32",), "s16": ("i32",), "u32": ("i32",), "s32": ("i32",), "char": ("i32",),
        "u64": ("i64",), "s64": ("i64",), "f32": ("f32",), "f64": ("f64",)}

def flat(t):
    if isinstance(t, str):
        return ["i32", "i32"] if t == "string" else list(PRIM[t])
    d = T[t]; k = d["kind"]
    if isinstance(k, str): return ["i32"]
    (kind, v), = k.items()
    if kind == "type": return flat(v)
    if kind == "handle": return ["i32"]
    if kind == "list": return ["i32", "i32"]
    if kind == "record": return sum((flat(f["type"]) for f in v["fields"]), [])
    if kind == "tuple": return sum((flat(x) for x in v["types"]), [])
    if kind == "flags": return ["i32"]
    if kind == "enum": return ["i32"]
    if kind in ("option", "result", "variant"):
        cases = [None, v] if kind == "option" else [v["ok"], v["err"]] if kind == "result" else [c["type"] for c in v["cases"]]
        out = ["i32"]
        for c in cases:
            if c is None: continue
            for i, f in enumerate(flat(c)):
                if i + 1 >= len(out): out.append(f)
                elif out[i + 1] != f: out[i + 1] = "i32" if {out[i + 1], f} == {"i32", "f32"} else "i64"
        return out
    raise ValueError(kind)

pk = [p["name"] for p in wit["packages"]]
mods = {"clocks": wasi_p2_clocks, "cli": wasi_p2_cli, "io": wasi_p2_io, "random": wasi_p2_random, "filesystem": wasi_p2_filesystem}
csrc = {n: open(__import__("pathlib").Path(__file__).resolve().parents[3] / "src" / "wasmext" / "c" / "p2" / f"wasi_p2_{n}.h").read() for n in mods}
bad = 0; total = 0
def check(pyname, mod, cmod, params_flat, results_flat, uses_mem_hint):
    global bad, total
    total += 1
    fn = getattr(mod, pyname, None)
    if fn is None: print("MISSING python", pyname); bad += 1; return
    n_py = len(inspect.signature(fn).parameters) - 1  # without host
    has_comp = "comp" in inspect.signature(fn).parameters
    expected = len(params_flat) + (1 if len(results_flat) > 1 else 0)  # retptr
    got = n_py - (1 if has_comp else 0)
    if got != expected:
        print(f"ARITY {pyname}: python {got}, expected {expected} ({params_flat}+ret={len(results_flat)>1})"); bad += 1
    m = re.search(r"WASI_P2_FN\s+\w+\s+\**" + pyname + r"\(([^)]*)\)", csrc[cmod])
    if not m: print("MISSING c", pyname); bad += 1; return
    n_c = len([p for p in m.group(1).split(",") if p.strip()]) - 1
    if n_c != n_py: print(f"C/PY ARITY {pyname}: c {n_c}, py {n_py}"); bad += 1
    # returns a value only when the result is flat 1
    ret_py = inspect.signature(fn).return_annotation
    returns = ret_py not in (None, "None", inspect._empty)
    if returns != (len(results_flat) == 1): print(f"RESULT {pyname}: python returns {returns}, flat results {results_flat}"); bad += 1

for i, x in enumerate(wit["interfaces"]):
    pkg = pk[x["package"]].split(":")[1].split("@")[0]
    iname = x["name"]
    if pkg not in mods: continue
    mod = mods[pkg]
    for fname, f in x["functions"].items():
        if "unstable" in f.get("stability", {}) or (iname == "run"): continue
        kind = f["kind"]
        params = []
        if kind != "freestanding" and not (f["params"] and f["params"][0]["name"] == "self"): params.append("i32")  # self
        for p in f["params"]: params += flat(p["type"])
        if len(params) > 16: params = ["i32"]
        res = flat(f["result"]) if f.get("result") is not None else []
        if fname.startswith("[method]"): fn = fname.split(".")[1]; res_name = fname[len("[method]"):].split(".")[0]
        elif fname.startswith("[static]"): fn = fname.split(".")[1]; res_name = fname[len("[static]"):].split(".")[0]
        elif fname.startswith("[constructor]"): res_name = fname[len("[constructor]"):]; fn = "new"
        else: res_name = None; fn = fname
        base = "wasi_" + pkg + "_" + iname.replace("-", "_") + "_" + ((res_name.replace("-", "_") + "_") if res_name else "") + fn.replace("-", "_")
        # the names in the code repeat the interface for clocks/cli: wasi_clocks_wall_clock_now = wasi_<pkg>_<iface>_<fn>
        check(base, mod, pkg, params, res, None)
    for t in wit["types"]:
        if t["kind"] == "resource" and t["owner"] and t["owner"].get("interface") == i:
            base = "wasi_" + pkg + "_" + iname.replace("-", "_") + "_" + t["name"].replace("-", "_") + "_drop"
            total += 1
            if not hasattr(mod, base): print("MISSING drop", base); bad += 1
print(f"checked {total}, problems {bad}")
