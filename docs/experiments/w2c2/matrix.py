"""Translate modules with w2c2 and compile the C it writes: python matrix.py W2C2 WAT2WASM W2C2_DIR OUT_DIR MODULE...
(each module is a .wasm or a .wat; a .wat is made a .wasm with `wat2wasm --enable-all` first). Prints one row of a table for each."""
import os
import re
import subprocess
import sys
import time

w2c2, wat2wasm, w2c2_dir, out = sys.argv[1:5]
os.makedirs(out, exist_ok=True)
print("| Module | Size | w2c2 | C compiler | Note |\n| --- | ---: | --- | --- | --- |")
for path in sys.argv[5:]:
    name = re.sub(r"[^A-Za-z0-9_]", "_", os.path.relpath(path)[-40:].rsplit(".", 1)[0])
    wasm = path
    if path.endswith(".wat"):
        wasm = f"{out}/{name}.wasm"
        r = subprocess.run([wat2wasm, "--enable-all", path, "-o", wasm], capture_output=True, text=True, check=False)
        if r.returncode:
            print(f"| `{os.path.basename(path)}` | - | not tried | - | wat2wasm refused: {r.stderr.strip().splitlines()[0][:70] if r.stderr.strip() else r.returncode} |")
            continue
    size = os.path.getsize(wasm)
    c = f"{out}/{name}.c"
    t0 = time.time()
    r = subprocess.run([w2c2, wasm, c], capture_output=True, text=True, check=False, timeout=600)
    note = (r.stderr + r.stdout).strip().splitlines()
    if r.returncode != 0 or not os.path.exists(c):
        print(f"| `{os.path.basename(path)}` | {size:,} | **FAILS** ({r.returncode}) | - | {note[-1][:100] if note else ''} |")
        continue
    t_translate = time.time() - t0
    cc = subprocess.run(["gcc", "-c", "-w", "-O0", "-DWASM_THREADS_PTHREADS", f"-I{w2c2_dir}", c, "-o", f"{out}/{name}.o"], capture_output=True, text=True, check=False, timeout=900)
    errs = [x for x in cc.stderr.splitlines() if "error" in x]
    verdict = "ok" if cc.returncode == 0 else f"**{len(errs)} errors**"
    why = "" if cc.returncode == 0 else (errs[0].split("error:")[-1].strip()[:90] if errs else "")
    print(f"| `{os.path.basename(path)}` | {size:,} | ok ({t_translate:.1f} s) | {verdict} | {why or (note[0][:90] if note else '')} |")
