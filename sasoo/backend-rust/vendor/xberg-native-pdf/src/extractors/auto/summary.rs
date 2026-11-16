//! Aggregate per-document summarisation, split out of `auto.rs` purely for
//! file size. Re-exported as `auto::summarise`. ~keep

use super::{DocumentSummary, PageKind};

/// Roll per-page kinds into a [`DocumentSummary`] (case Q — never a
/// forced single doc mode; this is an *aggregate* only).
#[must_use]
pub fn summarise(pages: &[PageKind]) -> DocumentSummary {
    if pages.is_empty() || pages.iter().all(|k| *k == PageKind::Empty) {
        return DocumentSummary::Empty;
    }
    let non_empty: Vec<&PageKind> = pages.iter().filter(|k| **k != PageKind::Empty).collect();
    let text = non_empty.iter().filter(|k| matches!(k, PageKind::TextLayer)).count();
    let scanned = non_empty.iter().filter(|k| matches!(k, PageKind::Scanned)).count();
    let n = non_empty.len();
    if text * 100 >= n * 80 {
        DocumentSummary::MostlyText
    } else if scanned * 100 >= n * 80 {
        DocumentSummary::MostlyScanned
    } else {
        DocumentSummary::Mixed
    }
}
