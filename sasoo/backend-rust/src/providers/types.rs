use crate::{
    analysis::pricing::{KnownUsage, reported_usage},
    error::{Result, SasooError},
    types::{Hash256, Json, LocalRequestId, ProviderId, UtcMillis},
};
use serde_json::json;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NewRequestSpec {
    pub provider: ProviderId,
    pub model: String,
    pub input: ProviderInput,
    pub instructions: Option<String>,
    pub schema: Option<Json>,
    /// OpenAI only: closes every object schema (additionalProperties=false, all required).
    #[serde(default)]
    pub strict_schema: bool,
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

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ProviderInput {
    pub parts: Vec<InputPart>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum InputPart {
    Text(String),
    Pdf(PdfPart),
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum PdfPart {
    Inline {
        source_sha256: Hash256,
        path: PathBuf,
    },
    File(ProviderFileRef),
}

#[derive(Clone, Debug, Serialize, Deserialize)]
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

/// Python adapter retry delays in seconds (`_RETRY_DELAYS`, 3 attempts per call).
/// Measured with tests/provider_wire_oracle.py: the SDKs retry inside each attempt too,
/// so Python sends up to 9 OpenAI or 12 Gemini HTTP requests for one call.
pub const RETRY_DELAYS_SECS: [u64; 2] = [2, 8];

/// Python `_is_retryable`: no status (transport error), 408, 429 and 5xx retry.
pub fn is_retryable(outcome: &ProviderOutcome) -> bool {
    match outcome.terminal {
        RequestOutcome::OutcomeUnknown => true,
        RequestOutcome::Failed => match http_status(outcome) {
            Some(status) => status == 408 || status == 429 || status >= 500,
            None => true,
        },
        _ => false,
    }
}

pub fn http_status(outcome: &ProviderOutcome) -> Option<u16> {
    outcome
        .content
        .as_ref()?
        .get("http_status")?
        .as_u64()
        .and_then(|s| u16::try_from(s).ok())
}

/// `content` holds the same dict the Python adapter returns; usage is derived
/// from it with the pricing rules so a missing count never becomes zero.
pub(crate) fn outcome_from_result(result: Json, raw: &[u8], received_at: UtcMillis) -> ProviderOutcome {
    let incomplete = result.get("incomplete").and_then(Json::as_bool).unwrap_or(true);
    let usage = match reported_usage(&result) {
        Ok(known) => UsageState::Known(known),
        Err(_) => UsageState::Unknown {
            reason: result
                .get("incomplete_reason")
                .and_then(Json::as_str)
                .unwrap_or("missing_usage")
                .to_owned(),
        },
    };
    ProviderOutcome {
        remote_id: result.get("interaction_id").and_then(Json::as_str).map(str::to_owned),
        terminal: if incomplete { RequestOutcome::Incomplete } else { RequestOutcome::Completed },
        content: Some(result),
        usage,
        raw_response: raw.to_vec(),
        received_at,
    }
}

pub(crate) fn http_error_outcome(status: u16, body: &[u8], received_at: UtcMillis) -> ProviderOutcome {
    let error = serde_json::from_slice::<Json>(body)
        .unwrap_or_else(|_| Json::String(String::from_utf8_lossy(body).into_owned()));
    ProviderOutcome {
        remote_id: None,
        terminal: RequestOutcome::Failed,
        content: Some(json!({"http_status": status, "error": error})),
        usage: UsageState::Unknown { reason: "http_error".into() },
        raw_response: body.to_vec(),
        received_at,
    }
}

/// The request may have reached the provider; billing is unknown.
pub fn transport_error_outcome(message: &str, received_at: UtcMillis) -> ProviderOutcome {
    ProviderOutcome {
        remote_id: None,
        terminal: RequestOutcome::OutcomeUnknown,
        content: Some(json!({"transport_error": message})),
        usage: UsageState::Unknown { reason: "transport_error".into() },
        raw_response: Vec::new(),
        received_at,
    }
}

/// Single text part goes on the wire as a plain string, as the Python callers send it.
pub(crate) fn single_text(input: &ProviderInput) -> Option<&str> {
    match input.parts.as_slice() {
        [InputPart::Text(text)] => Some(text),
        _ => None,
    }
}

pub(crate) fn check_chain(spec: &NewRequestSpec) -> Result<()> {
    if !spec.store && spec.previous_id.is_some() {
        return Err(SasooError::InvalidInput(
            "previous_interaction_id requires store=True".into(),
        ));
    }
    Ok(())
}

pub(crate) fn now_ms() -> UtcMillis {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as UtcMillis)
        .unwrap_or(0)
}
