use std::path::PathBuf;
use std::process::Command;

fn script() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../scripts/evaluate-pdf-engines.py")
}

#[test]
fn stored_evidence_rejects_missing_metrics_and_false_provenance() {
    let output = Command::new("python3")
        .arg(script())
        .arg("--self-test")
        .output()
        .expect("Python is required for the PDF evaluation preparation tests");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn unmeasured_corpus_keeps_legacy_without_quality_claims() {
    let fixture_root =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../contract-fixtures/rust-backend-v2/pdf");
    let output = Command::new("python3")
        .arg(script())
        .arg("--corpus")
        .arg(fixture_root.join("corpus.json"))
        .arg("--rubric")
        .arg(fixture_root.join("rubric.json"))
        .output()
        .expect("Python is required for the PDF evaluation preparation tests");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["decision"], "blocked_pending_measurement");
    assert_eq!(report["engine_selection"], "legacy");
    assert_eq!(report["quality_verified"], false);
    assert_eq!(report["extraction_ran"], false);
    assert_eq!(report["source_files_verified"], false);
    assert_eq!(report["measurements"], serde_json::json!([]));
}
