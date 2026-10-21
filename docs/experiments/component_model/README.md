# Sources of the experiments of the first report in docs/WASI_COMPONENTS.md

The code of the experiments, taken out of the text of the report so that the document does not carry it, **as it was written**. Not part of the package, not built or
tested by the CI, excluded from `ruff`. The runs were not repeated unless the document says so.

| File | What it is | Part of the document |
| --- | --- | --- |
| `demo.wit` | the WIT of the experiment: the interfaces `host`, `api`, `inspect`, and the worlds `guest` and `provider` | "Host functions between two modules" |
| `guest_impl.c`, `provider_impl.c` | the guest and the provider over the bindings of `wit-bindgen c` | the same |
| `run.py` | the three ways of joining them: `direct`, `adapter` (Python), `wasm-adapter` | the same |
| `adapter.wat` | the adapter of the third way, in wasm, with two memories | the same |
| `commands.sh` | the commands in the order of the report (not a script to run as it is) | the same, and "To repeat it" |
| `pyext_Cargo.toml`, `aot_Cargo.toml`, `aot_main.rs`, `onefile_lib.rs`, `greeter_usage.py`, `cross_aot.sh` | the minimal Wasmtime as a PyO3 extension, the AOT tool, the one-file form, the cross-AOT loop | "A cut-down Wasmtime" |
