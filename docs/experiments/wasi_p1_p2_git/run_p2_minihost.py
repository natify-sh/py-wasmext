"""wasip2 git.git on the host of examples/wasi2_unbundled plus the smallest additions; which imports the program calls."""
import io, os, struct, sys, importlib, collections
sys.path.insert(0, "."); sys.path.insert(0, "/home/user/py-wasmext/examples/wasi2_unbundled/src")
from wasi2demo.host import Host
from wasmext import parse

class Exit(Exception):
    def __init__(self, code): self.code = code

class Mini(Host):
    def __init__(self, args, env, **kw):
        super().__init__(**kw); self.args, self.env = args, env
    def _str_list(self, items, result, pair=False):
        size = 16 if pair else 8
        base = self._instance.cabi_realloc(0, 0, 4, max(size * len(items), 1))
        for k, it in enumerate(items):
            for j, s in enumerate(it if pair else (it,)):
                b = s.encode(); p = self._instance.cabi_realloc(0, 0, 1, max(len(b), 1)); self._memory()[p:p+len(b)] = b
                self._u32(base + k * size + 8 * j, p); self._u32(base + k * size + 8 * j + 4, len(b))
        self._u32(result, base); self._u32(result + 4, len(items))
    def get_arguments(self, result): self._str_list(self.args, result)
    def get_environment(self, result): self._str_list(list(self.env.items()), result, pair=True)
    def exit_(self, status): raise Exit(status)
    def exit_code(self, code): raise Exit(code)
    def get_directories(self, result): self._u32(result, 4); self._u32(result + 4, 0)   # an empty list
    def random_bytes(self, n, result):
        b = os.urandom(n); p = self._instance.cabi_realloc(0, 0, 1, max(n, 1)); self._memory()[p:p+n] = b
        self._u32(result, p); self._u32(result + 4, n)

def run(name, wasm, args):
    m = importlib.import_module(name)
    out, err = io.BytesIO(), io.BytesIO()
    host = Mini(args, {"GIT_AUTHOR_NAME": "T"}, stdout=out, stderr=err)
    given = host.imports()
    extra = {("wasi:cli/environment", "get-arguments"): host.get_arguments, ("wasi:cli/environment", "get-environment"): host.get_environment,
             ("wasi:cli/exit", "exit"): host.exit_, ("wasi:cli/exit", "exit-with-code"): host.exit_code,
             ("wasi:filesystem/preopens", "get-directories"): host.get_directories, ("wasi:random/random", "get-random-bytes"): host.random_bytes}
    calls = collections.Counter(); wrote = []; order = []
    def rec(n, f):
        def w(*a):
            calls[n] += 1; order.append((n, a))
            return f(*a)
        return w
    def refuse(n):
        def w(*a):
            calls[n] += 1; raise NotImplementedError(n)
        return w
    imports = {}
    for i in parse(open(wasm, "rb").read()).imports:
        mod = imports.setdefault(i.module, {})
        key = (i.module.split("@")[0], i.name)
        f = extra.get(key) or given.get(i.module, {}).get(i.name)
        if f is None and i.name.startswith("[resource-drop]"): f = host.drop
        mod[i.name] = rec(f"{key[0].split(':')[1]}.{i.name}", f) if f else refuse(f"{key[0].split(':')[1]}.{i.name}")
    inst = m.Instance(imports); host.bind(inst)
    try:
        r = getattr(inst, "wasi:cli/run@0.2.12#run")(); how = f"returned {r}"
    except Exit as e: how = f"exit({e.code})"
    except NotImplementedError as e: how = f"STOPPED at {e}"
    except Exception as e: how = f"{type(e).__name__}: {e}"; print("     order of the calls before it:", order)
    print(f"  git {' '.join(args[1:]) or ''}: {how}; output {out.getvalue()[:60]!r} {err.getvalue()[:70]!r}")
    print(f"     {len(calls)} different imports called: {sorted(calls)}")

name, wasm = sys.argv[1], sys.argv[2]
for a in (["git", "--version"], ["git", "-C", "/", "--no-pager", "init", "-q", "."]):
    run(name, wasm, a)
