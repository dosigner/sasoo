use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub type Json = serde_json::Value;
pub type UtcMillis = i64;
pub type Hash256 = [u8; 32];

macro_rules! id_type {
    ($name:ident, $value:ty) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(pub $value);
    };
}

id_type!(PaperId, i64);
id_type!(Generation, i64);
id_type!(PaperEpoch, i64);
id_type!(KeyEpoch, i64);
id_type!(ExecutionId, Uuid);
id_type!(AttemptId, Uuid);
id_type!(LocalRequestId, Uuid);
id_type!(VersionId, Uuid);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ProviderId {
    OpenAi,
    Gemini,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct SecretRef {
    pub provider: ProviderId,
    pub epoch: KeyEpoch,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommitScope {
    pub paper_id: PaperId,
    pub execution_id: ExecutionId,
    pub attempt_id: AttemptId,
    pub generation: Generation,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResourceVersion {
    pub resource_key: String,
    pub version_token: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OperationKind {
    Extraction,
    Metadata,
    Chat,
    FigureExplain,
    Visualization,
    HtmlCheck,
    ExperimentPlan,
    Synthesis,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OperationScope {
    pub paper_id: PaperId,
    pub operation_id: Uuid,
    pub paper_epoch: PaperEpoch,
    pub source_sha256: Option<Hash256>,
    pub expected_versions: Vec<ResourceVersion>,
    pub kind: OperationKind,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ImportScope {
    pub import_id: Uuid,
    pub source_sha256: Hash256,
    pub library_revision: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PublicationScope {
    Analysis(CommitScope),
    Operation(OperationScope),
    Import(ImportScope),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RunState {
    Queued,
    Claimed,
    Running,
    Cancelling,
    RecoveryPending,
    NeedsReconciliation,
    PausedForQuit,
    Completed,
    Error,
    Cancelled,
    Deleted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RunDisposition {
    Completed,
    Partial,
    Cancelled,
    RecoveryRequired,
    Error,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RunOutcome {
    pub disposition: RunDisposition,
    pub checkpoints: Vec<VersionId>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum StageVerdict {
    Valid,
    Partial { reason: String },
    SkippedWithReason { reason: String },
    Invalid { reason: String },
}
