//! Citation reference detection and preservation.
//!
//! This module detects common citation formats in text and preserves their integrity
//! to prevent corruption or fragmentation during text processing.

use regex::Regex;
use std::sync::OnceLock;

/// Citation type enumeration.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CitationType {
    /// Numeric citations like \[1\], (1), or superscript
    Numeric,
    /// Author-year citations like (Smith, 2020) or Smith (2020)
    AuthorYear,
    /// Combined format like [Smith et al., 2020]
    Combined,
    /// Range citations like [1-3]
    Range,
}

/// A detected citation in text.
#[derive(Debug, Clone)]
pub struct Citation {
    /// The citation text itself
    pub text: String,
    /// Starting position in text
    pub position: usize,
    /// Type of citation
    pub citation_type: CitationType,
}

/// Detects and preserves citation references in text.
#[derive(Debug, Clone)]
pub struct CitationDetector;

impl CitationDetector {
    /// Create a new citation detector.
    pub fn new() -> Self {
        Self
    }

    /// Detect citations in text.
    ///
    /// Returns a vector of detected citations with their positions and types.
    pub fn detect_citations(&self, text: &str) -> Vec<Citation> {
        let mut citations = Vec::new();

        citations.extend(self.detect_numeric_citations(text));

        citations.extend(self.detect_author_year_citations(text));

        citations.extend(self.detect_combined_citations(text));

        citations.sort_by_key(|c| c.position);

        citations.dedup_by_key(|c| c.position);

        citations
    }

    /// Preserve citations by ensuring they're not split or corrupted.
    ///
    /// # Arguments
    ///
    /// * `text` - Original text
    /// * `citations` - Detected citations
    ///
    /// # Returns
    ///
    /// Text with citations preserved and normalized
    pub fn preserve_citations(&self, text: &str, citations: &[Citation]) -> String {
        if citations.is_empty() {
            return text.to_string();
        }

        let mut result = text.to_string();

        for citation in citations {
            if citation.text.contains(|c: char| c.is_alphabetic()) {
                continue; // Don't normalize author names ~keep
            }

            if let Some(normalized) = self.normalize_numeric_citation(&citation.text) {
                result = result.replace(&citation.text, &normalized);
            }
        }

        result
    }

    /// Normalize spacing in numeric citations like [  1  ] → [1]
    fn normalize_numeric_citation(&self, text: &str) -> Option<String> {
        if text.starts_with('[') && text.ends_with(']') {
            let inner = text[1..text.len() - 1].trim();
            Some(format!("[{}]", inner))
        } else if text.starts_with('(') && text.ends_with(')') {
            let inner = text[1..text.len() - 1].trim();
            if inner.chars().all(|c| c.is_numeric() || c == '-') {
                Some(format!("({})", inner))
            } else {
                None
            }
        } else {
            None
        }
    }

    /// Detect numeric citations like [1], (23), 1-3.
    fn detect_numeric_citations(&self, text: &str) -> Vec<Citation> {
        let mut citations = Vec::new();

        if let Some(regex) = get_numeric_bracket_regex() {
            for m in regex.find_iter(text) {
                citations.push(Citation {
                    text: m.as_str().to_string(),
                    position: m.start(),
                    citation_type: if m.as_str().contains('-') {
                        CitationType::Range
                    } else {
                        CitationType::Numeric
                    },
                });
            }
        }

        if let Some(regex) = get_numeric_paren_regex() {
            for m in regex.find_iter(text) {
                // Avoid detecting years or random numbers ~keep
                if !self.is_likely_year(m.as_str()) {
                    citations.push(Citation {
                        text: m.as_str().to_string(),
                        position: m.start(),
                        citation_type: CitationType::Numeric,
                    });
                }
            }
        }

        if let Some(regex) = get_superscript_regex() {
            for m in regex.find_iter(text) {
                citations.push(Citation {
                    text: m.as_str().to_string(),
                    position: m.start(),
                    citation_type: CitationType::Numeric,
                });
            }
        }

        citations
    }

    /// Detect author-year citations like (Smith, 2020) or Smith (2020).
    fn detect_author_year_citations(&self, text: &str) -> Vec<Citation> {
        let mut citations = Vec::new();

        if let Some(regex) = get_author_year_regex() {
            for m in regex.find_iter(text) {
                citations.push(Citation {
                    text: m.as_str().to_string(),
                    position: m.start(),
                    citation_type: CitationType::AuthorYear,
                });
            }
        }

        citations
    }

    /// Detect combined format citations like [Smith et al., 2020].
    fn detect_combined_citations(&self, text: &str) -> Vec<Citation> {
        let mut citations = Vec::new();

        if let Some(regex) = get_combined_regex() {
            for m in regex.find_iter(text) {
                citations.push(Citation {
                    text: m.as_str().to_string(),
                    position: m.start(),
                    citation_type: CitationType::Combined,
                });
            }
        }

        citations
    }

    /// Check if text is likely a year rather than a citation.
    fn is_likely_year(&self, text: &str) -> bool {
        text.trim_matches(|c: char| !c.is_numeric()).len() == 4
    }
}

impl Default for CitationDetector {
    fn default() -> Self {
        Self::new()
    }
}

static NUMERIC_BRACKET_REGEX: OnceLock<Option<Regex>> = OnceLock::new();
static NUMERIC_PAREN_REGEX: OnceLock<Option<Regex>> = OnceLock::new();
static SUPERSCRIPT_REGEX: OnceLock<Option<Regex>> = OnceLock::new();
static AUTHOR_YEAR_REGEX: OnceLock<Option<Regex>> = OnceLock::new();
static COMBINED_REGEX: OnceLock<Option<Regex>> = OnceLock::new();

fn get_numeric_bracket_regex() -> Option<&'static Regex> {
    NUMERIC_BRACKET_REGEX
        .get_or_init(|| Regex::new(r"\[\s*\d+(?:-\d+)?\s*\]").ok())
        .as_ref()
}

fn get_numeric_paren_regex() -> Option<&'static Regex> {
    NUMERIC_PAREN_REGEX.get_or_init(|| Regex::new(r"\(\d+\)").ok()).as_ref()
}

fn get_superscript_regex() -> Option<&'static Regex> {
    SUPERSCRIPT_REGEX
        .get_or_init(|| Regex::new(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+").ok())
        .as_ref()
}

fn get_author_year_regex() -> Option<&'static Regex> {
    AUTHOR_YEAR_REGEX
        .get_or_init(|| {
            Regex::new(
                r"\([A-Z][a-z]+(?:,?\s+and\s+[A-Z][a-z]+)?,?\s*\d{4}\)|[A-Z][a-z]+\s*\(\d{4}\)|[A-Z][a-z]+,\s*\d{4}",
            )
            .ok()
        })
        .as_ref()
}

fn get_combined_regex() -> Option<&'static Regex> {
    COMBINED_REGEX
        .get_or_init(|| Regex::new(r"\[[A-Z][a-z]+(?:\s+et\s+al\.?)?,?\s*\d{4}\]").ok())
        .as_ref()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_numeric_bracket() {
        let detector = CitationDetector::new();
        let text = "Text [1] here";
        let citations = detector.detect_citations(text);
        assert!(!citations.is_empty());
    }
}
