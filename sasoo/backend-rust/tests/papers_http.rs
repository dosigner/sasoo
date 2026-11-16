use std::{path::PathBuf, process::Command};

#[test]
fn actual_listener_matches_read_only_python_corpus_and_preserves_every_file() {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let python = manifest.join("../backend/.venv").join(if cfg!(windows) {
        "Scripts/python.exe"
    } else {
        "bin/python"
    });
    assert!(
        python.is_file(),
        "The local Python oracle requires the existing backend test environment"
    );
    let root = tempfile::Builder::new()
        .prefix("sasoo-phase17-http-")
        .tempdir()
        .unwrap()
        .keep();
    let result = Command::new(python)
        .arg(manifest.join("tests/papers_http_oracle.py"))
        .arg(env!("CARGO_BIN_EXE_sasoo-backend"))
        .arg(&root)
        .env("PYTHON_DOTENV_DISABLED", "1")
        .output()
        .unwrap();
    println!("{}", String::from_utf8_lossy(&result.stdout));
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
}
