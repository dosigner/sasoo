//! Logging utilities for the text extraction pipeline.
//!
//! These macros forward to the `tracing` crate, which is emitted unconditionally
//! (no feature gate) by every core library in the stack. Callers install a
//! `tracing-subscriber` (or an OTLP layer) to observe the events; without one,
//! the calls are near-zero cost.
//!
//! Each macro accepts two forms for backward compatibility:
//! 1. A single expression: `extract_log_info!(my_string_var)` — logged as `{}`.
//! 2. A format string with optional args: `extract_log_info!("page {}", n)`.

/// Log an INFO level event. Forwards to `tracing::info!`.
#[macro_export]
macro_rules! extract_log_info {
    ($fmt:literal $(, $($arg:tt)*)?) => {
        ::tracing::info!($fmt $(, $($arg)*)?);
    };
    ($msg:expr) => {
        ::tracing::info!("{}", $msg);
    };
}

/// Log a WARN level event. Forwards to `tracing::warn!`.
#[macro_export]
macro_rules! extract_log_warn {
    ($fmt:literal $(, $($arg:tt)*)?) => {
        ::tracing::warn!($fmt $(, $($arg)*)?);
    };
    ($msg:expr) => {
        ::tracing::warn!("{}", $msg);
    };
}

/// Log a DEBUG level event. Forwards to `tracing::debug!`.
#[macro_export]
macro_rules! extract_log_debug {
    ($fmt:literal $(, $($arg:tt)*)?) => {
        ::tracing::debug!($fmt $(, $($arg)*)?);
    };
    ($msg:expr) => {
        ::tracing::debug!("{}", $msg);
    };
}

/// Log a TRACE level event. Forwards to `tracing::trace!`.
#[macro_export]
macro_rules! extract_log_trace {
    ($fmt:literal $(, $($arg:tt)*)?) => {
        ::tracing::trace!($fmt $(, $($arg)*)?);
    };
    ($msg:expr) => {
        ::tracing::trace!("{}", $msg);
    };
}

/// Log an ERROR level event. Forwards to `tracing::error!`.
#[macro_export]
macro_rules! extract_log_error {
    ($fmt:literal $(, $($arg:tt)*)?) => {
        ::tracing::error!($fmt $(, $($arg)*)?);
    };
    ($msg:expr) => {
        ::tracing::error!("{}", $msg);
    };
}

pub use extract_log_debug;
pub use extract_log_error;
pub use extract_log_info;
pub use extract_log_trace;
pub use extract_log_warn;
