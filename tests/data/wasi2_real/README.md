Programs of WASI 0.2 as toolchains make them (see `tests/test_wasi2_programs.py`). `*.wasm` are the core modules that `wasm-tools component unbundle --threshold 0` leaves of the components:

- `prog_c.wasm` from `prog.c`, `net_c.wasm` from `net.c`, `fs2_c.wasm` from `fs2.c`: `wasi-sdk-34/bin/clang --target=wasm32-wasip2 -O1 x.c -o x.component.wasm`;
- `httpc_rs.wasm` from `httpc/main.rs`: a binary crate with `wasip2 = "2"`, `cargo build --release --target wasm32-wasip2` (a client of `wasi:http/outgoing-handler`);
- `prog.rs` is built by the test itself when `rustc` has the `wasm32-wasip2` target.
