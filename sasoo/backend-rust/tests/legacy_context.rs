#[path = "support/library_fixture.rs"]
mod fixture;
use sasoo_backend::{
    analysis::chat_retrieval::Document, pdf::legacy_context::load_legacy_document,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{fs, time::UNIX_EPOCH};

#[test]
fn metadata_compatibility_does_not_invent_a_historical_source_hash() {
    let root = tempfile::tempdir().unwrap();
    fixture::seed(root.path(), false);
    let dir = root.path().join("library/one");
    let result = load_legacy_document(&dir).unwrap();
    assert_eq!(result.state, "usable");
    assert_eq!(result.source_identity, "metadata_matched");
    assert!(result.stored_source_sha256.is_none());
    assert!(result.source_sha256.is_some());
    let path = dir.join(".document_context.json");
    let mut data: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    data["pdf_sha256"] = json!(format!(
        "{:x}",
        Sha256::digest(fs::read(dir.join("paper.pdf")).unwrap())
    ));
    fs::write(&path, serde_json::to_vec(&data).unwrap()).unwrap();
    let result = load_legacy_document(&dir).unwrap();
    assert_eq!(result.source_identity, "sha256_matched");
    assert!(result.stored_source_sha256.is_some());
}

#[test]
fn missing_empty_stale_corrupt_and_old_context_are_not_empty_successes() {
    for mode in [
        "missing",
        "empty",
        "stale",
        "corrupt",
        "old",
        "hash-mismatch",
        "no-version",
    ] {
        let root = tempfile::tempdir().unwrap();
        fixture::seed(root.path(), false);
        let dir = root.path().join("library/one");
        fs::remove_file(dir.join(".odl_manifest.json")).unwrap();
        let path = dir.join(".document_context.json");
        let mut data: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        match mode {
            "missing" => {
                data.as_object_mut().unwrap().remove("full_text");
            }
            "empty" => data["full_text"] = json!("  "),
            "stale" => data["pdf_signature"]["pdf_size"] = json!(1),
            "old" => data["context_builder_version"] = json!("document-context-v3"),
            "hash-mismatch" => data["pdf_sha256"] = json!("00"),
            "no-version" => data["parser_version"] = Value::Null,
            _ => {}
        }
        fs::write(
            &path,
            if mode == "corrupt" {
                b"{broken".to_vec()
            } else {
                serde_json::to_vec(&data).unwrap()
            },
        )
        .unwrap();
        let before = fs::read(&path).unwrap();
        let result = load_legacy_document(&dir).unwrap();
        assert_ne!(result.state, "usable", "{mode}");
        assert!(result.document.is_none(), "{mode}");
        assert_eq!(fs::read(&path).unwrap(), before);
    }
    assert!(serde_json::from_value::<Document>(json!({"parser_version":"old"})).is_err());
}

#[test]
fn legacy_manifest_can_supply_full_text_without_rewriting_an_old_context() {
    let root = tempfile::tempdir().unwrap();
    fixture::seed(root.path(), false);
    let dir = root.path().join("library/one");
    let path = dir.join(".document_context.json");
    fs::write(&path, b"{}").unwrap();
    let result = load_legacy_document(&dir).unwrap();
    assert_eq!(result.state, "usable");
    assert_eq!(
        result.extraction_file.as_deref(),
        Some(".odl_manifest.json")
    );
    assert_eq!(fs::read(&path).unwrap(), b"{}");
    let pdf = dir.join("paper.pdf");
    let old = pdf.metadata().unwrap();
    let mut changed = fs::read(&pdf).unwrap();
    changed[0] = b'!';
    fs::write(&pdf, changed).unwrap();
    fs::File::open(&pdf)
        .unwrap()
        .set_modified(old.modified().unwrap())
        .unwrap();
    let meta = pdf.metadata().unwrap();
    assert_eq!(
        meta.modified()
            .unwrap()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos(),
        old.modified()
            .unwrap()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    // Matching old metadata alone cannot detect this replacement.
    assert_eq!(
        load_legacy_document(&dir).unwrap().source_identity,
        "metadata_matched"
    );
}
