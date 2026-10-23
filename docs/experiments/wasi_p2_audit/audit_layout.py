import json
wit = json.load(open("stable.json")); T = wit["types"]
P = {"bool":(1,1),"u8":(1,1),"s8":(1,1),"u16":(2,2),"s16":(2,2),"u32":(4,4),"s32":(4,4),"char":(4,4),"u64":(8,8),"s64":(8,8),"f32":(4,4),"f64":(8,8)}
al = lambda n,a:(n+a-1)//a*a
def lay(t):
    """(size, align, description with offsets)"""
    if isinstance(t,str):
        return (8,4,"string{ptr@0,len@4}") if t=="string" else (*P[t],t)
    d=T[t];k=d["kind"]
    if isinstance(k,str): return (4,4,"own/resource")
    (kind,v),=k.items()
    if kind=="type": return lay(v)
    if kind=="handle": return (4,4,"handle")
    if kind=="list": return (8,4,"list{ptr@0,len@4}")
    if kind in("record","tuple"):
        fs=[(f["name"],f["type"]) for f in v["fields"]] if kind=="record" else [(str(i),x) for i,x in enumerate(v["types"])]
        off=0;al_=1;parts=[]
        for n,x in fs:
            s,a,_=lay(x);off=al(off,a);parts.append(f"{n}@{off}");off+=s;al_=max(al_,a)
        return (al(off,al_),al_,"{"+",".join(parts)+"}")
    if kind=="flags":
        n=len(v["flags"]);s=1 if n<=8 else 2 if n<=16 else 4*((n+31)//32);return (s,min(s,4),f"flags{n}")
    if kind=="enum":
        n=len(v["cases"]);s=1 if n<=256 else 2;return (s,s,f"enum{n}")
    if kind in("option","result","variant"):
        cs=[None,v] if kind=="option" else [v["ok"],v["err"]] if kind=="result" else [c["type"] for c in v["cases"]]
        disc=1 if len(cs)<=256 else 2
        a=max([disc]+[lay(c)[1] for c in cs if c is not None])
        pay=max([0]+[lay(c)[0] for c in cs if c is not None])
        po=al(disc,a)
        return (al(po+pay,a),a,f"{kind}{{tag@0,payload@{po}}}")
    raise ValueError(kind)
seen={}
for x in wit["interfaces"]:
    pk=wit["packages"][x["package"]]["name"].split(":")[1].split("@")[0]
    if pk not in("filesystem","io","cli","clocks","random"): continue
    for fn,f in x["functions"].items():
        r=f.get("result")
        if r is None: continue
        s,a,d=lay(r)
        key=(s,a,d)
        seen.setdefault(key,[]).append(f"{x['name']}.{fn}")
for (s,a,d),fs in sorted(seen.items(), key=lambda kv:-kv[0][0]):
    print(f"size {s:3} align {a} {d}  <- {', '.join(fs[:3])}{' ...' if len(fs)>3 else ''}")
# the inner offsets that the code relies on
for name in ("descriptor-stat","metadata-hash-value","directory-entry","datetime"):
    for i,t in enumerate(T):
        if t["name"]==name and t["kind"]!="resource": print(name,lay(i))
