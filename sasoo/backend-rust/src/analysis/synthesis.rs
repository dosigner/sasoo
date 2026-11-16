//! Phase 5 synthesis (port of `_run_synthesis`, `_validate_synthesis` and the error row
//! `_run_visualizations` stores when synthesis raises, analysis_execution.py).
//! Not ported: the phase cache lookup (like the other Rust stages).
#[path = "evidence_numeric.rs"]
pub mod evidence_numeric;

use crate::{
    analysis::{
        cache::{CacheInput, legacy_input_hash, phase_cache_key},
        citation::py_json_loads,
        deep_dive::{StageSource, instructions::SYNTHESIS_INSTRUCTION},
        graph::{AnalysisPhase, PhaseExecutor, ProviderGateway, RunContext, StageInput, StageOutput},
        screening::stage::{
            ChainCall, chain_previous_id, chain_restart_context, choice, clean_llm_json, is_error_result,
            parse_error_text, previous_results, prior_result, python_dumps, python_loads, python_str,
            result_cost_or_mark, result_row, run_chain_stage, source_signature, stage_max_output_tokens,
            stage_output, stage_schema, truthy,
        },
        visual::doc_reference_phrase,
    },
    error::Result,
    providers::{transport::BoxFuture, types::{NewRequestSpec, ProviderOutcome}},
    types::{Json, LocalRequestId, ProviderId},
};
use std::sync::Mutex;
use evidence_numeric::{Number, casefold, is_py_space, normalize_text, numeric_tokens};
use serde_json::{Map, json};

pub struct SynthesisExecutor {
    /// `phase_inputs["visualization"]`.
    pub visualization_input: String,
    /// `figures` rows as (figure_num, caption), already in
    /// `ORDER BY COALESCE(page_number, 999999), figure_num`; empty numbers are skipped.
    pub figures: Vec<(String, Option<String>)>,
    /// Full paper text for the evidence check (`body_text`, not the chain `doc_text`).
    pub body_text: String,
    /// The chain provider's source (synthesis always runs on the chain provider).
    pub source: StageSource,
    pub system_instruction: String,
}

/// Python `str(value or "")`.
fn or_str(value: Option<&Json>) -> String {
    value.filter(|v| truthy(v)).map(python_str).unwrap_or_default()
}

/// Python `for item in (value or [])`; a truthy number raises TypeError.
fn py_iter(value: Option<&Json>) -> std::result::Result<Vec<Json>, String> {
    match value.filter(|v| truthy(v)) {
        None => Ok(Vec::new()),
        Some(Json::Array(items)) => Ok(items.clone()),
        Some(Json::String(s)) => Ok(s.chars().map(|c| json!(c.to_string())).collect()),
        Some(Json::Object(map)) => Ok(map.keys().map(|k| json!(k)).collect()),
        Some(Json::Bool(_)) => Err("'bool' object is not iterable".into()),
        Some(Json::Number(n)) => Err(format!("'{}' object is not iterable", if n.is_f64() { "float" } else { "int" })),
        Some(Json::Null) => Ok(Vec::new()),
    }
}

fn is_emoji(c: char) -> bool {
    matches!(c, '\u{1F000}'..='\u{1FAFF}' | '\u{2600}'..='\u{27BF}' | '\u{2B00}'..='\u{2BFF}' | '\u{FE0F}' | '\u{20E3}')
}

/// `_strip_emoji`.
pub fn strip_emoji(value: &Json) -> Json {
    match value {
        Json::String(s) => json!(s.chars().filter(|c| !is_emoji(*c)).collect::<String>().trim_matches(is_py_space)),
        Json::Array(items) => Json::Array(items.iter().map(strip_emoji).collect()),
        Json::Object(map) => Json::Object(map.iter().map(|(k, v)| (k.clone(), strip_emoji(v))).collect()),
        other => other.clone(),
    }
}

/// `_norm_compact`.
pub fn norm_compact(value: Option<&Json>) -> String {
    casefold(&or_str(value).chars().filter(|c| !is_py_space(*c)).collect::<String>())
}

/// `_norm_figure_num`.
pub fn norm_figure_num(value: Option<&Json>) -> String {
    let compact = norm_compact(value);
    ["figure", "fig.", "fig"]
        .iter()
        .find_map(|p| compact.strip_prefix(p))
        .map_or_else(|| compact.clone(), str::to_owned)
}

/// `_recipe_param_names`.
pub fn recipe_param_names(recipe_result: &str) -> std::result::Result<Vec<String>, String> {
    let Some(parsed) = python_loads(&clean_llm_json(recipe_result)).filter(Json::is_object) else {
        return Ok(Vec::new());
    };
    Ok(py_iter(parsed.get("parameters"))?
        .iter()
        .filter(|p| p.is_object() && p.get("name").is_some_and(truthy))
        .map(|p| python_str(&p["name"]))
        .collect())
}

fn numbers(text: Option<&Json>) -> Vec<Number> {
    numeric_tokens(&normalize_text(&or_str(text))).into_iter().map(|(n, _)| n).collect()
}

/// `_validate_synthesis`: (cleaned dict, dropped counts), or the TypeError text.
pub fn validate_synthesis(
    data: &Json,
    doc_text: &str,
    figure_nums: &[String],
    param_names: &[String],
) -> std::result::Result<(Json, Json), String> {
    let mut out = strip_emoji(data);
    let doc_numbers: Vec<Number> = if doc_text.is_empty() {
        Vec::new()
    } else {
        numeric_tokens(&normalize_text(doc_text)).into_iter().map(|(n, _)| n).collect()
    };
    let (mut dropped_metrics, mut dropped_figures, mut dropped_params) = (0, 0, 0);

    let mut metrics = Vec::new();
    for metric in py_iter(out.get("key_metrics"))? {
        if !metric.is_object() || or_str(metric.get("unit")).trim_matches(is_py_space).is_empty() {
            dropped_metrics += 1;
            continue;
        }
        let evidence = numbers(metric.get("evidence"));
        if numbers(metric.get("value")).iter().any(|n| !evidence.contains(n)) {
            dropped_metrics += 1;
            continue;
        }
        if !doc_numbers.is_empty() && !evidence.is_empty() && !evidence.iter().any(|n| doc_numbers.contains(n)) {
            dropped_metrics += 1;
            continue;
        }
        metrics.push(metric);
    }
    metrics.truncate(3);
    out["key_metrics"] = Json::Array(metrics);

    let known_figures: Vec<String> = figure_nums.iter().map(|n| norm_figure_num(Some(&json!(n)))).collect();
    let mut figures = Vec::new();
    for item in py_iter(out.get("result_figures"))? {
        if !item.is_object() || !known_figures.contains(&norm_figure_num(item.get("figure_num"))) {
            dropped_figures += 1;
            continue;
        }
        figures.push(item);
    }
    figures.truncate(4);
    out["result_figures"] = Json::Array(figures);

    let known_params: Vec<String> = param_names.iter().map(|n| norm_compact(Some(&json!(n)))).collect();
    let mut params = Vec::new();
    for item in py_iter(out.get("key_parameters"))? {
        if !item.is_object() || !known_params.contains(&norm_compact(item.get("name"))) {
            dropped_params += 1;
            continue;
        }
        params.push(item);
    }
    params.truncate(5);
    out["key_parameters"] = Json::Array(params);

    let mut equations: Vec<Json> = py_iter(out.get("equations"))?.into_iter().filter(Json::is_object).take(5).collect();
    for equation in &mut equations {
        let symbols: Vec<Json> = py_iter(equation.get("symbols"))?.into_iter().filter(Json::is_object).take(4).collect();
        equation["symbols"] = Json::Array(symbols);
    }
    out["equations"] = Json::Array(equations);

    let mut dropped = Map::new();
    dropped.insert("key_metrics".into(), json!(dropped_metrics));
    dropped.insert("result_figures".into(), json!(dropped_figures));
    dropped.insert("key_parameters".into(), json!(dropped_params));
    Ok((out, Json::Object(dropped)))
}

/// Row `_run_visualizations` stores when `_run_synthesis` raises (model "system").
pub fn synthesis_error_row(visualization_input: &str, message: &str) -> Json {
    json!({
        "phase": "synthesis",
        "result": python_dumps(&json!({"error": format!("종합 단계 실패: {message}")}), false),
        "model_used": "system",
        "tokens_in": null,
        "tokens_out": null,
        "cost_usd": null,
        "input_hash": legacy_input_hash(visualization_input, None, None, None),
        "interaction_id": null,
        "config_hash": legacy_input_hash("", None, None, None),
    })
}

/// Keeps the last HTTP failure so a failed call reads like the Python adapter's RuntimeError.
struct FailureProbe<'a> {
    inner: &'a dyn ProviderGateway,
    failure: Mutex<Option<Json>>,
}

impl ProviderGateway for FailureProbe<'_> {
    fn call(&self, spec: NewRequestSpec) -> BoxFuture<'_, Result<(LocalRequestId, ProviderOutcome)>> {
        Box::pin(async move {
            let (id, outcome) = self.inner.call(spec).await?;
            if let Some(content) = outcome.content.as_ref().filter(|c| c.get("http_status").is_some()) {
                if let Ok(mut slot) = self.failure.lock() {
                    *slot = Some(content.clone());
                }
            }
            Ok((id, outcome))
        })
    }
}

/// `RuntimeError` text of gemini_client/openai_client for an HTTP status error.
fn adapter_error(provider: ProviderId, failure: &Json) -> String {
    let status = failure["http_status"].as_u64().unwrap_or(0);
    let prefix = if provider == ProviderId::OpenAi { "OpenAI call failed" } else { "Interactions API call failed" };
    let kind = if status == 408 || status == 429 || status >= 500 { "after retries" } else { "(non-retryable)" };
    format!("{prefix} {kind}: Error code: {status} - {}", python_str(&failure["error"]))
}

impl PhaseExecutor for SynthesisExecutor {
    fn run<'a>(
        &'a self,
        ctx: &'a RunContext,
        gateway: &'a dyn ProviderGateway,
        input: &'a StageInput,
    ) -> BoxFuture<'a, Result<StageOutput>> {
        Box::pin(async move {
            let choice = choice(ctx, "synthesis")?;
            let failed = |message: String, ids| Ok(stage_output(synthesis_error_row(&self.visualization_input, &message), ids, None));
            let source_hash = self.source.source_hash();
            let doc_text = self.source.doc_text();
            let source_text = if doc_text.is_empty() { self.visualization_input.as_str() } else { doc_text };
            let previous = previous_results(input);
            let restart_context = chain_restart_context(&previous, 4000);

            let figures: Vec<_> = self.figures.iter().filter(|(n, _)| !n.is_empty()).collect();
            let figure_nums: Vec<String> = figures.iter().map(|(n, _)| n.clone()).collect();
            let mut figure_list = figures
                .iter()
                .map(|(n, c)| format!("- {n}: {}", c.as_deref().unwrap_or("").chars().take(200).collect::<String>()))
                .collect::<Vec<_>>()
                .join("\n");
            if figure_list.is_empty() {
                figure_list = "- (추출된 그림 없음)".into();
            }
            let param_names = match recipe_param_names(&prior_result(input, AnalysisPhase::Recipe)) {
                Ok(names) => names,
                Err(message) => return failed(message, Vec::new()),
            };
            let param_list = if param_names.is_empty() { "(추출된 파라미터 없음)".to_owned() } else { param_names.join(", ") };

            let instruction = format!(
                "{SYNTHESIS_INSTRUCTION}\n\n--- 그림 목록(figure_num: 캡션) ---\n{figure_list}\n\n--- 레시피 파라미터 이름 ---\n{param_list}"
            );
            let prev_context = previous.iter().take(4).cloned().collect::<Vec<_>>().join("\n---\n");
            let prompt_chain = format!(
                "{instruction}\n\n{}와 이전 분석 단계 결과를 바탕으로 종합해줘.",
                doc_reference_phrase(choice.provider == ProviderId::OpenAi, self.source.openai_pdf())
            );
            let prompt_fallback = format!(
                "{instruction}\n\n--- 분석 결과 (Phase 1-4) ---\n{}\n\n--- 관련 텍스트 요약 ---\n{}",
                prev_context.chars().take(9000).collect::<String>(),
                self.visualization_input
            );
            let cache_key = String::from_utf8(phase_cache_key(&CacheInput {
                model: choice.model.clone(),
                thinking: choice.effort.clone().unwrap_or_default(),
                system_instruction: self.system_instruction.clone(),
                prompt: format!("{prompt_fallback}\n{restart_context}"),
                source_signature: source_signature(source_text, source_hash, "high"),
                max_output_tokens: stage_max_output_tokens("synthesis").map(u64::from),
            })?)
            .unwrap_or_default();

            let mut ids = Vec::new();
            let call = ChainCall {
                phase: "synthesis",
                prompt_chain,
                prompt_fallback,
                system_instruction: self.system_instruction.clone(),
                previous_id: if self.source.chained { chain_previous_id(input) } else { None },
                source: self.source.source.clone(),
                restart_context,
                choice: choice.clone(),
                schema: stage_schema("synthesis")?,
                single_attempt: false,
                max_output_tokens: None,
            };
            let probe = FailureProbe { inner: gateway, failure: Mutex::new(None) };
            let (mut result, at) = match run_chain_stage(&probe, &mut ids, &call).await {
                Ok(done) => done,
                Err(error) => match probe.failure.lock().ok().and_then(|f| f.clone()) {
                    Some(failure) => return failed(adapter_error(choice.provider, &failure), ids),
                    None => return Err(error),
                },
            };
            let cost = result_cost_or_mark(&mut result, at);
            let text = result["text"].as_str().unwrap_or("").to_owned();
            if !is_error_result(&text) {
                let parsed = py_json_loads(&clean_llm_json(&text))
                    .and_then(|v| if v.is_object() { Ok(v) } else { Err("synthesis 결과가 dict가 아님".to_owned()) });
                match parsed {
                    Err(message) => result["text"] = json!(parse_error_text(&text, &message)),
                    Ok(data) => match validate_synthesis(&data, &self.body_text, &figure_nums, &param_names) {
                        Ok((mut validated, dropped)) => {
                            validated["dropped"] = dropped;
                            result["text"] = json!(python_dumps(&validated, false));
                        }
                        Err(message) => return failed(message, ids),
                    },
                }
            }
            Ok(stage_output(result_row("synthesis", &result, cost, &cache_key, &choice), ids, None))
        })
    }
}
