// AUTO-GENERATED from Adobe Glyph List
// Source: https://github.com/adobe-type-tools/agl-aglfn
// License: BSD-3-Clause ~keep

// Split into sibling `adobe_glyph_list/partNN.rs` chunks to satisfy the file-too-long lint
// (GH#1567); the map's keys/values are unchanged, only sharded across files. ~keep
mod part01;
mod part02;
mod part03;
mod part04;
mod part05;

/// Adobe Glyph List - complete 4000+ glyph name to Unicode mapping
pub(crate) struct AdobeGlyphList;

impl AdobeGlyphList {
    /// Look up the Unicode code point for a glyph name in the Adobe Glyph List.
    pub(crate) fn get(&self, name: &str) -> Option<&char> {
        part01::PART01
            .get(name)
            .or_else(|| part02::PART02.get(name))
            .or_else(|| part03::PART03.get(name))
            .or_else(|| part04::PART04.get(name))
            .or_else(|| part05::PART05.get(name))
    }
}

pub(crate) static ADOBE_GLYPH_LIST: AdobeGlyphList = AdobeGlyphList;

// Total entries: 4281
