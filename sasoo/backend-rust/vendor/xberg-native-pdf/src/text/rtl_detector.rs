//! Right-to-Left (RTL) Script Support
//!
//! This module provides comprehensive support for Arabic and Hebrew scripts,
//! including:
//! - Script detection (Arabic, Hebrew, supplements, presentation forms)
//! - Diacritical mark handling (no boundaries before marks)
//! - Letter and punctuation detection
//! - Number handling (Western and Eastern Arabic digits)
//! - LAM-ALEF ligature support
//! - Contextual form normalization
//! - RTL-specific word boundary detection
//!
//! The implementation follows Unicode standards and common RTL text processing rules.

use crate::text::{BoundaryContext, CharacterInfo};

/// Detected RTL script types
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RTLScript {
    /// Arabic main block (U+0600-U+06FF)
    Arabic,
    /// Arabic Supplement (U+0750-U+077F)
    ArabicSupplement,
    /// Arabic Extended-A (U+08A0-U+08FF)
    ArabicExtendedA,
    /// Hebrew (U+0590-U+05FF)
    Hebrew,
    /// Arabic Presentation Forms-A (U+FB50-U+FDFF)
    PresentationFormsA,
    /// Arabic Presentation Forms-B (U+FE70-U+FEFF)
    PresentationFormsB,
}

/// Detect RTL script for a character code (O(1) complexity)
///
/// Returns the specific RTL script type if the character belongs to an RTL script,
/// or None if it's not an RTL character.
///
/// # Fast Path
/// The implementation checks the Arabic main range first as it's most common.
pub fn detect_rtl_script(code: u32) -> Option<RTLScript> {
    if matches!(code, 0x0600..=0x06FF) {
        return Some(RTLScript::Arabic);
    }

    match code {
        0x0590..=0x05FF => Some(RTLScript::Hebrew),
        0x0750..=0x077F => Some(RTLScript::ArabicSupplement),
        0x08A0..=0x08FF => Some(RTLScript::ArabicExtendedA),
        0xFB50..=0xFDFF => Some(RTLScript::PresentationFormsA),
        0xFE70..=0xFEFF => Some(RTLScript::PresentationFormsB),
        _ => None,
    }
}

/// Check if a character code is any RTL text
///
/// This is a convenience function that returns true if the character
/// belongs to any RTL script (Arabic or Hebrew).
#[inline]
pub fn is_rtl_text(code: u32) -> bool {
    detect_rtl_script(code).is_some()
}

/// Check if a code is an Arabic diacritical mark
///
/// Arabic diacritics include:
/// - Basic marks (U+064B-U+0658): FATHATAN, DAMMATAN, KASRATAN, FATHA, DAMMA, KASRA, SHADDA, SUKUN, etc.
/// - Extended marks (U+06D6-U+06ED): Various small high and low marks
///
/// Diacritics should never create word boundaries.
pub fn is_arabic_diacritic(code: u32) -> bool {
    matches!(code,
        0x064B..=0x0658 |
        0x06D6..=0x06DC |
        0x06DF..=0x06E4 |
        0x06E7..=0x06E8 |
        0x06EA..=0x06ED
    )
}

/// Check if a code is an Arabic letter (not diacritic or punctuation)
///
/// Includes letters from:
/// - Arabic main block (U+0621-U+063A, U+0641-U+064A)
/// - Arabic Supplement (U+0750-U+076D)
/// - Arabic Extended-A (U+08A0-U+08B4, U+08B6-U+08BD)
pub fn is_arabic_letter(code: u32) -> bool {
    matches!(code,
        0x0621..=0x063A |
        0x0641..=0x064A |
        0x0750..=0x076D |
        0x08A0..=0x08B4 |
        0x08B6..=0x08BD
    )
}

/// Arabic letters with Unicode `Joining_Type = R` (right-joining only): they
/// join to a preceding letter but NEVER to the following one, so the cursive
/// connection breaks *after* them regardless of any following letter. The
/// canonical set is the alef family (ا أ إ آ ٱ), waw (و ؤ), dal/thal (د ذ),
/// reh/zain (ر ز), teh marbuta (ة), and their block variants — per Unicode
/// `ArabicShaping.txt`.
///
/// Relevance (ISO 32000-1 §14.8.2.3.3): because the join already breaks after
/// an R-letter, a SPACE following one renders the same whether it is a genuine
/// word break or a producer artefact — the two are visually indistinguishable.
/// The interior-space stripper uses this to avoid concatenating two real words
/// across such a space (`دار اب` must stay two words, not become `داراب`).
pub fn is_right_joining_arabic(code: u32) -> bool {
    matches!(code,
        0x0622..=0x0625 |
        0x0627 |
        0x0629 |
        0x062F | 0x0630 |
        0x0631 | 0x0632 |
        0x0648 |
        0x0671..=0x0673 | 0x0675 |
        0x0688..=0x0699 |
        0x06C0 | 0x06C3..=0x06CB | 0x06CD | 0x06CF |
        0x06D2 | 0x06D3 |
        0x06EE | 0x06EF
    )
}

/// Check if a code is a Hebrew diacritical mark
///
/// Hebrew diacritics include:
/// - Vowel points (U+05B0-U+05BB): SHEVA, HATAF SEGOL, HOLAM, etc.
/// - Other marks (U+05BC-U+05C7): DAGESH, METEG, RAFE, SHIN DOT, SIN DOT, etc.
///
/// Diacritics should never create word boundaries.
pub fn is_hebrew_diacritic(code: u32) -> bool {
    matches!(code,
        0x05B0..=0x05BB |
        0x05BC |
        0x05BD |
        0x05BF |
        0x05C1..=0x05C2 |
        0x05C4..=0x05C5 |
        0x05C7
    )
}

/// Check if a code is a Hebrew letter
///
/// Hebrew alphabet: U+05D0-U+05EA (ALEF through TAV)
pub fn is_hebrew_letter(code: u32) -> bool {
    matches!(code, 0x05D0..=0x05EA)
}

/// Check if a code is Hebrew punctuation
///
/// Includes:
/// - GERESH (U+05F3): Used for abbreviations
/// - GERSHAYIM (U+05F4): Used for acronyms and abbreviations
pub fn is_hebrew_punctuation(code: u32) -> bool {
    matches!(code, 0x05F3 | 0x05F4)
}

/// Check if a code is any RTL diacritical mark (Arabic or Hebrew)
#[inline]
pub fn is_rtl_diacritic(code: u32) -> bool {
    is_arabic_diacritic(code) || is_hebrew_diacritic(code)
}

/// Normalize Arabic contextual form to base character
///
/// Arabic letters have multiple presentation forms (isolated, initial, medial, final).
/// This function maps presentation forms back to their base characters.
///
/// Handles:
/// - Presentation Forms-A (U+FB50-U+FDFF)
/// - Presentation Forms-B (U+FE70-U+FEFF)
///
/// Returns the base character if a presentation form, otherwise returns the original code.
pub fn normalize_arabic_contextual_form(code: u32) -> u32 {
    match code {
        0xFB50 => 0x0671,
        0xFE82 => 0x0627,
        0xFE8D => 0x0627,
        0xFE8E => 0x0627,

        0xFE8F => 0x0628,
        0xFE90 => 0x0628,
        0xFE91 => 0x0628,
        0xFE92 => 0x0628,

        // For full implementation, would need all ~600 mappings
        // For now, if in presentation form range but not mapped, return as-is ~keep
        0xFB50..=0xFDFF | 0xFE70..=0xFEFF => {
            // Generic approximation: many presentation forms follow patterns
            // In production, use a complete lookup table ~keep
            code
        }

        _ => code,
    }
}

/// Check if a code is a LAM-ALEF ligature
///
/// LAM-ALEF is a mandatory ligature in Arabic consisting of LAM (ل) + ALEF (ا) or variants.
/// Unicode has dedicated code points for these ligatures:
/// - U+FEFB, U+FEFC: LAM with ALEF
/// - U+FEF5-U+FEFA: LAM with ALEF variants (with MADDA, HAMZA ABOVE, HAMZA BELOW)
pub fn is_lam_alef_ligature(code: u32) -> bool {
    matches!(code, 0xFEF5..=0xFEFC)
}

/// Decompose a LAM-ALEF ligature into its constituent characters
///
/// Returns (LAM, ALEF_VARIANT) if the code is a LAM-ALEF ligature, None otherwise.
pub fn decompose_lam_alef(code: u32) -> Option<(u32, u32)> {
    match code {
        0xFEFB | 0xFEFC => Some((0x0644, 0x0627)),
        0xFEF5 | 0xFEF6 => Some((0x0644, 0x0622)),
        0xFEF7 | 0xFEF8 => Some((0x0644, 0x0623)),
        0xFEF9 | 0xFEFA => Some((0x0644, 0x0625)),
        _ => None,
    }
}

/// Check if a code is an Eastern Arabic-Indic digit (٠-٩)
///
/// Eastern Arabic digits: U+06F0-U+06F9
/// These are commonly used in Persian, Urdu, and some Arabic contexts.
pub fn is_eastern_arabic_digit(code: u32) -> bool {
    matches!(code, 0x06F0..=0x06F9)
}

/// Check if a code is a number in RTL context (Western or Eastern Arabic digit)
///
/// Includes:
/// - Western digits (0-9): U+0030-U+0039
/// - Eastern Arabic-Indic digits (٠-٩): U+06F0-U+06F9
///
/// In RTL text, both types of digits may appear and should be kept together.
pub fn is_arabic_number(code: u32) -> bool {
    matches!(code,
        0x0030..=0x0039 |
        0x06F0..=0x06F9
    )
}

/// Determine if a word boundary should be created between two characters in RTL context
///
/// Returns:
/// - Some(true): Definitely create a boundary
/// - Some(false): Definitely do NOT create a boundary
/// - None: Not applicable (let other detectors handle)
///
/// # Boundary Rules (in priority order)
///
/// 1. **Space (U+0020)**: Always creates a boundary
/// 2. **TATWEEL (U+0640)**: Never creates a boundary (Arabic kashida for elongation)
/// 3. **Diacritics**: Never create boundaries (must stay with base character)
/// 4. **Multiple marks on same base**: No boundary between marks
/// 5. **TJ offset**: Large negative offset (< -50) in RTL context creates boundary
/// 6. **Script transitions**: RTL-to-LTR or LTR-to-RTL creates boundary
/// 7. **RTL punctuation**: Creates boundary
/// 8. **Number sequences**: No boundaries within digit sequences
/// 9. **Normal letters**: No boundary between consecutive letters of same script
///
/// # Arguments
///
/// * `prev_char` - The previous character
/// * `curr_char` - The current character
/// * `context` - Optional boundary context (unused for RTL currently)
pub fn should_split_at_rtl_boundary(
    prev_char: &CharacterInfo,
    curr_char: &CharacterInfo,
    _context: Option<&BoundaryContext>,
) -> Option<bool> {
    let prev_code = prev_char.code;
    let curr_code = curr_char.code;

    let prev_is_rtl = is_rtl_text(prev_code);
    let curr_is_rtl = is_rtl_text(curr_code);

    if curr_code == 0x0020 || prev_code == 0x0020 {
        return Some(true);
    }

    // Rule 8 (early): Number sequences - no boundaries between digits
    // This must come before the RTL check because Western digits (0-9) are not RTL ~keep
    if is_arabic_number(prev_code) && is_arabic_number(curr_code) {
        return Some(false);
    }

    if !prev_is_rtl && !curr_is_rtl {
        return None;
    }

    rtl_script_boundary(prev_char, curr_char, prev_is_rtl, curr_is_rtl)
}

/// Rules 3-9 of [`should_split_at_rtl_boundary`], applied in the same order
/// once at least one side of the pair is known to be RTL.
fn rtl_script_boundary(
    prev_char: &CharacterInfo,
    curr_char: &CharacterInfo,
    prev_is_rtl: bool,
    curr_is_rtl: bool,
) -> Option<bool> {
    let prev_code = prev_char.code;
    let curr_code = curr_char.code;

    if curr_code == 0x0640 || prev_code == 0x0640 {
        return Some(false);
    }

    if is_rtl_diacritic(curr_code) {
        return Some(false);
    }

    if is_rtl_diacritic(prev_code) && is_rtl_diacritic(curr_code) {
        return Some(false);
    }

    if let Some(tj_offset) = prev_char.tj_offset
        && tj_offset < -50
    {
        return Some(true);
    }

    // Rule 6: RTL-to-LTR or LTR-to-RTL transitions create boundary
    // But skip if both are numbers (already handled above) ~keep
    if prev_is_rtl != curr_is_rtl && !(is_arabic_number(prev_code) && is_arabic_number(curr_code)) {
        return Some(true);
    }

    rtl_same_script_boundary(prev_code, curr_code, prev_is_rtl, curr_is_rtl)
}

/// Rules 7-9: punctuation, same-script letter runs, and the same-script RTL
/// fallthrough. Reached only once the transition rules above have declined.
fn rtl_same_script_boundary(prev_code: u32, curr_code: u32, prev_is_rtl: bool, curr_is_rtl: bool) -> Option<bool> {
    if is_arabic_punctuation(curr_code) || is_hebrew_punctuation(curr_code) {
        return Some(true);
    }

    if (is_arabic_letter(prev_code) || is_arabic_letter(normalize_arabic_contextual_form(prev_code)))
        && (is_arabic_letter(curr_code) || is_arabic_letter(normalize_arabic_contextual_form(curr_code)))
    {
        return Some(false);
    }

    if is_hebrew_letter(prev_code) && is_hebrew_letter(curr_code) {
        return Some(false);
    }

    // Both are RTL but fall through all rules - assume no boundary for same-script RTL ~keep
    if prev_is_rtl && curr_is_rtl {
        return Some(false);
    }

    // Shouldn't reach here, but return None as fallback ~keep
    None
}

/// Check if a code is Arabic punctuation
///
/// Common Arabic punctuation marks that should create word boundaries.
fn is_arabic_punctuation(code: u32) -> bool {
    matches!(code, 0x060C | 0x061B | 0x061F | 0x066A | 0x066B | 0x066C | 0x066D)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_script_detection() {
        assert_eq!(detect_rtl_script(0x0627), Some(RTLScript::Arabic));
        assert_eq!(detect_rtl_script(0x05D0), Some(RTLScript::Hebrew));
        assert_eq!(detect_rtl_script(0x0041), None);
    }

    #[test]
    fn test_right_joining_arabic() {
        for r in [
            0x0627, 0x0622, 0x0623, 0x0625, 0x062F, 0x0630, 0x0631, 0x0632, 0x0648, 0x0629,
        ] {
            assert!(is_right_joining_arabic(r), "{r:#06X} should be right-joining");
        }
        // Dual-joining letters (beh, teh, lam, qaf, …) and yeh-hamza are NOT R. ~keep
        for d in [0x0628, 0x062A, 0x0644, 0x0642, 0x0639, 0x0626] {
            assert!(!is_right_joining_arabic(d), "{d:#06X} should be dual-joining");
        }
        assert!(!is_right_joining_arabic(0x05D0));
        assert!(!is_right_joining_arabic(0x0041));
    }

    #[test]
    fn test_basic_diacritic_detection() {
        assert!(is_arabic_diacritic(0x064E));
        assert!(is_hebrew_diacritic(0x05BC));
        assert!(!is_arabic_diacritic(0x0627));
    }

    #[test]
    fn test_basic_letter_detection() {
        assert!(is_arabic_letter(0x0628));
        assert!(is_hebrew_letter(0x05D1));
        assert!(!is_arabic_letter(0x064B));
    }

    #[test]
    fn test_lam_alef_basic() {
        assert!(is_lam_alef_ligature(0xFEFC));
        assert_eq!(decompose_lam_alef(0xFEFC), Some((0x0644, 0x0627)));
    }
}
