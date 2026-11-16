use base64::{Engine, engine::general_purpose::STANDARD};
use sasoo_backend::analysis::{
    cache::{CacheInput, legacy_input_hash, phase_cache_key},
    prompts::{
        CompatibilityCase, codepoint_prefix, compat_bytes, python_json_bytes, system_instruction,
    },
    schemas::legacy_schema,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

fn fixture(name: &str) -> Value {
    serde_json::from_str(
        &std::fs::read_to_string(format!(
            "{}/../contract-fixtures/rust-backend-v2/{name}.json",
            env!("CARGO_MANIFEST_DIR")
        ))
        .unwrap(),
    )
    .unwrap()
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[test]
fn json_and_schema_bytes_match_python_source_vectors() {
    for case in fixture("bytes")["cases"]
        .as_array()
        .unwrap()
        .iter()
        .chain(fixture("schemas")["cases"].as_array().unwrap())
    {
        if case["serializer"]["kind"] != "json.dumps" || case["expected"].is_null() {
            continue;
        }
        let actual = python_json_bytes(
            &case["expected"],
            case["serializer"]["ensure_ascii"].as_bool().unwrap(),
        )
        .unwrap();
        assert_eq!(
            actual,
            STANDARD
                .decode(case["utf8_base64"].as_str().unwrap())
                .unwrap(),
            "{}",
            case["id"]
        );
        assert_eq!(hash(&actual), case["sha256"].as_str().unwrap());
    }
    for case in fixture("schemas")["cases"].as_array().unwrap() {
        let actual = legacy_schema(case["id"].as_str().unwrap()).unwrap();
        assert_eq!(
            hash(&python_json_bytes(&actual, true).unwrap()),
            case["sha256"].as_str().unwrap()
        );
    }
    assert!(legacy_schema("missing").is_err());
}

#[test]
fn unicode_has_python_codepoint_and_ascii_escape_semantics() {
    assert_eq!(codepoint_prefix("한e\u{301}😀끝", 3), "한e\u{301}");
    assert_eq!(
        python_json_bytes(&json!({"a":"😀\u{7f}","한글":"e\u{301}"}), true).unwrap(),
        br#"{"a": "\ud83d\ude00\u007f", "\ud55c\uae00": "e\u0301"}"#
    );
    assert_eq!(
        python_json_bytes(&json!({"한글":"e\u{301}","a":"\u{1f}"}), false).unwrap(),
        "{\"a\": \"\\u001f\", \"한글\": \"é\"}".as_bytes()
    );
    assert_ne!(
        python_json_bytes(&json!({"a":null}), false).unwrap(),
        python_json_bytes(&json!({}), false).unwrap()
    );
}

#[test]
fn cache_keys_preserve_none_zero_unicode_and_separator() {
    for case in fixture("cache")["cases"].as_array().unwrap() {
        if !case["id"].as_str().unwrap().starts_with("phase_cache:") {
            continue;
        }
        let input: CacheInput = serde_json::from_value(case["input"].clone()).unwrap();
        let actual = phase_cache_key(&input).unwrap();
        assert_eq!(
            actual,
            STANDARD
                .decode(case["utf8_base64"].as_str().unwrap())
                .unwrap()
        );
        assert_eq!(hash(&actual), case["sha256"].as_str().unwrap());
    }
    assert_eq!(
        legacy_input_hash("abc", None, None, None),
        "ba7816bf8f01cfea"
    );
    assert_ne!(
        legacy_input_hash("abc", None, None, None),
        legacy_input_hash("abc", Some("openai"), None, None)
    );
    assert_ne!(
        legacy_input_hash("한é", Some("openai"), Some("m"), Some("low")),
        legacy_input_hash("한é", Some("openai"), Some("m"), Some("high"))
    );
}

#[test]
fn original_system_instruction_is_preserved() {
    let data = fixture("bytes");
    let case = data["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == "system_instruction")
        .unwrap();
    assert_eq!(
        system_instruction().as_bytes(),
        STANDARD
            .decode(case["utf8_base64"].as_str().unwrap())
            .unwrap()
    );
}

#[test]
fn serializer_float_notation_and_default_strings_match_python() {
    let value: Value = serde_json::from_str(
        r#"{"a":1.0,"b":1e20,"c":1e-7,"d":-0.0,"e":0.00001,"f":1e15,"g":0.0001}"#,
    )
    .unwrap();
    assert_eq!(
        String::from_utf8(python_json_bytes(&value, false).unwrap()).unwrap(),
        r#"{"a": 1.0, "b": 1e+20, "c": 1e-07, "d": -0.0, "e": 1e-05, "f": 1000000000000000.0, "g": 0.0001}"#
    );
    for raw in fixture("bytes")["cases"].as_array().unwrap() {
        let case: CompatibilityCase = serde_json::from_value(raw.clone()).unwrap();
        if case.id.starts_with("phase_input:") && case.serializer["kind"] == "utf8" {
            assert!(compat_bytes(&case).is_err());
            continue;
        }
        let actual = compat_bytes(&case).unwrap();
        assert_eq!(
            actual,
            STANDARD
                .decode(raw["utf8_base64"].as_str().unwrap())
                .unwrap(),
            "{}",
            case.id
        );
    }
}
