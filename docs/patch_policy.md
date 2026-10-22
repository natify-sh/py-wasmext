# How wasmext changes what wasm2c gives it

wasmext does not carry a copy of WABT. It takes `wasm2c` and its runtime from the `wabt-package` and changes what it needs on the way, in three ways: a **wrapper** of a runtime file
(`_RUNTIME_WRAPPERS` in `src/wasmext/_natify.py`: a macro, an `#include` around the original), a **repair of the generated C** (a regular expression, as `_TAIL_CALL_LOCALS` and
`_MSVC_ADDCARRY`), and **macros and flags on the command line** (`WASMEXT_PY_CHAIN`, `WASM_RT_USE_MMAP`, `-z now`). All of them are patches, and WABT moves slowly and without
warning, so they follow the same policy. (No `.patch` files and no vendored copy of WABT for now: that is a decision, not an omission.)

1. **Small and exact.** One patch, one cause. It changes the least that the cause needs, and nothing for "while we are here".
2. **Outside first.** What can be done outside the files of WABT (a wrapper, a macro, the glue of wasmext) is done there; a repair of generated C only where nothing else reaches.
3. **It matches only the known shape.** A regular expression matches the broken text and nothing else, so that a WABT that is fixed passes through untouched and one that changed
   fails to match instead of matching something else.
4. **It states what breaks without it, and a test proves it.** A comment at the patch says the cause (and the WABT issue, if it is reported); a test fails when the patch is taken
   off. This is how a patch that became useless is found, and how a patch that stopped working is.
5. **It fails loudly.** A patch that does not apply, or an assumption about the runtime that no longer holds, must stop the build or a test, not leave a quieter, different behaviour.
   (The chain of handlers assumes that the runtime calls `sigaction` by that name; `tests/test_two_modules.py` fails if it does not.)
6. **Tied to the version.** The patches are written for the WABT in `uv.lock`/the minimum in `pyproject.toml`; a new version of WABT is a reason to run the tests, and the table of
   the issues in [wasm2c_limits.md](wasm2c_limits.md) is where each one is followed.
7. **Upstream when it can be.** A defect of WABT is reported with a small reproducer; a patch that WABT takes is removed here when the minimum version has it.
