//! Review-paper replacement for deep_dive (port of `_run_review_map`, analysis_execution.py).
//! Runs only after deep_dive returned skip_reason "review_paper"; failures store an error row.
use crate::{
    analysis::{
        cache::{CacheInput, phase_cache_key},
        deep_dive::{StageSource, instructions, unfinished},
        graph::{AnalysisPhase, PhaseExecutor, ProviderGateway, RunContext, StageInput, StageOutput},
        screening::stage::{
            ChainCall, OPENAI_DOC_TEXT_CHAR_LIMIT, choice, clean_llm_json, input_coverage, parse_error_text,
            parse_summary_json, python_dumps, result_cost_or_mark, result_row, run_chain_stage, source_signature,
            stage_max_output_tokens, stage_output, truthy,
        },
        visual::doc_reference_phrase,
    },
    error::Result,
    providers::transport::BoxFuture,
    types::{Json, ProviderId},
};
use serde_json::json;

pub struct ReviewMapExecutor {
    /// Same input deep_dive would have used (`source_text` in Python).
    pub deep_dive_input: String,
    pub source: StageSource,
    pub system_instruction: String,
    pub single_attempt: bool,
}

/// deep_dive's `previous_interaction_id`: the latest visual or recipe ID, skipping the
/// deep_dive skip row itself.
fn previous_id(input: &StageInput) -> Option<String> {
    input
        .prior
        .iter()
        .rev()
        .find(|p| matches!(p.phase, AnalysisPhase::Visual | AnalysisPhase::Recipe))
        .and_then(|p| p.remote_id.clone())
}

impl PhaseExecutor for ReviewMapExecutor {
    fn run<'a>(
        &'a self,
        ctx: &'a RunContext,
        gateway: &'a dyn ProviderGateway,
        input: &'a StageInput,
    ) -> BoxFuture<'a, Result<StageOutput>> {
        Box::pin(async move {
            let choice = choice(ctx, "deep_dive")?;
            let source_hash = self.source.source_hash();
            let doc_text = self.source.doc_text();
            let source_text = if doc_text.is_empty() { self.deep_dive_input.as_str() } else { doc_text };
            let instruction = instructions::REVIEW_MAP_INSTRUCTION;
            let prompt_chain = format!(
                "{instruction}\n\n{}를 바탕으로 리뷰 지도를 만들어줘.",
                doc_reference_phrase(choice.provider == ProviderId::OpenAi, self.source.openai_pdf())
            );
            let prompt_fallback = format!("논문 텍스트:\n{source_text}\n\n{instruction}");
            // Python keys the cache with 16000 while the call itself passes None (the
            // review_map entry of _STAGE_MAX_OUTPUT_TOKENS then applies in _run_chain_stage).
            let cache_key = String::from_utf8(phase_cache_key(&CacheInput {
                model: choice.model.clone(),
                thinking: choice.effort.clone().unwrap_or_default(),
                system_instruction: self.system_instruction.clone(),
                prompt: prompt_fallback.clone(),
                source_signature: source_signature(source_text, source_hash, "high"),
                max_output_tokens: stage_max_output_tokens("review_map").map(u64::from),
            })?)
            .unwrap_or_default();
            let mut ids = Vec::new();
            let call = ChainCall {
                phase: "review_map",
                prompt_chain,
                prompt_fallback,
                system_instruction: self.system_instruction.clone(),
                previous_id: if self.source.chained { previous_id(input) } else { None },
                source: self.source.source.clone(),
                restart_context: String::new(),
                choice: choice.clone(),
                schema: crate::analysis::screening::stage::stage_schema("review_map")?,
                single_attempt: self.single_attempt,
                max_output_tokens: None,
            };
            let (mut result, at) = match run_chain_stage(gateway, &mut ids, &call).await {
                Ok(done) => done,
                Err(_) => {
                    // Python: json.dumps({"error": f"...{type(exc).__name__}"}); adapters raise RuntimeError.
                    let failed = json!({
                        "text": python_dumps(&json!({"error": "리뷰 지도를 만들지 못했어요: RuntimeError"}), false),
                        "model": choice.model, "tokens_in": 0, "tokens_out": 0,
                    });
                    let mut row = result_row("review_map", &failed, Some(0.0), &cache_key, &choice);
                    row["interaction_id"] = Json::Null;
                    return Ok(stage_output(row, ids, None));
                }
            };
            let cleaned = clean_llm_json(result["text"].as_str().unwrap_or(""));
            let validated = if unfinished(&result) {
                Err("리뷰 지도 응답이 출력 상한에 걸렸거나 완료되지 않았습니다".to_owned())
            } else {
                parse_summary_json(&cleaned).and_then(|mut payload| {
                    if !payload.get("parts").is_some_and(truthy) {
                        return Err("리뷰 지도에 파트가 없습니다".to_owned());
                    }
                    payload["_input_coverage"] = input_coverage(source_text, source_hash, Some(OPENAI_DOC_TEXT_CHAR_LIMIT));
                    Ok(payload)
                })
            };
            result["text"] = json!(match validated {
                Ok(payload) => python_dumps(&payload, false),
                Err(message) => parse_error_text(result.get("raw_text").and_then(Json::as_str).unwrap_or(&cleaned), &message),
            });
            let cost = result_cost_or_mark(&mut result, at);
            Ok(stage_output(result_row("review_map", &result, cost, &cache_key, &choice), ids, None))
        })
    }
}
