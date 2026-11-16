//! F02 OpenAI Responses API over plain HTTP. Wire bytes match
//! `services/llm/openai_client.py` as recorded in tests/fixtures/provider/wire-v1.json.
use crate::{
    analysis::prompts::system_instruction,
    error::{Result, SasooError},
    providers::{
        transport::{HttpRequest, Transport},
        types::{
            InputPart, NewRequestSpec, PdfPart, ProviderOutcome, RequestSpec, check_chain,
            http_error_outcome, now_ms, outcome_from_result, single_text, transport_error_outcome,
        },
    },
    types::{Json, UtcMillis},
};
use base64::{Engine, engine::general_purpose::STANDARD as B64};
use secrecy::{ExposeSecret, SecretString};
use serde_json::{Map, json};
use sha2::{Digest, Sha256};

pub const RESPONSES_URL: &str = "https://api.openai.com/v1/responses";
const MAX_PDF_BYTES: u64 = 50_000_000;

pub fn build_request(spec: &NewRequestSpec, api_key: &str) -> Result<HttpRequest> {
    check_chain(spec)?;
    let mut body = Map::new();
    body.insert("model".into(), json!(spec.model));
    body.insert("input".into(), input(spec)?);
    body.insert(
        "instructions".into(),
        json!(spec.instructions.as_deref().unwrap_or(system_instruction())),
    );
    if let Some(effort) = spec.effort.as_deref().filter(|e| !e.is_empty()) {
        body.insert("reasoning".into(), json!({"effort": effort}));
    }
    if let Some(previous) = spec.previous_id.as_deref().filter(|p| !p.is_empty()) {
        body.insert("previous_response_id".into(), json!(previous));
    }
    if let Some(schema) = spec.schema.as_ref().filter(|s| !is_empty_schema(s)) {
        let mut wire = schema.clone();
        if spec.strict_schema {
            close_objects(&mut wire);
        }
        body.insert(
            "text".into(),
            json!({"format": {"type": "json_schema", "name": "sasoo_result", "schema": wire, "strict": spec.strict_schema}}),
        );
    }
    body.insert("store".into(), json!(spec.store));
    if let Some(max) = spec.max_output_tokens {
        body.insert("max_output_tokens".into(), json!(max));
    }
    if let Some(tier) = &spec.service_tier {
        body.insert("service_tier".into(), json!(tier));
    }
    Ok(HttpRequest {
        method: "POST".into(),
        url: RESPONSES_URL.into(),
        headers: vec![
            ("authorization".into(), format!("Bearer {api_key}")),
            ("content-type".into(), "application/json".into()),
        ],
        body: serde_json::to_vec(&Json::Object(body))
            .map_err(|_| SasooError::InvalidInput("OpenAI request cannot be encoded".into()))?,
    })
}

/// Python treats `{}` and None alike (`if response_schema:`).
fn is_empty_schema(schema: &Json) -> bool {
    schema.is_null() || schema.as_object().is_some_and(Map::is_empty)
}

/// Same walk as `_build_request`: every object node closes and requires all its properties.
fn close_objects(schema: &mut Json) {
    let mut pending: Vec<&mut Json> = vec![schema];
    while let Some(node) = pending.pop() {
        let Some(obj) = node.as_object_mut() else { continue };
        let names: Vec<Json> = obj
            .get("properties")
            .and_then(Json::as_object)
            .map(|p| p.keys().map(|k| json!(k)).collect())
            .unwrap_or_default();
        if obj.get("type").and_then(Json::as_str) == Some("object") {
            obj.insert("additionalProperties".into(), json!(false));
            obj.insert("required".into(), Json::Array(names));
        }
        // Collect children after the inserts so the borrows do not overlap.
        let mut children: Vec<&mut Json> = Vec::new();
        for (key, value) in obj.iter_mut() {
            match key.as_str() {
                "properties" => {
                    if let Some(props) = value.as_object_mut() {
                        children.extend(props.values_mut());
                    }
                }
                "items" => children.push(value),
                _ => {}
            }
        }
        pending.extend(children);
    }
}

fn input(spec: &NewRequestSpec) -> Result<Json> {
    if let Some(text) = single_text(&spec.input) {
        return Ok(json!(text));
    }
    let mut content = Vec::new();
    for part in &spec.input.parts {
        match part {
            InputPart::Text(text) => content.push(json!({"type": "input_text", "text": text})),
            InputPart::Pdf(PdfPart::Inline { source_sha256, path }) => {
                let size = std::fs::metadata(path)?.len();
                if size == 0 || size >= MAX_PDF_BYTES {
                    return Err(SasooError::InvalidInput(format!(
                        "PDF size must be between 1 and 49,999,999 bytes: {size}"
                    )));
                }
                let data = std::fs::read(path)?;
                if !data.starts_with(b"%PDF-") {
                    return Err(SasooError::InvalidInput("Invalid PDF input".into()));
                }
                if Sha256::digest(&data).as_slice() != source_sha256.as_slice() {
                    return Err(SasooError::Conflict("PDF bytes differ from the source identity".into()));
                }
                let filename = path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .ok_or_else(|| SasooError::InvalidInput("PDF filename is missing".into()))?;
                content.push(json!({
                    "type": "input_file",
                    "filename": filename,
                    "file_data": format!("data:application/pdf;base64,{}", B64.encode(&data)),
                    "detail": "high",
                }));
            }
            InputPart::Pdf(PdfPart::File(_)) => {
                return Err(SasooError::InvalidInput(
                    "OpenAI requires an inline PDF document".into(),
                ));
            }
        }
    }
    Ok(json!([{"role": "user", "content": content}]))
}

/// Port of `_response_metadata` plus the SDK `output_text` property.
pub fn parse_response(model: &str, status: u16, body: &[u8], received_at: UtcMillis) -> ProviderOutcome {
    if !(200..300).contains(&status) {
        return http_error_outcome(status, body, received_at);
    }
    let Ok(response) = serde_json::from_slice::<Json>(body) else {
        return transport_error_outcome("OpenAI response is not JSON", received_at);
    };
    let field = |v: &Json, k: &str| v.get(k).cloned().unwrap_or(Json::Null);
    let usage = field(&response, "usage");
    let input_details = field(&usage, "input_tokens_details");
    let output_details = field(&usage, "output_tokens_details");
    let tokens_in = field(&usage, "input_tokens");
    let tokens_out = field(&usage, "output_tokens");
    let status_value = field(&response, "status");
    let incomplete = matches!(status_value.as_str(), Some("incomplete" | "failed" | "cancelled"));
    let result = json!({
        "text": output_text(&response),
        "model": model,
        "response_model": field(&response, "model"),
        "response_status": status_value,
        "incomplete": incomplete,
        "incomplete_reason": field(&field(&response, "incomplete_details"), "reason"),
        "service_tier": field(&response, "service_tier"),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_thought": field(&output_details, "reasoning_tokens"),
        "tokens_cached": field(&input_details, "cached_tokens"),
        "tokens_cache_write": field(&input_details, "cache_write_tokens"),
        "interaction_id": field(&response, "id"),
        "usage_complete": !tokens_in.is_null() && !tokens_out.is_null(),
    });
    outcome_from_result(result, body, received_at)
}

fn output_text(response: &Json) -> String {
    let mut text = String::new();
    for item in response.get("output").and_then(Json::as_array).into_iter().flatten() {
        if item.get("type").and_then(Json::as_str) != Some("message") {
            continue;
        }
        for content in item.get("content").and_then(Json::as_array).into_iter().flatten() {
            if content.get("type").and_then(Json::as_str) == Some("output_text") {
                text.push_str(content.get("text").and_then(Json::as_str).unwrap_or(""));
            }
        }
    }
    text
}

/// One HTTP attempt. Retries belong to the gateway so each attempt gets its own ledger ID.
pub async fn generate(
    spec: &RequestSpec,
    transport: &dyn Transport,
    api_key: &SecretString,
) -> Result<ProviderOutcome> {
    let request = build_request(&spec.new, api_key.expose_secret())?;
    Ok(match transport.send(request).await {
        Ok(response) => parse_response(&spec.new.model, response.status, &response.body, now_ms()),
        Err(error) => transport_error_outcome(&error.to_string(), now_ms()),
    })
}
