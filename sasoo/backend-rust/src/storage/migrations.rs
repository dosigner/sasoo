use super::db::{Db, db_sql_error};
use crate::error::{Result, SasooError};
use rusqlite::{Connection, OptionalExtension, types::ValueRef};
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::Read,
    path::{Path, PathBuf},
    time::Duration,
};

const RUNTIME_SQL: &str = include_str!("../../migrations/0001_runtime.sql");
const ISOLATION_MARKER: &str = "synthetic-only\n";

#[derive(Debug)]
pub struct BackupReceipt {
    pub destination: PathBuf,
    pub source: PathBuf,
    pub destination_sha256: [u8; 32],
    pub source_content_sha256: [u8; 32],
    pub source_schema_sha256: [u8; 32],
    owner_id: String,
}
#[derive(Debug)]
pub struct MigrationReport {
    pub revision: i64,
    pub legacy_rows_changed: usize,
}
#[derive(Debug)]
pub struct SchemaCompatibility {
    pub legacy_readable: bool,
    pub runtime_revision: Option<i64>,
    pub runtime_collisions: Vec<String>,
}

fn quote_identifier(name: &str) -> String {
    format!("\"{}\"", name.replace('"', "\"\""))
}
fn hash_file(path: &Path) -> Result<[u8; 32]> {
    let mut file = File::open(path)?;
    let mut hash = Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        let count = file.read(&mut buf)?;
        if count == 0 {
            break;
        }
        hash.update(&buf[..count]);
    }
    Ok(hash.finalize().into())
}
fn schema_rows(conn: &Connection) -> Result<Vec<(String, String, String)>> {
    let mut stmt = conn
        .prepare("SELECT type,name,COALESCE(sql,'') FROM sqlite_schema ORDER BY type,name")
        .map_err(db_sql_error)?;
    stmt.query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))
        .map_err(db_sql_error)?
        .collect::<rusqlite::Result<Vec<_>>>()
        .map_err(db_sql_error)
}
fn schema_hash(conn: &Connection) -> Result<[u8; 32]> {
    let mut hash = Sha256::new();
    for row in schema_rows(conn)? {
        for value in [row.0, row.1, row.2] {
            hash.update((value.len() as u64).to_be_bytes());
            hash.update(value.as_bytes());
        }
    }
    Ok(hash.finalize().into())
}
fn content_hash(conn: &Connection) -> Result<[u8; 32]> {
    let mut hash = Sha256::new();
    hash.update(schema_hash(conn)?);
    for (kind, name, _) in schema_rows(conn)? {
        if kind != "table" {
            continue;
        }
        let columns = conn
            .prepare(&format!(
                "SELECT * FROM {} LIMIT 0",
                quote_identifier(&name)
            ))
            .map_err(db_sql_error)?
            .column_count();
        let order = (1..=columns)
            .map(|i| i.to_string())
            .collect::<Vec<_>>()
            .join(",");
        let mut stmt = conn
            .prepare(&format!(
                "SELECT * FROM {} ORDER BY {order}",
                quote_identifier(&name)
            ))
            .map_err(db_sql_error)?;
        let mut rows = stmt.query([]).map_err(db_sql_error)?;
        hash.update((name.len() as u64).to_be_bytes());
        hash.update(name.as_bytes());
        while let Some(row) = rows.next().map_err(db_sql_error)? {
            hash.update([255]);
            for i in 0..columns {
                match row.get_ref(i).map_err(db_sql_error)? {
                    ValueRef::Null => hash.update([0]),
                    ValueRef::Integer(v) => {
                        hash.update([1]);
                        hash.update(v.to_be_bytes());
                    }
                    ValueRef::Real(v) => {
                        hash.update([2]);
                        hash.update(v.to_bits().to_be_bytes());
                    }
                    ValueRef::Text(v) => {
                        hash.update([3]);
                        hash.update((v.len() as u64).to_be_bytes());
                        hash.update(v);
                    }
                    ValueRef::Blob(v) => {
                        hash.update([4]);
                        hash.update((v.len() as u64).to_be_bytes());
                        hash.update(v);
                    }
                }
            }
        }
    }
    for pragma in ["user_version", "application_id"] {
        let value: i64 = conn
            .pragma_query_value(None, pragma, |r| r.get(0))
            .map_err(db_sql_error)?;
        hash.update(value.to_be_bytes());
    }
    Ok(hash.finalize().into())
}

fn inspect_connection(conn: &Connection) -> Result<SchemaCompatibility> {
    let schema = schema_rows(conn)?;
    let has = |name: &str| {
        schema
            .iter()
            .any(|(kind, n, _)| kind == "table" && n == name)
    };
    let mut legacy_readable = ["papers", "settings", "analysis_results", "analysis_runs"]
        .into_iter()
        .all(has);
    for (table, required) in [
        ("papers", &["id", "title", "folder_name", "status"][..]),
        ("settings", &["key", "value"][..]),
        (
            "analysis_results",
            &[
                "id",
                "paper_id",
                "phase",
                "result",
                "cost_usd",
                "created_at",
            ][..],
        ),
        (
            "analysis_runs",
            &["paper_id", "status", "generation", "cancel_requested"][..],
        ),
    ] {
        if has(table) {
            let mut columns = conn
                .prepare(&format!("PRAGMA table_info({})", quote_identifier(table)))
                .map_err(db_sql_error)?;
            let names = columns
                .query_map([], |row| row.get::<_, String>(1))
                .map_err(db_sql_error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(db_sql_error)?;
            legacy_readable &= required
                .iter()
                .all(|name| names.iter().any(|actual| actual == name));
        }
    }
    let runtime_revision = if has("runtime_server_state") {
        conn.query_row(
            "SELECT schema_revision FROM runtime_server_state WHERE singleton=1",
            [],
            |r| r.get::<_, i64>(0),
        )
        .optional()
        .map_err(db_sql_error)?
    } else {
        None
    };
    let runtime_collisions = if runtime_revision.is_none() {
        schema
            .into_iter()
            .filter(|(_, name, _)| name.starts_with("runtime_"))
            .map(|(_, name, _)| name)
            .collect()
    } else {
        vec![]
    };
    Ok(SchemaCompatibility {
        legacy_readable,
        runtime_revision,
        runtime_collisions,
    })
}

fn validate_runtime_schema(conn: &Connection) -> Result<()> {
    let expected = Connection::open_in_memory().map_err(db_sql_error)?;
    expected.execute_batch(RUNTIME_SQL).map_err(db_sql_error)?;
    let runtime_only = |rows: Vec<(String, String, String)>| {
        rows.into_iter()
            .filter(|(_, name, _)| {
                name.starts_with("runtime_")
                    || name.starts_with("idx_runtime_")
                    || name.starts_with("sqlite_autoindex_runtime_")
            })
            .collect::<Vec<_>>()
    };
    if runtime_only(schema_rows(conn)?) != runtime_only(schema_rows(&expected)?) {
        return Err(SasooError::Unsupported(
            "Runtime schema differs from the owned migration; preserve it for reconciliation"
                .into(),
        ));
    }
    Ok(())
}

pub fn inspect_schema(db: &Db) -> Result<SchemaCompatibility> {
    db.blocking_call(|conn| inspect_connection(conn))
}

pub fn create_backup(db: &Db, destination: &Path) -> Result<BackupReceipt> {
    let owner_id = db.owner_id()?.to_string();
    let root = db
        .path()
        .parent()
        .ok_or_else(|| SasooError::InvalidInput("Database root is missing".into()))?;
    // A Rust owner lock cannot attest that the legacy Python owner has stopped.
    if std::fs::read_to_string(root.join(".sasoo-rust-isolated-fixture"))
        .ok()
        .as_deref()
        != Some(ISOLATION_MARKER)
    {
        return Err(SasooError::Forbidden("Live backup/migration requires D03 frozen-writes evidence; this milestone accepts synthetic fixtures only".into()));
    }
    let parent = destination
        .parent()
        .ok_or_else(|| SasooError::InvalidInput("Backup directory is missing".into()))?
        .canonicalize()?;
    if !parent.starts_with(root) {
        return Err(SasooError::Forbidden(
            "Synthetic backup must remain inside its isolated app-data root".into(),
        ));
    }
    let name = destination
        .file_name()
        .ok_or_else(|| SasooError::InvalidInput("Backup filename is missing".into()))?;
    let destination = parent.join(name);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&destination)?;
    drop(file);
    let target = destination.clone();
    let source = db.path().to_path_buf();
    let (source_content_sha256, source_schema_sha256) = db.blocking_call(move |conn| {
        let mut dest = Connection::open(&target).map_err(db_sql_error)?;
        {
            let backup = rusqlite::backup::Backup::new(conn, &mut dest).map_err(db_sql_error)?;
            backup
                .run_to_completion(64, Duration::from_millis(5), None)
                .map_err(db_sql_error)?;
        }
        // Hash the consistent destination, not independently read source pages.
        Ok((content_hash(&dest)?, schema_hash(&dest)?))
    })?;
    File::open(&destination)?.sync_all()?;
    let destination_sha256 = hash_file(&destination)?;
    Ok(BackupReceipt {
        destination,
        source,
        destination_sha256,
        source_content_sha256,
        source_schema_sha256,
        owner_id,
    })
}

pub fn migrate_owned_db(db: &Db, receipt: &BackupReceipt) -> Result<MigrationReport> {
    if db.owner_id()? != receipt.owner_id
        || db.path() != receipt.source
        || hash_file(&receipt.destination)? != receipt.destination_sha256
    {
        return Err(SasooError::Conflict(
            "Backup receipt does not match this owner/source or its bytes changed".into(),
        ));
    }
    let source_content = receipt.source_content_sha256;
    let source_schema = receipt.source_schema_sha256;
    let owner_id = receipt.owner_id.clone();
    db.blocking_call(move |conn| {
        let tx = conn
            .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
            .map_err(db_sql_error)?;
        if content_hash(&tx)? != source_content || schema_hash(&tx)? != source_schema {
            return Err(SasooError::Conflict(
                "Database changed after the consistent backup".into(),
            ));
        }
        let compatibility = inspect_connection(&tx)?;
        if !compatibility.legacy_readable {
            return Err(SasooError::Unsupported(
                "Required legacy tables are missing; no defaults or schema were synthesized".into(),
            ));
        }
        if !compatibility.runtime_collisions.is_empty() {
            return Err(SasooError::Conflict(
                "Existing runtime names do not have an owned schema revision".into(),
            ));
        }
        match compatibility.runtime_revision {
            Some(1) => {
                validate_runtime_schema(&tx)?;
                return Ok(MigrationReport {
                    revision: 1,
                    legacy_rows_changed: 0,
                });
            }
            Some(_) => {
                return Err(SasooError::Unsupported(
                    "Runtime schema revision is unsupported".into(),
                ));
            }
            None => {}
        }
        tx.execute_batch(RUNTIME_SQL).map_err(db_sql_error)?;
        tx.execute(
            "INSERT INTO runtime_server_state(singleton,schema_revision,owner_id) VALUES(1,1,?1)",
            [owner_id],
        )
        .map_err(db_sql_error)?;
        tx.commit().map_err(db_sql_error)?;
        Ok(MigrationReport {
            revision: 1,
            legacy_rows_changed: 0,
        })
    })
}

/// Add the legacy discussion context column only after an unchanged isolated backup.
pub fn migrate_discussion_context(db: &Db, receipt: &BackupReceipt) -> Result<bool> {
    if db.owner_id()? != receipt.owner_id
        || db.path() != receipt.source
        || hash_file(&receipt.destination)? != receipt.destination_sha256
    {
        return Err(SasooError::Conflict(
            "Backup receipt does not match this owner/source or its bytes changed".into(),
        ));
    }
    let root = db
        .path()
        .parent()
        .ok_or_else(|| SasooError::InvalidInput("Database root is missing".into()))?;
    if std::fs::read_to_string(root.join(".sasoo-rust-isolated-fixture"))
        .ok()
        .as_deref()
        != Some(ISOLATION_MARKER)
    {
        return Err(SasooError::Forbidden(
            "Discussion migration requires an isolated fixture".into(),
        ));
    }
    let source_content = receipt.source_content_sha256;
    let source_schema = receipt.source_schema_sha256;
    db.blocking_call(move |conn| {
        let tx = conn
            .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
            .map_err(db_sql_error)?;
        if content_hash(&tx)? != source_content || schema_hash(&tx)? != source_schema {
            return Err(SasooError::Conflict(
                "Database changed after the consistent backup".into(),
            ));
        }
        let columns = {
            let mut statement = tx
                .prepare("PRAGMA table_info(discussion_messages)")
                .map_err(db_sql_error)?;
            let values = statement
                .query_map([], |row| {
                    Ok((row.get::<_, String>(1)?, row.get::<_, String>(2)?))
                })
                .map_err(db_sql_error)?;
            values
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(db_sql_error)?
        };
        if columns.is_empty() {
            return Err(SasooError::Unsupported(
                "Discussion table is missing".into(),
            ));
        }
        if let Some((_, kind)) = columns.iter().find(|(name, _)| name == "context_json") {
            if !kind.eq_ignore_ascii_case("text") {
                return Err(SasooError::Conflict(
                    "Existing discussion context column has an incompatible type".into(),
                ));
            }
            tx.commit().map_err(db_sql_error)?;
            return Ok(false);
        }
        tx.execute(
            "ALTER TABLE discussion_messages ADD COLUMN context_json TEXT",
            [],
        )
        .map_err(db_sql_error)?;
        tx.commit().map_err(db_sql_error)?;
        Ok(true)
    })
}

/// Add only the opt-in PDF candidate catalog to an unchanged synthetic backup.
pub fn migrate_pdf_candidate(db: &Db, receipt: &BackupReceipt) -> Result<()> {
    if db.owner_id()? != receipt.owner_id
        || db.path() != receipt.source
        || hash_file(&receipt.destination)? != receipt.destination_sha256
    {
        return Err(SasooError::Conflict("PDF backup receipt no longer matches".into()));
    }
    let content = receipt.source_content_sha256;
    let schema = receipt.source_schema_sha256;
    db.blocking_call(move |conn| {
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(db_sql_error)?;
        if content_hash(&tx)? != content || schema_hash(&tx)? != schema {
            return Err(SasooError::Conflict("Database changed after the PDF backup".into()));
        }
        crate::http::papers::ensure_idle(&tx)?;
        tx.execute_batch(include_str!("../../migrations/pdf_candidate.sql")).map_err(db_sql_error)?;
        tx.commit().map_err(db_sql_error)
    })
}

/// Add recovery identities without promoting unpublished files.
pub fn migrate_pdf_process(db: &Db, receipt: &BackupReceipt) -> Result<()> {
    if db.owner_id()? != receipt.owner_id
        || db.path() != receipt.source
        || hash_file(&receipt.destination)? != receipt.destination_sha256
    {
        return Err(SasooError::Conflict("PDF backup receipt no longer matches".into()));
    }
    let content = receipt.source_content_sha256;
    let schema = receipt.source_schema_sha256;
    db.blocking_call(move |conn| {
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(db_sql_error)?;
        if content_hash(&tx)? != content || schema_hash(&tx)? != schema {
            return Err(SasooError::Conflict("Database changed after the PDF backup".into()));
        }
        crate::http::papers::ensure_idle(&tx)?;
        tx.execute_batch(include_str!("../../migrations/pdf_process.sql")).map_err(db_sql_error)?;
        tx.commit().map_err(db_sql_error)
    })
}

/// Upgrade only an unchanged, backed-up synthetic runtime to FigureExplain revision 2.
pub fn migrate_figure_runtime(db: &Db, receipt: &BackupReceipt) -> Result<MigrationReport> {
    if db.owner_id()? != receipt.owner_id
        || db.path() != receipt.source
        || hash_file(&receipt.destination)? != receipt.destination_sha256
    {
        return Err(SasooError::Conflict(
            "Backup receipt does not match this owner/source or its bytes changed".into(),
        ));
    }
    let root = db
        .path()
        .parent()
        .ok_or_else(|| SasooError::InvalidInput("Database root is missing".into()))?;
    let marker = root.join(".sasoo-rust-isolated-fixture");
    if marker.symlink_metadata()?.file_type().is_symlink()
        || std::fs::read_to_string(marker)? != ISOLATION_MARKER
    {
        return Err(SasooError::Forbidden(
            "FigureExplain migration accepts synthetic fixtures only".into(),
        ));
    }
    let source_content = receipt.source_content_sha256;
    let source_schema = receipt.source_schema_sha256;
    let owner = receipt.owner_id.clone();
    db.blocking_call(move |conn| {
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(db_sql_error)?;
        if content_hash(&tx)? != source_content || schema_hash(&tx)? != source_schema {
            return Err(SasooError::Conflict("Database changed after the consistent backup".into()));
        }
        let compatibility = inspect_connection(&tx)?;
        match compatibility.runtime_revision {
            Some(1) => validate_runtime_schema(&tx)?,
            Some(2) => {
                validate_figure_runtime_schema(&tx)?;
                return Ok(MigrationReport { revision: 2, legacy_rows_changed: 0 });
            }
            _ => return Err(SasooError::Unsupported("FigureExplain requires an owned revision 1 or 2 runtime".into())),
        }
        let authorized: bool = tx.query_row("SELECT owner_id=?1 AND quiescing=0 FROM runtime_server_state WHERE singleton=1", [&owner], |row| row.get(0)).map_err(db_sql_error)?;
        if !authorized { return Err(SasooError::FenceLost("Runtime owner changed or shutdown has begun".into())); }
        tx.execute_batch(include_str!("../../migrations/0002_figure_explain.sql")).map_err(db_sql_error)?;
        let changed = tx.execute("UPDATE runtime_server_state SET schema_revision=2 WHERE singleton=1 AND schema_revision=1 AND owner_id=?1 AND quiescing=0", [&owner]).map_err(db_sql_error)?;
        if changed != 1 { return Err(SasooError::FenceLost("Runtime schema authority changed".into())); }
        validate_figure_runtime_schema(&tx)?;
        tx.commit().map_err(db_sql_error)?;
        Ok(MigrationReport { revision: 2, legacy_rows_changed: 0 })
    })
}

pub(crate) fn validate_figure_runtime_schema(conn: &Connection) -> Result<()> {
    let expected = Connection::open_in_memory().map_err(db_sql_error)?;
    expected.execute_batch(RUNTIME_SQL).map_err(db_sql_error)?;
    expected
        .execute_batch(include_str!("../../migrations/0002_figure_explain.sql"))
        .map_err(db_sql_error)?;
    let owned = |rows: Vec<(String, String, String)>| {
        rows.into_iter()
            .filter(|(_, name, _)| {
                name.starts_with("runtime_")
                    || name.starts_with("idx_runtime_")
                    || name.starts_with("sqlite_autoindex_runtime_")
            })
            .collect::<Vec<_>>()
    };
    if owned(schema_rows(conn)?) != owned(schema_rows(&expected)?) {
        return Err(SasooError::Unsupported(
            "FigureExplain runtime schema differs from its owned migration".into(),
        ));
    }
    Ok(())
}
