/// Parser configuration for controlling lenient/strict parsing modes.
/// Parser options for controlling error handling and recovery behavior.
///
/// These options allow you to trade strict PDF compliance for broader compatibility
/// with malformed or non-standard PDF files.
///
/// # Example
///
/// ```
/// use xberg_native_pdf::parser_config::ParserOptions;
///
/// // Strict mode - fail on first error (default)
/// let strict = ParserOptions::strict();
///
/// // Lenient mode - skip invalid objects and continue
/// let lenient = ParserOptions::lenient();
///
/// // Custom configuration
/// let custom = ParserOptions {
///     strict: false,
///     skip_invalid_objects: true,
///     max_errors: 100,
///     max_nesting: 100,
///     allow_missing_endobj: true,
///     allow_malformed_streams: true,
///     max_decompression_ratio: 100,
///     max_decompressed_size: 100 * 1024 * 1024,
///     max_recursion_depth: 100,
///     max_file_size: 500 * 1024 * 1024,
/// };
/// ```
#[derive(Debug, Clone, Copy)]
pub struct ParserOptions {
    /// Fail on first error (true) or attempt recovery (false)
    ///
    /// In strict mode, the parser enforces all PDF spec requirements and
    /// rejects spec violations. In lenient mode, the parser attempts to
    /// recover from errors for maximum compatibility.
    pub strict: bool,

    /// Skip malformed objects and replace with Null
    pub skip_invalid_objects: bool,

    /// Maximum number of errors before giving up (0 = unlimited)
    pub max_errors: usize,

    /// Maximum object nesting depth (DoS protection)
    ///
    /// Prevents stack overflow from deeply nested arrays/dictionaries
    /// in malicious PDFs. PDF spec recommends max 100 levels.
    ///
    /// PDF Spec: ISO 32000-1:2008, Section H.1 - Implementation Limits
    pub max_nesting: usize,

    /// Allow objects without "endobj" keyword
    pub allow_missing_endobj: bool,

    /// Allow streams with missing or incorrect Length
    pub allow_malformed_streams: bool,

    /// Maximum decompression ratio (compressed:decompressed)
    ///
    /// Prevents decompression bomb attacks where small compressed data
    /// expands to enormous uncompressed data, causing memory exhaustion.
    ///
    /// Default: 100 (100:1 ratio). Set to 0 to disable check.
    ///
    /// Security: ISO 32000-1:2008 does not specify limits, but 100:1 is
    /// a reasonable security threshold that allows legitimate compressed
    /// content while preventing memory exhaustion attacks.
    pub max_decompression_ratio: u32,

    /// Maximum decompressed stream size in bytes
    ///
    /// Prevents memory exhaustion from extremely large decompressed streams.
    ///
    /// Default: 256 MB baseline, overridable via the
    /// `XBERG_NATIVE_PDF_MAX_DECOMPRESS_MB` environment variable; doubled by
    /// [`ParserOptions::very_lenient`]. Set to 0 to disable check.
    ///
    /// Security: Protects against decompression bombs and malicious PDFs.
    pub max_decompressed_size: usize,

    /// Maximum recursion depth (same as max_nesting, for clarity)
    ///
    /// PDF Spec: ISO 32000-1:2008, Section H.1 - Implementation Limits
    pub max_recursion_depth: u32,

    /// Maximum PDF file size in bytes
    ///
    /// Default: 500 MB. Set to 0 to disable check.
    pub max_file_size: usize,
}

impl Default for ParserOptions {
    /// Default configuration: lenient mode with error limits
    fn default() -> Self {
        Self::lenient()
    }
}

impl ParserOptions {
    /// Strict mode: fail on any parsing error
    ///
    /// Use this for validating PDF compliance or when parsing trusted files.
    pub fn strict() -> Self {
        Self {
            strict: true,
            skip_invalid_objects: false,
            max_errors: 1,
            max_nesting: 100,
            allow_missing_endobj: false,
            allow_malformed_streams: false,
            max_decompression_ratio: 100,
            max_decompressed_size: crate::decoders::default_max_decompressed_size(),
            max_recursion_depth: 100,
            max_file_size: 500 * 1024 * 1024,
        }
    }

    /// Lenient mode: attempt to recover from parsing errors
    ///
    /// Use this for parsing potentially malformed PDFs from untrusted sources.
    /// Malformed objects are replaced with Null and parsing continues.
    pub fn lenient() -> Self {
        Self {
            strict: false,
            skip_invalid_objects: true,
            max_errors: 1000,
            max_nesting: 100,
            allow_missing_endobj: true,
            allow_malformed_streams: true,
            max_decompression_ratio: 100,
            max_decompressed_size: crate::decoders::default_max_decompressed_size(),
            max_recursion_depth: 100,
            max_file_size: 500 * 1024 * 1024,
        }
    }

    /// Very lenient mode: maximum compatibility
    ///
    /// Use this for extracting data from heavily damaged PDFs.
    /// Warning: may produce incorrect results for valid PDFs.
    pub fn very_lenient() -> Self {
        Self {
            strict: false,
            skip_invalid_objects: true,
            max_errors: 0,
            max_nesting: 200,
            allow_missing_endobj: true,
            allow_malformed_streams: true,
            // Doubles the size cap alongside the ratio cap (100 -> 200 above): this mode
            // already accepts twice the bomb risk by design, so the size cap tracks it
            // proportionally instead of being a second, independently hardcoded number. ~keep
            max_decompression_ratio: 200,
            max_decompressed_size: crate::decoders::default_max_decompressed_size().saturating_mul(2),
            max_recursion_depth: 200,
            max_file_size: 1024 * 1024 * 1024,
        }
    }

    /// Check if we should continue parsing after an error
    #[cfg(test)]
    pub(crate) fn should_continue(&self, error_count: usize) -> bool {
        if self.strict {
            return false;
        }

        if self.max_errors == 0 {
            return true;
        }

        error_count < self.max_errors
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strict_mode() {
        let opts = ParserOptions::strict();
        assert!(opts.strict);
        assert!(!opts.skip_invalid_objects);
        assert!(!opts.allow_missing_endobj);
    }

    #[test]
    fn test_lenient_mode() {
        let opts = ParserOptions::lenient();
        assert!(!opts.strict);
        assert!(opts.skip_invalid_objects);
        assert!(opts.allow_missing_endobj);
    }

    /// GH#1754 unified `default_max_decompressed_size()` (`decoders::mod`) with
    /// `flate::effective_limit()`, but `ParserOptions::strict()`/`lenient()`/
    /// `very_lenient()` kept hardcoding `100 * 1024 * 1024` independently. Every
    /// production call site passes `options: None` so the env var already reached
    /// production; this only affected callers that construct `ParserOptions`
    /// explicitly, whose cap the env var could not move. One knob must govern both. ~keep
    #[test]
    fn max_decompressed_size_tracks_the_crate_wide_default() {
        let default_cap = crate::decoders::default_max_decompressed_size();
        assert_eq!(ParserOptions::default().max_decompressed_size, default_cap);
        assert_eq!(ParserOptions::strict().max_decompressed_size, default_cap);
        assert_eq!(ParserOptions::lenient().max_decompressed_size, default_cap);
        assert_eq!(
            ParserOptions::very_lenient().max_decompressed_size,
            default_cap.saturating_mul(2),
            "very_lenient already doubles max_decompression_ratio (100 -> 200); its size cap \
             scales the same way rather than being a second, independently hardcoded number"
        );
    }

    #[test]
    fn test_should_continue() {
        let strict = ParserOptions::strict();
        assert!(!strict.should_continue(0));

        let lenient = ParserOptions::lenient();
        assert!(lenient.should_continue(0));
        assert!(lenient.should_continue(999));
        assert!(!lenient.should_continue(1000));

        let very_lenient = ParserOptions::very_lenient();
        assert!(very_lenient.should_continue(0));
        assert!(very_lenient.should_continue(10000));
    }
}
