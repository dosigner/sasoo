//! Synthesis stage against tests/stage_oracle_synthesis.py recordings (synthesis-v1.json).
mod stage_support;
use sasoo_backend::analysis::{
    deep_dive::StageSource,
    graph::{AnalysisPhase, PhaseExecutor, StageInput},
    screening::stage::python_dumps,
    synthesis::{
        SynthesisExecutor, evidence_numeric::{normalize_text, numeric_tokens},
        norm_figure_num, recipe_param_names, strip_emoji, validate_synthesis,
    },
};
use serde_json::{Value, json};
use stage_support::*;

fn synthesis_fixture() -> Value {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/stage/synthesis-v1.json");
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

fn strings(v: &Value) -> Vec<String> {
    v.as_array().unwrap().iter().map(|s| s.as_str().unwrap().to_owned()).collect()
}

#[test]
fn numeric_tokens_match_python() {
    let doc = synthesis_fixture();
    let cases = doc["numeric"].as_array().unwrap();
    assert!(cases.len() >= 50);
    for case in cases {
        let text = case["text"].as_str().unwrap();
        let normalized = normalize_text(text);
        assert_eq!(normalized, case["normalized"].as_str().unwrap(), "normalize {text:?}");
        let tokens: Vec<Value> = numeric_tokens(&normalized)
            .into_iter()
            .map(|(n, lit)| json!([n.negative, n.digits, n.exponent as i64, lit]))
            .collect();
        assert_eq!(Value::Array(tokens), case["tokens"], "tokens {text:?}");
    }
}

#[test]
fn validate_and_helpers_match_python() {
    let doc = synthesis_fixture();
    for case in doc["validate"].as_array().unwrap() {
        let got = validate_synthesis(&case["data"], case["doc"].as_str().unwrap(), &strings(&case["figures"]), &strings(&case["params"]));
        match got {
            Ok((out, dropped)) => {
                assert_eq!(python_dumps(&out, false), case["out"].as_str().unwrap(), "{} out", case["name"]);
                assert_eq!(python_dumps(&dropped, false), python_dumps(&case["dropped"], false), "{} dropped", case["name"]);
            }
            Err(message) => assert_eq!(message, case["error"].as_str().unwrap(), "{} error", case["name"]),
        }
    }
    let helpers = &doc["helpers"];
    for (input, want) in helpers["norm_figure_num"].as_object().unwrap() {
        assert_eq!(norm_figure_num(Some(&json!(input))), want.as_str().unwrap(), "figure {input:?}");
    }
    for (input, want) in helpers["strip_emoji"].as_object().unwrap() {
        assert_eq!(strip_emoji(&json!(input)), *want, "emoji {input:?}");
    }
    for (input, want) in helpers["recipe_param_names"].as_object().unwrap() {
        assert_eq!(recipe_param_names(input).unwrap(), strings(want), "params {input:?}");
    }
}

#[tokio::test]
async fn synthesis_matches_python_requests_and_rows() {
    let doc = synthesis_fixture();
    let cases = doc["synthesis"].as_array().unwrap();
    assert!(cases.len() >= 25);
    for case in cases {
        assert!(case["error"].is_null(), "{}", case["name"]);
        let ctx = context("synthesis", provider_of(case["provider"].as_str().unwrap()), &case["choice"]);
        let gateway = OracleGateway::new(case);
        let (source, pdf_sha256) = source_of(&case["source"]);
        let stage = StageInput {
            prior: vec![
                prior(AnalysisPhase::Screening, &case["screening"], None),
                prior(AnalysisPhase::Citation, &case["citation_text"], None),
                prior(AnalysisPhase::Visual, &case["visual_text"], None),
                prior(AnalysisPhase::Recipe, &case["recipe_text"], None),
                prior(AnalysisPhase::DeepDive, &case["deep_text"], case["previous_id"].as_str().map(str::to_owned)),
            ],
            ..input(AnalysisPhase::Synthesis)
        };
        let executor = SynthesisExecutor {
            visualization_input: case["visualization_input"].as_str().unwrap().into(),
            figures: case["figures"]
                .as_array()
                .unwrap()
                .iter()
                .map(|f| (f[0].as_str().unwrap().to_owned(), f[1].as_str().map(str::to_owned)))
                .collect(),
            body_text: case["body_text"].as_str().unwrap().into(),
            source: StageSource { source, pdf_sha256, chained: true },
            system_instruction: case["system_instruction"].as_str().unwrap().into(),
        };
        let out = executor.run(&ctx, &gateway, &stage).await.unwrap();
        assert_eq!(case["rows"].as_array().unwrap().len(), 1, "{}", case["name"]);
        assert_eq!(out.payload, case["rows"][0], "{} row", case["name"]);
        gateway.finished();
    }
}
