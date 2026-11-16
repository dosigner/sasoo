//! Statistical analysis of gaps between text spans.
//!
//! This module provides tools for analyzing the distribution of horizontal gaps
//! between consecutive text spans in a PDF document. Gap analysis is a fundamental
//! heuristic for detecting word boundaries, table structures, and column layouts.
//!
//! # Statistical Approach
//!
//! Instead of using fixed thresholds for gap detection, this module computes robust
//! statistics from the actual gap distribution in a document:
//!
//! - **Mean and Standard Deviation**: Overall spacing trends
//! - **Median and Percentiles**: Robust to outliers
//! - **IQR (Interquartile Range)**: Robust spread measure
//!
//! # Adaptive Thresholding
//!
//! The adaptive threshold is computed as a multiple of the median gap size,
//! optionally using IQR instead. This allows the threshold to automatically
//! adapt to different documents and font sizes.
//!
//! # Examples
//!
//! ```ignore
//! use xberg_native_pdf::extractors::gap_statistics::{
//!     analyze_document_gaps, AdaptiveThresholdConfig
//! };
//! use xberg_native_pdf::layout::TextSpan;
//!
//! let spans = vec![/* text spans from document */];
//!
//! // Use default adaptive threshold
//! let result = analyze_document_gaps(&spans, None);
//! println!("Threshold: {}pt", result.threshold_pt);
//!
//! // Use aggressive threshold for tight spacing
//! let config = AdaptiveThresholdConfig::aggressive();
//! let result = analyze_document_gaps(&spans, Some(config));
//! ```
//!
//! Phase 5.1

use crate::layout::TextSpan;
use tracing::debug;

/// Statistical summary of gaps between text spans.
///
/// All percentile values and gap measurements are in PDF points (1/72 inch).
/// This struct captures the complete distribution of horizontal spacing.
#[derive(Debug, Clone)]
pub struct GapStatistics {
    /// All measured gaps between consecutive spans (in points)
    pub gaps: Vec<f32>,
    /// Number of gaps measured
    pub count: usize,
    /// Minimum gap size (in points)
    pub min: f32,
    /// Maximum gap size (in points)
    pub max: f32,
    /// Mean (average) gap size (in points)
    pub mean: f32,
    /// Median gap size (50th percentile) (in points)
    pub median: f32,
    /// Standard deviation of gaps (in points)
    pub std_dev: f32,
    /// 25th percentile (first quartile) (in points)
    pub p25: f32,
    /// 75th percentile (third quartile) (in points)
    pub p75: f32,
    /// 10th percentile (in points)
    pub p10: f32,
    /// 90th percentile (in points)
    pub p90: f32,
}

impl GapStatistics {
    /// Get the interquartile range (IQR = p75 - p25).
    ///
    /// IQR is a robust measure of spread that is less sensitive to outliers
    /// than standard deviation.
    pub fn iqr(&self) -> f32 {
        self.p75 - self.p25
    }

    /// Get the range (max - min).
    pub fn range(&self) -> f32 {
        self.max - self.min
    }

    /// Calculate the coefficient of variation (std_dev / mean).
    ///
    /// Useful for understanding relative variability in gap sizes.
    /// Returns 0.0 if mean is 0 or negative.
    pub fn coefficient_of_variation(&self) -> f32 {
        if self.mean > 0.0 { self.std_dev / self.mean } else { 0.0 }
    }
}

/// Configuration for adaptive threshold calculation.
///
/// Determines how the threshold is computed from gap statistics.
/// All point values assume PDF points (1/72 inch).
#[derive(Debug, Clone, PartialEq)]
pub struct AdaptiveThresholdConfig {
    /// Multiplier applied to median gap when computing threshold.
    ///
    /// **Default**: 1.5
    /// **Range**: 0.5 - 3.0 (values outside this may be unreasonable)
    ///
    /// Higher values → more conservative (fewer gaps marked as word boundaries)
    /// Lower values → more aggressive (more gaps marked as word boundaries)
    pub median_multiplier: f32,

    /// Minimum threshold in PDF points (floor).
    ///
    /// **Default**: 0.05pt (very small, close to tracking/kerning)
    /// **Range**: 0.01 - 0.2pt
    ///
    /// Prevents threshold from becoming too small even with small median gaps.
    pub min_threshold_pt: f32,

    /// Maximum threshold in PDF points (ceiling).
    ///
    /// **Default**: 1.0pt (about 1/72 inch, reasonable word spacing)
    /// **Range**: 0.5 - 2.0pt
    ///
    /// Prevents threshold from becoming unreasonably large.
    pub max_threshold_pt: f32,

    /// Use IQR instead of median for robust threshold calculation.
    ///
    /// **Default**: false
    ///
    /// When true: `threshold = (p75 - p25) * multiplier`
    /// When false: `threshold = median * multiplier`
    ///
    /// IQR-based approach is more robust to outliers but may require
    /// different multiplier values (typically 0.3 - 0.7).
    pub use_iqr: bool,

    /// Minimum number of samples required to compute meaningful statistics.
    ///
    /// **Default**: 10
    ///
    /// If fewer gaps exist, statistics cannot be reliably computed
    /// and the function returns a default threshold instead.
    pub min_samples: usize,
}

impl Default for AdaptiveThresholdConfig {
    fn default() -> Self {
        Self {
            median_multiplier: 1.5,
            min_threshold_pt: 0.05,
            max_threshold_pt: 100.0,
            // ~keep
            use_iqr: false,
            min_samples: 10,
        }
    }
}

impl AdaptiveThresholdConfig {
    /// Create a new configuration with default values.
    pub fn new() -> Self {
        Self::default()
    }

    /// Balanced configuration (default multiplier: 1.5).
    ///
    /// Suitable for most PDF documents with standard spacing.
    pub fn balanced() -> Self {
        Self::default()
    }

    /// Aggressive configuration (lower multiplier: 1.2).
    ///
    /// Marks more gaps as word boundaries. Useful when:
    /// - Text has tight spacing
    /// - You want to break up large blocks more aggressively
    /// - False negatives (missed gaps) are worse than false positives
    pub fn aggressive() -> Self {
        Self {
            median_multiplier: 1.2,
            min_threshold_pt: 0.05,
            max_threshold_pt: 100.0,
            // ~keep
            use_iqr: false,
            min_samples: 10,
        }
    }

    /// Conservative configuration (higher multiplier: 2.0).
    ///
    /// Marks fewer gaps as word boundaries. Useful when:
    /// - Text has loose spacing
    /// - You want to avoid breaking up tightly-kerned text
    /// - False positives (extra gaps) are worse than false negatives
    pub fn conservative() -> Self {
        Self {
            median_multiplier: 2.0,
            min_threshold_pt: 0.05,
            max_threshold_pt: 100.0,
            // ~keep
            use_iqr: false,
            min_samples: 10,
        }
    }

    /// Optimized for policy documents with tight spacing (multiplier: 1.3).
    ///
    /// Policy documents often have:
    /// - Narrow margins
    /// - Tight justified alignment
    /// - Minimal word spacing
    ///
    /// This configuration requires larger gaps to be detected as boundaries,
    /// and sets higher minimum threshold to avoid false positives.
    pub fn policy_documents() -> Self {
        Self {
            median_multiplier: 1.3,
            min_threshold_pt: 0.08,
            max_threshold_pt: 100.0,
            // ~keep
            use_iqr: false,
            min_samples: 10,
        }
    }

    /// Optimized for academic papers with standard spacing (multiplier: 1.6).
    ///
    /// Academic papers typically have:
    /// - Standard margins
    /// - Generous word spacing
    /// - Single or double-column layouts
    ///
    /// This configuration is slightly more conservative than balanced
    /// to handle the higher baseline spacing.
    pub fn academic() -> Self {
        Self {
            median_multiplier: 1.6,
            min_threshold_pt: 0.2,
            max_threshold_pt: 100.0,
            // ~keep
            use_iqr: false,
            min_samples: 10,
        }
    }

    /// Create a configuration with custom multiplier.
    ///
    /// # Arguments
    ///
    /// * `multiplier` - Multiplier for median or IQR (typically 0.5 - 3.0)
    ///
    /// # Examples
    ///
    /// ```ignore
    /// use xberg_native_pdf::extractors::gap_statistics::AdaptiveThresholdConfig;
    ///
    /// let config = AdaptiveThresholdConfig::with_multiplier(1.4);
    /// ```
    pub fn with_multiplier(multiplier: f32) -> Self {
        Self {
            median_multiplier: multiplier,
            ..Default::default()
        }
    }

    /// Enable or disable IQR-based calculation.
    ///
    /// # Arguments
    ///
    /// * `use_iqr` - If true, use IQR instead of median
    ///
    /// # Examples
    ///
    /// ```ignore
    /// use xberg_native_pdf::extractors::gap_statistics::AdaptiveThresholdConfig;
    ///
    /// let config = AdaptiveThresholdConfig::default()
    ///     .with_iqr(true);
    /// ```
    pub fn with_iqr(mut self, use_iqr: bool) -> Self {
        self.use_iqr = use_iqr;
        self
    }

    /// Set minimum threshold floor.
    pub fn with_min_threshold(mut self, min_pt: f32) -> Self {
        self.min_threshold_pt = min_pt;
        self
    }

    /// Set maximum threshold ceiling.
    pub fn with_max_threshold(mut self, max_pt: f32) -> Self {
        self.max_threshold_pt = max_pt;
        self
    }

    /// Set minimum number of samples required.
    pub fn with_min_samples(mut self, count: usize) -> Self {
        self.min_samples = count;
        self
    }
}

/// Result of adaptive threshold analysis.
///
/// Contains the computed threshold, underlying statistics if available,
/// and a reason string explaining how the threshold was determined.
#[derive(Debug, Clone)]
pub struct AdaptiveThresholdResult {
    /// The computed threshold in PDF points.
    ///
    /// Use this value to classify gaps:
    /// - If `gap >= threshold_pt`: likely a word boundary
    /// - If `gap < threshold_pt`: likely tight spacing/kerning
    pub threshold_pt: f32,

    /// Statistical summary if available.
    ///
    /// None if:
    /// - No spans provided
    /// - Fewer gaps than `min_samples` in config
    /// - All gaps are identical (no variation)
    pub stats: Option<GapStatistics>,

    /// Explanation of how threshold was determined.
    ///
    /// Examples:
    /// - "Computed from 245 gaps: median=0.15pt * 1.5 = 0.225pt"
    /// - "Insufficient samples: 3 gaps < min_samples (10), using default 0.1pt"
    /// - "Single span: no gaps to analyze, using default 0.1pt"
    pub reason: String,
}

/// Extract horizontal gaps from text spans.
///
/// Measures the distance from the right edge of each span to the left edge
/// of the next span. Negative values indicate overlapping text.
///
/// # Arguments
///
/// * `spans` - Text spans sorted in reading order (typically by position)
///
/// # Returns
///
/// Vector of gap sizes in PDF points. Empty if fewer than 2 spans.
///
/// # Examples
///
/// ```ignore
/// use xberg_native_pdf::extractors::gap_statistics::extract_gaps;
/// use xberg_native_pdf::layout::TextSpan;
/// use xberg_native_pdf::geometry::Rect;
///
/// let spans = vec![
///     TextSpan { artifact_type: None,
///         bbox: Rect::new(10.0, 10.0, 30.0, 12.0),  // right edge at 40.0
///         // ...other fields...
///     },
///     TextSpan { artifact_type: None,
///         bbox: Rect::new(45.0, 10.0, 30.0, 12.0),  // left edge at 45.0
///         // ...other fields...
///     },
/// ];
///
/// let gaps = extract_gaps(&spans);
/// assert_eq!(gaps[0], 5.0);  // 45.0 - 40.0 = 5.0
/// ```
pub fn extract_gaps(spans: &[TextSpan]) -> Vec<f32> {
    if spans.len() < 2 {
        return Vec::new();
    }

    let mut gaps = Vec::with_capacity(spans.len() - 1);

    for i in 0..spans.len() - 1 {
        let current_right = spans[i].bbox.right();
        let next_left = spans[i + 1].bbox.left();
        let gap = next_left - current_right;
        gaps.push(gap);
    }

    gaps
}

/// Calculate comprehensive statistics from a list of gaps.
///
/// Computes mean, median, standard deviation, and multiple percentiles.
/// Returns None if the input is empty.
///
/// # Arguments
///
/// * `gaps` - Raw gap measurements in points
///
/// # Returns
///
/// Some(GapStatistics) if gaps is non-empty, None otherwise.
///
/// # Percentile Calculation
///
/// Uses linear interpolation between sorted values (NIST recommended method).
/// This provides smooth estimates even with small samples.
///
/// # Examples
///
/// ```ignore
/// use xberg_native_pdf::extractors::gap_statistics::calculate_statistics;
///
/// let gaps = vec![0.1, 0.2, 0.15, 0.25, 0.3, 0.18, 0.22];
/// let stats = calculate_statistics(gaps).unwrap();
///
/// println!("Mean: {}pt", stats.mean);
/// println!("Median: {}pt", stats.median);
/// println!("Std Dev: {}pt", stats.std_dev);
/// ```
pub fn calculate_statistics(mut gaps: Vec<f32>) -> Option<GapStatistics> {
    if gaps.is_empty() {
        return None;
    }

    let count = gaps.len();

    let min = gaps.iter().copied().fold(f32::INFINITY, f32::min);
    let max = gaps.iter().copied().fold(f32::NEG_INFINITY, f32::max);

    let sum: f32 = gaps.iter().sum();
    let mean = sum / count as f32;

    let variance: f32 = gaps.iter().map(|&g| (g - mean).powi(2)).sum::<f32>() / count as f32;
    let std_dev = variance.sqrt();

    gaps.sort_by(|a, b| crate::utils::safe_float_cmp(*a, *b));

    let p10 = percentile(&gaps, 0.10);
    let p25 = percentile(&gaps, 0.25);
    let median = percentile(&gaps, 0.50);
    let p75 = percentile(&gaps, 0.75);
    let p90 = percentile(&gaps, 0.90);

    Some(GapStatistics {
        gaps,
        count,
        min,
        max,
        mean,
        median,
        std_dev,
        p25,
        p75,
        p10,
        p90,
    })
}

/// Determine adaptive threshold from gap statistics.
///
/// Uses the configuration to compute a threshold based on median or IQR,
/// then clamps the result to the configured bounds.
///
/// # Arguments
///
/// * `stats` - Gap statistics from the document
/// * `config` - Threshold configuration parameters
///
/// # Returns
///
/// Threshold value in PDF points.
///
/// # Calculation
///
/// If `config.use_iqr` is false:
/// ```text
/// base_threshold = stats.median * config.median_multiplier
/// ```
///
/// If `config.use_iqr` is true:
/// ```text
/// base_threshold = (stats.p75 - stats.p25) * config.median_multiplier
/// ```
///
/// Then clamped:
/// ```text
/// final_threshold = clamp(base_threshold, min_threshold_pt, max_threshold_pt)
/// ```
///
/// # Examples
///
/// ```ignore
/// use xberg_native_pdf::extractors::gap_statistics::{
///     calculate_statistics, determine_adaptive_threshold, AdaptiveThresholdConfig
/// };
///
/// let gaps = vec![0.1, 0.15, 0.2, 0.25, 0.3];
/// let stats = calculate_statistics(gaps).unwrap();
///
/// let config = AdaptiveThresholdConfig::balanced();
/// let threshold = determine_adaptive_threshold(&stats, &config);
///
/// println!("Threshold: {}pt", threshold);
/// ```
pub fn determine_adaptive_threshold(stats: &GapStatistics, config: &AdaptiveThresholdConfig) -> f32 {
    let base_threshold = if config.use_iqr {
        stats.iqr() * config.median_multiplier
    } else {
        stats.median * config.median_multiplier
    };

    base_threshold.max(config.min_threshold_pt).min(config.max_threshold_pt)
}

/// Detect word boundary threshold using percentile-based analysis.
///
/// Uses the 75th percentile of positive gaps as the word spacing threshold.
/// This naturally falls at the boundary between letter-spacing (tight, ~70% of gaps)
/// and word-spacing (wider, ~25% of gaps).
///
/// # Algorithm
///
/// 1. Filter gaps to only positive values (negative gaps indicate overlaps/kerning)
/// 2. Sort positive gaps
/// 3. Compute 75th percentile: approximately where letter-spacing ends, word-spacing begins
/// 4. Return percentile if within reasonable bounds (2-10pt)
///
/// # Returns
///
/// `Some(threshold)` if percentile falls in reasonable range (2-10pt)
/// `None` if insufficient data or percentile out of bounds
///
/// # Rationale
///
/// In typical documents:
/// - ~75% of gaps are letter-spacing (tight, 2-4pt)
/// - ~25% of gaps are word-spacing (wider, 4-10pt)
/// - P75 naturally marks the transition
///
/// This is more robust than looking for the "largest jump" because:
/// - Handles diverse PDF structures uniformly
/// - Adapts to document's actual gap distribution
/// - Avoids detecting layout breaks (which are far beyond word-spacing)
fn detect_word_boundary_threshold(spans: &[TextSpan]) -> Option<f32> {
    let mut gaps: Vec<f32> = spans
        .windows(2)
        .map(|w| w[1].bbox.left() - w[0].bbox.right())
        .filter(|g| *g > 0.0)
        .collect();

    if gaps.len() < 10 {
        return None;
    }

    gaps.sort_by(|a, b| crate::utils::safe_float_cmp(*a, *b));

    let p75 = percentile(&gaps, 0.75);

    if (2.0..=10.0).contains(&p75) {
        debug!("Percentile-based threshold: P75 = {:.4}pt", p75);
        Some(p75)
    } else {
        debug!("Percentile-based threshold: P75 = {:.4}pt (out of bounds 2-10pt)", p75);
        None
    }
}

/// Analyze gap statistics for an entire document and compute adaptive threshold.
///
/// This is the main entry point for gap analysis. It:
/// 1. Extracts gaps from consecutive spans
/// 2. Attempts bimodal detection first
/// 3. Falls back to adaptive threshold computation
/// 4. Computes statistics if sufficient gaps exist
/// 5. Provides detailed reasoning in the result
///
/// # Arguments
///
/// * `spans` - Text spans from the document (should be sorted by position)
/// * `config` - Configuration (uses default if None)
///
/// # Returns
///
/// AdaptiveThresholdResult containing:
/// - `threshold_pt`: The computed threshold for gap detection
/// - `stats`: Optional statistics (None if insufficient data)
/// - `reason`: Explanation of how threshold was determined
///
/// # Edge Cases
///
/// - **No spans or single span**: Returns default threshold of 0.1pt
/// - **Insufficient gaps**: Returns default threshold if gaps < min_samples
/// - **All identical gaps**: Computes threshold normally (std_dev = 0)
/// - **Very tight spacing**: Threshold is clamped to max_threshold_pt
/// - **Very loose spacing**: Threshold is clamped to max_threshold_pt
///
/// # Examples
///
/// ```ignore
/// use xberg_native_pdf::extractors::gap_statistics::{
///     analyze_document_gaps, AdaptiveThresholdConfig
/// };
/// use xberg_native_pdf::layout::TextSpan;
///
/// let spans = vec![/* extracted text spans */];
///
/// // With default config
/// let result = analyze_document_gaps(&spans, None);
/// println!("Threshold: {}pt ({})", result.threshold_pt, result.reason);
///
/// // With custom config
/// let config = AdaptiveThresholdConfig::aggressive();
/// let result = analyze_document_gaps(&spans, Some(config));
/// ```
pub fn analyze_document_gaps(spans: &[TextSpan], config: Option<AdaptiveThresholdConfig>) -> AdaptiveThresholdResult {
    let config = config.unwrap_or_default();

    debug!(
        "Analyzing {} spans with config: multiplier={}, min={}pt, max={}pt, iqr={}",
        spans.len(),
        config.median_multiplier,
        config.min_threshold_pt,
        config.max_threshold_pt,
        config.use_iqr
    );

    if let Some(result) = insufficient_span_result(spans) {
        return result;
    }

    if let Some(bimodal_threshold) = detect_word_boundary_threshold(spans) {
        return bimodal_gap_result(bimodal_threshold);
    }

    let gaps = extract_gaps(spans);

    debug!("Extracted {} gaps from {} spans", gaps.len(), spans.len());

    if let Some(result) = insufficient_gap_samples_result(&gaps, &config) {
        return result;
    }

    // Filter out negative gaps before computing statistics
    // (negative gaps represent text overlaps/kerning, not word boundaries) ~keep
    let gaps_to_analyze = select_gaps_to_analyze(gaps);

    let stats = match calculate_statistics(gaps_to_analyze) {
        Some(s) => s,
        None => {
            let reason = "Failed to calculate statistics".to_string();
            debug!("{}", reason);

            return AdaptiveThresholdResult {
                threshold_pt: 0.1,
                stats: None,
                reason,
            };
        }
    };

    let threshold_pt = determine_adaptive_threshold(&stats, &config);
    let reason = build_threshold_reason(&stats, &config, threshold_pt);

    debug!("Threshold analysis: {}", reason);

    AdaptiveThresholdResult {
        threshold_pt,
        stats: Some(stats),
        reason,
    }
}

/// Early-return result for zero or one span: there are no gaps to analyze. ~keep
fn insufficient_span_result(spans: &[TextSpan]) -> Option<AdaptiveThresholdResult> {
    if spans.len() >= 2 {
        return None;
    }

    let reason = if spans.is_empty() {
        "No spans provided".to_string()
    } else {
        "Single span: no gaps to analyze".to_string()
    };

    debug!("{}, using default threshold", reason);

    Some(AdaptiveThresholdResult {
        threshold_pt: 0.1,
        stats: None,
        reason,
    })
}

/// Builds the result when bimodal detection already identified a word-boundary threshold. ~keep
fn bimodal_gap_result(bimodal_threshold: f32) -> AdaptiveThresholdResult {
    let reason = format!(
        "Bimodal detection: identified word boundary at {:.4}pt",
        bimodal_threshold
    );
    debug!("Using bimodal threshold: {}", reason);

    AdaptiveThresholdResult {
        threshold_pt: bimodal_threshold,
        stats: None,
        reason,
    }
}

/// Early-return result when there aren't enough gap samples to compute statistics. ~keep
fn insufficient_gap_samples_result(gaps: &[f32], config: &AdaptiveThresholdConfig) -> Option<AdaptiveThresholdResult> {
    if gaps.len() >= config.min_samples {
        return None;
    }

    let reason = format!(
        "Insufficient samples: {} gaps < min_samples ({}), using default",
        gaps.len(),
        config.min_samples
    );

    debug!("{}", reason);

    Some(AdaptiveThresholdResult {
        threshold_pt: 0.1,
        stats: None,
        reason,
    })
}

/// Filters to positive gaps when there are enough of them, otherwise keeps all gaps. ~keep
fn select_gaps_to_analyze(gaps: Vec<f32>) -> Vec<f32> {
    let positive_gaps: Vec<f32> = gaps.iter().filter(|g| **g > 0.0).copied().collect();

    if positive_gaps.len() >= 10 {
        debug!(
            "Filtered to {} positive gaps (from {} total gaps)",
            positive_gaps.len(),
            gaps.len()
        );
        positive_gaps
    } else {
        debug!(
            "Not enough positive gaps ({}) to filter, using all gaps",
            positive_gaps.len()
        );
        gaps
    }
}

/// Builds the human-readable reason string for a computed threshold. ~keep
fn build_threshold_reason(stats: &GapStatistics, config: &AdaptiveThresholdConfig, threshold_pt: f32) -> String {
    let base_value = if config.use_iqr {
        format!("IQR={:.3}pt", stats.iqr())
    } else {
        format!("median={:.3}pt", stats.median)
    };

    format!(
        "Computed from {} gaps: {} * {:.1} = {:.3}pt (clamped to {:.3}pt)",
        stats.count,
        base_value,
        config.median_multiplier,
        if config.use_iqr {
            stats.iqr() * config.median_multiplier
        } else {
            stats.median * config.median_multiplier
        },
        threshold_pt
    )
}

/// Helper function to compute percentiles using linear interpolation.
///
/// Uses the NIST-recommended method:
/// - For sorted array of length n, to compute percentile p (0.0 - 1.0):
///   - Calculate index: `i = p * (n - 1)`
///   - If i is not an integer, interpolate between adjacent values
///
/// # Arguments
///
/// * `sorted_values` - Values in ascending order
/// * `percentile` - Percentile to compute (0.0 - 1.0)
///
/// # Returns
///
/// Interpolated percentile value.
fn percentile(sorted_values: &[f32], percentile: f32) -> f32 {
    if sorted_values.is_empty() {
        return 0.0;
    }

    if sorted_values.len() == 1 {
        return sorted_values[0];
    }

    let index = percentile * (sorted_values.len() - 1) as f32;
    let lower_index = index.floor() as usize;
    let upper_index = (lower_index + 1).min(sorted_values.len() - 1);

    if lower_index == upper_index {
        sorted_values[lower_index]
    } else {
        let fraction = index - lower_index as f32;
        sorted_values[lower_index] * (1.0 - fraction) + sorted_values[upper_index] * fraction
    }
}

#[cfg(test)]
mod tests;
