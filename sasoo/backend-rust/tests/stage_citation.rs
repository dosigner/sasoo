//! Citation stage against tests/stage_oracle_citation.py recordings (citation-v1.json).
mod stage_support;
use sasoo_backend::analysis::{
    citation::{CitationExecutor, analyze_citations, py_json_loads},
    graph::{AnalysisPhase, PhaseExecutor},
};
use serde_json::Value;
use stage_support::*;

fn citation_fixture() -> Value {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/stage/citation-v1.json");
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

fn sections(value: &Value) -> Vec<(String, String)> {
    value.as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.as_str().unwrap().to_owned())).collect()
}

fn s(value: &Value) -> String {
    value.as_str().unwrap().to_owned()
}

#[tokio::test]
async fn citation_matches_python_requests_and_rows() {
    let doc = citation_fixture();
    let cases = doc["citation"].as_array().unwrap();
    assert!(cases.len() >= 32);
    for case in cases {
        let name = case["name"].as_str().unwrap();
        assert!(case["error"].is_null(), "{name}");
        assert_eq!(case["unused_responses"], 0, "{name}");
        let ctx = context("citation", provider_of(case["provider"].as_str().unwrap()), &case["choice"]);
        let gateway = OracleGateway::new(case);
        let executor = CitationExecutor {
            sections: sections(&case["sections"]),
            citation_body: s(&case["citation_body"]),
            citation_references: s(&case["citation_references"]),
            paper_authors: s(&case["paper_authors"]),
        };
        let out = executor.run(&ctx, &gateway, &input(AnalysisPhase::Citation)).await.unwrap();
        gateway.finished();
        let want = &case["rows"][0];
        // Compare the stored text first so a mismatch shows the JSON diff, not one long line.
        let got_text: Value = serde_json::from_str(out.payload["result"].as_str().unwrap()).unwrap();
        let want_text: Value = serde_json::from_str(want["result"].as_str().unwrap()).unwrap();
        assert_eq!(got_text, want_text, "{name} result json");
        assert_eq!(out.payload, *want, "{name} row");
        assert_eq!(out.request_ids.len(), case["requests"].as_array().unwrap().len(), "{name}");
    }
}

#[test]
fn json_errors_match_cpython_messages() {
    for probe in citation_fixture()["json_errors"].as_array().unwrap() {
        let text = probe["text"].as_str().unwrap();
        assert_eq!(py_json_loads(text).err(), probe["error"].as_str().map(str::to_owned), "{text:?}");
    }
}

#[test]
fn analyzer_matches_python_to_dict() {
    for case in citation_fixture()["analyzer"].as_array().unwrap() {
        let got = analyze_citations(
            case["references"].as_str().unwrap(),
            case["body"].as_str().unwrap(),
            &sections(&case["sections"]),
            case["authors"].as_str().unwrap(),
        );
        assert_eq!(got, case["expected"], "{:?}", case["references"]);
    }
}
