# JSLinux (x86-64 Linux in wasm) built with wasmext and compared with other engines

Date: 2026-11-13 to 2026-11-16, one cloud container (Xeon 2.3 GHz, Linux, CPython 3.11, gcc). Everything below was run once on that machine; nothing here is in CI.

**Question (the maintainer):** can the x86-64 build of Bellard's JSLinux (TinyEMU compiled with Emscripten, closed source) be taken by `wasmext natify` and run from Python, and how fast is the emulated machine against other engines and against the native machine?

**Answer:** yes. The module is natified unchanged except for one patch of its memory limits (below); Alpine Linux 6.19.3 boots to a shell prompt in about 3 s and runs a static x86-64 CoreMark.

## The module and what it needs from the host

`x86_64emu-wasm.wasm` (1.5 MB) is not in this repository (Bellard's, no licence to redistribute): fetch `https://bellard.org/jslinux/x86_64emu-wasm.wasm` together with `x86_64emu-wasm.js` (read it for the semantics of the imports) and the kernel named in `alpine-x86_64.cfg`. The guest root file system is fetched over HTTP from `vfsync.org` (GET only; `jsl_host.py` refuses every other method, so nothing is uploaded).

* 27 imports of the module `a`, minified (`a.a` .. `a.A`): the names and what they are are in `NAMES` of `jsl_host.py` (assert_fail, exit, file_buffer_*, random, async_call, date_now, console_write, fd_write, clock_time_get, ...).
* Exports used: `C` (constructors), `D` (console_queue_char), `L` (vm_start with 7 arguments: url, RAM in MB, cmdline, pwd, width, height, net), `M` free, `N` malloc, `O` (fs_import_file; the callee frees the buffer), `B` the memory, `G` the table (the callbacks of timers and downloads are called through it).
* The host (`jsl_host.py`) replaces `jslinux.js`: the timers that drive the emulator (`async_call`), the downloads (`wget3_data`: config, kernel, files of the root file system, cached in `JSL_CACHE`), the console. Without an answer to the cursor query `ESC[6n` the shell prompt is never recognised: the host answers `ESC[1;1R`.

## How it was built (the commands are reconstructed; the build directory is gone)

1. Raise the initial memory so that 256 MiB of guest RAM fits without growing it (**wasmext has no memory-grow API from Python**, and the module asks for growth through `resize_heap`, which the host answers "yes" only when the size already fits):
   `wasm-tools print x86_64emu-wasm.wasm`, change `(memory (;0;) 1024 32768)` to `(memory (;0;) 6144 32768)`, `wasm-tools parse` back to `x86_64emu_big.wasm`.
2. `wasmext natify -b -i x86_64emu.wasm` (the generated C was 27 MB in 12 parts; the abi3 extension 42 MB). The build used the repository's defaults (`WASMEXT_CHAIN`, `WASMEXT_STACK_LIMIT`).
3. For wasm3 (through wasmhost) the module needs two trampolines, because that backend gives no table access: exports `ci1(idx, arg)` and `ci4(idx, a, b, c, d)` that `call_indirect` through the table (+61 bytes). Add them in the WAT, as two functions of types `(i32) -> ()` and `(i32 i32 i32 i32) -> ()`.
4. `run_vm.py --engine wasmext|wasmtime|jsc|wasm3 --stage boot|info|coremark`. The constants at its top (`CFG`, `BUILD`, `WASM`, `WASM_CI`) are paths of the original machine: edit them. `jsc` and `wasm3` go through wasmhost (`WASMHOST_BACKEND=wasm3`; `JSC_useJIT=false` for JavaScriptCore without its JIT).

CoreMark inside the guest: a static x86-64 binary built from github.com/eembc/coremark (`make PORT_DIR=linux ... LFLAGS_END=-static`), run as `~/coremark 0x0 0x0 0x66 N 7 1 2000` (explicit iteration count, no calibration). A run is valid only for at least 10 s of the **guest** clock. The binary is taken into the guest with the module's `fs_import_file` (`O`).

## Results (iterations per second by the **host** clock; the guest clock disagreed on JSC and wasm3)

Native, same static binary, same container: **31,529** (31,309 / 31,407 / 31,870).

| engine | CoreMark it/s | slower than native | boot to the prompt |
|---|---:|---:|---:|
| wasmtime-py (Cranelift) | 413.1 (398.9 / 423.1 / 417.4) | 76x | 3.2-3.3 s (+1.0-1.15 s of compilation) |
| **wasmext** (wasm2c, AOT, gcc -O2) | 375.1 (375.0 / 375.1) | 84x | 3.0-3.3 s |
| wasm3 (pywasm3 0.9.1.dev75, interpreter) | 42.9 (42.8 / 43.1 / 42.9) | 735x | 19.9-21.4 s |
| JavaScriptCore without JIT (WebKitGTK 2.52.6 through wasmhost) | 10.9 (10.9 / 10.9) | ~2900x | 67-68 s |

The raw logs are in `logs/`. The guest reports AVX-512 and APX flags: they are emulated; the 76-84x is the price of emulating an x86-64 CPU in software, not of wasm as such (a guest instruction takes tens of host instructions). wasmext is about 10% behind wasmtime here and does not pay the 1 s compile; wasm3 is 9.6x behind wasmtime and 3.9x ahead of JSC without JIT.

**Discarded and why** (so nobody repeats it): an early "23.67 it/s" on wasmtime was an artefact of a `__DONE__` marker missed when the output had no trailing newline; the 120 s timeout of the wait was what had been measured.

## Traps met

* wasmtime memoryview: assigning a slice needs `.cast("B")`.
* the prompt regex must see the text after stripping ANSI; the shell asks the cursor position first.
* `inst["G"].get(idx)(*a)` calls a table entry from Python on wasmext; `inst.B` is the memory as a buffer; `inst.N`/`inst.M` are callable. Host functions take positional ints.
* The module imports `abort_js` and `assert_fail`: both raise in the host (`jsl_host.py`).
* Do not run `cmake`/`ninja` in a cloned third-party tree: the sandbox classifier denied it once; build out of tree with plain `gcc`.
