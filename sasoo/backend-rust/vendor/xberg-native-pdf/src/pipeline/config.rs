//! Unified configuration for the text extraction pipeline.
//!
//! This module consolidates configuration that was previously scattered across:
//! - TextExtractionConfig
//! - SpanMergingConfig
//! - SpacingConfig
//! - ConversionOptions

/// Logging detail level for extraction pipeline.
///
/// Controls the verbosity of logging output during text extraction.
/// Logging is written to stderr.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum LogLevel {
    /// Only critical errors are logged
    Error,
    /// Warnings and errors are logged
    Warn,
    /// General information (default level)
    #[default]
    Info,
    /// Detailed debug information for troubleshooting
    Debug,
    /// Very detailed trace information (character-level details)
    Trace,
}

/// Document type classification for optimized extraction settings.
///
/// Different document types have different characteristics that benefit from
/// tuned extraction parameters:
/// - Academic: Dense text, special characters, equations
/// - Business: Tables, formal structure, headers/footers
/// - Novel: Long narrative, simple formatting, chapters
/// - CJK: Chinese/Japanese/Korean text with special boundary rules
/// - RTL: Arabic/Hebrew with right-to-left text flow
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DocumentType {
    /// Academic papers, theses, technical documents
    /// Characteristics: Dense text, many special characters, equations, citations
    /// Optimizations: Aggressive hyphenation, strict spacing, preserve formatting
    Academic,

    /// Business documents, reports, contracts
    /// Characteristics: Formal structure, tables, headers/footers, multi-column
    /// Optimizations: Table detection, header preservation, justified text
    Business,

    /// Novels, books, creative content
    /// Characteristics: Long narrative, simple formatting, chapters
    /// Optimizations: Relaxed spacing, chapter detection, paragraph preservation
    Novel,

    /// CJK documents: Chinese, Japanese, Korean
    /// Characteristics: Different word boundaries, no spaces, special punctuation
    /// Optimizations: CJK-aware boundaries, density-adaptive scoring, custom punctuation
    Cjk,

    /// RTL documents: Arabic, Hebrew
    /// Characteristics: Right-to-left text flow, special diacritics, ligatures
    /// Optimizations: RTL detection, diacritic handling, ligature support
    Rtl,

    /// Generic/unknown documents - balanced defaults
    Generic,
}

impl DocumentType {
    /// Create optimized TextPipelineConfig for this document type
    pub fn create_config(&self) -> TextPipelineConfig {
        match self {
            Self::Academic => Self::academic_config(),
            Self::Business => Self::business_config(),
            Self::Novel => Self::novel_config(),
            Self::Cjk => Self::cjk_config(),
            Self::Rtl => Self::rtl_config(),
            Self::Generic => TextPipelineConfig::default(),
        }
    }

    fn academic_config() -> TextPipelineConfig {
        TextPipelineConfig {
            spacing: SpacingConfig { word_margin: 0.1 },
            tj_threshold: TjThresholdConfig {
                space_insertion_threshold: -120.0,
                use_adaptive: true,
            },
            reading_order: ReadingOrderConfig {
                strategy: ReadingOrderStrategyType::StructureTreeFirst,
            },
            output: OutputConfig {
                detect_headings: false,
                include_images: false,
                bold_marker_behavior: BoldMarkerBehavior::Conservative,
                preserve_layout: true,
                extract_tables: true,
                image_output_dir: None,
                embed_images: true,
                include_form_fields: true,
                include_artifacts: true,
            },
            word_boundary_mode: WordBoundaryMode::Primary,
            enable_hyphenation_reconstruction: true,
            log_level: LogLevel::Info,
            collect_metrics: false,
        }
    }

    fn business_config() -> TextPipelineConfig {
        TextPipelineConfig {
            spacing: SpacingConfig { word_margin: 0.1 },
            tj_threshold: TjThresholdConfig {
                space_insertion_threshold: -120.0,
                use_adaptive: true,
            },
            reading_order: ReadingOrderConfig {
                strategy: ReadingOrderStrategyType::XYCut,
            },
            output: OutputConfig {
                detect_headings: false,
                include_images: false,
                bold_marker_behavior: BoldMarkerBehavior::Conservative,
                preserve_layout: true, // Headers/footers matter ~keep
                extract_tables: true,  // Essential for reports ~keep
                image_output_dir: None,
                embed_images: true,
                include_form_fields: true,
                include_artifacts: true,
            },
            word_boundary_mode: WordBoundaryMode::Primary,
            enable_hyphenation_reconstruction: true,
            log_level: LogLevel::Info,
            collect_metrics: false,
        }
    }

    fn novel_config() -> TextPipelineConfig {
        TextPipelineConfig {
            spacing: SpacingConfig { word_margin: 0.15 },
            tj_threshold: TjThresholdConfig {
                space_insertion_threshold: -100.0,
                use_adaptive: false,
            },
            reading_order: ReadingOrderConfig {
                strategy: ReadingOrderStrategyType::Simple,
            },
            output: OutputConfig {
                detect_headings: false,
                include_images: false,
                bold_marker_behavior: BoldMarkerBehavior::Conservative,
                preserve_layout: false,
                extract_tables: false,
                image_output_dir: None,
                embed_images: true,
                include_form_fields: true,
                include_artifacts: true,
            },
            word_boundary_mode: WordBoundaryMode::Tiebreaker,
            enable_hyphenation_reconstruction: true, // Essential for novels ~keep
            log_level: LogLevel::Info,
            collect_metrics: false,
        }
    }

    fn cjk_config() -> TextPipelineConfig {
        TextPipelineConfig {
            spacing: SpacingConfig { word_margin: 0.05 }, // Tighter for CJK ~keep
            tj_threshold: TjThresholdConfig {
                space_insertion_threshold: -80.0, // CJK-aware ~keep
                use_adaptive: true,
            },
            reading_order: ReadingOrderConfig {
                strategy: ReadingOrderStrategyType::StructureTreeFirst,
            },
            output: OutputConfig {
                detect_headings: false,
                include_images: false,
                bold_marker_behavior: BoldMarkerBehavior::Conservative,
                preserve_layout: true,
                extract_tables: true,
                image_output_dir: None,
                embed_images: true,
                include_form_fields: true,
                include_artifacts: true,
            },
            word_boundary_mode: WordBoundaryMode::Primary,
            enable_hyphenation_reconstruction: false, // Not applicable to CJK ~keep
            log_level: LogLevel::Info,
            collect_metrics: false,
        }
    }

    fn rtl_config() -> TextPipelineConfig {
        TextPipelineConfig {
            spacing: SpacingConfig { word_margin: 0.1 },
            tj_threshold: TjThresholdConfig {
                space_insertion_threshold: -120.0,
                use_adaptive: true,
            },
            reading_order: ReadingOrderConfig {
                strategy: ReadingOrderStrategyType::StructureTreeFirst,
            },
            output: OutputConfig {
                detect_headings: false,
                include_images: false,
                bold_marker_behavior: BoldMarkerBehavior::Conservative,
                preserve_layout: true,
                extract_tables: true,
                image_output_dir: None,
                embed_images: true,
                include_form_fields: true,
                include_artifacts: true,
            },
            word_boundary_mode: WordBoundaryMode::Tiebreaker,
            enable_hyphenation_reconstruction: false,
            log_level: LogLevel::Info,
            collect_metrics: false,
        }
    }

    /// Detect document type from text sample
    ///
    /// Examines first 1000 characters to classify document
    pub fn detect_from_sample(sample: &str) -> Self {
        if sample.is_empty() {
            return Self::Generic;
        }

        let cjk_ratio = Self::count_cjk_chars(sample) as f32 / sample.len() as f32;
        let rtl_ratio = Self::count_rtl_chars(sample) as f32 / sample.len() as f32;
        let special_ratio = Self::count_special_chars(sample) as f32 / sample.len() as f32;

        if cjk_ratio > 0.1 {
            return Self::Cjk;
        }

        if rtl_ratio > 0.2 {
            return Self::Rtl;
        }

        if Self::looks_like_business(sample) {
            return Self::Business;
        }

        // Academic if high special character count (equations, citations, etc.) ~keep
        if special_ratio >= 0.08 {
            return Self::Academic;
        }

        if Self::looks_like_narrative(sample) {
            return Self::Novel;
        }

        Self::Generic
    }

    fn count_cjk_chars(text: &str) -> usize {
        text.chars()
            .filter(|c| {
                let code = *c as u32;
                matches!(
                    code,
                    0x3040..=0x309F   // Hiragana ~keep
                    | 0x30A0..=0x30FF // Katakana ~keep
                    | 0x3400..=0x4DBF // CJK Ext A ~keep
                    | 0x4E00..=0x9FFF // CJK ~keep
                    | 0xAC00..=0xD7AF // Hangul (Korean) ~keep
                )
            })
            .count()
    }

    fn count_rtl_chars(text: &str) -> usize {
        text.chars()
            .filter(|c| {
                let code = *c as u32;
                matches!(
                    code,
                    0x0590..=0x05FF   // Hebrew ~keep
                    | 0x0600..=0x06FF // Arabic ~keep
                    | 0x0750..=0x077F // Arabic Supplement ~keep
                )
            })
            .count()
    }

    fn count_special_chars(text: &str) -> usize {
        text.chars()
            .filter(|c| {
                matches!(
                    *c,
                    '©' | '®'
                        | '™'
                        | '§'
                        | '¶'
                        | '†'
                        | '‡'
                        | '€'
                        | '£'
                        | '¥'
                        | '¢'
                        | '±'
                        | '×'
                        | '÷'
                        | '√'
                        | '∞'
                        | '∫'
                        | '←'
                        | '→'
                        | '↑'
                        | '↓'
                        | '°'
                        | '′'
                        | '″'
                )
            })
            .count()
    }

    fn looks_like_narrative(text: &str) -> bool {
        let lower_count = text.chars().filter(|c| c.is_lowercase()).count();
        let upper_count = text.chars().filter(|c| c.is_uppercase()).count();
        let digit_count = text.chars().filter(|c| c.is_ascii_digit()).count();

        let period_count = text.matches('.').count();
        let has_narrative_words = text.contains("was ")
            || text.contains("were ")
            || text.contains("walked ")
            || text.contains("said ")
            || text.contains("went ");

        lower_count > upper_count * 5 && digit_count < text.len() / 20 && (has_narrative_words || period_count > 2)
    }

    fn looks_like_business(text: &str) -> bool {
        text.contains("Table")
            || text.contains("Figure")
            || text.contains("report")
            || text.contains("document")
            || text.contains("agreement")
    }
}

impl LogLevel {
    /// Check if a message at the given level should be logged.
    ///
    /// This is used internally by logging macros to determine whether
    /// to actually emit log output.
    pub fn should_log(&self, level: LogLevel) -> bool {
        match (*self, level) {
            (Self::Error, Self::Error) => true,
            (Self::Warn, Self::Error | Self::Warn) => true,
            (Self::Info, Self::Error | Self::Warn | Self::Info) => true,
            (Self::Debug, Self::Error | Self::Warn | Self::Info | Self::Debug) => true,
            (Self::Trace, _) => true,
            _ => false,
        }
    }
}

/// Word boundary detection mode for TJ array processing.
///
/// Per ISO 32000-1:2008 Section 9.4.4, word boundaries can be detected
/// using multiple signals (TJ offsets, geometric gaps, character properties).
///
/// Tiebreaker mode (default): Uses WordBoundaryDetector only when TJ offset
/// and geometric signals contradict each other (backward compatible).
///
/// Primary mode: Uses WordBoundaryDetector to detect boundaries BEFORE creating
/// TextSpans, partitioning the tj_character_array into word-level clusters.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum WordBoundaryMode {
    /// Use WordBoundaryDetector only as tiebreaker (backward compatible, default)
    #[default]
    Tiebreaker,
    /// Use WordBoundaryDetector as primary detector before span creation
    Primary,
}

/// Unified configuration for the text extraction pipeline.
///
/// This replaces the scattered configuration across multiple modules
/// and provides a single configuration point for the entire pipeline.
#[derive(Debug, Clone)]
pub struct TextPipelineConfig {
    /// Spacing configuration for span merging
    pub spacing: SpacingConfig,

    /// TJ offset threshold configuration
    pub tj_threshold: TjThresholdConfig,

    /// Reading order strategy to use
    pub reading_order: ReadingOrderConfig,

    /// Output formatting options
    pub output: OutputConfig,

    /// Word boundary detection mode for TJ array processing (Phase 9.2)
    pub word_boundary_mode: WordBoundaryMode,

    /// Enable hyphenation reconstruction
    /// When true, hyphenated words at line breaks are reconstructed
    pub enable_hyphenation_reconstruction: bool,

    /// Logging detail level for the extraction pipeline
    pub log_level: LogLevel,

    /// Enable metrics collection during extraction
    pub collect_metrics: bool,
}

impl Default for TextPipelineConfig {
    fn default() -> Self {
        Self {
            spacing: SpacingConfig::default(),
            tj_threshold: TjThresholdConfig::default(),
            reading_order: ReadingOrderConfig::default(),
            output: OutputConfig::default(),
            word_boundary_mode: WordBoundaryMode::default(),
            enable_hyphenation_reconstruction: true,
            log_level: LogLevel::default(),
            collect_metrics: false,
        }
    }
}

impl TextPipelineConfig {
    /// Create config for a specific document type
    ///
    /// # Examples
    ///
    /// ```ignore
    /// use xberg_native_pdf::pipeline::config::{TextPipelineConfig, DocumentType};
    ///
    /// let config = TextPipelineConfig::for_document_type(DocumentType::Academic);
    /// ```
    pub fn for_document_type(doc_type: DocumentType) -> Self {
        doc_type.create_config()
    }

    /// Detect document type from text sample and create optimized config
    ///
    /// Analyzes the first portion of text to classify the document type,
    /// then returns a configuration optimized for that type.
    ///
    /// # Examples
    ///
    /// ```ignore
    /// use xberg_native_pdf::pipeline::config::TextPipelineConfig;
    ///
    /// let sample = "これは日本語です。";
    /// let config = TextPipelineConfig::detect_and_optimize(sample);
    /// ```
    pub fn detect_and_optimize(sample: &str) -> Self {
        let doc_type = DocumentType::detect_from_sample(sample);
        doc_type.create_config()
    }

    /// Create config with pdfplumber-compatible defaults.
    ///
    /// Uses word_margin = 0.1 and simple reading order.
    pub fn pdfplumber_compatible() -> Self {
        Self {
            spacing: SpacingConfig { word_margin: 0.1 },
            tj_threshold: TjThresholdConfig {
                space_insertion_threshold: -120.0,
                use_adaptive: false,
            },
            reading_order: ReadingOrderConfig {
                strategy: ReadingOrderStrategyType::Simple,
            },
            output: OutputConfig::default(),
            word_boundary_mode: WordBoundaryMode::Tiebreaker,
            enable_hyphenation_reconstruction: true,
            log_level: LogLevel::default(),
            collect_metrics: false,
        }
    }

    /// Create from legacy ConversionOptions for backwards compatibility.
    ///
    /// Maps old `ConversionOptions` to new `TextPipelineConfig` to maintain
    /// backwards compatibility while migrating to the new pipeline architecture.
    ///
    /// # Examples
    ///
    /// ```ignore
    /// use xberg_native_pdf::converters::ConversionOptions;
    /// use xberg_native_pdf::pipeline::config::TextPipelineConfig;
    ///
    /// let options = ConversionOptions::default();
    /// let config = TextPipelineConfig::from_conversion_options(&options);
    /// ```
    pub fn from_conversion_options(opts: &crate::converters::ConversionOptions) -> Self {
        use crate::converters::BoldMarkerBehavior as OldBMB;
        use crate::converters::ReadingOrderMode;

        let strategy = match &opts.reading_order_mode {
            ReadingOrderMode::TopToBottomLeftToRight => ReadingOrderStrategyType::Simple,
            ReadingOrderMode::ColumnAware => ReadingOrderStrategyType::XYCut,
            ReadingOrderMode::StructureTreeFirst { .. } => ReadingOrderStrategyType::StructureTreeFirst,
        };

        // Map BoldMarkerBehavior enum (both have same variants) ~keep
        let bold_marker_behavior = match opts.bold_marker_behavior {
            OldBMB::Aggressive => BoldMarkerBehavior::Aggressive,
            OldBMB::Conservative => BoldMarkerBehavior::Conservative,
        };

        Self {
            spacing: SpacingConfig::default(),
            tj_threshold: TjThresholdConfig::default(),
            reading_order: ReadingOrderConfig { strategy },
            output: OutputConfig {
                detect_headings: opts.detect_headings,
                include_images: opts.include_images,
                bold_marker_behavior,
                preserve_layout: opts.preserve_layout,
                extract_tables: opts.extract_tables,
                image_output_dir: opts.image_output_dir.clone(),
                embed_images: opts.embed_images,
                include_form_fields: opts.include_form_fields,
                include_artifacts: opts.include_artifacts,
            },
            word_boundary_mode: WordBoundaryMode::Tiebreaker, // Keep old behavior compatible ~keep
            enable_hyphenation_reconstruction: true,
            log_level: LogLevel::default(),
            collect_metrics: false,
        }
    }

    /// Set the word boundary detection mode (Phase 9.2)
    pub fn with_word_boundary_mode(mut self, mode: WordBoundaryMode) -> Self {
        self.word_boundary_mode = mode;
        self
    }

    /// Set whether to enable hyphenation reconstruction.
    ///
    /// When enabled, hyphenated words at line breaks are reconstructed
    /// (e.g., "govern-" + "ment" becomes "government").
    ///
    /// # Arguments
    ///
    /// * `enabled` - true to enable hyphenation reconstruction (default)
    pub fn with_hyphenation_reconstruction(mut self, enabled: bool) -> Self {
        self.enable_hyphenation_reconstruction = enabled;
        self
    }

    /// Set the logging detail level for the extraction pipeline.
    ///
    /// # Arguments
    ///
    /// * `level` - The logging level to use
    ///
    /// # Examples
    ///
    /// ```ignore
    /// use xberg_native_pdf::pipeline::config::{TextPipelineConfig, LogLevel};
    ///
    /// let config = TextPipelineConfig::default()
    ///     .with_log_level(LogLevel::Debug);
    /// ```
    pub fn with_log_level(mut self, level: LogLevel) -> Self {
        self.log_level = level;
        self
    }

    /// Enable metrics collection during extraction.
    ///
    /// When enabled, the extraction pipeline will collect detailed metrics
    /// about the extraction process for quality tracking and analysis.
    ///
    /// # Arguments
    ///
    /// * `enabled` - true to enable metrics collection
    ///
    /// # Examples
    ///
    /// ```ignore
    /// use xberg_native_pdf::pipeline::config::TextPipelineConfig;
    ///
    /// let config = TextPipelineConfig::default()
    ///     .with_metrics_collection(true);
    /// ```
    pub fn with_metrics_collection(mut self, enabled: bool) -> Self {
        self.collect_metrics = enabled;
        self
    }
}

#[cfg(test)]
mod tests;

/// Configuration for geometric spacing decisions.
///
/// Controls how gaps between text spans are interpreted.
#[derive(Debug, Clone, Copy)]
pub struct SpacingConfig {
    /// Word margin as ratio of character size.
    ///
    /// If the gap between spans is less than this ratio times the average
    /// character width, they are considered part of the same word.
    ///
    /// Default: 0.1 (pdfplumber default)
    pub word_margin: f32,
}

impl Default for SpacingConfig {
    fn default() -> Self {
        Self { word_margin: 0.1 }
    }
}

/// Configuration for TJ offset threshold.
///
/// Controls how TJ array offsets are interpreted for word boundary detection.
#[derive(Debug, Clone)]
pub struct TjThresholdConfig {
    /// Static threshold for TJ offsets (in text space units).
    ///
    /// Offsets more negative than this value indicate a word boundary.
    /// Default: -120.0 (pdfplumber default)
    pub space_insertion_threshold: f32,

    /// Whether to use adaptive threshold based on font metrics.
    ///
    /// When true, the threshold is computed dynamically based on
    /// the statistical distribution of gaps in the document.
    pub use_adaptive: bool,
}

impl Default for TjThresholdConfig {
    fn default() -> Self {
        Self {
            space_insertion_threshold: -120.0,
            use_adaptive: false,
        }
    }
}

/// Configuration for reading order strategy.
#[derive(Debug, Clone)]
pub struct ReadingOrderConfig {
    /// The reading order strategy to use for horizontal (left-to-right,
    /// top-to-bottom) pages.
    ///
    /// **Vertical-writing override.** When a page is detected as
    /// vertical-majority — at least half of the page's spans carry
    /// `wmode == 1` from a `/WMode 1` CMap or a `-V`-suffixed encoding
    /// (Identity-V, UniJIS-UTF16-V, …) — the configured strategy is
    /// bypassed and the page is routed through a tategaki-aware
    /// right-to-left column ordering instead. None of the four
    /// horizontal strategies (`Simple`, `Geometric`, `XYCut`,
    /// `StructureTreeFirst`) can produce correct right-to-left column
    /// order for vertical writing, so the override is unconditional.
    /// Per-span `wmode` is preserved on every output span regardless of
    /// which path the page took, so downstream consumers can still
    /// distinguish the two modes.
    pub strategy: ReadingOrderStrategyType,
}

impl Default for ReadingOrderConfig {
    fn default() -> Self {
        Self {
            strategy: ReadingOrderStrategyType::StructureTreeFirst,
        }
    }
}

/// Available reading order strategy types.
///
/// All four variants are horizontal (left-to-right, top-to-bottom)
/// strategies. Vertical-majority (tategaki) pages bypass the configured
/// variant entirely — see [`ReadingOrderConfig::strategy`] for the
/// override rule.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReadingOrderStrategyType {
    /// Use structure tree MCIDs for reading order, fallback to geometric.
    ///
    /// This is the PDF-spec-compliant approach for Tagged PDFs
    /// (ISO 32000-1:2008 Section 14.7).
    StructureTreeFirst,

    /// Column-aware geometric analysis.
    ///
    /// Uses horizontal gap detection to identify columns and
    /// processes each column top-to-bottom.
    Geometric,

    /// Recursive XY-Cut spatial partitioning.
    ///
    /// Uses projection profiles to detect columns in complex layouts
    /// like newspapers and academic papers. More sophisticated than
    /// simple gap detection (ISO 32000-1:2008 Section 9.4).
    XYCut,

    /// Simple top-to-bottom, left-to-right ordering.
    ///
    /// Sorts spans by Y coordinate (descending) then X coordinate (ascending).
    Simple,
}

/// Output formatting configuration.
#[derive(Debug, Clone)]
pub struct OutputConfig {
    /// Whether to detect and format headings.
    ///
    /// When true, larger text is formatted as markdown headings.
    /// Default: false (disabled for PDF spec compliance)
    pub detect_headings: bool,

    /// Whether to include images in output.
    pub include_images: bool,

    /// Bold marker behavior for whitespace-only spans.
    pub bold_marker_behavior: BoldMarkerBehavior,

    /// Preserve document layout using whitespace (Markdown) or CSS positioning (HTML).
    ///
    /// When enabled:
    /// - Markdown converter preserves column alignment via whitespace
    /// - HTML converter uses CSS `position:absolute` for spatial preservation
    /// - Plain text converter preserves spacing
    ///
    /// Default: false
    pub preserve_layout: bool,

    /// Extract table structures and format as markdown tables or HTML tables.
    ///
    /// When enabled:
    /// - Grid-aligned text is detected and formatted as tables
    /// - Markdown converter outputs markdown table syntax
    /// - HTML converter outputs HTML table elements
    ///
    /// Default: false
    pub extract_tables: bool,

    /// Directory to save extracted images.
    ///
    /// When Some(path):
    /// - Images are extracted to the specified directory
    /// - Image references use the provided path
    ///
    /// When None:
    /// - Images are referenced but not extracted to disk
    ///
    /// Default: None
    pub image_output_dir: Option<String>,

    /// Embed images as base64 data URIs.
    ///
    /// When true (default):
    /// - HTML output embeds images as base64 data URIs
    /// - Creates self-contained HTML files
    ///
    /// When false:
    /// - Images are saved to `image_output_dir` and referenced by path
    /// - Markdown always uses file references (base64 not well supported)
    ///
    /// Default: true
    pub embed_images: bool,

    /// Include form field values inline in output.
    ///
    /// When true (default), form field values are merged with page content at their
    /// spatial positions. When false, form field values are omitted.
    ///
    /// Default: true
    pub include_form_fields: bool,

    /// Include spans tagged `/Artifact` (running headers/footers, page
    /// numbers, watermarks; ISO 32000-1:2008 §14.8.2.2.1) in the output.
    ///
    /// Default: true (backward compatibility; see
    /// [`crate::converters::ConversionOptions::include_artifacts`]).
    pub include_artifacts: bool,
}

impl Default for OutputConfig {
    fn default() -> Self {
        Self {
            detect_headings: false,
            include_images: false, // Off by default to avoid base64 bloat ~keep
            bold_marker_behavior: BoldMarkerBehavior::Conservative,
            preserve_layout: false,
            extract_tables: false,
            image_output_dir: None,
            embed_images: true,
            include_form_fields: true,
            include_artifacts: true,
        }
    }
}

/// Behavior for bold markers around whitespace.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BoldMarkerBehavior {
    /// Don't apply bold markers to whitespace-only spans.
    ///
    /// This prevents patterns like "** **" in output.
    Conservative,

    /// Apply bold markers to any span with bold font weight.
    Aggressive,
}

impl Default for BoldMarkerBehavior {
    /// Default behavior is Conservative mode.
    fn default() -> Self {
        Self::Conservative
    }
}
