//! The guest of the conformance experiment for wasi:http: it runs a script of requests and prints one line for each, in the form that `ours_http.py` prints too.
use wasi::http::outgoing_handler;
use wasi::http::types::{Fields, IncomingBody, Method, OutgoingBody, OutgoingRequest, RequestOptions, Scheme};

fn name_of<T: std::fmt::Debug>(e: &T) -> String {
    let s = format!("{:?}", e);
    let s = s.rsplit("::").next().unwrap().to_string(); // the Debug is `ErrorCode::ConnectionRefused(..)` or similar
    s.chars().take_while(|c| c.is_alphanumeric() || *c == '-').collect::<String>().to_lowercase().replace('-', "")
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{:02x}", x)).collect()
}

fn fields(entries: &[(String, Vec<u8>)]) -> Fields {
    let mut v = vec![];
    for (n, x) in entries {
        v.push((n.clone(), x.clone()));
    }
    Fields::from_list(&v).expect("fields")
}

fn show(f: &Fields) -> String {
    let mut v: Vec<String> = f
        .entries()
        .into_iter()
        .map(|(n, x)| format!("{}:{}", n, String::from_utf8_lossy(&x)))
        .filter(|s| !s.starts_with("date:") && !s.starts_with("server:"))
        .collect();
    v.sort();
    v.join(",")
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let script = std::fs::read_to_string(&args[1]).expect("script");
    let mut n = 0;
    for line in script.lines() {
        let line = line.split("#~").next().unwrap().trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        n += 1;
        let t: Vec<&str> = line.split_whitespace().collect();
        assert_eq!(t[0], "req");
        let method = match t[1] {
            "GET" => Method::Get,
            "HEAD" => Method::Head,
            "POST" => Method::Post,
            "PUT" => Method::Put,
            "DELETE" => Method::Delete,
            other => Method::Other(other.to_string()),
        };
        let mut headers = vec![];
        let mut trailers = None;
        let mut body = None;
        let mut first = None;
        for opt in &t[4..] {
            if let Some(v) = opt.strip_prefix("body=") {
                body = Some(v.replace("\\n", "\n").into_bytes());
            } else if let Some(v) = opt.strip_prefix("h:") {
                let (k, x) = v.split_once('=').unwrap();
                headers.push((k.to_string(), x.as_bytes().to_vec()));
            } else if let Some(v) = opt.strip_prefix("tr:") {
                let (k, x) = v.split_once('=').unwrap();
                trailers.get_or_insert_with(Vec::new).push((k.to_string(), x.as_bytes().to_vec()));
            } else if let Some(v) = opt.strip_prefix("first=") {
                first = Some(v.parse::<u64>().unwrap());
            }
        }
        let req = OutgoingRequest::new(fields(&headers));
        req.set_method(&method).unwrap();
        req.set_scheme(Some(&Scheme::Http)).unwrap();
        req.set_authority(Some(t[2])).unwrap();
        req.set_path_with_query(Some(t[3])).unwrap();
        if body.is_some() || trailers.is_some() {
            let ob = req.body().unwrap();
            if let Some(b) = &body {
                let s = ob.write().unwrap();
                s.blocking_write_and_flush(b).unwrap();
                drop(s);
            }
            let tf = trailers.as_ref().map(|x| fields(x));
            OutgoingBody::finish(ob, tf).unwrap();
        }
        let opts = first.map(|ms| {
            let o = RequestOptions::new();
            o.set_first_byte_timeout(Some(ms * 1_000_000)).unwrap();
            o
        });
        let result: String = match outgoing_handler::handle(req, opts) {
            Err(e) => format!("err={}", name_of(&e)),
            Ok(fut) => {
                fut.subscribe().block();
                match fut.get().unwrap().unwrap() {
                    Err(e) => format!("err={}", name_of(&e)),
                    Ok(resp) => {
                        let status = resp.status();
                        let h = show(&resp.headers());
                        let body = resp.consume().unwrap();
                        let stream = body.stream().unwrap();
                        let mut data = vec![];
                        while let Ok(chunk) = stream.blocking_read(4096) {
                            data.extend(chunk);
                        }
                        drop(stream);
                        let ft = IncomingBody::finish(body);
                        ft.subscribe().block();
                        let tr = match ft.get().unwrap().unwrap() {
                            Ok(Some(f)) => show(&f),
                            Ok(None) => "none".into(),
                            Err(e) => format!("err={}", name_of(&e)),
                        };
                        format!("status={} h=[{}] body={} trailers={}", status, h, hex(&data), tr)
                    }
                }
            }
        };
        println!("{n} req: {result}");
    }
}
