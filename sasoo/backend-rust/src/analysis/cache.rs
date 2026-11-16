use crate::error::Result;
use serde::Deserialize;
use sha2::{Digest, Sha256};

pub const CHAIN_CACHE_VERSION: &str = "2026-08-06-ev1";
pub const CITATION_PROMPT_VERSION: &str = "2026-09-01";

#[derive(Debug, Clone, Deserialize)]
pub struct CacheInput {
    pub model: String,
    pub thinking: String,
    pub system_instruction: String,
    pub prompt: String,
    #[serde(default)]
    pub source_signature: String,
    pub max_output_tokens: Option<u64>,
}

pub fn phase_cache_key(input: &CacheInput) -> Result<Vec<u8>> {
    let cap = input
        .max_output_tokens
        .map_or_else(|| "None".to_owned(), |n| n.to_string());
    Ok([
        CHAIN_CACHE_VERSION,
        &input.model,
        &input.thinking,
        &input.system_instruction,
        &input.prompt,
        &input.source_signature,
        &cap,
    ]
    .join("\n\u{1f}\n")
    .into_bytes())
}

pub fn legacy_input_hash(
    text: &str,
    provider: Option<&str>,
    model: Option<&str>,
    effort: Option<&str>,
) -> String {
    let payload = if provider.is_none() && model.is_none() && effort.is_none() {
        text.to_owned()
    } else {
        [
            provider.unwrap_or("None"),
            model.unwrap_or("None"),
            effort.unwrap_or("None"),
            text,
        ]
        .join("\u{1f}")
    };
    format!("{:x}", Sha256::digest(payload.as_bytes()))[..16].to_owned()
}
