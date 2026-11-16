//! Immutable, private extraction versions. Only the owner catalog publishes references.
use super::{BlockContent, DocumentArtifact, PdfOptions};
use crate::error::{Result, SasooError};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Component, Path, PathBuf},
};

pub const MAX_PDF_BYTES: usize = 100 * 1024 * 1024;
pub fn valid_pdf_header(bytes: &[u8]) -> bool {
    bytes[..bytes.len().min(1024)]
        .windows(5)
        .any(|w| w == b"%PDF-")
}
const MAX_ARTIFACT_BYTES: u64 = 128 * 1024 * 1024;

pub fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub(crate) fn read_bounded(path: &Path, limit: u64) -> Result<Vec<u8>> {
    if path.symlink_metadata()?.file_type().is_symlink() {
        return Err(SasooError::Forbidden(
            "Symlink artifact is not permitted".into(),
        ));
    }
    let file = File::open(path)?;
    if !file.metadata()?.is_file() || file.metadata()?.len() > limit {
        return Err(SasooError::InvalidInput(
            "Artifact exceeds the regular-file limit".into(),
        ));
    }
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(SasooError::InvalidInput(
            "Artifact grew beyond its limit".into(),
        ));
    }
    Ok(bytes)
}

pub(crate) fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    #[cfg(test)]
    if FAULT.with(|f| {
        f.get()
            .is_some_and(|name| path.file_name().is_some_and(|p| p == name))
    }) {
        file.write_all(&bytes[..bytes.len() / 2])?;
        return Err(SasooError::Incomplete(
            "Synthetic partial file write".into(),
        ));
    }
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

pub(crate) fn contained(root: &Path, path: &Path) -> Result<PathBuf> {
    let path = path.canonicalize()?;
    if !path.starts_with(root) {
        return Err(SasooError::Forbidden(
            "PDF path leaves its isolated root".into(),
        ));
    }
    Ok(path)
}

pub(crate) fn component(value: &str) -> Result<()> {
    if value.contains(['\\', ':', '\0'])
        || value.starts_with('.')
        || Path::new(value).components().count() != 1
        || !matches!(
            Path::new(value).components().next(),
            Some(Component::Normal(_))
        )
    {
        return Err(SasooError::Forbidden(
            "Invalid PDF catalog path component".into(),
        ));
    }
    Ok(())
}

pub fn page_text(document: &DocumentArtifact) -> Vec<String> {
    let mut pages = vec![String::new(); document.pages.len()];
    for block in &document.blocks {
        if let BlockContent::Text { text } = &block.content {
            let page = &mut pages[block.page_index0 as usize];
            if !page.is_empty() {
                page.push('\n');
            }
            page.push_str(text);
        }
    }
    pages
}

pub fn full_text(pages: &[String]) -> String {
    pages
        .iter()
        .enumerate()
        .map(|(i, t)| format!("--- Page {} ---\n\n{t}", i + 1))
        .collect::<Vec<_>>()
        .join("\n\n")
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VersionReceipt {
    pub version: String,
    pub source_sha256: String,
    pub document_sha256: String,
    pub options: PdfOptions,
    pub settings_bytes: String,
    pub text_state: String,
    pub pages_with_text: usize,
    pub physical_pages: usize,
    pub visual_ready: bool,
    pub analysis_state: String,
    pub metadata_state: String,
    pub page_evidence: String,
}

pub(crate) fn save_version(
    dir: &Path,
    version: &str,
    document: &DocumentArtifact,
    options: &PdfOptions,
    settings: &str,
) -> Result<VersionReceipt> {
    document.validate()?;
    fs::create_dir(dir)?;
    let bytes = serde_json::to_vec(document).map_err(|e| SasooError::Internal(e.to_string()))?;
    let pages = page_text(document);
    let count = pages.iter().filter(|p| !p.trim().is_empty()).count();
    let receipt = VersionReceipt {
        version: version.into(),
        source_sha256: document
            .source_sha256
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect(),
        document_sha256: hash(&bytes),
        options: options.clone(),
        settings_bytes: settings.into(),
        text_state: if count == 0 {
            "no_native_text"
        } else if count < pages.len() {
            "partial_native_text"
        } else {
            "native_text_extracted_unverified"
        }
        .into(),
        pages_with_text: count,
        physical_pages: pages.len(),
        visual_ready: false,
        analysis_state: "not_run".into(),
        metadata_state: "filename_stub_unverified".into(),
        page_evidence: "page_unverified".into(),
    };
    write_new(&dir.join("document.json"), &bytes)?;
    write_new(
        &dir.join("receipt.json"),
        &serde_json::to_vec(&receipt).map_err(|e| SasooError::Internal(e.to_string()))?,
    )?;
    File::open(dir)?.sync_all()?;
    Ok(receipt)
}

pub(crate) fn load_version(
    dir: &Path,
    expected_document_hash: &str,
) -> Result<(VersionReceipt, DocumentArtifact)> {
    let receipt: VersionReceipt =
        serde_json::from_slice(&read_bounded(&dir.join("receipt.json"), 65536)?)
            .map_err(|_| SasooError::Incomplete("Invalid PDF receipt".into()))?;
    let bytes = read_bounded(&dir.join("document.json"), MAX_ARTIFACT_BYTES)?;
    if hash(&bytes) != expected_document_hash || receipt.document_sha256 != expected_document_hash {
        return Err(SasooError::Conflict(
            "Saved PDF artifact hash differs".into(),
        ));
    }
    let document: DocumentArtifact = serde_json::from_slice(&bytes)
        .map_err(|_| SasooError::Incomplete("Invalid PDF artifact".into()))?;
    document.validate()?;
    let pages = page_text(&document);
    let count = pages.iter().filter(|p| !p.trim().is_empty()).count();
    let state = if count == 0 {
        "no_native_text"
    } else if count < pages.len() {
        "partial_native_text"
    } else {
        "native_text_extracted_unverified"
    };
    if receipt.physical_pages != pages.len()
        || receipt.pages_with_text != count
        || receipt.text_state != state
        || receipt.visual_ready
        || receipt.analysis_state != "not_run"
        || receipt.metadata_state != "filename_stub_unverified"
        || receipt.page_evidence != "page_unverified"
    {
        return Err(SasooError::Conflict(
            "PDF readiness receipt differs from the saved text evidence".into(),
        ));
    }
    if receipt.source_sha256
        != document
            .source_sha256
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>()
        || document.engine != receipt.options.engine
        || document.extraction_options_sha256 != Some(receipt.options.options_hash)
        || <[u8; 32]>::from(Sha256::digest(receipt.settings_bytes.as_bytes()))
            != receipt.options.options_hash
    {
        return Err(SasooError::Conflict(
            "PDF receipt identity differs from its artifact".into(),
        ));
    }
    Ok((receipt, document))
}

#[cfg(test)]
thread_local! {pub(crate) static FAULT: std::cell::Cell<Option<&'static str>> = const { std::cell::Cell::new(None) };}
#[cfg(test)]
pub(crate) fn checkpoint(name: &str) -> Result<()> {
    if FAULT.with(|f| f.get() == Some(name)) {
        return Err(SasooError::Incomplete(format!("Synthetic fault: {name}")));
    }
    Ok(())
}
