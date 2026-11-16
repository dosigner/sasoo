use rusqlite::{Connection, params};
use sasoo_backend::storage::{
    db::{DbAccess, open_db},
    migrations::{create_backup, inspect_schema, migrate_owned_db},
    paths::RuntimePaths,
};
use std::process::Command;
use tempfile::TempDir;

fn fixture() -> (TempDir, RuntimePaths) {
    let dir = TempDir::new().unwrap();
    let root = dir.path().to_path_buf();
    std::fs::write(
        root.join(".sasoo-rust-isolated-fixture"),
        b"synthetic-only\n",
    )
    .unwrap();
    let paths = RuntimePaths {
        app_data_root: root.clone(),
        db_path: root.join("sasoo.db"),
        config_path: root.join("config.json"),
        default_library_root: root.join("library"),
        library_root: root.join("library"),
        library_search_roots: vec![root.join("library")],
        owner_lock_path: root.join("sasoo-runtime-owner.lock"),
    };
    let conn = Connection::open(&paths.db_path).unwrap();
    conn.execute_batch(include_str!("fixtures/legacy/schema.sql"))
        .unwrap();
    conn.execute("INSERT INTO papers(id,title,folder_name,authors,status) VALUES(8,'합성 자료','legacy',NULL,'completed')", []).unwrap();
    conn.execute(
        "INSERT INTO settings(key,value) VALUES('openai_api_key',?1)",
        ["enc:v1:synthetic-ciphertext"],
    )
    .unwrap();
    conn.execute("INSERT INTO analysis_results(id,paper_id,phase,result,cost_usd,created_at) VALUES(10,8,'recipe','{}',NULL,'2026-11-13')", []).unwrap();
    (dir, paths)
}

#[test]
fn migration_requires_exclusive_owner_and_verified_unchanged_backup() {
    let (dir, paths) = fixture();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    assert!(open_db(&paths, DbAccess::ServerOwner).is_err());
    let backup = create_backup(&db, &dir.path().join("before.sqlite")).unwrap();
    let report = migrate_owned_db(&db, &backup).unwrap();
    assert_eq!(report.revision, 1);
    assert_eq!(report.legacy_rows_changed, 0);
    assert!(inspect_schema(&db).unwrap().runtime_revision == Some(1));
    let conn = Connection::open(&paths.db_path).unwrap();
    assert_eq!(
        conn.query_row("SELECT authors FROM papers WHERE id=8", [], |r| r
            .get::<_, Option<String>>(0))
            .unwrap(),
        None
    );
    assert_eq!(
        conn.query_row(
            "SELECT cost_usd FROM analysis_results WHERE id=10",
            [],
            |r| r.get::<_, Option<f64>>(0)
        )
        .unwrap(),
        None
    );
    assert_eq!(
        conn.query_row(
            "SELECT value FROM settings WHERE key='openai_api_key'",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        "enc:v1:synthetic-ciphertext"
    );
    let worker = open_db(&paths, DbAccess::Worker).unwrap();
    assert!(create_backup(&worker, &dir.path().join("worker.sqlite")).is_err());
    assert!(migrate_owned_db(&worker, &backup).is_err());
}

#[test]
fn stale_or_tampered_backup_and_runtime_name_collision_are_rejected() {
    let (dir, paths) = fixture();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let backup = create_backup(&db, &dir.path().join("before.sqlite")).unwrap();
    let conn = Connection::open(&paths.db_path).unwrap();
    conn.execute("UPDATE papers SET notes='new user edit' WHERE id=8", [])
        .unwrap();
    assert!(migrate_owned_db(&db, &backup).is_err());
    assert!(
        conn.query_row(
            "SELECT name FROM sqlite_master WHERE name='runtime_requests'",
            [],
            |r| r.get::<_, String>(0)
        )
        .is_err()
    );
    let current = create_backup(&db, &dir.path().join("current.sqlite")).unwrap();
    std::fs::write(&current.destination, b"tampered").unwrap();
    assert!(migrate_owned_db(&db, &current).is_err());
    conn.execute("CREATE TABLE runtime_requests(unrelated TEXT)", [])
        .unwrap();
    let collision = create_backup(&db, &dir.path().join("collision.sqlite")).unwrap();
    assert!(migrate_owned_db(&db, &collision).is_err());
}

#[test]
fn legacy_python_reader_and_writer_preserve_new_audit_rows() {
    let (dir, paths) = fixture();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let receipt = create_backup(&db, &dir.path().join("before.sqlite")).unwrap();
    migrate_owned_db(&db, &receipt).unwrap();
    let conn = Connection::open(&paths.db_path).unwrap();
    conn.execute("INSERT INTO runtime_requests(request_id,paper_id,state,spec_json) VALUES('req-preserved',8,'outcome_unknown','{}')",[]).unwrap();
    let backend = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../backend");
    let python = if cfg!(windows) {
        backend.join(".venv/Scripts/python.exe")
    } else {
        backend.join(".venv/bin/python")
    };
    let output=Command::new(python).arg("-c").arg(r#"
import asyncio,sys
from models import database
async def main():
 c=await database.connect_worker_db()
 try:
  r=await database.fetch_one('SELECT * FROM papers WHERE id=?',(8,))
  assert r['authors'] is None and r['status']=='completed'
  await database.execute_update('UPDATE papers SET notes=? WHERE id=?',('Python edit',8))
  await database.execute_insert('INSERT INTO analysis_results(paper_id,phase,result,cost_usd) VALUES(?,?,?,?)',(8,'recipe','{}',None))
  r=await database.fetch_one("SELECT state FROM runtime_requests WHERE request_id='req-preserved'")
  assert r['state']=='outcome_unknown'
 finally:
  await database.close_db()
asyncio.run(main())
"#).current_dir(&backend).env("SASOO_APP_DATA_ROOT",dir.path()).env("SASOO_ENV","production").output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        conn.query_row("SELECT notes FROM papers WHERE id=?", params![8], |r| {
            r.get::<_, String>(0)
        })
        .unwrap(),
        "Python edit"
    );
}

#[test]
fn owned_revision_does_not_hide_damaged_runtime_schema() {
    let (dir, paths) = fixture();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let before = create_backup(&db, &dir.path().join("before.sqlite")).unwrap();
    migrate_owned_db(&db, &before).unwrap();
    let unchanged = create_backup(&db, &dir.path().join("unchanged.sqlite")).unwrap();
    assert_eq!(migrate_owned_db(&db, &unchanged).unwrap().revision, 1);
    let conn = Connection::open(&paths.db_path).unwrap();
    conn.execute("DROP TABLE runtime_permits", []).unwrap();
    let damaged = create_backup(&db, &dir.path().join("damaged.sqlite")).unwrap();
    assert!(migrate_owned_db(&db, &damaged).is_err());
}

#[test]
fn named_tables_with_incompatible_legacy_columns_do_not_receive_migrations() {
    let (dir, paths) = fixture();
    let conn = Connection::open(&paths.db_path).unwrap();
    conn.execute_batch("DROP TABLE settings; CREATE TABLE settings(unrelated TEXT)")
        .unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    assert!(!inspect_schema(&db).unwrap().legacy_readable);
    let receipt = create_backup(&db, &dir.path().join("before.sqlite")).unwrap();
    assert!(migrate_owned_db(&db, &receipt).is_err());
    assert_eq!(
        conn.query_row(
            "SELECT COUNT(*) FROM sqlite_schema WHERE name='runtime_server_state'",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        0
    );
}
