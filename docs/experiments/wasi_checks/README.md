# Checks of 2026-10-21 for docs/WASI_COMPONENTS.md

Small scripts of the checks that were made again, in the session that consolidated the WASI documents, to confirm or to correct what the earlier reports said.
They are references, not tests: they need tools that are not in this repository (wasm-tools, wasi-sdk, wit-bindgen, meld, jco), see "Tools" and "To repeat it" in
[../../WASI_COMPONENTS.md](../../WASI_COMPONENTS.md). Excluded from `ruff` like the rest of `docs/experiments`.

| Path | What it does |
| --- | --- |
| `minimal/demo.wit`, `provider.wat`, `guest.wat` | the smallest two components with a string crossing between them (hand-written WAT, no wasi-sdk): `wasm-tools component embed … && component new` |
| `minimal/run_direct_vs_adapter.py` | the two core modules after `unbundle --threshold 0`, joined directly (wrong: `1`) and through a Python adapter (right: `196`) |
| `fused_simple/run_fused.py` | the composed minimal component fused by `meld fuse`, built with `wasmext natify`, called from Python: `196` |
| `complex_fused/run_cx_fused.py` | the complex component of `../jco_zwasm/complex` fused by meld and called from Python, with the resource functions in Python |
