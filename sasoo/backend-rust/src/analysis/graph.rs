use crate::{
    analysis::config::ConfigSnapshot,
    error::{Result, SasooError},
    pdf::DocumentArtifact,
    providers::{
        transport::BoxFuture,
        types::{NewRequestSpec, ProviderOutcome},
    },
    types::{CommitScope, Hash256, Json, LocalRequestId, ResourceVersion, VersionId},
};
use std::{collections::HashMap, sync::Arc};
use tokio_util::sync::CancellationToken;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum AnalysisPhase {
    Screening,
    Citation,
    Visual,
    Recipe,
    DeepDive,
    Synthesis,
    Visualization,
    ReviewMap,
}

pub struct RunContext {
    pub scope: CommitScope,
    pub snapshot: ConfigSnapshot,
    pub document: Arc<DocumentArtifact>,
    pub cancel: CancellationToken,
}

pub struct StageInput {
    pub phase: AnalysisPhase,
    pub source_sha256: Hash256,
    pub input_hash: Hash256,
    pub prior: Vec<PriorStage>,
}

pub struct PriorStage {
    pub phase: AnalysisPhase,
    pub version_id: VersionId,
    pub payload: Json,
    pub remote_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InputCoverage {
    Full,
    Partial { missing: Vec<String> },
}

pub struct StageOutput {
    pub payload: Json,
    pub request_ids: Vec<LocalRequestId>,
    pub coverage: InputCoverage,
    pub artifact_refs: Vec<ResourceVersion>,
    pub skip_reason: Option<String>,
}

// A gateway instance must be bound to the execution scope before use.
pub trait ProviderGateway: Send + Sync {
    fn call(
        &self,
        spec: NewRequestSpec,
    ) -> BoxFuture<'_, Result<(LocalRequestId, ProviderOutcome)>>;
}

pub trait PhaseExecutor: Send + Sync {
    fn run<'a>(
        &'a self,
        ctx: &'a RunContext,
        gateway: &'a dyn ProviderGateway,
        input: &'a StageInput,
    ) -> BoxFuture<'a, Result<StageOutput>>;
}

pub struct PipelineDeps {
    pub gateway: Arc<dyn ProviderGateway>,
    pub executors: HashMap<AnalysisPhase, Arc<dyn PhaseExecutor>>,
}

pub fn run_phase<'a>(
    deps: &'a PipelineDeps,
    phase: AnalysisPhase,
    ctx: &'a RunContext,
    input: &'a StageInput,
) -> BoxFuture<'a, Result<StageOutput>> {
    Box::pin(async move {
        if phase != input.phase {
            return Err(SasooError::InvalidInput(
                "Stage phase differs from the requested phase".into(),
            ));
        }
        let executor = deps
            .executors
            .get(&phase)
            .ok_or_else(|| SasooError::Unsupported("Phase executor is not connected".into()))?;
        executor.run(ctx, deps.gateway.as_ref(), input).await
    })
}
