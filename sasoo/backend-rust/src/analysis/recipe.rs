//! Phase 3 recipe extraction (port of `_run_recipe`, analysis_execution.py).
//! Not ported: `_ensure_recipe_evidence` (evidence anchors are a separate artifact).
#[path = "recipe_text.rs"]
mod text;

use crate::{
    analysis::{
        cache::{CacheInput, phase_cache_key},
        graph::{AnalysisPhase, PhaseExecutor, ProviderGateway, RunContext, StageInput, StageOutput},
        screening::stage::{
            ChainCall, ChainSource, OPENAI_DOC_TEXT_CHAR_LIMIT, chain_previous_id, chain_restart_context, choice,
            clean_llm_json, input_coverage, is_error_result, paper_type, parse_error_text, previous_results,
            prior_result, python_dumps, python_loads, result_cost_or_mark, result_row, run_chain_stage,
            screening_gate_decision, skipped_row, source_signature, stage_max_output_tokens, stage_output,
        },
        visual::doc_reference_phrase,
    },
    error::Result,
    providers::transport::BoxFuture,
    types::{Json, ProviderId},
};
use serde_json::json;

pub struct RecipeExecutor {
    pub recipe_input: String,
    pub source: ChainSource,
    pub pdf_sha256: Option<String>,
    pub system_instruction: String,
    pub single_attempt: bool,
    pub max_output_tokens: Option<u32>,
}

pub fn domain_hint(screening_text: &str) -> &'static str {
    if screening_text.is_empty() {
        return "";
    }
    let Some(data) = python_loads(&clean_llm_json(screening_text)) else { return "" };
    match data.get("domain").and_then(Json::as_str).unwrap_or("") {
        "optics" | "photonics" => text::HINT_OPTICS,
        "bio" | "biology" => text::HINT_BIO,
        "ai_ml" | "neural" | "computer_science" => text::HINT_AI_ML,
        "ee" | "circuit" | "electrical" => text::HINT_EE,
        _ => text::HINT_GENERAL,
    }
}

pub fn instruction(screening_text: &str) -> String {
    format!("{}{}{}", text::INSTRUCTION_HEAD, domain_hint(screening_text), text::INSTRUCTION_TAIL)
}

impl PhaseExecutor for RecipeExecutor {
    fn run<'a>(
        &'a self,
        ctx: &'a RunContext,
        gateway: &'a dyn ProviderGateway,
        input: &'a StageInput,
    ) -> BoxFuture<'a, Result<StageOutput>> {
        Box::pin(async move {
            let choice = choice(ctx, "recipe")?;
            let screening = prior_result(input, AnalysisPhase::Screening);
            let (skip, reason) = screening_gate_decision(Some(&screening), "recipe");
            if skip {
                let review = reason == "not_applicable_recipe"
                    && python_loads(&clean_llm_json(&screening)).is_some_and(|s| paper_type(&s) == "review");
                let message = review.then_some("Review 논문이라 재현 레시피를 만들지 않았습니다.");
                return Ok(stage_output(skipped_row("recipe", &reason, "Recipe", message), Vec::new(), Some(reason)));
            }
            let openai_pdf = matches!(self.source, ChainSource::OpenAiPdf { .. });
            let source_hash = match self.source {
                ChainSource::OpenAiPdf { .. } | ChainSource::GeminiFile(_) => self.pdf_sha256.as_deref(),
                _ => None,
            };
            let doc_text = match &self.source {
                ChainSource::DocText(t) => t.as_str(),
                _ => "",
            };
            let source_text = if doc_text.is_empty() { self.recipe_input.as_str() } else { doc_text };
            let instruction = instruction(&screening);
            let prompt_chain = format!(
                "{instruction}\n\n{}와 이전 분석을 바탕으로 실험 레시피를 추출해줘.",
                doc_reference_phrase(choice.provider == ProviderId::OpenAi, openai_pdf)
            );
            let prompt_fallback = format!("논문 텍스트:\n{}\n\n{instruction}", self.recipe_input);
            let cache_key = String::from_utf8(phase_cache_key(&CacheInput {
                model: choice.model.clone(),
                thinking: choice.effort.clone().unwrap_or_default(),
                system_instruction: self.system_instruction.clone(),
                prompt: prompt_fallback.clone(),
                source_signature: source_signature(source_text, source_hash, "high"),
                max_output_tokens: self.max_output_tokens.or_else(|| stage_max_output_tokens("recipe")).map(u64::from),
            })?)
            .unwrap_or_default();
            let mut ids = Vec::new();
            let call = ChainCall {
                phase: "recipe",
                prompt_chain,
                prompt_fallback,
                system_instruction: self.system_instruction.clone(),
                previous_id: chain_previous_id(input),
                source: self.source.clone(),
                restart_context: chain_restart_context(&previous_results(input), 4000),
                choice: choice.clone(),
                schema: crate::analysis::screening::stage::stage_schema("recipe")?,
                single_attempt: self.single_attempt,
                max_output_tokens: self.max_output_tokens,
            };
            let (mut result, at) = run_chain_stage(gateway, &mut ids, &call).await?;
            let cleaned = clean_llm_json(result["text"].as_str().unwrap_or(""));
            result["text"] = match python_loads(&cleaned) {
                Some(mut payload) => {
                    if payload.is_object() && !is_error_result(&cleaned) {
                        payload["_input_coverage"] = input_coverage(source_text, source_hash, Some(OPENAI_DOC_TEXT_CHAR_LIMIT));
                    }
                    json!(python_dumps(&payload, false))
                }
                // shortcut: Python stores str(json.JSONDecodeError) here.
                None => json!(parse_error_text(&cleaned, "JSON parse failed")),
            };
            let cost = result_cost_or_mark(&mut result, at);
            Ok(stage_output(result_row("recipe", &result, cost, &cache_key, &choice), ids, None))
        })
    }
}
