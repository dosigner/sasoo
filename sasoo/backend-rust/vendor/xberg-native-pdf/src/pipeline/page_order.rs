//! Canonical page reading order — single source of truth for text-extraction
//! span ordering.
//!
//! Resolution per PDF 32000-1:2008:
//!
//!   1. **Tagged PDF** (`/MarkInfo /Marked true`) with a `/StructTreeRoot`
//!      and `/Suspects != true`: walk the structure tree on this page and
//!      return spans in **logical structure order** (§14.7.2). This is the
//!      authoritative reading order when present.
//!
//!   2. **Otherwise**: return spans in **page content order** — the
//!      geometric top-to-bottom + left-to-right pass described in §14.8.2.3.1.
//!
//! All public text-extraction APIs (`extract_words`, `extract_text_lines`,
//! `extract_text`, `to_markdown`, `to_html`, `to_plain_text`) should consume
//! this function so they cannot drift apart on the same input.
//!
//! The `StructureTreeStrategy` it dispatches to already falls back to the
//! geometric strategy when the structure tree is suspect (§14.7.1) or when
//! the MCID order would zigzag horizontally across columns — both
//! defenses against producer bugs that this helper inherits transparently.

use crate::document::PdfDocument;
use crate::error::Result;
use crate::geometry::Rect;
use crate::pipeline::{OrderedTextSpan, ReadingOrderContext, TextPipeline, TextPipelineConfig};

/// Compute the canonical reading-order span sequence for a single page.
///
/// Returns an empty vector when the page has no extractable text.
///
/// All extracted spans are returned by default — including any that the
/// upstream extractor tagged as `/Artifact` (running headers, footers,
/// page numbers, watermarks; ISO 32000-1:2008 §14.8.2.2.1). Some
/// downstream callers (e.g. `extract_text` on untagged PDFs) apply
/// their own artifact filter. Use
/// [`page_reading_order_no_artifacts`] for the spec-correct
/// "exclude artifacts" variant.
///
/// # Errors
///
/// Returns the underlying parse / extraction error if span extraction
/// itself fails. Structure-tree resolution errors are tolerated and the
/// helper falls back to geometric order.
pub fn page_reading_order(doc: &PdfDocument, page_index: usize) -> Result<Vec<OrderedTextSpan>> {
    page_reading_order_inner(doc, page_index, true)
}

/// Variant of [`page_reading_order`] that drops spans flagged as
/// `/Artifact` (running headers, footers, page numbers, watermarks;
/// ISO 32000-1:2008 §14.8.2.2.1).
pub fn page_reading_order_no_artifacts(doc: &PdfDocument, page_index: usize) -> Result<Vec<OrderedTextSpan>> {
    page_reading_order_inner(doc, page_index, false)
}

fn page_reading_order_inner(
    doc: &PdfDocument,
    page_index: usize,
    include_artifacts: bool,
) -> Result<Vec<OrderedTextSpan>> {
    let mut spans = doc.extract_spans(page_index)?;
    if !include_artifacts {
        spans.retain(|s| s.artifact_type.is_none());
    }
    if spans.is_empty() {
        return Ok(Vec::new());
    }

    order_page_spans(doc, page_index, spans)
}

/// Apply the canonical page reading-order pipeline to spans already extracted
/// from `page_index`.
///
/// This is equivalent to [`page_reading_order`] after extraction, and lets
/// callers preserve span filters without parsing the page content a second time.
/// Every span must originate from `doc` and the same `page_index`; mixing pages
/// or documents produces undefined ordering semantics. <!-- ~keep -->
///
/// # Errors
///
/// Returns an error when page metadata or reading-order context cannot be read.
pub fn order_page_spans(
    doc: &PdfDocument,
    page_index: usize,
    spans: Vec<crate::layout::TextSpan>,
) -> Result<Vec<OrderedTextSpan>> {
    if spans.is_empty() {
        return Ok(Vec::new());
    }

    // Tier 1 (logical structure order) → Tier 2 (article threads) → Tier 3
    // (geometric). A sweep showed a bare ≥80%-bead-coverage gate
    // regressed single-column books (it reordered content non-improvingly), so
    // Tier 2 only activates behind the conservative multi-column +
    // order-divergence gate in `page_article_bead_rects` — which is provably a
    // no-op on single-column / geometric-order threads. ~keep
    let mut context = build_context(doc, page_index);
    // `build_context` has no spans, and the gutter is a property of them.
    // This is the third and last XY-cut entry point on an output path; the
    // heading-run pre-pass is inert without it (GH#1757). ~keep
    if let Some(gutter_x) = PdfDocument::detect_column_gutter(&spans) {
        context = context.with_column_gutter(gutter_x);
    }
    if !context.has_structure_tree
        && let Some(beads) = page_article_bead_rects(doc, page_index, &spans)
    {
        context = context.with_bead_rects(beads);
    }

    let pipeline = TextPipeline::with_config(TextPipelineConfig::default());

    // Text-matrix-rotated content. Gated to unrotated pages:
    // on a `/Rotate`d page `postprocess_spans` already mapped
    // rotated-content spans into the displayed frame, so their retained
    // `rotation_degrees` describes the pre-display frame and re-rotating
    // here would double-transform. ~keep
    if doc.get_page_rotation(page_index).unwrap_or(0) == 0 {
        // A dominant rotation (a landscape table typeset on a portrait
        // page) reorders the WHOLE page in the rotated reading frame. ~keep
        if let Some(rot) = crate::utils::dominant_rotation(&spans).and_then(reading_frame_quadrant) {
            tracing::debug!(
                page_index,
                rotation_degrees = rot,
                "dominant text rotation — ordering in rotated frame"
            );
            return order_in_rotated_frame(doc, page_index, spans, context, &pipeline, rot);
        }
        // Otherwise mirror the span path's per-span rotation firewall:
        // rotated minority runs (margin stamps, figure labels) break the
        // axis-aligned assumptions of the geometric strategies, so lift
        // them out, order each rotation group in its upright frame, and
        // append after the horizontal flow. ~keep
        if spans.iter().any(|s| s.rotation_degrees != 0.0) {
            let (rotated, upright): (Vec<_>, Vec<_>) = spans.into_iter().partition(|s| s.rotation_degrees != 0.0);
            tracing::debug!(
                page_index,
                count = rotated.len(),
                "rotated minority span(s) appended after the horizontal flow"
            );
            let mut ordered = if upright.is_empty() {
                Vec::new()
            } else {
                pipeline.process(upright, context)?
            };
            let base = ordered.len();
            ordered.extend(
                PdfDocument::order_rotated_blocks(rotated)
                    .into_iter()
                    .enumerate()
                    .map(|(i, s)| OrderedTextSpan::new(s, base + i)),
            );
            return Ok(ordered);
        }
    }

    pipeline.process(spans, context)
}

/// Display-rotation quadrant that turns text of the given snapped rotation
/// upright: `90°` text (reading bottom-to-top) becomes readable when the
/// page is displayed as if `/Rotate 90`, `-90°` under `/Rotate 270`, and
/// `180°` under `/Rotate 180`. Mirrored or free-angle runs (which
/// `snap_run_rotation` reports as raw angles) have no quadrant frame.
fn reading_frame_quadrant(degrees: f32) -> Option<i32> {
    for (deg, rot) in [(90.0, 90), (180.0, 180), (-90.0, 270)] {
        if (degrees - deg).abs() < 0.5 {
            return Some(rot);
        }
    }
    None
}

/// Order a dominant-rotation page in its rotated reading frame: map every
/// span bbox through the display rotation (so the text becomes horizontal),
/// run the standard pipeline there, then map the bboxes back so callers see
/// true page coordinates — only the ORDER reflects the rotated frame.
fn order_in_rotated_frame(
    doc: &PdfDocument,
    page_index: usize,
    mut spans: Vec<crate::layout::TextSpan>,
    context: ReadingOrderContext,
    pipeline: &TextPipeline,
    rot: i32,
) -> Result<Vec<OrderedTextSpan>> {
    let (llx, lly, urx, ury) = doc.get_page_media_box(page_index).unwrap_or((0.0, 0.0, 612.0, 792.0));
    let (w, h) = (urx - llx, ury - lly);

    // Rotated spans store TEXT-LOCAL extents (origin + advance-along-the-
    // run as `width` + font size as `height`), so mapping into the reading
    // frame rotates the ORIGIN as a point — through the same quadrant map
    // as `PdfDocument::rotate_span_bbox` — and keeps the extents, which
    // already describe the run in its own upright frame. This mirrors
    // `order_rotated_blocks`, which sorts rotated origins the same way. ~keep
    let map_origin = |x: f32, y: f32, rot: i32, fw: f32, fh: f32| -> (f32, f32) {
        let (rx, ry) = (x - llx, y - lly);
        let (mx, my) = match rot {
            90 => (ry, fw - rx),
            180 => (fw - rx, fh - ry),
            270 => (fh - ry, rx),
            _ => (rx, ry),
        };
        (llx + mx, lly + my)
    };

    for s in &mut spans {
        let (x, y) = map_origin(s.bbox.x, s.bbox.y, rot, w, h);
        s.bbox.x = x;
        s.bbox.y = y;
    }
    // The rotated frame swaps the page dimensions for 90°/270°. ~keep
    let (fw, fh) = if rot % 180 == 90 { (h, w) } else { (w, h) };
    let context = context.with_bbox(Rect::new(llx, lly, fw, fh));

    let mut ordered = pipeline.process(spans, context)?;

    // Inverse map: the opposite quadrant applied with the rotated frame's
    // dimensions. `w - (w - x)` round-trips within ~1 ULP of the page
    // dimension in f32 (≈6e-5 pt on a Letter page) — well inside every
    // downstream tolerance, but not bit-exact. ~keep
    let inv = (360 - rot) % 360;
    for os in &mut ordered {
        let (x, y) = map_origin(os.span.bbox.x, os.span.bbox.y, inv, fw, fh);
        os.span.bbox.x = x;
        os.span.bbox.y = y;
    }
    Ok(ordered)
}

/// Article-thread bead rectangles for `page_index`, in `/N` chain order,
/// when a conservative gate confirms a thread genuinely governs this page.
///
/// All conditions are required — a corpus sweep found a bare
/// ≥80%-coverage gate regressed single-column books by reordering them
/// non-improvingly:
///   1. **≥2 beads** on the page (nothing to reorder otherwise).
///   2. **Coverage** — ≥80% of non-empty span centres fall inside some bead.
///   3. **Multi-column** — the beads occupy ≥2 disjoint horizontal bands; a
///      single-column thread adds nothing over geometric order (this is the
///      gate that excludes the technical books the prior attempt regressed).
///   4. **Order-divergence** — the `/N` bead order differs from the naive
///      geometric order (top-to-bottom, left-to-right). When they coincide the
///      thread reorders nothing, so skipping keeps output byte-identical.
fn page_article_bead_rects(
    doc: &PdfDocument,
    page_index: usize,
    spans: &[crate::layout::TextSpan],
) -> Option<Vec<Rect>> {
    let threads = doc.cached_article_threads();
    if threads.is_empty() {
        return None;
    }
    let beads: Vec<Rect> = threads
        .iter()
        .flat_map(|t| t.beads.iter())
        .filter(|b| b.page_index == page_index)
        .map(|b| b.rect)
        .collect();
    if beads.len() < 2 {
        return None;
    }

    let body: Vec<&crate::layout::TextSpan> = spans.iter().filter(|s| !s.text.trim().is_empty()).collect();
    if body.is_empty() {
        return None;
    }
    let inside = |r: &Rect, x: f32, y: f32| x >= r.x && x <= r.x + r.width && y >= r.y && y <= r.y + r.height;
    let covered = body
        .iter()
        .filter(|s| {
            let cx = s.bbox.x + s.bbox.width * 0.5;
            let cy = s.bbox.y + s.bbox.height * 0.5;
            beads.iter().any(|r| inside(r, cx, cy))
        })
        .count();
    if (covered as f32) < 0.8 * body.len() as f32 {
        return None;
    }

    let mut xs: Vec<(f32, f32)> = beads.iter().map(|r| (r.x, r.x + r.width)).collect();
    xs.sort_by(|a, b| crate::utils::safe_float_cmp(a.0, b.0));
    let mut bands = 1usize;
    let mut cover_right = xs[0].1;
    for &(l, r) in &xs[1..] {
        if l > cover_right {
            bands += 1;
        }
        cover_right = cover_right.max(r);
    }
    if bands < 2 {
        return None;
    }

    let mut geom: Vec<Rect> = beads.clone();
    geom.sort_by(|a, b| {
        let y = crate::utils::safe_float_cmp(b.y, a.y); // larger y = higher on page ~keep
        if y != std::cmp::Ordering::Equal {
            return y;
        }
        crate::utils::safe_float_cmp(a.x, b.x)
    });
    let same_order = beads.iter().zip(geom.iter()).all(|(a, b)| a.x == b.x && a.y == b.y);
    if same_order {
        return None;
    }

    Some(beads)
}

/// Build the `ReadingOrderContext` for a page from the document's
/// `MarkInfo`, `StructTreeRoot`, and media box.
///
/// Best-effort: any errors reading structure metadata produce a context
/// without MCID order, which means the pipeline takes the geometric path.
pub(crate) fn build_context(doc: &PdfDocument, page_index: usize) -> ReadingOrderContext {
    let media_box = doc.get_page_media_box(page_index).unwrap_or((0.0, 0.0, 612.0, 792.0));
    // MediaBox is `(llx, lly, urx, ury)` per PDF 32000-1:2008 §7.7.3.3.
    // `Rect::new` expects `(x, y, width, height)`, so use `from_points`. ~keep
    let bbox = Rect::from_points(media_box.0, media_box.1, media_box.2, media_box.3);

    let mut ctx = ReadingOrderContext::new().with_page(page_index as u32).with_bbox(bbox);

    // Use logical structure order only when the tree is trustworthy
    // (§14.8.2.3.1 / §14.7.1): the document is /Marked or the catalog references
    // a /StructTreeRoot, and /MarkInfo /Suspects is not true. This accepts
    // PDF-1.4 catalog-only tagged files that the old `!marked` early-return
    // wrongly skipped, and rejects suspect trees. ~keep
    let Some(tree) = doc.struct_tree_trustworthy() else {
        return ctx;
    };

    // Use the all-pages traversal cache (O(1) per page) instead of re-walking
    // the whole structure tree here (≈ O(pages²) across a tagged document).
    // Reading-order strategies only need the bare MCID sequence (for
    // geometric checks); they don't disambiguate by content-stream
    // scope. Project the scoped list down to MCID-only here. ~keep
    let mcid_order: Vec<u32> = doc
        .cached_mcid_order_for_page(&tree, page_index as u32)
        .into_iter()
        .map(|(_scope, m)| m)
        .collect();

    if !mcid_order.is_empty() {
        ctx = ctx.with_mcid_order(mcid_order);
    }
    // The predicate already vetted the tree as non-suspect, so the strategy's
    // own suspect guard is a no-op here. ~keep
    ctx = ctx.with_suspects(false);
    ctx
}
