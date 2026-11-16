use super::db::{Db, db_sql_error};
use crate::{
    error::{Result, SasooError},
    types::{ExecutionId, Hash256, PaperEpoch, PaperId, ProviderId, SecretRef},
};
use rusqlite::{OptionalExtension, TransactionBehavior, params};
use std::time::{SystemTime, UNIX_EPOCH};

pub(crate) struct NewExecution {
    pub execution_id: ExecutionId,
    pub paper_id: PaperId,
    pub paper_epoch: PaperEpoch,
    pub source_sha256: Hash256,
    pub extraction_version: String,
    pub config_bytes: Vec<u8>,
    pub config_hash: Hash256,
    pub settings_revision: i64,
    pub secret_refs: Vec<SecretRef>,
}

pub(crate) async fn enqueue_execution(db: &Db, input: NewExecution) -> Result<()> {
    let owner_id = db.owner_id()?.to_string();
    let created_at_ms = i64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| SasooError::Internal("Clock is before the Unix epoch".into()))?
            .as_millis(),
    )
    .map_err(|_| SasooError::Internal("Clock is outside the supported range".into()))?;
    db.call(move |conn| {
        let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).map_err(db_sql_error)?;
        let state:Option<(String,i64,i64)>=tx.query_row("SELECT owner_id,quiescing,settings_revision FROM runtime_server_state WHERE singleton=1 AND schema_revision=1",[],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional().map_err(db_sql_error)?;
        let Some((current_owner,quiescing,revision))=state else {return Err(SasooError::Unsupported("An owned runtime schema is required before accepting an analysis".into()));};
        if current_owner!=owner_id || quiescing!=0 { return Err(SasooError::Conflict("Server ownership changed or shutdown has begun".into())); }
        if revision!=input.settings_revision { return Err(SasooError::Conflict("Settings changed after PDF preparation; resolve the configuration again".into())); }
        let paper_exists:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM papers WHERE id=?1)",[input.paper_id.0],|row|row.get(0)).map_err(db_sql_error)?;
        let deleted:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM runtime_tombstones WHERE paper_id=?1)",[input.paper_id.0],|row|row.get(0)).map_err(db_sql_error)?;
        if !paper_exists || deleted {return Err(SasooError::NotFound("Paper no longer exists".into()));}
        let source:Option<(i64,Option<Vec<u8>>)>=tx.query_row("SELECT paper_epoch,source_sha256 FROM runtime_paper_epochs WHERE paper_id=?1",[input.paper_id.0],|row|Ok((row.get(0)?,row.get(1)?))).optional().map_err(db_sql_error)?;
        if !matches!(source,Some((epoch,Some(ref hash))) if epoch==input.paper_epoch.0 && hash.as_slice()==input.source_sha256) {
            return Err(SasooError::Conflict("Paper source changed after PDF preparation".into()));
        }
        let active:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM analysis_runs WHERE paper_id=?1 AND status IN ('queued','running')) OR EXISTS(SELECT 1 FROM runtime_executions WHERE paper_id=?1 AND state IN ('queued','claimed','running','cancelling','recovery_pending','needs_reconciliation','paused_for_quit'))",[input.paper_id.0],|row|row.get(0)).map_err(db_sql_error)?;
        if active {return Err(SasooError::Conflict("Analysis is already queued, active or awaiting reconciliation".into()));}
        for reference in &input.secret_refs {
            let provider=match reference.provider {ProviderId::OpenAi=>"openai",ProviderId::Gemini=>"gemini"};
            let epoch:Option<i64>=tx.query_row("SELECT epoch FROM runtime_credential_epochs WHERE provider=?1",[provider],|row|row.get(0)).optional().map_err(db_sql_error)?;
            if epoch!=Some(reference.epoch.0) {return Err(SasooError::CredentialUnavailable("Credential reference changed or is unavailable".into()));}
            let key=format!("{provider}_api_key");
            let present:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM settings WHERE key=?1 AND value IS NOT NULL AND length(value)>0)",[key],|row|row.get(0)).map_err(db_sql_error)?;
            if !present {return Err(SasooError::CredentialUnavailable("A selected provider has no stored credential".into()));}
        }
        let epoch=input.paper_epoch.0.checked_add(1).ok_or_else(||SasooError::Conflict("Paper epoch is exhausted".into()))?;
        let execution=input.execution_id.0.to_string();
        tx.execute("INSERT INTO runtime_executions(execution_id,paper_id,paper_epoch,source_sha256,extraction_version,config_bytes,config_hash,settings_revision,state,created_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,'queued',?9)",params![execution,input.paper_id.0,epoch,input.source_sha256.as_slice(),input.extraction_version,input.config_bytes,input.config_hash.as_slice(),input.settings_revision,created_at_ms]).map_err(db_sql_error)?;
        // Starting a new analysis invalidates older interactive operation scopes.
        let changed=tx.execute("UPDATE runtime_paper_epochs SET paper_epoch=?1,current_execution_id=?2,updated_at_ms=?3 WHERE paper_id=?4 AND paper_epoch=?5 AND source_sha256=?6",params![epoch,execution,created_at_ms,input.paper_id.0,input.paper_epoch.0,input.source_sha256.as_slice()]).map_err(db_sql_error)?;
        if changed!=1 {return Err(SasooError::Conflict("Prepared paper epoch no longer has write authority".into()));}
        let queued=tx.execute("INSERT INTO analysis_runs(paper_id,status,generation,current_phase,progress_pct,cancel_requested,attempts,pid,error_message,started_at,last_attempt_at,heartbeat_at,updated_at) VALUES(?1,'queued',0,NULL,0,0,0,NULL,NULL,strftime('%Y-%m-%dT%H:%M:%fZ','now'),NULL,NULL,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(paper_id) DO UPDATE SET status='queued',current_phase=NULL,progress_pct=0,cancel_requested=0,attempts=0,pid=NULL,error_message=NULL,started_at=excluded.started_at,last_attempt_at=NULL,heartbeat_at=NULL,updated_at=excluded.updated_at WHERE analysis_runs.status NOT IN ('queued','running')",[input.paper_id.0]).map_err(db_sql_error)?;
        if queued!=1 {return Err(SasooError::Conflict("Analysis was accepted by another request".into()));}
        let changed=tx.execute("UPDATE papers SET status='analyzing' WHERE id=?1",[input.paper_id.0]).map_err(db_sql_error)?;
        if changed!=1 {return Err(SasooError::NotFound("Paper disappeared during acceptance".into()));}
        tx.commit().map_err(db_sql_error)
    }).await
}
