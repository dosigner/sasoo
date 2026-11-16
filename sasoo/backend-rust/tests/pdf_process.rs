#![cfg(feature = "pdf-xberg-native")]
use std::process::Command;

#[test]
fn pdf_child_mode_is_separate_from_server_and_analysis_worker() {
    let out = Command::new(env!("CARGO_BIN_EXE_sasoo-backend"))
        .arg("--pdf-operation")
        .output()
        .unwrap();
    assert!(!out.status.success());
    assert!(
        String::from_utf8_lossy(&out.stderr).contains("PDF child request"),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}

#[path = "support/library_fixture.rs"]
mod fixture;
use sasoo_backend::pdf::{
    PdfInput,
    native::native_options,
    process::{self, Policy},
};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::OnceLock,
    time::Duration,
};
use tokio_util::sync::CancellationToken;
fn helpers() -> &'static Path {
    static DIR: OnceLock<PathBuf> = OnceLock::new();
    DIR.get_or_init(|| {
        let dir =
            std::env::temp_dir().join(format!("sasoo-test-children-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&dir).unwrap();
        let source = make_input(&dir);
        let document = sasoo_backend::pdf::extract_document(
            &source,
            &native_options(),
            &CancellationToken::new(),
        )
        .unwrap();
        let json = serde_json::to_string(&document).unwrap();
        let out = Command::new("rustc")
            .env("TEST_DOCUMENT_JSON", &json)
            .env(
                "TEST_DOCUMENT_HASH",
                sasoo_backend::pdf::artifacts::hash(json.as_bytes()),
            )
            .args([
                "--edition=2024",
                "tests/support/pdf-process/fault_child.rs",
                "-o",
            ])
            .arg(dir.join("hang"))
            .current_dir(env!("CARGO_MANIFEST_DIR"))
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        for name in [
            "crash",
            "early-crash",
            "partial",
            "corrupt",
            "oversize",
            "sandbox",
            "barrier",
            "wrong-identity",
        ] {
            fs::copy(dir.join("hang"), dir.join(name)).unwrap();
        }
        fs::write(dir.join("credential-sentinel"), "synthetic-secret").unwrap();
        dir
    })
}
fn make_input(root: &Path) -> PdfInput {
    let bytes = fixture::minimal_pdf();
    let path = root.join("source.pdf");
    fs::write(&path, &bytes).unwrap();
    PdfInput {
        path,
        source_sha256: Sha256::digest(bytes).into(),
    }
}
fn work(root: &Path) -> PathBuf {
    fs::read_dir(root)
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.is_dir())
        .unwrap()
}
#[test]
fn controlled_timeout_crash_partial_corrupt_and_output_limit_are_reaped() {
    for mode in [
        "hang",
        "crash",
        "early-crash",
        "partial",
        "corrupt",
        "oversize",
        "wrong-identity",
    ] {
        let root = tempfile::tempdir().unwrap();
        let input = make_input(root.path());
        let policy = Policy::new(
            helpers().join(mode),
            Duration::from_millis(if mode == "hang" { 200 } else { 3000 }),
        );
        let out = process::extract(
            &policy,
            &input,
            &native_options(),
            &CancellationToken::new(),
            uuid::Uuid::new_v4(),
            root.path(),
        );
        assert!(out.is_err(), "{mode}");
        if mode == "wrong-identity" {
            assert!(out.unwrap_err().to_string().contains("identity differs"));
        }
        let receipt: serde_json::Value =
            serde_json::from_slice(&fs::read(work(root.path()).join("reaped.json")).unwrap())
                .unwrap();
        assert_eq!(receipt["state"], "child_exited_and_reaped");
        if mode == "hang" {
            assert_eq!(receipt["stop"], "deadline_elapsed");
        }
        assert!(!work(root.path()).join("validated.json").exists());
        let real = Policy::new(env!("CARGO_BIN_EXE_sasoo-backend"), Duration::from_secs(5));
        assert!(
            process::extract(
                &real,
                &input,
                &native_options(),
                &CancellationToken::new(),
                uuid::Uuid::new_v4(),
                root.path()
            )
            .is_ok(),
            "next real parser after {mode}"
        );
    }
}
#[test]
fn cancellation_owns_handle_until_reaped_and_environment_and_credentials_are_denied() {
    let root = tempfile::tempdir().unwrap();
    let input = make_input(root.path());
    let policy = Policy::new(helpers().join("hang"), Duration::from_secs(5));
    let token = CancellationToken::new();
    let cancel = token.clone();
    let work_root = root.path().to_owned();
    let owner = std::thread::spawn(move || {
        process::extract(
            &policy,
            &input,
            &native_options(),
            &token,
            uuid::Uuid::new_v4(),
            &work_root,
        )
    });
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    while !fs::read_dir(root.path())
        .unwrap()
        .filter_map(|e| e.ok())
        .any(|e| e.path().join("child.json").exists())
    {
        assert!(std::time::Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(5));
    }
    cancel.cancel();
    assert!(owner.join().unwrap().is_err());
    let receipt: serde_json::Value =
        serde_json::from_slice(&fs::read(work(root.path()).join("reaped.json")).unwrap()).unwrap();
    assert_eq!(receipt["stop"], "cancel_requested");
    let root = tempfile::tempdir().unwrap();
    let input = make_input(root.path());
    assert!(
        process::extract(
            &Policy::new(helpers().join("sandbox"), Duration::from_secs(5)),
            &input,
            &native_options(),
            &CancellationToken::new(),
            uuid::Uuid::new_v4(),
            root.path()
        )
        .is_err()
    );
    assert_eq!(
        fs::read_to_string(work(root.path()).join("probe.json")).unwrap(),
        "[true,true,true,true]"
    );
}

use sasoo_backend::{
    pdf::import::{CANDIDATE_MARKER, PdfCandidate},
    types::PaperId,
};
fn service(root: &Path) -> PdfCandidate {
    fixture::seed(root, true);
    rusqlite::Connection::open(root.join("sasoo.db"))
        .unwrap()
        .execute("UPDATE papers SET status='pending'", [])
        .unwrap();
    fs::write(root.join(".sasoo-rust-pdf-candidate"), CANDIDATE_MARKER).unwrap();
    PdfCandidate::open(root)
        .unwrap()
        .with_execution(Policy::new(
            env!("CARGO_BIN_EXE_sasoo-backend"),
            Duration::from_secs(5),
        ))
}
fn ready(root: &Path) -> PathBuf {
    let until = std::time::Instant::now() + Duration::from_secs(5);
    loop {
        if let Ok(entries) = fs::read_dir(root.join("library/.sasoo-process")) {
            if let Some(path) = entries
                .filter_map(|e| e.ok())
                .map(|e| e.path())
                .find(|p| p.join("ready").exists() && !p.join("release").exists())
            {
                return path;
            }
        }
        assert!(
            std::time::Instant::now() < until,
            "child barrier not reached"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
}
#[test]
fn publication_faults_and_completion_races_preserve_previous_success() {
    for fault in ["db", "cancel", "source", "current"] {
        let root = tempfile::tempdir().unwrap();
        let s = service(root.path());
        let saved = s
            .import_pdf(
                "source.pdf",
                &fixture::minimal_pdf(),
                &CancellationToken::new(),
            )
            .unwrap();
        let id = PaperId(saved["id"].as_i64().unwrap());
        let old = saved["extraction"]["version"].as_str().unwrap().to_owned();
        let latest = s.refresh(id, &CancellationToken::new()).unwrap();
        let previous = latest["extraction"]["version"].as_str().unwrap().to_owned();
        let s = std::sync::Arc::new(s.with_execution(Policy::new(
            helpers().join("barrier"),
            Duration::from_secs(5),
        )));
        let op = uuid::Uuid::new_v4();
        let token = CancellationToken::new();
        let guard = s.register(op, token.clone()).unwrap();
        let permit = s.admission.clone().try_acquire_owned().unwrap();
        let producer = s.clone();
        let owner = std::thread::spawn(move || {
            let _guard = guard;
            let _permit = permit;
            producer.refresh(id, &token)
        });
        let work = ready(root.path());
        assert_eq!(s.admission.available_permits(), 0);
        match fault {
            "db" => s.db.blocking_call(|c|{c.execute_batch("CREATE TRIGGER reject_pdf BEFORE INSERT ON pdf_candidate_versions BEGIN SELECT RAISE(ABORT,'synthetic publication failure'); END;").map_err(sasoo_backend::storage::db::db_sql_error)}).unwrap(),
            "cancel" => assert!(s.cancel(op).unwrap()),
            "source" => fs::write(root.path().join("library").join(saved["folder_name"].as_str().unwrap()).join("source.pdf"),b"%PDF-1.7 changed").unwrap(),
            "current" => {let old=old.clone();s.db.blocking_call(move|c|{c.execute("UPDATE pdf_candidate_current SET version=?1 WHERE paper_id=?2",rusqlite::params![old,id.0]).map_err(sasoo_backend::storage::db::db_sql_error)?;Ok(())}).unwrap();},
            _=>unreachable!()
        }
        fs::write(work.join("release"), b"release").unwrap();
        assert!(owner.join().unwrap().is_err(), "{fault}");
        assert_eq!(s.admission.available_permits(), 1);
        assert_eq!(
            s.operation_status(op).unwrap()["publication_state"],
            "unknown"
        );
        assert_eq!(
            s.load(id, Some(previous.clone())).unwrap().0.version,
            previous
        );
        let current =
            s.db.blocking_call(move |c| {
                c.query_row(
                    "SELECT version FROM pdf_candidate_current WHERE paper_id=?1",
                    [id.0],
                    |r| r.get::<_, String>(0),
                )
                .map_err(sasoo_backend::storage::db::db_sql_error)
            })
            .unwrap();
        assert_eq!(current, if fault == "current" { old } else { previous });
    }
}
#[test]
fn committed_response_loss_and_late_cancel_survive_restart_without_retry() {
    let root = tempfile::tempdir().unwrap();
    let s = std::sync::Arc::new(service(root.path()));
    let op = uuid::Uuid::new_v4();
    let token = CancellationToken::new();
    let guard = s.register(op, token.clone()).unwrap();
    let saved = s
        .import_pdf("source.pdf", &fixture::minimal_pdf(), &token)
        .unwrap();
    assert!(s.cancel(op).unwrap());
    assert_eq!(
        s.operation_status(op).unwrap()["version"],
        saved["extraction"]["version"]
    );
    assert_eq!(
        s.operation_status(op).unwrap()["publication_state"],
        "committed"
    );
    assert!(s.load(PaperId(saved["id"].as_i64().unwrap()), None).is_ok());
    drop(guard);
    drop(s);
    let until = std::time::Instant::now() + Duration::from_secs(5);
    let reopened = loop {
        match PdfCandidate::open(root.path()) {
            Ok(s) => break s,
            Err(_) => {
                assert!(std::time::Instant::now() < until);
                std::thread::sleep(Duration::from_millis(5));
            }
        }
    };
    assert_eq!(
        reopened.operation_status(op).unwrap()["version"],
        saved["extraction"]["version"]
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_http_disconnect_retains_producer_slot_until_child_reaped() {
    use tokio::io::AsyncWriteExt;
    let root = tempfile::tempdir().unwrap();
    let s = std::sync::Arc::new(service(root.path()).with_execution(Policy::new(
        helpers().join("hang"),
        Duration::from_millis(700),
    )));
    let app = sasoo_backend::http::build_router(sasoo_backend::http::ApiState {
        api_token: Some("synthetic".into()),
        shutdown_token: None,
        production: true,
        library_path: root.path().join("library"),
        shutdown_signal: None,
        library: None,
        paper_service: None,
        pdf_candidate: Some(s.clone()),
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let mut socket = tokio::net::TcpStream::connect(addr).await.unwrap();
    let mut body=b"--x\r\nContent-Disposition: form-data; name=\"file\"; filename=\"disconnect.pdf\"\r\nContent-Type: application/pdf\r\n\r\n".to_vec();
    body.extend(fixture::minimal_pdf());
    body.extend(b"\r\n--x--\r\n");
    let op = uuid::Uuid::new_v4();
    socket.write_all(format!("POST /api/papers/upload HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer synthetic\r\nX-Sasoo-Pdf-Operation-ID: {op}\r\nContent-Type: multipart/form-data; boundary=x\r\nContent-Length: {}\r\n\r\n",body.len()).as_bytes()).await.unwrap();
    socket.write_all(&body).await.unwrap();
    let wait_root = root.path().to_owned();
    let work = tokio::task::spawn_blocking(move || {
        let until = std::time::Instant::now() + Duration::from_secs(5);
        loop {
            if let Ok(entries) = fs::read_dir(wait_root.join("library/.sasoo-process")) {
                if let Some(path) = entries
                    .filter_map(|e| e.ok())
                    .map(|e| e.path())
                    .find(|p| p.join("child.json").exists())
                {
                    break path;
                }
            }
            assert!(std::time::Instant::now() < until);
            std::thread::sleep(Duration::from_millis(5));
        }
    })
    .await
    .unwrap();
    assert_eq!(s.admission.available_permits(), 0);
    drop(socket);
    let permit = s.admission.acquire().await.unwrap();
    assert!(work.join("reaped.json").is_file());
    assert_eq!(
        s.operation_status(op).unwrap()["publication_state"],
        "unknown"
    );
    drop(permit);
    server.abort();
}
