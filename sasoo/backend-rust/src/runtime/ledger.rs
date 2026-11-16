//! W03 request ledger. One local ID per provider request, issued before dispatch.
//!
//! State vocabulary is shared with `figure_explain.rs`:
//! `state` is prepared, dispatched, settled, outcome_unknown or recovery_unknown;
//! `terminal` is complete, incomplete or conflicting.
use crate::{
    analysis::pricing::KnownUsage,
    error::{Result, SasooError},
    providers::types::{NewRequestSpec, ProviderOutcome, RequestOutcome, RequestSpec, UsageState},
    storage::db::{Db, db_sql_error},
    types::{Json, LocalRequestId, PublicationScope, UtcMillis},
};
use base64::{Engine, engine::general_purpose::STANDARD as B64};
use rusqlite::{OptionalExtension, TransactionBehavior, params};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
use uuid::Uuid;

pub type RequestScope = PublicationScope;

pub struct PreparedRequest {
    pub spec: RequestSpec,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReplayReceipt {
    pub request_id: LocalRequestId,
    /// False when the same spool bytes were already recorded.
    pub inserted: bool,
}

/// Immutable spool record. `received_at` stays out so a re-delivered
/// identical response hashes to the same event.
#[derive(Serialize, Deserialize)]
struct SpoolRecord {
    request_id: LocalRequestId,
    remote_id: Option<String>,
    terminal: String,
    content: Option<Json>,
    usage: Json,
    raw_response_b64: String,
}

pub struct Ledger {
    db: Db,
    spool_root: PathBuf,
}

impl Ledger {
    pub fn open(db: Db, spool_root: PathBuf) -> Result<Self> {
        if !spool_root.is_absolute() {
            return Err(SasooError::InvalidInput(
                "Ledger spool root must be absolute".into(),
            ));
        }
        fs::create_dir_all(&spool_root)?;
        let spool_root = spool_root.canonicalize()?;
        Ok(Self { db, spool_root })
    }

    pub fn spool_root(&self) -> &Path {
        &self.spool_root
    }

    pub fn prepare_request(
        &self,
        scope: &RequestScope,
        spec: NewRequestSpec,
    ) -> Result<PreparedRequest> {
        let id = LocalRequestId(Uuid::new_v4());
        let spec_json = serde_json::to_string(&json!({"scope": scope, "spec": &spec}))
            .map_err(|_| SasooError::InvalidInput("Request spec cannot be encoded".into()))?;
        let (paper, execution, attempt, operation, import, generation) = match scope {
            PublicationScope::Analysis(s) => (
                Some(s.paper_id.0),
                Some(s.execution_id.0.to_string()),
                Some(s.attempt_id.0.to_string()),
                None,
                None,
                Some(s.generation.0),
            ),
            PublicationScope::Operation(s) => (
                Some(s.paper_id.0),
                None,
                None,
                Some(s.operation_id.to_string()),
                None,
                None,
            ),
            PublicationScope::Import(s) => {
                (None, None, None, None, Some(s.import_id.to_string()), None)
            }
        };
        let created = now()?;
        self.db.blocking_call(move |conn| {
            conn.execute(
                "INSERT INTO runtime_requests(request_id,paper_id,execution_id,attempt_id,operation_id,import_id,generation,state,spec_json,created_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7,'prepared',?8,?9)",
                params![id.0.to_string(), paper, execution, attempt, operation, import, generation, spec_json, created],
            )
            .map_err(db_sql_error)?;
            Ok(())
        })?;
        Ok(PreparedRequest {
            spec: RequestSpec { id, new: spec },
        })
    }

    /// Grants the single dispatch. A second call is a conflict, never a re-send.
    pub fn mark_dispatched(&self, id: LocalRequestId) -> Result<()> {
        let request = id.0.to_string();
        let at = now()?;
        self.db.blocking_call(move |conn| {
            let tx = conn
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(db_sql_error)?;
            let state = request_state(&tx, &request)?;
            if state != "prepared" {
                return Err(SasooError::Conflict(format!(
                    "Request is {state}, not prepared"
                )));
            }
            tx.execute(
                "UPDATE runtime_requests SET state='dispatched',dispatched_at_ms=?1 WHERE request_id=?2 AND state='prepared'",
                params![at, request],
            )
            .map_err(db_sql_error)?;
            tx.commit().map_err(db_sql_error)
        })
    }

    /// Writes the durable spool file first, then records it. A crash between
    /// the two is repaired by `replay_spool` on the same file.
    pub fn append_outcome(&self, id: LocalRequestId, outcome: &ProviderOutcome) -> Result<()> {
        let terminal = terminal_name(outcome.terminal)?;
        let request = id.0.to_string();
        let state = self
            .db
            .blocking_call(move |conn| request_state(conn, &request))?;
        if state == "prepared" {
            return Err(SasooError::Incomplete(
                "Outcome has no recorded dispatch".into(),
            ));
        }
        let record = SpoolRecord {
            request_id: id,
            remote_id: outcome.remote_id.clone(),
            terminal: terminal.into(),
            content: outcome.content.clone(),
            usage: usage_json(&outcome.usage),
            raw_response_b64: B64.encode(&outcome.raw_response),
        };
        let bytes = serde_json::to_vec(&record)
            .map_err(|_| SasooError::InvalidInput("Outcome cannot be encoded".into()))?;
        let path = self.write_immutable(&format!("{}-{}.json", id.0, hex(&bytes)), &bytes)?;
        self.ingest(&path, Some(outcome.received_at))?;
        Ok(())
    }

    /// Records one spool file again after a restart. Idempotent per file.
    pub fn replay_spool(&self, path: &Path) -> Result<ReplayReceipt> {
        self.ingest(path, None)
    }

    fn ingest(&self, path: &Path, received_at: Option<UtcMillis>) -> Result<ReplayReceipt> {
        let path = path.canonicalize()?;
        if path.parent() != Some(self.spool_root.as_path()) || !path.is_file() {
            return Err(SasooError::Forbidden(
                "Outcome must be a ledger spool file".into(),
            ));
        }
        let bytes = fs::read(&path)?;
        let record: SpoolRecord = serde_json::from_slice(&bytes)
            .map_err(|_| SasooError::Incomplete("Spool record is invalid".into()))?;
        let event = hex(&bytes);
        let name = format!("{}-{event}.json", record.request_id.0);
        if path.file_name().and_then(|s| s.to_str()) != Some(name.as_str()) {
            return Err(SasooError::Incomplete(
                "Spool event hash does not match its bytes".into(),
            ));
        }
        let payload = String::from_utf8(bytes)
            .map_err(|_| SasooError::Incomplete("Spool is not UTF-8".into()))?;
        let usage_state = record
            .usage
            .get("state")
            .and_then(Json::as_str)
            .unwrap_or("unknown")
            .to_owned();
        let id = record.request_id;
        let received = match received_at {
            Some(at) => at,
            None => now()?,
        };
        let settled = now()?;
        self.db.blocking_call(move |conn| {
            let tx = conn
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(db_sql_error)?;
            let request = id.0.to_string();
            let state = request_state(&tx, &request)?;
            if state == "prepared" {
                return Err(SasooError::Incomplete(
                    "Outcome has no recorded dispatch".into(),
                ));
            }
            let inserted = tx
                .execute(
                    "INSERT INTO runtime_usage_events(event_id,request_id,event_hash,payload_json,usage_state,received_at_ms) VALUES(?1,?2,?3,?4,?5,?6) ON CONFLICT(request_id,event_hash) DO NOTHING",
                    params![Uuid::new_v4().to_string(), request, event, payload, usage_state, received],
                )
                .map_err(db_sql_error)?;
            if inserted == 0 {
                tx.commit().map_err(db_sql_error)?;
                return Ok(ReplayReceipt { request_id: id, inserted: false });
            }
            let count: i64 = tx
                .query_row(
                    "SELECT COUNT(*) FROM runtime_usage_events WHERE request_id=?1",
                    [&request],
                    |r| r.get(0),
                )
                .map_err(db_sql_error)?;
            let terminal = if count > 1 { "conflicting" } else { record.terminal.as_str() };
            if count > 1 {
                tx.execute(
                    "UPDATE runtime_usage_events SET usage_state='conflicting' WHERE request_id=?1",
                    [&request],
                )
                .map_err(db_sql_error)?;
            }
            let next = if terminal == "conflicting" || record.terminal == "unknown" {
                "outcome_unknown"
            } else {
                "settled"
            };
            let stored_terminal = if terminal == "unknown" { "incomplete" } else { terminal };
            let changed = tx
                .execute(
                    "UPDATE runtime_requests SET state=CASE WHEN state='recovery_unknown' THEN state ELSE ?1 END,terminal=?2,remote_id=COALESCE(remote_id,?3),response_ref=COALESCE(response_ref,?4),settled_at_ms=?5 WHERE request_id=?6",
                    params![next, stored_terminal, record.remote_id, name, settled, request],
                )
                .map_err(db_sql_error)?;
            if changed != 1 {
                return Err(SasooError::Conflict("Ledger request disappeared".into()));
            }
            tx.commit().map_err(db_sql_error)?;
            Ok(ReplayReceipt { request_id: id, inserted: true })
        })
    }

    fn write_immutable(&self, name: &str, bytes: &[u8]) -> Result<PathBuf> {
        let target = self.spool_root.join(name);
        if let Ok(meta) = fs::symlink_metadata(&target) {
            if meta.file_type().is_symlink() || !meta.is_file() {
                return Err(SasooError::Forbidden(
                    "Spool target is not a regular file".into(),
                ));
            }
            if fs::read(&target)? != bytes {
                return Err(SasooError::Conflict("Immutable spool bytes conflict".into()));
            }
            return Ok(target);
        }
        let pending = self.spool_root.join(format!(".pending-{}", Uuid::new_v4()));
        let mut file = OpenOptions::new().write(true).create_new(true).open(&pending)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        match fs::hard_link(&pending, &target) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                if fs::read(&target)? != bytes {
                    fs::remove_file(&pending)?;
                    return Err(SasooError::Conflict("Immutable spool bytes conflict".into()));
                }
            }
            Err(e) => return Err(e.into()),
        }
        fs::remove_file(pending)?;
        File::open(&self.spool_root)?.sync_all()?;
        Ok(target)
    }
}

fn request_state(conn: &rusqlite::Connection, request: &str) -> Result<String> {
    conn.query_row(
        "SELECT state FROM runtime_requests WHERE request_id=?1",
        [request],
        |r| r.get(0),
    )
    .optional()
    .map_err(db_sql_error)?
    .ok_or_else(|| SasooError::NotFound("Ledger request ID is not registered".into()))
}

/// Spool name of a terminal outcome. "unknown" is stored as terminal=incomplete
/// with state=outcome_unknown.
fn terminal_name(outcome: RequestOutcome) -> Result<&'static str> {
    match outcome {
        RequestOutcome::Completed => Ok("complete"),
        RequestOutcome::Incomplete | RequestOutcome::Failed => Ok("incomplete"),
        RequestOutcome::OutcomeUnknown => Ok("unknown"),
        RequestOutcome::NotDispatched | RequestOutcome::InFlight => Err(SasooError::InvalidInput(
            "Only a terminal outcome can be appended".into(),
        )),
    }
}

fn usage_json(usage: &UsageState) -> Json {
    match usage {
        UsageState::Known(KnownUsage {
            tokens_in,
            tokens_out,
            tokens_cached,
            tokens_cache_write,
        }) => json!({
            "state": "reported",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_cached": tokens_cached,
            "tokens_cache_write": tokens_cache_write,
        }),
        UsageState::Unknown { reason } => json!({"state": "unknown", "reason": reason}),
        UsageState::Conflicting { event_ids } => {
            json!({"state": "conflicting", "event_ids": event_ids})
        }
    }
}

fn hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

fn now() -> Result<UtcMillis> {
    i64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| SasooError::Internal("Clock predates the Unix epoch".into()))?
            .as_millis(),
    )
    .map_err(|_| SasooError::Internal("Clock is outside the supported range".into()))
}
