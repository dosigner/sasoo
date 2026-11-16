//! Read old extraction files without rebuilding or changing their provenance.
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
    time::UNIX_EPOCH,
};

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::{
    analysis::chat_retrieval::Document,
    error::{Result, SasooError},
};

const MAX_JSON_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Debug, Serialize)]
pub struct LegacyDocument {
    pub state: &'static str,
    pub reason: String,
    pub source_sha256: Option<String>,
    pub stored_source_sha256: Option<String>,
    pub source_identity: &'static str,
    pub parser_version: Option<String>,
    pub extraction_file: Option<String>,
    #[serde(skip)]
    pub document: Option<Document>,
}

pub(crate) fn contained_file(root: &Path, path: &Path) -> Result<PathBuf> {
    let path = path.canonicalize()?;
    if !path.starts_with(root.canonicalize()?) || !path.is_file() {
        return Err(SasooError::Forbidden(
            "File must remain inside its paper directory".into(),
        ));
    }
    Ok(path)
}

pub(crate) fn read_json(root: &Path, path: &Path) -> Result<Value> {
    let path = contained_file(root, path)?;
    let mut bytes = Vec::new();
    fs::File::open(path)?
        .take(MAX_JSON_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_JSON_BYTES {
        return Err(SasooError::InvalidInput(
            "Extraction JSON exceeds 64 MiB".into(),
        ));
    }
    serde_json::from_slice(&bytes)
        .map_err(|_| SasooError::InvalidInput("Invalid extraction JSON".into()))
}

pub fn load_legacy_document(paper_dir: &Path) -> Result<LegacyDocument> {
    let mut result = LegacyDocument {
        state: "missing",
        reason: "No source PDF or extraction file".into(),
        source_sha256: None,
        stored_source_sha256: None,
        source_identity: "unverified",
        parser_version: None,
        extraction_file: None,
        document: None,
    };
    if !paper_dir.is_dir() {
        return Ok(result);
    }
    let mut pdfs = fs::read_dir(paper_dir)?
        .map(|entry| entry.map(|e| e.path()))
        .collect::<std::io::Result<Vec<_>>>()?;
    pdfs.retain(|p| p.extension().is_some_and(|e| e == "pdf"));
    pdfs.sort();
    let Some(pdf) = pdfs.first() else {
        return Ok(result);
    };
    let pdf = contained_file(paper_dir, pdf)?;
    let mut file = fs::File::open(&pdf)?;
    let before = file.metadata()?;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let n = file.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        hash.update(&buffer[..n]);
    }
    let after = fs::metadata(&pdf)?;
    if before.len() != after.len() || before.modified()? != after.modified()? {
        result.state = "stale";
        result.reason = "Source PDF changed during observation".into();
        return Ok(result);
    }
    let observed_hash = format!("{:x}", hash.finalize());
    result.source_sha256 = Some(observed_hash.clone());
    let mtime = before
        .modified()?
        .duration_since(UNIX_EPOCH)
        .map_err(|_| {
            SasooError::InvalidInput("PDF modification time predates the Unix epoch".into())
        })?
        .as_nanos();
    let mut manifest = None;
    for name in [".odl_manifest.json", ".document_context.json"] {
        let path = paper_dir.join(name);
        if !path.exists() {
            continue;
        }
        let data = match read_json(paper_dir, &path) {
            Ok(data) => data,
            Err(SasooError::InvalidInput(_)) => {
                if result.document.is_none() {
                    result.state = "invalid";
                    result.reason = "Extraction JSON is invalid or too large".into();
                }
                continue;
            }
            Err(error) => return Err(error),
        };
        if name == ".odl_manifest.json" {
            manifest = Some(data.clone());
        }
        let signature = data.get("pdf_signature").unwrap_or(&data);
        let signature_matches = signature["pdf_size"].as_u64() == Some(before.len())
            && signature["pdf_mtime_ns"].as_u64().map(u128::from) == Some(mtime);
        if !signature_matches {
            if result.document.is_none() {
                result.state = "stale";
                result.reason = "PDF size or modification time differs".into();
            }
            continue;
        }
        let stored_hash = data
            .get("pdf_sha256")
            .or_else(|| signature.get("sha256"))
            .and_then(Value::as_str);
        if stored_hash.is_some_and(|hash| !hash.eq_ignore_ascii_case(&observed_hash)) {
            if result.document.is_none() {
                result.state = "stale";
                result.reason = "Stored PDF SHA-256 differs".into();
            }
            continue;
        }
        let version = data["parser_version"]
            .as_str()
            .filter(|v| !v.trim().is_empty() && *v != "unknown");
        let context_current = name != ".document_context.json"
            || (data["context_builder_version"] == "document-context-v4"
                && manifest
                    .as_ref()
                    .is_none_or(|m| m["parser_version"] == data["parser_version"]));
        let text = data["full_text"]
            .as_str()
            .filter(|text| !text.trim().is_empty());
        let (Some(version), Some(text)) = (version.filter(|_| context_current), text) else {
            if result.document.is_none() {
                result.state = "needs_reextraction";
                result.reason = "Extraction version or nonempty full_text is missing".into();
            }
            continue;
        };
        result.state = "usable";
        result.reason = if stored_hash.is_some() {
            "Stored source hash matched"
        } else {
            "Legacy size and modification time matched; historical source hash is absent"
        }
        .into();
        result.source_identity = if stored_hash.is_some() {
            "sha256_matched"
        } else {
            "metadata_matched"
        };
        result.stored_source_sha256 = stored_hash.map(str::to_owned);
        result.parser_version = Some(version.to_owned());
        result.extraction_file = Some(name.into());
        result.document = Some(Document {
            parser_version: version.into(),
            full_text: text.into(),
        });
    }
    Ok(result)
}
