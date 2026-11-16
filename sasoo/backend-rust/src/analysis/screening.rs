//! Phase 1 screening (port of `_run_screening`, analysis_execution.py).
// shortcut: these modules live here until Codex registers them in analysis/mod.rs;
// then delete these two lines and register `document_context` and `stage` there.
#[path = "document_context.rs"]
pub mod document_context;
#[path = "stage.rs"]
pub mod stage;

// Phase 1 screening (port of `_run_screening`, analysis_execution.py).
use crate::{
    analysis::{
        cache::{CacheInput, phase_cache_key},
        graph::{PhaseExecutor, ProviderGateway, RunContext, StageInput, StageOutput},
    },
    error::Result,
    providers::{
        transport::BoxFuture,
        types::{InputPart, NewRequestSpec, ProviderInput},
    },
    types::Json,
};
use serde_json::json;
use stage::{
    call, choice, clean_llm_json, combine_retry_usage, is_unfinished, parse_error_text, python_dumps,
    python_loads, result_cost_or_mark, result_row, salvage_truncated_json, stage_output, stage_result_defect,
};

pub const UNFINISHED: &str = "응답이 완료되지 않았습니다";
pub const SALVAGED_NOTE: &str = "잘린 응답에서 복구한 일부 결과입니다.";

pub fn screening_prompt(screening_input: &str) -> String {
    format!(
        "논문 텍스트:
{screening_input}

위 논문을 후속 분석 단계에 배정하기 위한 스크리닝 평가를 해줘.

판정 기준:
- domain: optics|bio|ai_ml|ee|general 중 하나
- agent_recommended: photon|cell|neural|circuit 중 하나
- relevance_score: 연구 논문으로서 분석할 실질이 있는지 (0.0=분석할 내용 없음, 1.0=분석 가치가 충분한 연구 논문)
- recipe_applicable: 재현 가능한 실험·학습·설계 절차가 논문에 있는지
- deep_dive_applicable: 기여·방법·근거·한계를 분석할 실질 내용이 있는지
- applicability_reason: 위 두 판정의 근거 1문장 (한국어)
- key_topics: 핵심 주제 리스트
- methodology_type: experimental|computational|theoretical|review 중 하나
- paper_type: article|letter|review 중 하나. review는 여러 선행 연구를 모아 한 분야를 정리하는 논문,
  letter는 Letter·Communication처럼 짧은 속보형 원저 논문, 그 밖의 원저 연구는 article
- summary: 2-3문장 요약 (한국어)
- is_experimental: 실험 논문 여부 / has_figures: 그림 포함 여부
- estimated_complexity: low|medium|high 중 하나
- confidence: 이 스크리닝 판정 자체의 확신도 (0.0~1.0)

경계 예시:
- 리뷰 논문: paper_type=review, recipe_applicable=false, deep_dive_applicable=true
- 실험 세부가 없는 사설·초록만 있는 문서: 둘 다 false 가능
불확실하면 applicable을 성급히 false로 두지 말고 confidence를 낮춰.
"
    )
}

/// Holds the per-run input; built by the graph owner for one execution.
pub struct ScreeningExecutor {
    pub screening_input: String,
    pub single_attempt: bool,
}

fn incomplete_status(result: &Json) -> bool {
    result.get("incomplete").is_some_and(stage::truthy)
        || matches!(result.get("response_status").and_then(Json::as_str), Some("incomplete" | "failed" | "cancelled"))
}

impl PhaseExecutor for ScreeningExecutor {
    fn run<'a>(
        &'a self,
        ctx: &'a RunContext,
        gateway: &'a dyn ProviderGateway,
        _input: &'a StageInput,
    ) -> BoxFuture<'a, Result<StageOutput>> {
        Box::pin(async move {
            let choice = choice(ctx, "screening")?;
            let prompt = screening_prompt(&self.screening_input);
            let cache_key = String::from_utf8(phase_cache_key(&CacheInput {
                model: choice.model.clone(),
                thinking: choice.effort.clone().unwrap_or_default(),
                system_instruction: String::new(),
                prompt: prompt.clone(),
                source_signature: String::new(),
                max_output_tokens: None,
            })?)
            .unwrap_or_default();
            let spec = NewRequestSpec {
                provider: choice.provider,
                model: choice.model.clone(),
                input: ProviderInput { parts: vec![InputPart::Text(prompt)] },
                instructions: None,
                schema: Some(stage::stage_schema("screening")?),
                strict_schema: false,
                effort: choice.effort.clone(),
                previous_id: None,
                store: false,
                max_output_tokens: None,
                service_tier: None,
                source_identity: None,
            };
            let mut ids = Vec::new();
            let (mut result, mut at) = call(gateway, spec.clone(), &mut ids).await?;
            let text = result["text"].as_str().unwrap_or("").to_owned();
            result["raw_text"] = json!(text);
            let defect = stage_result_defect(&text);
            if is_unfinished(&result) || (self.single_attempt && defect.is_some()) {
                result["text"] = json!(parse_error_text(&text, defect.unwrap_or(UNFINISHED)));
            } else if defect.is_some() {
                let schema = spec.schema.clone().unwrap_or(Json::Null);
                if let Some(salvaged) = salvage_truncated_json(&text, &schema) {
                    let mut payload = python_loads(&salvaged).unwrap_or(Json::Null);
                    payload["_partial"] = json!(SALVAGED_NOTE);
                    result["text"] = json!(python_dumps(&payload, false));
                } else {
                    let (mut retry, retry_at) = call(gateway, spec, &mut ids).await?;
                    combine_retry_usage(&result, &mut retry, at);
                    let raw = retry["text"].as_str().unwrap_or("").to_owned();
                    retry["raw_text"] = json!(raw);
                    if incomplete_status(&retry) {
                        retry["text"] = json!(parse_error_text(&raw, UNFINISHED));
                    }
                    result = retry;
                    at = retry_at;
                }
            }
            let cleaned = clean_llm_json(result["text"].as_str().unwrap_or(""));
            result["text"] = if python_loads(&cleaned).is_some() {
                json!(cleaned)
            } else {
                // shortcut: Python stores str(json.JSONDecodeError) here; serde has other
                // messages. Only reached when a retry still returns invalid JSON.
                json!(parse_error_text(&cleaned, "JSON parse failed"))
            };
            let cost = result_cost_or_mark(&mut result, at);
            let row = result_row("screening", &result, cost, &cache_key, &choice);
            Ok(stage_output(row, ids, None))
        })
    }
}
