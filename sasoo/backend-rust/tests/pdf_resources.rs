use std::{path::Path, process::Command};

#[test]
fn resource_integrity_rejects_missing_unpinned_and_cross_target_files() {
    let script =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../scripts/verify-rust-pdf-resources.js");
    let result = Command::new("node")
        .arg(script)
        .arg("--self-test")
        .output()
        .expect("Node must be available for the resource contract test");
    assert!(
        result.status.success(),
        "{}{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
    let receipt: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(receipt["status"], "passed");
    assert_eq!(receipt["network_requests"], 0);
}

#[test]
fn declared_xberg_resources_do_not_imply_deployment_readiness() {
    let crate_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let result = Command::new("node")
        .arg(crate_dir.join("../scripts/verify-rust-pdf-resources.js"))
        .arg("--manifest")
        .arg(crate_dir.join("../contract-fixtures/rust-backend-v2/dependency-resources.json"))
        .args(["--target", "aarch64-apple-darwin", "--profile", "x-native"])
        .arg("--resource-root")
        .arg(crate_dir.join("resources"))
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(2));
    let receipt: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(receipt["resource_status"], "blocked");
    assert_eq!(receipt["deployment_status"], "not_evaluated");
    assert_eq!(receipt["network_requests"], 0);
}
