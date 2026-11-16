//! Document context against values recorded from the shipped Python builder
//! (tests/document_context_oracle.py).
use sasoo_backend::analysis::screening::document_context::{
    SectionSplitter, Sections, build_document_context_from_text, input_coverage,
    select_visual_source, source_signature,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::path::PathBuf;

fn load(path: &PathBuf) -> Value {
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

/// Every mismatching case name; the first diff is printed in full.
fn check_case(case: &Value, text: &str, failures: &mut Vec<String>) {
    let name = case["name"].as_str().unwrap_or("?");
    let signature = case
        .get("pdf_signature")
        .cloned()
        .unwrap_or(json!({"pdf_mtime_ns": 1, "pdf_size": 2}));
    let got = build_document_context_from_text(text, Some(signature), "fixture");
    if got != case["expected"] {
        for (k, v) in case["expected"].as_object().unwrap() {
            if got.get(k) != Some(v) {
                eprintln!(
                    "{name}: key {k} differs\n  rust: {}\n  py:   {v}",
                    got.get(k).unwrap_or(&Value::Null)
                );
                break;
            }
        }
        failures.push(name.into());
    }
    // The sidecar path recomputes references from stored sections (document_context.py:285).
    let mut sections = Sections::from_json(&case["expected"]["sections"]);
    sections.insert("full_text", text.into());
    if SectionSplitter.get_references_text(&sections)
        != case["expected"]["phase_inputs"]["citation_references"]
    {
        failures.push(format!("{name}: references"));
    }
    check_visual(case, text, failures);
}

fn check_visual(case: &Value, text: &str, failures: &mut Vec<String>) {
    let name = case["name"].as_str().unwrap_or("?");
    for run in case
        .get("visual")
        .or(case.get("runs"))
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let got = select_visual_source(&run["plan"], text, run["limit"].as_u64().unwrap() as usize);
        if got != run["expected"] {
            eprintln!(
                "{name}: visual {}\n  rust: {got}\n  py:   {}",
                run["plan"], run["expected"]
            );
            failures.push(format!("{name}: visual {}", run["plan"]));
        }
    }
}

#[test]
fn synthetic_cases_match_python() {
    let fixture = load(
        &PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures/document_context/synthetic-v1.json"),
    );
    let mut failures = Vec::new();
    let cases = fixture["cases"].as_array().unwrap();
    for case in cases {
        check_case(case, case["full_text"].as_str().unwrap(), &mut failures);
    }
    let visual_cases = fixture["visual_cases"].as_array().unwrap();
    for case in visual_cases {
        check_visual(case, case["full_text"].as_str().unwrap(), &mut failures);
    }
    for c in fixture["coverage"].as_array().unwrap() {
        let got = input_coverage(
            c["text"].as_str().unwrap(),
            c["pdf_sha256"].as_str(),
            c["text_limit"].as_i64(),
        );
        if got != c["expected"] {
            failures.push(format!("coverage {got}"));
        }
    }
    for c in fixture["signatures"].as_array().unwrap() {
        let got = source_signature(
            c["text"].as_str().unwrap(),
            c["pdf_sha256"].as_str(),
            c["detail"].as_str().unwrap(),
        );
        if got != c["expected"] {
            failures.push(format!("signature {got}"));
        }
    }
    assert!(
        cases.len() >= 19 && !visual_cases.is_empty(),
        "fixture has too few cases"
    );
    assert!(failures.is_empty(), "mismatches: {failures:?}");
}

#[test]
fn corpus_cases_match_python() {
    let Some(path) = std::env::var_os("SASOO_M1_CORPUS_ORACLE") else {
        eprintln!("skip: SASOO_M1_CORPUS_ORACLE is not set");
        return;
    };
    let oracle = load(&PathBuf::from(path));
    let mut failures = Vec::new();
    let cases = oracle["cases"].as_array().unwrap();
    for case in cases {
        let bytes = std::fs::read(case["full_text_path"].as_str().unwrap()).unwrap();
        let sha: String = Sha256::digest(&bytes)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        assert_eq!(
            sha,
            case["sha256"].as_str().unwrap(),
            "{} changed since the oracle ran",
            case["name"]
        );
        check_case(case, std::str::from_utf8(&bytes).unwrap(), &mut failures);
    }
    assert!(!cases.is_empty());
    assert!(failures.is_empty(), "mismatches: {failures:?}");
    eprintln!("corpus: {} cases match", cases.len());
}
