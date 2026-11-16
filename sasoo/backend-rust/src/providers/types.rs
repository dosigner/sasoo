use crate::{
    analysis::pricing::KnownUsage,
    types::{Hash256, Json, LocalRequestId, ProviderId, UtcMillis},
};
use std::path::PathBuf;

#[derive(Clone)]
pub struct NewRequestSpec {
    pub provider: ProviderId,
    pub model: String,
    pub input: ProviderInput,
    pub instructions: Option<String>,
    pub schema: Option<Json>,
    pub effort: Option<String>,
    pub previous_id: Option<String>,
    pub store: bool,
    pub max_output_tokens: Option<u32>,
    pub service_tier: Option<String>,
    pub source_identity: Option<Hash256>,
}

#[derive(Clone)]
pub struct RequestSpec {
    pub id: LocalRequestId,
    pub new: NewRequestSpec,
}

#[derive(Clone)]
pub struct ProviderInput {
    pub parts: Vec<InputPart>,
}

#[derive(Clone)]
pub enum InputPart {
    Text(String),
    Pdf(PdfPart),
}

#[derive(Clone)]
pub enum PdfPart {
    Inline {
        source_sha256: Hash256,
        path: PathBuf,
    },
    File(ProviderFileRef),
}

#[derive(Clone)]
pub struct ProviderFileRef {
    pub provider: ProviderId,
    pub uri: String,
    pub expires_at: Option<UtcMillis>,
    pub source_sha256: Hash256,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RequestOutcome {
    NotDispatched,
    InFlight,
    Completed,
    Incomplete,
    Failed,
    OutcomeUnknown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UsageState {
    Known(KnownUsage),
    Unknown { reason: String },
    Conflicting { event_ids: Vec<String> },
}

#[derive(Clone)]
pub struct ProviderOutcome {
    pub remote_id: Option<String>,
    pub terminal: RequestOutcome,
    pub content: Option<Json>,
    pub usage: UsageState,
    pub raw_response: Vec<u8>,
    pub received_at: UtcMillis,
}

pub enum ProviderEvent {
    Token(String),
    Terminal(ProviderOutcome),
    TransportError(String),
}
