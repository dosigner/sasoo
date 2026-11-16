//! Write a new isolated extraction version without updating a library or sidecar.
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::Path,
    time::Instant,
};

use sasoo_backend::pdf::{
    BlockContent, PdfInput, extract_document,
    native::{NATIVE_SETTINGS, native_options},
};
use serde_json::json;
use sha2::{Digest, Sha256};
use tokio_util::sync::CancellationToken;

fn write_new(root: &Path, name: &str, bytes: &[u8]) -> std::io::Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join(name))?;
    file.write_all(bytes)?;
    file.sync_all()
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 2 {
        return Err("Usage: pdf_probe <input.pdf> <new-output-directory>".into());
    }
    let source = fs::canonicalize(&args[0])?;
    let output = Path::new(&args[1]);
    if output.exists() {
        return Err("Output directory already exists; choose a new extraction version".into());
    }
    let source_sha256 = {
        let file = File::open(&source)?;
        if !file.metadata()?.is_file() || file.metadata()?.len() > 100 * 1024 * 1024 {
            return Err("Input must be a regular PDF file of at most 100 MiB".into());
        }
        let mut bytes = Vec::new();
        file.take(100 * 1024 * 1024 + 1).read_to_end(&mut bytes)?;
        if bytes.len() > 100 * 1024 * 1024 {
            return Err("Input grew beyond 100 MiB".into());
        }
        Sha256::digest(bytes).into()
    };
    let options = native_options();
    let started = Instant::now();
    let document = extract_document(
        &PdfInput {
            path: source,
            source_sha256,
        },
        &options,
        &CancellationToken::new(),
    )?;
    let elapsed_ms = started.elapsed().as_secs_f64() * 1000.0;
    let mut pages = vec![String::new(); document.pages.len()];
    for block in &document.blocks {
        if let BlockContent::Text { text } = &block.content {
            pages[block.page_index0 as usize].push_str(text);
        }
    }
    let full_text = pages
        .iter()
        .enumerate()
        .map(|(index, text)| format!("--- Page {} ---\n\n{text}", index + 1))
        .collect::<Vec<_>>()
        .join("\n\n");
    let text_pages = pages.iter().filter(|text| !text.trim().is_empty()).count();
    let status = if text_pages == 0 {
        "no_native_text"
    } else if text_pages != pages.len() {
        "partial_native_text"
    } else {
        "native_text_extracted_unverified"
    };
    let receipt = json!({
        "status": status,
        "evidence_kind": "local_native_text_probe",
        "production_engine_adopted": false,
        "engine": options.engine,
        "source_sha256": source_sha256.iter().map(|b| format!("{b:02x}")).collect::<String>(),
        "physical_pages": pages.len(),
        "pages_with_text": text_pages,
        "pages_without_text": pages.len() - text_pages,
        "elapsed_ms": elapsed_ms,
        "warning_count": document.warnings.len(),
        "ocr": false,
    });
    // Creating the directory is the no-overwrite fence between concurrent probes.
    fs::create_dir(output)?;
    write_new(
        output,
        "document.json",
        &serde_json::to_vec_pretty(&document)?,
    )?;
    write_new(
        output,
        "page-text.json",
        &serde_json::to_vec_pretty(&pages)?,
    )?;
    write_new(output, "full-text.txt", full_text.as_bytes())?;
    write_new(
        output,
        "options.json",
        &serde_json::to_vec_pretty(&json!({
            "options": options,
            "settings": serde_json::from_str::<serde_json::Value>(NATIVE_SETTINGS)?,
            "settings_bytes": NATIVE_SETTINGS,
        }))?,
    )?;
    write_new(
        output,
        "receipt.json",
        &serde_json::to_vec_pretty(&receipt)?,
    )?;
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

fn main() -> std::process::ExitCode {
    match run() {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("PDF probe failed: {error}");
            std::process::ExitCode::FAILURE
        }
    }
}
