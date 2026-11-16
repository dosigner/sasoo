use crate::error::{Result, SasooError};
use serde_json::Value;

// C02 preserves source schemas before any provider strict-format conversion.
pub fn legacy_schema(stage: &str) -> Result<Value> {
    let catalog: Value = serde_json::from_str(include_str!(
        "../../../contract-fixtures/rust-backend-v2/schemas.json"
    ))
    .map_err(|_| SasooError::Internal("Pinned schema catalog is invalid".into()))?;
    catalog["cases"]
        .as_array()
        .and_then(|cases| cases.iter().find(|case| case["id"] == stage))
        .and_then(|case| case.get("expected"))
        .cloned()
        .ok_or_else(|| SasooError::NotFound("Unknown legacy schema".into()))
}
