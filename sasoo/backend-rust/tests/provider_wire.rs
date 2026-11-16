//! Rust adapters against bytes recorded from the shipped Python adapters
//! (tests/provider_wire_oracle.py). Network: none.
use sasoo_backend::{
    error::Result,
    providers::{
        gemini, openai,
        transport::{BoxFuture, HttpRequest, HttpResponse, ResponseStream, Transport},
        types::{
            InputPart, NewRequestSpec, PdfPart, ProviderFileRef, ProviderInput, RequestOutcome,
            UsageState, is_retryable,
        },
    },
    types::{Hash256, Json, ProviderId},
};
use secrecy::SecretString;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::PathBuf, sync::Mutex};

fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/provider")
}

fn fixture() -> Value {
    serde_json::from_slice(&std::fs::read(fixture_dir().join("wire-v1.json")).unwrap()).unwrap()
}

fn sha(path: &PathBuf) -> Hash256 {
    Sha256::digest(std::fs::read(path).unwrap()).into()
}

fn spec_of(spec: &Value) -> NewRequestSpec {
    let s = |k: &str| spec.get(k).and_then(Value::as_str).map(str::to_owned);
    let provider = match spec["provider"].as_str().unwrap() {
        "OpenAi" => ProviderId::OpenAi,
        _ => ProviderId::Gemini,
    };
    let parts = spec["parts"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| {
            if let Some(text) = p.get("text") {
                InputPart::Text(text.as_str().unwrap().into())
            } else if let Some(name) = p.get("pdf_inline") {
                let path = fixture_dir().join(name.as_str().unwrap());
                InputPart::Pdf(PdfPart::Inline { source_sha256: sha(&path), path })
            } else {
                InputPart::Pdf(PdfPart::File(ProviderFileRef {
                    provider: ProviderId::Gemini,
                    uri: p["pdf_uri"].as_str().unwrap().into(),
                    expires_at: None,
                    source_sha256: [0; 32],
                }))
            }
        })
        .collect();
    NewRequestSpec {
        provider,
        model: s("model").unwrap(),
        input: ProviderInput { parts },
        instructions: s("instructions"),
        schema: spec.get("schema").cloned(),
        strict_schema: spec.get("strict_schema").and_then(Value::as_bool).unwrap_or(false),
        effort: s("effort"),
        previous_id: s("previous_id"),
        store: spec.get("store").and_then(Value::as_bool).unwrap_or(true),
        max_output_tokens: spec.get("max_output_tokens").and_then(Value::as_u64).map(|v| v as u32),
        service_tier: s("service_tier"),
        source_identity: None,
    }
}

fn redacted_headers(req: &HttpRequest) -> BTreeMap<String, String> {
    req.headers
        .iter()
        .map(|(k, v)| {
            let k = k.to_ascii_lowercase();
            let v = if k == "authorization" || k == "x-goog-api-key" { "<redacted>".into() } else { v.clone() };
            (k, v)
        })
        .collect()
}

fn recorded_headers(rec: &Value) -> BTreeMap<String, String> {
    rec["headers"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_owned()))
        .collect()
}

fn assert_request(name: &str, req: &HttpRequest, rec: &Value) {
    assert_eq!(req.method, rec["method"], "{name} method");
    assert_eq!(req.url, rec["url"].as_str().unwrap(), "{name} url");
    assert_eq!(redacted_headers(req), recorded_headers(rec), "{name} headers");
    match rec.get("body_json") {
        Some(body) => assert_eq!(&serde_json::from_slice::<Value>(&req.body).unwrap(), body, "{name} body"),
        None => {
            use base64::Engine;
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(rec["body_base64"].as_str().unwrap())
                .unwrap();
            assert_eq!(req.body, bytes, "{name} binary body");
        }
    }
}

#[test]
fn requests_match_python_wire_bytes() {
    let doc = fixture();
    let cases = doc["cases"].as_array().unwrap();
    assert!(cases.len() >= 20);
    for case in cases {
        let name = case["name"].as_str().unwrap();
        let spec = spec_of(&case["spec"]);
        let req = match spec.provider {
            ProviderId::OpenAi => openai::build_request(&spec, "fixture-openai-key").unwrap(),
            ProviderId::Gemini => gemini::build_request(&spec, "fixture-gemini-key").unwrap(),
        };
        // Every recorded attempt is the same request.
        for rec in case["requests"].as_array().unwrap() {
            assert_request(name, &req, rec);
        }
    }
}

#[test]
fn responses_parse_to_the_python_result_dict() {
    let doc = fixture();
    for case in doc["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let spec = spec_of(&case["spec"]);
        let served = case["responses"].as_array().unwrap();
        let attempts = case["requests"].as_array().unwrap().len();
        let parse = |r: &Value| {
            let body = r["body"].as_str().unwrap().as_bytes();
            let status = r["status"].as_u64().unwrap() as u16;
            match spec.provider {
                ProviderId::OpenAi => openai::parse_response(&spec.model, status, body, 7),
                ProviderId::Gemini => gemini::parse_response(&spec.model, status, body, 7),
            }
        };
        let last = parse(&served[attempts - 1]);
        if let Some(result) = case.get("result") {
            assert_eq!(last.content.as_ref().unwrap(), result, "{name} result dict");
            assert_eq!(last.remote_id.as_deref(), result["interaction_id"].as_str(), "{name} remote id");
            let incomplete = result["incomplete"].as_bool().unwrap();
            assert_eq!(last.terminal == RequestOutcome::Incomplete, incomplete, "{name} terminal");
            assert_eq!(
                matches!(last.usage, UsageState::Known(_)),
                result["usage_complete"].as_bool().unwrap(),
                "{name} usage"
            );
            assert!(!is_retryable(&last), "{name} success must not retry");
            // Earlier attempts in the recording were retried by Python.
            for earlier in &served[..attempts - 1] {
                assert!(is_retryable(&parse(earlier)), "{name} earlier attempt retries");
            }
        } else {
            assert_eq!(last.terminal, RequestOutcome::Failed, "{name}");
            let error = case["error"].as_str().unwrap();
            assert_eq!(is_retryable(&last), error.contains("after retries"), "{name} retry class");
        }
    }
}

#[test]
fn reported_zero_is_known_and_missing_is_unknown() {
    let doc = fixture();
    let by_name = |n: &str| doc["cases"].as_array().unwrap().iter().find(|c| c["name"] == n).unwrap().clone();
    let zero = by_name("gemini_reported_zero");
    let outcome = gemini::parse_response("gemini-fixture", 200, zero["responses"][0]["body"].as_str().unwrap().as_bytes(), 0);
    assert!(matches!(outcome.usage, UsageState::Known(ref k) if k.tokens_in == 0 && k.tokens_out == 0));
    for name in ["gemini_usage_missing", "gemini_thought_missing", "openai_usage_missing"] {
        let case = by_name(name);
        let body = case["responses"][0]["body"].as_str().unwrap().as_bytes();
        let outcome = if name.starts_with("openai") {
            openai::parse_response("gpt-fixture", 200, body, 0)
        } else {
            gemini::parse_response("gemini-fixture", 200, body, 0)
        };
        assert!(matches!(outcome.usage, UsageState::Unknown { .. }), "{name}");
    }
}

#[test]
fn invalid_requests_are_refused_before_dispatch() {
    let base = NewRequestSpec {
        provider: ProviderId::OpenAi,
        model: "m".into(),
        input: ProviderInput { parts: vec![InputPart::Text("x".into())] },
        instructions: None,
        schema: None,
        strict_schema: false,
        effort: None,
        previous_id: Some("resp_prev".into()),
        store: false,
        max_output_tokens: None,
        service_tier: None,
        source_identity: None,
    };
    assert!(openai::build_request(&base, "k").is_err());
    assert!(gemini::build_request(&base, "k").is_err());
    let path = fixture_dir().join("tiny.pdf");
    let mut wrong_hash = base.clone();
    wrong_hash.previous_id = None;
    wrong_hash.input.parts = vec![InputPart::Pdf(PdfPart::Inline { source_sha256: [1; 32], path: path.clone() })];
    assert!(openai::build_request(&wrong_hash, "k").is_err());
    assert!(gemini::build_request(&wrong_hash, "k").is_err());
}

struct Replay {
    responses: Mutex<Vec<HttpResponse>>,
    seen: Mutex<Vec<HttpRequest>>,
}

impl Transport for Replay {
    fn send(&self, req: HttpRequest) -> BoxFuture<'_, Result<HttpResponse>> {
        self.seen.lock().unwrap().push(req);
        let next = self.responses.lock().unwrap().remove(0);
        Box::pin(async move { Ok(next) })
    }
    fn send_stream(&self, _req: HttpRequest) -> BoxFuture<'_, Result<(u16, ResponseStream)>> {
        unreachable!("analysis calls do not stream")
    }
}

#[tokio::test]
async fn gemini_upload_matches_the_sdk_and_keeps_korean_names_out_of_headers() {
    let doc = fixture();
    let upload = &doc["upload"];
    let path = fixture_dir().join(upload["file"].as_str().unwrap());
    let upload_url = "https://generativelanguage.googleapis.com/upload/v1beta/files?upload_id=fixture&upload_protocol=resumable";
    let transport = Replay {
        responses: Mutex::new(vec![
            HttpResponse { status: 200, headers: vec![("x-goog-upload-url".into(), upload_url.into())], body: vec![] },
            HttpResponse {
                status: 200,
                headers: vec![],
                body: br#"{"file":{"name":"files/abc","uri":"https://generativelanguage.googleapis.com/v1beta/files/abc"}}"#.to_vec(),
            },
        ]),
        seen: Mutex::new(vec![]),
    };
    let file = gemini::upload_pdf(&path, &sha(&path), &transport, &SecretString::from("fixture-gemini-key"))
        .await
        .unwrap();
    assert_eq!(file.uri, upload["result"]["uri"].as_str().unwrap());
    assert_eq!(file.provider, ProviderId::Gemini);
    let seen = transport.seen.lock().unwrap();
    let recorded = upload["requests"].as_array().unwrap();
    assert_eq!(seen.len(), recorded.len());
    for (req, rec) in seen.iter().zip(recorded) {
        assert_request("upload", req, rec);
        assert!(req.headers.iter().all(|(_, v)| v.is_ascii()));
    }
}

#[tokio::test]
async fn generate_maps_transport_errors_to_unknown_outcomes() {
    struct Down;
    impl Transport for Down {
        fn send(&self, _req: HttpRequest) -> BoxFuture<'_, Result<HttpResponse>> {
            Box::pin(async { Err(sasoo_backend::error::SasooError::OutcomeUnknown("reset".into())) })
        }
        fn send_stream(&self, _req: HttpRequest) -> BoxFuture<'_, Result<(u16, ResponseStream)>> {
            unreachable!()
        }
    }
    let spec = sasoo_backend::providers::types::RequestSpec {
        id: sasoo_backend::types::LocalRequestId(uuid::Uuid::new_v4()),
        new: spec_of(&serde_json::json!({"provider": "OpenAi", "model": "m", "parts": [{"text": "x"}], "store": false})),
    };
    let outcome = openai::generate(&spec, &Down, &SecretString::from("k")).await.unwrap();
    assert_eq!(outcome.terminal, RequestOutcome::OutcomeUnknown);
    assert!(is_retryable(&outcome));
    assert!(matches!(outcome.usage, UsageState::Unknown { .. }));
    let _: Option<Json> = outcome.content;
}
