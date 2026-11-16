//! Convenience re-exports for read-path PDF operations.
//!
//! This module gathers read-only functionality -- element extraction, page
//! labels, XMP metadata, text search, rendering, and XFA analysis -- behind
//! a single `api::` path for callers who don't want to import each
//! sub-module individually. It has no PDF creation, editing, or annotation
//! building capability; those live on the document/extraction types
//! directly.
//!
//! ## Example
//!
//! ```ignore
//! use xberg_native_pdf::api::{SearchOptions, TextSearcher};
//! use xberg_native_pdf::PdfDocument;
//!
//! let doc = PdfDocument::open("input.pdf")?;
//! let results = TextSearcher::search(&doc, "Hello", &SearchOptions::default())?;
//! ```

pub use crate::document::ReadingOrder;

pub use crate::geometry::Rect;

pub use crate::elements::{ImageContent, PathContent, TableContent, TextContent};

pub use crate::extractors::page_labels::{PageLabelExtractor, PageLabelRange, PageLabelStyle};

pub use crate::extractors::xmp::{XmpExtractor, XmpMetadata};

pub use crate::search::{SearchOptions, SearchResult, TextSearcher};

pub use crate::rendering::{ImageFormat, PageRenderer, RenderOptions, RenderedImage};

pub use crate::xfa::{
    XfaAnalysis, XfaExtractor, XfaField, XfaFieldType, XfaForm, XfaOption, XfaPage, XfaParser, analyze_xfa_document,
};
