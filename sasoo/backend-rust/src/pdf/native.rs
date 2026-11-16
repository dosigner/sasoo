//! Explicit text-layer probe. This profile is not an adopted production engine.
use std::{fs::File, io::Read, sync::Mutex};

use sha2::{Digest, Sha256};
use tokio_util::sync::CancellationToken;
use xberg_native_pdf::{PdfDocument, converters::ConversionOptions, object::Object};

use super::types::*;
use crate::error::{Result, SasooError};

static EXTRACTION_SLOT: Mutex<()> = Mutex::new(());
const MAX_INPUT_BYTES: u64 = 100 * 1024 * 1024;
const MAX_PAGES: usize = 10_000;
const MAX_TEXT_BYTES: usize = 64 * 1024 * 1024;
pub const NATIVE_SETTINGS: &str = r#"{
  "adapter": "sasoo-xberg-native-text-v2",
  "local_patch_sha256": "09da20aff894ce3abef256f76db48d953f4d21007c43b4d2b978155b2f7eaeac",
  "parser": "PdfDocument::from_bytes, pinned 1.3.10 defaults",
  "conversion": {"extract_tables": false, "assembly": "glyph-walk with stacked single-span line guard", "other_options": "pinned 1.3.10 defaults"},
  "ocr": false,
  "max_input_bytes": 104857600,
  "header": "%PDF- within first 1024 bytes; source bytes unchanged",
  "max_pages": 10000,
  "max_text_bytes": 67108864,
  "bbox": "unavailable",
  "geometry": "unrotated PDF user space, UserUnit separate"
}"#;

pub fn native_options() -> PdfOptions {
    PdfOptions {
        engine: EngineIdentity {
            name: "xberg-native-pdf".into(),
            version: "1.3.10".into(),
            // crates.io's source revision differs from the historical proposal's tag.
            revision: Some("2b2d4186e7b0db959c15150008564ee41aa73d62".into()),
            resource_manifest_sha256: None,
        },
        profile: "text-layer-v2".into(),
        options_hash: Sha256::digest(NATIVE_SETTINGS.as_bytes()).into(),
    }
}

pub(super) fn extract(
    input: &PdfInput,
    options: &PdfOptions,
    cancel: &CancellationToken,
) -> Result<DocumentArtifact> {
    if options != &native_options() {
        return Err(SasooError::Conflict(
            "Native PDF engine, revision, profile and options must match native_options()".into(),
        ));
    }
    if std::env::var_os("XBERG_NATIVE_PDF_MAX_DECOMPRESS_MB").is_some() {
        return Err(SasooError::Unsupported(
            "Unset XBERG_NATIVE_PDF_MAX_DECOMPRESS_MB for the fixed text-layer-v2 profile".into(),
        ));
    }
    // Keep the slot until the synchronous producer returns, including after cancellation.
    let _slot = EXTRACTION_SLOT
        .lock()
        .map_err(|_| SasooError::Internal("Native PDF extraction slot was poisoned".into()))?;
    check_cancel(cancel)?;
    let file = File::open(&input.path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > MAX_INPUT_BYTES {
        return Err(invalid(
            "Native PDF input must be a regular file of at most 100 MiB",
        ));
    }
    let mut bytes = Vec::new();
    file.take(MAX_INPUT_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_INPUT_BYTES || !super::artifacts::valid_pdf_header(&bytes) {
        return Err(invalid(
            "Native PDF input exceeds 100 MiB or has no PDF header",
        ));
    }
    if <[u8; 32]>::from(Sha256::digest(&bytes)) != input.source_sha256 {
        return Err(SasooError::Conflict(
            "PDF source SHA-256 differs from the requested source".into(),
        ));
    }
    check_cancel(cancel)?;
    // Parse exactly the bytes that were hashed; do not reopen the mutable source path.
    let pdf = PdfDocument::from_bytes(bytes).map_err(engine_error)?;
    check_cancel(cancel)?;
    if pdf.is_encrypted() {
        return Err(SasooError::Unsupported(
            "Encrypted PDFs are not supported by text-layer-v2".into(),
        ));
    }
    let count = pdf.page_count().map_err(engine_error)?;
    if count == 0 || count > MAX_PAGES {
        return Err(invalid(
            "Native PDF input requires between 1 and 10000 physical pages",
        ));
    }
    let mut artifact = DocumentArtifact {
        source_sha256: input.source_sha256,
        engine: options.engine.clone(),
        extraction_options_sha256: Some(options.options_hash),
        pages: Vec::with_capacity(count),
        blocks: Vec::new(),
        assets: Vec::new(),
        warnings: vec![
            warning(
                "unverified_reading_order",
                "Pinned text assembly uses heuristic reading order; source reading order has not been independently verified.",
                None,
            ),
            warning(
                "text_only_profile",
                "No verified block boxes, structured tables, equation LaTeX, figure assets or OCR are produced by this profile.",
                None,
            ),
        ],
    };
    // shortcut: this profile returns only page text, add layout evidence after the PDF quality gate.
    let conversion = ConversionOptions {
        extract_tables: false,
        ..Default::default()
    };
    let mut total_text_bytes = 0;
    for index in 0..count {
        check_cancel(cancel)?;
        let page_index0 = index as u32;
        let object = pdf.get_page(index).map_err(engine_error)?;
        let dict = object
            .as_dict()
            .ok_or_else(|| invalid("PDF page is not a dictionary"))?;
        let resolve = |key: &str| -> Result<Option<Object>> {
            dict.get(key)
                .map(|value| pdf.resolve_references(value, 16).map_err(engine_error))
                .transpose()
        };
        let media_box = rectangle(resolve("MediaBox")?.as_ref())?;
        let crop_box = match resolve("CropBox")? {
            Some(value) => rectangle(Some(&value))?,
            None => media_box,
        };
        let rotation = match resolve("Rotate")? {
            Some(Object::Integer(value)) if value % 90 == 0 => value.rem_euclid(360) as u16,
            None => 0,
            _ => {
                return Err(invalid(
                    "PDF Rotate must be an integer multiple of 90 degrees",
                ));
            }
        };
        let user_unit = resolve("UserUnit")?
            .as_ref()
            .map(number)
            .transpose()?
            .unwrap_or(1.0);
        let page = Page {
            page_index0,
            page_number1: page_index0 + 1,
            media_box,
            crop_box,
            rotation_deg: rotation,
            user_unit,
            source_space: CoordinateSpace::PdfUserSpace,
            engine_to_pdf_user_space: None,
        };
        page.geometry().validate()?;
        let text = pdf
            .extract_text_with_options(index, &conversion)
            .map_err(|error| {
                SasooError::Incomplete(format!(
                    "Native text extraction failed on physical page {}: {error}",
                    index + 1
                ))
            })?;
        check_cancel(cancel)?;
        total_text_bytes += text.len();
        if total_text_bytes > MAX_TEXT_BYTES {
            return Err(invalid("Native PDF text exceeds the 64 MiB profile limit"));
        }
        if text.trim().is_empty() {
            artifact.warnings.push(warning("no_text_layer", "No native text was returned. This page may be blank, scanned or unsupported; OCR was not run.", Some(page_index0)));
        } else {
            artifact.blocks.push(Block {
                native_id: format!("page-{page_index0}-text"),
                page_index0,
                reading_order: Some(0),
                source_bbox: None,
                bbox: None,
                content: BlockContent::Text { text },
                provenance: Provenance {
                    source_kind: "native_pdf_text_layer".into(),
                    source_native_id: None,
                    engine_revision: options.engine.revision.clone(),
                    ocr: Some(false),
                    confidence: None,
                },
            });
        }
        artifact.pages.push(page);
        for message in pdf.take_warnings() {
            artifact
                .warnings
                .push(warning("engine_warning", &message, None));
        }
    }
    check_cancel(cancel)?;
    artifact.validate()?;
    Ok(artifact)
}

fn number(value: &Object) -> Result<f64> {
    let n = match value {
        Object::Integer(value) => *value as f64,
        Object::Real(value) => *value,
        _ => return Err(invalid("PDF geometry requires numeric values")),
    };
    if !n.is_finite() {
        return Err(invalid("PDF geometry requires finite values"));
    }
    Ok(n)
}

fn rectangle(value: Option<&Object>) -> Result<[f64; 4]> {
    let values = value
        .and_then(Object::as_array)
        .filter(|a| a.len() == 4)
        .ok_or_else(|| invalid("PDF page boxes require exactly four numeric coordinates"))?;
    Ok([
        number(&values[0])?,
        number(&values[1])?,
        number(&values[2])?,
        number(&values[3])?,
    ])
}

fn warning(code: &str, message: &str, page_index0: Option<u32>) -> ExtractionWarning {
    ExtractionWarning {
        code: code.into(),
        message: message.into(),
        page_index0,
    }
}

fn check_cancel(cancel: &CancellationToken) -> Result<()> {
    if cancel.is_cancelled() {
        Err(SasooError::Incomplete(
            "Native PDF extraction was cancelled; no artifact was returned".into(),
        ))
    } else {
        Ok(())
    }
}

fn invalid(message: &str) -> SasooError {
    SasooError::InvalidInput(message.into())
}

fn engine_error(error: xberg_native_pdf::Error) -> SasooError {
    invalid(&format!("Native PDF parser failed: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cancelled_waiter_does_not_open_a_source() {
        let slot = EXTRACTION_SLOT.lock().unwrap();
        let cancel = CancellationToken::new();
        let waiting_cancel = cancel.clone();
        let (started, waiting) = std::sync::mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            started.send(()).unwrap();
            extract(
                &PdfInput {
                    path: "/does-not-exist/cancelled.pdf".into(),
                    source_sha256: [0; 32],
                },
                &native_options(),
                &waiting_cancel,
            )
        });
        waiting.recv().unwrap();
        cancel.cancel();
        drop(slot);
        assert!(matches!(
            worker.join().unwrap(),
            Err(SasooError::Incomplete(_))
        ));
    }
}
