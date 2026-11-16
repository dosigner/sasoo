//! XFA (XML Forms Architecture) support.
//!
//! This module provides limited support for XFA forms in PDF documents.
//! XFA is an XML-based form specification used in some PDFs, particularly
//! government and financial forms.
//!
//! # Features
//!
//! - Parse XFA template and datasets
//! - Extract field definitions and values
//! - Analyze XFA form structure (field count, page count, field types)
//!
//! # Limitations
//!
//! This module is read-only: it parses and reports on XFA form structure,
//! it does not convert XFA to AcroForm or write PDFs.
//!
//! # Example
//!
//! ```ignore
//! use xberg_native_pdf::xfa::{XfaExtractor, XfaParser};
//! use xberg_native_pdf::PdfDocument;
//!
//! let mut doc = PdfDocument::open("form.pdf")?;
//!
//! // Check if document has XFA form
//! if XfaExtractor::has_xfa(&mut doc)? {
//!     // Extract and parse XFA data
//!     let xfa_data = XfaExtractor::extract_xfa(&mut doc)?;
//!
//!     let mut parser = XfaParser::new();
//!     let form = parser.parse(&xfa_data)?;
//!     println!("Parsed {} fields", form.field_count());
//! }
//! ```

mod analysis;
mod extractor;
mod parser;

pub use analysis::{XfaAnalysis, analyze_xfa_document};
pub use extractor::XfaExtractor;
pub use parser::{XfaField, XfaFieldType, XfaForm, XfaOption, XfaPage, XfaParser, is_xfa_data};
