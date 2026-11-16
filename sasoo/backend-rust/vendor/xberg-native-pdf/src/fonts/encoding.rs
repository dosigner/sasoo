//! Unicode encoding support for PDF text.
//!
//! This module handles encoding conversions for PDF text strings,
//! particularly for CID fonts with Identity-H encoding.
//!
//! # Identity-H Encoding
//!
//! Per PDF spec Section 9.7.5.2, Identity-H is a predefined CMap that
//! maps CIDs directly to character codes (i.e., CID = GID for TrueType).
//! This allows using glyph IDs directly in content streams as:
//!
//! ```text
//! <0001002300A4> Tj
//! ```
//!
//! Where each 4-digit hex value is a glyph ID (big-endian u16).

use std::collections::HashMap;

/// Unicode encoder for PDF text strings.
///
/// Converts Unicode text to PDF string format for different encodings.
#[derive(Debug)]
pub struct UnicodeEncoder {
    /// Glyph lookup function results cache
    glyph_cache: HashMap<u32, u16>,
}

impl UnicodeEncoder {
    /// Create a new Unicode encoder.
    pub fn new() -> Self {
        Self {
            glyph_cache: HashMap::new(),
        }
    }

    /// Encode a Unicode string to Identity-H format (hex string of glyph IDs).
    ///
    /// # Arguments
    /// * `text` - Unicode text to encode
    /// * `glyph_lookup` - Function to convert Unicode codepoint to glyph ID
    ///
    /// # Returns
    /// Hex-encoded string suitable for Tj/TJ operators, e.g., "<00410042>"
    pub fn encode_identity_h(&mut self, text: &str, glyph_lookup: impl Fn(u32) -> Option<u16>) -> String {
        let mut hex = String::with_capacity(text.len() * 4 + 2);
        hex.push('<');

        for ch in text.chars() {
            let codepoint = ch as u32;
            let glyph_id = self
                .glyph_cache
                .get(&codepoint)
                .copied()
                .or_else(|| {
                    let gid = glyph_lookup(codepoint)?;
                    self.glyph_cache.insert(codepoint, gid);
                    Some(gid)
                })
                .unwrap_or(0); // Use .notdef for missing glyphs ~keep

            hex.push_str(&format!("{:04X}", glyph_id));
        }

        hex.push('>');
        hex
    }

    /// Encode a single character to Identity-H format.
    pub fn encode_char_identity_h(&self, glyph_id: u16) -> String {
        format!("<{:04X}>", glyph_id)
    }

    /// Encode text as PDF literal string (for WinAnsi/MacRoman encoding).
    ///
    /// Characters outside the encoding are replaced with '?'.
    pub fn encode_literal(text: &str) -> String {
        let mut result = String::with_capacity(text.len() + 2);
        result.push('(');

        for ch in text.chars() {
            match ch {
                '(' => result.push_str("\\("),
                ')' => result.push_str("\\)"),
                '\\' => result.push_str("\\\\"),
                '\n' => result.push_str("\\n"),
                '\r' => result.push_str("\\r"),
                '\t' => result.push_str("\\t"),
                c if c.is_ascii() && c >= ' ' => result.push(c),
                c if (c as u32) < 256 => {
                    result.push_str(&format!("\\{:03o}", c as u32));
                }
                _ => result.push('?'),
            }
        }

        result.push(')');
        result
    }

    /// Encode text as PDF hex string for UTF-16BE.
    ///
    /// Used for metadata strings and bookmarks that need full Unicode.
    pub fn encode_utf16be(text: &str) -> String {
        let mut hex = String::new();
        hex.push('<');

        // BOM for UTF-16BE ~keep
        hex.push_str("FEFF");

        for ch in text.chars() {
            let codepoint = ch as u32;
            if codepoint <= 0xFFFF {
                hex.push_str(&format!("{:04X}", codepoint));
            } else {
                let adjusted = codepoint - 0x10000;
                let high = ((adjusted >> 10) & 0x3FF) + 0xD800;
                let low = (adjusted & 0x3FF) + 0xDC00;
                hex.push_str(&format!("{:04X}{:04X}", high, low));
            }
        }

        hex.push('>');
        hex
    }

    /// Encode text as PDF literal string if ASCII, otherwise as UTF-16BE hex.
    ///
    /// This is the recommended approach for general PDF strings.
    pub fn encode_text(text: &str) -> String {
        if text
            .chars()
            .all(|c| c.is_ascii() && c >= ' ' && c != '(' && c != ')' && c != '\\')
        {
            format!("({})", text)
        } else if text.chars().all(|c| (c as u32) < 256) {
            Self::encode_literal(text)
        } else {
            Self::encode_utf16be(text)
        }
    }

    /// Clear the glyph cache.
    pub fn clear_cache(&mut self) {
        self.glyph_cache.clear();
    }

    /// Get cache statistics.
    pub fn cache_size(&self) -> usize {
        self.glyph_cache.len()
    }
}

impl Default for UnicodeEncoder {
    fn default() -> Self {
        Self::new()
    }
}

/// Map a Mathematical Alphanumeric Symbol (U+1D400-U+1D7FF) to its plain
/// Latin or Greek base codepoint.
///
/// This block holds 1024 styled letter/digit forms (italic, bold, script,
/// fraktur, double-struck, sans-serif, monospace) used in mathematical
/// notation. None of them have glyphs in the standard 14 PDF fonts, but
/// they collapse cleanly to plain letters: `𝑥` (U+1D465) → `x`, `𝛽`
/// (U+1D6FD) → `β`, etc. The block is structured as fixed-stride 26-letter
/// or 10-digit ranges, so the mapping is purely arithmetic.
///
/// Returns None for codepoints outside the block (and for the 6 reserved
/// holes within it where the canonical letter lives elsewhere).
pub fn math_alphanumeric_base(codepoint: u32) -> Option<u32> {
    if !(0x1D400..=0x1D7FF).contains(&codepoint) {
        return None;
    }
    math_alphanumeric_reserved_hole(codepoint)
        .or_else(|| math_alphanumeric_latin(codepoint))
        .or_else(|| math_alphanumeric_greek(codepoint))
        .or_else(|| math_alphanumeric_digit(codepoint))
}

/// Reserved holes: codepoints already encoded elsewhere in Unicode.
/// (BMP italic h, planar holes for h-related letters, etc.) ~keep
fn math_alphanumeric_reserved_hole(codepoint: u32) -> Option<u32> {
    let canonical = match codepoint {
        0x1D455 => 0x0068,
        0x1D49D => 0x0042,
        0x1D4A0 => 0x0045,
        0x1D4A1 => 0x0046,
        0x1D4A3 => 0x0048,
        0x1D4A4 => 0x0049,
        0x1D4A7 => 0x004C,
        0x1D4A8 => 0x004D,
        0x1D4AD => 0x0052,
        0x1D4BA => 0x0065,
        0x1D4BC => 0x0067,
        0x1D4C4 => 0x006F,
        0x1D506 => 0x0043,
        0x1D50B => 0x0048,
        0x1D50C => 0x0049,
        0x1D515 => 0x0052,
        0x1D51D => 0x005A,
        0x1D53A => 0x0043,
        0x1D53F => 0x0048,
        0x1D545 => 0x004E,
        0x1D547 => 0x0050,
        0x1D548 => 0x0051,
        0x1D549 => 0x0052,
        0x1D551 => 0x005A,
        _ => 0,
    };
    if canonical != 0 { Some(canonical) } else { None }
}

/// Bold / Italic / Bold-Italic / Script / Bold-Script / Fraktur /
/// Double-Struck / Bold-Fraktur / Sans / Sans-Bold / Sans-Italic /
/// Sans-Bold-Italic / Mono Latin (each 52 chars: A-Z then a-z). ~keep
fn math_alphanumeric_latin(codepoint: u32) -> Option<u32> {
    const LATIN_RANGES: &[(u32, u32)] = &[
        (0x1D400, 0x41),
        (0x1D41A, 0x61),
        (0x1D434, 0x41),
        (0x1D44E, 0x61),
        (0x1D468, 0x41),
        (0x1D482, 0x61),
        (0x1D49C, 0x41),
        (0x1D4B6, 0x61),
        (0x1D4D0, 0x41),
        (0x1D4EA, 0x61),
        (0x1D504, 0x41),
        (0x1D51E, 0x61),
        (0x1D538, 0x41),
        (0x1D552, 0x61),
        (0x1D56C, 0x41),
        (0x1D586, 0x61),
        (0x1D5A0, 0x41),
        (0x1D5BA, 0x61),
        (0x1D5D4, 0x41),
        (0x1D5EE, 0x61),
        (0x1D608, 0x41),
        (0x1D622, 0x61),
        (0x1D63C, 0x41),
        (0x1D656, 0x61),
        (0x1D670, 0x41),
        (0x1D68A, 0x61),
    ];
    for &(start, base) in LATIN_RANGES {
        if codepoint >= start && codepoint < start + 26 {
            return Some(base + (codepoint - start));
        }
    }
    None
}

/// Greek bold / italic / bold-italic / sans-bold / sans-bold-italic.
/// Each block is 58 chars: 25 capitals (Α-Ω inc. capital Theta variant
/// at offset 17), nabla at +25, then 25 lowercase α-ω at +26, partial-
/// differential at +51, then 6 alt forms (epsilon/theta/kappa/phi/rho/pi).
/// We map the 25 capitals (best-effort — the Theta-variant slot lands on
/// unassigned U+03A2 but is rare) and the 25 lowercases. ~keep
fn math_alphanumeric_greek(codepoint: u32) -> Option<u32> {
    const GREEK_RANGES: &[u32] = &[0x1D6A8, 0x1D6E2, 0x1D71C, 0x1D756, 0x1D790];
    for &start in GREEK_RANGES {
        if codepoint >= start && codepoint < start + 25 {
            return Some(0x0391 + (codepoint - start));
        }
        let lower_start = start + 26;
        if codepoint >= lower_start && codepoint < lower_start + 25 {
            return Some(0x03B1 + (codepoint - lower_start));
        }
    }
    None
}

fn math_alphanumeric_digit(codepoint: u32) -> Option<u32> {
    const DIGIT_STARTS: &[u32] = &[0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6];
    for &start in DIGIT_STARTS {
        if codepoint >= start && codepoint < start + 10 {
            return Some(0x30 + (codepoint - start));
        }
    }
    None
}

/// WinAnsi (Windows-1252) encoding table.
///
/// Maps Unicode codepoints to WinAnsi byte values for the range 0x80-0x9F
/// which differs from Latin-1.
pub fn unicode_to_winansi(codepoint: u32) -> Option<u8> {
    if codepoint < 0x80 || (0xA0..=0xFF).contains(&codepoint) {
        return Some(codepoint as u8);
    }

    match codepoint {
        0x20AC => Some(0x80),
        0x201A => Some(0x82),
        0x0192 => Some(0x83),
        0x201E => Some(0x84),
        0x2026 => Some(0x85),
        0x2020 => Some(0x86),
        0x2021 => Some(0x87),
        0x02C6 => Some(0x88),
        0x2030 => Some(0x89),
        0x0160 => Some(0x8A),
        0x2039 => Some(0x8B),
        0x0152 => Some(0x8C),
        0x017D => Some(0x8E),
        0x2018 => Some(0x91),
        0x2019 => Some(0x92),
        0x201C => Some(0x93),
        0x201D => Some(0x94),
        0x2022 => Some(0x95),
        0x2013 => Some(0x96),
        0x2014 => Some(0x97),
        0x02DC => Some(0x98),
        0x2122 => Some(0x99),
        0x0161 => Some(0x9A),
        0x203A => Some(0x9B),
        0x0153 => Some(0x9C),
        0x017E => Some(0x9E),
        0x0178 => Some(0x9F),
        _ => None,
    }
}

/// Check if a character can be encoded in WinAnsi.
pub fn is_winansi_char(ch: char) -> bool {
    unicode_to_winansi(ch as u32).is_some()
}

/// Escape a byte for PDF literal string.
fn escape_byte_for_literal(b: u8) -> String {
    match b {
        b'(' => "\\(".to_string(),
        b')' => "\\)".to_string(),
        b'\\' => "\\\\".to_string(),
        0x0A => "\\n".to_string(),
        0x0D => "\\r".to_string(),
        0x09 => "\\t".to_string(),
        0x08 => "\\b".to_string(),
        0x0C => "\\f".to_string(),
        b if (0x20..0x7F).contains(&b) => (b as char).to_string(),
        b => format!("\\{:03o}", b),
    }
}

/// Encode bytes as PDF literal string with proper escaping.
pub fn encode_bytes_as_literal(bytes: &[u8]) -> String {
    let mut result = String::with_capacity(bytes.len() * 2 + 2);
    result.push('(');
    for &b in bytes {
        result.push_str(&escape_byte_for_literal(b));
    }
    result.push(')');
    result
}

/// Encode bytes as PDF hex string.
pub fn encode_bytes_as_hex(bytes: &[u8]) -> String {
    let mut result = String::with_capacity(bytes.len() * 2 + 2);
    result.push('<');
    for b in bytes {
        result.push_str(&format!("{:02X}", b));
    }
    result.push('>');
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_encode_identity_h() {
        let mut encoder = UnicodeEncoder::new();
        let lookup = |cp: u32| match cp {
            0x41 => Some(1_u16),
            0x42 => Some(2_u16),
            _ => None,
        };

        let result = encoder.encode_identity_h("AB", lookup);
        assert_eq!(result, "<00010002>");
    }

    #[test]
    fn test_encode_identity_h_missing_glyph() {
        let mut encoder = UnicodeEncoder::new();
        let lookup = |_: u32| None;

        let result = encoder.encode_identity_h("A", lookup);
        assert_eq!(result, "<0000>"); // .notdef ~keep
    }

    #[test]
    fn test_encode_literal_simple() {
        let result = UnicodeEncoder::encode_literal("Hello");
        assert_eq!(result, "(Hello)");
    }

    #[test]
    fn test_encode_literal_escapes() {
        let result = UnicodeEncoder::encode_literal("(test)");
        assert_eq!(result, "(\\(test\\))");

        let result = UnicodeEncoder::encode_literal("back\\slash");
        assert_eq!(result, "(back\\\\slash)");
    }

    #[test]
    fn test_encode_utf16be() {
        let result = UnicodeEncoder::encode_utf16be("A");
        assert_eq!(result, "<FEFF0041>");

        let result = UnicodeEncoder::encode_utf16be("\u{20AC}");
        assert_eq!(result, "<FEFF20AC>");
    }

    #[test]
    fn test_encode_utf16be_supplementary() {
        let result = UnicodeEncoder::encode_utf16be("\u{1F600}");
        // U+1F600 = surrogate pair D83D DE00 ~keep
        assert_eq!(result, "<FEFFD83DDE00>");
    }

    #[test]
    fn test_encode_text_auto() {
        let result = UnicodeEncoder::encode_text("Hello");
        assert_eq!(result, "(Hello)");

        let result = UnicodeEncoder::encode_text("Hello\u{20AC}World");
        assert!(result.starts_with("<FEFF"));
    }

    #[test]
    fn test_winansi_mapping() {
        assert_eq!(unicode_to_winansi(0x41), Some(0x41));
        assert_eq!(unicode_to_winansi(0x20AC), Some(0x80));
        assert_eq!(unicode_to_winansi(0x2019), Some(0x92));
        assert_eq!(unicode_to_winansi(0x10000), None);
    }

    #[test]
    fn test_math_alphanumeric_basic() {
        assert_eq!(math_alphanumeric_base(0x1D465), Some(0x78));
        assert_eq!(math_alphanumeric_base(0x1D434), Some(0x41));
        assert_eq!(math_alphanumeric_base(0x1D41A), Some(0x61));
        assert_eq!(math_alphanumeric_base(0x1D455), Some(0x68));
        assert_eq!(math_alphanumeric_base(0x41), None);
        assert_eq!(math_alphanumeric_base(0x1D800), None);
    }

    #[test]
    fn test_math_alphanumeric_greek() {
        assert_eq!(math_alphanumeric_base(0x1D6FD), Some(0x03B2));
        assert_eq!(math_alphanumeric_base(0x1D70E), Some(0x03C3));
        assert_eq!(math_alphanumeric_base(0x1D6E2), Some(0x0391));
    }

    #[test]
    fn test_math_alphanumeric_digits() {
        assert_eq!(math_alphanumeric_base(0x1D7CE), Some(0x30));
        assert_eq!(math_alphanumeric_base(0x1D7FF), Some(0x39));
    }

    #[test]
    fn test_is_winansi_char() {
        assert!(is_winansi_char('A'));
        assert!(is_winansi_char('\u{20AC}'));
        assert!(!is_winansi_char('\u{4E2D}'));
    }

    #[test]
    fn test_encode_bytes_as_hex() {
        let result = encode_bytes_as_hex(&[0x41, 0x42, 0x43]);
        assert_eq!(result, "<414243>");
    }

    #[test]
    fn test_encode_bytes_as_literal() {
        let result = encode_bytes_as_literal(b"ABC");
        assert_eq!(result, "(ABC)");

        let result = encode_bytes_as_literal(&[0x28, 0x29]);
        assert_eq!(result, "(\\(\\))");
    }

    #[test]
    fn test_encoder_caching() {
        let mut encoder = UnicodeEncoder::new();
        let lookup = |cp: u32| Some(cp as u16);

        encoder.encode_identity_h("AAA", lookup);
        assert_eq!(encoder.cache_size(), 1); // Only 'A' cached ~keep

        encoder.encode_identity_h("ABC", lookup);
        assert_eq!(encoder.cache_size(), 3);

        encoder.clear_cache();
        assert_eq!(encoder.cache_size(), 0);
    }
}
