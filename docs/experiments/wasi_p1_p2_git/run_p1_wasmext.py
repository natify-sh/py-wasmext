import io, os, sys, importlib, shutil, tempfile, traceback
sys.path.insert(0, ".")
sys.path.insert(0, "/home/user/py-wasmext/examples/wasi2_unbundled/src")
from wasi2demo.host import Host

def p1(repo):
    m = importlib.import_module("rg_p1")
    def git(*args):
        out = []
        inst = m.Instance(wasi={"args": ["git", "-C", "/", "--no-pager", *args], "preopens": {"/": repo},
                                "env": {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x"},
                                "stdout": out.append, "stderr": out.append})
        try:
            inst._start(); code = 0
        except m.WasiExit as e:
            code = e.code
        print(f"  $ git {' '.join(args)} -> exit {code}  {b''.join(out).decode(errors='replace').strip()[:90]!r}")
    git("init", "-q", "-b", "main", ".")
    open(os.path.join(repo, "a.txt"), "w").write("hello\n")
    git("add", "a.txt"); git("commit", "-q", "-m", "first"); git("log", "--oneline"); git("status", "--short")

def p2(name):
    m = importlib.import_module(name)
    out, err = io.BytesIO(), io.BytesIO()
    host = Host(stdout=out, stderr=err)
    imports = host.imports()
    calls = []
    for mod, funcs in imports.items():                 # a recording wrapper over every import
        for fn, f in list(funcs.items()):
            def wrap(*a, _f=f, _n=f"{mod.split('@')[0]}.{fn}"):
                calls.append(_n); return _f(*a)
            funcs[fn] = wrap
    inst = m.Instance(imports); host.bind(inst)
    try:
        r = getattr(inst, "wasi:cli/run@0.2.12#run")(); print(f"  {name}: run returned {r}; imports called: {len(set(calls))}")
    except NotImplementedError as e:
        print(f"  {name}: stops at the first import the host does not write: {e}; imports called before it: {len(set(calls))} {sorted(set(calls))[:6]}")
    except Exception as e:
        print(f"  {name}: {type(e).__name__}: {str(e)[:120]}; called before: {sorted(set(calls))[:8]}")

which = sys.argv[1]
if which == "p1":
    d = tempfile.mkdtemp(); p1(d); shutil.rmtree(d)
else:
    p2(which)
