use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::{
    error::{Result, SasooError},
    types::Hash256,
};

use super::types::{DocumentArtifact, PdfOptions};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LegacyHelperRequest {
    pub pdf_path: PathBuf,
    pub output_dir: PathBuf,
    pub options: PdfOptions,
    pub expected_sha256: Hash256,
}

/// Validate a helper receipt without granting it provider or publication access.
pub fn import_legacy_response(
    request: &LegacyHelperRequest,
    bytes: &[u8],
) -> Result<DocumentArtifact> {
    if !request.pdf_path.is_absolute() || !request.output_dir.is_absolute() {
        return Err(SasooError::InvalidInput(
            "Legacy helper paths must be absolute".into(),
        ));
    }
    let document: DocumentArtifact = serde_json::from_slice(bytes).map_err(|error| {
        SasooError::InvalidInput(format!("Invalid legacy helper response: {error}"))
    })?;
    if document.source_sha256 != request.expected_sha256 {
        return Err(SasooError::Conflict(
            "Legacy helper source SHA-256 differs from the requested source".into(),
        ));
    }
    if document.engine != request.options.engine {
        return Err(SasooError::Conflict(
            "Legacy helper engine differs from the explicitly selected engine".into(),
        ));
    }
    if document.extraction_options_sha256 != Some(request.options.options_hash) {
        return Err(SasooError::Conflict(
            "Legacy helper options identity is missing or differs from the requested options"
                .into(),
        ));
    }
    document.validate()?;
    Ok(document)
}
