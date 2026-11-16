//! Synthetic FigureExplain lifecycle. Dispatch authority is local, never a provider call.
use crate::{
    analysis::{config::ConfigSnapshot, pricing::reported_usage},
    error::{Result, SasooError},
    storage::{
        db::{Db, db_sql_error},
        migrations::validate_figure_runtime_schema,
    },
    types::{
        Hash256, LocalRequestId, OperationKind, OperationScope, PaperEpoch, PaperId, ProviderId,
        ResourceVersion, SecretRef, VersionId,
    },
};
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
use uuid::Uuid;

#[derive(Clone)]
pub struct FigureCore {
    db: Db,
    spool_root: PathBuf,
    owner: String,
}
#[derive(Clone)]
pub struct FigureInput {
    pub paper_id: PaperId,
    pub figure_id: i64,
    pub source_bytes: Vec<u8>,
    pub asset_bytes: Vec<u8>,
    pub config: ConfigSnapshot,
    pub settings_revision: i64,
}
#[derive(Clone, Debug)]
pub struct AcceptedFigure {
    pub scope: OperationScope,
    pub request_id: LocalRequestId,
    pub created: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FigureOutcome {
    pub request_id: LocalRequestId,
    pub explanation: Option<String>,
    pub raw: String,
    pub terminal: bool,
    pub usage: Value,
}
#[derive(Debug, PartialEq, Eq)]
pub enum Publication {
    Published(VersionId),
    AlreadyPublished(VersionId),
    Rejected(String),
    Incomplete(String),
}
#[derive(Clone, Serialize, Deserialize)]
struct Identity {
    paper_id: PaperId,
    figure_id: i64,
    source_sha256: Hash256,
    asset_sha256: Hash256,
    config_hash: Hash256,
    paper_epoch: PaperEpoch,
    settings_revision: i64,
    credential_refs: Vec<SecretRef>,
}
#[derive(Clone)]
struct Snapshot {
    scope: OperationScope,
    identity: Identity,
    identity_json: String,
    identity_hash: Vec<u8>,
    owner: String,
    source: Vec<u8>,
    asset: Vec<u8>,
    config: Vec<u8>,
    config_hash: Vec<u8>,
    settings_revision: i64,
    credential_refs: Vec<SecretRef>,
    resource_version: String,
}
fn hash(bytes: &[u8]) -> Hash256 {
    Sha256::digest(bytes).into()
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
fn encode<T: Serialize>(value: &T) -> Result<String> {
    serde_json::to_string(value)
        .map_err(|_| SasooError::InvalidInput("FigureExplain value cannot be encoded".into()))
}
fn decode<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T> {
    serde_json::from_slice(bytes)
        .map_err(|_| SasooError::Incomplete("FigureExplain evidence is invalid".into()))
}
fn now() -> Result<i64> {
    i64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| SasooError::Internal("Clock predates the Unix epoch".into()))?
            .as_millis(),
    )
    .map_err(|_| SasooError::Internal("Clock is outside the supported range".into()))
}
fn resource_key(figure: i64) -> String {
    format!("figure:{figure}:explanation")
}
fn owner_check(conn: &Connection, owner: &str) -> Result<()> {
    let valid: bool = conn.query_row("SELECT EXISTS(SELECT 1 FROM runtime_server_state WHERE singleton=1 AND schema_revision=2 AND owner_id=?1 AND quiescing=0)", [owner], |r| r.get(0)).map_err(db_sql_error)?;
    if !valid {
        return Err(SasooError::FenceLost(
            "FigureExplain ownership changed or shutdown has begun".into(),
        ));
    }
    Ok(())
}
fn membership(conn: &Connection, paper: i64, figure: i64) -> Result<bool> {
    conn.query_row("SELECT EXISTS(SELECT 1 FROM papers p JOIN figures f ON f.paper_id=p.id WHERE p.id=?1 AND f.id=?2) AND NOT EXISTS(SELECT 1 FROM runtime_tombstones WHERE paper_id=?1)", params![paper,figure], |r|r.get(0)).map_err(db_sql_error)
}
fn credentials_current(conn: &Connection, refs: &[SecretRef]) -> Result<bool> {
    for reference in refs {
        let provider = match reference.provider {
            ProviderId::OpenAi => "openai",
            ProviderId::Gemini => "gemini",
        };
        let epoch: Option<i64> = conn
            .query_row(
                "SELECT epoch FROM runtime_credential_epochs WHERE provider=?1",
                [provider],
                |r| r.get(0),
            )
            .optional()
            .map_err(db_sql_error)?;
        if epoch != Some(reference.epoch.0) {
            return Ok(false);
        }
    }
    Ok(true)
}
fn snapshot(conn: &Connection, operation: &str) -> Result<Snapshot> {
    let row: Option<(String,String,Vec<u8>,String,Vec<u8>,Vec<u8>,Vec<u8>,Vec<u8>,i64,String,String,String)> = conn.query_row(
        "SELECT o.expected_versions_json,s.identity_json,s.identity_hash,s.owner_id,s.source_bytes,s.asset_bytes,s.config_bytes,s.config_hash,s.settings_revision,s.credential_refs_json,s.resource_version,o.kind FROM runtime_figure_snapshots s JOIN runtime_operations o USING(operation_id) WHERE s.operation_id=?1", [operation],
        |r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?,r.get(6)?,r.get(7)?,r.get(8)?,r.get(9)?,r.get(10)?,r.get(11)?))).optional().map_err(db_sql_error)?;
    let Some((
        versions,
        identity_json,
        identity_hash,
        owner,
        source,
        asset,
        config,
        config_hash,
        settings_revision,
        refs,
        resource_version,
        kind,
    )) = row
    else {
        return Err(SasooError::NotFound(
            "FigureExplain snapshot is missing".into(),
        ));
    };
    if kind != "FigureExplain" {
        return Err(SasooError::Unsupported(
            "Only FigureExplain operations have a publication implementation".into(),
        ));
    }
    let identity: Identity = decode(identity_json.as_bytes())?;
    let scope = OperationScope {
        paper_id: identity.paper_id,
        operation_id: Uuid::parse_str(operation)
            .map_err(|_| SasooError::Incomplete("Operation ID is invalid".into()))?,
        paper_epoch: identity.paper_epoch,
        source_sha256: Some(identity.source_sha256),
        expected_versions: decode(versions.as_bytes())?,
        kind: OperationKind::FigureExplain,
    };
    Ok(Snapshot {
        scope,
        identity,
        identity_json,
        identity_hash,
        owner,
        source,
        asset,
        config,
        config_hash,
        settings_revision,
        credential_refs: decode(refs.as_bytes())?,
        resource_version,
    })
}
fn intact(s: &Snapshot) -> bool {
    hash(s.identity_json.as_bytes()).as_slice() == s.identity_hash
        && hash(&s.source) == s.identity.source_sha256
        && hash(&s.asset) == s.identity.asset_sha256
        && hash(&s.config).as_slice() == s.config_hash
        && s.config_hash.as_slice() == s.identity.config_hash
        && s.settings_revision == s.identity.settings_revision
        && s.credential_refs == s.identity.credential_refs
}
fn usage_state(usage: &Value) -> &'static str {
    let Some(fields) = usage.as_object() else {
        return "unknown";
    };
    let mut known = 0;
    for key in [
        "tokens_in",
        "tokens_out",
        "tokens_cached",
        "tokens_cache_write",
    ] {
        if let Some(value) = fields.get(key).filter(|v| !v.is_null()) {
            if value.as_u64().is_none() {
                return "unknown";
            }
            known += 1;
        }
    }
    if let Some(value) = fields.get("cost_usd").filter(|v| !v.is_null()) {
        if !value.as_f64().is_some_and(|n| n.is_finite() && n >= 0.0) {
            return "unknown";
        }
        known += 1;
    }
    if reported_usage(usage).is_ok() {
        return "reported";
    }
    if let Some(input) = fields.get("tokens_in").and_then(Value::as_u64) {
        let cached = fields
            .get("tokens_cached")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        let written = fields
            .get("tokens_cache_write")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        if cached.checked_add(written).is_none_or(|n| n > input) {
            return "unknown";
        }
    }
    if known > 0 { "partial" } else { "unknown" }
}

fn scope_current(conn: &Connection, s: &Snapshot, owner: &str) -> Result<bool> {
    match owner_check(conn, owner) {
        Ok(()) => {}
        Err(SasooError::FenceLost(_)) => return Ok(false),
        Err(error) => return Err(error),
    }
    if s.owner != owner
        || !intact(s)
        || !membership(conn, s.scope.paper_id.0, s.identity.figure_id)?
    {
        return Ok(false);
    }
    let active:bool=conn.query_row("SELECT state='active' AND cancel_requested=0 AND paper_id=?2 AND paper_epoch=?3 AND source_sha256=?4 FROM runtime_operations WHERE operation_id=?1",params![s.scope.operation_id.to_string(),s.scope.paper_id.0,s.scope.paper_epoch.0,hex(&s.identity.source_sha256)],|r|r.get(0)).map_err(db_sql_error)?;
    let epoch:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM runtime_paper_epochs WHERE paper_id=?1 AND paper_epoch=?2 AND source_sha256=?3)",params![s.scope.paper_id.0,s.scope.paper_epoch.0,s.identity.source_sha256.as_slice()],|r|r.get(0)).map_err(db_sql_error)?;
    let settings: bool = conn
        .query_row(
            "SELECT settings_revision=?1 FROM runtime_server_state WHERE singleton=1",
            [s.settings_revision],
            |r| r.get(0),
        )
        .map_err(db_sql_error)?;
    let resource:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM runtime_figure_resources WHERE paper_id=?1 AND figure_id=?2 AND version_token=?3 AND source_sha256=?4 AND asset_sha256=?5)",params![s.scope.paper_id.0,s.identity.figure_id,s.resource_version,s.identity.source_sha256.as_slice(),s.identity.asset_sha256.as_slice()],|r|r.get(0)).map_err(db_sql_error)?;
    let versions = vec![ResourceVersion {
        resource_key: resource_key(s.identity.figure_id),
        version_token: s.resource_version.clone(),
    }];
    Ok(active
        && epoch
        && settings
        && resource
        && credentials_current(conn, &s.credential_refs)?
        && s.scope.expected_versions == versions)
}

impl FigureCore {
    pub fn open(db: Db, spool_root: PathBuf) -> Result<Self> {
        let owner = db.owner_id()?.to_owned();
        let root = db
            .path()
            .parent()
            .ok_or_else(|| SasooError::InvalidInput("Database root is missing".into()))?
            .canonicalize()?;
        let marker = root.join(".sasoo-rust-isolated-fixture");
        if marker.symlink_metadata()?.file_type().is_symlink()
            || fs::read_to_string(marker)? != "synthetic-only\n"
        {
            return Err(SasooError::Forbidden(
                "FigureExplain accepts synthetic fixtures only".into(),
            ));
        }
        if !spool_root.is_absolute()
            || spool_root
                .parent()
                .ok_or_else(|| SasooError::InvalidInput("Spool parent is missing".into()))?
                .canonicalize()?
                != root
        {
            return Err(SasooError::Forbidden(
                "Figure spool must be directly inside its isolated root".into(),
            ));
        }
        fs::create_dir_all(&spool_root)?;
        let spool_root = spool_root.canonicalize()?;
        if spool_root.parent() != Some(root.as_path()) {
            return Err(SasooError::Forbidden(
                "Figure spool leaves its isolated root".into(),
            ));
        }
        db.blocking_call(|conn| {
            let revision: Option<i64> = conn
                .query_row(
                    "SELECT schema_revision FROM runtime_server_state WHERE singleton=1",
                    [],
                    |r| r.get(0),
                )
                .optional()
                .map_err(db_sql_error)?;
            if revision != Some(2) {
                return Err(SasooError::Unsupported(
                    "FigureExplain requires explicit runtime revision 2".into(),
                ));
            }
            validate_figure_runtime_schema(conn)
        })?;
        Ok(Self {
            db,
            spool_root,
            owner,
        })
    }
    /// Owner-managed source or asset replacement revokes every old paper scope first.
    pub fn register_resource(
        &self,
        paper: PaperId,
        figure: i64,
        source: &[u8],
        asset: &[u8],
    ) -> Result<()> {
        if source.is_empty() || asset.is_empty() || paper.0 <= 0 || figure <= 0 {
            return Err(SasooError::Incomplete(
                "A paper, figure and nonempty source/asset bytes are required".into(),
            ));
        }
        let source = hash(source);
        let asset = hash(asset);
        let owner = self.owner.clone();
        let version = Uuid::new_v4().to_string();
        self.db.blocking_call(move|conn|{
            let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).map_err(db_sql_error)?;owner_check(&tx,&owner)?;
            if !membership(&tx,paper.0,figure)?{return Err(SasooError::NotFound("Paper/figure membership is missing or deleted".into()));}
            let current:Option<(i64,Option<Vec<u8>>)>=tx.query_row("SELECT paper_epoch,source_sha256 FROM runtime_paper_epochs WHERE paper_id=?1",[paper.0],|r|Ok((r.get(0)?,r.get(1)?))).optional().map_err(db_sql_error)?;
            let old_asset:Option<Vec<u8>>=tx.query_row("SELECT asset_sha256 FROM runtime_figure_resources WHERE paper_id=?1 AND figure_id=?2",params![paper.0,figure],|r|r.get(0)).optional().map_err(db_sql_error)?;
            let changed=current.as_ref().is_some_and(|(_,old)|old.as_deref()!=Some(source.as_slice()))||old_asset.as_deref().is_some_and(|old|old!=asset);
            let epoch=match current{Some((epoch,_)) if changed=>epoch.checked_add(1).ok_or_else(||SasooError::Conflict("Paper epoch is exhausted".into()))?,Some((epoch,_))=>epoch,None=>0};
            tx.execute("INSERT INTO runtime_paper_epochs(paper_id,paper_epoch,source_sha256,updated_at_ms) VALUES(?1,?2,?3,?4) ON CONFLICT(paper_id) DO UPDATE SET paper_epoch=excluded.paper_epoch,source_sha256=excluded.source_sha256,updated_at_ms=excluded.updated_at_ms",params![paper.0,epoch,source.as_slice(),now()?]).map_err(db_sql_error)?;
            tx.execute("INSERT INTO runtime_figure_resources(paper_id,figure_id,source_sha256,asset_sha256,version_token) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(paper_id,figure_id) DO UPDATE SET source_sha256=excluded.source_sha256,asset_sha256=excluded.asset_sha256,version_token=excluded.version_token WHERE runtime_figure_resources.source_sha256!=excluded.source_sha256 OR runtime_figure_resources.asset_sha256!=excluded.asset_sha256",params![paper.0,figure,source.as_slice(),asset.as_slice(),version]).map_err(db_sql_error)?;
            tx.commit().map_err(db_sql_error)
        })
    }
    pub fn accept(&self, input: FigureInput) -> Result<AcceptedFigure> {
        if input.source_bytes.is_empty()
            || input.asset_bytes.is_empty()
            || input.paper_id.0 <= 0
            || input.figure_id <= 0
            || input.settings_revision < 0
        {
            return Err(SasooError::Incomplete(
                "FigureExplain input is incomplete".into(),
            ));
        }
        let source = hash(&input.source_bytes);
        let asset = hash(&input.asset_bytes);
        if source != input.config.snapshot().pdf_identity.source_sha256 {
            return Err(SasooError::Incomplete(
                "Configuration and source bytes differ".into(),
            ));
        }
        let owner = self.owner.clone();
        let operation = Uuid::new_v4();
        let request = LocalRequestId(Uuid::new_v4());
        self.db.blocking_call(move|conn|{
            let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).map_err(db_sql_error)?;owner_check(&tx,&owner)?;
            if !membership(&tx,input.paper_id.0,input.figure_id)?{return Err(SasooError::NotFound("Paper/figure membership is missing or deleted".into()));}
            let revision:i64=tx.query_row("SELECT settings_revision FROM runtime_server_state WHERE singleton=1",[],|r|r.get(0)).map_err(db_sql_error)?;
            if revision!=input.settings_revision{return Err(SasooError::FenceLost("Settings changed; resolve the immutable configuration again".into()));}
            let row:Option<(i64,Vec<u8>,Vec<u8>,Vec<u8>,String)>=tx.query_row("SELECT e.paper_epoch,e.source_sha256,r.source_sha256,r.asset_sha256,r.version_token FROM runtime_paper_epochs e JOIN runtime_figure_resources r USING(paper_id) WHERE e.paper_id=?1 AND r.figure_id=?2",params![input.paper_id.0,input.figure_id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional().map_err(db_sql_error)?;
            let Some((epoch,paper_source,resource_source,resource_asset,version))=row else{return Err(SasooError::Incomplete("Owner-observed source and asset identity are required".into()));};
            if paper_source!=source||resource_source!=source||resource_asset!=asset{return Err(SasooError::FenceLost("Source or asset changed after the snapshot".into()));}
            let refs=input.config.snapshot().secret_refs.clone();if !credentials_current(&tx,&refs)?{return Err(SasooError::CredentialUnavailable("Credential reference is missing or changed".into()));}
            let identity=Identity {paper_id:input.paper_id,figure_id:input.figure_id,source_sha256:source,asset_sha256:asset,config_hash:input.config.sha256(),paper_epoch:PaperEpoch(epoch),settings_revision:revision,credential_refs:refs.clone()};
            let identity_json=encode(&identity)?;let identity_hash=hash(identity_json.as_bytes());
            let existing:Option<(String,String,String)>=tx.query_row("SELECT o.operation_id,r.request_id,o.state FROM runtime_figure_snapshots s JOIN runtime_operations o USING(operation_id) JOIN runtime_requests r USING(operation_id) WHERE s.identity_hash=?1 AND o.state IN ('active','completed','recovery_unknown') ORDER BY o.created_at_ms DESC LIMIT 1",params![identity_hash.as_slice()],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional().map_err(db_sql_error)?;
            if let Some((id,request,state))=existing {
                if state=="recovery_unknown"{return Err(SasooError::OutcomeUnknown("A prior producer cannot be verified; automatic redispatch is disabled".into()));}
                let s=snapshot(&tx,&id)?;if !intact(&s){return Err(SasooError::Incomplete("Stored immutable snapshot changed".into()));}
                tx.commit().map_err(db_sql_error)?;return Ok(AcceptedFigure {scope:s.scope,request_id:LocalRequestId(Uuid::parse_str(&request).map_err(|_|SasooError::Incomplete("Request ID is invalid".into()))?),created:false});
            }
            let next_version=operation.to_string();
            let changed=tx.execute("UPDATE runtime_figure_resources SET version_token=?1 WHERE paper_id=?2 AND figure_id=?3 AND version_token=?4 AND source_sha256=?5 AND asset_sha256=?6",params![next_version,input.paper_id.0,input.figure_id,version,source.as_slice(),asset.as_slice()]).map_err(db_sql_error)?;
            if changed!=1{return Err(SasooError::FenceLost("Figure authority changed before acceptance".into()));}
            let version=next_version;
            let versions=vec![ResourceVersion {resource_key:resource_key(input.figure_id),version_token:version.clone()}];
            let scope=OperationScope {paper_id:input.paper_id,operation_id:operation,paper_epoch:PaperEpoch(epoch),source_sha256:Some(source),expected_versions:versions.clone(),kind:OperationKind::FigureExplain};let created=now()?;
            tx.execute("INSERT INTO runtime_operations(operation_id,paper_id,paper_epoch,kind,source_sha256,expected_versions_json,state,created_at_ms) VALUES(?1,?2,?3,'FigureExplain',?4,?5,'active',?6)",params![operation.to_string(),input.paper_id.0,epoch,hex(&source),encode(&versions)?,created]).map_err(db_sql_error)?;
            tx.execute("INSERT INTO runtime_figure_snapshots(operation_id,figure_id,identity_json,identity_hash,owner_id,source_bytes,asset_bytes,config_bytes,config_hash,settings_revision,credential_refs_json,resource_version) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)",params![operation.to_string(),input.figure_id,identity_json,identity_hash.as_slice(),owner,input.source_bytes,input.asset_bytes,input.config.canonical_bytes(),input.config.sha256().as_slice(),revision,encode(&refs)?,version]).map_err(db_sql_error)?;
            tx.execute("INSERT INTO runtime_requests(request_id,paper_id,operation_id,state,spec_json,created_at_ms) VALUES(?1,?2,?3,'prepared',?4,?5)",params![request.0.to_string(),input.paper_id.0,operation.to_string(),encode(&scope)?,created]).map_err(db_sql_error)?;
            tx.commit().map_err(db_sql_error)?;Ok(AcceptedFigure {scope,request_id:request,created:true})
        })
    }
    /// A true return grants the one local dispatch; repeated calls never re-send it.
    pub fn dispatch(&self, accepted: &AcceptedFigure) -> Result<bool> {
        let a = accepted.clone();
        let owner = self.owner.clone();
        self.db.blocking_call(move|conn|{
            let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).map_err(db_sql_error)?;owner_check(&tx,&owner)?;
            let s=snapshot(&tx,&a.scope.operation_id.to_string())?;
            let state:Option<String>=tx.query_row("SELECT state FROM runtime_requests WHERE request_id=?1 AND operation_id=?2",params![a.request_id.0.to_string(),a.scope.operation_id.to_string()],|r|r.get(0)).optional().map_err(db_sql_error)?;
            if state.as_deref()!=Some("prepared"){return Ok(false);}
            if s.scope!=a.scope{return Err(SasooError::FenceLost("Dispatch snapshot differs from the accepted scope".into()));}
            if !scope_current(&tx,&s,&owner)?{return Ok(false);}
            let changed=tx.execute("UPDATE runtime_requests SET state='dispatched',dispatched_at_ms=?1 WHERE request_id=?2 AND operation_id=?3 AND state='prepared'",params![now()?,a.request_id.0.to_string(),a.scope.operation_id.to_string()]).map_err(db_sql_error)?;
            tx.commit().map_err(db_sql_error)?;Ok(changed==1)
        })
    }
    fn immutable_file(&self, relative: &str, bytes: &[u8]) -> Result<PathBuf> {
        let target = self.spool_root.join(relative);
        let parent = target
            .parent()
            .ok_or_else(|| SasooError::InvalidInput("Spool parent is missing".into()))?;
        fs::create_dir_all(parent)?;
        if !parent.canonicalize()?.starts_with(&self.spool_root) {
            return Err(SasooError::Forbidden("Spool path leaves its root".into()));
        }
        if let Ok(meta) = fs::symlink_metadata(&target) {
            if meta.file_type().is_symlink() || !meta.is_file() {
                return Err(SasooError::Forbidden(
                    "Immutable spool target is not a regular file".into(),
                ));
            }
            if fs::read(&target)? != bytes {
                return Err(SasooError::Conflict(
                    "Immutable spool bytes conflict".into(),
                ));
            }
            File::open(&target)?.sync_all()?;
            File::open(parent)?.sync_all()?;
            return Ok(target);
        }
        let pending = parent.join(format!(".pending-{}", Uuid::new_v4()));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&pending)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        match fs::hard_link(&pending, &target) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                if fs::read(&target)? != bytes {
                    return Err(SasooError::Conflict(
                        "Immutable spool bytes conflict".into(),
                    ));
                }
            }
            Err(e) => return Err(e.into()),
        }
        File::open(parent)?.sync_all()?;
        fs::remove_file(pending)?;
        File::open(parent)?.sync_all()?;
        Ok(target)
    }
    pub fn spool(&self, outcome: &FigureOutcome) -> Result<PathBuf> {
        let bytes = serde_json::to_vec(outcome)
            .map_err(|_| SasooError::InvalidInput("Outcome cannot be encoded".into()))?;
        let name = format!("{}-{}.json", outcome.request_id.0, hex(&hash(&bytes)));
        self.immutable_file(&name, &bytes)
    }
    fn read_outcome(&self, path: &Path) -> Result<(FigureOutcome, String, String)> {
        let path = path.canonicalize()?;
        if path.parent() != Some(self.spool_root.as_path()) || !path.is_file() {
            return Err(SasooError::Forbidden(
                "Outcome must be an immutable spool file".into(),
            ));
        }
        let bytes = fs::read(&path)?;
        let outcome: FigureOutcome = decode(&bytes)?;
        let event = hex(&hash(&bytes));
        let name = format!("{}-{event}.json", outcome.request_id.0);
        if path.file_name().and_then(|s| s.to_str()) != Some(name.as_str()) {
            return Err(SasooError::Incomplete(
                "Spool event hash does not match its immutable bytes".into(),
            ));
        }
        Ok((
            outcome,
            event,
            String::from_utf8(bytes)
                .map_err(|_| SasooError::Incomplete("Spool is not UTF-8".into()))?,
        ))
    }
    /// Usage survives every publication fence; this transaction never grants result authority.
    pub fn ingest(&self, path: &Path) -> Result<()> {
        let (o, event, payload) = self.read_outcome(path)?;
        let response = path.file_name().unwrap().to_string_lossy().into_owned();
        self.db.blocking_call(move|conn|{
            let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).map_err(db_sql_error)?;
            let request=o.request_id.0.to_string();let state:Option<String>=tx.query_row("SELECT r.state FROM runtime_requests r JOIN runtime_figure_snapshots s USING(operation_id) JOIN runtime_operations op USING(operation_id) WHERE r.request_id=?1 AND op.kind='FigureExplain'",[&request],|r|r.get(0)).optional().map_err(db_sql_error)?;
            let Some(state)=state else{return Err(SasooError::NotFound("FigureExplain request ID is not registered".into()));};
            if state=="prepared"{return Err(SasooError::Incomplete("Outcome has no recorded dispatch".into()));}
            let inserted=tx.execute("INSERT INTO runtime_usage_events(event_id,request_id,event_hash,payload_json,usage_state,received_at_ms) VALUES(?1,?2,?3,?4,?5,?6) ON CONFLICT(request_id,event_hash) DO NOTHING",params![Uuid::new_v4().to_string(),request,event,payload,usage_state(&o.usage),now()?]).map_err(db_sql_error)?;
            if inserted==0{tx.commit().map_err(db_sql_error)?;return Ok(());}
            let count:i64=tx.query_row("SELECT COUNT(*) FROM runtime_usage_events WHERE request_id=?1",[&request],|r|r.get(0)).map_err(db_sql_error)?;
            let terminal=if count>1{"conflicting"}else if o.terminal{"complete"}else{"incomplete"};
            if count>1 {tx.execute("UPDATE runtime_usage_events SET usage_state='conflicting' WHERE request_id=?1",[&request]).map_err(db_sql_error)?;}
            let changed=tx.execute("UPDATE runtime_requests SET state=CASE WHEN state='recovery_unknown' THEN state WHEN ?1='conflicting' THEN 'outcome_unknown' ELSE 'settled' END,terminal=?1,response_ref=COALESCE(response_ref,?2),settled_at_ms=?3 WHERE request_id=?4",params![terminal,response,now()?,request]).map_err(db_sql_error)?;
            if changed!=1{return Err(SasooError::Conflict("Usage request disappeared".into()));}
            tx.commit().map_err(db_sql_error)
        })
    }
    pub fn publish(&self, path: &Path) -> Result<Publication> {
        let (o, event, _) = self.read_outcome(path)?;
        if !o.terminal
            || usage_state(&o.usage) != "reported"
            || o.explanation.as_deref().is_none_or(|s| s.trim().is_empty())
        {
            return Ok(Publication::Incomplete(
                "Terminal, reported usage and a nonempty final explanation are required".into(),
            ));
        }
        let explanation = o.explanation.as_ref().unwrap().as_bytes();
        let artifact_hash = hex(&hash(explanation));
        let relative = format!("results/{}-{event}.md", o.request_id.0);
        self.immutable_file(&relative, explanation)?;
        let owner = self.owner.clone();
        let request = o.request_id.0.to_string();
        self.db.blocking_call(move|conn|{
            let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).map_err(db_sql_error)?;
            let request_row:Option<(String,String,String)>=tx.query_row("SELECT operation_id,state,COALESCE(terminal,'') FROM runtime_requests WHERE request_id=?1",[&request],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional().map_err(db_sql_error)?;
            let Some((operation,request_state,terminal))=request_row else{return Err(SasooError::NotFound("FigureExplain request is missing".into()));};
            let s=snapshot(&tx,&operation)?;
            let previous:Option<String>=tx.query_row("SELECT version_id FROM runtime_artifact_versions WHERE operation_id=?1 AND resource_key=?2",params![operation,resource_key(s.identity.figure_id)],|r|r.get(0)).optional().map_err(db_sql_error)?;
            if let Some(id)=previous{return Ok(Publication::AlreadyPublished(VersionId(Uuid::parse_str(&id).map_err(|_|SasooError::Incomplete("Stored version ID is invalid".into()))?)));}
            let reported:bool=tx.query_row("SELECT COUNT(*)=1 AND COALESCE(MIN(event_hash=?2 AND usage_state='reported'),0) FROM runtime_usage_events WHERE request_id=?1",params![request,event],|r|r.get(0)).map_err(db_sql_error)?;
            if !reported||terminal=="conflicting"{return Ok(Publication::Rejected("Usage is absent or conflicting".into()));}
            if request_state!="settled"||!scope_current(&tx,&s,&owner)?{return Ok(Publication::Rejected("Current FigureExplain authority no longer matches the snapshot".into()));}
            let version=VersionId(Uuid::new_v4());let changed=tx.execute("UPDATE runtime_figure_resources SET version_token=?1 WHERE paper_id=?2 AND figure_id=?3 AND version_token=?4 AND source_sha256=?5 AND asset_sha256=?6",params![version.0.to_string(),s.scope.paper_id.0,s.identity.figure_id,s.resource_version,s.identity.source_sha256.as_slice(),s.identity.asset_sha256.as_slice()]).map_err(db_sql_error)?;
            if changed!=1{return Ok(Publication::Rejected("Figure resource version changed".into()));}
            tx.execute("INSERT INTO runtime_artifact_versions(version_id,paper_id,operation_id,resource_key,source_sha256,artifact_sha256,relative_path,state,metadata_json,created_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7,'ready',?8,?9)",params![version.0.to_string(),s.scope.paper_id.0,operation,resource_key(s.identity.figure_id),hex(&s.identity.source_sha256),artifact_hash,relative,encode(&json!({"request_id":request,"event_hash":event,"figure_id":s.identity.figure_id}))?,now()?]).map_err(db_sql_error)?;
            let latest=tx.execute("INSERT INTO runtime_latest(paper_id,resource_key,version_id) VALUES(?1,?2,?3) ON CONFLICT(paper_id,resource_key) DO UPDATE SET version_id=excluded.version_id",params![s.scope.paper_id.0,resource_key(s.identity.figure_id),version.0.to_string()]).map_err(db_sql_error)?;
            let operation_changed=tx.execute("UPDATE runtime_operations SET state='completed' WHERE operation_id=?1 AND state='active' AND cancel_requested=0",[&operation]).map_err(db_sql_error)?;
            if latest!=1||operation_changed!=1{return Err(SasooError::FenceLost("Publication compare-and-swap failed".into()));}
            tx.commit().map_err(db_sql_error)?;Ok(Publication::Published(version))
        })
    }
    pub fn replay(&self) -> Result<Vec<Publication>> {
        let mut entries = fs::read_dir(&self.spool_root)?
            .map(|e| e.map(|e| e.path()))
            .collect::<std::io::Result<Vec<_>>>()?;
        entries.sort();
        let mut output = Vec::new();
        entries.retain(|path| path.is_file() && path.extension().is_some_and(|e| e == "json"));
        for path in &entries {
            self.ingest(path)?;
        }
        for path in entries {
            output.push(self.publish(&path)?);
        }
        Ok(output)
    }
    pub fn cancel(&self, operation: Uuid) -> Result<()> {
        let owner = self.owner.clone();
        self.db.blocking_call(move|conn|{let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).map_err(db_sql_error)?;owner_check(&tx,&owner)?;let s=snapshot(&tx,&operation.to_string())?;if s.owner!=owner{return Err(SasooError::FenceLost("Operation belongs to a prior owner".into()));}tx.execute("UPDATE runtime_operations SET cancel_requested=1,state='cancelled' WHERE operation_id=?1 AND kind='FigureExplain' AND state='active'",[operation.to_string()]).map_err(db_sql_error)?;tx.commit().map_err(db_sql_error)})
    }
    /// Only the isolated FigureExplain authority is revoked; paid/legacy rows are retained.
    pub fn tombstone(&self, paper: PaperId) -> Result<()> {
        let owner = self.owner.clone();
        self.db.blocking_call(move|conn|{let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).map_err(db_sql_error)?;owner_check(&tx,&owner)?;let epoch:Option<i64>=tx.query_row("SELECT paper_epoch FROM runtime_paper_epochs WHERE paper_id=?1",[paper.0],|r|r.get(0)).optional().map_err(db_sql_error)?;let epoch=epoch.ok_or_else(||SasooError::NotFound("Paper epoch is missing".into()))?.checked_add(1).ok_or_else(||SasooError::Conflict("Paper epoch is exhausted".into()))?;tx.execute("INSERT INTO runtime_tombstones(paper_id,paper_epoch,deleted_at_ms) VALUES(?1,?2,?3) ON CONFLICT(paper_id) DO NOTHING",params![paper.0,epoch,now()?]).map_err(db_sql_error)?;tx.execute("UPDATE runtime_operations SET cancel_requested=1,state='deleted' WHERE paper_id=?1 AND kind='FigureExplain' AND state='active'",[paper.0]).map_err(db_sql_error)?;tx.commit().map_err(db_sql_error)})
    }
    /// A new local owner never assumes a prior dispatched producer can be resumed.
    pub fn claim_owner(&self) -> Result<usize> {
        let owner = self.owner.clone();
        self.db.blocking_call(move|conn|{let tx=conn.transaction_with_behavior(TransactionBehavior::Immediate).map_err(db_sql_error)?;let previous:String=tx.query_row("SELECT owner_id FROM runtime_server_state WHERE singleton=1 AND schema_revision=2",[],|r|r.get(0)).map_err(db_sql_error)?;if previous==owner{return Ok(0);}
            let changed=tx.execute("UPDATE runtime_server_state SET owner_id=?1,quiescing=0 WHERE singleton=1 AND schema_revision=2 AND owner_id=?2",params![owner,previous]).map_err(db_sql_error)?;if changed!=1{return Err(SasooError::FenceLost("Owner handoff compare-and-swap failed".into()));}
            let recovered=tx.execute("UPDATE runtime_operations SET state='recovery_unknown' WHERE kind='FigureExplain' AND state='active' AND operation_id IN (SELECT operation_id FROM runtime_figure_snapshots WHERE owner_id!=?1)",[&owner]).map_err(db_sql_error)?;
            tx.execute("UPDATE runtime_requests SET state='recovery_unknown' WHERE operation_id IN (SELECT operation_id FROM runtime_operations WHERE kind='FigureExplain' AND state='recovery_unknown') AND state IN ('prepared','dispatched')",[]).map_err(db_sql_error)?;tx.commit().map_err(db_sql_error)?;Ok(recovered)})
    }
}
