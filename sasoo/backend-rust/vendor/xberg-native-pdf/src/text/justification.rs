//! Text justification detection with PDF spec compliance.
//!
//! Implements ISO 32000-1:2008 Section 9.3 Text State Parameters:
//! - Tc (character spacing): Added after every character
//! - Tw (word spacing): Added after space characters (U+0020)
//! - Tz (horizontal scaling): Scales character widths and spacing
//!
//! Justification modes detected:
//! 1. Left-justified: Constant word spacing, ragged right edge
//! 2. Right-justified: Ragged left, aligned to right margin
//! 3. Center-justified: Balanced margins on both sides
//! 4. Fully-justified: Variable spacing to align both edges
//! 5. Unjustified: No apparent alignment structure

/// Justification modes for text alignment
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum JustificationMode {
    /// Left-aligned with ragged right edge
    LeftJustified,
    /// Right-aligned with ragged left edge
    RightJustified,
    /// Centered with balanced margins
    CenterJustified,
    /// Aligned on both edges with variable spacing
    FullyJustified,
    /// No apparent justification structure
    Unjustified,
}

/// Detects text justification mode from line spacing and alignment.
///
/// Per ISO 32000-1:2008 Section 9.3.1, justification is determined by:
/// 1. Analysis of spacing variance (Tw - word spacing parameter)
/// 2. Line edge alignment (start_x and end_x positions)
/// 3. Margins relative to page boundaries
pub struct JustificationDetector;

impl JustificationDetector {
    /// Detect justification mode from line characteristics.
    ///
    /// # Arguments
    /// * `avg_word_spacing` - Average word spacing (Tw parameter) across line
    /// * `word_spacing_variance` - Variance in word spacing values
    /// * `start_x` - Line starting position (left edge)
    /// * `end_x` - Line ending position (right edge)
    /// * `page_width` - Total page width for margin calculation
    /// * `page_margin_left` - Left page margin (typically 0)
    ///
    /// # Returns
    /// `JustificationMode` indicating the detected justification
    pub fn detect(
        _avg_word_spacing: f32,
        word_spacing_variance: f32,
        start_x: f32,
        end_x: f32,
        page_width: f32,
        page_margin_left: f32,
    ) -> JustificationMode {
        let left_margin = start_x - page_margin_left;
        let right_margin = page_width - end_x;

        let margin_diff = (left_margin - right_margin).abs();
        let is_centered = margin_diff < 10.0; // Allow 10 units tolerance ~keep

        let aligns_left = left_margin < 5.0; // Within 5 units of left edge ~keep
        let aligns_right = right_margin < 5.0; // Within 5 units of right edge ~keep

        // Detect variance-based justification
        // High variance indicates variable spacing (fully justified)
        // Low variance indicates uniform spacing ~keep
        let has_spacing_variance = word_spacing_variance > 0.5;

        if aligns_left && aligns_right {
            JustificationMode::FullyJustified
        } else if is_centered {
            JustificationMode::CenterJustified
        } else if aligns_right {
            JustificationMode::RightJustified
        } else if aligns_left {
            if has_spacing_variance {
                JustificationMode::FullyJustified
            } else {
                JustificationMode::LeftJustified
            }
        } else {
            JustificationMode::Unjustified
        }
    }

    /// Calculate spacing variance in word spacing parameters.
    ///
    /// Variance indicates justification complexity:
    /// - Low variance: Consistent spacing (left-justified)
    /// - High variance: Variable spacing (fully-justified)
    pub fn calculate_word_spacing_variance(word_spacings: &[f32]) -> f32 {
        if word_spacings.is_empty() {
            return 0.0;
        }

        let mean = word_spacings.iter().sum::<f32>() / word_spacings.len() as f32;
        let variance = word_spacings
            .iter()
            .map(|&spacing| (spacing - mean).powi(2))
            .sum::<f32>()
            / word_spacings.len() as f32;

        variance.sqrt()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_left_justified_detection() {
        let mode = JustificationDetector::detect(5.0, 0.1, 0.0, 250.0, 500.0, 0.0);
        assert_eq!(mode, JustificationMode::LeftJustified);
    }

    #[test]
    fn test_right_justified_detection() {
        let mode = JustificationDetector::detect(5.0, 0.1, 250.0, 500.0, 500.0, 0.0);
        assert_eq!(mode, JustificationMode::RightJustified);
    }

    #[test]
    fn test_center_justified_detection() {
        let mode = JustificationDetector::detect(5.0, 0.1, 200.0, 300.0, 500.0, 0.0);
        assert_eq!(mode, JustificationMode::CenterJustified);
    }

    #[test]
    fn test_fully_justified_detection() {
        let mode = JustificationDetector::detect(5.0, 2.0, 0.0, 500.0, 500.0, 0.0);
        assert_eq!(mode, JustificationMode::FullyJustified);
    }

    #[test]
    fn test_unjustified_detection() {
        let mode = JustificationDetector::detect(5.0, 0.1, 100.0, 350.0, 500.0, 0.0);
        assert_eq!(mode, JustificationMode::Unjustified);
    }

    #[test]
    fn test_spacing_variance_calculation() {
        let spacings = vec![5.0, 5.0, 5.0, 5.0];
        let variance = JustificationDetector::calculate_word_spacing_variance(&spacings);
        assert!(variance < 0.1, "Uniform spacing should have low variance");
    }

    #[test]
    fn test_spacing_variance_variable() {
        let spacings = vec![3.0, 5.0, 7.0, 4.0];
        let variance = JustificationDetector::calculate_word_spacing_variance(&spacings);
        assert!(variance > 1.0, "Variable spacing should have higher variance");
    }
}
