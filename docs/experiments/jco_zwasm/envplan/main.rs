//! Dump the instantiation plan wasmtime-environ makes for a component (the same data jco turns into JS):
//! core modules (original and FACT adapter), the flat list of initializers, and the builtins (trampolines) needed.
use std::collections::BTreeMap;
use wasmtime_environ::wasmparser::{Validator, WasmFeatures};
use wasmtime_environ::component::{ComponentTypesBuilder, GlobalInitializer, Translator};
use wasmtime_environ::{ScopeVec, Tunables};

fn main() -> anyhow::Result<()> {
    let path = std::env::args().nth(1).expect("component.wasm");
    let out_dir = std::env::args().nth(2);
    let bytes = std::fs::read(&path)?;
    let tunables = Tunables::default_host();
    let mut validator = Validator::new_with_features(WasmFeatures::all());
    let mut types = ComponentTypesBuilder::new(&validator);
    let scope = ScopeVec::new();
    let (tr, modules) = Translator::new(&tunables, &mut validator, &mut types, &scope).translate(&bytes).map_err(|e| anyhow::anyhow!("{e:?}"))?;
    println!("core modules: {}", modules.len());
    for (i, m) in modules.iter() {
        let n = m.wasm.len();
        println!("  module {:?}: {} bytes, {} imports, {} exports", i, n, m.module.imports().count(), m.module.exports.len());
        if let Some(d) = &out_dir { std::fs::write(format!("{d}/module{}.wasm", i.as_u32()), m.wasm)?; }
    }
    let mut kinds: BTreeMap<&str, usize> = BTreeMap::new();
    for init in &tr.component.initializers {
        let k = match init {
            GlobalInitializer::InstantiateModule(..) => "InstantiateModule",
            GlobalInitializer::LowerImport { .. } => "LowerImport",
            GlobalInitializer::ExtractMemory(_) => "ExtractMemory",
            GlobalInitializer::ExtractRealloc(_) => "ExtractRealloc",
            GlobalInitializer::ExtractCallback(_) => "ExtractCallback",
            GlobalInitializer::ExtractPostReturn(_) => "ExtractPostReturn",
            GlobalInitializer::ExtractTable(_) => "ExtractTable",
            GlobalInitializer::Resource(_) => "Resource",
        };
        *kinds.entry(k).or_default() += 1;
    }
    println!("initializers: {} {:?}", tr.component.initializers.len(), kinds);
    let mut tk: BTreeMap<String, usize> = BTreeMap::new();
    for (_, t) in tr.trampolines.iter() {
        let name = format!("{t:?}");
        let name = name.split(|c: char| c == '{' || c == '(' || c == ' ').next().unwrap().to_string();
        *tk.entry(name).or_default() += 1;
    }
    println!("trampolines (builtins the host provides): {} {:?}", tr.trampolines.len(), tk);
    println!("imports of the component: {}", tr.component.import_types.len());
    Ok(())
}
