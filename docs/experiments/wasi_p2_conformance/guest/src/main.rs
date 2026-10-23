//! The guest of the conformance experiment: it runs a script of operations on wasi:filesystem and prints one line for each, in the form that `ours.py` prints too.
use std::collections::HashMap;
use wasi::filesystem::types::{Advice, Descriptor, DescriptorFlags, DescriptorType, ErrorCode, OpenFlags, PathFlags};
use wasi::io::streams::StreamError;

fn kebab(debug: String) -> String {
    let mut out = String::new();
    for (i, c) in debug.chars().enumerate() {
        if c.is_uppercase() {
            if i > 0 {
                out.push('-');
            }
            out.extend(c.to_lowercase());
        } else {
            out.push(c);
        }
    }
    out
}

fn err(e: ErrorCode) -> String {
    // the Debug of the code is `error-code { code: 14, name: "is-directory", message: ... }`
    let s = format!("{:?}", e);
    match s.split("name: \"").nth(1).and_then(|x| x.split('"').next()) {
        Some(name) => format!("err={}", name),
        None => format!("err={}", kebab(s)),
    }
}

fn kind(t: DescriptorType) -> String {
    let s = format!("{:?}", t);
    kebab(s.rsplit("::").next().unwrap().to_string())
}

fn text(s: &str) -> String {
    if s == "''" { String::new() } else { s.replace("\\n", "\n") }
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{:02x}", x)).collect()
}

fn pflags(s: &str) -> PathFlags {
    if s.contains('f') { PathFlags::SYMLINK_FOLLOW } else { PathFlags::empty() }
}

fn oflags(s: &str) -> OpenFlags {
    let mut f = OpenFlags::empty();
    for c in s.chars() {
        match c {
            'c' => f |= OpenFlags::CREATE,
            'd' => f |= OpenFlags::DIRECTORY,
            'e' => f |= OpenFlags::EXCLUSIVE,
            't' => f |= OpenFlags::TRUNCATE,
            _ => {}
        }
    }
    f
}

fn dflags(s: &str) -> DescriptorFlags {
    let mut f = DescriptorFlags::empty();
    for c in s.chars() {
        match c {
            'r' => f |= DescriptorFlags::READ,
            'w' => f |= DescriptorFlags::WRITE,
            'f' => f |= DescriptorFlags::FILE_INTEGRITY_SYNC,
            'd' => f |= DescriptorFlags::DATA_INTEGRITY_SYNC,
            'q' => f |= DescriptorFlags::REQUESTED_WRITE_SYNC,
            'm' => f |= DescriptorFlags::MUTATE_DIRECTORY,
            _ => {}
        }
    }
    f
}

fn flags_text(f: DescriptorFlags) -> String {
    let mut out = String::new();
    for (bit, c) in [
        (DescriptorFlags::READ, 'r'),
        (DescriptorFlags::WRITE, 'w'),
        (DescriptorFlags::FILE_INTEGRITY_SYNC, 'f'),
        (DescriptorFlags::DATA_INTEGRITY_SYNC, 'd'),
        (DescriptorFlags::REQUESTED_WRITE_SYNC, 'q'),
        (DescriptorFlags::MUTATE_DIRECTORY, 'm'),
    ] {
        if f.contains(bit) {
            out.push(c);
        }
    }
    if out.is_empty() { "-".into() } else { out }
}

fn stream_err(e: StreamError) -> String {
    match e {
        StreamError::Closed => "stream-closed".into(),
        StreamError::LastOperationFailed(_) => "stream-failed".into(),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let script = std::fs::read_to_string(&args[1]).expect("script");
    let mut handles: HashMap<String, Descriptor> = HashMap::new();
    let pre = wasi::filesystem::preopens::get_directories();
    let mut n = 0;
    for line in script.lines() {
        let line = line.split("#~").next().unwrap().trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        n += 1;
        let t: Vec<&str> = line.split_whitespace().collect();
        let used: &[usize] = match t[0] {
            "preopen" => &[],
            "open" => &[2],
            "rename" => &[1, 3],
            "link" => &[1, 4],
            "same" => &[1, 2],
            _ => &[1],
        };
        if used.iter().any(|&i| !handles.contains_key(t[i])) {
            println!("{n} {}: no-handle", t[0]);
            continue;
        }
        macro_rules! d {
            ($i:expr) => {
                handles.get(t[$i]).unwrap_or_else(|| panic!("no handle {}", t[$i]))
            };
        }
        let result: String = match t[0] {
            "preopen" => {
                let i: usize = t[2].parse().unwrap();
                let (d, name) = &pre[i];
                let _ = d;
                // a preopen is used by its own handle: ask again to own one
                let fresh = wasi::filesystem::preopens::get_directories().into_iter().nth(i).unwrap().0;
                handles.insert(t[1].to_string(), fresh);
                format!("name={}", name)
            }
            "open" => match d!(2).open_at(pflags(t[4]), &text(t[3]), oflags(t[5]), dflags(t[6])) {
                Ok(x) => {
                    handles.insert(t[1].to_string(), x);
                    "ok".into()
                }
                Err(e) => err(e),
            },
            "stat" => match d!(1).stat() {
                Ok(s) => format!("type={} size={} links={}", kind(s.type_), s.size, s.link_count),
                Err(e) => err(e),
            },
            "stat-at" => match d!(1).stat_at(pflags(t[2]), &text(t[3])) {
                Ok(s) => format!("type={} size={} links={}", kind(s.type_), s.size, s.link_count),
                Err(e) => err(e),
            },
            "type" => match d!(1).get_type() {
                Ok(k) => kind(k),
                Err(e) => err(e),
            },
            "flags" => match d!(1).get_flags() {
                Ok(f) => flags_text(f),
                Err(e) => err(e),
            },
            "read" => match d!(1).read(t[3].parse().unwrap(), t[2].parse().unwrap()) {
                Ok((b, eof)) => format!("{} eof={}", hex(&b), eof),
                Err(e) => err(e),
            },
            "write" => match d!(1).write(text(t[3]).as_bytes(), t[2].parse().unwrap()) {
                Ok(k) => format!("written={}", k),
                Err(e) => err(e),
            },
            "read-stream" => match d!(1).read_via_stream(t[2].parse().unwrap()) {
                Ok(s) => match s.blocking_read(t[3].parse().unwrap()) {
                    Ok(b) => hex(&b),
                    Err(e) => stream_err(e),
                },
                Err(e) => err(e),
            },
            "write-stream" => match d!(1).write_via_stream(t[2].parse().unwrap()) {
                Ok(s) => match s.blocking_write_and_flush(text(t[3]).as_bytes()) {
                    Ok(()) => "ok".into(),
                    Err(e) => stream_err(e),
                },
                Err(e) => err(e),
            },
            "append-stream" => match d!(1).append_via_stream() {
                Ok(s) => match s.blocking_write_and_flush(text(t[2]).as_bytes()) {
                    Ok(()) => "ok".into(),
                    Err(e) => stream_err(e),
                },
                Err(e) => err(e),
            },
            "readdir" => match d!(1).read_directory() {
                Ok(s) => {
                    let mut names = vec![];
                    loop {
                        match s.read_directory_entry() {
                            Ok(Some(e)) => names.push(format!("{}:{}", e.name, kind(e.type_))),
                            Ok(None) => break,
                            Err(e) => {
                                names.push(err(e));
                                break;
                            }
                        }
                    }
                    names.sort();
                    names.join(",")
                }
                Err(e) => err(e),
            },
            "mkdir" => match d!(1).create_directory_at(&text(t[2])) {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "rmdir" => match d!(1).remove_directory_at(&text(t[2])) {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "unlink" => match d!(1).unlink_file_at(&text(t[2])) {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "rename" => match d!(1).rename_at(&text(t[2]), d!(3), &text(t[4])) {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "symlink" => match d!(1).symlink_at(&text(t[2]), &text(t[3])) {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "link" => match d!(1).link_at(pflags(t[2]), &text(t[3]), d!(4), &text(t[5])) {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "readlink" => match d!(1).readlink_at(&text(t[2])) {
                Ok(s) => format!("target={}", s),
                Err(e) => err(e),
            },
            "set-size" => match d!(1).set_size(t[2].parse().unwrap()) {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "sync" => match d!(1).sync() {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "sync-data" => match d!(1).sync_data() {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "advise" => match d!(1).advise(t[2].parse().unwrap(), t[3].parse().unwrap(), Advice::Normal) {
                Ok(()) => "ok".into(),
                Err(e) => err(e),
            },
            "same" => format!("{}", d!(1).is_same_object(d!(2))),
            "hash" => match (d!(1).metadata_hash(), d!(1).metadata_hash()) {
                (Ok(a), Ok(b)) => format!("stable={}", a.lower == b.lower && a.upper == b.upper),
                (Err(e), _) | (_, Err(e)) => err(e),
            },
            "hash-at" => match (d!(1).metadata_hash_at(pflags(t[2]), &text(t[3])), d!(1).metadata_hash_at(pflags(t[2]), &text(t[3]))) {
                (Ok(a), Ok(b)) => format!("stable={}", a.lower == b.lower && a.upper == b.upper),
                (Err(e), _) | (_, Err(e)) => err(e),
            },
            "drop" => {
                handles.remove(t[1]);
                "ok".into()
            }
            other => panic!("unknown op {other}"),
        };
        println!("{n} {}: {result}", t[0]);
    }
}
