// aot/src/main.rs: precompile a component or core module to .cwasm, optionally for another target
fn main() {
    let a: Vec<String> = std::env::args().collect();
    let mut cfg = wasmtime::Config::new();
    if let Some(t) = a.get(3) { cfg.target(t).unwrap(); }
    let engine = wasmtime::Engine::new(&cfg).unwrap();
    let wasm = std::fs::read(&a[1]).unwrap();
    let r = if wasm[4..8] == [1, 0, 0, 0] { engine.precompile_module(&wasm) } else { engine.precompile_component(&wasm) };
    match r { Ok(b) => { std::fs::write(&a[2], b).unwrap(); println!("ok {} bytes", std::fs::metadata(&a[2]).unwrap().len()) }
              Err(e) => println!("error: {e:#}") }
}
