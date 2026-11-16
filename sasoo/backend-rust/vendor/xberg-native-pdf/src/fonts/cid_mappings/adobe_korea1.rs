//! Adobe-Korea1 (Korean) CID to Unicode mappings.
//!
//! Generated from Adobe cid2code.txt (UniKS-UCS2-H + UTF16/UTF32 fallback)
//! Source: <https://github.com/adobe-type-tools/cmap-resources>
//!
//! Coverage: 17097 CID-to-Unicode mappings
//! Characters: KS X 1001, Hangul syllables, Hanja
//!
//! Adobe Technical Note #5093: Adobe-Korea1 Character Collection

// Split into sibling `adobe_korea1/partNN.rs` chunks to satisfy the file-too-long lint
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
mod part18;
mod part19;

/// CID to Unicode mapping for Adobe-Korea1 character collection.
///
/// 17097 entries merged from UniKS-UCS2-H, UTF16, and UTF32 CMaps.
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
        .or_else(|| part18::PART18.get(&cid).copied())
        .or_else(|| part19::PART19.get(&cid).copied())
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
        + part18::PART18.len()
        + part19::PART19.len()
}

/// Look up Unicode code point for a CID in Adobe-Korea1.
pub fn lookup(cid: u16) -> Option<u32> {
    if let Some(unicode) = cid_to_unicode(cid) {
        return Some(unicode);
    }

    match cid {
        0x1100..=0x11FF => Some(cid as u32),
        0x3130..=0x318F => Some(cid as u32),
        0xAC00..=0xD7AF => Some(cid as u32),
        0xA960..=0xA97F => Some(cid as u32),
        0xD7B0..=0xD7FF => Some(cid as u32),
        0x4E00..=0x9FFF => Some(cid as u32),
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
        assert!(cid_to_unicode_len() >= 17087);
    }
}
