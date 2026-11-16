//! Shared harness for stage executors against tests/stage_oracle.py recordings.
#![allow(dead_code)]
use sasoo_backend::{
    analysis::{
        config::{ConfigInput, FrozenAgent, PdfIdentity, resolve_config},
        graph::{AnalysisPhase, ProviderGateway, RunContext, StageInput},
    },
    error::Result,
    pdf::{DocumentArtifact, EngineIdentity},
    providers::{gemini, openai, transport::BoxFuture, types::{NewRequestSpec, ProviderOutcome}},
    types::{AttemptId, CommitScope, ExecutionId, Generation, KeyEpoch, LocalRequestId, PaperId, ProviderId, SecretRef},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, sync::{Arc, Mutex}};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

pub fn fixture() -> Value {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/stage/stages-v1.json");
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

pub fn provider_of(name: &str) -> ProviderId {
    if name == "openai" { ProviderId::OpenAi } else { ProviderId::Gemini }
}

/// Run context whose snapshot maps `role` to the model Python resolved.
pub fn context(role: &str, provider: ProviderId, choice: &Value) -> RunContext {
    let effort = choice["effort"].as_str().map(str::to_owned);
    let config = ConfigInput {
        schema_version: 1,
        provider_roles: BTreeMap::from([(role.to_owned(), provider)]),
        models: BTreeMap::from([(role.to_owned(), choice["model"].as_str().unwrap().to_owned())]),
        efforts: BTreeMap::from([(role.to_owned(), effort)]),
        prompt_schema_hashes: BTreeMap::from([("prompt".to_owned(), [1; 32])]),
        raw_agent_hash: None,
        frozen_agent_catalog: vec![FrozenAgent { name: "fixture".into(), enabled: true, keywords: vec![], raw_md: "x".into(), sha256: Sha256::digest(b"x").into() }],
        agent_selection_policy_version: "fixture".into(),
        profile: json!({}),
        focus: json!({}),
        pdf_identity: PdfIdentity { source_sha256: [7; 32], engine: "fixture".into(), engine_revision: "fixture".into(), options_hash: [8; 32] },
        limits: BTreeMap::from([("limit".to_owned(), 1)]),
        cache_version: "fixture".into(),
        secret_refs: vec![SecretRef { provider, epoch: KeyEpoch(0) }],
    };
    RunContext {
        scope: CommitScope { paper_id: PaperId(1), execution_id: ExecutionId(Uuid::nil()), attempt_id: AttemptId(Uuid::nil()), generation: Generation(0) },
        snapshot: resolve_config(&config).unwrap(),
        document: Arc::new(DocumentArtifact {
            source_sha256: [7; 32],
            engine: EngineIdentity { name: "fixture".into(), version: "1".into(), revision: None, resource_manifest_sha256: None },
            extraction_options_sha256: None, pages: vec![], blocks: vec![], assets: vec![], warnings: vec![],
        }),
        cancel: CancellationToken::new(),
    }
}

pub fn input(phase: AnalysisPhase) -> StageInput {
    StageInput { phase, source_sha256: [7; 32], input_hash: [9; 32], prior: vec![] }
}

/// Checks each request against the Python wire bytes and serves the recorded response.
pub struct OracleGateway {
    pub name: String,
    pub requests: Vec<Value>,
    pub responses: Vec<Value>,
    pub calls: Mutex<usize>,
}

impl OracleGateway {
    pub fn new(case: &Value) -> Self {
        Self {
            name: case["name"].as_str().unwrap().into(),
            requests: case["requests"].as_array().unwrap().clone(),
            responses: case["responses"].as_array().unwrap().clone(),
            calls: Mutex::new(0),
        }
    }
    pub fn finished(&self) {
        assert_eq!(*self.calls.lock().unwrap(), self.requests.len(), "{} call count", self.name);
    }
}

impl ProviderGateway for OracleGateway {
    fn call(&self, spec: NewRequestSpec) -> BoxFuture<'_, Result<(LocalRequestId, ProviderOutcome)>> {
        Box::pin(async move {
            let i = {
                let mut calls = self.calls.lock().unwrap();
                *calls += 1;
                *calls - 1
            };
            let recorded = self.requests.get(i).unwrap_or_else(|| panic!("{} extra call {i}", self.name));
            let served = &self.responses[i];
            let (status, body) = match served {
                Value::String(b) => (200u16, b.as_str()),
                other => (other["status"].as_u64().unwrap() as u16, other["body"].as_str().unwrap()),
            };
            let (req, outcome) = match spec.provider {
                ProviderId::OpenAi => (openai::build_request(&spec, "k")?, openai::parse_response(&spec.model, status, body.as_bytes(), now())),
                ProviderId::Gemini => (gemini::build_request(&spec, "k")?, gemini::parse_response(&spec.model, status, body.as_bytes(), now())),
            };
            assert_eq!(req.url, recorded["url"].as_str().unwrap(), "{} url", self.name);
            let body: Value = serde_json::from_slice(&req.body).unwrap();
            assert_eq!(&body, &recorded["body_json"], "{} request body {i}", self.name);
            Ok((LocalRequestId(Uuid::new_v4()), outcome))
        })
    }
}

fn now() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as i64
}

use sasoo_backend::{analysis::screening::stage::ChainSource, providers::types::ProviderFileRef};

fn hex_to_hash(hex: &str) -> [u8; 32] {
    let mut out = [0u8; 32];
    for (i, byte) in out.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&hex[2 * i..2 * i + 2], 16).unwrap();
    }
    out
}

pub fn source_of(src: &Value) -> (ChainSource, Option<String>) {
    if let Some(uri) = src.get("pdf_uri") {
        let sha = src["pdf_sha256"].as_str().unwrap().to_owned();
        let file = ProviderFileRef { provider: ProviderId::Gemini, uri: uri.as_str().unwrap().into(), expires_at: None, source_sha256: hex_to_hash(&sha) };
        (ChainSource::GeminiFile(file), Some(sha))
    } else if let Some(name) = src.get("openai_pdf") {
        let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/provider").join(name.as_str().unwrap());
        let digest: [u8; 32] = Sha256::digest(std::fs::read(&path).unwrap()).into();
        let hex = digest.iter().map(|b| format!("{b:02x}")).collect();
        (ChainSource::OpenAiPdf { path, sha256: digest }, Some(hex))
    } else if let Some(text) = src.get("doc_text") {
        (ChainSource::DocText(text.as_str().unwrap().into()), None)
    } else {
        (ChainSource::None, None)
    }
}


pub fn prior(phase: sasoo_backend::analysis::graph::AnalysisPhase, text: &Value, remote_id: Option<String>) -> sasoo_backend::analysis::graph::PriorStage {
    sasoo_backend::analysis::graph::PriorStage { phase, version_id: sasoo_backend::types::VersionId(Uuid::nil()), payload: json!({"result": text}), remote_id }
}
