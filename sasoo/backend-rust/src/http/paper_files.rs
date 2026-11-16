//! Read prepared paper files without refreshing or opening a document engine.
use super::papers::PaperObservation;
use crate::{
    error::{Result, SasooError},
    storage::paths::RuntimePaths,
};
use regex::Regex;
use serde_json::{Map, Value};
use std::{
    fs,
    io::Read,
    path::{Component, Path, PathBuf},
    sync::OnceLock,
    time::UNIX_EPOCH,
};

pub(crate) fn isolated_paths(root: &Path) -> Result<RuntimePaths> {
    let root = super::papers::validate_isolated_root(root)?;
    let library = root.join("library").canonicalize()?;
    if !library.starts_with(&root) {
        return Err(SasooError::Forbidden(
            "Isolated library leaves its root".into(),
        ));
    }
    let db = root.join("sasoo.db").canonicalize()?;
    if db.parent() != Some(root.as_path()) {
        return Err(SasooError::Forbidden(
            "Isolated database leaves its root".into(),
        ));
    }
    for suffix in ["-wal", "-shm", "-journal"] {
        let mut sidecar = db.as_os_str().to_os_string();
        sidecar.push(suffix);
        if fs::symlink_metadata(PathBuf::from(sidecar)).is_ok() {
            return Err(SasooError::Unsupported("Read-only papers requires a prepared rollback-journal DB without sidecars; WAL and recovery are unsupported".into()));
        }
    }
    let mut header = [0u8; 100];
    fs::File::open(&db)?.read_exact(&mut header)?;
    if &header[..16] != b"SQLite format 3\0" || header[18] != 1 || header[19] != 1 {
        return Err(SasooError::Unsupported("Read-only papers accepts only a prepared rollback-journal SQLite database; committed WAL must not be ignored".into()));
    }
    Ok(RuntimePaths {
        app_data_root: root.clone(),
        db_path: db,
        config_path: root.join("config.json"),
        default_library_root: library.clone(),
        library_root: library.clone(),
        library_search_roots: vec![library],
        owner_lock_path: root.join("sasoo.db.runtime-owner.lock"),
    })
}
fn contained(root: &Path, path: &Path) -> Result<Option<PathBuf>> {
    let path = match path.canonicalize() {
        Ok(path) => path,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e.into()),
    };
    if !path.starts_with(root) {
        return Err(SasooError::Forbidden(
            "Paper artifact leaves the isolated library".into(),
        ));
    }
    Ok(Some(path))
}
fn read_json(root: &Path, path: &Path) -> Result<Option<Value>> {
    let Some(path) = contained(root, path)? else {
        return Ok(None);
    };
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(_) => return Ok(None),
    };
    let text = std::str::from_utf8(&bytes)
        .map_err(|_| SasooError::Internal("Saved JSON is not UTF-8".into()))?;
    Ok(serde_json::from_str::<Value>(text).ok())
}
fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(v) => !v.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
    }
}
fn exists(root: &Path, dir: &Path, value: Option<&Value>) -> Result<bool> {
    let Some(value) = value.filter(|v| truthy(v)) else {
        return Ok(false);
    };
    let Some(text) = value.as_str() else {
        return Err(SasooError::Internal(
            "Saved artifact path has an invalid shape".into(),
        ));
    };
    let path = Path::new(text);
    let path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        dir.join(path)
    };
    Ok(contained(root, &path)?.is_some())
}
fn contract_paths(root: &Path, dir: &Path, manifest: &Value) -> Result<bool> {
    for name in ["markdown_file", "json_file"] {
        if let Some(value) = manifest.get(name).filter(|v| truthy(v)) {
            let text = Value::String(python_path_text(value));
            if !exists(root, dir, Some(&text))? {
                return Ok(false);
            }
        }
    }
    Ok(true)
}
fn visual_paths(root: &Path, dir: &Path, manifest: &Value) -> Result<bool> {
    for (group, fields, required) in [
        ("figures", &["file_path"][..], true),
        ("tables", &["csv_path", "html_path"][..], false),
        ("pages", &["raster_path"][..], false),
    ] {
        let Some(items) = manifest.get(group) else {
            continue;
        };
        let Some(items) = items.as_array() else {
            return Err(SasooError::Internal(
                "Saved artifact list has an invalid shape".into(),
            ));
        };
        for item in items {
            if !item.is_object() {
                return Err(SasooError::Internal(
                    "Saved artifact entry has an invalid shape".into(),
                ));
            }
            for field in fields {
                if (required || item.get(*field).is_some_and(truthy))
                    && !exists(root, dir, item.get(*field))?
                {
                    return Ok(false);
                }
            }
        }
    }
    Ok(true)
}
fn current(manifest: &Value, mtime: u64, size: u64) -> bool {
    manifest["pdf_mtime_ns"].as_u64() == Some(mtime)
        && manifest["pdf_size"].as_u64() == Some(size)
        && manifest["requested_mode"] == "java"
        && manifest["parser_version"] == "odl-v3"
        && manifest
            .get("extraction_pipeline_version")
            .and_then(Value::as_str)
            .unwrap_or("resolver_v1")
            == "resolver_v1"
        && manifest
            .get("resolver_version")
            .and_then(Value::as_str)
            .unwrap_or("legacy")
            == "resolver-v1"
}
fn normalize(text: &str) -> String {
    text.split(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
fn title(raw: &str, fallback: &str) -> String {
    static PATTERNS: OnceLock<Vec<Regex>> = OnceLock::new();
    let patterns=PATTERNS.get_or_init(||[
        r"^\P{L}*$",r"(?i)^---\s*Page\s+\d+\s*---$",r"(?i)^page\s+\d+$",r"(?i)\barxiv:\s*\S+",r"(?i)^https?://\S+$",r"^\S+@\S+$",r"(?i)^.+\.pdf$",r"^(?:[A-Za-z-]+\.)+[A-Za-z-]+$",r"(?i)^(?:\d{1,2}\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s,.-]+\d{4}$"
    ].into_iter().map(|pattern|Regex::new(pattern).expect("Static title pattern")).collect());
    let raw = normalize(raw);
    let valid = raw.chars().count() >= 8 && !patterns.iter().any(|r| r.is_match(&raw));
    let result = if valid {
        raw
    } else {
        let mut value = normalize(fallback).replace('_', " ");
        if value.to_lowercase().ends_with(".pdf") {
            value.truncate(value.len() - 4);
            value = value.trim().to_owned();
        }
        if value.is_empty() {
            "Untitled Paper".into()
        } else {
            value
        }
    };
    result.chars().take(200).collect()
}
fn openalex(id: Option<i64>) -> Option<String> {
    static MAPPING: OnceLock<Value> = OnceLock::new();
    let map = MAPPING.get_or_init(|| {
        serde_json::from_str(include_str!(
            "../../../backend/agents/openalex_subfields.json"
        ))
        .expect("Bundled OpenAlex mapping")
    });
    id.and_then(|id| {
        map["subfields"][id.to_string()]["field"]
            .as_str()
            .map(str::to_owned)
    })
}
pub(crate) fn observe(root: &Path, row: &Map<String, Value>) -> Result<PaperObservation> {
    let folder = row
        .get("folder_name")
        .and_then(Value::as_str)
        .ok_or_else(|| SasooError::Incomplete("Paper folder is missing".into()))?;
    if folder.contains(['\\', '\0'])
        || Path::new(folder).is_absolute()
        || Path::new(folder)
            .components()
            .any(|p| !matches!(p, Component::Normal(_)))
    {
        return Err(SasooError::Forbidden(
            "Paper folder leaves the isolated library".into(),
        ));
    }
    let count = row
        .get("__visual_row_count")
        .and_then(Value::as_i64)
        .ok_or_else(|| {
            SasooError::Incomplete("Selected-page figure/table observations are missing".into())
        })?;
    if count < 0 {
        return Err(SasooError::Incomplete(
            "Observed figure/table count is invalid".into(),
        ));
    }
    let dir = root.join(folder);
    let dir = contained(root, &dir)?.unwrap_or(dir);
    let mut pdfs = if dir.is_dir() {
        fs::read_dir(&dir)?
            .map(|e| e.map(|e| e.path()))
            .collect::<std::io::Result<Vec<_>>>()?
    } else {
        vec![]
    };
    pdfs.retain(|p| p.extension().is_some_and(|v| v == "pdf"));
    pdfs.sort();
    let raw = row.get("title").and_then(Value::as_str).unwrap_or("");
    let fallback = pdfs
        .first()
        .and_then(|p| p.file_stem())
        .and_then(|v| v.to_str())
        .unwrap_or(if raw.is_empty() {
            "Untitled Paper"
        } else {
            raw
        });
    let mut result = PaperObservation {
        resolved_title: Some(title(raw, fallback)),
        text_ready: false,
        visual_ready: false,
        visual_state: "partial".into(),
        visual_error: None,
        openalex_field: openalex(row.get("openalex_subfield_id").and_then(Value::as_i64)),
    };
    let Some(pdf) = pdfs.first() else {
        result.visual_state = "error".into();
        result.visual_error = Some("PDF not found".into());
        return Ok(result);
    };
    let pdf = contained(root, pdf)?
        .ok_or_else(|| SasooError::NotFound("Source PDF disappeared during observation".into()))?;
    let meta = fs::metadata(pdf)?;
    let mtime = u64::try_from(
        meta.modified()?
            .duration_since(UNIX_EPOCH)
            .map_err(|_| {
                SasooError::InvalidInput(
                    "Source timestamp is outside this isolated contract".into(),
                )
            })?
            .as_nanos(),
    )
    .map_err(|_| {
        SasooError::InvalidInput("Source timestamp is outside this isolated contract".into())
    })?;
    let Some(manifest) = read_json(root, &dir.join(".odl_manifest.json"))?.filter(truthy) else {
        return Ok(result);
    };
    if !manifest.is_object() {
        return Err(SasooError::Internal(
            "Saved manifest has an invalid shape".into(),
        ));
    }
    let signature = current(&manifest, mtime, meta.len());
    let text = manifest
        .get("full_text")
        .is_some_and(|v| v.as_str().is_none_or(|s| !s.trim().is_empty()));
    let cache = if signature && text {
        if contained(root, &dir.join(".text_cache.txt"))?.is_none() {
            false
        } else {
            match read_json(root, &dir.join(".text_cache.meta.json"))? {
                None => false,
                Some(value) if value.is_object() => {
                    value["pdf_mtime_ns"].as_u64() == Some(mtime)
                        && value["pdf_size"].as_u64() == Some(meta.len())
                }
                Some(_) => {
                    return Err(SasooError::Internal(
                        "Saved text cache metadata has an invalid shape".into(),
                    ));
                }
            }
        }
    } else {
        false
    };
    result.text_ready = signature && text && cache && contract_paths(root, &dir, &manifest)?;
    result.visual_ready = signature
        && manifest.get("visual_artifacts_ready").is_none_or(truthy)
        && visual_paths(root, &dir, &manifest)?;
    if result.visual_ready {
        result.visual_state = "ready".into();
    }
    Ok(result)
}

// Legacy text-contract paths call Python str() before checking the file.
fn python_path_text(value: &Value) -> String {
    fn repr(value: &Value) -> String {
        match value {
            Value::String(text) => {
                let quote = if text.contains('\'') && !text.contains('"') {
                    '"'
                } else {
                    '\''
                };
                let mut out = String::from(quote);
                for c in text.chars() {
                    match c {
                        '\\' => out.push_str("\\\\"),
                        '\n' => out.push_str("\\n"),
                        '\r' => out.push_str("\\r"),
                        '\t' => out.push_str("\\t"),
                        c if c == quote => {
                            out.push('\\');
                            out.push(c);
                        }
                        c if c.is_control() => {
                            let n = c as u32;
                            out.push_str(&if n <= 255 {
                                format!("\\x{n:02x}")
                            } else {
                                format!("\\u{n:04x}")
                            });
                        }
                        c => out.push(c),
                    }
                }
                out.push(quote);
                out
            }
            Value::Array(items) => format!(
                "[{}]",
                items.iter().map(repr).collect::<Vec<_>>().join(", ")
            ),
            Value::Object(fields) => format!(
                "{{{}}}",
                fields
                    .iter()
                    .map(|(k, v)| format!("{}: {}", repr(&Value::String(k.clone())), repr(v)))
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            _ => python_path_text(value),
        }
    }
    match value {
        Value::String(text) => text.clone(),
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) if n.is_f64() => {
            let text = format!("{:?}", n.as_f64().unwrap());
            if let Some((base, exp)) = text.split_once('e') {
                let exp = exp.parse::<i32>().unwrap();
                format!("{base}e{exp:+03}")
            } else {
                text
            }
        }
        Value::Number(n) => n.to_string(),
        Value::Array(_) | Value::Object(_) => repr(value),
    }
}
