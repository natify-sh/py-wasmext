# meld 0.65.0 on the complex component (the check of #512 and #513)

**[run]** 2026-10-22, Linux x86-64, meld from the release tarballs of v0.64.0 and v0.65.0 (the sha256 of 0.65.0 was checked against `SHA256SUMS.txt`), wasmtime 50.0.0, wasm-tools 1.262.0, the component built again from `../jco_zwasm/complex` with wasi-sdk 34.0 and wit-bindgen 0.63.0 (`build.sh`).

`wasmtime run --invoke 'run-all()'` on the composed component, then on the output of `meld fuse --component --memory multi`:

| | `get=` in the result |
| --- | --- |
| the composed component, not fused | `get=apple,3,[red,big]` |
| fused by **meld 0.64.0** | `get=apple,3,[,]` (the bug of #512) |
| fused by **meld 0.65.0** | `get=apple,3,[red,big]`, and **the whole string equal to the unfused one** |

**#512 is fixed**, checked here by running (the maintainer's check of the same on `aarch64-apple-darwin` was reported in the issue; this one is on x86-64 Linux and was done on our own build of the component).

**#513 (the import map) is in**, checked on the command-variant composition (`cxcomposed.wasm`, 53 function imports) with `meld fuse --exports world --emit-import-map`: `"version": 2`, each import has `component`, `encoding`, `memory` (`{"index": 1, "export": "memory$0"}`), `realloc` (`{"func": 218, "export": "cabi_realloc$1"}` or `null`), `resource` for resource intrinsics; the fused core module validates. File: `cx.imports.v2.json`. So the glue (`../jco_zwasm/meld/fused_glue.py`, `../wasi_checks/complex_fused/`) no longer has to read the memory off the suffix `$N` and the order of the exports; the glue was **not** changed, and the run of the fused core module through wasm2c and the zwasm host (`libzw_w2c_host.a`, not in this repository) was **not** repeated here: only the fused component was run, on wasmtime.

**A finding that is not fixed in 0.65.0 and not reported yet:** a composed component made of two components that each export `wasi:cli/run` (a program built by wasi-sdk 34 as a command, the default, with no `-mexec-model=reactor`) gives, with `meld fuse --component`, a component that does not validate: `export name 'run$0' is not a valid extern name` (the suffix `$N`, added to tell two exports of one name apart, has `$`, not allowed in a kebab-case name). The same on **0.64.0** and **0.65.0**. The route used in the documents (`--exports world`, a core module) is not affected. Built as reactors the composition fuses and runs, as in the table.
