use std::{
    ffi::OsString,
    net::{IpAddr, Ipv4Addr},
};

use sasoo_backend::{
    cli::{Mode, parse_cli},
    types::{AttemptId, Generation, PaperId},
};
use uuid::Uuid;

fn args(values: &[&str]) -> Vec<OsString> {
    values.iter().map(OsString::from).collect()
}

#[test]
fn default_and_explicit_server_keep_legacy_flags() {
    assert_eq!(
        parse_cli(&[]).unwrap(),
        Mode::Server {
            host: IpAddr::V4(Ipv4Addr::LOCALHOST),
            port: 8000,
        }
    );
    assert_eq!(
        parse_cli(&args(&["--host", "127.0.0.1", "--port=8341"])).unwrap(),
        Mode::Server {
            host: IpAddr::V4(Ipv4Addr::LOCALHOST),
            port: 8341,
        }
    );
}

#[test]
fn legacy_worker_does_not_invent_missing_attempt_identity() {
    assert_eq!(
        parse_cli(&args(&["--analyze-paper", "7", "--run-generation", "3"])).unwrap(),
        Mode::Worker {
            paper_id: PaperId(7),
            generation: Generation(3),
            attempt_id: None
        }
    );
    let id = "2ec23e1f-7b45-4ee5-b5cf-8bb5fcdb8cda";
    assert_eq!(
        parse_cli(&args(&["--analyze-paper=7", "--attempt-id", id])).unwrap(),
        Mode::Worker {
            paper_id: PaperId(7),
            generation: Generation(0),
            attempt_id: Some(AttemptId(Uuid::parse_str(id).unwrap()))
        }
    );
}

#[test]
fn invalid_flags_and_secrets_fail_without_echoing_values() {
    for input in [
        vec!["--port", "70000"],
        vec!["--port", "0"],
        vec!["--host", "garbage"],
        vec!["--analyze-paper", "-1"],
        vec!["--run-generation", "1"],
        vec!["--analyze-paper", "7", "--run-generation", "-1"],
        vec!["--analyze-paper", "7", "--host", "127.0.0.1"],
        vec!["--analyze-paper", "7", "--attempt-id", "not-a-uuid"],
        vec!["--port", "8000", "--port", "8001"],
        vec!["--port"],
        vec!["--api-token", "sensitive-contract-value"],
        vec!["--openai-key=sensitive-contract-value"],
    ] {
        let error = parse_cli(&args(&input)).unwrap_err();
        assert!(!error.to_string().contains("sensitive-contract-value"));
    }
}

#[test]
fn binary_worker_and_default_server_cannot_start_a_live_owner() {
    let binary = env!("CARGO_BIN_EXE_sasoo-backend");
    let worker = std::process::Command::new(binary)
        .env_clear()
        .args(["--analyze-paper", "7", "--run-generation", "4"])
        .output()
        .unwrap();
    assert!(!worker.status.success());
    assert!(String::from_utf8_lossy(&worker.stderr).contains("Worker execution is not connected"));
    let server = std::process::Command::new(binary)
        .env_clear()
        .output()
        .unwrap();
    assert!(!server.status.success());
    assert!(String::from_utf8_lossy(&server.stderr).contains("SASOO_RUST_ISOLATED_ROOT"));
}
