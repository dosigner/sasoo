//! Adobe-GB1 (Simplified Chinese) CID to Unicode mappings.
//!
//! Generated from Adobe cid2code.txt (UniGB-UCS2-H + UTF16/UTF32 fallback)
//! Source: <https://github.com/adobe-type-tools/cmap-resources>
//!
//! Coverage: 29983 CID-to-Unicode mappings
//! Characters: GB 2312, GBK, GB 18030
//!
//! Adobe Technical Note #5079: Adobe-GB1 Character Collection

// Split into sibling `adobe_gb1/partNN.rs` chunks to satisfy the file-too-long lint
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
mod part20;
mod part21;
mod part22;
mod part23;
mod part24;
mod part25;
mod part26;
mod part27;
mod part28;
mod part29;
mod part30;
mod part31;
mod part32;
mod part33;
mod part34;

/// CID to Unicode mapping for Adobe-GB1 character collection.
///
/// 29983 entries merged from UniGB-UCS2-H, UTF16, and UTF32 CMaps.
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
        .or_else(|| part20::PART20.get(&cid).copied())
        .or_else(|| part21::PART21.get(&cid).copied())
        .or_else(|| part22::PART22.get(&cid).copied())
        .or_else(|| part23::PART23.get(&cid).copied())
        .or_else(|| part24::PART24.get(&cid).copied())
        .or_else(|| part25::PART25.get(&cid).copied())
        .or_else(|| part26::PART26.get(&cid).copied())
        .or_else(|| part27::PART27.get(&cid).copied())
        .or_else(|| part28::PART28.get(&cid).copied())
        .or_else(|| part29::PART29.get(&cid).copied())
        .or_else(|| part30::PART30.get(&cid).copied())
        .or_else(|| part31::PART31.get(&cid).copied())
        .or_else(|| part32::PART32.get(&cid).copied())
        .or_else(|| part33::PART33.get(&cid).copied())
        .or_else(|| part34::PART34.get(&cid).copied())
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
        + part20::PART20.len()
        + part21::PART21.len()
        + part22::PART22.len()
        + part23::PART23.len()
        + part24::PART24.len()
        + part25::PART25.len()
        + part26::PART26.len()
        + part27::PART27.len()
        + part28::PART28.len()
        + part29::PART29.len()
        + part30::PART30.len()
        + part31::PART31.len()
        + part32::PART32.len()
        + part33::PART33.len()
        + part34::PART34.len()
}

/// Look up Unicode code point for a CID in Adobe-GB1.
pub fn lookup(cid: u16) -> Option<u32> {
    if let Some(unicode) = cid_to_unicode(cid) {
        return Some(unicode);
    }

    match cid {
        0x4E00..=0x9FFF => Some(cid as u32),
        0x3400..=0x4DBF => Some(cid as u32),
        0x2E80..=0x2EFF => Some(cid as u32),
        0x3000..=0x303F => Some(cid as u32),
        0xF900..=0xFAFF => Some(cid as u32),
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
        assert!(cid_to_unicode_len() >= 29973);
    }
}
