//! Adobe-Japan1 (Japanese) CID to Unicode mappings.
//!
//! Generated from Adobe cid2code.txt (UniJIS-UCS2-H + UTF16/UTF32 fallback)
//! Source: <https://github.com/adobe-type-tools/cmap-resources>
//!
//! Coverage: 15277 CID-to-Unicode mappings
//! Characters: JIS X 0208, JIS X 0212, Hiragana, Katakana, CJK Ideographs
//!
//! Adobe Technical Note #5078: Adobe-Japan1 Character Collection

// Split into sibling `adobe_japan1/partNN.rs` chunks to satisfy the file-too-long lint
// (GH#1567); the map's keys/values are unchanged, only sharded across files. ~keep
mod part01;
mod part02;
mod part03;
mod part04;
mod part05;
mod part06;
mod part07;
mod part08;
mod part09;
mod part10;
mod part11;
mod part12;
mod part13;
mod part14;
mod part15;
mod part16;
mod part17;

/// CID to Unicode mapping for Adobe-Japan1 character collection.
///
/// 15277 entries merged from UniJIS-UCS2-H, UTF16, and UTF32 CMaps.
fn cid_to_unicode(cid: u16) -> Option<u32> {
    part01::PART01
        .get(&cid)
        .copied()
        .or_else(|| part02::PART02.get(&cid).copied())
        .or_else(|| part03::PART03.get(&cid).copied())
        .or_else(|| part04::PART04.get(&cid).copied())
        .or_else(|| part05::PART05.get(&cid).copied())
        .or_else(|| part06::PART06.get(&cid).copied())
        .or_else(|| part07::PART07.get(&cid).copied())
        .or_else(|| part08::PART08.get(&cid).copied())
        .or_else(|| part09::PART09.get(&cid).copied())
        .or_else(|| part10::PART10.get(&cid).copied())
        .or_else(|| part11::PART11.get(&cid).copied())
        .or_else(|| part12::PART12.get(&cid).copied())
        .or_else(|| part13::PART13.get(&cid).copied())
        .or_else(|| part14::PART14.get(&cid).copied())
        .or_else(|| part15::PART15.get(&cid).copied())
        .or_else(|| part16::PART16.get(&cid).copied())
        .or_else(|| part17::PART17.get(&cid).copied())
}

#[cfg(test)]
fn cid_to_unicode_len() -> usize {
    part01::PART01.len()
        + part02::PART02.len()
        + part03::PART03.len()
        + part04::PART04.len()
        + part05::PART05.len()
        + part06::PART06.len()
        + part07::PART07.len()
        + part08::PART08.len()
        + part09::PART09.len()
        + part10::PART10.len()
        + part11::PART11.len()
        + part12::PART12.len()
        + part13::PART13.len()
        + part14::PART14.len()
        + part15::PART15.len()
        + part16::PART16.len()
        + part17::PART17.len()
}

/// Look up Unicode code point for a CID in Adobe-Japan1.
pub fn lookup(cid: u16) -> Option<u32> {
    if let Some(unicode) = cid_to_unicode(cid) {
        return Some(unicode);
    }

    match cid {
        0x3040..=0x309F => Some(cid as u32),
        0x30A0..=0x30FF => Some(cid as u32),
        0x4E00..=0x9FFF => Some(cid as u32),
        0xFF00..=0xFF5F => Some(cid as u32),
        0xFF65..=0xFF9F => Some(cid as u32),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ascii_range() {
        assert_eq!(lookup(1), Some(0x0020));
        assert_eq!(lookup(34), Some(0x0041));
        assert_eq!(lookup(91), Some(0x007A));
    }

    #[test]
    fn test_mapping_count() {
        assert!(cid_to_unicode_len() >= 15267);
    }
}
