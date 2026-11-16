use crate::types::{RunState, StageVerdict};
use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct StartedReply {
    pub paper_id: i64,
    pub status: &'static str,
    pub message: String,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum LegacyStatus {
    Pending,
    Running,
    Completed,
    Error,
    Cancelled,
}
/// Only validated output can expose the completed state.
pub fn legacy_status(state: &RunState, verdict: &StageVerdict) -> LegacyStatus {
    match state {
        RunState::Completed if matches!(verdict, StageVerdict::Valid) => LegacyStatus::Completed,
        RunState::Error | RunState::NeedsReconciliation | RunState::Completed => {
            LegacyStatus::Error
        }
        RunState::Cancelled | RunState::Deleted => LegacyStatus::Cancelled,
        RunState::PausedForQuit => LegacyStatus::Pending,
        _ => LegacyStatus::Running,
    }
}
