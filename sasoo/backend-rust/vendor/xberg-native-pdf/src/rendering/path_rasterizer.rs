//! Path rasterizer - renders PDF paths using tiny-skia.

use super::{
    create_fill_paint, create_stroke_paint, guarded_fill_path, guarded_stroke_path, paint_with_nonsep_blend,
    pdf_blend_mode_is_nonseparable,
};
use crate::content::GraphicsState;
use tiny_skia::{FillRule, LineCap, LineJoin, Path, Pixmap, Stroke, Transform};

/// Rasterizer for PDF path operations.
pub struct PathRasterizer {}

impl PathRasterizer {
    /// Create a new path rasterizer.
    pub fn new() -> Self {
        Self {}
    }

    /// Fill a path with optional clip mask.
    pub fn fill_path_clipped(
        &self,
        pixmap: &mut Pixmap,
        path: &tiny_skia::Path,
        transform: Transform,
        gs: &GraphicsState,
        fill_rule: FillRule,
        clip_mask: Option<&tiny_skia::Mask>,
    ) {
        // NOTE: do NOT compute `path.clone().transform(transform)` here just for
        // logging. Vector figures (scatter / contour plots embedded as Form
        // XObjects) trigger this path tens of thousands of times per page, and
        // cloning + retransforming the path on every call dominated the render
        // time on vector-heavy PDFs (~240 s/page → seconds). Event field
        // expressions are only evaluated when the callsite is enabled, so at
        // non-TRACE levels `pixel_bounds` costs nothing — no explicit guard
        // needed. TRACE (not DEBUG) because this fires per fill, i.e.
        // per-path. ~keep
        tracing::trace!(
            color = ?gs.fill_color_rgb,
            alpha = gs.fill_alpha,
            bounds = ?path.bounds(),
            pixel_bounds = ?path.clone().transform(transform).map(|p| p.bounds()),
            "PathRasterizer::fill_path"
        );

        // §11.3.5.3 non-separable blend modes have no native tiny_skia
        // counterpart. Route through the out-of-band path: render with
        // Normal blending into a scratch pixmap, then per-pixel compose
        // into the destination via HSL/HSY algorithm. ~keep
        if let Some(mode) = pdf_blend_mode_is_nonseparable(&gs.blend_mode) {
            let paint = create_fill_paint(gs, "Normal");
            paint_with_nonsep_blend(pixmap, mode, |scratch| {
                guarded_fill_path(scratch, path, &paint, fill_rule, transform, clip_mask);
            });
            return;
        }

        let paint = create_fill_paint(gs, &gs.blend_mode);
        guarded_fill_path(pixmap, path, &paint, fill_rule, transform, clip_mask);
    }

    /// Stroke a path with optional clip mask.
    pub fn stroke_path_clipped(
        &self,
        pixmap: &mut Pixmap,
        path: &Path,
        transform: Transform,
        gs: &GraphicsState,
        clip_mask: Option<&tiny_skia::Mask>,
    ) {
        // See fill_path_clipped: field expressions are only evaluated when the
        // callsite is enabled, so this costs nothing at non-TRACE levels.
        // TRACE because this fires per stroke, i.e. per-path. ~keep
        tracing::trace!(
            color = ?gs.stroke_color_rgb,
            alpha = gs.stroke_alpha,
            bounds = ?path.bounds(),
            pixel_bounds = ?path.clone().transform(transform).map(|p| p.bounds()),
            "PathRasterizer::stroke_path"
        );

        let dash = if !gs.dash_pattern.0.is_empty() {
            tiny_skia::StrokeDash::new(gs.dash_pattern.0.clone(), gs.dash_pattern.1)
        } else {
            None
        };

        let stroke = Stroke {
            width: gs.line_width,
            line_cap: self.pdf_line_cap_to_skia(gs.line_cap),
            line_join: self.pdf_line_join_to_skia(gs.line_join),
            miter_limit: gs.miter_limit,
            dash,
        };

        // §11.3.5.3 non-separable blend modes go through the
        // out-of-band scratch + HSL/HSY compose path. ~keep
        if let Some(mode) = pdf_blend_mode_is_nonseparable(&gs.blend_mode) {
            let paint = create_stroke_paint(gs, "Normal");
            paint_with_nonsep_blend(pixmap, mode, |scratch| {
                guarded_stroke_path(scratch, path, &paint, &stroke, transform, clip_mask);
            });
            return;
        }

        let paint = create_stroke_paint(gs, &gs.blend_mode);
        guarded_stroke_path(pixmap, path, &paint, &stroke, transform, clip_mask);
    }

    /// Convert PDF line cap style to tiny-skia.
    fn pdf_line_cap_to_skia(&self, cap: u8) -> LineCap {
        match cap {
            0 => LineCap::Butt,
            1 => LineCap::Round,
            2 => LineCap::Square,
            _ => LineCap::Butt,
        }
    }

    /// Convert PDF line join style to tiny-skia.
    fn pdf_line_join_to_skia(&self, join: u8) -> LineJoin {
        match join {
            0 => LineJoin::Miter,
            1 => LineJoin::Round,
            2 => LineJoin::Bevel,
            _ => LineJoin::Miter,
        }
    }
}

impl Default for PathRasterizer {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_path_rasterizer_new() {
        let rasterizer = PathRasterizer::new();
        assert_eq!(rasterizer.pdf_line_cap_to_skia(0), LineCap::Butt);
    }

    #[test]
    fn test_line_cap_conversion() {
        let rasterizer = PathRasterizer::new();
        assert_eq!(rasterizer.pdf_line_cap_to_skia(0), LineCap::Butt);
        assert_eq!(rasterizer.pdf_line_cap_to_skia(1), LineCap::Round);
        assert_eq!(rasterizer.pdf_line_cap_to_skia(2), LineCap::Square);
        assert_eq!(rasterizer.pdf_line_cap_to_skia(99), LineCap::Butt);
    }

    #[test]
    fn test_line_join_conversion() {
        let rasterizer = PathRasterizer::new();
        assert_eq!(rasterizer.pdf_line_join_to_skia(0), LineJoin::Miter);
        assert_eq!(rasterizer.pdf_line_join_to_skia(1), LineJoin::Round);
        assert_eq!(rasterizer.pdf_line_join_to_skia(2), LineJoin::Bevel);
    }
}
