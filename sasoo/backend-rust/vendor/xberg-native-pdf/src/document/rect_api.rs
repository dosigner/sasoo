//! Rectangle-scoped and rectangle-excluding extraction variants.
//!
//! Split out of the parent's single 18,544-line `impl PdfDocument`, which made
//! `document.rs` 1.2 MiB and tripped the 500 KiB file-safety limit. A child module's
//! `impl` is the same inherent impl and sees the parent's private items unchanged. ~keep

use super::*;

impl PdfDocument {
    /// Extract text from a specific rectangular region of a page.
    ///
    /// Only spans whose bounding boxes match `region` under `mode` are kept;
    /// the retained spans are assembled through the full text pipeline
    /// (reading order, tables, line breaks) so the output matches the
    /// quality of [`Self::extract_text`]. Calling this with a region that covers
    /// the whole page is equivalent to [`Self::extract_text`].
    pub fn extract_text_in_rect(
        &self,
        page_index: usize,
        region: crate::geometry::Rect,
        mode: crate::layout::RectFilterMode,
    ) -> Result<String> {
        let options = crate::converters::ConversionOptions {
            extract_tables: true,
            include_region: Some((region, mode)),
            ..Default::default()
        };
        self.extract_text_with_options(page_index, &options)
    }

    /// Extract words from a specific rectangular region of a page.
    pub fn extract_words_in_rect(
        &self,
        page_index: usize,
        region: crate::geometry::Rect,
        mode: crate::layout::RectFilterMode,
    ) -> Result<Vec<crate::layout::Word>> {
        use crate::layout::SpatialCollectionFiltering;
        let words = self.extract_words(page_index)?;
        Ok(words.filter_by_rect(&region, mode))
    }

    /// Extract text lines from a specific rectangular region of a page.
    pub fn extract_text_lines_in_rect(
        &self,
        page_index: usize,
        region: crate::geometry::Rect,
        mode: crate::layout::RectFilterMode,
    ) -> Result<Vec<crate::layout::TextLine>> {
        use crate::layout::SpatialCollectionFiltering;
        let lines = self.extract_text_lines(page_index)?;
        Ok(lines.filter_by_rect(&region, mode))
    }

    /// Extract text spans from a specific rectangular region of a page.
    pub fn extract_spans_in_rect(
        &self,
        page_index: usize,
        region: crate::geometry::Rect,
        mode: crate::layout::RectFilterMode,
    ) -> Result<Vec<crate::layout::TextSpan>> {
        use crate::layout::SpatialCollectionFiltering;
        let spans = self.extract_spans(page_index)?;
        Ok(spans.filter_by_rect(&region, mode))
    }

    /// Extract text from a page excluding specific rectangular regions.
    ///
    /// The excluded spans are removed before the full text-assembly pipeline
    /// runs, so the output has the same structure — line breaks, tables,
    /// reading order — as [`Self::extract_text`]. Calling this with an empty
    /// `exclude` slice is equivalent to [`Self::extract_text`].
    ///
    /// `mode` controls the overlap rule:
    /// - [`crate::layout::RectFilterMode::Intersects`] (default): drop any span with *any* overlap
    /// - [`crate::layout::RectFilterMode::FullyContained`]: drop only spans lying entirely inside
    /// - `RectFilterMode::MinOverlap(t)`: drop spans where at least fraction `t`
    ///   of the *span's* area overlaps an excluded region
    ///
    /// For Tagged PDFs the extractor already honours `/Artifact` marked-content
    /// (PDF spec §14.8.2.2). This method provides the same capability for
    /// untagged PDFs where spatial coordinates are the only available signal.
    /// Exclusion is unconditional: spans inside a region are dropped regardless
    /// of their structure-tree role.
    pub fn extract_text_excluding_rects(
        &self,
        page_index: usize,
        exclude: &[crate::geometry::Rect],
        mode: crate::layout::RectFilterMode,
    ) -> Result<String> {
        let options = crate::converters::ConversionOptions {
            extract_tables: true,
            exclude_regions: exclude.to_vec(),
            exclude_regions_mode: mode,
            ..Default::default()
        };
        self.extract_text_with_options(page_index, &options)
    }

    /// Extract words from a page excluding specific rectangular regions.
    ///
    /// See [`Self::extract_text_excluding_rects`] for a description of `exclude` and `mode`.
    /// Returns the low-level [`crate::layout::Word`] stream; use [`Self::extract_text_excluding_rects`]
    /// for fully-assembled text with line breaks and tables.
    pub fn extract_words_excluding_rects(
        &self,
        page_index: usize,
        exclude: &[crate::geometry::Rect],
        mode: crate::layout::RectFilterMode,
    ) -> Result<Vec<crate::layout::Word>> {
        use crate::layout::SpatialCollectionFiltering;
        let words = self.extract_words(page_index)?;
        Ok(words.exclude_rects(exclude, mode))
    }

    /// Extract text spans from a page excluding specific rectangular regions.
    ///
    /// See [`Self::extract_text_excluding_rects`] for a description of `exclude` and `mode`.
    /// Returns raw [`crate::layout::TextSpan`] objects with bounding boxes and font metadata;
    /// use [`Self::extract_text_excluding_rects`] for fully-assembled text output.
    pub fn extract_spans_excluding_rects(
        &self,
        page_index: usize,
        exclude: &[crate::geometry::Rect],
        mode: crate::layout::RectFilterMode,
    ) -> Result<Vec<crate::layout::TextSpan>> {
        use crate::layout::SpatialCollectionFiltering;
        let spans = self.extract_spans(page_index)?;
        Ok(spans.exclude_rects(exclude, mode))
    }

    /// Extract rectangles from a specific rectangular region of a page.
    pub fn extract_rects_in_rect(
        &self,
        page_index: usize,
        region: crate::geometry::Rect,
    ) -> Result<Vec<crate::elements::PathContent>> {
        let rects = self.extract_rects(page_index)?;
        // Rendered extents, matching `extract_paths_in_rect`. ~keep
        Ok(rects
            .into_iter()
            .filter(|p| p.rendered_bbox().intersects(&region))
            .collect())
    }

    /// Extract straight lines from a specific rectangular region of a page.
    pub fn extract_lines_in_rect(
        &self,
        page_index: usize,
        region: crate::geometry::Rect,
    ) -> Result<Vec<crate::elements::PathContent>> {
        let lines = self.extract_lines(page_index)?;
        // Rendered extents, matching `extract_paths_in_rect`: a
        // stroke-width-encoded rule must match region queries over its drawn
        // bar, not only over its geometric speck. ~keep
        Ok(lines
            .into_iter()
            .filter(|p| p.rendered_bbox().intersects(&region))
            .collect())
    }

    /// Extract individual characters from a specific rectangular region of a page.
    pub fn extract_chars_in_rect(
        &self,
        page_index: usize,
        region: crate::geometry::Rect,
        mode: crate::layout::RectFilterMode,
    ) -> Result<Vec<crate::layout::TextChar>> {
        use crate::layout::SpatialCollectionFiltering;
        let chars = self.extract_chars(page_index)?;
        Ok(chars.filter_by_rect(&region, mode))
    }

    /// Extract images from a specific rectangular region of a page.
    pub fn extract_images_in_rect(
        &self,
        page_index: usize,
        region: crate::geometry::Rect,
    ) -> Result<Vec<crate::extractors::PdfImage>> {
        let images = self.extract_images(page_index)?;
        Ok(images
            .into_iter()
            .filter(|img| {
                if let Some(bbox) = img.bbox() {
                    bbox.intersects(&region)
                } else {
                    false
                }
            })
            .collect())
    }

    /// Get information about a page, including its dimensions.
    ///
    /// This is useful for rendering and layout calculations.
    pub fn get_page_info(&self, page_index: usize) -> Result<PageInfo> {
        let page = self.get_page(page_index)?;
        let page_dict = page.as_dict().ok_or_else(|| Error::ParseError {
            offset: 0,
            reason: "Page is not a dictionary".to_string(),
        })?;

        fn obj_to_f32(obj: &Object) -> Option<f32> {
            match obj {
                Object::Integer(i) => Some(*i as f32),
                Object::Real(r) => Some(*r as f32),
                _ => None,
            }
        }

        // Get MediaBox (required, may be inherited).
        // PDF spec §7.3.10: any value may be a direct or indirect reference —
        // including each individual array element (pdf.js issue7872 stores
        // `/MediaBox [4 0 R 5 0 R 6 0 R 7 0 R]`). Resolve every element,
        // otherwise an unresolved Reference reads as None and silently
        // falls back to the Letter-size default instead of the true bounds. ~keep
        let media_box = page_dict
            .get("MediaBox")
            .map(|o| self.resolve_obj_ref(o))
            .as_ref()
            .and_then(|o| o.as_array().map(|a| a.to_owned()))
            .map(|arr| {
                let r: Vec<Object> = arr.iter().map(|o| self.resolve_obj_ref(o)).collect();
                let x0 = r.first().and_then(obj_to_f32).unwrap_or(0.0);
                let y0 = r.get(1).and_then(obj_to_f32).unwrap_or(0.0);
                let x1 = r.get(2).and_then(obj_to_f32).unwrap_or(612.0);
                let y1 = r.get(3).and_then(obj_to_f32).unwrap_or(792.0);
                crate::geometry::Rect::from_points(x0, y0, x1, y1)
            })
            .unwrap_or(crate::geometry::Rect::from_points(0.0, 0.0, 612.0, 792.0));

        let crop_box = page_dict
            .get("CropBox")
            .map(|o| self.resolve_obj_ref(o))
            .as_ref()
            .and_then(|o| o.as_array().map(|a| a.to_owned()))
            .map(|arr| {
                let r: Vec<Object> = arr.iter().map(|o| self.resolve_obj_ref(o)).collect();
                let x0 = r.first().and_then(obj_to_f32).unwrap_or(0.0);
                let y0 = r.get(1).and_then(obj_to_f32).unwrap_or(0.0);
                let x1 = r.get(2).and_then(obj_to_f32).unwrap_or(612.0);
                let y1 = r.get(3).and_then(obj_to_f32).unwrap_or(792.0);
                crate::geometry::Rect::from_points(x0, y0, x1, y1)
            });

        let rotation = page_dict
            .get("Rotate")
            .map(|o| self.resolve_obj_ref(o))
            .as_ref()
            .and_then(|o| match o {
                Object::Integer(i) => Some(*i as i32),
                Object::Real(r) => Some(*r as i32),
                _ => None,
            })
            .unwrap_or(0);

        Ok(PageInfo {
            media_box,
            crop_box,
            rotation,
        })
    }

    /// Get the resources dictionary for a page.
    ///
    /// Resources contain fonts, images, patterns, and other objects
    /// used when rendering the page.
    pub fn get_page_resources(&self, page_index: usize) -> Result<Object> {
        let page = self.get_page(page_index)?;
        let page_dict = page.as_dict().ok_or_else(|| Error::ParseError {
            offset: 0,
            reason: "Page is not a dictionary".to_string(),
        })?;

        let resources = page_dict
            .get("Resources")
            .cloned()
            .unwrap_or(Object::Dictionary(std::collections::HashMap::new()));

        if let Some(ref_val) = resources.as_reference() {
            self.load_object(ref_val)
        } else {
            Ok(resources)
        }
    }
}
