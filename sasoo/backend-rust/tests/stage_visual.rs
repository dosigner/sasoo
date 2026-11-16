mod stage_support;
use sasoo_backend::analysis::{
    graph::{AnalysisPhase, PhaseExecutor},
    visual::{VisualExecutor, VisualSnapshot},
};
use stage_support::*;

#[tokio::test]
async fn visual_matches_python_requests_and_rows() {
    let doc = fixture();
    let cases = doc["visual"].as_array().unwrap();
    assert!(cases.len() >= 13);
    for case in cases {
        assert!(case["error"].is_null(), "{}", case["name"]);
        let ctx = context("visual", provider_of(case["provider"].as_str().unwrap()), &case["choice"]);
        let gateway = OracleGateway::new(case);
        let (source, pdf_sha256) = source_of(&case["source"]);
        let snap = case["snapshot"].as_array().unwrap();
        let executor = VisualExecutor {
            visual_input: case["visual_input"].as_str().unwrap().into(),
            snapshot: VisualSnapshot {
                contract: snap[0].clone(),
                figures: snap[1].as_array().unwrap().clone(),
                tables: snap[2].as_array().unwrap().clone(),
            },
            source,
            pdf_sha256,
            system_instruction: case["system_instruction"].as_str().unwrap_or("").into(),
            single_attempt: false,
            max_output_tokens: None,
        };
        let out = executor.run(&ctx, &gateway, &input(AnalysisPhase::Visual)).await.unwrap();
        gateway.finished();
        assert_eq!(out.payload, case["rows"][0], "{} row", case["name"]);
    }
}
