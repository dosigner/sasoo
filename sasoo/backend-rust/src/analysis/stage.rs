//! Shared stage helpers. Ports of `api/analysis_helpers.py` and the pure helpers of
//! `services/analysis_execution.py`; parity cases in tests/stage_helpers.rs.
use crate::{analysis::prompts::python_json_unsorted, types::Json};
use serde_json::{Map, Value, json};
use std::collections::HashSet;

pub const REVIEW_SKIP_REASON: &str = "review_paper";
const GATE_CONFIDENCE_FLOOR: f64 = 0.6;
const DEGEN_WINDOW: usize = 50;
const DEGEN_UNIQUE_RATIO: f64 = 0.15;
const DEGEN_MIN_CHARS: usize = 300;

/// `json.dumps(value, ensure_ascii=...)` with Python's default separators.
pub fn python_dumps(value: &Json, ensure_ascii: bool) -> String {
    // Encoding only fails on non-finite numbers, which serde_json cannot hold.
    python_json_unsorted(value, ensure_ascii).unwrap_or_default()
}

/// `json.loads`. shortcut: serde_json rejects NaN/Infinity, which Python accepts;
/// providers do not emit them in schema-constrained JSON. Revisit if a recording shows one.
pub fn python_loads(text: &str) -> Option<Json> {
    serde_json::from_str(text).ok()
}

/// `str.strip()`/`str.isspace()` whitespace: Unicode White_Space plus U+001C..U+001F.
fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

fn py_strip(text: &str) -> &str {
    text.trim_matches(is_py_space)
}

pub fn clean_llm_json(text: &str) -> String {
    let cleaned = py_strip(text);
    if !cleaned.starts_with("```") {
        return cleaned.to_owned();
    }
    let mut lines: Vec<&str> = cleaned.split('\n').collect();
    if lines.first().is_some_and(|l| py_strip(l).starts_with("```")) {
        lines.remove(0);
    }
    if lines.last().is_some_and(|l| py_strip(l) == "```") {
        lines.pop();
    }
    py_strip(&lines.join("\n")).to_owned()
}

pub fn is_degenerate_string(text: &str) -> bool {
    if text.chars().count() < DEGEN_MIN_CHARS {
        return false;
    }
    if zlib_says_degenerate(text.as_bytes()) {
        return true;
    }
    let words: Vec<&str> = text.split(is_py_space).filter(|w| !w.is_empty()).collect();
    if words.len() < DEGEN_WINDOW {
        return false;
    }
    let step = DEGEN_WINDOW / 2;
    let mut i = 0;
    while i + DEGEN_WINDOW <= words.len() {
        let window = &words[i..i + DEGEN_WINDOW];
        let unique: HashSet<&&str> = window.iter().collect();
        if (unique.len() as f64) / (window.len() as f64) < DEGEN_UNIQUE_RATIO {
            return true;
        }
        i += step;
    }
    false
}

/// Python: `len(zlib.compress(raw, 6)) / len(raw) < 0.05` for raw >= 500 bytes.
/// shortcut: always false until Codex adds `flate2` (already in Cargo.lock) as a direct
/// dependency; until then repetition without spaces is caught only by the word window.
fn zlib_says_degenerate(_raw: &[u8]) -> bool {
    false
}

pub fn has_degenerate_repetition(value: &Json) -> bool {
    match value {
        Value::String(s) => is_degenerate_string(s),
        Value::Object(map) => map.values().any(has_degenerate_repetition),
        Value::Array(items) => items.iter().any(has_degenerate_repetition),
        _ => false,
    }
}

pub fn stage_result_defect(text: &str) -> Option<&'static str> {
    let Some(parsed) = python_loads(&clean_llm_json(text)) else {
        return Some("JSON parse failed");
    };
    has_degenerate_repetition(&parsed).then_some("degenerate repetition detected")
}

/// Returns (cut index in chars, open containers).
fn last_complete_value_cut(chars: &[char]) -> Option<(usize, Vec<char>)> {
    let mut stack: Vec<char> = Vec::new();
    let (mut in_string, mut escape) = (false, false);
    let mut best = None;
    for (i, &ch) in chars.iter().enumerate() {
        if in_string {
            if escape {
                escape = false;
            } else if ch == '\\' {
                escape = true;
            } else if ch == '"' {
                in_string = false;
            }
            continue;
        }
        match ch {
            '"' => in_string = true,
            '{' | '[' => stack.push(ch),
            '}' | ']' => {
                stack.pop()?;
                best = Some((i + 1, stack.clone()));
            }
            ',' => best = Some((i, stack.clone())),
            _ => {}
        }
    }
    best
}

fn schema_get<'a>(schema: &'a Json, key: &str) -> Option<&'a Json> {
    schema.as_object()?.get(key)
}

fn required_keys(schema: &Json) -> Vec<String> {
    match schema_get(schema, "required") {
        Some(Value::Array(keys)) => keys.iter().filter_map(|k| k.as_str().map(str::to_owned)).collect(),
        _ => Vec::new(),
    }
}

fn empty_object() -> Json {
    Value::Object(Map::new())
}

fn prune_incomplete_items(value: Json, schema: &Json) -> Json {
    if !schema.is_object() {
        return value;
    }
    let kind = schema_get(schema, "type").and_then(Json::as_str);
    match (kind, value) {
        (Some("array"), Value::Array(items)) => {
            let item_schema = schema_get(schema, "items").filter(|s| truthy(s)).cloned().unwrap_or_else(empty_object);
            let required = required_keys(&item_schema);
            Value::Array(
                items
                    .into_iter()
                    .filter(|item| {
                        required.is_empty()
                            || item.as_object().is_some_and(|o| required.iter().all(|k| o.contains_key(k)))
                    })
                    .map(|item| prune_incomplete_items(item, &item_schema))
                    .collect(),
            )
        }
        (Some("object"), Value::Object(map)) => {
            let props = schema_get(schema, "properties").cloned().unwrap_or_else(empty_object);
            Value::Object(
                map.into_iter()
                    .map(|(k, v)| {
                        let s = props.get(&k).cloned().unwrap_or_else(empty_object);
                        (k, prune_incomplete_items(v, &s))
                    })
                    .collect(),
            )
        }
        (_, value) => value,
    }
}

fn prune_degenerate(value: &Json, schema: &Json) -> Option<Json> {
    match value {
        Value::String(s) => (!is_degenerate_string(s)).then(|| value.clone()),
        Value::Array(items) => {
            let item_schema = schema_get(schema, "items").filter(|s| truthy(s)).cloned().unwrap_or_else(empty_object);
            Some(Value::Array(items.iter().filter_map(|i| prune_degenerate(i, &item_schema)).collect()))
        }
        Value::Object(map) => {
            let props = schema_get(schema, "properties").cloned().unwrap_or_else(empty_object);
            let required = required_keys(schema);
            let mut out = Map::new();
            for (key, item) in map {
                let item_schema = props.get(key).cloned().unwrap_or_else(empty_object);
                match prune_degenerate(item, &item_schema) {
                    None if required.contains(key) => return None,
                    None => continue,
                    Some(pruned) => {
                        let empty_required_array = required.contains(key)
                            && schema_get(&item_schema, "type").and_then(Json::as_str) == Some("array")
                            && pruned.as_array().is_some_and(Vec::is_empty);
                        if empty_required_array {
                            return None;
                        }
                        out.insert(key.clone(), pruned);
                    }
                }
            }
            Some(Value::Object(out))
        }
        _ => Some(value.clone()),
    }
}

pub fn drop_degenerate_fields(text: &str, schema: &Json) -> Option<String> {
    let parsed = python_loads(&clean_llm_json(text))?;
    if !parsed.is_object() || !has_degenerate_repetition(&parsed) {
        return None;
    }
    let pruned = prune_degenerate(&parsed, schema).filter(Json::is_object)?;
    if has_degenerate_repetition(&pruned) {
        return None;
    }
    Some(python_dumps(&pruned, false))
}

pub fn salvage_truncated_json(text: &str, schema: &Json) -> Option<String> {
    let cleaned = clean_llm_json(text);
    if py_strip(&cleaned).is_empty() || python_loads(&cleaned).is_some() {
        return None;
    }
    let chars: Vec<char> = cleaned.chars().collect();
    let (index, stack) = last_complete_value_cut(&chars)?;
    let mut candidate: String = chars[..index].iter().collect();
    candidate.extend(stack.iter().rev().map(|c| if *c == '{' { '}' } else { ']' }));
    let parsed = python_loads(&candidate).filter(Json::is_object)?;
    let parsed = prune_incomplete_items(parsed, schema);
    let props = schema_get(schema, "properties").cloned().unwrap_or_else(empty_object);
    for key in required_keys(schema) {
        let value = parsed.get(&key)?;
        let is_array = props.get(&key).and_then(|p| schema_get(p, "type")).and_then(Json::as_str) == Some("array");
        if is_array && !truthy(value) {
            return None;
        }
    }
    Some(python_dumps(&parsed, false))
}

/// Python truthiness of a JSON value.
pub fn truthy(value: &Json) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// Python `float(x)` for the value types a provider JSON can hold.
fn py_float(value: Option<&Json>) -> Option<f64> {
    match value? {
        Value::Number(n) => n.as_f64(),
        Value::Bool(b) => Some(f64::from(u8::from(*b))),
        Value::String(s) => py_strip(s).parse().ok(),
        _ => None,
    }
}

pub fn paper_type(screening: &Json) -> &'static str {
    match screening.get("paper_type").and_then(Json::as_str) {
        Some("article") => "article",
        Some("letter") => "letter",
        Some("review") => "review",
        _ if screening.get("methodology_type").and_then(Json::as_str) == Some("review") => "review",
        _ => "article",
    }
}

/// `_screening_gate_decision`: (skip, reason) for recipe or deep_dive.
pub fn screening_gate_decision(screening_text: Option<&str>, phase: &str) -> (bool, String) {
    let none = (false, String::new());
    let Some(text) = screening_text.filter(|t| !t.is_empty()) else { return none };
    let Some(payload) = python_loads(&clean_llm_json(text)).filter(Json::is_object) else { return none };
    match payload.get("relevance_score") {
        None | Some(Value::Null) => return none,
        Some(Value::String(s)) if s.is_empty() => return none,
        _ => {}
    }
    let Some(relevance) = py_float(payload.get("relevance_score")) else { return none };
    if relevance < 0.35 {
        return (true, "low_relevance_screening".into());
    }
    if phase == "deep_dive" && paper_type(&payload) == "review" {
        return (true, REVIEW_SKIP_REASON.into());
    }
    match payload.get(&format!("{phase}_applicable")) {
        Some(Value::Bool(false)) => {
            let confidence = py_float(payload.get("confidence")).unwrap_or(1.0);
            if confidence < GATE_CONFIDENCE_FLOOR {
                return none;
            }
            return (true, format!("not_applicable_{phase}"));
        }
        Some(Value::Bool(true)) => return none,
        _ => {}
    }
    let domain = payload
        .get("domain")
        .filter(|d| truthy(d))
        .map(|d| match d {
            Value::String(s) => py_strip(s).to_lowercase(),
            other => other.to_string().to_lowercase(),
        })
        .unwrap_or_default();
    let topics = payload.get("key_topics").filter(|t| truthy(t)).map_or(0, |t| match t {
        Value::Array(a) => a.len(),
        Value::String(s) => s.chars().count(),
        Value::Object(o) => o.len(),
        _ => 0,
    });
    let experimental = payload.get("is_experimental").is_none_or(truthy);
    if relevance < 0.5 && (domain == "general" || domain == "unknown") && (!experimental || topics < 2) {
        return (true, "low_confidence_screening".into());
    }
    none
}

/// `_build_chain_restart_context`.
pub fn chain_restart_context(previous: &[String], per_stage_limit: usize) -> String {
    previous
        .iter()
        .filter(|r| !r.is_empty())
        .map(|r| r.chars().take(per_stage_limit).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n\n")
}

/// Result text of `_store_skipped_phase_result`.
pub fn skipped_result_text(reason: &str, title: &str, message: Option<&str>) -> String {
    let message = match message {
        Some(m) if !m.is_empty() => m.to_owned(),
        _ if reason == REVIEW_SKIP_REASON => format!("Review 논문이라 {title} 대신 리뷰 지도를 만들었습니다."),
        _ => format!("{title} 단계는 스크리닝 신호가 약해 자동 실행을 건너뛰었습니다."),
    };
    python_dumps(&json!({"skipped": true, "reason": reason, "message": message}), false)
}

/// `_skip_reason`: the reason of a skip row, "" otherwise.
pub fn skip_reason(text: &str) -> String {
    if text.is_empty() {
        return String::new();
    }
    match python_loads(&clean_llm_json(text)) {
        Some(Value::Object(payload)) if payload.get("skipped").is_some_and(truthy) => {
            match payload.get("reason").filter(|r| truthy(r)) {
                Some(Value::String(s)) => s.clone(),
                Some(other) => other.to_string(),
                None => "skipped".into(),
            }
        }
        _ => String::new(),
    }
}

/// `_is_error_result`.
pub fn is_error_result(text: &str) -> bool {
    if py_strip(text).is_empty() {
        return true;
    }
    match python_loads(text) {
        Some(Value::Object(o)) => o.contains_key("_parse_error") || o.contains_key("error"),
        _ => false,
    }
}

/// `json.dumps({"_raw": raw, "_parse_error": reason})`, ASCII-escaped like Python's default.
pub fn parse_error_text(raw: &str, reason: &str) -> String {
    python_dumps(&json!({"_raw": raw, "_parse_error": reason}), true)
}

// ---------------------------------------------------------------------------
// Rows, cost and provider calls
// ---------------------------------------------------------------------------

use crate::{
    analysis::{
        cache::legacy_input_hash,
        graph::{InputCoverage, ProviderGateway, RunContext, StageOutput},
        pricing::{legacy_rates, price, reported_usage},
    },
    error::{Result as SasooResult, SasooError},
    providers::types::NewRequestSpec,
    types::{LocalRequestId, ProviderId},
};

pub fn provider_name(provider: ProviderId) -> &'static str {
    match provider {
        ProviderId::OpenAi => "openai",
        ProviderId::Gemini => "gemini",
    }
}

/// Role choice frozen in the run snapshot (`model_registry.resolve(role, provider)`).
#[derive(Debug, Clone)]
pub struct ModelChoice {
    pub provider: ProviderId,
    pub model: String,
    pub effort: Option<String>,
}

pub fn choice(ctx: &RunContext, role: &str) -> SasooResult<ModelChoice> {
    let input = ctx.snapshot.snapshot();
    let missing = || SasooError::InvalidInput(format!("Run snapshot has no model for role {role}"));
    Ok(ModelChoice {
        provider: *input.provider_roles.get(role).ok_or_else(missing)?,
        model: input.models.get(role).ok_or_else(missing)?.clone(),
        effort: input.efforts.get(role).cloned().flatten(),
    })
}

/// `calc_result_cost`; `at` fixes the pinned rate day.
pub fn result_cost(result: &Json, at: i64) -> SasooResult<f64> {
    if let Some(prior) = result.get("cost_usd_prior_attempts").filter(|v| !v.is_null()) {
        return prior
            .as_f64()
            .filter(|p| p.is_finite() && *p >= 0.0 && !prior.is_boolean())
            .ok_or_else(|| SasooError::InvalidInput("Prior-attempt total must be a finite non-negative cost".into()));
    }
    let model = result
        .get("model")
        .and_then(Json::as_str)
        .filter(|m| !m.is_empty())
        .ok_or_else(|| SasooError::InvalidInput("A model is required to price usage".into()))?;
    let usage = reported_usage(result)?;
    let cost = price(&usage, &legacy_rates(model, at, usage.tokens_in)?, at)?;
    cost.to_string()
        .parse()
        .map_err(|_| SasooError::Internal("Cost is not a float".into()))
}

/// `_combine_retry_usage`: the retry dict carries both attempts' usage.
pub fn combine_retry_usage(first: &Json, retry: &mut Json, at: i64) {
    match (result_cost(first, at), result_cost(retry, at)) {
        (Ok(a), Ok(b)) => retry["cost_usd_prior_attempts"] = json!(a + b),
        _ => retry["usage_complete"] = json!(false),
    }
    for key in ["tokens_in", "tokens_out"] {
        let sum = match (first.get(key).and_then(Json::as_u64), retry.get(key).and_then(Json::as_u64)) {
            (Some(a), Some(b)) => json!(a + b),
            _ => Json::Null,
        };
        retry[key] = sum;
    }
}

/// `_result_cost`: a usage the pricing rules reject turns the row into a parse error.
pub fn result_cost_or_mark(result: &mut Json, at: i64) -> Option<f64> {
    match result_cost(result, at) {
        Ok(cost) => Some(cost),
        Err(error) => {
            let raw = result.get("raw_text").or_else(|| result.get("text")).cloned().unwrap_or(json!(""));
            let usage: Map<String, Json> = ["tokens_in", "tokens_out", "tokens_cached", "tokens_cache_write", "usage_complete"]
                .iter()
                .map(|k| ((*k).to_owned(), result.get(*k).cloned().unwrap_or(Json::Null)))
                .collect();
            result["text"] = json!(python_dumps(
                &json!({"_raw": raw, "_parse_error": error.to_string(), "_usage": usage}),
                false
            ));
            None
        }
    }
}

/// One stored `analysis_results` row, the payload a stage executor hands to W05.
pub fn result_row(
    phase: &str,
    result: &Json,
    cost: Option<f64>,
    input_text: &str,
    choice: &ModelChoice,
) -> Json {
    let provider = provider_name(choice.provider);
    let effort = choice.effort.as_deref();
    json!({
        "phase": phase,
        "result": result.get("text").cloned().unwrap_or(json!("")),
        "model_used": result.get("model").cloned().unwrap_or(json!(choice.model)),
        "tokens_in": result.get("tokens_in").cloned().unwrap_or(Json::Null),
        "tokens_out": result.get("tokens_out").cloned().unwrap_or(Json::Null),
        "cost_usd": cost,
        "input_hash": legacy_input_hash(input_text, Some(provider), Some(&choice.model), effort),
        "interaction_id": result.get("interaction_id").cloned().unwrap_or(Json::Null),
        "config_hash": legacy_input_hash("", Some(provider), Some(&choice.model), effort),
    })
}

/// Calls the gateway and returns the Python-shaped result dict.
pub async fn call(
    gateway: &dyn ProviderGateway,
    spec: NewRequestSpec,
    request_ids: &mut Vec<LocalRequestId>,
) -> SasooResult<(Json, i64)> {
    let (id, outcome) = gateway.call(spec).await?;
    request_ids.push(id);
    let result = outcome
        .content
        .filter(|c| c.get("text").is_some())
        .ok_or_else(|| SasooError::Incomplete("Provider call returned no result".into()))?;
    Ok((result, outcome.received_at))
}

pub fn is_unfinished(result: &Json) -> bool {
    result.get("usage_complete") == Some(&json!(false))
        || result.get("tokens_in").is_none_or(Json::is_null)
        || result.get("tokens_out").is_none_or(Json::is_null)
        || result.get("incomplete").is_some_and(truthy)
        || matches!(result.get("response_status").and_then(Json::as_str), Some("incomplete" | "failed" | "cancelled"))
}

pub fn stage_output(row: Json, request_ids: Vec<LocalRequestId>, skip_reason: Option<String>) -> StageOutput {
    StageOutput { payload: row, request_ids, coverage: InputCoverage::Full, artifact_refs: Vec::new(), skip_reason }
}

// ---------------------------------------------------------------------------
// Source identity, coverage and the chain stage (`_run_chain_stage`)
// ---------------------------------------------------------------------------

use crate::providers::types::{InputPart, PdfPart, ProviderFileRef, ProviderInput};
use sha2::{Digest, Sha256};

pub const OPENAI_DOC_TEXT_CHAR_LIMIT: usize = 150_000;
pub const UNFINISHED: &str = "응답이 완료되지 않았습니다";
pub const SALVAGED_NOTE: &str = "잘린 응답에서 복구한 일부 결과입니다.";
pub const PRUNED_NOTE: &str = "반복 출력으로 손상된 필드를 제외한 일부 결과입니다.";

/// Python `str(value)` inside an f-string.
pub fn python_str(value: &Json) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::String(s) => s.clone(),
        Value::Array(_) | Value::Object(_) => python_repr(value),
        Value::Number(_) => python_dumps(value, false),
    }
}

/// Python `f"{n:,}"` for a non-negative integer.
pub fn thousands(n: usize) -> String {
    let digits = n.to_string();
    let mut out = String::new();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(c);
    }
    out
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes).iter().map(|b| format!("{b:02x}")).collect()
}

/// `document_context.source_signature`.
pub fn source_signature(text: &str, pdf_sha256: Option<&str>, detail: &str) -> String {
    super::document_context::source_signature(text, pdf_sha256, detail)
}

/// `document_context.input_coverage`.
pub fn input_coverage(text: &str, pdf_sha256: Option<&str>, text_limit: Option<usize>) -> Json {
    super::document_context::input_coverage(text, pdf_sha256, text_limit.map(|l| l as i64))
}

/// The paper source a chain attaches on its first call.
#[derive(Clone, Debug)]
pub enum ChainSource {
    None,
    GeminiFile(ProviderFileRef),
    OpenAiPdf { path: std::path::PathBuf, sha256: crate::types::Hash256 },
    DocText(String),
}

pub struct ChainCall<'a> {
    pub phase: &'a str,
    pub prompt_chain: String,
    pub prompt_fallback: String,
    pub system_instruction: String,
    pub previous_id: Option<String>,
    pub source: ChainSource,
    pub restart_context: String,
    pub choice: ModelChoice,
    pub schema: Json,
    pub single_attempt: bool,
    pub max_output_tokens: Option<u32>,
}

/// `_STAGE_MAX_OUTPUT_TOKENS`.
pub fn stage_max_output_tokens(phase: &str) -> Option<u32> {
    match phase {
        "recipe" => Some(24_000),
        "deep_dive" | "review_map" => Some(16_000),
        _ => None,
    }
}

fn chain_spec(call: &ChainCall) -> NewRequestSpec {
    let output_cap = call.max_output_tokens.or_else(|| stage_max_output_tokens(call.phase));
    let mut parts = Vec::new();
    let has_source = !matches!(call.source, ChainSource::None);
    let store = has_source;
    let mut previous_id = None;
    if has_source && call.previous_id.is_none() {
        let mut chain_text = call.prompt_chain.clone();
        if !call.restart_context.is_empty() {
            chain_text = format!("{}\n\n이전 분석 단계 결과(체인 재시작으로 복원):\n{}", call.prompt_chain, call.restart_context);
        }
        match &call.source {
            ChainSource::OpenAiPdf { path, sha256 } => {
                parts.push(InputPart::Pdf(PdfPart::Inline { source_sha256: *sha256, path: path.clone() }));
                parts.push(InputPart::Text(chain_text));
            }
            ChainSource::GeminiFile(file) => {
                parts.push(InputPart::Pdf(PdfPart::File(file.clone())));
                parts.push(InputPart::Text(chain_text));
            }
            ChainSource::DocText(doc_text) => {
                let label = if doc_text.chars().count() >= OPENAI_DOC_TEXT_CHAR_LIMIT {
                    format!("[논문 본문({}자 절단)]", thousands(OPENAI_DOC_TEXT_CHAR_LIMIT))
                } else {
                    "[논문 전문]".to_owned()
                };
                parts.push(InputPart::Text(format!("{label}\n{doc_text}\n\n{chain_text}")));
            }
            ChainSource::None => {}
        }
    } else if has_source {
        parts.push(InputPart::Text(call.prompt_chain.clone()));
        previous_id = call.previous_id.clone();
    } else {
        parts.push(InputPart::Text(call.prompt_fallback.clone()));
    }
    NewRequestSpec {
        provider: call.choice.provider,
        model: call.choice.model.clone(),
        input: ProviderInput { parts },
        instructions: Some(call.system_instruction.clone()).filter(|s| !s.is_empty()),
        schema: Some(call.schema.clone()),
        strict_schema: call.phase == "deep_dive" && call.choice.provider == ProviderId::OpenAi,
        effort: call.choice.effort.clone(),
        previous_id,
        store,
        max_output_tokens: output_cap,
        service_tier: None,
        source_identity: None,
    }
}

fn status_unfinished(result: &Json) -> bool {
    result.get("incomplete").is_some_and(truthy)
        || matches!(result.get("response_status").and_then(Json::as_str), Some("incomplete" | "failed" | "cancelled"))
}

/// `_run_chain_stage`: one call, then salvage, one retry, or degenerate-field pruning.
pub async fn run_chain_stage(
    gateway: &dyn ProviderGateway,
    ids: &mut Vec<LocalRequestId>,
    call_spec: &ChainCall<'_>,
) -> SasooResult<(Json, i64)> {
    let spec = chain_spec(call_spec);
    let (mut result, at) = call(gateway, spec.clone(), ids).await?;
    let text = result["text"].as_str().unwrap_or("").to_owned();
    result["raw_text"] = json!(text);
    if is_unfinished(&result) {
        result["text"] = json!(parse_error_text(&text, UNFINISHED));
        return Ok((result, at));
    }
    let Some(defect) = stage_result_defect(&text) else { return Ok((result, at)) };
    if call_spec.single_attempt {
        result["text"] = json!(parse_error_text(&text, defect));
        return Ok((result, at));
    }
    let salvaged = if call_spec.phase == "deep_dive" { None } else { salvage_truncated_json(&text, &call_spec.schema) };
    if let Some(salvaged) = salvaged {
        let mut payload = python_loads(&salvaged).unwrap_or(Json::Null);
        payload["_partial"] = json!(SALVAGED_NOTE);
        result["text"] = json!(python_dumps(&payload, false));
        return Ok((result, at));
    }
    let (mut retry, retry_at) = call(gateway, spec, ids).await?;
    combine_retry_usage(&result, &mut retry, at);
    let raw = retry["text"].as_str().unwrap_or("").to_owned();
    retry["raw_text"] = json!(raw);
    if status_unfinished(&retry) {
        retry["text"] = json!(parse_error_text(&raw, UNFINISHED));
        return Ok((retry, retry_at));
    }
    if stage_result_defect(&raw) == Some("degenerate repetition detected") {
        if let Some(pruned) = drop_degenerate_fields(&raw, &call_spec.schema) {
            let mut payload = python_loads(&pruned).unwrap_or(Json::Null);
            payload["_partial"] = json!(PRUNED_NOTE);
            retry["text"] = json!(python_dumps(&payload, false));
        }
    }
    Ok((retry, retry_at))
}

/// Stored result texts of earlier stages, as `run_full_analysis` builds `previous`.
pub fn previous_results(input: &crate::analysis::graph::StageInput) -> Vec<String> {
    input
        .prior
        .iter()
        .filter_map(|p| p.payload.get("result").and_then(Json::as_str))
        .filter(|t| !t.is_empty() && !is_error_result(t))
        .map(str::to_owned)
        .collect()
}

/// `chain_prev_id`: remote ID of the latest chain stage (visual, recipe, deep_dive).
pub fn chain_previous_id(input: &crate::analysis::graph::StageInput) -> Option<String> {
    use crate::analysis::graph::AnalysisPhase::{DeepDive, Recipe, Visual};
    input
        .prior
        .iter()
        .rev()
        .find(|p| matches!(p.phase, Visual | Recipe | DeepDive))
        .and_then(|p| p.remote_id.clone())
}

pub fn prior_result(input: &crate::analysis::graph::StageInput, phase: crate::analysis::graph::AnalysisPhase) -> String {
    input
        .prior
        .iter()
        .find(|p| p.phase == phase)
        .and_then(|p| p.payload.get("result").and_then(Json::as_str))
        .unwrap_or("")
        .to_owned()
}

/// Row of `_store_skipped_phase_result` (model "system", no provider identity).
pub fn skipped_row(phase: &str, reason: &str, title: &str, message: Option<&str>) -> Json {
    let input_text = String::from_utf8(
        crate::analysis::prompts::python_json_bytes(&json!({"phase": phase, "skip_reason": reason}), false).unwrap_or_default(),
    )
    .unwrap_or_default();
    json!({
        "phase": phase,
        "result": skipped_result_text(reason, title, message),
        "model_used": "system",
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "input_hash": legacy_input_hash(&input_text, None, None, None),
        "interaction_id": null,
        "config_hash": legacy_input_hash("", None, None, None),
    })
}

// ---------------------------------------------------------------------------
// Python repr and `summary_contract.py`
// ---------------------------------------------------------------------------

/// Python `repr(str)`. shortcut: escapes only ASCII control chars; Python also escapes
/// non-printable Unicode (e.g. U+200B), which model JSON rarely contains.
pub fn python_repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::from(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => out.push_str(&format!("\\x{:02x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// Python `repr(value)` of a JSON-decoded value.
pub fn python_repr(value: &Json) -> String {
    match value {
        Value::String(s) => python_repr_str(s),
        Value::Array(items) => format!("[{}]", items.iter().map(python_repr).collect::<Vec<_>>().join(", ")),
        Value::Object(map) => format!(
            "{{{}}}",
            map.iter().map(|(k, v)| format!("{}: {}", python_repr_str(k), python_repr(v))).collect::<Vec<_>>().join(", ")
        ),
        other => python_str(other),
    }
}

/// `json.loads(text, object_pairs_hook=unique_fields)`: duplicate keys are an error.
pub fn loads_unique(text: &str) -> std::result::Result<Json, String> {
    use serde::de::{self, Deserializer, MapAccess, SeqAccess, Visitor};
    struct Unique;
    impl<'de> Visitor<'de> for Unique {
        type Value = Json;
        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            f.write_str("JSON")
        }
        fn visit_bool<E>(self, v: bool) -> std::result::Result<Json, E> { Ok(Value::Bool(v)) }
        fn visit_i64<E>(self, v: i64) -> std::result::Result<Json, E> { Ok(json!(v)) }
        fn visit_u64<E>(self, v: u64) -> std::result::Result<Json, E> { Ok(json!(v)) }
        fn visit_f64<E>(self, v: f64) -> std::result::Result<Json, E> { Ok(json!(v)) }
        fn visit_str<E>(self, v: &str) -> std::result::Result<Json, E> { Ok(json!(v)) }
        fn visit_string<E>(self, v: String) -> std::result::Result<Json, E> { Ok(Value::String(v)) }
        fn visit_unit<E>(self) -> std::result::Result<Json, E> { Ok(Value::Null) }
        fn visit_none<E>(self) -> std::result::Result<Json, E> { Ok(Value::Null) }
        fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> std::result::Result<Json, A::Error> {
            let mut items = Vec::new();
            while let Some(item) = seq.next_element_seed(UniqueSeed)? {
                items.push(item);
            }
            Ok(Value::Array(items))
        }
        fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> std::result::Result<Json, A::Error> {
            let mut out = Map::new();
            while let Some(key) = map.next_key::<String>()? {
                if out.contains_key(&key) {
                    return Err(de::Error::custom(format!("심층 분석 응답에 중복된 키가 있습니다: {key}")));
                }
                let value = map.next_value_seed(UniqueSeed)?;
                out.insert(key, value);
            }
            Ok(Value::Object(out))
        }
    }
    struct UniqueSeed;
    impl<'de> de::DeserializeSeed<'de> for UniqueSeed {
        type Value = Json;
        fn deserialize<D: Deserializer<'de>>(self, d: D) -> std::result::Result<Json, D::Error> {
            d.deserialize_any(Unique)
        }
    }
    let mut de = serde_json::Deserializer::from_str(text);
    let parsed = de.deserialize_any(Unique).and_then(|v| de.end().map(|()| v));
    parsed.map_err(|e| {
        let msg = e.to_string();
        if msg.starts_with("심층 분석 응답에 중복된 키가 있습니다") {
            // serde appends " at line L column C"; keep only the duplicate-key message.
            msg.split(" at line ").next().unwrap_or(&msg).to_owned()
        } else {
            json_error_message(text)
        }
    })
}

/// `parse_summary_json`.
pub fn parse_summary_json(text: &str) -> std::result::Result<Json, String> {
    let payload = loads_unique(text)?;
    if !payload.is_object() {
        return Err("심층 분석 응답이 객체가 아닙니다".into());
    }
    let mut pending: Vec<&Json> = vec![&payload];
    let mut keys: Vec<&str> = Vec::new();
    let bad = |s: &str| s.chars().any(|c| (c as u32) < 32 && !matches!(c, '\t' | '\n' | '\r'));
    while let Some(value) = pending.pop() {
        match value {
            Value::Object(map) => {
                keys.extend(map.keys().map(String::as_str));
                pending.extend(map.values());
            }
            Value::Array(items) => pending.extend(items),
            Value::String(s) if bad(s) => return Err("심층 분석 응답에 표시할 수 없는 제어 문자가 있습니다".into()),
            _ => {}
        }
    }
    if keys.into_iter().any(bad) {
        return Err("심층 분석 응답에 표시할 수 없는 제어 문자가 있습니다".into());
    }
    Ok(payload)
}

/// `validate_summary_extensions(data, require=True)`.
pub fn validate_summary_extensions(data: &Json) -> std::result::Result<(), String> {
    let obj = data.as_object().ok_or("심층 분석 응답 형식을 확인하지 못했어요")?;
    if obj.contains_key("_parse_error") || obj.contains_key("error") {
        return Err("심층 분석 응답 형식을 확인하지 못했어요".into());
    }
    if !(obj.contains_key("section_answers") && obj.contains_key("transfer_checks")) {
        return Err("요약 확장 필드가 누락됐습니다".into());
    }
    let rules: [(&str, usize, &[&str]); 2] = [
        ("section_answers", 12, &["section_title", "question", "answer", "explanation"]),
        ("transfer_checks", 8, &["item", "paper_condition", "check_before_transfer"]),
    ];
    for (name, maximum, fields) in rules {
        let entries = obj[name].as_array().filter(|e| e.len() <= maximum).ok_or(format!("{name} 배열 형식 또는 항목 수가 잘못됐습니다"))?;
        for entry in entries {
            let entry = entry.as_object().ok_or(format!("{name} 항목이 객체가 아닙니다"))?;
            for field in fields {
                let ok = entry.get(*field).and_then(Json::as_str).is_some_and(|v| *field == "explanation" || !py_strip(v).is_empty());
                if !ok {
                    return Err(format!("{name}.{field} 문자열이 잘못됐습니다"));
                }
            }
            let refs = entry.get("source_refs").and_then(Json::as_array).filter(|r| r.len() <= 4).ok_or(format!("{name}.source_refs 배열이 잘못됐습니다"))?;
            if !refs.iter().all(|r| r.as_str().is_some_and(|s| !py_strip(s).is_empty())) {
                return Err(format!("{name}.source_refs 출처가 잘못됐습니다"));
            }
            if name == "section_answers" {
                if refs.is_empty() {
                    return Err("핵심 답변에 출처가 필요합니다".into());
                }
            } else {
                let basis = entry.get("condition_basis").and_then(Json::as_str);
                if !matches!(basis, Some("reported" | "inferred" | "not_reported")) {
                    return Err("적용 조건의 근거 성격이 잘못됐습니다".into());
                }
                if basis != Some("not_reported") && refs.is_empty() {
                    return Err("명시 또는 추론 조건에 출처가 필요합니다".into());
                }
            }
        }
    }
    Ok(())
}

#[path = "stage_schemas.rs"]
mod stage_schemas;

/// Stage response schema in Python dict order (`legacy_schema` holds the same content
/// with sorted keys, which changes OpenAI strict `required` order).
pub fn stage_schema(stage: &str) -> SasooResult<Json> {
    let text = stage_schemas::stage_schema(stage).ok_or_else(|| SasooError::NotFound(format!("Unknown stage schema {stage}")))?;
    serde_json::from_str(text).map_err(|_| SasooError::Internal("Stage schema is invalid".into()))
}

/// `str(json.JSONDecodeError)` for invalid JSON, as Python stores it in `_parse_error`.
pub fn json_error_message(text: &str) -> String {
    crate::analysis::citation::py_json_loads(text).err().unwrap_or_else(|| "JSON parse failed".into())
}
