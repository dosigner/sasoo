//! Third-party code vendored directly into this crate rather than pulled in
//! as a Cargo dependency, typically because it needed non-trivial surgery
//! (e.g. an unsafe code path removed, or an internal parser swapped out)
//! that isn't appropriate to carry as a patched fork of someone else's crate.
//!
//! See `ATTRIBUTIONS.md` at the repository root for the licensing terms of
//! everything vendored here.

pub(crate) mod fontdb;
