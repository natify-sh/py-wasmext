use std::collections::BTreeMap;
use std::io::{BufRead, Read, Write};
use std::time::Instant;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    println!("args={:?}", args);
    println!("GREETING={:?}", std::env::var("GREETING"));
    let stdin = std::io::stdin();
    let mut first = String::new();
    stdin.lock().read_line(&mut first).unwrap();
    println!("stdin: {}", first.trim_end());
    let mut rest = String::new();
    stdin.lock().read_to_string(&mut rest).unwrap();
    println!("rest bytes={}", rest.len());
    std::fs::create_dir_all("/data/dir/deep").unwrap();
    let mut f = std::fs::File::create("/data/dir/file.txt").unwrap();
    for i in 0..1000 { writeln!(f, "line {i}").unwrap(); }
    drop(f);
    let text = std::fs::read_to_string("/data/dir/file.txt").unwrap();
    println!("lines={}", text.lines().count());
    std::fs::rename("/data/dir/file.txt", "/data/dir/moved.txt").unwrap();
    let mut names: Vec<String> = std::fs::read_dir("/data/dir").unwrap().map(|e| e.unwrap().file_name().into_string().unwrap()).collect();
    names.sort();
    println!("dir={:?}", names);
    let md = std::fs::metadata("/data/dir/moved.txt").unwrap();
    println!("size={}", md.len());
    std::fs::remove_file("/data/dir/moved.txt").unwrap();
    println!("missing is err={}", std::fs::File::open("/data/dir/moved.txt").is_err());
    let mut m = BTreeMap::new();
    for i in 0..10000u32 { m.insert(i.wrapping_mul(2654435761), i); }
    println!("map={}", m.len());
    let t = Instant::now();
    std::thread::sleep(std::time::Duration::from_millis(20));
    println!("slept>=20ms={}", t.elapsed().as_millis() >= 20);
    eprintln!("to stderr");
    std::process::exit(if names.len() == 2 { 0 } else { 9 });
}
