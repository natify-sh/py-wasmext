# Sources of the experiments of the second report (jco, meld, zwasm) in docs/WASI_COMPONENTS.md

A reference: the sources that came with the second report, now merged into [WASI_COMPONENTS.md](../../WASI_COMPONENTS.md) (`jco_zwasm_sources.tar.gz`, 13 files), kept **as they were written**. They are not part of the package, are not built or tested by the CI, and are excluded from `ruff` (`extend-exclude` in `pyproject.toml`). The runs were not repeated in the session that added them; they need the tools named in "Tools" and "Flattening a composed component" of the document (wasi-sdk, wasm-tools, wit-bindgen, WABT, meld, Rust with `wasmtime-environ`, and the `w2c_host` prototype of zwasm for the parts that use it, which is **not** in this archive).

| Path | What it is | Part of the report |
| --- | --- | --- |
| `complex/cx.wit` | the WIT of the complex component: `record item`, `variant shape`, `enum level`, `flags perms`, `resource counter`, `result`, `option`, `list` | 0 |
| `complex/guest_impl.c`, `complex/provider_impl.c` | the guest (`app.run-all`) and the provider (`store`) of the complex component, in C, over the bindings of `wit-bindgen c` | 0, 1.2 |
| `envplan/Cargo.toml`, `envplan/main.rs` | the 47 lines of Rust that call `Translator::translate` of `wasmtime-environ` and print the plan (core modules, initializers, trampolines) | 2.2 |
| `meld/fused_glue.py` | the glue (115 lines): from a module fused by meld, makes the C that instantiates it, gives each WASI import to the host, chooses the memory and `cabi_realloc` by the suffix `$N`, keeps the table of resources | 2.1 |
| `meld/fa_main.c`, `meld/fb_main.c` | the mains for the simple and the complex fused components | 2.1 |
| `p3/p3host.c`, `p3/p3host.h` | the minimal host of WASI 0.3 in C (94 lines): waitables, streams, futures, stdio, clocks | 4 |
| `p3/gen_p3.py` | the generator (84 lines) of the imports of a `wasm32-wasip3` core module for that host | 4 |
| `p3/p3test.c`, `p3/h3_main.c` | the test program (`printf`, `usleep`, `fgets`, `stderr`, `time`) and its main | 4 |

The commands that use them are in the report, in the same parts.
