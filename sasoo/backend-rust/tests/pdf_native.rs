#![cfg(feature = "pdf-xberg-native")]

use sasoo_backend::{
    error::SasooError,
    pdf::{BlockContent, PdfInput, extract_document, native::native_options},
};
use sha2::{Digest, Sha256};
use tokio_util::sync::CancellationToken;

// Build real PDF bytes with independent, explicit page-tree and text expectations.
fn pdf(pages: &[(&str, &str)], inherited: &str) -> Vec<u8> {
    let kids = (0..pages.len())
        .map(|i| format!("{} 0 R", 5 + 2 * i))
        .collect::<Vec<_>>()
        .join(" ");
    let mut objects = vec![
        "<< /Type /Catalog /Pages 2 0 R >>".as_bytes().to_vec(),
        format!("<< /Type /Pages /Count {} /Kids [{kids}] {inherited} >>", pages.len()).into_bytes(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>".to_vec(),
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>\nstream\n\xff\nendstream".to_vec(),
    ];
    for (i, (extra, content)) in pages.iter().enumerate() {
        objects.push(format!("<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 3 0 R >> /XObject << /Im0 4 0 R >> >> /Contents {} 0 R {extra} >>", 6 + 2 * i).into_bytes());
        objects.push(
            format!(
                "<< /Length {} >>\nstream\n{content}\nendstream",
                content.len()
            )
            .into_bytes(),
        );
    }
    let mut bytes = b"%PDF-1.7\n".to_vec();
    let mut offsets = vec![0];
    for (i, object) in objects.iter().enumerate() {
        offsets.push(bytes.len());
        bytes.extend_from_slice(format!("{} 0 obj\n", i + 1).as_bytes());
        bytes.extend_from_slice(object);
        bytes.extend_from_slice(b"\nendobj\n");
    }
    let startxref = bytes.len();
    bytes.extend_from_slice(format!("xref\n0 {}\n0000000000 65535 f \n", offsets.len()).as_bytes());
    for offset in &offsets[1..] {
        bytes.extend_from_slice(format!("{offset:010} 00000 n \n").as_bytes());
    }
    bytes.extend_from_slice(
        format!(
            "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n",
            offsets.len()
        )
        .as_bytes(),
    );
    bytes
}

fn input(dir: &std::path::Path, bytes: &[u8]) -> PdfInput {
    let path = dir.join("source.pdf");
    std::fs::write(&path, bytes).unwrap();
    PdfInput {
        path,
        source_sha256: Sha256::digest(bytes).into(),
    }
}

#[test]
fn close_indented_lines_keep_baseline_order_even_with_one_span_per_line() {
    let dir = tempfile::tempdir().unwrap();
    // Leading is below the parser's 1.2 em same-line tolerance.
    let input = input(
        dir.path(),
        &pdf(
            &[(
                "",
                "BT /F1 12 Tf 70 700 Td (The upper indented line ends here.) Tj -30 -11 Td (Continuation belongs below the first line.) Tj ET",
            )],
            "/MediaBox [0 0 612 792]",
        ),
    );
    let doc = extract_document(&input, &native_options(), &CancellationToken::new()).unwrap();
    let BlockContent::Text { text } = &doc.blocks[0].content else {
        panic!("text expected")
    };
    assert!(
        text.find("upper indented").unwrap() < text.find("Continuation").unwrap(),
        "{text}"
    );
}

#[test]
fn accepts_legacy_header_window_without_removing_preamble_from_source_hash() {
    let dir = tempfile::tempdir().unwrap();
    let mut bytes = b"preamble\n".to_vec();
    bytes.extend(pdf(
        &[(
            "",
            "BT /F1 12 Tf 40 700 Td (Preamble input keeps its original bytes.) Tj ET",
        )],
        "/MediaBox [0 0 612 792]",
    ));
    let input = input(dir.path(), &bytes);
    let doc = extract_document(&input, &native_options(), &CancellationToken::new()).unwrap();
    assert_eq!(doc.source_sha256, <[u8; 32]>::from(Sha256::digest(&bytes)));
    assert_eq!(std::fs::read(&input.path).unwrap(), bytes);
    let mut late = vec![b' '; 1020];
    late.extend_from_slice(b"%PDF-");
    assert!(!sasoo_backend::pdf::artifacts::valid_pdf_header(&late));
    assert!(sasoo_backend::pdf::artifacts::valid_pdf_header(
        b"\n%PDF-1.7"
    ));
}

#[test]
fn extracts_physical_pages_preserves_raw_geometry_and_marks_image_only_page() {
    let dir = tempfile::tempdir().unwrap();
    let bytes = pdf(
        &[
            (
                "/UserUnit 2",
                "BT /F1 12 Tf 40 700 Td (Independent alpha on physical page one.) Tj ET",
            ),
            ("", "q 100 0 0 100 40 500 cm /Im0 Do Q"),
        ],
        "/MediaBox [-10 20 602 812] /CropBox [0 30 590 800] /Rotate 90",
    );
    let input = input(dir.path(), &bytes);
    std::fs::write(
        dir.path().join(".document_context.json"),
        b"keep legacy bytes",
    )
    .unwrap();
    let options = native_options();
    let doc = extract_document(&input, &options, &CancellationToken::new()).unwrap();
    doc.validate().unwrap();
    assert_eq!(doc.source_sha256, input.source_sha256);
    assert_eq!(doc.engine, options.engine);
    assert_eq!(doc.extraction_options_sha256, Some(options.options_hash));
    assert_eq!(doc.pages.len(), 2);
    assert_eq!(doc.pages[0].media_box, [-10.0, 20.0, 602.0, 812.0]);
    assert_eq!(doc.pages[0].crop_box, [0.0, 30.0, 590.0, 800.0]);
    assert_eq!(
        (doc.pages[0].rotation_deg, doc.pages[0].user_unit),
        (90, 2.0)
    );
    assert_eq!(
        (doc.pages[1].page_index0, doc.pages[1].page_number1),
        (1, 2)
    );
    assert_eq!(doc.pages[1].user_unit, 1.0);
    assert_eq!(doc.blocks.len(), 1);
    assert!(
        matches!(&doc.blocks[0].content, BlockContent::Text { text } if text.contains("Independent alpha"))
    );
    assert_eq!(doc.blocks[0].reading_order, Some(0));
    assert_eq!(doc.blocks[0].bbox, None);
    assert_eq!(doc.blocks[0].provenance.ocr, Some(false));
    assert!(
        doc.warnings
            .iter()
            .any(|w| w.code == "no_text_layer" && w.page_index0 == Some(1))
    );
    assert!(
        doc.warnings
            .iter()
            .any(|w| w.code == "unverified_reading_order")
    );
    assert_eq!(std::fs::read(&input.path).unwrap(), bytes);
    assert_eq!(
        std::fs::read(dir.path().join(".document_context.json")).unwrap(),
        b"keep legacy bytes"
    );
    assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 2);
}

#[test]
fn rejects_wrong_source_and_forged_engine_profile_or_options() {
    let dir = tempfile::tempdir().unwrap();
    let mut input = input(dir.path(), &pdf(&[("", "")], "/MediaBox [0 0 612 792]"));
    let options = native_options();
    input.source_sha256 = [42; 32];
    assert!(matches!(
        extract_document(&input, &options, &CancellationToken::new()),
        Err(SasooError::Conflict(_))
    ));
    input.source_sha256 = Sha256::digest(std::fs::read(&input.path).unwrap()).into();
    for field in ["version", "revision", "profile", "options", "resources"] {
        let mut wrong = options.clone();
        match field {
            "version" => wrong.engine.version = "unknown".into(),
            "revision" => wrong.engine.revision = None,
            "profile" => wrong.profile = "ocr".into(),
            "resources" => wrong.engine.resource_manifest_sha256 = Some([1; 32]),
            _ => wrong.options_hash = [0; 32],
        }
        assert!(
            matches!(
                extract_document(&input, &wrong, &CancellationToken::new()),
                Err(SasooError::Conflict(_))
            ),
            "{field}"
        );
    }
}

#[test]
fn rejects_invalid_pdf_geometry_and_empty_page_tree() {
    let dir = tempfile::tempdir().unwrap();
    for bytes in [
        b"not a PDF".to_vec(),
        b"%PDF-1.7\ntruncated".to_vec(),
        pdf(&[], "/MediaBox [0 0 612 792]"),
        pdf(&[("", "")], ""),
        pdf(&[("", "")], "/MediaBox [0 0 0 792]"),
        pdf(&[("/UserUnit 0", "")], "/MediaBox [0 0 612 792]"),
        pdf(&[("/UserUnit /Invalid", "")], "/MediaBox [0 0 612 792]"),
        pdf(&[("/Rotate 45", "")], "/MediaBox [0 0 612 792]"),
        pdf(&[("/CropBox [0 0 10]", "")], "/MediaBox [0 0 612 792]"),
    ] {
        let input = input(dir.path(), &bytes);
        assert!(extract_document(&input, &native_options(), &CancellationToken::new()).is_err());
    }
}

#[test]
fn normalizes_only_valid_quadrant_rotations_and_defaults_crop_to_media() {
    let dir = tempfile::tempdir().unwrap();
    for (rotation, expected) in [
        (0, 0),
        (90, 90),
        (180, 180),
        (270, 270),
        (-90, 270),
        (360, 0),
    ] {
        let extra = format!("/Rotate {rotation}");
        let input = input(dir.path(), &pdf(&[(&extra, "")], "/MediaBox [0 0 612 792]"));
        let doc = extract_document(&input, &native_options(), &CancellationToken::new()).unwrap();
        assert_eq!(doc.pages[0].rotation_deg, expected);
        assert_eq!(doc.pages[0].crop_box, doc.pages[0].media_box);
    }
}

#[test]
fn cancellation_and_input_size_limit_fail_before_parsing() {
    let dir = tempfile::tempdir().unwrap();
    let input = input(dir.path(), b"%PDF-1.7\n");
    let cancel = CancellationToken::new();
    cancel.cancel();
    assert!(matches!(
        extract_document(&input, &native_options(), &cancel),
        Err(SasooError::Incomplete(_))
    ));
    std::fs::OpenOptions::new()
        .write(true)
        .open(&input.path)
        .unwrap()
        .set_len(100 * 1024 * 1024 + 1)
        .unwrap();
    assert!(matches!(
        extract_document(&input, &native_options(), &CancellationToken::new()),
        Err(SasooError::InvalidInput(_))
    ));
}

#[test]
fn extracted_text_retains_retrieval_and_selection_page_contracts() {
    use sasoo_backend::analysis::{
        chat_retrieval::{Document, search, verify_pages},
        selection_context::{Selection, match_selection},
    };
    let dir = tempfile::tempdir().unwrap();
    let input = input(
        dir.path(),
        &pdf(
            &[
                (
                    "",
                    "BT /F1 12 Tf 40 700 Td (Introduction with independent background.) Tj ET",
                ),
                (
                    "",
                    "BT /F1 12 Tf 40 700 Td (Conditional objectives have identical gradients for model parameters.) Tj ET",
                ),
            ],
            "/MediaBox [0 0 612 792]",
        ),
    );
    let artifact = extract_document(&input, &native_options(), &CancellationToken::new()).unwrap();
    let pages: Vec<String> = artifact
        .blocks
        .iter()
        .map(|b| match &b.content {
            BlockContent::Text { text } => text.clone(),
            _ => unreachable!(),
        })
        .collect();
    let document = Document {
        parser_version: "sasoo-xberg-native-text-v1".into(),
        full_text: pages
            .iter()
            .enumerate()
            .map(|(i, t)| format!("--- Page {} ---\n\n{t}", i + 1))
            .collect::<Vec<_>>()
            .join("\n\n"),
    };
    let independent_pages = vec![
        "Introduction with independent background.".into(),
        "Conditional objectives have identical gradients for model parameters.".into(),
    ];
    let found = verify_pages(
        search(&document, "conditional gradients", 4),
        Some(&independent_pages),
    );
    assert!(!found.is_empty());
    assert_eq!(found[0].page, Some(2));
    assert_eq!(found[0].extraction_status, "page_confirmed");
    let selection = match_selection(
        &pages[1..2],
        Selection {
            text: "objectives have identical gradients".into(),
            page: 2,
            end_page: 2,
        },
    )
    .unwrap();
    assert_eq!(selection.status, "matched");
    assert_eq!(selection.selection.page, 2);
}
