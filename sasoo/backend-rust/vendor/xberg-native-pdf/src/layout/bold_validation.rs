//! Conservative Bold Rendering Validation - Phase 2 Core
//!
//! This module validates bold marker placement before rendering to ensure
//! we never create invalid markdown like `** **` (bold with only whitespace).
//!
//! **PDF Spec Compliance**: ISO 32000-1:2008 Section 9.4.4 NOTE 6
//! Text formatting must only apply to actual content, not positioning artifacts.

/// Check if a character is any form of whitespace (ASCII or Unicode).
///
/// Standard Rust `char::is_whitespace()` handles most cases, but some PDFs
/// (especially policy documents) use Unicode whitespace characters that are
/// non-breaking or have special spacing semantics. These can appear in bold
/// markers but represent layout spacing, not content.
///
/// # Unicode whitespace variants covered:
/// - U+00A0: Non-breaking space (NBSP) - common in justified PDFs
/// - U+2007: Figure space - used in tables for alignment
/// - U+202F: Narrow no-break space - used in French/German typography
/// - U+3000: Ideographic space - used in Asian typesetting
/// - U+FEFF: Zero-width no-break space (BOM) - rarely in PDF, but defensive
///
/// # References:
/// - Unicode Standard Section 6.3 (C.1.2 Whitespace)
/// - PDF Spec ISO 32000-1:2008 Section 7.3.2 (String Types)
///
/// # Examples:
///
/// ```ignore
/// // ASCII whitespace
/// assert!(is_any_whitespace(' '));
/// assert!(is_any_whitespace('\t'));
/// assert!(is_any_whitespace('\n'));
///
/// // Unicode whitespace
/// assert!(is_any_whitespace('\u{00A0}')); // NBSP
/// assert!(is_any_whitespace('\u{2007}')); // Figure space
///
/// // Non-whitespace
/// assert!(!is_any_whitespace('a'));
/// assert!(!is_any_whitespace('1'));
/// ```
fn is_any_whitespace(c: char) -> bool {
    c.is_whitespace() || c == '\u{00A0}' || c == '\u{2007}' || c == '\u{202F}' || c == '\u{3000}' || c == '\u{FEFF}'
}

/// Result of bold marker validation
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BoldMarkerDecision {
    /// Safe to insert markers
    Insert,
    /// Skip markers - provides reason
    Skip(ValidatorError),
}

/// Reason why markers were not inserted
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ValidatorError {
    /// Content is purely whitespace
    WhitespaceOnly,
    /// No word character at opening position
    InvalidOpeningBoundary,
    /// No word character at closing position
    InvalidClosingBoundary,
    /// Content becomes empty after formatting
    EmptyAfterFormatting,
    /// Font is not bold
    NotBold,
}

/// A group of spans with the same bold status
#[derive(Debug, Clone)]
pub struct BoldGroup {
    /// Text content of the bold group
    pub text: String,
    /// Whether this group is bold (true) or regular (false)
    pub is_bold: bool,
    /// First character in the group for boundary validation
    pub first_char_in_group: Option<char>,
    /// Last character in the group for boundary validation
    pub last_char_in_group: Option<char>,
}

impl BoldGroup {
    /// Check if group has word content (non-whitespace, including Unicode variants).
    ///
    /// Uses comprehensive Unicode whitespace detection to handle PDFs with
    /// non-breaking spaces, figure spaces, and other Unicode spacing characters.
    /// This prevents policy PDFs with these characters from creating invalid bold markers.
    pub fn has_word_content(&self) -> bool {
        self.text.chars().any(|c| !is_any_whitespace(c))
    }

    /// Check if opening boundary is valid (word character, excluding Unicode whitespace).
    ///
    /// A valid opening boundary must be:
    /// 1. Alphabetic or numeric (actual word content)
    /// 2. NOT any form of whitespace (including Unicode variants like NBSP)
    ///
    /// This prevents patterns like "**\u{00A0}text**" where NBSP creates an invalid marker.
    pub fn has_valid_opening_boundary(&self) -> bool {
        match self.first_char_in_group {
            Some(c) => {
                let is_word_char = c.is_alphabetic() || c.is_numeric();
                let is_not_whitespace = !is_any_whitespace(c);
                is_word_char && is_not_whitespace
            }
            None => false,
        }
    }

    /// Check if closing boundary is valid (word character, excluding Unicode whitespace).
    ///
    /// A valid closing boundary must be:
    /// 1. Alphabetic or numeric (actual word content)
    /// 2. NOT any form of whitespace (including Unicode variants)
    ///
    /// This prevents patterns like "**text\u{00A0}**" where NBSP creates an invalid marker.
    pub fn has_valid_closing_boundary(&self) -> bool {
        match self.last_char_in_group {
            Some(c) => {
                let is_word_char = c.is_alphabetic() || c.is_numeric();
                let is_not_whitespace = !is_any_whitespace(c);
                is_word_char && is_not_whitespace
            }
            None => false,
        }
    }

    /// Simulate content after formatting (URLs, reference spacing cleanup)
    pub fn simulated_formatted_content(&self) -> String {
        // In real implementation, this would call the actual formatting functions
        // For now, just return the text as-is (conservative) ~keep
        self.text.clone()
    }
}

/// Validator for bold marker insertion
pub struct BoldMarkerValidator;

impl BoldMarkerValidator {
    /// **Task B.2: Enhanced boundary validation with word boundary context**
    ///
    /// Prevents bold markers from being inserted at invalid word boundaries.
    /// This prevents patterns like:
    /// - `theBold` (mid-word, part of CamelCase)
    /// - `boldness` (not full word)
    ///
    /// # Arguments
    ///
    /// * `preceding_text` - Text before the bold group (context)
    /// * `group_text` - The bold group's content
    /// * `following_text` - Text after the bold group (context)
    ///
    /// # Returns
    ///
    /// `true` if bold group has valid word boundaries before/after
    pub fn validate_boundary_context(preceding_text: &str, _group_text: &str, following_text: &str) -> bool {
        // Bold group must start with a word boundary
        // Valid: "word **bold**" or beginning of line
        // Invalid: "the**Bold**" (CamelCase mid-word) ~keep
        let has_space_before =
            preceding_text.ends_with(' ') || preceding_text.ends_with('\n') || preceding_text.is_empty();

        // Bold group must end with a word boundary
        // Valid: "**bold** word" or end of line
        // Invalid: "**bold**ness" (not complete word) ~keep
        let has_space_after =
            following_text.starts_with(' ') || following_text.starts_with('\n') || following_text.is_empty();

        has_space_before && has_space_after
    }

    /// Validate if markers can be safely inserted
    pub fn can_insert_markers(group: &BoldGroup) -> BoldMarkerDecision {
        if !group.is_bold {
            tracing::trace!(
                "Rejecting bold markers: not marked bold for '{}'",
                group.text.chars().take(20).collect::<String>()
            );
            return BoldMarkerDecision::Skip(ValidatorError::NotBold);
        }

        if !group.has_word_content() {
            tracing::trace!(
                "Rejecting bold markers: no word content in '{}'",
                group.text.chars().take(20).collect::<String>()
            );
            return BoldMarkerDecision::Skip(ValidatorError::WhitespaceOnly);
        }

        if !group.has_valid_opening_boundary() {
            tracing::trace!(
                "Rejecting bold markers: invalid opening boundary '{}' in '{}'",
                group.first_char_in_group.unwrap_or('?'),
                group.text.chars().take(20).collect::<String>()
            );
            return BoldMarkerDecision::Skip(ValidatorError::InvalidOpeningBoundary);
        }

        if !group.has_valid_closing_boundary() {
            tracing::trace!(
                "Rejecting bold markers: invalid closing boundary '{}' in '{}'",
                group.last_char_in_group.unwrap_or('?'),
                group.text.chars().take(20).collect::<String>()
            );
            return BoldMarkerDecision::Skip(ValidatorError::InvalidClosingBoundary);
        }

        let formatted = group.simulated_formatted_content();
        if formatted.trim().is_empty() {
            tracing::trace!("Rejecting bold markers: content became empty after formatting");
            return BoldMarkerDecision::Skip(ValidatorError::EmptyAfterFormatting);
        }

        BoldMarkerDecision::Insert
    }

    /// Check if all markers in a sequence are valid
    pub fn validate_group_sequence(groups: &[BoldGroup]) -> Result<(), String> {
        for (idx, group) in groups.iter().enumerate() {
            match Self::can_insert_markers(group) {
                BoldMarkerDecision::Skip(err) if group.is_bold => {
                    tracing::warn!(
                        "Group {}: {:?}: '{}'",
                        idx,
                        err,
                        group.text.chars().take(20).collect::<String>()
                    );
                }
                _ => {}
            }
        }
        Ok(())
    }

    /// Predict markdown output for group
    pub fn predict_markdown(group: &BoldGroup) -> String {
        match Self::can_insert_markers(group) {
            BoldMarkerDecision::Insert => {
                format!("**{}**", group.text)
            }
            BoldMarkerDecision::Skip(_) => group.text.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_valid_bold_group() {
        let group = BoldGroup {
            text: "hello".to_string(),
            is_bold: true,
            first_char_in_group: Some('h'),
            last_char_in_group: Some('o'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&group),
            BoldMarkerDecision::Insert
        );
    }

    #[test]
    fn test_whitespace_only_group() {
        let group = BoldGroup {
            text: "   ".to_string(),
            is_bold: true,
            first_char_in_group: Some(' '),
            last_char_in_group: Some(' '),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&group),
            BoldMarkerDecision::Skip(ValidatorError::WhitespaceOnly)
        );
    }

    #[test]
    fn test_invalid_opening_boundary() {
        let group = BoldGroup {
            text: "hello".to_string(),
            is_bold: true,
            first_char_in_group: Some(' '),
            last_char_in_group: Some('o'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&group),
            BoldMarkerDecision::Skip(ValidatorError::InvalidOpeningBoundary)
        );
    }

    #[test]
    fn test_invalid_closing_boundary() {
        let group = BoldGroup {
            text: "hello".to_string(),
            is_bold: true,
            first_char_in_group: Some('h'),
            last_char_in_group: Some(' '),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&group),
            BoldMarkerDecision::Skip(ValidatorError::InvalidClosingBoundary)
        );
    }

    #[test]
    fn test_predict_markdown() {
        let valid = BoldGroup {
            text: "hello".to_string(),
            is_bold: true,
            first_char_in_group: Some('h'),
            last_char_in_group: Some('o'),
        };

        assert_eq!(BoldMarkerValidator::predict_markdown(&valid), "**hello**");

        let whitespace = BoldGroup {
            text: "   ".to_string(),
            is_bold: true,
            first_char_in_group: Some(' '),
            last_char_in_group: Some(' '),
        };

        assert_eq!(BoldMarkerValidator::predict_markdown(&whitespace), "   ");
    }

    #[test]
    fn test_bold_respects_word_boundaries() {
        assert!(BoldMarkerValidator::validate_boundary_context("word ", "bold", " text"));

        assert!(BoldMarkerValidator::validate_boundary_context("", "bold", " text"));

        assert!(BoldMarkerValidator::validate_boundary_context("word ", "bold", ""));

        assert!(BoldMarkerValidator::validate_boundary_context("", "bold", ""));
    }

    #[test]
    fn test_bold_between_spaces() {
        assert!(!BoldMarkerValidator::validate_boundary_context("the", "Bold", " word"));

        assert!(!BoldMarkerValidator::validate_boundary_context("the ", "bold", "ness"));

        assert!(!BoldMarkerValidator::validate_boundary_context("the", "Bold", "ness"));
    }

    #[test]
    fn test_camelcase_split_not_bolded_individually() {
        // Edge case from word fusion fix: split CamelCase words
        // "theGeneral" splits into "the" and "General"
        // If "General" is bolded, it shouldn't be marked as bold in markdown
        // because it's mid-word in the original PDF context ~keep

        // Scenario: "the" + "General" where "General" is marked bold
        // If we try to bold "General" without context, it looks like:
        // "the**General**" which violates CamelCase integrity ~keep

        assert!(BoldMarkerValidator::validate_boundary_context("the ", "General", ""));

        assert!(!BoldMarkerValidator::validate_boundary_context("the", "General", ""));
    }

    #[test]
    fn test_newline_as_boundary() {
        assert!(BoldMarkerValidator::validate_boundary_context(
            "text\n", "bold", " more"
        ));

        assert!(BoldMarkerValidator::validate_boundary_context("text ", "bold", "\n"));

        assert!(BoldMarkerValidator::validate_boundary_context("text\n", "bold", "\n"));
    }

    #[test]
    fn test_punctuation_not_bolded() {
        let punct_group = BoldGroup {
            text: "---".to_string(),
            is_bold: true,
            first_char_in_group: Some('-'),
            last_char_in_group: Some('-'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&punct_group),
            BoldMarkerDecision::Skip(ValidatorError::InvalidOpeningBoundary)
        );
    }

    #[test]
    fn test_numeric_content_can_be_bold() {
        let num_group = BoldGroup {
            text: "2024".to_string(),
            is_bold: true,
            first_char_in_group: Some('2'),
            last_char_in_group: Some('4'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&num_group),
            BoldMarkerDecision::Insert
        );
    }

    #[test]
    fn test_alphanumeric_mixed_content() {
        let mixed_group = BoldGroup {
            text: "version2024".to_string(),
            is_bold: true,
            first_char_in_group: Some('v'),
            last_char_in_group: Some('4'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&mixed_group),
            BoldMarkerDecision::Insert
        );
    }

    #[test]
    fn test_no_empty_bold_markers_regression() {
        let empty_group = BoldGroup {
            text: " ".to_string(),
            is_bold: true,
            first_char_in_group: Some(' '),
            last_char_in_group: Some(' '),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&empty_group),
            BoldMarkerDecision::Skip(ValidatorError::WhitespaceOnly)
        );

        assert_eq!(BoldMarkerValidator::predict_markdown(&empty_group), " ");
    }

    #[test]
    fn test_fix_2b_nbsp_treated_as_whitespace() {
        // Non-breaking space (U+00A0) should be treated as whitespace
        // This is common in justified PDF documents ~keep

        let nbsp_group = BoldGroup {
            text: "\u{00A0}hello".to_string(),
            is_bold: true,
            first_char_in_group: Some('\u{00A0}'),
            last_char_in_group: Some('o'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&nbsp_group),
            BoldMarkerDecision::Skip(ValidatorError::InvalidOpeningBoundary)
        );
    }

    #[test]
    fn test_fix_2b_figure_space_treated_as_whitespace() {
        // Figure space (U+2007) should be treated as whitespace
        // Used in tables for alignment ~keep

        let fig_space_group = BoldGroup {
            text: "hello\u{2007}".to_string(),
            is_bold: true,
            first_char_in_group: Some('h'),
            last_char_in_group: Some('\u{2007}'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&fig_space_group),
            BoldMarkerDecision::Skip(ValidatorError::InvalidClosingBoundary)
        );
    }

    #[test]
    fn test_fix_2b_narrow_nbsp_treated_as_whitespace() {
        // Narrow no-break space (U+202F) should be treated as whitespace
        // Used in French and German typography ~keep

        let narrow_nbsp_group = BoldGroup {
            text: "hello\u{202F}world".to_string(),
            is_bold: true,
            first_char_in_group: Some('h'),
            last_char_in_group: Some('d'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&narrow_nbsp_group),
            BoldMarkerDecision::Insert
        );
    }

    #[test]
    fn test_fix_2b_ideographic_space_treated_as_whitespace() {
        // Ideographic space (U+3000) should be treated as whitespace
        // Used in Asian typesetting ~keep

        let ideo_space_group = BoldGroup {
            text: "hello\u{3000}".to_string(),
            is_bold: true,
            first_char_in_group: Some('h'),
            last_char_in_group: Some('\u{3000}'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&ideo_space_group),
            BoldMarkerDecision::Skip(ValidatorError::InvalidClosingBoundary)
        );
    }

    #[test]
    fn test_fix_2b_unicode_bom_treated_as_whitespace() {
        // Zero-width no-break space / BOM (U+FEFF) should be treated as whitespace
        // Rarely appears in PDFs but defensive against edge cases ~keep

        let bom_group = BoldGroup {
            text: "\u{FEFF}hello".to_string(),
            is_bold: true,
            first_char_in_group: Some('\u{FEFF}'),
            last_char_in_group: Some('o'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&bom_group),
            BoldMarkerDecision::Skip(ValidatorError::InvalidOpeningBoundary)
        );
    }

    #[test]
    fn test_fix_2b_has_word_content_with_unicode_whitespace() {
        let nbsp_only = BoldGroup {
            text: "\u{00A0}\u{00A0}".to_string(),
            is_bold: true,
            first_char_in_group: Some('\u{00A0}'),
            last_char_in_group: Some('\u{00A0}'),
        };
        assert!(!nbsp_only.has_word_content());

        let nbsp_mixed = BoldGroup {
            text: "\u{00A0}hello\u{00A0}".to_string(),
            is_bold: true,
            first_char_in_group: Some('\u{00A0}'),
            last_char_in_group: Some('\u{00A0}'),
        };
        assert!(nbsp_mixed.has_word_content());

        let fig_mixed = BoldGroup {
            text: "\u{2007}world\u{2007}".to_string(),
            is_bold: true,
            first_char_in_group: Some('\u{2007}'),
            last_char_in_group: Some('\u{2007}'),
        };
        assert!(fig_mixed.has_word_content());
    }

    #[test]
    fn test_fix_2b_no_empty_markers_with_unicode_spaces() {
        let unicode_only = BoldGroup {
            text: "\u{00A0}\u{2007}\u{202F}\u{3000}".to_string(),
            is_bold: true,
            first_char_in_group: Some('\u{00A0}'),
            last_char_in_group: Some('\u{3000}'),
        };

        // WhitespaceOnly is caught before boundary checks (validator
        // rejects all-whitespace content at the top level). ~keep
        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&unicode_only),
            BoldMarkerDecision::Skip(ValidatorError::WhitespaceOnly)
        );
        assert_eq!(BoldMarkerValidator::predict_markdown(&unicode_only), unicode_only.text);

        // Scenario 2: Actual content with Unicode spaces around it
        // If boundaries are trimmed, content is valid
        // (This is covered by Fix 2A tests, but here we validate boundaries don't accept Unicode spaces)
        // ~keep
        let valid_with_unicode = BoldGroup {
            text: "\u{00A0}hello\u{00A0}".to_string(),
            is_bold: true,
            first_char_in_group: Some('h'), // From trimming (Fix 2A) ~keep
            last_char_in_group: Some('o'),  // From trimming (Fix 2A) ~keep
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&valid_with_unicode),
            BoldMarkerDecision::Insert
        );
    }

    #[test]
    fn test_fix_2b_policy_pdf_scenario() {
        // Real-world scenario from policy PDFs
        // These documents often use NBSP for justified spacing and alignment ~keep

        // Anti-Bribery policy example: "Policy" followed by NBSP (for spacing) ~keep
        let policy_text = BoldGroup {
            text: "Policy\u{00A0}".to_string(),
            is_bold: true,
            first_char_in_group: Some('P'),
            last_char_in_group: Some('\u{00A0}'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&policy_text),
            BoldMarkerDecision::Skip(ValidatorError::InvalidClosingBoundary)
        );
    }

    #[test]
    fn test_fix_2b_combined_with_ascii_whitespace() {
        let combined = BoldGroup {
            text: " \u{00A0}text\u{00A0} ".to_string(),
            is_bold: true,
            first_char_in_group: Some(' '),
            last_char_in_group: Some(' '),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&combined),
            BoldMarkerDecision::Skip(ValidatorError::InvalidOpeningBoundary)
        );

        assert!(combined.has_word_content());
    }

    #[test]
    fn test_fix_2b_unicode_space_in_middle_allowed() {
        let internal_space = BoldGroup {
            text: "hello\u{00A0}world".to_string(),
            is_bold: true,
            first_char_in_group: Some('h'),
            last_char_in_group: Some('d'),
        };

        assert_eq!(
            BoldMarkerValidator::can_insert_markers(&internal_space),
            BoldMarkerDecision::Insert
        );
        assert_eq!(
            BoldMarkerValidator::predict_markdown(&internal_space),
            "**hello\u{00A0}world**"
        );
    }
}
