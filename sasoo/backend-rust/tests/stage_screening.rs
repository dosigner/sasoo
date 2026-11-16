mod stage_support;
use sasoo_backend::analysis::{graph::{AnalysisPhase, PhaseExecutor}, screening::ScreeningExecutor};
use stage_support::*;

#[tokio::test]
async fn screening_matches_python_requests_and_rows() {
    let doc = fixture();
    let cases = doc["screening"].as_array().unwrap();
    assert!(cases.len() >= 16);
    for case in cases {
        assert!(case["error"].is_null(), "{}", case["name"]);
        let ctx = context("screening", provider_of(case["provider"].as_str().unwrap()), &case["choice"]);
        let gateway = OracleGateway::new(case);
        let executor = ScreeningExecutor { screening_input: case["screening_input"].as_str().unwrap().into(), single_attempt: false };
        let out = executor.run(&ctx, &gateway, &input(AnalysisPhase::Screening)).await.unwrap();
        gateway.finished();
        assert_eq!(out.payload, case["rows"][0], "{} row", case["name"]);
        assert_eq!(out.request_ids.len(), case["requests"].as_array().unwrap().len());
    }
}
