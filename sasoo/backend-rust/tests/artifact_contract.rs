#![cfg(feature = "pdf-xberg-native")]
#[path = "support/library_fixture.rs"]
mod fixture;
use sasoo_backend::{
    pdf::import::{CANDIDATE_MARKER, PdfCandidate},
    types::PaperId,
};
use std::fs;
use tokio_util::sync::CancellationToken;

#[test]
fn restart_reads_the_same_version_and_gets_do_not_write_artifacts() {
    let dir = tempfile::tempdir().unwrap();
    fixture::seed(dir.path(), true);
    rusqlite::Connection::open(dir.path().join("sasoo.db"))
        .unwrap()
        .execute("UPDATE papers SET status='pending'", [])
        .unwrap();
    fs::write(
        dir.path().join(".sasoo-rust-pdf-candidate"),
        CANDIDATE_MARKER,
    )
    .unwrap();
    let first;
    {
        let s = PdfCandidate::open(dir.path()).unwrap().with_execution(
            sasoo_backend::pdf::process::Policy::new(
                env!("CARGO_BIN_EXE_sasoo-backend"),
                std::time::Duration::from_secs(5),
            ),
        );
        first = s
            .import_pdf(
                "source.pdf",
                &fixture::minimal_pdf(),
                &CancellationToken::new(),
            )
            .unwrap();
    }
    // Wait for the bounded SQLite owner thread to close its connection and lock.
    let s = loop {
        match PdfCandidate::open(dir.path()) {
            Ok(s) => {
                break s.with_execution(sasoo_backend::pdf::process::Policy::new(
                    env!("CARGO_BIN_EXE_sasoo-backend"),
                    std::time::Duration::from_secs(5),
                ));
            }
            Err(sasoo_backend::error::SasooError::Conflict(_)) => std::thread::yield_now(),
            Err(e) => panic!("{e}"),
        }
    };
    let id = PaperId(first["id"].as_i64().unwrap());
    let (receipt, artifact) = s.load(id, None).unwrap();
    assert_eq!(receipt.version, first["extraction"]["version"]);
    assert_eq!(artifact.pages.len(), 1);
    let folder = dir
        .path()
        .join("library")
        .join(first["folder_name"].as_str().unwrap());
    let path = folder
        .join(".sasoo-runtime/pdf")
        .join(&receipt.version)
        .join("document.json");
    let before = fs::read(&path).unwrap();
    let meta = fs::metadata(&path).unwrap().modified().unwrap();
    s.paper(id).unwrap();
    s.load(id, None).unwrap();
    assert_eq!(fs::read(&path).unwrap(), before);
    assert_eq!(fs::metadata(&path).unwrap().modified().unwrap(), meta);
    fs::write(&path, b"{}").unwrap();
    assert!(s.load(id, None).is_err());
    assert_eq!(s.paper(id).unwrap()["text_ready"], false);
}

#[cfg(unix)]
#[test]
fn private_versions_and_source_symlinks_cannot_escape_the_library() {
    use std::os::unix::fs::symlink;
    let dir = tempfile::tempdir().unwrap();
    fixture::seed(dir.path(), true);
    rusqlite::Connection::open(dir.path().join("sasoo.db"))
        .unwrap()
        .execute("UPDATE papers SET status='pending'", [])
        .unwrap();
    fs::write(
        dir.path().join(".sasoo-rust-pdf-candidate"),
        CANDIDATE_MARKER,
    )
    .unwrap();
    let s = PdfCandidate::open(dir.path()).unwrap().with_execution(
        sasoo_backend::pdf::process::Policy::new(
            env!("CARGO_BIN_EXE_sasoo-backend"),
            std::time::Duration::from_secs(5),
        ),
    );
    let paper = s
        .import_pdf(
            "source.pdf",
            &fixture::minimal_pdf(),
            &CancellationToken::new(),
        )
        .unwrap();
    let id = PaperId(paper["id"].as_i64().unwrap());
    let folder = dir
        .path()
        .join("library")
        .join(paper["folder_name"].as_str().unwrap());
    let outside = tempfile::tempdir().unwrap();
    fs::write(outside.path().join("source.pdf"), fixture::minimal_pdf()).unwrap();
    // Only replace this test's own source, never a user file.
    fs::remove_file(folder.join("source.pdf")).unwrap();
    symlink(outside.path().join("source.pdf"), folder.join("source.pdf")).unwrap();
    assert!(s.load(id, None).is_err());
    assert!(s.load(id, Some("../../outside".into())).is_err());
}
