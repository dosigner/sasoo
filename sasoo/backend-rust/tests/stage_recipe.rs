mod stage_support;
use sasoo_backend::analysis::{
    graph::{AnalysisPhase, PhaseExecutor, StageInput},
    recipe::RecipeExecutor,
};
use stage_support::*;


#[tokio::test]
async fn recipe_matches_python_requests_and_rows() {
    let doc = fixture();
    let cases = doc["recipe"].as_array().unwrap();
    assert!(cases.len() >= 18);
    for case in cases {
        assert!(case["error"].is_null(), "{}", case["name"]);
        let ctx = context("recipe", provider_of(case["provider"].as_str().unwrap()), &case["choice"]);
        let gateway = OracleGateway::new(case);
        let (source, pdf_sha256) = source_of(&case["source"]);
        let executor = RecipeExecutor {
            recipe_input: case["recipe_input"].as_str().unwrap().into(),
            source,
            pdf_sha256,
            system_instruction: String::new(),
            single_attempt: false,
            max_output_tokens: None,
        };
        let stage = StageInput {
            prior: vec![
                prior(AnalysisPhase::Screening, &case["screening"], None),
                prior(AnalysisPhase::Citation, &case["citation_text"], None),
                prior(AnalysisPhase::Visual, &case["visual_text"], case["previous_id"].as_str().map(str::to_owned)),
            ],
            ..input(AnalysisPhase::Recipe)
        };
        let out = executor.run(&ctx, &gateway, &stage).await.unwrap();
        gateway.finished();
        assert_eq!(out.payload, case["rows"][0], "{} row", case["name"]);
        assert_eq!(out.skip_reason.is_some(), case["rows"][0]["model_used"] == "system", "{}", case["name"]);
    }
}
