# xberg-native-pdf

Pure-Rust PDF parsing, extraction and rendering — the native PDF engine behind
[xberg](https://github.com/xberg-io/xberg).

This crate is published so that `xberg` can depend on it from crates.io, but it is developed as
part of the xberg workspace and its API moves with xberg's needs rather than to a separate
compatibility promise. If you want a general-purpose PDF library, you probably want something
else.

## What it does

- Text extraction with positioned spans, reading order and column detection
- Tables, forms (AcroForm and XFA), annotations and outlines
- Page rendering to raster, including image masks, shadings and transparency groups
- Encryption (RC4 and AES, including AES-256/R6)
- Document editing and writing

## Features

Everything the crate can do is unconditional. The only two knobs bundle multi-megabyte CJK
fonts via `include_bytes!`, and are opt-in because xberg's WASM bundle sits inside a hard CDN
size budget:

| Feature | Effect |
|---|---|
| `cjk-form-fonts` | Bundles a CJK font for form-field appearance generation |
| `cjk-render-fallback` | Bundles a CJK fallback font for page rendering |

## Diagnostics

The crate emits `tracing` events rather than writing to stdout or stderr. Every target is rooted
at [`LOG_TARGET_ROOT`], which is `module_path!()` evaluated at the crate root — filter on that
constant rather than on a copied string literal, so your filter cannot silently stop matching if
the crate is ever renamed again.

## Provenance and licence

MIT. This crate began as a fork of a third-party project; that project, its author, its licence,
and the vendored code and bundled fonts this crate carries are all recorded in
[`ATTRIBUTIONS.md`](ATTRIBUTIONS.md) and in the repository's root `ATTRIBUTIONS.md`. The upstream
copyright notice is preserved in [`LICENSE`](LICENSE). No endorsement by or affiliation with the
upstream project is implied.
