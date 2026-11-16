use crate::error::{Result, SasooError};
use crate::types::UtcMillis;
use rust_decimal::{Decimal, RoundingStrategy};
use serde_json::Value;
use std::str::FromStr;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KnownUsage {
    pub tokens_in: u64,
    pub tokens_out: u64,
    pub tokens_cached: Option<u64>,
    pub tokens_cache_write: Option<u64>,
}

#[derive(Debug, Clone)]
pub struct PinnedRates {
    pub model: String,
    pub source_sha256: &'static str,
    pub valid_utc_day: i64,
    pub priced_tokens_in: u64,
    pub input: Decimal,
    pub output: Decimal,
    pub cached_input: Decimal,
    pub cache_write: Decimal,
    pub long_context: bool,
}

fn invalid(reason: &str) -> SasooError {
    SasooError::InvalidInput(reason.into())
}
fn decimal(value: &str) -> Decimal {
    Decimal::from_str(value).expect("Pinned decimal rate must be valid")
}

pub fn reported_usage(value: &Value) -> Result<KnownUsage> {
    if value.get("usage_complete") == Some(&Value::Bool(false)) {
        return Err(invalid("Incomplete usage cannot be priced"));
    }
    let count = |field: &str| {
        value
            .get(field)
            .and_then(Value::as_u64)
            .ok_or_else(|| invalid(&format!("{field} must be a non-negative integer")))
    };
    let optional = |field: &str| match value.get(field) {
        None | Some(Value::Null) => Ok(None),
        _ => count(field).map(Some),
    };
    let result = KnownUsage {
        tokens_in: count("tokens_in")?,
        tokens_out: count("tokens_out")?,
        tokens_cached: optional("tokens_cached")?,
        tokens_cache_write: optional("tokens_cache_write")?,
    };
    validate_usage(&result)?;
    Ok(result)
}

fn validate_usage(usage: &KnownUsage) -> Result<()> {
    if usage
        .tokens_cached
        .unwrap_or(0)
        .checked_add(usage.tokens_cache_write.unwrap_or(0))
        .is_none_or(|n| n > usage.tokens_in)
    {
        return Err(invalid("Cache token counts exceed total input tokens"));
    }
    Ok(())
}

pub fn price(usage: &KnownUsage, rates: &PinnedRates, at: UtcMillis) -> Result<Decimal> {
    validate_usage(usage)?;
    if usage.tokens_in != rates.priced_tokens_in {
        return Err(invalid("Pinned rates belong to different input usage"));
    }
    if at.div_euclid(86_400_000) != rates.valid_utc_day {
        return Err(invalid("Pinned rates belong to a different UTC date"));
    }
    if rates.model.starts_with("gpt-") && rates.long_context != (usage.tokens_in > 272_000) {
        return Err(invalid("Pinned rates belong to a different context tier"));
    }
    if [
        rates.input,
        rates.output,
        rates.cached_input,
        rates.cache_write,
    ]
    .iter()
    .any(|v| *v < Decimal::ZERO)
    {
        return Err(invalid("Rates must be non-negative"));
    }
    let (cached, written) = if rates.model.starts_with("gpt-") {
        match (usage.tokens_cached, usage.tokens_cache_write) {
            (Some(c), Some(w)) => (c, w),
            _ => (0, usage.tokens_in),
        }
    } else {
        (0, 0)
    };
    let ordinary = usage.tokens_in - cached - written;
    let mul = |tokens: u64, rate: Decimal| {
        Decimal::from(tokens)
            .checked_mul(rate)
            .ok_or_else(|| invalid("Cost exceeds decimal range"))
    };
    let add = |a: Decimal, b: Decimal| {
        a.checked_add(b)
            .ok_or_else(|| invalid("Cost exceeds decimal range"))
    };
    let input = add(
        add(
            mul(ordinary, rates.input)?,
            mul(cached, rates.cached_input)?,
        )?,
        mul(written, rates.cache_write)?,
    )?;
    let input = input
        .checked_mul(if rates.long_context {
            decimal("2")
        } else {
            Decimal::ONE
        })
        .ok_or_else(|| invalid("Cost exceeds decimal range"))?;
    let output = mul(usage.tokens_out, rates.output)?
        .checked_mul(if rates.long_context {
            decimal("1.5")
        } else {
            Decimal::ONE
        })
        .ok_or_else(|| invalid("Cost exceeds decimal range"))?;
    let total = add(input, output)?
        .checked_div(decimal("1000000"))
        .ok_or_else(|| invalid("Cost exceeds decimal range"))?;
    Ok(total.round_dp_with_strategy(8, RoundingStrategy::MidpointNearestEven))
}

pub fn python_quantize_8(text: &str) -> Result<String> {
    let value = Decimal::from_str(text)
        .map_err(|_| invalid("Invalid decimal value"))?
        .round_dp_with_strategy(8, RoundingStrategy::MidpointNearestEven);
    let mut scaled = value;
    scaled.rescale(8);
    python_decimal_str(&scaled.to_string())
}

// Rates are copied from the source revision, not fetched from current provider prices.
pub fn legacy_rates(model: &str, at: UtcMillis, tokens_in: u64) -> Result<PinnedRates> {
    let selected = match model {
        "gemini-3.1-pro-preview" => model,
        "gemini-3.8-flash" => model,
        "gemini-3.7-flash" => model,
        "gemini-3.6-flash" => model,
        "gemini-3.5-flash-lite" => model,
        "gemini-3.5-flash" => model,
        "gemini-3-flash-preview" => model,
        "gemini-3.1-flash-lite" => model,
        "gemini-3-pro-image" => model,
        "gemini-3.1-flash-image" => model,
        "gemini-nano-banana-2.1" => model,
        "gemini-3.1-flash-lite-preview" => model,
        "gemini-3-pro-image-preview" => model,
        "gemini-3.1-flash-image-preview" => model,
        "gemini-2.5-flash" => model,
        "gemini-2.0-flash" => model,
        "claude-sonnet-4-20250514" => model,
        "claude-sonnet-4-5-20250929" => model,
        "gpt-5.6-luna" => model,
        "gpt-6-luna" => model,
        _ if model.starts_with("gpt-") => "gpt-5.6-luna",
        _ => "gemini-3-flash-preview",
    };
    let (input, output, cached, write) = match selected {
        "gemini-3.1-pro-preview" => ("2.0", "12.0", "2.0", "2.0"),
        "gemini-3.8-flash" => ("1.5", "7.5", "1.5", "1.5"),
        "gemini-3.7-flash" => ("1.5", "7.5", "1.5", "1.5"),
        "gemini-3.6-flash" => ("1.5", "7.5", "1.5", "1.5"),
        "gemini-3.5-flash-lite" => ("0.3", "2.5", "0.3", "0.3"),
        "gemini-3.5-flash" => ("1.5", "9.0", "1.5", "1.5"),
        "gemini-3-flash-preview" => ("0.5", "3.0", "0.5", "0.5"),
        "gemini-3.1-flash-lite" => ("0.25", "1.5", "0.25", "0.25"),
        "gemini-3-pro-image" => ("2.0", "12.0", "2.0", "2.0"),
        "gemini-3.1-flash-image" => ("0.5", "3.0", "0.5", "0.5"),
        "gemini-nano-banana-2.1" => ("1.5", "7.5", "1.5", "1.5"),
        "gemini-3.1-flash-lite-preview" => ("0.25", "1.5", "0.25", "0.25"),
        "gemini-3-pro-image-preview" => ("2.0", "12.0", "2.0", "2.0"),
        "gemini-3.1-flash-image-preview" => ("0.5", "3.0", "0.5", "0.5"),
        "gemini-2.5-flash" => ("0.3", "2.5", "0.3", "0.3"),
        "gemini-2.0-flash" => ("0.1", "0.4", "0.1", "0.1"),
        "claude-sonnet-4-20250514" => ("3.0", "15.0", "3.0", "3.0"),
        "claude-sonnet-4-5-20250929" => ("3.0", "15.0", "3.0", "3.0"),
        "gpt-5.6-luna" => ("0.2", "1.2", "0.02", "0.25"),
        "gpt-6-luna" => ("0.1", "0.5", "0.01", "0.125"),
        _ => return Err(invalid("Pinned model rate is unavailable")),
    };
    let (input, output) = if matches!(
        selected,
        "gemini-3.8-flash" | "gemini-3.7-flash" | "gemini-3.6-flash"
    ) && at < 1798761600000
    {
        ("0.75", "3.75")
    } else if selected == "gemini-3.1-pro-preview" && tokens_in > 200_000 {
        ("4.0", "18.0")
    } else {
        (input, output)
    };
    let (cached, write) = if selected.starts_with("gpt-") {
        (cached, write)
    } else {
        (input, input)
    };
    Ok(PinnedRates {
        model: selected.into(),
        source_sha256: "1667bf86faa63cc1652aab82469030e6362967ce88878592b7d33616d8a1934b",
        valid_utc_day: at.div_euclid(86_400_000),
        priced_tokens_in: tokens_in,
        input: decimal(input),
        output: decimal(output),
        cached_input: decimal(cached),
        cache_write: decimal(write),
        long_context: selected.starts_with("gpt-") && tokens_in > 272_000,
    })
}

pub fn python_decimal_str(text: &str) -> Result<String> {
    let (sign, text) = if let Some(value) = text.strip_prefix('-') {
        ("-", value)
    } else {
        ("", text.strip_prefix('+').unwrap_or(text))
    };
    let mut exponents = text.split(['e', 'E']);
    let mantissa = exponents.next().unwrap_or("");
    let exponent = exponents
        .next()
        .map_or(Ok(0), |v| v.parse::<i32>())
        .map_err(|_| invalid("Invalid decimal exponent"))?;
    if exponents.next().is_some() {
        return Err(invalid("Invalid decimal value"));
    }
    let mut parts = mantissa.split('.');
    let whole = parts.next().unwrap_or("");
    let fraction = parts.next().unwrap_or("");
    if parts.next().is_some()
        || whole.is_empty() && fraction.is_empty()
        || !whole
            .bytes()
            .chain(fraction.bytes())
            .all(|b| b.is_ascii_digit())
    {
        return Err(invalid("Invalid decimal value"));
    }
    let combined = format!("{whole}{fraction}");
    let digits = combined.trim_start_matches('0');
    let digits = if digits.is_empty() { "0" } else { digits };
    let exponent = exponent
        .checked_sub(
            i32::try_from(fraction.len()).map_err(|_| invalid("Decimal exceeds string range"))?,
        )
        .ok_or_else(|| invalid("Decimal exceeds string range"))?;
    let adjusted = exponent
        .checked_add(digits.len() as i32 - 1)
        .ok_or_else(|| invalid("Decimal exceeds string range"))?;
    if exponent > 0 || adjusted < -6 {
        let tail = if digits.len() > 1 {
            format!(".{}", &digits[1..])
        } else {
            String::new()
        };
        return Ok(format!(
            "{sign}{}{tail}E{}{adjusted}",
            &digits[..1],
            if adjusted >= 0 { "+" } else { "" }
        ));
    }
    let position = digits.len() as i32 + exponent;
    let fixed = if position <= 0 {
        format!("0.{}{digits}", "0".repeat((-position) as usize))
    } else if position as usize >= digits.len() {
        format!("{digits}{}", "0".repeat(position as usize - digits.len()))
    } else {
        format!(
            "{}.{}",
            &digits[..position as usize],
            &digits[position as usize..]
        )
    };
    Ok(format!("{sign}{fixed}"))
}
