//! F03 Gemini Interactions API and Files upload over plain HTTP. Wire bytes match
//! `services/llm/gemini_client.py` (google-genai SDK) as recorded in
//! tests/fixtures/provider/wire-v1.json.
use crate::{
    analysis::prompts::system_instruction,
    error::{Result, SasooError},
    providers::{
        transport::{HttpRequest, Transport},
        types::{
            InputPart, NewRequestSpec, PdfPart, ProviderFileRef, ProviderOutcome, RequestSpec,
            check_chain, http_error_outcome, now_ms, outcome_from_result, single_text,
            transport_error_outcome,
        },
    },
    types::{Hash256, Json, ProviderId, UtcMillis},
};
use secrecy::{ExposeSecret, SecretString};
use serde_json::{Map, json};
use sha2::{Digest, Sha256};
use std::path::Path;

pub const INTERACTIONS_URL: &str = "https://generativelanguage.googleapis.com/v1beta/interactions";
pub const UPLOAD_URL: &str = "https://generativelanguage.googleapis.com/upload/v1beta/files";
/// Python caches an upload for 47 h; the server keeps files for 48 h.
pub const FILE_TTL_MS: i64 = 47 * 3600 * 1000;

pub fn build_request(spec: &NewRequestSpec, api_key: &str) -> Result<HttpRequest> {
    check_chain(spec)?;
    let mut body = Map::new();
    body.insert("model".into(), json!(spec.model));
    body.insert("input".into(), input(spec)?);
    body.insert(
        "system_instruction".into(),
        json!(spec.instructions.as_deref().unwrap_or(system_instruction())),
    );
    body.insert("store".into(), json!(spec.store));
    let mut generation = Map::new();
    if let Some(effort) = spec.effort.as_deref().filter(|e| !e.is_empty()) {
        generation.insert("thinking_level".into(), json!(effort));
    }
    if let Some(max) = spec.max_output_tokens {
        generation.insert("max_output_tokens".into(), json!(max));
    }
    if !generation.is_empty() {
        body.insert("generation_config".into(), Json::Object(generation));
    }
    if let Some(previous) = spec.previous_id.as_deref().filter(|p| !p.is_empty()) {
        body.insert("previous_interaction_id".into(), json!(previous));
    }
    if let Some(schema) = spec
        .schema
        .as_ref()
        .filter(|s| !(s.is_null() || s.as_object().is_some_and(Map::is_empty)))
    {
        body.insert(
            "response_format".into(),
            json!({"type": "text", "mime_type": "application/json", "schema": schema}),
        );
    }
    Ok(HttpRequest {
        method: "POST".into(),
        url: INTERACTIONS_URL.into(),
        headers: vec![
            ("content-type".into(), "application/json".into()),
            ("x-goog-api-key".into(), api_key.into()),
        ],
        body: serde_json::to_vec(&Json::Object(body))
            .map_err(|_| SasooError::InvalidInput("Gemini request cannot be encoded".into()))?,
    })
}

fn input(spec: &NewRequestSpec) -> Result<Json> {
    if let Some(text) = single_text(&spec.input) {
        return Ok(json!(text));
    }
    let mut content = Vec::new();
    for part in &spec.input.parts {
        match part {
            InputPart::Text(text) => content.push(json!({"type": "text", "text": text})),
            InputPart::Pdf(PdfPart::File(file)) => {
                if file.provider != ProviderId::Gemini {
                    return Err(SasooError::InvalidInput(
                        "A provider file reference cannot cross providers".into(),
                    ));
                }
                content.push(json!({"type": "document", "uri": file.uri, "mime_type": "application/pdf"}));
            }
            InputPart::Pdf(PdfPart::Inline { .. }) => {
                return Err(SasooError::InvalidInput(
                    "Gemini PDFs go through the Files API".into(),
                ));
            }
        }
    }
    // The SDK wraps a part list in one user_input step.
    Ok(json!([{"type": "user_input", "content": content}]))
}

/// Port of `_response_metadata` (call path, completed=False) plus the SDK `output_text`.
pub fn parse_response(model: &str, status: u16, body: &[u8], received_at: UtcMillis) -> ProviderOutcome {
    if !(200..300).contains(&status) {
        return http_error_outcome(status, body, received_at);
    }
    let Ok(interaction) = serde_json::from_slice::<Json>(body) else {
        return transport_error_outcome("Gemini response is not JSON", received_at);
    };
    let field = |v: &Json, k: &str| v.get(k).cloned().unwrap_or(Json::Null);
    let usage = field(&interaction, "usage");
    let tokens_in = field(&usage, "total_input_tokens");
    let output = usage.get("total_output_tokens").and_then(Json::as_u64);
    let thought = field(&usage, "total_thought_tokens");
    let tokens_out = match (output, thought.as_u64()) {
        (Some(o), Some(t)) => json!(o + t),
        _ => Json::Null,
    };
    let usage_complete = !tokens_in.is_null() && !tokens_out.is_null();
    let status_value = match interaction.get("status").and_then(Json::as_str) {
        Some(s) if !s.is_empty() => json!(s),
        _ => Json::Null,
    };
    let incomplete = !usage_complete
        || matches!(status_value.as_str(), Some("incomplete" | "failed" | "cancelled"));
    let result = json!({
        "text": output_text(&interaction),
        "model": model,
        "response_status": status_value,
        "incomplete": incomplete,
        "incomplete_reason": if usage_complete { Json::Null } else { json!("missing_usage") },
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_thought": thought,
        "interaction_id": field(&interaction, "id"),
        "usage_complete": usage_complete,
    });
    outcome_from_result(result, body, received_at)
}

/// SDK `_populate_output_helpers`: the last consecutive run of text in the trailing
/// model_output steps; stops at user_input or any other step once collecting.
fn output_text(interaction: &Json) -> String {
    let mut parts: Vec<&str> = Vec::new();
    let mut collecting = false;
    let steps = interaction.get("steps").and_then(Json::as_array);
    'steps: for step in steps.into_iter().flatten().rev() {
        match step.get("type").and_then(Json::as_str) {
            Some("user_input") => break,
            Some("model_output") => {}
            _ => {
                if collecting {
                    break;
                }
                continue;
            }
        }
        let Some(content) = step.get("content").and_then(Json::as_array) else {
            if collecting {
                break;
            }
            continue;
        };
        for item in content.iter().rev() {
            if item.get("type").and_then(Json::as_str) == Some("text") {
                collecting = true;
                parts.push(item.get("text").and_then(Json::as_str).unwrap_or(""));
            } else if collecting {
                break 'steps;
            }
        }
    }
    parts.reverse();
    parts.concat()
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

/// Resumable upload as the SDK sends it for an open file object. The display name
/// travels in the JSON body, never in a header, so non-ASCII file names are safe.
pub async fn upload_pdf(
    path: &Path,
    source_sha256: &Hash256,
    transport: &dyn Transport,
    api_key: &SecretString,
) -> Result<ProviderFileRef> {
    let data = std::fs::read(path)?;
    if Sha256::digest(&data).as_slice() != source_sha256.as_slice() {
        return Err(SasooError::Conflict("PDF bytes differ from the source identity".into()));
    }
    let name = path
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| SasooError::InvalidInput("PDF filename is missing".into()))?;
    let size = data.len().to_string();
    let common = |command: &str| {
        vec![
            ("content-type".to_owned(), "application/json".to_owned()),
            ("x-goog-upload-protocol".to_owned(), "resumable".to_owned()),
            ("x-goog-upload-command".to_owned(), command.to_owned()),
            ("x-goog-upload-header-content-length".to_owned(), size.clone()),
            ("x-goog-upload-header-content-type".to_owned(), "application/pdf".to_owned()),
        ]
    };
    let mut start_headers = common("start");
    start_headers.push(("x-goog-api-key".into(), api_key.expose_secret().to_owned()));
    let start = transport
        .send(HttpRequest {
            method: "POST".into(),
            url: UPLOAD_URL.into(),
            headers: start_headers,
            body: serde_json::to_vec(&json!({"file": {
                "display_name": name, "mime_type": "application/pdf", "size_bytes": data.len(),
            }}))
            .map_err(|_| SasooError::InvalidInput("Upload metadata cannot be encoded".into()))?,
        })
        .await?;
    let upload_url = header(&start.headers, "x-goog-upload-url")
        .filter(|_| (200..300).contains(&start.status))
        .ok_or_else(|| SasooError::Incomplete(format!("Gemini upload start failed: HTTP {}", start.status)))?;
    if !upload_url.starts_with(UPLOAD_URL) {
        return Err(SasooError::Forbidden("Gemini upload URL leaves the upload endpoint".into()));
    }
    let mut finish_headers = common("upload, finalize");
    finish_headers.push(("x-goog-upload-offset".into(), "0".into()));
    let finish = transport
        .send(HttpRequest {
            method: "POST".into(),
            url: upload_url,
            headers: finish_headers,
            body: data,
        })
        .await?;
    let uri = serde_json::from_slice::<Json>(&finish.body)
        .ok()
        .filter(|_| (200..300).contains(&finish.status))
        .and_then(|v| v.get("file")?.get("uri")?.as_str().map(str::to_owned))
        .ok_or_else(|| SasooError::Incomplete(format!("Gemini upload failed: HTTP {}", finish.status)))?;
    Ok(ProviderFileRef {
        provider: ProviderId::Gemini,
        uri,
        expires_at: Some(now_ms() + FILE_TTL_MS),
        source_sha256: *source_sha256,
    })
}

fn header(headers: &[(String, String)], name: &str) -> Option<String> {
    headers
        .iter()
        .find(|(k, _)| k.eq_ignore_ascii_case(name))
        .map(|(_, v)| v.clone())
}
