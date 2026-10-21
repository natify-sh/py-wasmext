static CWASM: &[u8] = include_bytes!("../composed.cwasm");

fn to_val(o: &Bound<PyAny>, t: &Type) -> PyResult<Val> {
    Ok(match t {
        Type::Bool => Val::Bool(o.extract()?),
        Type::U32 => Val::U32(o.extract()?), /* … all integer and float types … */
        Type::String => Val::String(o.extract()?),
        Type::List(l) => { let et = l.ty(); Val::List(o.try_iter()?.map(|x| to_val(&x?, &et)).collect::<PyResult<_>>()?) }
        Type::Record(r) => { let d = o.cast::<PyDict>()?; Val::Record(r.fields().map(|f| {
            let v = d.get_item(f.name)?.ok_or_else(|| PyTypeError::new_err(f.name.to_string()))?;
            Ok((f.name.to_string(), to_val(&v, &f.ty)?)) }).collect::<PyResult<_>>()?) }
        Type::Option(op) => Val::Option(if o.is_none() { None } else { Some(Box::new(to_val(o, &op.ty())?)) }),
        _ => return Err(PyTypeError::new_err(format!("type {t:?} not handled in this demo"))),
    })
}
// from_val: the reverse (record → dict, option → None, result: Ok → value, Err → RuntimeError)

#[pyfunction]
fn instance() -> PyResult<Component_> {
    let engine = Engine::default();
    let comp = unsafe { Component::deserialize(&engine, CWASM) }.map_err(err)?;
    let mut linker: Linker<()> = Linker::new(&engine);
    linker.define_unknown_imports_as_traps(&comp).map_err(err)?;
    let mut store = Store::new(&engine, ());
    let inst = linker.instantiate(&mut store, &comp).map_err(err)?;
    Ok(Component_ { store: Mutex::new(store), inst })
}
