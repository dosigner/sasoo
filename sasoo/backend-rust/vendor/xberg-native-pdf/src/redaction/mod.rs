//! True / destructive redaction and document sanitization.
//!
//! Replaces the prior *cosmetic* redaction (a filled rectangle drawn over
//! content whose underlying bytes survived) with physical content removal
//! and a document-wide sanitization pass, per ISO 32000-1:2008 §12.5.6.23:
//! *"shall remove all traces of the specified content … clipping or image
//! masks shall not be used to hide that data."*
//!
//! **Scope, so callers do not assume more than this delivers: redaction
//! here removes *text*.** Glyphs whose mapped boxes fall in a region are
//! physically dropped from the content stream, and [`sanitize`] scrubs the
//! document catalog. Embedded font programs are NOT subset to drop redacted
//! glyph outlines, image samples under a region are NOT resampled, and
//! vector paths crossing a region are NOT clipped. Speculative,
//! never-wired implementations of those three were removed rather than
//! left to imply coverage that does not exist. A document whose sensitive
//! content is an image or a vector drawing is not fully served by this
//! module today.

#![forbid(unsafe_code)]

pub mod classify;
pub mod engine;
pub mod options;
pub mod overlay;
pub mod region;
pub mod sanitize;
pub mod serialize;
pub mod text_engine;
pub mod text_prune;

pub use engine::{FontInfoMetrics, redact_content_stream};
pub use options::{OcgPolicy, RedactionOptions, RedactionReport};
pub use region::{DEFAULT_EDGE_PADDING, RedactionRegion, RegionSet};
pub use sanitize::{CatalogScrub, SanitizeCounts, sanitize_catalog};
