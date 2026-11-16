use rusqlite::Connection;
use sasoo_backend::{
    storage::{
        db::{DbAccess, open_db},
        legacy::{latest_results, read_paper},
        paths::RuntimePaths,
    },
    types::PaperId,
};
use tempfile::TempDir;

#[test]
fn connection_policy_latest_tie_and_nullable_legacy_fields_are_preserved() {
    let dir = TempDir::new().unwrap();
    let root = dir.path().to_path_buf();
    let paths = RuntimePaths {
        app_data_root: root.clone(),
        db_path: root.join("sasoo.db"),
        config_path: root.join("config.json"),
        default_library_root: root.clone(),
        library_root: root.clone(),
        library_search_roots: vec![root.clone()],
        owner_lock_path: root.join("owner.lock"),
    };
    let conn = Connection::open(&paths.db_path).unwrap();
    conn.execute_batch(include_str!("fixtures/legacy/schema.sql"))
        .unwrap();
    conn.execute("INSERT INTO papers(id,title,folder_name,analysis_focus,authors) VALUES(1,'논문','one','{\"focus\":true}',NULL)",[]).unwrap();
    conn.execute("INSERT INTO analysis_results(id,paper_id,phase,result,cost_usd,created_at) VALUES(3,1,'recipe','{\"old\":true}',1.0,'same'),(4,1,'recipe','{\"partial\":true}',NULL,'same')",[]).unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let state = db.connection_policy().unwrap();
    assert_eq!(state.journal_mode.to_lowercase(), "wal");
    assert_eq!(state.busy_timeout_ms, 5000);
    assert!(state.foreign_keys);
    let paper = read_paper(&db, PaperId(1)).unwrap().unwrap();
    assert!(paper.fields["authors"].is_null());
    assert_eq!(paper.fields["analysis_focus"], "{\"focus\":true}");
    let rows = latest_results(&db, PaperId(1)).unwrap();
    assert_eq!(rows["recipe"].id, 4);
    assert!(rows["recipe"].cost_usd.is_none());
    assert_eq!(rows["recipe"].result, "{\"partial\":true}");
    assert!(read_paper(&db, PaperId(999)).unwrap().is_none());
    let worker = open_db(&paths, DbAccess::Worker).unwrap();
    assert_eq!(worker.connection_policy().unwrap().busy_timeout_ms, 5000);
}

#[test]
fn missing_read_only_or_worker_database_is_not_created() {
    let dir = TempDir::new().unwrap();
    let root = dir.path().to_path_buf();
    let paths = RuntimePaths {
        app_data_root: root.clone(),
        db_path: root.join("absent.sqlite"),
        config_path: root.join("config.json"),
        default_library_root: root.clone(),
        library_root: root.clone(),
        library_search_roots: vec![root.clone()],
        owner_lock_path: root.join("owner.lock"),
    };
    assert!(open_db(&paths, DbAccess::ReadOnly).is_err());
    assert!(open_db(&paths, DbAccess::Worker).is_err());
    assert!(!paths.db_path.exists());
    assert!(!paths.owner_lock_path.exists());
}

#[test]
fn read_only_and_owner_peer_connections_keep_access_and_ownership_boundaries() {
    let dir = TempDir::new().unwrap();
    let root = dir.path().to_path_buf();
    let paths = RuntimePaths {
        app_data_root: root.clone(),
        db_path: root.join("sasoo.db"),
        config_path: root.join("config.json"),
        default_library_root: root.clone(),
        library_root: root.clone(),
        library_search_roots: vec![root.clone()],
        owner_lock_path: root.join("owner.lock"),
    };
    let conn = Connection::open(&paths.db_path).unwrap();
    conn.execute_batch(include_str!("fixtures/legacy/schema.sql"))
        .unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let peer = db.owner_peer().unwrap();
    assert!(open_db(&paths, DbAccess::ServerOwner).is_err());
    let reader = open_db(&paths, DbAccess::ReadOnly).unwrap();
    assert!(reader.owner_peer().is_err());
    assert!(
        reader
            .blocking_call(|c| c
                .execute(
                    "INSERT INTO papers(title,folder_name) VALUES('blocked','blocked')",
                    []
                )
                .map(|_| ())
                .map_err(sasoo_backend::storage::db::db_sql_error))
            .is_err()
    );
    peer.blocking_call(|c| {
        c.busy_timeout(std::time::Duration::from_millis(20))
            .map_err(sasoo_backend::storage::db::db_sql_error)
    })
    .unwrap();
    conn.execute_batch("BEGIN IMMEDIATE").unwrap();
    let blocked = peer.blocking_call(|c| {
        c.execute(
            "INSERT INTO papers(title,folder_name) VALUES('busy','busy')",
            [],
        )
        .map(|_| ())
        .map_err(sasoo_backend::storage::db::db_sql_error)
    });
    assert!(matches!(
        blocked,
        Err(sasoo_backend::error::SasooError::StorageBusy(_))
    ));
    conn.execute_batch("ROLLBACK").unwrap();
    drop(db);
    assert!(open_db(&paths, DbAccess::ServerOwner).is_err());
    peer.blocking_call(|c| {
        c.execute(
            "INSERT INTO papers(title,folder_name) VALUES('safe retry','safe')",
            [],
        )
        .map(|_| ())
        .map_err(sasoo_backend::storage::db::db_sql_error)
    })
    .unwrap();
    assert_eq!(
        conn.query_row("SELECT COUNT(*) FROM papers", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        1
    );
}
