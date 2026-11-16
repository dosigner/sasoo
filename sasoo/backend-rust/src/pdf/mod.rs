pub mod artifacts;
pub mod coordinates;
#[cfg(feature = "pdf-xberg-native")]
pub mod import;
pub mod legacy_context;
pub mod legacy_helper;
#[cfg(feature = "pdf-xberg-native")]
pub mod native;
#[cfg(feature = "pdf-xberg-native")]
pub mod process;
pub mod types;

pub use coordinates::{to_pdf_user_space, to_physical_points};
pub use legacy_helper::{LegacyHelperRequest, import_legacy_response};
pub use types::*;

use tokio_util::sync::CancellationToken;

use crate::error::{Result, SasooError};

pub fn extract_document(
    input: &PdfInput,
    options: &PdfOptions,
    cancel: &CancellationToken,
) -> Result<DocumentArtifact> {
    if cancel.is_cancelled() {
        return Err(SasooError::Incomplete(
            "PDF extraction was cancelled before dispatch".into(),
        ));
    }
    if !input.path.is_absolute()
        || options.engine.name.trim().is_empty()
        || options.profile.trim().is_empty()
    {
        return Err(SasooError::InvalidInput(
            "PDF extraction requires an absolute source path and explicit engine/profile".into(),
        ));
    }
    if options.engine.name == "xberg-native-pdf" {
        #[cfg(feature = "pdf-xberg-native")]
        return native::extract(input, options, cancel);
        #[cfg(not(feature = "pdf-xberg-native"))]
        return Err(SasooError::Unsupported(
            "PDF engine 'xberg-native-pdf' requires a build with --features pdf-xberg-native; no fallback was run".into(),
        ));
    }
    Err(SasooError::Unsupported(format!(
        "PDF engine '{}' is not configured; no automatic fallback was run",
        options.engine.name
    )))
}
