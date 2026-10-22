"""Patch the generated Python layer (<name>_py.c) of an extension for the experiment: master `patch.py master FILE`, slave `patch.py slave FILE`."""

import re
import sys

role, path = sys.argv[1:3]
with open(path) as f:
    s = f.read()
if role == "master":
    s = s.replace("PyMODINIT_FUNC PyInit_", '#include "shared_rt.h"\nPyMODINIT_FUNC PyInit_', 1)
    at = s.index(
        "PyMODINIT_FUNC PyInit_"
    )  # the same line is in the function that sets a thread up: the one in PyInit is meant
    old = "    wasmext_py_ready_ = 1;\n"
    assert old in s[at:]
    s = s[:at] + s[at:].replace(old, old + "    if (rt_master_publish() < 0) return NULL;\n", 1)
elif role == "one":  # a module that takes part in the one handler of the process
    s = s.replace("PyMODINIT_FUNC PyInit_", '#include "one_handler.h"\nPyMODINIT_FUNC PyInit_', 1)
    at = s.index("PyMODINIT_FUNC PyInit_")
    old = "    if (attach_traps() < 0) return NULL;"
    assert old in s[at:]
    s = s[:at] + s[at:].replace(old, old + "\n    if (one_handler_install() < 0) return NULL;", 1)
elif (
    role == "chain"
):  # no capsule: the entry marks that a call of this module is running, and the handler is a link of a chain
    s = s.replace("PyMODINIT_FUNC PyInit_", '#include "chain_handler.h"\nPyMODINIT_FUNC PyInit_', 1)
    at = s.index("PyMODINIT_FUNC PyInit_")
    old = "    wasm_rt_init();"
    assert old in s[at:]
    s = s[:at] + s[at:].replace(old, old + "\n    if (chain_install() < 0) return NULL;", 1)
    glue = path.replace("_py.c", "_glue.h")
    with open(glue) as f:
        g = f.read()
    g, n = re.subn(
        r"#define WASMEXT_ENTER\(CODE, FAIL\) WASMEXT_THREAD_READY\(\); WASMEXT_ENTER_(\w+)\(CODE, FAIL\)\n#define WASMEXT_LEAVE\(\) WASMEXT_LEAVE_(\w+)\(\)",
        "static WASM_RT_THREAD_LOCAL int chain_active_;  /* 1 while a call of this module is running in this thread */\n"
        "#define WASMEXT_ENTER(CODE, FAIL) int chain_saved_ = chain_active_; chain_active_ = 1; WASMEXT_THREAD_READY(); WASMEXT_ENTER_\\1(CODE, { chain_active_ = chain_saved_; FAIL; })\n"
        "#define WASMEXT_LEAVE() chain_active_ = chain_saved_; WASMEXT_LEAVE_\\2()",
        g,
    )
    assert n == 1, n
    with open(glue, "w") as f:
        f.write(g)
elif role == "plain":  # untouched: a module with the default runtime, which installs a handler of its own
    pass
elif role == "dual":
    s = s.replace("PyMODINIT_FUNC PyInit_", '#define RT_DUAL 1\n#include "shared_rt.h"\nPyMODINIT_FUNC PyInit_', 1)
    at = s.index("PyMODINIT_FUNC PyInit_")
    old = "    wasm_rt_init();"
    assert old in s[at:]
    s = s[:at] + s[at:].replace(old, "    if (rt_dual_start() < 0) return NULL;\n" + old, 1)
    old = "    wasmext_py_ready_ = 1;\n"
    at = s.index("PyMODINIT_FUNC PyInit_")
    assert old in s[at:]
    s = s[:at] + s[at:].replace(old, old + "    if (rt_dual_publish() < 0) return NULL;\n", 1)
else:
    s = s.replace("PyMODINIT_FUNC PyInit_", '#define RT_SLAVE 1\n#include "shared_rt.h"\nPyMODINIT_FUNC PyInit_', 1)
    at = s.index("PyMODINIT_FUNC PyInit_")
    old = "    wasm_rt_init();"
    assert old in s[at:]
    s = s[:at] + s[at:].replace(old, "    if (rt_slave_attach() < 0) return NULL;\n" + old, 1)
with open(path, "w") as f:
    f.write(s)
