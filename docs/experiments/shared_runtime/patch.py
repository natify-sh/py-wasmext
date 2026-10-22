"""Patch the generated Python layer (<name>_py.c) of an extension for the experiment: master `patch.py master FILE`, slave `patch.py slave FILE`."""

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
