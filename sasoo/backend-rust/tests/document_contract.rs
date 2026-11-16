use sasoo_backend::pdf::{
    BlockContent, DocumentArtifact, LegacyHelperRequest, PdfInput, PdfOptions, extract_document,
    import_legacy_response,
};
use tokio_util::sync::CancellationToken;

fn fixture() -> Vec<u8> {
    include_bytes!("../../contract-fixtures/rust-backend-v2/pdf/legacy-output.json").to_vec()
}

#[test]
fn source_frame_native_ids_merged_cells_and_unknown_evidence_roundtrip() {
    let source: serde_json::Value = serde_json::from_slice(&fixture()).unwrap();
    assert_eq!(source["evidence_kind"], "synthetic_adapter_contract");
    let document: DocumentArtifact = serde_json::from_value(source["document"].clone()).unwrap();
    document.validate().unwrap();
    assert_eq!(document.pages[0].page_index0, 0);
    assert_eq!(document.pages[0].page_number1, 1);
    let figure = document
        .blocks
        .iter()
        .find(|b| b.native_id == "fig-native-7")
        .unwrap();
    assert_eq!(figure.bbox, None);
    assert_eq!(figure.provenance.confidence, None);
    assert!(!figure.has_verified_bbox(&document.pages[0].geometry()));
    let table = document
        .blocks
        .iter()
        .find_map(|b| match &b.content {
            BlockContent::Table { cells, .. } => Some(cells),
            _ => None,
        })
        .unwrap();
    assert_eq!((table[0].rowspan, table[0].colspan), (2, 2));
    assert_eq!(table[0].bbox, None);
    let bytes = serde_json::to_vec(&document).unwrap();
    assert_eq!(
        serde_json::from_slice::<DocumentArtifact>(&bytes).unwrap(),
        document
    );
}

#[test]
fn legacy_response_rejects_wrong_source_engine_and_invalid_page_ids() {
    let value: serde_json::Value = serde_json::from_slice(&fixture()).unwrap();
    let document: DocumentArtifact = serde_json::from_value(value["document"].clone()).unwrap();
    let request = LegacyHelperRequest {
        pdf_path: "/synthetic/source.pdf".into(),
        output_dir: "/synthetic/private-attempt".into(),
        options: PdfOptions {
            engine: document.engine.clone(),
            profile: "legacy-explicit".into(),
            options_hash: [3; 32],
        },
        expected_sha256: document.source_sha256,
    };
    let response = serde_json::to_vec(&document).unwrap();
    assert_eq!(
        import_legacy_response(&request, &response).unwrap(),
        document
    );
    let mut mismatch = request.clone();
    mismatch.expected_sha256 = [2; 32];
    assert!(import_legacy_response(&mismatch, &response).is_err());
    mismatch = request.clone();
    mismatch.options.engine.name = "unrequested-engine".into();
    assert!(import_legacy_response(&mismatch, &response).is_err());
    mismatch = request.clone();
    mismatch.options.options_hash = [4; 32];
    assert!(import_legacy_response(&mismatch, &response).is_err());
    let mut invalid = document;
    invalid.pages[0].page_number1 = 0;
    assert!(import_legacy_response(&request, &serde_json::to_vec(&invalid).unwrap()).is_err());
}

#[test]
fn cancellation_and_unconfigured_engine_do_not_read_or_run_a_pdf() {
    let value: serde_json::Value = serde_json::from_slice(&fixture()).unwrap();
    let document: DocumentArtifact = serde_json::from_value(value["document"].clone()).unwrap();
    let input = PdfInput {
        path: "/does-not-exist/no-source.pdf".into(),
        source_sha256: document.source_sha256,
    };
    let options = PdfOptions {
        engine: document.engine,
        profile: "legacy-explicit".into(),
        options_hash: [3; 32],
    };
    let cancel = CancellationToken::new();
    cancel.cancel();
    assert!(extract_document(&input, &options, &cancel).is_err());
    let cancel = CancellationToken::new();
    let error = extract_document(&input, &options, &cancel).unwrap_err();
    assert!(error.to_string().contains("not configured"));
}

#[test]
#[cfg(not(feature = "pdf-xberg-native"))]
fn disabled_native_feature_fails_before_opening_a_source() {
    let input = PdfInput {
        path: "/does-not-exist/no-source.pdf".into(),
        source_sha256: [0; 32],
    };
    let options = PdfOptions {
        engine: sasoo_backend::pdf::EngineIdentity {
            name: "xberg-native-pdf".into(),
            version: "1.3.10".into(),
            revision: None,
            resource_manifest_sha256: None,
        },
        profile: "text-layer-v1".into(),
        options_hash: [0; 32],
    };
    let error = extract_document(&input, &options, &CancellationToken::new()).unwrap_err();
    assert!(matches!(
        error,
        sasoo_backend::error::SasooError::Unsupported(_)
    ));
    assert!(error.to_string().contains("--features pdf-xberg-native"));
}

#[test]
fn untrusted_bbox_and_asset_paths_cannot_gain_verified_status() {
    let value: serde_json::Value = serde_json::from_slice(&fixture()).unwrap();
    let document: DocumentArtifact = serde_json::from_value(value["document"].clone()).unwrap();
    let mut invalid = document.clone();
    invalid.blocks[0].bbox.as_mut().unwrap().coords[0] += 1.0;
    assert!(!invalid.blocks[0].has_verified_bbox(&invalid.pages[0].geometry()));
    assert!(invalid.validate().is_err());
    invalid = document.clone();
    invalid.blocks[0].source_bbox = None;
    assert!(invalid.validate().is_err());
    for path in [
        "../paid.png",
        "/absolute/file.png",
        "..\\paid.png",
        "C:\\paid.png",
    ] {
        invalid = document.clone();
        invalid.assets.push(sasoo_backend::pdf::AssetRef {
            id: "unsafe".into(),
            relative_path: path.into(),
            sha256: None,
            mime_type: None,
            source_native_id: None,
        });
        assert!(invalid.validate().is_err(), "{path}");
    }
}
