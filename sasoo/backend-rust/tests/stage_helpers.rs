//! Shared stage helpers against Python outputs (tests/stage_helpers_oracle.py).
use sasoo_backend::analysis::screening::stage;
use serde_json::Value;

fn fixture() -> Value {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/stage/helpers-v1.json");
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

fn cases<'a>(doc: &'a Value, name: &str) -> &'a Vec<Value> {
    doc[name].as_array().unwrap()
}

fn opt_str(v: &Value) -> Option<String> {
    v.as_str().map(str::to_owned)
}

/// Python detects repetition without spaces through zlib; Rust lacks flate2 until Codex
/// adds it, so those inputs are listed here and checked to still be the only gap.
fn zlib_only(input: &str) -> bool {
    input.contains(&"가나다라마".repeat(120))
}

#[test]
fn clean_and_defect_match_python() {
    let doc = fixture();
    for c in cases(&doc, "clean_llm_json") {
        assert_eq!(stage::clean_llm_json(c["input"].as_str().unwrap()), c["output"].as_str().unwrap(), "{c}");
    }
    for c in cases(&doc, "stage_result_defect") {
        assert_eq!(stage::stage_result_defect(c["input"].as_str().unwrap()).map(str::to_owned), opt_str(&c["output"]), "{c}");
    }
    for c in cases(&doc, "is_error_result") {
        assert_eq!(stage::is_error_result(c["input"].as_str().unwrap()), c["output"].as_bool().unwrap(), "{c}");
    }
}

#[test]
fn degenerate_detection_matches_python_except_zlib_only_inputs() {
    let doc = fixture();
    let mut gaps = 0;
    for c in cases(&doc, "is_degenerate_string") {
        let input = c["input"].as_str().unwrap();
        let got = stage::is_degenerate_string(input);
        if zlib_only(input) {
            assert!(c["output"].as_bool().unwrap() && !got, "zlib gap changed: {input:.40}");
            gaps += 1;
            continue;
        }
        assert_eq!(got, c["output"].as_bool().unwrap(), "{input:.60}");
    }
    assert_eq!(gaps, 1);
}

#[test]
fn salvage_and_drop_match_python_bytes() {
    let doc = fixture();
    let schema = &doc["schema"];
    for c in cases(&doc, "salvage_truncated_json") {
        assert_eq!(stage::salvage_truncated_json(c["input"].as_str().unwrap(), schema), opt_str(&c["output"]), "{c}");
    }
    for c in cases(&doc, "drop_degenerate_fields") {
        assert_eq!(stage::drop_degenerate_fields(c["input"].as_str().unwrap(), schema), opt_str(&c["output"]), "{c}");
    }
}

#[test]
fn gate_restart_skip_and_error_rows_match_python() {
    let doc = fixture();
    for c in cases(&doc, "screening_gate_decision") {
        let (skip, reason) = stage::screening_gate_decision(c["input"].as_str(), c["phase"].as_str().unwrap());
        assert_eq!(serde_json::json!([skip, reason]), c["output"], "{c}");
    }
    for c in cases(&doc, "chain_restart_context") {
        let prev: Vec<String> = c["input"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_owned()).collect();
        assert_eq!(stage::chain_restart_context(&prev, 4000), c["output"].as_str().unwrap());
    }
    for c in cases(&doc, "skip_reason") {
        assert_eq!(stage::skip_reason(c["input"].as_str().unwrap()), c["output"].as_str().unwrap(), "{c}");
    }
    for c in cases(&doc, "parse_error_text") {
        assert_eq!(
            stage::parse_error_text(c["raw"].as_str().unwrap(), c["reason"].as_str().unwrap()),
            c["output"].as_str().unwrap()
        );
    }
}
