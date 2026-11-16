# Sasoo text-layer-v2 patch

This is the published MIT xberg-native-pdf 1.3.10 source, not a new engine.
SASOO-PROVENANCE.json records the crates.io archive checksum, base Git revision,
and every copied original file hash. LICENSE and ATTRIBUTIONS.md are retained.
Only src/document/spans_text.rs differs from those original files.
SASOO-reading-order.patch is the exact change. The Cargo patch uses this directory;
the Cargo registry source/cache has not been modified.

The glyph-walk assembly groups spans with up to 1.2 em baseline distance and then
sorts a group by X. The old stacked-line guard needs two spans on each line.
Indented adjacent lines with one span per line can therefore be reversed.
The patch stops grouping equal-size, horizontally overlapping spans when their
baselines differ by more than half an em. Font sizes within 0.1 native units count
as equal; overlap must exceed half an em. Mixed-size superscripts retain the
upstream path. These are explicit layout heuristics, not a proof of reading order.

The public regression in tests/pdf_native.rs exercises a real two-line PDF through
the same extract_document API as imports. Its pre-fix output is saved in the
20261116 PDF integration validation directory. The fixed-corpus comparison keeps
all three original PDFs and old extraction versions. No filename, hash, page
number, expected passage, alternate API, or alternate engine selects this patch.

EngineIdentity.revision identifies the upstream base. NATIVE_SETTINGS separately
includes this patch's SHA-256 and the Sasoo v2 adapter identity; PdfOptions hashes
those exact settings bytes. Old stored artifacts are historical data, not new v2
extractions. Upstream tests and all deployment targets have not been certified.
