// Standalone test executable. No product request can activate these faults.
use std::{io::{BufRead, Write}, time::Duration};
fn main() {
    if std::env::current_exe().unwrap().file_name().unwrap()=="early-crash" {std::process::abort();}
    let mut line=String::new();
    std::io::stdin().lock().read_line(&mut line).unwrap();
    let exe=std::env::current_exe().unwrap();
    let mode=exe.file_name().unwrap().to_str().unwrap();
    match mode {
        "hang" => loop {std::thread::sleep(Duration::from_millis(10));},
        "crash" => std::process::abort(),
        "partial" => {std::fs::write("document.json",b"{\"pages\":[").unwrap();std::process::exit(7);},
        "corrupt" => {std::fs::write("document.json",b"{}").unwrap();std::fs::write("complete.json",b"{}").unwrap();},
        "barrier" | "wrong-identity" => {
            if mode=="barrier" {
                std::fs::write("ready",b"ready").unwrap();
                while !std::path::Path::new("release").exists() {std::thread::sleep(Duration::from_millis(5));}
            }
            let field=|name:&str| {let key=format!("\"{name}\":\"");line.split(&key).nth(1).unwrap().split('"').next().unwrap().to_owned()};
            std::fs::write("document.json",env!("TEST_DOCUMENT_JSON")).unwrap();
            let nonce=if mode=="wrong-identity" {"00000000-0000-0000-0000-000000000000".to_owned()} else {field("nonce")};
            std::fs::write("complete.json",format!("{{\"operation\":\"{}\",\"nonce\":\"{}\",\"pid\":{},\"document_sha256\":\"{}\"}}",field("operation"),nonce,std::process::id(),env!("TEST_DOCUMENT_HASH"))).unwrap();
        },
        "oversize" => {let mut f=std::fs::File::create("document.json").unwrap();let chunk=vec![0;1024*1024];loop {f.write_all(&chunk).unwrap();}},
        "sandbox" => {
            let env_empty=std::env::vars().next().is_none();
            let outside=std::fs::read(exe.parent().unwrap().join("credential-sentinel")).is_err();
            let network=std::net::TcpStream::connect("127.0.0.1:9").is_err();
            let credential=std::process::Command::new("/usr/bin/security").arg("list-keychains").output().is_err();
            std::fs::write("probe.json",format!("[{env_empty},{outside},{network},{credential}]")).unwrap();
        },
        _ => panic!("Unknown synthetic fault"),
    }
}
