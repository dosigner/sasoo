#![cfg(feature = "pdf-xberg-native")]
#[path = "support/library_fixture.rs"]
mod fixture;
use sasoo_backend::{
    error::SasooError,
    pdf::import::{CANDIDATE_MARKER, PdfCandidate, safe_filename},
    types::PaperId,
};
use std::{fs, path::Path};
use tokio_util::sync::CancellationToken;

fn seed(root: &Path) {
    fixture::seed(root, true);
    rusqlite::Connection::open(root.join("sasoo.db"))
        .unwrap()
        .execute("UPDATE papers SET status='pending' WHERE id=2", [])
        .unwrap();
    fs::write(root.join(".sasoo-rust-pdf-candidate"), CANDIDATE_MARKER).unwrap();
}
fn count(s: &PdfCandidate) -> i64 {
    s.db.blocking_call(|c| {
        c.query_row("SELECT COUNT(*) FROM papers", [], |r| r.get(0))
            .map_err(sasoo_backend::storage::db::db_sql_error)
    })
    .unwrap()
}

#[test]
fn imports_duplicate_names_without_overwriting_and_preserves_legacy_files() {
    let dir = tempfile::tempdir().unwrap();
    seed(dir.path());
    let legacy = fs::read(dir.path().join("library/one/.document_context.json")).unwrap();
    let s = PdfCandidate::open(dir.path()).unwrap().with_execution(
        sasoo_backend::pdf::process::Policy::new(
            env!("CARGO_BIN_EXE_sasoo-backend"),
            std::time::Duration::from_secs(5),
        ),
    );
    let before = count(&s);
    let a = s
        .import_pdf(
            "../../한글 paper.PDF",
            &fixture::minimal_pdf(),
            &CancellationToken::new(),
        )
        .unwrap();
    let b = s
        .import_pdf(
            "../../한글 paper.PDF",
            &fixture::minimal_pdf(),
            &CancellationToken::new(),
        )
        .unwrap();
    assert_ne!(a["id"], b["id"]);
    assert_ne!(a["folder_name"], b["folder_name"]);
    assert_eq!(a["status"], "pending");
    assert_eq!(a["text_ready"], true);
    assert_eq!(a["visual_ready"], false);
    assert_eq!(a["artifacts_ready"], false);
    assert_eq!(
        a["extraction"]["metadata_state"],
        "filename_stub_unverified"
    );
    assert_eq!(a["extraction"]["analysis_state"], "not_run");
    let pdf = dir
        .path()
        .join("library")
        .join(a["folder_name"].as_str().unwrap())
        .join("한글_paper.pdf");
    assert_eq!(fs::read(pdf).unwrap(), fixture::minimal_pdf());
    assert_eq!(count(&s), before + 2);
    assert_eq!(
        fs::read(dir.path().join("library/one/.document_context.json")).unwrap(),
        legacy
    );
    assert!(
        PdfCandidate::open(dir.path()).is_err(),
        "second owner must fail"
    );
}

#[test]
fn invalid_cancelled_and_partial_uploads_never_enter_the_catalog() {
    let dir = tempfile::tempdir().unwrap();
    seed(dir.path());
    let s = PdfCandidate::open(dir.path()).unwrap().with_execution(
        sasoo_backend::pdf::process::Policy::new(
            env!("CARGO_BIN_EXE_sasoo-backend"),
            std::time::Duration::from_secs(5),
        ),
    );
    let before = count(&s);
    for (name, bytes) in [
        ("source.txt", b"%PDF-invalid".as_slice()),
        ("source.pdf", b"text".as_slice()),
        ("source.pdf", b"%PDF-1.7\ntruncated".as_slice()),
    ] {
        assert!(
            s.import_pdf(name, bytes, &CancellationToken::new())
                .is_err()
        );
    }
    let cancel = CancellationToken::new();
    cancel.cancel();
    assert!(matches!(
        s.import_pdf("cancel.pdf", &fixture::minimal_pdf(), &cancel),
        Err(SasooError::Incomplete(_))
    ));
    assert_eq!(count(&s), before);
    assert_eq!(
        s.db.blocking_call(|c| c
            .query_row("SELECT COUNT(*) FROM pdf_candidate_versions", [], |r| r
                .get::<_, i64>(0))
            .map_err(sasoo_backend::storage::db::db_sql_error))
            .unwrap(),
        0
    );
    assert_eq!(safe_filename("C:\\temp\\Paper.PDF").unwrap(), "Paper.pdf");
    for name in [".pdf", "../../.hidden.pdf", "a\0b.txt", ""] {
        assert!(safe_filename(name).is_err());
    }
}

#[test]
fn unmarked_active_or_symlink_roots_cannot_be_writers() {
    let dir = tempfile::tempdir().unwrap();
    fixture::seed(dir.path(), true);
    assert!(PdfCandidate::open(dir.path()).is_err());
    fs::write(
        dir.path().join(".sasoo-rust-pdf-candidate"),
        CANDIDATE_MARKER,
    )
    .unwrap();
    assert!(matches!(
        PdfCandidate::open(dir.path()),
        Err(SasooError::Unsupported(_))
    ));
}

#[test]
fn immutable_refresh_retains_history_and_rejects_stale_source_or_options() {
    let dir = tempfile::tempdir().unwrap();
    seed(dir.path());
    let s = PdfCandidate::open(dir.path()).unwrap().with_execution(
        sasoo_backend::pdf::process::Policy::new(
            env!("CARGO_BIN_EXE_sasoo-backend"),
            std::time::Duration::from_secs(5),
        ),
    );
    let first = s
        .import_pdf(
            "source.pdf",
            &fixture::minimal_pdf(),
            &CancellationToken::new(),
        )
        .unwrap();
    let id = PaperId(first["id"].as_i64().unwrap());
    let version = first["extraction"]["version"].as_str().unwrap().to_owned();
    let folder = dir
        .path()
        .join("library")
        .join(first["folder_name"].as_str().unwrap());
    let original = fs::read(
        folder
            .join(".sasoo-runtime/pdf")
            .join(&version)
            .join("document.json"),
    )
    .unwrap();
    let second = s.refresh(id, &CancellationToken::new()).unwrap();
    assert_ne!(second["extraction"]["version"], version);
    assert_eq!(
        s.load(id, Some(version.clone())).unwrap().0.version,
        version
    );
    assert_eq!(
        fs::read(
            folder
                .join(".sasoo-runtime/pdf")
                .join(&version)
                .join("document.json")
        )
        .unwrap(),
        original
    );
    let cancel = CancellationToken::new();
    cancel.cancel();
    assert!(s.refresh(id, &cancel).is_err());
    assert_eq!(
        s.paper(id).unwrap()["extraction"]["version"],
        second["extraction"]["version"]
    );
    fs::write(folder.join("source.pdf"), b"%PDF-1.7\nreplaced").unwrap();
    assert!(matches!(s.load(id, None), Err(SasooError::Conflict(_))));
    assert_eq!(s.paper(id).unwrap()["text_ready"], false);
    assert!(s.refresh(id, &CancellationToken::new()).is_err());
    assert!(s.load(id, Some(version.clone())).is_ok());
    fs::write(folder.join("source.pdf"), fixture::minimal_pdf()).unwrap();
    let current = second["extraction"]["version"].as_str().unwrap().to_owned();
    s.db.blocking_call(move |c| {
        c.execute(
            "UPDATE pdf_candidate_versions SET options_sha256='stale' WHERE version=?1",
            [current],
        )
        .map_err(sasoo_backend::storage::db::db_sql_error)?;
        Ok(())
    })
    .unwrap();
    assert!(s.load(id, None).is_err());
    assert_eq!(s.paper(id).unwrap()["text_ready"], false);
}
