//! Read-only XFA document analysis.
//!
//! This module reports on the XFA form structure of a document (field
//! count, page count, field types) without converting it. It has no
//! dependency on the PDF writer.

use super::extractor::XfaExtractor;
use super::parser::XfaParser;
use crate::document::PdfDocument;
use crate::error::Result;

/// Result of XFA document analysis.
#[derive(Debug, Clone)]
pub struct XfaAnalysis {
    /// Whether the document contains XFA forms
    pub has_xfa: bool,
    /// Number of fields found (if XFA present)
    pub field_count: Option<usize>,
    /// Number of pages found (if XFA present)
    pub page_count: Option<usize>,
    /// Field types found
    pub field_types: Vec<String>,
}

/// Analyze an XFA document without converting.
///
/// This function provides information about the XFA form structure
/// without performing the full conversion.
///
/// # Example
///
/// ```ignore
/// use xberg_native_pdf::PdfDocument;
/// use xberg_native_pdf::xfa::analyze_xfa_document;
///
/// let mut doc = PdfDocument::open("form.pdf")?;
/// let analysis = analyze_xfa_document(&mut doc)?;
///
/// if analysis.has_xfa {
///     println!("Found {} fields across {} pages",
///         analysis.field_count.unwrap_or(0),
///         analysis.page_count.unwrap_or(0));
/// }
/// ```
pub fn analyze_xfa_document(doc: &mut PdfDocument) -> Result<XfaAnalysis> {
    let has_xfa = XfaExtractor::has_xfa(doc)?;

    if !has_xfa {
        return Ok(XfaAnalysis {
            has_xfa: false,
            field_count: None,
            page_count: None,
            field_types: Vec::new(),
        });
    }

    let xfa_data = XfaExtractor::extract_xfa(doc)?;
    let mut parser = XfaParser::new();
    let xfa_form = parser.parse(&xfa_data)?;

    let mut field_types: Vec<String> = xfa_form.fields.iter().map(|f| format!("{:?}", f.field_type)).collect();
    field_types.sort();
    field_types.dedup();

    Ok(XfaAnalysis {
        has_xfa: true,
        field_count: Some(xfa_form.field_count()),
        page_count: Some(if xfa_form.pages.is_empty() {
            1
        } else {
            xfa_form.pages.len()
        }),
        field_types,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const SIMPLE_PDF: &[u8] = include_bytes!("../../tests/fixtures/simple.pdf");

    #[test]
    fn analyze_xfa_document_should_report_no_xfa_for_a_plain_pdf() {
        let mut doc = PdfDocument::from_bytes(SIMPLE_PDF.to_vec()).expect("simple.pdf should parse");

        let analysis = analyze_xfa_document(&mut doc).expect("analysis should not fail on a non-XFA document");

        assert!(!analysis.has_xfa);
        assert_eq!(analysis.field_count, None);
        assert_eq!(analysis.page_count, None);
        assert!(analysis.field_types.is_empty());
    }
}
