//! Explicit synthetic-only PDF import; this is not the production P04 cutover.
use super::{
    DocumentArtifact, PdfInput,
    artifacts::*,
    native::{NATIVE_SETTINGS, native_options},
};
use crate::{
    error::{Result, SasooError},
    http::{
        files::{AssetAccess, AssetService},
        papers::{PaperDto, PaperObservation, PaperService, ensure_idle, validate_isolated_root},
    },
    storage::{
        db::{Db, DbAccess, db_sql_error, open_db},
        migrations::{create_backup, migrate_pdf_candidate, migrate_pdf_process},
        paths::RuntimePaths,
    },
    types::PaperId,
};
use rusqlite::{OptionalExtension, params};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};
use tokio_util::sync::CancellationToken;

pub const CANDIDATE_MARKER: &str = "isolated-native-text-v2\n";

pub struct PdfCandidate {
    pub db: Db,
    pub library_root: PathBuf,
    root: PathBuf,
    execution: Option<super::process::Policy>,
    // A producer owns admission until extraction and publication have both returned.
    pub admission: Arc<tokio::sync::Semaphore>,
    active: Mutex<Option<(uuid::Uuid, CancellationToken)>>,
}

pub struct OperationGuard {
    service: Arc<PdfCandidate>,
    id: uuid::Uuid,
}
impl Drop for OperationGuard {
    fn drop(&mut self) {
        if let Ok(mut active) = self.service.active.lock() {
            if active.as_ref().is_some_and(|(id, _)| *id == self.id) {
                *active = None;
            }
        }
    }
}

fn cancelled(cancel: &CancellationToken) -> Result<()> {
    if cancel.is_cancelled() {
        Err(SasooError::Incomplete(
            "PDF cancellation requested; publication rejected before commit".into(),
        ))
    } else {
        Ok(())
    }
}

pub fn safe_filename(filename: &str) -> Result<String> {
    let raw = filename.replace('\\', "/");
    let name = raw.rsplit('/').next().unwrap_or("");
    if !name.to_lowercase().ends_with(".pdf") {
        return Err(SasooError::InvalidInput(
            "Only PDF files are accepted.".into(),
        ));
    }
    let stem = &name[..name.len() - 4];
    let mut safe = String::new();
    for c in stem.chars() {
        let c = if c.is_alphanumeric() || matches!(c, '-' | '_' | '.') {
            c
        } else {
            '_'
        };
        if c != '_' || !safe.ends_with('_') {
            safe.push(c);
        }
        if safe.chars().count() == 80 {
            break;
        }
    }
    if safe.is_empty() {
        return Err(SasooError::InvalidInput("Invalid PDF filename.".into()));
    }
    // Avoid hidden/special path components after the legacy-compatible sanitization.
    let safe = format!("{safe}.pdf");
    component(&safe)?;
    Ok(safe)
}

impl PdfCandidate {
    pub fn with_execution(mut self, policy: super::process::Policy) -> Self {
        self.execution = Some(policy);
        self
    }

    fn extract(
        &self,
        input: &PdfInput,
        options: &super::PdfOptions,
        cancel: &CancellationToken,
        operation: uuid::Uuid,
    ) -> Result<DocumentArtifact> {
        let policy = self.execution.as_ref().ok_or_else(|| {
            SasooError::Unsupported("PDF child execution policy is required".into())
        })?;

        let work = self.library_root.join(".sasoo-process");
        if !work.exists() {
            fs::create_dir(&work)?;
        }
        if work.symlink_metadata()?.file_type().is_symlink() {
            return Err(SasooError::Forbidden(
                "PDF work root cannot be a symlink".into(),
            ));
        }
        contained(&self.library_root, &work)?;
        super::process::extract(policy, input, options, cancel, operation, &work)
    }
    pub fn open(root: &Path) -> Result<Self> {
        let root = validate_isolated_root(root)?;
        let marker = root.join(".sasoo-rust-pdf-candidate");
        if marker.symlink_metadata()?.file_type().is_symlink()
            || fs::read_to_string(marker)? != CANDIDATE_MARKER
        {
            return Err(SasooError::Forbidden(
                "Explicit PDF candidate marker is required".into(),
            ));
        }
        let library = contained(&root, &root.join("library"))?;
        if library != root.join("library") || !library.is_dir() {
            return Err(SasooError::Forbidden(
                "PDF library must be a direct isolated directory".into(),
            ));
        }
        for name in [
            "sasoo.db",
            "sasoo.db.runtime-owner.lock",
            "sasoo.db-wal",
            "sasoo.db-shm",
            "sasoo.db-journal",
        ] {
            if root
                .join(name)
                .symlink_metadata()
                .is_ok_and(|m| m.file_type().is_symlink())
            {
                return Err(SasooError::Forbidden(
                    "PDF database paths cannot be symlinks".into(),
                ));
            }
        }
        let paths = RuntimePaths {
            app_data_root: root.clone(),
            db_path: root.join("sasoo.db"),
            config_path: root.join("config.json"),
            default_library_root: library.clone(),
            library_root: library.clone(),
            library_search_roots: vec![library.clone()],
            owner_lock_path: root.join("sasoo.db.runtime-owner.lock"),
        };
        let db = open_db(&paths, DbAccess::ServerOwner)?;
        let exists = db.blocking_call(|conn| {
            ensure_idle(conn)?;
            conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='pdf_candidate_versions')",
                [],
                |r| r.get::<_, bool>(0),
            )
            .map_err(db_sql_error)
        })?;
        if !exists {
            let backup = create_backup(
                &db,
                &root.join(format!("pdf-candidate-before-{}.db", uuid::Uuid::new_v4())),
            )?;
            migrate_pdf_candidate(&db, &backup)?;
        }
        let operations = db.blocking_call(|conn| {
            conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='pdf_candidate_operations')",
                [],
                |r| r.get::<_, bool>(0),
            )
            .map_err(db_sql_error)
        })?;
        if !operations {
            let backup = create_backup(
                &db,
                &root.join(format!("pdf-process-before-{}.db", uuid::Uuid::new_v4())),
            )?;
            migrate_pdf_process(&db, &backup)?;
        }
        // A collision or a partial schema is an error, never an invitation to repair it.
        db.blocking_call(|conn| {conn.prepare("SELECT v.version,v.paper_id,v.filename,v.source_sha256,v.options_sha256,v.document_sha256,c.version FROM pdf_candidate_versions v LEFT JOIN pdf_candidate_current c ON c.paper_id=v.paper_id LIMIT 0").map_err(db_sql_error)?; Ok(())})?;
        Ok(Self {
            db,
            library_root: library,
            root,
            admission: Arc::new(tokio::sync::Semaphore::new(1)),
            active: Mutex::new(None),
            execution: None,
        })
    }

    pub fn register(
        self: &Arc<Self>,
        id: uuid::Uuid,
        cancel: CancellationToken,
    ) -> Result<OperationGuard> {
        let mut active = self
            .active
            .lock()
            .map_err(|_| SasooError::Internal("PDF operation registry stopped".into()))?;
        if active.is_some() {
            return Err(SasooError::StorageBusy(
                "A PDF operation still owns admission".into(),
            ));
        }
        self.record_operation(id)?;
        *active = Some((id, cancel));
        Ok(OperationGuard {
            service: self.clone(),
            id,
        })
    }

    fn record_operation(&self, id: uuid::Uuid) -> Result<()> {
        self.db.blocking_call(move |c| {
            c.execute(
                "INSERT INTO pdf_candidate_operations(operation_id) VALUES(?1)",
                [id.to_string()],
            )
            .map_err(db_sql_error)?;
            Ok(())
        })
    }

    fn operation(&self) -> Result<uuid::Uuid> {
        if let Some((id, _)) = self
            .active
            .lock()
            .map_err(|_| SasooError::Internal("PDF registry stopped".into()))?
            .as_ref()
        {
            return Ok(*id);
        }
        let id = uuid::Uuid::new_v4();
        self.record_operation(id)?;
        Ok(id)
    }

    pub fn operation_status(&self, id: uuid::Uuid) -> Result<Value> {
        self.db.blocking_call(move |c| {
            let version: Option<String> = c.query_row("SELECT version FROM pdf_candidate_operations WHERE operation_id=?1", [id.to_string()], |r|r.get(0)).optional().map_err(db_sql_error)?.ok_or_else(||SasooError::NotFound("PDF operation not found".into()))?;
            Ok(json!({"operation_id":id,"publication_state":if version.is_some(){"committed"}else{"unknown"},"version":version,"automatic_retry":false}))
        })
    }

    pub fn cancel(&self, id: uuid::Uuid) -> Result<bool> {
        let active = self
            .active
            .lock()
            .map_err(|_| SasooError::Internal("PDF operation registry stopped".into()))?;
        if let Some((current, token)) = active.as_ref().filter(|(current, _)| *current == id) {
            let _ = current;
            token.cancel();
            return Ok(true);
        }
        Ok(false)
    }

    fn check_authority(&self) -> Result<()> {
        if self.db.access() != DbAccess::ServerOwner
            || validate_isolated_root(&self.root)? != self.root
            || read_bounded(&self.root.join(".sasoo-rust-pdf-candidate"), 128)?
                != CANDIDATE_MARKER.as_bytes()
            || contained(&self.root, &self.root.join("library"))? != self.library_root
        {
            return Err(SasooError::Forbidden(
                "PDF candidate authority changed".into(),
            ));
        }
        self.db.blocking_call(|conn| ensure_idle(conn))
    }

    fn folder(&self, id: PaperId) -> Result<PathBuf> {
        let folder: String = self.db.blocking_call(move |conn| {
            conn.query_row("SELECT folder_name FROM papers WHERE id=?1", [id.0], |r| {
                r.get(0)
            })
            .optional()
            .map_err(db_sql_error)?
            .ok_or_else(|| SasooError::NotFound("Paper not found".into()))
        })?;
        component(&folder)?;
        contained(&self.library_root, &self.library_root.join(folder))
    }

    fn version_dir(&self, folder: &Path, version: &str) -> Result<PathBuf> {
        component(version)?;
        let parent = folder.join(".sasoo-runtime/pdf");
        contained(folder, &parent)?;
        contained(&parent, &parent.join(version))
    }

    pub fn load(
        &self,
        id: PaperId,
        historical: Option<String>,
    ) -> Result<(VersionReceipt, DocumentArtifact)> {
        self.check_authority()?;
        let folder = self.folder(id)?;
        let history = historical.is_some();
        let (version, filename, source, options, document_hash): (String,String,String,String,String) = self.db.blocking_call(move |conn| {
            conn.query_row("SELECT version,filename,source_sha256,options_sha256,document_sha256 FROM pdf_candidate_versions WHERE paper_id=?1 AND version=COALESCE(?2,(SELECT version FROM pdf_candidate_current WHERE paper_id=?1))",params![id.0,historical],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional().map_err(db_sql_error)?.ok_or_else(||SasooError::NotFound("No published native extraction".into()))
        })?;
        component(&filename)?;
        let (receipt, artifact) =
            load_version(&self.version_dir(&folder, &version)?, &document_hash)?;
        if receipt.version != version
            || receipt.source_sha256 != source
            || receipt
                .options
                .options_hash
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
                != options
        {
            return Err(SasooError::Conflict(
                "PDF catalog and receipt disagree".into(),
            ));
        }
        if !history
            && (receipt.options != native_options()
                || hash(&read_bounded(
                    &contained(&folder, &folder.join(filename))?,
                    MAX_PDF_BYTES as u64,
                )?) != source)
        {
            return Err(SasooError::Conflict(
                "PDF source or extraction settings changed; current text is stale".into(),
            ));
        }
        Ok((receipt, artifact))
    }

    fn service(&self, id: PaperId, text_ready: bool) -> PaperService {
        PaperService {
            db: self.db.clone(),
            observations: BTreeMap::from([(
                id.0,
                PaperObservation {
                    resolved_title: None,
                    text_ready,
                    visual_ready: false,
                    visual_state: "partial".into(),
                    visual_error: None,
                    openalex_field: None,
                },
            )]),
            domain_agents: BTreeMap::new(),
            filesystem_root: None,
        }
    }

    pub fn paper(&self, id: PaperId) -> Result<Value> {
        let (text_ready, extraction) = match self.load(id, None) {
            Ok((receipt, _)) => (
                receipt.pages_with_text > 0,
                serde_json::to_value(receipt).map_err(|e| SasooError::Internal(e.to_string()))?,
            ),
            Err(
                SasooError::Conflict(message)
                | SasooError::Incomplete(message)
                | SasooError::InvalidInput(message),
            ) => (
                false,
                json!({"text_state":"stale_or_invalid","error":message,"analysis_state":"not_run","page_evidence":"page_unverified"}),
            ),
            Err(SasooError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => (
                false,
                json!({"text_state":"missing","analysis_state":"not_run"}),
            ),
            Err(error) => return Err(error),
        };
        let PaperDto { fields } = self.service(id, text_ready).get_paper(id)?;
        let mut value = Value::Object(fields);
        value["read_only"] = json!(true);
        value["pdf_candidate"] = json!(true);
        value["extraction"] = extraction;
        Ok(value)
    }

    pub fn assets(&self) -> AssetService {
        AssetService {
            db: self.db.clone(),
            search_roots: vec![self.library_root.clone()],
            access: AssetAccess::default(),
        }
    }

    pub fn import_pdf(
        &self,
        filename: &str,
        bytes: &[u8],
        cancel: &CancellationToken,
    ) -> Result<Value> {
        self.check_authority()?;
        cancelled(cancel)?;
        let operation = self.operation()?;
        let filename = safe_filename(filename)?;
        if bytes.len() > MAX_PDF_BYTES {
            return Err(SasooError::InvalidInput(
                "PDF files must not exceed 100 MB.".into(),
            ));
        }
        if !valid_pdf_header(bytes) {
            return Err(SasooError::InvalidInput(
                "The uploaded file is not a valid PDF.".into(),
            ));
        }
        let staging = self.library_root.join(".sasoo-staging");
        match fs::create_dir(&staging) {
            Ok(()) => (),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => (),
            Err(e) => return Err(e.into()),
        }
        if staging.symlink_metadata()?.file_type().is_symlink() {
            return Err(SasooError::Forbidden("Staging cannot be a symlink".into()));
        }
        contained(&self.library_root, &staging)?;
        let folder_name = format!("pdf-{}", uuid::Uuid::new_v4());
        let staged = staging.join(&folder_name);
        fs::create_dir(&staged)?;
        let source_path = staged.join(&filename);
        write_new(&source_path, bytes)?;
        let options = native_options();
        let artifact = self.extract(
            &PdfInput {
                path: source_path.clone(),
                source_sha256: Sha256::digest(bytes).into(),
            },
            &options,
            cancel,
            operation,
        )?;
        cancelled(cancel)?;
        let version = uuid::Uuid::new_v4().to_string();
        fs::create_dir_all(staged.join(".sasoo-runtime/pdf"))?;
        let receipt = save_version(
            &staged.join(".sasoo-runtime/pdf").join(&version),
            &version,
            &artifact,
            &options,
            NATIVE_SETTINGS,
        )?;
        load_version(
            &staged.join(".sasoo-runtime/pdf").join(&version),
            &receipt.document_sha256,
        )?;
        if hash(&read_bounded(&source_path, MAX_PDF_BYTES as u64)?) != receipt.source_sha256 {
            return Err(SasooError::Conflict("Staged source changed".into()));
        }
        cancelled(cancel)?;
        self.check_authority()?;
        let final_dir = self.library_root.join(&folder_name);
        // create_dir is the no-replace reservation; only our new files move into it.
        fs::create_dir(&final_dir)?;
        for entry in fs::read_dir(&staged)? {
            let path = entry?.path();
            fs::rename(&path, final_dir.join(path.file_name().unwrap()))?;
        }
        cancelled(cancel)?;
        let title = filename.trim_end_matches(".pdf").to_owned();
        let saved = receipt.clone();
        let token = cancel.clone();
        #[cfg(test)]
        checkpoint("before_commit")?;
        let _publication_guard = self
            .active
            .lock()
            .map_err(|_| SasooError::Internal("PDF publication fence stopped".into()))?;
        let id = self.db.blocking_call(move |conn| {
            let tx=conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(db_sql_error)?;
            ensure_idle(&tx)?;
            cancelled(&token)?;
            if hash(&read_bounded(&final_dir.join(&filename),MAX_PDF_BYTES as u64)?) != saved.source_sha256 {
                return Err(SasooError::Conflict("Source changed before publication".into()));
            }
            tx.execute("INSERT INTO papers(title,folder_name,domain,agent_used,status) VALUES(?1,?2,'general','general','pending')",params![title,folder_name]).map_err(db_sql_error)?;
            let id=PaperId(tx.last_insert_rowid());
            insert_version(&tx,id,&filename,&saved)?;
            publish_operation(&tx, operation, &saved.version)?;
            tx.commit().map_err(db_sql_error)?;
            Ok(id)
        })?;
        drop(_publication_guard);
        #[cfg(test)]
        checkpoint("after_commit")?;
        self.paper(id)
    }

    pub fn refresh(&self, id: PaperId, cancel: &CancellationToken) -> Result<Value> {
        self.check_authority()?;
        let operation = self.operation()?;
        let folder = self.folder(id)?;
        let (filename, previous): (String,String) = self.db.blocking_call(move |conn|conn.query_row("SELECT v.filename,v.version FROM pdf_candidate_versions v JOIN pdf_candidate_current c ON c.version=v.version AND c.paper_id=v.paper_id WHERE c.paper_id=?1",[id.0],|r|Ok((r.get(0)?,r.get(1)?))).optional().map_err(db_sql_error)?.ok_or_else(||SasooError::NotFound("Native extraction not found".into())))?;
        component(&filename)?;
        let source = contained(&folder, &folder.join(&filename))?;
        let bytes = read_bounded(&source, MAX_PDF_BYTES as u64)?;
        let options = native_options();
        let artifact = self.extract(
            &PdfInput {
                path: source.clone(),
                source_sha256: Sha256::digest(&bytes).into(),
            },
            &options,
            cancel,
            operation,
        )?;
        let parent = folder.join(".sasoo-runtime/pdf");
        contained(&folder, &parent)?;
        let version = uuid::Uuid::new_v4().to_string();
        let receipt = save_version(
            &parent.join(&version),
            &version,
            &artifact,
            &options,
            NATIVE_SETTINGS,
        )?;
        load_version(&parent.join(&version), &receipt.document_sha256)?;
        cancelled(cancel)?;
        self.check_authority()?;
        let token = cancel.clone();
        #[cfg(test)]
        checkpoint("before_commit")?;
        let _publication_guard = self
            .active
            .lock()
            .map_err(|_| SasooError::Internal("PDF publication fence stopped".into()))?;
        self.db.blocking_call(move |conn| {
            let tx = conn
                .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
                .map_err(db_sql_error)?;
            ensure_idle(&tx)?;
            cancelled(&token)?;
            let current: String = tx
                .query_row(
                    "SELECT version FROM pdf_candidate_current WHERE paper_id=?1",
                    [id.0],
                    |r| r.get(0),
                )
                .map_err(db_sql_error)?;
            if current != previous
                || hash(&read_bounded(&source, MAX_PDF_BYTES as u64)?) != receipt.source_sha256
            {
                return Err(SasooError::Conflict(
                    "Source or published version changed before commit".into(),
                ));
            }
            insert_version(&tx, id, &filename, &receipt)?;
            publish_operation(&tx, operation, &receipt.version)?;
            tx.commit().map_err(db_sql_error)
        })?;
        drop(_publication_guard);
        #[cfg(test)]
        checkpoint("after_commit")?;
        self.paper(id)
    }
}

fn insert_version(
    conn: &rusqlite::Connection,
    id: PaperId,
    filename: &str,
    receipt: &VersionReceipt,
) -> Result<()> {
    let options = receipt
        .options
        .options_hash
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    conn.execute("INSERT INTO pdf_candidate_versions(version,paper_id,filename,source_sha256,options_sha256,document_sha256) VALUES(?1,?2,?3,?4,?5,?6)",params![receipt.version,id.0,filename,receipt.source_sha256,options,receipt.document_sha256]).map_err(db_sql_error)?;
    conn.execute("INSERT INTO pdf_candidate_current(paper_id,version) VALUES(?1,?2) ON CONFLICT(paper_id) DO UPDATE SET version=excluded.version",params![id.0,receipt.version]).map_err(db_sql_error)?;
    Ok(())
}

fn publish_operation(
    conn: &rusqlite::Connection,
    operation: uuid::Uuid,
    version: &str,
) -> Result<()> {
    if conn.execute("UPDATE pdf_candidate_operations SET version=?1 WHERE operation_id=?2 AND version IS NULL", params![version,operation.to_string()]).map_err(db_sql_error)? != 1 {
        return Err(SasooError::Conflict("PDF operation has already committed or lost its identity".into()));
    }
    Ok(())
}

#[cfg(test)]
mod fault_tests {
    use super::*;
    mod fixture {
        include!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/tests/support/library_fixture.rs"
        ));
    }

    #[test]
    fn partial_storage_and_commit_response_boundaries_preserve_success_and_legacy() {
        for fault in [
            "new.pdf",
            "document.json",
            "receipt.json",
            "before_commit",
            "after_commit",
        ] {
            let root = tempfile::tempdir().unwrap();
            fixture::seed(root.path(), true);
            rusqlite::Connection::open(root.path().join("sasoo.db"))
                .unwrap()
                .execute("UPDATE papers SET status='pending'", [])
                .unwrap();
            fs::write(
                root.path().join(".sasoo-rust-pdf-candidate"),
                CANDIDATE_MARKER,
            )
            .unwrap();
            let executable = std::env::current_exe()
                .unwrap()
                .parent()
                .unwrap()
                .parent()
                .unwrap()
                .join("sasoo-backend");
            let s = PdfCandidate::open(root.path()).unwrap().with_execution(
                super::super::process::Policy::new(executable, std::time::Duration::from_secs(5)),
            );
            let saved = s
                .import_pdf(
                    "source.pdf",
                    &fixture::minimal_pdf(),
                    &CancellationToken::new(),
                )
                .unwrap();
            let id = PaperId(saved["id"].as_i64().unwrap());
            let version = saved["extraction"]["version"].as_str().unwrap().to_owned();
            let legacy = fs::read(root.path().join("library/one/.document_context.json")).unwrap();
            FAULT.with(|f| f.set(Some(fault)));
            let result = s.import_pdf(
                "new.pdf",
                &fixture::minimal_pdf(),
                &CancellationToken::new(),
            );
            FAULT.with(|f| f.set(None));
            assert!(result.is_err(), "{fault}");
            assert_eq!(s.load(id, None).unwrap().0.version, version);
            assert_eq!(
                fs::read(root.path().join("library/one/.document_context.json")).unwrap(),
                legacy
            );
            let count =
                s.db.blocking_call(|c| {
                    c.query_row(
                        "SELECT COUNT(*) FROM pdf_candidate_operations WHERE version IS NOT NULL",
                        [],
                        |r| r.get::<_, i64>(0),
                    )
                    .map_err(db_sql_error)
                })
                .unwrap();
            assert_eq!(
                count,
                if fault == "after_commit" { 2 } else { 1 },
                "{fault}"
            );
        }
    }
}
