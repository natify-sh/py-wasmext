use wasip2::http::outgoing_handler;
use wasip2::http::types::{Fields, Method, OutgoingRequest, Scheme};

fn main() {
    let authority = std::env::args().nth(1).expect("authority");
    let path = std::env::args().nth(2).unwrap_or_else(|| "/".to_string());
    let req = OutgoingRequest::new(Fields::new());
    req.set_method(&Method::Get).unwrap();
    req.set_scheme(Some(&Scheme::Http)).unwrap();
    req.set_authority(Some(&authority)).unwrap();
    req.set_path_with_query(Some(&path)).unwrap();
    let fut = match outgoing_handler::handle(req, None) {
        Ok(f) => f,
        Err(e) => {
            println!("handle error: {e:?}");
            std::process::exit(3);
        }
    };
    fut.subscribe().block();
    let resp = match fut.get() {
        Some(Ok(Ok(r))) => r,
        other => {
            println!("response error: {:?}", other.map(|r| r.map(|_| ())));
            std::process::exit(4);
        }
    };
    println!("status={}", resp.status());
    let body = resp.consume().unwrap();
    let stream = body.stream().unwrap();
    let mut data = Vec::new();
    loop {
        match stream.blocking_read(4096) {
            Ok(chunk) => data.extend_from_slice(&chunk),
            Err(_) => break,
        }
    }
    println!("body={}", String::from_utf8_lossy(&data));
}
