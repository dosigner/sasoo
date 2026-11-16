//! Phase 2 citation analysis (port of `_run_citation`, analysis_execution.py).
#[path = "citation_analyzer.rs"]
mod citation_analyzer;
pub use citation_analyzer::analyze_citations;
use citation_analyzer::py_strip;

use crate::{
    analysis::{
        cache::CITATION_PROMPT_VERSION,
        graph::{PhaseExecutor, ProviderGateway, RunContext, StageInput, StageOutput},
        prompts::python_json_bytes,
        schemas::legacy_schema,
        screening::stage::{
            call, choice, clean_llm_json, python_dumps, python_loads, result_cost, result_cost_or_mark, result_row,
            stage_output, truthy,
        },
    },
    error::{Result, SasooError},
    providers::{
        transport::BoxFuture,
        types::{InputPart, NewRequestSpec, ProviderInput},
    },
    types::Json,
};
use serde_json::{Map, Value, json};

const TOP_N: usize = 7;
/// `MODEL_CITATION`: the cache key names this constant, not the resolved role model.
const MODEL_CITATION: &str = "gemini-3.8-flash";
const BACKGROUND_SECTIONS: [&str; 2] = ["introduction", "acknowledgments"];
const UNFINISHED: &str = "인용 분석 응답이 완료되지 않았습니다";
const INVALID: &str = "인용 분석의 필수 해석이 없거나 형식이 잘못됐습니다";

/// Holds the per-run inputs `_run_citation` reads; built by the graph owner.
pub struct CitationExecutor {
    /// Section name and text in document order (`sections` dict).
    pub sections: Vec<(String, String)>,
    pub citation_body: String,
    pub citation_references: String,
    pub paper_authors: String,
}

fn head(text: &str, count: usize) -> String {
    text.chars().take(count).collect()
}

fn text_of(value: Option<&Json>) -> String {
    value.and_then(Json::as_str).unwrap_or("").to_owned()
}

/// Python `str(value)` for the JSON scalars the local result holds.
fn py_str(value: Option<&Json>) -> String {
    match value {
        None | Some(Value::Null) => "None".into(),
        Some(Value::String(s)) => s.clone(),
        Some(Value::Bool(b)) => if *b { "True" } else { "False" }.into(),
        Some(other) => other.to_string(),
    }
}

/// `_norm_ref_id`. shortcut: only ASCII leading digits are normalised (Python `\d` is Unicode).
pub fn norm_ref_id(raw: &str) -> String {
    let mut s = py_strip(raw).to_lowercase().replace(['[', ']', '(', ')', '#'], "");
    if s.starts_with("ref") {
        s.drain(..3);
    }
    let s = py_strip(&s);
    let digits: String = s.chars().take_while(char::is_ascii_digit).collect();
    if digits.is_empty() {
        return s.to_owned();
    }
    let trimmed = digits.trim_start_matches('0');
    if trimmed.is_empty() { "0".into() } else { trimmed.to_owned() }
}

/// `_select_citation_top_refs`.
pub fn select_top_refs(local: &Json) -> Vec<Json> {
    let top = local["top_cited"].as_array().cloned().unwrap_or_default();
    let labels = |r: &Json| -> Vec<String> {
        r.get("section_counts").and_then(Json::as_object).map(|m| m.keys().cloned().collect()).unwrap_or_default()
    };
    if !top.iter().any(|r| labels(r).iter().any(|s| !s.is_empty())) {
        return top.into_iter().take(TOP_N).collect();
    }
    top.into_iter()
        .filter(|r| labels(r).iter().any(|s| !BACKGROUND_SECTIONS.contains(&s.as_str())))
        .take(TOP_N)
        .collect()
}

/// `_citation_cache_key` (json.dumps sort_keys=True).
pub fn citation_cache_key(local: &Json, body: &str) -> Result<String> {
    let top: Vec<Json> = select_top_refs(local)
        .iter()
        .map(|r| {
            let contexts: Vec<Json> = r["cite_contexts"]
                .as_array()
                .map(|cs| {
                    cs.iter()
                        .take(5)
                        .map(|c| json!({"s": head(&text_of(c.get("sentence")), 300), "sec": text_of(c.get("section"))}))
                        .collect()
                })
                .unwrap_or_default();
            json!({"ref_id": r.get("ref_id"), "cite_count": r.get("cite_count"), "contexts": contexts})
        })
        .collect();
    let payload = json!({
        "v": CITATION_PROMPT_VERSION,
        "phase": "citation",
        "model": MODEL_CITATION,
        "total_references": local.get("total_references").cloned().unwrap_or(json!(0)),
        "citation_style": local.get("citation_style").cloned().unwrap_or(json!("")),
        "self_citation_count": local.get("self_citation_count").cloned().unwrap_or(json!(0)),
        "top": top,
        "body": head(body, 3000),
    });
    sorted_dumps(&payload)
}

fn sorted_dumps(value: &Json) -> Result<String> {
    String::from_utf8(python_json_bytes(value, false)?).map_err(|_| SasooError::Internal("JSON is not UTF-8".into()))
}

pub fn citation_prompt(local: &Json, top_refs: &[Json], body: &str) -> String {
    let mut refs_text = String::new();
    for (i, r) in top_refs.iter().enumerate() {
        let parts: Vec<String> = r["cite_contexts"]
            .as_array()
            .map(|cs| {
                cs.iter()
                    .take(5)
                    .map(|c| {
                        let sentence = head(&text_of(c.get("sentence")), 300);
                        let sec = text_of(c.get("section"));
                        let sec = py_strip(&sec);
                        if sentence.is_empty() {
                            String::new()
                        } else {
                            format!("[{}] {sentence}", if sec.is_empty() { "위치미상" } else { sec })
                        }
                    })
                    .filter(|p| !p.is_empty())
                    .collect()
            })
            .unwrap_or_default();
        refs_text += &format!(
            "{}. {} {} ({}): \"{}\" [{}] — 인용 {}회\n   인용 맥락: {}\n\n",
            i + 1,
            text_of(r.get("ref_id")),
            text_of(r.get("authors")),
            py_str(r.get("year")),
            text_of(r.get("title")),
            text_of(r.get("journal")),
            py_str(r.get("cite_count")),
            parts.join("; "),
        );
    }
    let ratio = local["self_citation_ratio"].as_f64().unwrap_or(0.0) * 100.0;
    format!(
        "아래는 로컬 파서가 이 논문에서 추출한 참고문헌 통계와 상위 인용 맥락이야.

[인용 데이터]
총 참고문헌 수: {total}
인용 스타일: {style}
셀프 인용: {self_count}건 (비율: {ratio:.1}%)

가장 많이 인용된 상위 {TOP_N}개 참고문헌과 인용 맥락:
{refs_text}

[논문 본문 발췌 (맥락용)]
{excerpt}

위 데이터에 근거해서만 이 논문 내부의 인용 사용 패턴을 분석해줘.

규칙:
- citation_role은 인용 맥락과 참고문헌의 제목·저널 정보를 근거로 가장 그럴듯한 역할을 골라. 제목·저널도 위에 제공된 데이터니까 이를 근거로 판단하는 건 날조가 아니야.
- \"unclear\"는 최후 수단이야 — 인용 맥락과 제목·저널 어느 쪽으로도 판단할 수 없을 때만 써.
- evidence_context에는 분류 근거가 된 인용 맥락 문장을 위 자료에서 한 구절 그대로 옮겨 적어. 맥락이 아닌 제목·저널로 판단했다면 \"(제목 근거)\"라고 적어.
- why_cited는 왜 자주 인용됐는지 2-3문장(한국어)으로 써.
- 참고문헌의 실제 내용·존재 여부·학계 전체 영향력은 검증된 것처럼 말하지 마.
- key_influences는 위에 제시된 참고문헌 안에서만 골라 — 목록에 없는 연구를 추가하지 마.
- summary는 전체 인용 패턴 평가 2-3문장(한국어). limitations에는 상위 {TOP_N}개와 본문 발췌만 본 평가라는 한계를 한 문장으로 남겨.
",
        total = py_str(local.get("total_references")),
        style = text_of(local.get("citation_style")),
        self_count = py_str(local.get("self_citation_count")),
        excerpt = head(body, 3000),
    )
}

/// `Draft202012Validator(schema).is_valid` for the keywords the citation schema uses.
fn schema_valid(value: &Json, schema: &Json) -> bool {
    let type_ok = match schema.get("type").and_then(Json::as_str) {
        Some("object") => value.is_object(),
        Some("array") => value.is_array(),
        Some("string") => value.is_string(),
        Some("number") => value.is_number(),
        Some("integer") => value.is_i64() || value.is_u64(),
        Some("boolean") => value.is_boolean(),
        _ => true,
    };
    let enum_ok = schema.get("enum").and_then(Json::as_array).is_none_or(|e| e.contains(value));
    let required_ok = schema.get("required").and_then(Json::as_array).is_none_or(|keys| {
        value.as_object().is_none_or(|o| keys.iter().all(|k| k.as_str().is_some_and(|k| o.contains_key(k))))
    });
    let props_ok = match (value.as_object(), schema.get("properties").and_then(Json::as_object)) {
        (Some(o), Some(props)) => props.iter().all(|(k, s)| o.get(k).is_none_or(|v| schema_valid(v, s))),
        _ => true,
    };
    let items_ok = match (value.as_array(), schema.get("items")) {
        (Some(items), Some(s)) => items.iter().all(|v| schema_valid(v, s)),
        _ => true,
    };
    type_ok && enum_ok && required_ok && props_ok && items_ok
}

/// `json.loads` with CPython's `JSONDecodeError` text (C scanner, Python 3.14).
pub fn py_json_loads(text: &str) -> std::result::Result<Json, String> {
    let chars: Vec<char> = text.chars().collect();
    let fail = |msg: &str, pos: usize| {
        let line = chars[..pos].iter().filter(|c| **c == '\n').count() + 1;
        let col = pos - chars[..pos].iter().rposition(|c| *c == '\n').map_or(0, |i| i + 1) + 1;
        format!("{msg}: line {line} column {col} (char {pos})")
    };
    if chars.first() == Some(&'\u{feff}') {
        return Err(fail("Unexpected UTF-8 BOM (decode using utf-8-sig)", 0));
    }
    let scanner = PyScanner { s: &chars };
    let start = scanner.ws(0);
    let end = scanner.value(start).map_err(|(m, p)| fail(m, p))?;
    let end = scanner.ws(end);
    if end != chars.len() {
        return Err(fail("Extra data", end));
    }
    // shortcut: values CPython accepts but serde rejects (NaN, lone surrogates) get this text.
    python_loads(text).ok_or_else(|| "JSON parse failed".to_owned())
}

struct PyScanner<'a> {
    s: &'a [char],
}

type ScanResult = std::result::Result<usize, (&'static str, usize)>;

impl PyScanner<'_> {
    fn at(&self, i: usize) -> Option<char> {
        self.s.get(i).copied()
    }

    fn ws(&self, mut i: usize) -> usize {
        while matches!(self.at(i), Some(' ' | '\t' | '\n' | '\r')) {
            i += 1;
        }
        i
    }

    fn literal(&self, i: usize, word: &str) -> bool {
        word.chars().enumerate().all(|(k, c)| self.at(i + k) == Some(c))
    }

    fn value(&self, i: usize) -> ScanResult {
        let expecting = Err(("Expecting value", i));
        match self.at(i) {
            None => expecting,
            Some('"') => self.string(i + 1),
            Some('{') => self.object(i + 1),
            Some('[') => self.array(i + 1),
            Some('n') if self.literal(i, "null") => Ok(i + 4),
            Some('t') if self.literal(i, "true") => Ok(i + 4),
            Some('f') if self.literal(i, "false") => Ok(i + 5),
            Some('N') if self.literal(i, "NaN") => Ok(i + 3),
            Some('I') if self.literal(i, "Infinity") => Ok(i + 8),
            Some('-') if self.literal(i, "-Infinity") => Ok(i + 9),
            _ => self.number(i).map_or(expecting, Ok),
        }
    }

    fn number(&self, start: usize) -> Option<usize> {
        let digit = |i: usize| self.at(i).is_some_and(|c| c.is_ascii_digit());
        let mut i = start;
        if self.at(i) == Some('-') {
            i += 1;
        }
        match self.at(i) {
            Some('1'..='9') => {
                while digit(i) {
                    i += 1;
                }
            }
            Some('0') => i += 1,
            _ => return None,
        }
        if self.at(i) == Some('.') && digit(i + 1) {
            i += 1;
            while digit(i) {
                i += 1;
            }
        }
        if matches!(self.at(i), Some('e' | 'E')) {
            let mut j = i + 1;
            if matches!(self.at(j), Some('-' | '+')) {
                j += 1;
            }
            if digit(j) {
                while digit(j) {
                    j += 1;
                }
                i = j;
            }
        }
        Some(i)
    }

    fn string(&self, mut i: usize) -> ScanResult {
        let begin = i - 1;
        loop {
            match self.at(i) {
                None => return Err(("Unterminated string starting at", begin)),
                Some('"') => return Ok(i + 1),
                Some('\\') => {
                    let Some(c) = self.at(i + 1) else { return Err(("Unterminated string starting at", begin)) };
                    if c != 'u' {
                        if !"\"\\/bfnrt".contains(c) {
                            return Err(("Invalid \\escape", i));
                        }
                        i += 2;
                        continue;
                    }
                    let hex = |from: usize| -> Option<u32> {
                        (from..from + 4).try_fold(0, |acc, k| self.at(k)?.to_digit(16).map(|d| acc * 16 + d))
                    };
                    let u = i + 1;
                    if u + 5 >= self.s.len() {
                        return Err(("Invalid \\uXXXX escape", u));
                    }
                    let Some(code) = hex(u + 1) else { return Err(("Invalid \\uXXXX escape", u)) };
                    i = u + 5;
                    if (0xd800..0xdc00).contains(&code)
                        && i + 6 < self.s.len()
                        && self.at(i) == Some('\\')
                        && self.at(i + 1) == Some('u')
                    {
                        if hex(i + 2).is_none() {
                            return Err(("Invalid \\uXXXX escape", i + 1));
                        }
                        i += 6;
                    }
                }
                Some(c) if (c as u32) < 0x20 => return Err(("Invalid control character at", i)),
                Some(_) => i += 1,
            }
        }
    }

    fn object(&self, i: usize) -> ScanResult {
        let mut i = self.ws(i);
        if self.at(i) == Some('}') {
            return Ok(i + 1);
        }
        loop {
            if self.at(i) != Some('"') {
                return Err(("Expecting property name enclosed in double quotes", i));
            }
            i = self.ws(self.string(i + 1)?);
            if self.at(i) != Some(':') {
                return Err(("Expecting ':' delimiter", i));
            }
            i = self.ws(self.value(self.ws(i + 1))?);
            match self.at(i) {
                Some('}') => return Ok(i + 1),
                Some(',') => {}
                _ => return Err(("Expecting ',' delimiter", i)),
            }
            let comma = i;
            i = self.ws(i + 1);
            if self.at(i) == Some('}') {
                return Err(("Illegal trailing comma before end of object", comma));
            }
        }
    }

    fn array(&self, i: usize) -> ScanResult {
        let mut i = self.ws(i);
        if self.at(i) == Some(']') {
            return Ok(i + 1);
        }
        loop {
            i = self.ws(self.value(i)?);
            match self.at(i) {
                Some(']') => return Ok(i + 1),
                Some(',') => {}
                _ => return Err(("Expecting ',' delimiter", i)),
            }
            let comma = i;
            i = self.ws(i + 1);
            if self.at(i) == Some(']') {
                return Err(("Illegal trailing comma before end of array", comma));
            }
        }
    }
}

fn status_unfinished(result: &Json) -> bool {
    result.get("incomplete").is_some_and(truthy)
        || matches!(result.get("response_status").and_then(Json::as_str), Some("incomplete" | "failed" | "cancelled"))
}

/// The `try` body of `_run_citation` after the call: validate and merge into `local`.
fn interpret(result: &Json, at: i64, schema: &Json, local: &mut Json) -> std::result::Result<Option<f64>, String> {
    let cost = result_cost(result, at).map_err(|e| e.to_string())?;
    if status_unfinished(result) {
        return Err(UNFINISHED.into());
    }
    let data = py_json_loads(&clean_llm_json(result["text"].as_str().unwrap_or("")))?;
    if !schema_valid(&data, schema) || py_strip(data["summary"].as_str().unwrap_or("")).is_empty() {
        return Err(INVALID.into());
    }
    let mut first_by_norm: Map<String, Json> = Map::new();
    for (index, tc) in local["top_cited"].as_array().into_iter().flatten().enumerate() {
        first_by_norm.entry(norm_ref_id(&py_str(tc.get("ref_id")))).or_insert(json!(index));
    }
    for ra in data["ref_analyses"].as_array().into_iter().flatten() {
        let Some(index) = first_by_norm.get(&norm_ref_id(&text_of(ra.get("ref_id")))).and_then(Json::as_u64) else {
            continue;
        };
        let tc = &mut local["top_cited"][index as usize];
        for key in ["citation_role", "why_cited", "evidence_context"] {
            tc[key] = ra.get(key).cloned().unwrap_or(json!(""));
        }
    }
    local["summary"] = data.get("summary").cloned().unwrap_or(json!(""));
    local["citation_balance"] = data.get("citation_balance").cloned().unwrap_or(json!(""));
    local["key_influences"] = data.get("key_influences").cloned().unwrap_or(json!([]));
    local["citation_limitations"] = data.get("limitations").cloned().unwrap_or(json!(""));
    local["interpretation_status"] = json!("completed");
    Ok(Some(cost))
}

impl PhaseExecutor for CitationExecutor {
    fn run<'a>(
        &'a self,
        ctx: &'a RunContext,
        gateway: &'a dyn ProviderGateway,
        _input: &'a StageInput,
    ) -> BoxFuture<'a, Result<StageOutput>> {
        Box::pin(async move {
            let choice = choice(ctx, "citation")?;
            let mut local = analyze_citations(
                &self.citation_references,
                &self.citation_body,
                &self.sections,
                &self.paper_authors,
            );
            let top_refs = select_top_refs(&local);
            let mut ids = Vec::new();
            // (model_used, tokens_in, tokens_out, cost) as `phase_status` ends up holding them.
            let (model_used, tokens_in, tokens_out, cost) = if top_refs.is_empty() {
                local["summary"] = json!("");
                local["interpretation_status"] = json!("local_only");
                (Json::Null, json!(0), json!(0), Some(0.0))
            } else {
                let schema = legacy_schema("citation")?;
                let spec = NewRequestSpec {
                    provider: choice.provider,
                    model: choice.model.clone(),
                    input: ProviderInput {
                        parts: vec![InputPart::Text(citation_prompt(&local, &top_refs, &self.citation_body))],
                    },
                    instructions: None,
                    schema: Some(schema.clone()),
                    strict_schema: false,
                    effort: choice.effort.clone(),
                    previous_id: None,
                    store: false,
                    max_output_tokens: None,
                    service_tier: None,
                    source_identity: None,
                };
                let mut called = match call(gateway, spec, &mut ids).await {
                    Ok(pair) => Ok(pair),
                    Err(error @ SasooError::FenceLost(_)) => return Err(error),
                    // shortcut: Python stores str(exc) of the SDK exception; this is our error text.
                    Err(error) => Err(error.to_string()),
                };
                let outcome = match &mut called {
                    Ok((result, at)) => {
                        result["raw_text"] = result["text"].clone();
                        interpret(result, *at, &schema, &mut local)
                    }
                    Err(message) => Err(message.clone()),
                };
                match (outcome, called) {
                    (Ok(cost), Ok((result, _))) => (result["model"].clone(), result["tokens_in"].clone(), result["tokens_out"].clone(), cost),
                    (Err(message), called) => {
                        local["interpretation_status"] = json!("failed");
                        local["summary"] = json!(format!("LLM 분석 실패 ({message}). 로컬 파싱 결과만 제공됩니다."));
                        local["error"] = json!(format!("citation LLM 분석 실패: {message}"));
                        match called {
                            Ok((mut result, at)) => {
                                let usage: Map<String, Json> = ["tokens_in", "tokens_out", "usage_complete"]
                                    .iter()
                                    .map(|k| ((*k).to_owned(), result.get(*k).cloned().unwrap_or(Json::Null)))
                                    .collect();
                                local["_raw"] = result["raw_text"].clone();
                                local["_usage"] = Value::Object(usage);
                                let cost = result_cost_or_mark(&mut result, at);
                                (result["model"].clone(), result.get("tokens_in").cloned().unwrap_or(Json::Null), result.get("tokens_out").cloned().unwrap_or(Json::Null), cost)
                            }
                            Err(_) => (Json::Null, Json::Null, Json::Null, None),
                        }
                    }
                    (Ok(_), Err(_)) => unreachable!("an Ok interpretation needs a provider result"),
                }
            };
            let input_text = if top_refs.is_empty() {
                sorted_dumps(&json!({
                    "v": CITATION_PROMPT_VERSION,
                    "phase": "citation",
                    "citation_body": self.citation_body,
                    "citation_references": self.citation_references,
                    "paper_authors": self.paper_authors,
                }))?
            } else {
                citation_cache_key(&local, &self.citation_body)?
            };
            let model_used = if truthy(&model_used) { model_used } else { json!("local") };
            let stored = json!({
                "text": python_dumps(&local, false),
                "model": model_used,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            });
            let row = result_row("citation", &stored, cost, &input_text, &choice);
            Ok(stage_output(row, ids, None))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn norm_ref_id_matches_python_examples() {
        for (raw, want) in [("[52] Zhiqi Li et al. (2025)", "52"), ("ref 6", "6"), ("#007", "7"), ("(9)", "9"), (" Smith ", "smith"), ("", "")] {
            assert_eq!(norm_ref_id(raw), want, "{raw}");
        }
    }
}
