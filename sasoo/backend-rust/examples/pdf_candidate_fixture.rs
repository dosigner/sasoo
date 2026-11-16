//! Create a new disposable library; never accepts or migrates an existing root.
use std::fs;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let dir = tempfile::Builder::new()
        .prefix("sasoo-pdf-candidate-")
        .tempdir()?;
    fs::create_dir(dir.path().join("library"))?;
    fs::write(
        dir.path().join(".sasoo-rust-isolated-fixture"),
        "synthetic-only\n",
    )?;
    fs::write(
        dir.path().join(".sasoo-rust-pdf-candidate"),
        "isolated-native-text-v2\n",
    )?;
    let db = rusqlite::Connection::open(dir.path().join("sasoo.db"))?;
    db.execute_batch(include_str!("../tests/fixtures/legacy/schema.sql"))?;
    drop(db);
    println!("{}", dir.keep().display());
    Ok(())
}
