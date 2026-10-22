"""How much a host of WASI 0.2 has to implement: the WIT of the tag v0.2.12 against what was seen in imports and what the hosts here implement.

    python scope.py WIT.json COMPONENT_OR_MODULE.wasm... > table.md

WIT.json: `wasm-tools component wit WIT_DIR --json` (see README.md). Each .wasm is a component (taken apart with `wasm-tools component unbundle --threshold 0`) or a core
module; its imports are the "seen" set. The hosts of examples/wasi2_unbundled and examples/wasi2_python give the "implemented" set.
"""

import collections
import json
import subprocess
import sys
import tempfile

sys.path.insert(0, "/home/user/py-wasmext/examples/wasi2_unbundled/src")
sys.path.insert(0, "/home/user/py-wasmext/examples/wasi2_python/src")
from wasi2demo.host import _METHODS
from wasi2python.nethost import NetHost

from wasmext import parse

with open(sys.argv[1]) as f:
    wit = json.load(f)
packages = [f"{p['name'].split('@')[0]}" for p in wit["packages"]]
interfaces = wit["interfaces"]
iname = {i: f"{packages[x['package']]}/{x['name']}" for i, x in enumerate(interfaces)}

# every import a host must answer for each interface: functions (freestanding, [constructor], [method], [static]) and one [resource-drop] per resource
required = collections.defaultdict(set)
for i, x in enumerate(interfaces):
    for f in x["functions"].values():
        required[iname[i]].add(f["name"])
for t in wit["types"]:
    if t["kind"] == "resource" and "interface" in t["owner"]:
        required[iname[t["owner"]["interface"]]].add(f"[resource-drop]{t['name']}")
# what the program exports and the host does not implement: wasi:cli/run#run, wasi:http/incoming-handler#handle
exported = {("wasi:cli/run", "run"), ("wasi:http/incoming-handler", "handle")}
for module, name in exported:
    required[module].discard(name)

# the imports of the worlds (the interfaces a program of that world may import)
worlds = {}
for w in wit["worlds"]:
    worlds[f"{packages[w['package']]}/{w['name']}"] = sorted(
        {iname[v["interface"]["id"]] for v in w["imports"].values() if isinstance(v, dict) and "interface" in v}
    )

seen = collections.defaultdict(lambda: collections.defaultdict(set))  # program -> interface -> names
for path in sys.argv[2:]:
    with tempfile.TemporaryDirectory() as tmp:
        with open(path, "rb") as f:
            data = f.read()
        if data[4:8] == b"\x0d\x00\x01\x00":  # a component
            subprocess.run(
                [
                    "wasm-tools",
                    "component",
                    "unbundle",
                    path,
                    "--threshold",
                    "0",
                    "--module-dir",
                    tmp,
                    "-o",
                    f"{tmp}/rest.wasm",
                ],
                check=True,
                capture_output=True,
            )
            with open(f"{tmp}/unbundled-module0.wasm", "rb") as f:
                data = f.read()
        for item in parse(data).imports:
            if item.module.startswith("wasi:"):
                seen[path.rsplit("/", 1)[-1]][item.module.split("@")[0]].add(item.name)

base = {(m, n) for (m, n) in _METHODS}
ours = {(m, n) for (m, n) in NetHost([], {}, []).table()} | base
# answered with ok and nothing done (FsHost.ok1)
STUBS = {
    ("wasi:filesystem/types", n)
    for n in (
        "[method]descriptor.advise",
        "[method]descriptor.sync-data",
        "[method]descriptor.sync",
        "[method]descriptor.set-times",
        "[method]descriptor.set-times-at",
    )
}

total = collections.Counter()
union = collections.defaultdict(set)
for prog in seen.values():
    for module, names in prog.items():
        union[module] |= names
print(
    "| Package | Interface | Functions | Resources (drops) | Required | Seen in programs | Implemented here | Stubbed |"
)
print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
rows = []
for module in sorted(required, key=lambda m: (m.split("/")[0], m)):
    names = required[module]
    drops = {n for n in names if n.startswith("[resource-drop]")}
    funcs = names - drops
    s = union.get(module, set()) & names
    stub = {n for n in names if (module, n) in STUBS}
    impl = {n for n in funcs if (module, n) in ours and (module, n) not in STUBS}
    if impl:
        impl |= drops  # the generic host.drop answers a [resource-drop]; counted only where the interface is implemented at all
    rows.append((module, len(funcs), len(drops), len(names), len(s), len(impl), len(stub)))
    print(
        f"| {module.split('/')[0].replace('wasi:', '')} | {module.split('/')[1]} | {len(funcs)} | {len(drops)} | {len(names)} | {len(s)} | {len(impl)} | {len(stub)} |"
    )
by = collections.defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0])
for module, f, d, r, s, i, st in rows:
    p = by[module.split("/")[0]]
    p[0] += 1
    p[1] += f
    p[2] += d
    p[3] += r
    p[4] += s
    p[5] += i
    p[6] += st
print(
    "\n| Package | Interfaces | Functions | Drops | Required | Seen | Implemented | Stubbed |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
)
for p, v in by.items():
    print(f"| {p.replace('wasi:', '')} | " + " | ".join(map(str, v)) + " |")
print("| **all** | " + " | ".join(str(sum(v[k] for v in by.values())) for k in range(7)) + " |")
print("\nRequired and not implemented (functions only; drops are generic):")
for module in sorted(required):
    miss = sorted(
        n
        for n in required[module]
        if not n.startswith("[resource-drop]") and ((module, n) not in ours or (module, n) in STUBS)
    )
    if miss and not module.startswith("wasi:http"):
        print(f"- {module}: {len(miss)}" + (": " + ", ".join(miss) if len(miss) <= 12 else ""))
print("\nWorlds (interfaces imported):")
for name, ifs in worlds.items():
    print(f"- {name}: {len(ifs)} interfaces, {sum(len(required[i]) for i in ifs)} required imports")
print("\nPrograms seen:")
for prog, d in seen.items():
    print(f"- {prog}: {sum(len(v) for v in d.values())} imports in {len(d)} interfaces")

# the part of the CLI world that no program here asked for, and what was asked for and is not implemented
cli = set()
for module in worlds["wasi:cli/command"]:
    cli |= {(module, n) for n in required[module]}
asked = {(m, n) for m, names in union.items() for n in names}
done = {(m, n) for (m, n) in ours if (m, n) not in STUBS} | {
    (m, n) for (m, n) in cli if n.startswith("[resource-drop]")
}
print(
    f"\nCLI world: {len(cli)} imports; asked for by the programs: {len(cli & asked)}; never asked for: {len(cli - asked)}"
)
print(
    f"asked for and not implemented (drops left out): {len([x for x in (cli & asked) if x not in done and not x[1].startswith('[resource-drop]')])}"
)
print(
    f"  of them in wasi:sockets: {len([x for x in (cli & asked) if x not in done and x[0].startswith('wasi:sockets')])}"
)
