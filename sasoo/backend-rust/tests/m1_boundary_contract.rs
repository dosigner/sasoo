use sasoo_backend::{
    analysis::{
        config::{ConfigInput, FrozenAgent, PdfIdentity, resolve_config},
        graph::{
            AnalysisPhase, InputCoverage, PhaseExecutor, PipelineDeps, ProviderGateway, RunContext,
            StageInput, StageOutput, run_phase,
        },
    },
    error::{Result, SasooError},
    pdf::{DocumentArtifact, EngineIdentity},
    providers::{
        transport::BoxFuture,
        types::{NewRequestSpec, ProviderInput, ProviderOutcome, RequestOutcome, UsageState},
    },
    types::{
        AttemptId, CommitScope, ExecutionId, Generation, KeyEpoch, LocalRequestId, PaperId,
        ProviderId, SecretRef,
    },
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

struct ReplayGateway(AtomicUsize);
impl ProviderGateway for ReplayGateway {
    fn call(
        &self,
        spec: NewRequestSpec,
    ) -> BoxFuture<'_, Result<(LocalRequestId, ProviderOutcome)>> {
        Box::pin(async move {
            self.0.fetch_add(1, Ordering::SeqCst);
            assert_eq!(spec.model, "fixture-model");
            Ok((
                LocalRequestId(Uuid::nil()),
                ProviderOutcome {
                    remote_id: Some("fixture".into()),
                    terminal: RequestOutcome::Completed,
                    content: Some(json!({"result":"replayed"})),
                    usage: UsageState::Unknown {
                        reason: "fixture has no usage".into(),
                    },
                    raw_response: vec![],
                    received_at: 1,
                },
            ))
        })
    }
}
struct ReplayExecutor;
impl PhaseExecutor for ReplayExecutor {
    fn run<'a>(
        &'a self,
        _: &'a RunContext,
        gateway: &'a dyn ProviderGateway,
        _: &'a StageInput,
    ) -> BoxFuture<'a, Result<StageOutput>> {
        Box::pin(async move {
            let (id, outcome) = gateway
                .call(NewRequestSpec {
                    provider: ProviderId::OpenAi,
                    model: "fixture-model".into(),
                    input: ProviderInput { parts: vec![] },
                    instructions: None,
                    schema: None,
                    strict_schema: false,
                    effort: None,
                    previous_id: None,
                    store: false,
                    max_output_tokens: None,
                    service_tier: None,
                    source_identity: None,
                })
                .await?;
            Ok(StageOutput {
                payload: outcome.content.unwrap(),
                request_ids: vec![id],
                coverage: InputCoverage::Full,
                artifact_refs: vec![],
                skip_reason: None,
            })
        })
    }
}
fn context() -> RunContext {
    let raw = "# fixture".to_owned();
    let config = ConfigInput {
        schema_version: 1,
        provider_roles: [("screening".into(), ProviderId::OpenAi)].into(),
        models: [("screening".into(), "fixture-model".into())].into(),
        efforts: [("screening".into(), None)].into(),
        prompt_schema_hashes: [("prompt".into(), [1; 32])].into(),
        raw_agent_hash: None,
        frozen_agent_catalog: vec![FrozenAgent {
            name: "fixture".into(),
            enabled: true,
            keywords: vec![],
            sha256: Sha256::digest(raw.as_bytes()).into(),
            raw_md: raw,
        }],
        agent_selection_policy_version: "fixture".into(),
        profile: json!({}),
        focus: json!({}),
        pdf_identity: PdfIdentity {
            source_sha256: [7; 32],
            engine: "fixture".into(),
            engine_revision: "fixture".into(),
            options_hash: [8; 32],
        },
        limits: [("limit".into(), 1)].into(),
        cache_version: "fixture".into(),
        secret_refs: vec![SecretRef {
            provider: ProviderId::OpenAi,
            epoch: KeyEpoch(0),
        }],
    };
    RunContext {
        scope: CommitScope {
            paper_id: PaperId(1),
            execution_id: ExecutionId(Uuid::nil()),
            attempt_id: AttemptId(Uuid::nil()),
            generation: Generation(0),
        },
        snapshot: resolve_config(&config).unwrap(),
        document: Arc::new(DocumentArtifact {
            source_sha256: [7; 32],
            engine: EngineIdentity {
                name: "fixture".into(),
                version: "1".into(),
                revision: None,
                resource_manifest_sha256: None,
            },
            extraction_options_sha256: None,
            pages: vec![],
            blocks: vec![],
            assets: vec![],
            warnings: vec![],
        }),
        cancel: CancellationToken::new(),
    }
}
#[tokio::test]
async fn phase_dispatch_uses_injected_replay_gateway_and_rejects_wrong_or_missing_phase() {
    let gateway = Arc::new(ReplayGateway(AtomicUsize::new(0)));
    let deps = PipelineDeps {
        gateway: gateway.clone(),
        executors: HashMap::from([(
            AnalysisPhase::ReviewMap,
            Arc::new(ReplayExecutor) as Arc<dyn PhaseExecutor>,
        )]),
    };
    let ctx = context();
    let input = StageInput {
        phase: AnalysisPhase::ReviewMap,
        source_sha256: [7; 32],
        input_hash: [9; 32],
        prior: vec![],
    };
    let output = run_phase(&deps, AnalysisPhase::ReviewMap, &ctx, &input)
        .await
        .unwrap();
    assert_eq!(output.payload, json!({"result":"replayed"}));
    assert_eq!(output.request_ids, vec![LocalRequestId(Uuid::nil())]);
    assert!(matches!(
        run_phase(&deps, AnalysisPhase::Screening, &ctx, &input).await,
        Err(SasooError::InvalidInput(_))
    ));
    let missing = StageInput {
        phase: AnalysisPhase::Visual,
        ..input
    };
    assert!(matches!(
        run_phase(&deps, AnalysisPhase::Visual, &ctx, &missing).await,
        Err(SasooError::Unsupported(_))
    ));
    assert_eq!(gateway.0.load(Ordering::SeqCst), 1);
}
