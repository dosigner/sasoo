use rust_decimal::Decimal;
use sasoo_backend::analysis::pricing::{
    KnownUsage, legacy_rates, price, python_decimal_str, python_quantize_8, reported_usage,
};
use serde_json::Value;
use std::str::FromStr;

fn fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../contract-fixtures/rust-backend-v2/pricing.json"
    ))
    .unwrap()
}
fn timestamp(day: &str) -> i64 {
    match day {
        "2026-11-13" => 1794528000000,
        "2026-12-31" => 1798675200000,
        "2027-01-01" => 1798761600000,
        _ => panic!("unowned fixture day"),
    }
}

#[test]
fn frozen_python_prices_and_half_even_ties_match() {
    for case in fixture()["cases"].as_array().unwrap() {
        let id = case["id"].as_str().unwrap();
        if id.starts_with("decimal:tie:") {
            assert_eq!(
                python_quantize_8(case["input"].as_str().unwrap()).unwrap(),
                case["expected"].as_str().unwrap()
            );
        } else if id.starts_with("cost:") {
            let input = &case["input"];
            let at = timestamp(input["as_of"].as_str().unwrap());
            let usage = KnownUsage {
                tokens_in: input["tokens_in"].as_u64().unwrap(),
                tokens_out: input["tokens_out"].as_u64().unwrap(),
                tokens_cached: Some(0),
                tokens_cache_write: Some(0),
            };
            let rates =
                legacy_rates(input["model"].as_str().unwrap(), at, usage.tokens_in).unwrap();
            assert_eq!(
                price(&usage, &rates, at).unwrap(),
                Decimal::from_str(&case["expected"]["cost_usd"].to_string()).unwrap(),
                "{id}"
            );
        }
    }
}

#[test]
fn unknown_is_rejected_and_cache_bound_does_not_double_count_reasoning() {
    let at = timestamp("2026-11-13");
    for case in fixture()["cases"].as_array().unwrap() {
        if let Some(input) = case.get("input") {
            if case["id"].as_str().unwrap().starts_with("usage:") {
                assert_eq!(
                    reported_usage(input).unwrap_err().to_string(),
                    case["expected"]["reason"].as_str().unwrap()
                );
            }
        }
    }
    let rates = legacy_rates("gpt-6-luna", at, 1000).unwrap();
    let upper = KnownUsage {
        tokens_in: 1000,
        tokens_out: 100,
        tokens_cached: None,
        tokens_cache_write: None,
    };
    assert_eq!(
        price(&upper, &rates, at).unwrap(),
        Decimal::from_str("0.000175").unwrap()
    );
    let invalid = KnownUsage {
        tokens_in: 1000,
        tokens_out: 100,
        tokens_cached: Some(600),
        tokens_cache_write: Some(500),
    };
    assert!(price(&invalid, &rates, at).is_err());
    assert!(price(&upper, &rates, at + 86_400_000).is_err());
    assert!(reported_usage(&serde_json::json!({"tokens_in":true,"tokens_out":0})).is_err());
    let with_reasoning=reported_usage(&serde_json::json!({"tokens_in":1000,"tokens_out":100,"tokens_thinking":90,"tokens_cached":0,"tokens_cache_write":0})).unwrap();
    assert_eq!(
        price(&with_reasoning, &rates, at).unwrap(),
        Decimal::from_str("0.00015").unwrap()
    );
}

#[test]
fn decimal_string_forms_preserve_scale_and_exponent() {
    for (input, expected) in [
        ("0.000000015", "1.5E-8"),
        ("1.2300", "1.2300"),
        ("1.0E+2", "1.0E+2"),
        ("0.00000000", "0E-8"),
        ("-0.00000000", "-0E-8"),
        ("0.0000010", "0.0000010"),
    ] {
        assert_eq!(python_decimal_str(input).unwrap(), expected);
    }
    assert!(python_decimal_str("NaN").is_err());
    assert!(python_decimal_str("Infinity").is_err());
    assert!(python_decimal_str("1e2147483648").is_err());
}
