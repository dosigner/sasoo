use std::path::PathBuf;

pub fn contract_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../contract-fixtures/rust-backend-v2")
}
pub fn load(name: &str) -> serde_json::Value {
    let path = contract_root().join(name);
    serde_json::from_slice(
        &std::fs::read(&path).unwrap_or_else(|e| panic!("Fixture {}: {e}", path.display())),
    )
    .expect("Valid contract fixture JSON")
}
