//! ISO 32000-1:2008 Section 9.4.4 Word Boundary Detection
//!
//! This module implements specification-compliant word boundary detection for PDF text extraction.
//! Word boundaries are identified through multiple mechanisms defined in the PDF specification:
//!
//! 1. **TJ Array Offsets** (Section 9.4.4): Character-level spacing information from text positioning
//! 2. **Geometric Positioning** (Section 9.4): Layout-based word breaking through character positions
//! 3. **Space Characters** (Section 5.3.2): Explicit word separators (U+0020 and variants)
//! 4. **Font Metrics** (Section 9.3): Character width, font size, and scaling adjustments
//! 5. **Script-Aware Detection**: CJK text, custom encodings, and special characters
//!
//! # Specification References
//!
//! - ISO 32000-1:2008 Section 9.4: Text Objects
//! - ISO 32000-1:2008 Section 9.4.3: Text Positioning Operators
//! - ISO 32000-1:2008 Section 9.4.4: Text Objects and Word Spacing
//! - ISO 32000-1:2008 Section 9.3: Text State Parameters (Tc, Tw, Tz, TL)
//! - ISO 32000-1:2008 Section 9.6-9.8: Font Metrics

#![forbid(unsafe_code)]

use crate::text::cjk_punctuation;
use crate::text::complex_script_detector::{
    ComplexScript, detect_complex_script, handle_devanagari_boundary, handle_indic_boundary, handle_khmer_boundary,
    handle_thai_boundary,
};
use crate::text::rtl_detector::should_split_at_rtl_boundary;
use crate::text::script_detector::{
    DocumentLanguage, detect_cjk_script, handle_japanese_text, handle_korean_text, should_split_on_script_transition,
};

/// Information about a character in the text stream for boundary detection.
///
/// This type captures all the information needed to determine word boundaries
/// per PDF specification Section 9.4.4.
#[derive(Clone, Debug)]
pub struct CharacterInfo {
    /// Unicode code point of the character
    pub code: u32,

    /// Glyph ID in the font (if available)
    pub glyph_id: Option<u16>,

    /// Character width in text space units (thousandths of em)
    pub width: f32,

    /// X position (horizontal) in text space
    pub x_position: f32,

    /// TJ array offset value (in thousandths of em) - negative = extra space
    /// Per spec: Negative values in TJ array increase spacing between characters
    pub tj_offset: Option<i32>,

    /// Current font size in points
    pub font_size: f32,

    /// Whether this character is a ligature (U+FB00-U+FB04)
    pub is_ligature: bool,

    /// Original ligature character if this was split from a ligature
    /// Used for debugging and tracking ligature expansion
    pub original_ligature: Option<char>,

    /// Whether this character is protected from word boundary splitting
    ///
    /// When true, word boundary detection will skip creating boundaries
    /// before or after this character. Used to preserve email addresses
    /// (`user@example.com`) and URLs (`http://example.com`) as single tokens.
    pub protected_from_split: bool,
}

/// Context information for word boundary detection.
///
/// Provides the font metrics and text state parameters that influence
/// how word boundaries are determined (per Section 9.3).
#[derive(Clone, Debug)]
pub struct BoundaryContext {
    /// Font size (Tf parameter in text state)
    pub font_size: f32,

    /// Horizontal scaling percentage (Tz parameter, default 100.0)
    pub horizontal_scaling: f32,

    /// Word spacing adjustment (Tw parameter, added after space character)
    pub word_spacing: f32,

    /// Character spacing adjustment (Tc parameter, added after every character)
    pub char_spacing: f32,
}

impl BoundaryContext {
    /// Create a new boundary context with default text state parameters.
    pub fn new(font_size: f32) -> Self {
        Self {
            font_size,
            horizontal_scaling: 100.0,
            word_spacing: 0.0,
            char_spacing: 0.0,
        }
    }

    /// Get the effective font size accounting for horizontal scaling
    fn effective_font_size(&self) -> f32 {
        self.font_size * (self.horizontal_scaling / 100.0)
    }
}

/// Document script profile for optimization.
///
/// OPTIMIZATION: Detect document primary script once,
/// then skip unnecessary script detection functions for faster boundary detection.
///
/// When documents contain only Latin text, we skip RTL and CJK detection entirely.
/// When documents are CJK-dominant, we skip RTL detection.
/// This reduces function call overhead from millions per batch to thousands.
#[allow(clippy::upper_case_acronyms)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DocumentScript {
    /// Latin-only document (ASCII + extended Latin)
    /// Fast path: only check space, TJ offset, geometric gap
    Latin,

    /// CJK-dominant document (Chinese, Japanese, Korean)
    /// Skip RTL detection, use optimized CJK path
    CJK,

    /// Right-to-left dominant (Arabic, Hebrew)
    /// Skip CJK detection, use optimized RTL path
    RTL,

    /// Complex scripts (Devanagari, Thai, Khmer, etc.)
    /// Use specialized complex script detection
    Complex,

    /// Mixed scripts or unknown
    /// Check all detection functions (slowest path)
    Mixed,
}

impl DocumentScript {
    /// Detect document script profile by sampling first 1000 characters.
    ///
    /// This optimization reduces boundary detection overhead by skipping
    /// unnecessary script detection for documents with known script profiles.
    ///
    /// PERFORMANCE: O(min(n, 1000)) sampling, executed once per extraction
    pub fn detect_from_characters(characters: &[CharacterInfo]) -> Self {
        if characters.is_empty() {
            return Self::Latin;
        }

        let mut has_rtl = false;
        let mut has_cjk = false;
        let mut has_complex = false;
        let sample_size = characters.len().min(1000);

        for ch in &characters[..sample_size] {
            if (0x0590..=0x08FF).contains(&ch.code) || (0xFB1D..=0xFDFF).contains(&ch.code) {
                has_rtl = true;
            }

            if (0x4E00..=0x9FFF).contains(&ch.code)
                || (0x3040..=0x309F).contains(&ch.code)
                || (0x30A0..=0x30FF).contains(&ch.code)
                || (0xAC00..=0xD7AF).contains(&ch.code)
            {
                // Hangul ~keep
                has_cjk = true;
            }

            // Check for complex scripts. The Brahmic South-Asian blocks
            // (Bengali, Tamil, Telugu, Kannada, Malayalam) were previously
            // absent, so those docs classified as Latin/Mixed and never reached
            // the complex-script boundary rules — leaking spurious spaces after
            // matras (an Indic gap). They share the same matra/virama
            // boundary semantics as Devanagari. ~keep
            if (0x0900..=0x097F).contains(&ch.code)
                || (0x0980..=0x09FF).contains(&ch.code)
                || (0x0B80..=0x0BFF).contains(&ch.code)
                || (0x0C00..=0x0C7F).contains(&ch.code)
                || (0x0C80..=0x0CFF).contains(&ch.code)
                || (0x0D00..=0x0D7F).contains(&ch.code)
                || (0x0E00..=0x0E7F).contains(&ch.code)
                || (0x1780..=0x17FF).contains(&ch.code)
            {
                // Khmer ~keep
                has_complex = true;
            }
        }

        #[allow(clippy::let_and_return)]
        let script = match (has_rtl, has_cjk, has_complex) {
            (false, false, false) => Self::Latin,
            (false, true, _) => Self::CJK,
            (true, false, _) => Self::RTL,
            (_, _, true) => Self::Complex,
            _ => Self::Mixed,
        };

        crate::extract_log_trace!(
            "Detected document script: {:?} (sampled {} characters)",
            script,
            sample_size
        );

        script
    }
}

/// Main word boundary detection engine.
///
/// Implements the specification-compliant word boundary detection algorithm
/// that considers TJ offsets, geometric spacing, and font metrics.
#[derive(Debug)]
pub struct WordBoundaryDetector {
    /// Threshold for TJ offset values that indicate word boundaries
    /// Default: -100 (representing 0.1em in thousand-units of em)
    tj_offset_threshold: i32,

    /// Ratio of font size to use as geometric gap threshold
    /// Default: 0.3 (30% of font size indicates a word boundary)
    geometric_gap_ratio: f32,

    /// Enable CJK-aware boundary detection
    cjk_enabled: bool,

    /// Enable script-aware transition detection
    detect_script_transitions: bool,

    /// Document language context (if known)
    document_language: Option<DocumentLanguage>,

    /// Detected document script profile (optimization)
    /// Cached at detector creation to skip unnecessary detection functions
    primary_script: DocumentScript,

    /// Enable adaptive TJ threshold calculation based on font metrics
    /// When true, uses calculate_tj_threshold() instead of static tj_offset_threshold
    /// Default: true (adaptive mode enabled)
    use_adaptive_threshold: bool,
}

impl Default for WordBoundaryDetector {
    fn default() -> Self {
        Self::new()
    }
}

impl WordBoundaryDetector {
    /// Create a new word boundary detector with default settings.
    pub fn new() -> Self {
        Self {
            tj_offset_threshold: -100,
            // Geometric gap threshold: 80% of font size
            // This is conservative enough to avoid false positives from normal character spacing
            // but sensitive enough to detect actual word breaks ~keep
            geometric_gap_ratio: 0.8,
            cjk_enabled: true,
            detect_script_transitions: true,
            document_language: None,
            primary_script: DocumentScript::Mixed,
            use_adaptive_threshold: true,
        }
    }

    /// Set the TJ offset threshold for boundary detection.
    ///
    /// Negative values in TJ arrays that are more negative than this threshold
    /// are considered word boundaries. Default: -100
    pub fn with_tj_threshold(mut self, threshold: i32) -> Self {
        self.tj_offset_threshold = threshold;
        self
    }

    /// Set the geometric gap ratio as a fraction of font size.
    ///
    /// Gaps between characters larger than (font_size * ratio) are considered
    /// word boundaries. Default: 0.3
    pub fn with_geometric_gap_ratio(mut self, ratio: f32) -> Self {
        self.geometric_gap_ratio = ratio;
        self
    }

    /// Enable or disable CJK-aware word boundary detection.
    pub fn with_cjk_enabled(mut self, enabled: bool) -> Self {
        self.cjk_enabled = enabled;
        self
    }

    /// Enable or disable script-aware transition detection.
    ///
    /// When enabled, the detector will analyze script transitions (e.g., Hiragana→Katakana)
    /// and apply language-specific rules for word boundaries.
    pub fn with_script_detection(mut self, enabled: bool) -> Self {
        self.detect_script_transitions = enabled;
        self
    }

    /// Set the document language context.
    ///
    /// This helps apply appropriate script transition rules:
    /// - Japanese: Allow Han↔Kana transitions
    /// - Korean: Allow Hangul↔Hanja transitions
    /// - Chinese: Use conservative Han character boundaries
    pub fn with_document_language(mut self, lang: DocumentLanguage) -> Self {
        self.document_language = Some(lang);
        self
    }

    /// Set the document script profile (optimization).
    ///
    /// When set, the detector will skip unnecessary script detection functions
    /// for documents with known script profiles, significantly improving performance.
    pub fn with_document_script(mut self, script: DocumentScript) -> Self {
        self.primary_script = script;
        self
    }

    /// Enable or disable adaptive TJ threshold calculation.
    ///
    /// When enabled (default), TJ offset thresholds are calculated dynamically
    /// based on font metrics (size, scaling, spacing). When disabled, uses the
    /// static threshold set via `with_tj_threshold()`.
    ///
    /// Adaptive mode provides better accuracy across documents with varying
    /// font sizes and text state parameters.
    pub fn with_adaptive_threshold(mut self, enabled: bool) -> Self {
        self.use_adaptive_threshold = enabled;
        self
    }

    /// Calculate adaptive TJ threshold based on font metrics and text state.
    ///
    /// Per PDF Spec Section 9.3, TJ array offsets depend on:
    /// - Font size (Tf): Larger fonts need larger thresholds
    /// - Character spacing (Tc): Manual spacing offsets base threshold
    /// - Word spacing (Tw): Applied after space characters
    /// - Horizontal scaling (Tz): Affects text width calculations
    ///
    /// Formula: base_threshold = -font_size * (h_scale / 100.0) * 0.025
    /// Then adjust by: -(char_spacing.abs() + word_spacing.abs()) * 0.5
    fn calculate_tj_threshold(&self, context: &BoundaryContext) -> f32 {
        let font_size = context.font_size.max(1.0);
        let h_scale = (context.horizontal_scaling / 100.0).max(0.01);

        // Base threshold as percentage of font size (2.5%)
        // 12pt font → -0.3, 24pt font → -0.6 ~keep
        let base_threshold = -font_size * h_scale * 0.025;

        let spacing_adjustment = (context.char_spacing.abs() + context.word_spacing.abs()) * 0.5;

        base_threshold - spacing_adjustment
    }

    /// Detect word boundaries in a character stream.
    ///
    /// Returns a vector of indices where word boundaries occur.
    /// A boundary at index `i` means there is a word break between
    /// characters at indices `i-1` and `i`.
    ///
    /// Per ISO 32000-1:2008 Section 9.4.4, word boundaries are determined by:
    /// 1. Space characters (U+0020, U+200B)
    /// 2. TJ array offset signals (negative values below threshold)
    /// 3. Geometric gaps exceeding font-size relative threshold
    /// 4. CJK character transitions
    ///
    /// # Arguments
    ///
    /// * `characters` - Sequence of characters with positioning information
    /// * `context` - Font metrics and text state parameters
    ///
    /// # Returns
    ///
    /// Vector of indices where word boundaries occur (between characters)
    pub fn detect_word_boundaries(&self, characters: &[CharacterInfo], context: &BoundaryContext) -> Vec<usize> {
        if characters.is_empty() {
            return Vec::new();
        }

        let mut boundaries = Vec::new();

        for i in 1..characters.len() {
            let prev_char = &characters[i - 1];
            let curr_char = &characters[i];

            if self.is_word_boundary(prev_char, curr_char, context) {
                boundaries.push(i);
            }
        }

        crate::extract_log_trace!(
            "Word boundary detection: {} boundaries in {} characters",
            boundaries.len(),
            characters.len()
        );

        boundaries
    }

    /// Determine if a word boundary exists between two consecutive characters.
    ///
    /// Implements the specification rules per ISO 32000-1:2008 Section 9.4.4:
    ///
    /// 1. **Space characters** (U+0020, U+200B): Always create boundaries
    /// 2. **TJ array offsets**: Negative values below threshold indicate spacing
    /// 3. **Geometric gaps**: Gaps larger than font-size-relative threshold
    /// 4. **CJK script transitions**: Script-aware word boundaries
    /// 5. **CJK characters**: Each non-punctuation CJK character creates boundary (legacy)
    ///
    /// # Arguments
    ///
    /// * `prev_char` - Previous character in the stream
    /// * `curr_char` - Current character
    /// * `context` - Font metrics and text state
    ///
    /// # Returns
    ///
    /// `true` if a word boundary should be placed between these characters
    fn is_word_boundary(
        &self,
        prev_char: &CharacterInfo,
        curr_char: &CharacterInfo,
        context: &BoundaryContext,
    ) -> bool {
        if prev_char.protected_from_split || curr_char.protected_from_split {
            return false;
        }

        if prev_char.code == 0x20 || prev_char.code == 0x200B {
            return true;
        }

        // OPTIMIZATION: Use script-aware dispatch to avoid unnecessary function calls
        // This reduces millions of function calls per batch by skipping detection for known script types
        // ~keep
        match self.primary_script {
            DocumentScript::Latin => self.is_word_boundary_basic(prev_char, curr_char, context),

            DocumentScript::CJK => {
                if self.detect_script_transitions
                    && let Some(decision) = self.should_split_at_cjk_boundary(prev_char, curr_char)
                {
                    return decision;
                }
                self.is_word_boundary_basic(prev_char, curr_char, context)
            }

            DocumentScript::RTL => {
                if let Some(decision) = should_split_at_rtl_boundary(prev_char, curr_char, Some(context)) {
                    return decision;
                }
                self.is_word_boundary_basic(prev_char, curr_char, context)
            }

            DocumentScript::Complex => {
                if let Some(decision) = self.should_split_at_complex_script_boundary(prev_char, curr_char) {
                    return decision;
                }
                self.is_word_boundary_basic(prev_char, curr_char, context)
            }

            DocumentScript::Mixed => {
                if let Some(decision) = should_split_at_rtl_boundary(prev_char, curr_char, Some(context)) {
                    return decision;
                }

                if self.detect_script_transitions
                    && let Some(decision) = self.should_split_at_cjk_boundary(prev_char, curr_char)
                {
                    return decision;
                }

                if let Some(decision) = self.should_split_at_complex_script_boundary(prev_char, curr_char) {
                    return decision;
                }

                self.is_word_boundary_basic(prev_char, curr_char, context)
            }
        }
    }

    /// Basic boundary detection used by all script paths.
    ///
    /// This contains the core TJ offset and geometric gap checks
    /// that apply to all scripts.
    fn is_word_boundary_basic(
        &self,
        prev_char: &CharacterInfo,
        curr_char: &CharacterInfo,
        context: &BoundaryContext,
    ) -> bool {
        if let Some(tj_offset) = prev_char.tj_offset {
            let threshold = if self.use_adaptive_threshold {
                self.calculate_tj_threshold(context)
            } else {
                self.tj_offset_threshold as f32
            };
            if (tj_offset as f32) < threshold {
                return true;
            }
        }

        if self.has_significant_geometric_gap(prev_char, curr_char, context) {
            return true;
        }

        if self.cjk_enabled
            && !self.detect_script_transitions
            && self.is_cjk_character(prev_char.code)
            && !self.is_cjk_punctuation(prev_char.code)
        {
            return true;
        }

        false
    }

    /// Determine if a complex script boundary should be created.
    ///
    /// This implements Complex Script support:
    /// - Devanagari virama and matras
    /// - Thai tone marks and vowel modifiers
    /// - Khmer COENG and vowels
    /// - Indic scripts (Tamil, Telugu, Kannada, Malayalam) diacritics
    ///
    /// # Arguments
    ///
    /// * `prev_char` - Previous character information
    /// * `curr_char` - Current character information
    ///
    /// # Returns
    ///
    /// - `Some(true)` - Must create boundary
    /// - `Some(false)` - Must not create boundary
    /// - `None` - Use other signals (TJ offset, geometry)
    fn should_split_at_complex_script_boundary(
        &self,
        prev_char: &CharacterInfo,
        curr_char: &CharacterInfo,
    ) -> Option<bool> {
        let prev_script = detect_complex_script(prev_char.code);
        let curr_script = detect_complex_script(curr_char.code);

        if prev_script.is_none() && curr_script.is_none() {
            return None;
        }

        match (prev_script, curr_script) {
            (Some(ComplexScript::Devanagari), _) | (_, Some(ComplexScript::Devanagari)) => {
                handle_devanagari_boundary(prev_char, curr_char)
            }
            (Some(ComplexScript::Thai), _) | (_, Some(ComplexScript::Thai)) => {
                handle_thai_boundary(prev_char, curr_char)
            }
            (Some(ComplexScript::Khmer), _) | (_, Some(ComplexScript::Khmer)) => {
                handle_khmer_boundary(prev_char, curr_char)
            }
            (Some(ComplexScript::Tamil), _)
            | (_, Some(ComplexScript::Tamil))
            | (Some(ComplexScript::Telugu), _)
            | (_, Some(ComplexScript::Telugu))
            | (Some(ComplexScript::Kannada), _)
            | (_, Some(ComplexScript::Kannada))
            | (Some(ComplexScript::Malayalam), _)
            | (_, Some(ComplexScript::Malayalam))
            | (Some(ComplexScript::Bengali), _)
            | (_, Some(ComplexScript::Bengali)) => handle_indic_boundary(prev_char, curr_char),
            _ => None,
        }
    }

    /// Determine if a CJK boundary should be created based on script analysis.
    ///
    /// This implements CJK script support:
    /// - CJK punctuation detection
    /// - Script type detection
    /// - Language-specific transition rules
    /// - Japanese modifier handling
    ///
    /// # Arguments
    ///
    /// * `prev_char` - Previous character information
    /// * `curr_char` - Current character information
    ///
    /// # Returns
    ///
    /// - `Some(true)` - Must create boundary
    /// - `Some(false)` - Must not create boundary
    /// - `None` - Use other signals (TJ offset, geometry)
    fn should_split_at_cjk_boundary(&self, prev_char: &CharacterInfo, curr_char: &CharacterInfo) -> Option<bool> {
        // Check CJK punctuation (always creates boundary with high confidence)
        // Note: Using None for density to maintain current behavior
        // Future: Could integrate document-wide density measurement here ~keep
        let prev_punctuation_score = cjk_punctuation::get_cjk_punctuation_boundary_score(prev_char.code, None);
        if prev_punctuation_score >= 0.9 {
            // Sentence-ending and enumeration punctuation create boundaries ~keep
            return Some(true);
        }

        let prev_script = detect_cjk_script(prev_char.code);
        let curr_script = detect_cjk_script(curr_char.code);

        if prev_script.is_none() && curr_script.is_none() {
            return None;
        }

        match self.document_language {
            Some(DocumentLanguage::Japanese) => handle_japanese_text(prev_char, curr_char, prev_script, curr_script),
            Some(DocumentLanguage::Korean) => handle_korean_text(prev_char, curr_char, prev_script, curr_script),
            Some(DocumentLanguage::Chinese) | None => {
                should_split_on_script_transition(prev_script, curr_script, self.document_language)
            }
        }
    }

    /// Check if a gap is internal to a ligature expansion.
    ///
    /// When a ligature like 'fi' (U+FB01) is expanded into 'f' + 'i',
    /// the geometric gap between expanded components should not create a word boundary.
    fn is_ligature_internal_gap(&self, prev_char: &CharacterInfo, curr_char: &CharacterInfo) -> bool {
        // Ligature Unicode range: U+FB00-U+FB06 ~keep
        const LIGATURES: [u32; 7] = [0xFB00, 0xFB01, 0xFB02, 0xFB03, 0xFB04, 0xFB05, 0xFB06];

        LIGATURES.contains(&prev_char.code)
            || prev_char.is_ligature
            || LIGATURES.contains(&curr_char.code)
            || curr_char.is_ligature
    }

    /// Check if a character code represents punctuation that attaches to words.
    ///
    /// Punctuation like periods, commas, colons should use reduced threshold
    /// to avoid creating unwanted boundaries when appearing after words.
    pub fn is_punctuation(code: u32) -> bool {
        matches!(
            code,
            0x21
            | 0x22
            | 0x27
            | 0x2C
            | 0x2E
            | 0x3A
            | 0x3B
            | 0x3F
            | 0x2018..=0x201F
            | 0x2010..=0x2015
        )
    }

    /// Check if there is a significant geometric gap between two characters.
    ///
    /// Per Section 9.4, character positions and widths determine visual spacing.
    /// A gap larger than the threshold (font_size * ratio) indicates a word boundary.
    ///
    /// Special cases:
    /// 1. **Ligature internal gaps**: Gaps inside expanded ligatures never create boundaries
    /// 2. **Punctuation attachment**: Punctuation uses 50% threshold to attach to preceding words
    /// 3. **Character spacing**: Tc parameter adjusts baseline gap calculation
    fn has_significant_geometric_gap(
        &self,
        prev_char: &CharacterInfo,
        curr_char: &CharacterInfo,
        context: &BoundaryContext,
    ) -> bool {
        if self.is_ligature_internal_gap(prev_char, curr_char) {
            return false;
        }

        let prev_end_x = prev_char.x_position + prev_char.width;

        let raw_gap = curr_char.x_position - prev_end_x;

        // Adjust for character spacing (Tc parameter)
        // Tc is added after every character, so subtract it from the gap ~keep
        let adjusted_gap = raw_gap - context.char_spacing;

        let base_threshold = context.effective_font_size() * self.geometric_gap_ratio;

        if Self::is_punctuation(curr_char.code) {
            return adjusted_gap > (base_threshold * 0.5);
        }

        adjusted_gap > base_threshold
    }

    /// Check if a character code represents a CJK (Chinese/Japanese/Korean) character.
    ///
    /// CJK Unicode ranges per Unicode Standard:
    /// - CJK Unified Ideographs: U+4E00-U+9FFF
    /// - CJK Unified Ideographs Extension A: U+3400-U+4DBF
    /// - CJK Unified Ideographs Extension B and beyond: higher ranges
    /// - Hiragana: U+3040-U+309F
    /// - Katakana: U+30A0-U+30FF
    fn is_cjk_character(&self, code: u32) -> bool {
        matches!(
            code,
            0x3040..=0x309F
            | 0x30A0..=0x30FF
            | 0x3400..=0x4DBF
            | 0x4E00..=0x9FFF
            | 0x20000..=0x2A6DF
            | 0x2A700..=0x2B73F
            | 0x2B740..=0x2B81F
            | 0x2B820..=0x2CEAF
            | 0x2CEB0..=0x2EBEF
        )
    }

    /// Check if a character is CJK punctuation that attaches to words.
    ///
    /// CJK punctuation like ideographic commas and periods attach to the preceding
    /// word and should not create boundaries.
    fn is_cjk_punctuation(&self, code: u32) -> bool {
        matches!(
            code,
            0x3001
                | 0x3002
                | 0x3008
                | 0x3009
                | 0x300A
                | 0x300B
                | 0x300C
                | 0x300D
                | 0x300E
                | 0x300F
                | 0x3010
                | 0x3011
                | 0x3014
                | 0x3015
        )
    }
}

/// Detect word boundaries in a character stream.
///
/// This is a convenience function that creates a detector with default settings
/// and performs boundary detection in one call.
///
/// # Arguments
///
/// * `characters` - Sequence of characters with positioning information
/// * `context` - Font metrics and text state parameters
///
/// # Returns
///
/// Vector of indices where word boundaries occur
pub fn detect_word_boundaries(characters: &[CharacterInfo], context: &BoundaryContext) -> Vec<usize> {
    let detector = WordBoundaryDetector::new();
    detector.detect_word_boundaries(characters, context)
}

#[cfg(test)]
mod tests;
