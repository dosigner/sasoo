mod stage_support;
use sasoo_backend::analysis::{
    deep_dive::{DeepDiveExecutor, StageSource},
    graph::{AnalysisPhase, PhaseExecutor, StageInput},
    review_map::ReviewMapExecutor,
};
use stage_support::*;

#[tokio::test]
async fn deep_dive_and_review_map_match_python_requests_and_rows() {
    let doc = fixture();
    let cases = doc["deep_dive"].as_array().unwrap();
    assert!(cases.len() >= 20);
    for case in cases {
        assert!(case["error"].is_null(), "{}", case["name"]);
        let ctx = context("deep_dive", provider_of(case["provider"].as_str().unwrap()), &case["choice"]);
        let gateway = OracleGateway::new(case);
        let (source, pdf_sha256) = source_of(&case["source"]);
        let source = StageSource { source, pdf_sha256, chained: true };
        let mut stage = StageInput {
            prior: vec![
                prior(AnalysisPhase::Screening, &case["screening"], None),
                prior(AnalysisPhase::Citation, &case["citation_text"], None),
                prior(AnalysisPhase::Visual, &case["visual_text"], None),
                prior(AnalysisPhase::Recipe, &case["recipe_text"], case["previous_id"].as_str().map(str::to_owned)),
            ],
            ..input(AnalysisPhase::DeepDive)
        };
        let executor = DeepDiveExecutor {
            deep_dive_input: case["deep_dive_input"].as_str().unwrap().into(),
            source: source.clone(),
            system_instruction: String::new(),
            single_attempt: false,
            max_output_tokens: None,
        };
        let out = executor.run(&ctx, &gateway, &stage).await.unwrap();
        assert_eq!(out.payload, case["rows"][0], "{} deep_dive row", case["name"]);
        if out.skip_reason.as_deref() == Some("review_paper") {
            stage.prior.push(prior(AnalysisPhase::DeepDive, &out.payload["result"], None));
            stage.phase = AnalysisPhase::ReviewMap;
            let review = ReviewMapExecutor {
                deep_dive_input: case["deep_dive_input"].as_str().unwrap().into(),
                source,
                system_instruction: String::new(),
                single_attempt: false,
            };
            let map = review.run(&ctx, &gateway, &stage).await.unwrap();
            assert_eq!(map.payload, case["rows"][1], "{} review_map row", case["name"]);
        } else {
            assert_eq!(case["rows"].as_array().unwrap().len(), 1, "{}", case["name"]);
        }
        gateway.finished();
    }
}
