//! Phase 4 deep dive (port of `_run_deep_dive` and `_stateless_digest`, analysis_execution.py).
#[path = "instructions.rs"]
pub(crate) mod instructions;

use crate::{
    analysis::{
        cache::{CacheInput, phase_cache_key},
        graph::{AnalysisPhase, PhaseExecutor, ProviderGateway, RunContext, StageInput, StageOutput},
        screening::stage::{
            ChainCall, ChainSource, OPENAI_DOC_TEXT_CHAR_LIMIT, REVIEW_SKIP_REASON, chain_previous_id,
            chain_restart_context, choice, clean_llm_json, input_coverage, parse_error_text, parse_summary_json,
            previous_results, prior_result, python_dumps, python_loads, python_str, result_cost_or_mark, result_row,
            run_chain_stage, screening_gate_decision, skipped_row, source_signature, stage_max_output_tokens,
            stage_output, truthy, validate_summary_extensions,
        },
        visual::doc_reference_phrase,
    },
    error::Result,
    providers::transport::BoxFuture,
    types::{Json, ProviderId},
};
use serde_json::json;

/// Paper source for a stage that may run on a provider other than the chain's.
#[derive(Clone, Debug)]
pub struct StageSource {
    pub source: ChainSource,
    pub pdf_sha256: Option<String>,
    /// False when the deep_dive provider differs from the chain provider (no previous ID).
    pub chained: bool,
}

impl StageSource {
    pub fn source_hash(&self) -> Option<&str> {
        match self.source {
            ChainSource::OpenAiPdf { .. } | ChainSource::GeminiFile(_) => self.pdf_sha256.as_deref(),
            _ => None,
        }
    }
    pub fn doc_text(&self) -> &str {
        match &self.source {
            ChainSource::DocText(t) => t,
            _ => "",
        }
    }
    pub fn openai_pdf(&self) -> bool {
        matches!(self.source, ChainSource::OpenAiPdf { .. })
    }
}

fn chars(text: &str, n: usize) -> String {
    text.chars().take(n).collect()
}

fn get_or_q(v: &Json, k: &str) -> String {
    v.get(k).map_or_else(|| "?".to_owned(), python_str)
}

fn joined_or_q(v: &Json, k: &str) -> String {
    let joined = match v.get(k).filter(|x| truthy(x)) {
        Some(Json::Array(items)) => items.iter().map(python_str).collect::<Vec<_>>().join(", "),
        Some(Json::String(s)) => s.chars().map(String::from).collect::<Vec<_>>().join(", "),
        Some(Json::Object(o)) => o.keys().cloned().collect::<Vec<_>>().join(", "),
        _ => String::new(),
    };
    if joined.is_empty() { "?".into() } else { joined }
}

fn summary_of(v: &Json) -> String {
    chars(&v.get("summary").filter(|s| truthy(s)).map(python_str).unwrap_or_default(), 500)
}

/// `_stateless_digest`.
pub fn stateless_digest(screening: &str, citation: &str) -> String {
    let mut parts = Vec::new();
    if !screening.is_empty() {
        match python_loads(&clean_llm_json(screening)).filter(Json::is_object) {
            Some(s) => parts.push(format!(
                "[스크리닝] 도메인={}, 관련성={}, 방법론={}, 실험여부={}, 핵심주제={}\n요약: {}",
                get_or_q(&s, "domain"), get_or_q(&s, "relevance_score"), get_or_q(&s, "methodology_type"),
                get_or_q(&s, "is_experimental"), joined_or_q(&s, "key_topics"), summary_of(&s)
            )),
            None => parts.push(format!("[스크리닝 결과]\n{}", chars(screening, 1500))),
        }
    }
    if !citation.is_empty() {
        match python_loads(&clean_llm_json(citation)).filter(Json::is_object) {
            Some(c) => parts.push(format!(
                "[인용 분석] 총 참고문헌={}, 균형={}, 핵심영향={}\n종합: {}",
                get_or_q(&c, "total_references"), get_or_q(&c, "citation_balance"),
                joined_or_q(&c, "key_influences"), summary_of(&c)
            )),
            None => parts.push(format!("[인용 분석 결과]\n{}", chars(citation, 1500))),
        }
    }
    parts.join("\n\n")
}

pub struct DeepDiveExecutor {
    pub deep_dive_input: String,
    pub source: StageSource,
    pub system_instruction: String,
    pub single_attempt: bool,
    pub max_output_tokens: Option<u32>,
}

impl PhaseExecutor for DeepDiveExecutor {
    fn run<'a>(
        &'a self,
        ctx: &'a RunContext,
        gateway: &'a dyn ProviderGateway,
        input: &'a StageInput,
    ) -> BoxFuture<'a, Result<StageOutput>> {
        Box::pin(async move {
            let choice = choice(ctx, "deep_dive")?;
            let screening = prior_result(input, AnalysisPhase::Screening);
            let citation = prior_result(input, AnalysisPhase::Citation);
            let (skip, reason) = screening_gate_decision(Some(&screening), "deep_dive");
            if skip {
                // The graph runs ReviewMap next when the reason is review_paper.
                let row = skipped_row("deep_dive", &reason, "Deep Dive", None);
                return Ok(stage_output(row, Vec::new(), Some(reason)));
            }
            let source_hash = self.source.source_hash();
            let doc_text = self.source.doc_text();
            let source_text = if doc_text.is_empty() { self.deep_dive_input.as_str() } else { doc_text };
            let previous = previous_results(input);
            let prev_context = previous.iter().take(4).cloned().collect::<Vec<_>>().join("\n\n");
            let instruction = instructions::DEEP_DIVE_INSTRUCTION;
            let digest = stateless_digest(&screening, &citation);
            let mut prompt_chain = format!(
                "{instruction}\n\n{}와 앞선 체인 단계(시각·레시피) 결과, 그리고 아래 스크리닝·인용 분석 digest를 바탕으로 포괄적인 심층 분석을 제공해줘.",
                doc_reference_phrase(choice.provider == ProviderId::OpenAi, self.source.openai_pdf())
            );
            if !digest.is_empty() {
                prompt_chain.push_str(&format!("\n\n--- 스크리닝·인용 분석 digest ---\n{digest}"));
            }
            let prompt_fallback = format!(
                "논문 텍스트:\n{}\n\n이전 분석 단계의 결과:\n{}\n\n{instruction}\n\n위 정보를 바탕으로 포괄적인 심층 분석을 제공해줘.",
                self.deep_dive_input,
                chars(&prev_context, 4000)
            );
            let cache_key = String::from_utf8(phase_cache_key(&CacheInput {
                model: choice.model.clone(),
                thinking: choice.effort.clone().unwrap_or_default(),
                system_instruction: self.system_instruction.clone(),
                prompt: prompt_fallback.clone(),
                source_signature: source_signature(source_text, source_hash, "high"),
                max_output_tokens: self.max_output_tokens.or_else(|| stage_max_output_tokens("deep_dive")).map(u64::from),
            })?)
            .unwrap_or_default();
            let chain_results: Vec<String> = previous.into_iter().filter(|r| *r != screening && *r != citation).collect();
            let mut ids = Vec::new();
            let call = ChainCall {
                phase: "deep_dive",
                prompt_chain,
                prompt_fallback,
                system_instruction: self.system_instruction.clone(),
                previous_id: if self.source.chained { chain_previous_id(input) } else { None },
                source: self.source.source.clone(),
                restart_context: chain_restart_context(&chain_results, 4000),
                choice: choice.clone(),
                schema: crate::analysis::screening::stage::stage_schema("deep_dive")?,
                single_attempt: self.single_attempt,
                max_output_tokens: self.max_output_tokens,
            };
            let (mut result, at) = run_chain_stage(gateway, &mut ids, &call).await?;
            let cleaned = clean_llm_json(result["text"].as_str().unwrap_or(""));
            let validated = if unfinished(&result) {
                Err("심층 분석 응답이 출력 상한에 걸렸거나 완료되지 않았습니다".to_owned())
            } else {
                parse_summary_json(&cleaned).and_then(|mut payload| {
                    validate_summary_extensions(&payload)?;
                    payload["_input_coverage"] = input_coverage(source_text, source_hash, Some(OPENAI_DOC_TEXT_CHAR_LIMIT));
                    Ok(payload)
                })
            };
            result["text"] = json!(match validated {
                Ok(payload) => python_dumps(&payload, false),
                Err(message) => parse_error_text(result.get("raw_text").and_then(Json::as_str).unwrap_or(&cleaned), &message),
            });
            let cost = result_cost_or_mark(&mut result, at);
            Ok(stage_output(result_row("deep_dive", &result, cost, &cache_key, &choice), ids, None))
        })
    }
}

pub(crate) fn unfinished(result: &Json) -> bool {
    result.get("incomplete").is_some_and(truthy)
        || matches!(result.get("response_status").and_then(Json::as_str), Some("incomplete" | "failed" | "cancelled"))
}

pub const REVIEW_MAP_REASON: &str = REVIEW_SKIP_REASON;
