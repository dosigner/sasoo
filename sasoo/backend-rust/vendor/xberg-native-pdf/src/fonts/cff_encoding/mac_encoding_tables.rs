//! MacRomanEncoding and StandardEncoding byte -> glyph-name tables.
//!
//! Split out of `cff_encoding.rs` purely for file size (GH#1567), mirroring the
//! split used for `adobe_glyph_list.rs`/`adobe_glyph_list/part*.rs`. The mapping
//! itself is unchanged. ~keep

/// Annex D Table D.2 (MacRomanEncoding) byte → glyph name.
///
/// ASCII range 0x20-0x7E shares glyph names with WinAnsi; 0x80-0xFF is
/// the Mac OS Roman repertoire (which is *not* ISO-8859-1). The Apple-logo
/// glyph at 0xF0 (PUA U+F8FF) has no portable glyph name and returns `None`.
pub(super) fn mac_roman_byte_to_name(byte: u8) -> Option<&'static str> {
    use crate::fonts::font_dict::FontInfo;
    if (0x20..=0x7E).contains(&byte) {
        return FontInfo::gid_to_standard_glyph_name(byte as u16);
    }
    match byte {
        0x80..=0xBF => mac_roman_high_byte_to_name_low(byte),
        0xC0..=0xFF => mac_roman_high_byte_to_name_high(byte),
        _ => None,
    }
}

/// MacRomanEncoding byte → glyph name for 0x80-0xBF. Split out of
/// `mac_roman_byte_to_name` purely to keep that function within the
/// repository's line-length guideline; the mapping itself is unchanged. ~keep
fn mac_roman_high_byte_to_name_low(byte: u8) -> Option<&'static str> {
    match byte {
        0x80 => Some("Adieresis"),
        0x81 => Some("Aring"),
        0x82 => Some("Ccedilla"),
        0x83 => Some("Eacute"),
        0x84 => Some("Ntilde"),
        0x85 => Some("Odieresis"),
        0x86 => Some("Udieresis"),
        0x87 => Some("aacute"),
        0x88 => Some("agrave"),
        0x89 => Some("acircumflex"),
        0x8A => Some("adieresis"),
        0x8B => Some("atilde"),
        0x8C => Some("aring"),
        0x8D => Some("ccedilla"),
        0x8E => Some("eacute"),
        0x8F => Some("egrave"),
        0x90 => Some("ecircumflex"),
        0x91 => Some("edieresis"),
        0x92 => Some("iacute"),
        0x93 => Some("igrave"),
        0x94 => Some("icircumflex"),
        0x95 => Some("idieresis"),
        0x96 => Some("ntilde"),
        0x97 => Some("oacute"),
        0x98 => Some("ograve"),
        0x99 => Some("ocircumflex"),
        0x9A => Some("odieresis"),
        0x9B => Some("otilde"),
        0x9C => Some("uacute"),
        0x9D => Some("ugrave"),
        0x9E => Some("ucircumflex"),
        0x9F => Some("udieresis"),
        0xA0 => Some("dagger"),
        0xA1 => Some("degree"),
        0xA2 => Some("cent"),
        0xA3 => Some("sterling"),
        0xA4 => Some("section"),
        0xA5 => Some("bullet"),
        0xA6 => Some("paragraph"),
        0xA7 => Some("germandbls"),
        0xA8 => Some("registered"),
        0xA9 => Some("copyright"),
        0xAA => Some("trademark"),
        0xAB => Some("acute"),
        0xAC => Some("dieresis"),
        0xAD => Some("notequal"),
        0xAE => Some("AE"),
        0xAF => Some("Oslash"),
        0xB0 => Some("infinity"),
        0xB1 => Some("plusminus"),
        0xB2 => Some("lessequal"),
        0xB3 => Some("greaterequal"),
        0xB4 => Some("yen"),
        0xB5 => Some("mu"),
        0xB6 => Some("partialdiff"),
        0xB7 => Some("summation"),
        0xB8 => Some("product"),
        0xB9 => Some("pi"),
        0xBA => Some("integral"),
        0xBB => Some("ordfeminine"),
        0xBC => Some("ordmasculine"),
        0xBD => Some("Omega"),
        0xBE => Some("ae"),
        0xBF => Some("oslash"),
        _ => None,
    }
}

/// MacRomanEncoding byte → glyph name for 0xC0-0xFF. Split out of
/// `mac_roman_byte_to_name` purely to keep that function within the
/// repository's line-length guideline; the mapping itself is unchanged. ~keep
fn mac_roman_high_byte_to_name_high(byte: u8) -> Option<&'static str> {
    match byte {
        0xC0 => Some("questiondown"),
        0xC1 => Some("exclamdown"),
        0xC2 => Some("logicalnot"),
        0xC3 => Some("radical"),
        0xC4 => Some("florin"),
        0xC5 => Some("approxequal"),
        0xC6 => Some("Delta"),
        0xC7 => Some("guillemotleft"),
        0xC8 => Some("guillemotright"),
        0xC9 => Some("ellipsis"),
        0xCA => Some("space"), // nonbreakingspace; the canonical glyph name is "space" ~keep
        0xCB => Some("Agrave"),
        0xCC => Some("Atilde"),
        0xCD => Some("Otilde"),
        0xCE => Some("OE"),
        0xCF => Some("oe"),
        0xD0 => Some("endash"),
        0xD1 => Some("emdash"),
        0xD2 => Some("quotedblleft"),
        0xD3 => Some("quotedblright"),
        0xD4 => Some("quoteleft"),
        0xD5 => Some("quoteright"),
        0xD6 => Some("divide"),
        0xD7 => Some("lozenge"),
        0xD8 => Some("ydieresis"),
        0xD9 => Some("Ydieresis"),
        0xDA => Some("fraction"),
        0xDB => Some("currency"),
        0xDC => Some("guilsinglleft"),
        0xDD => Some("guilsinglright"),
        0xDE => Some("fi"),
        0xDF => Some("fl"),
        0xE0 => Some("daggerdbl"),
        0xE1 => Some("periodcentered"),
        0xE2 => Some("quotesinglbase"),
        0xE3 => Some("quotedblbase"),
        0xE4 => Some("perthousand"),
        0xE5 => Some("Acircumflex"),
        0xE6 => Some("Ecircumflex"),
        0xE7 => Some("Aacute"),
        0xE8 => Some("Edieresis"),
        0xE9 => Some("Egrave"),
        0xEA => Some("Iacute"),
        0xEB => Some("Icircumflex"),
        0xEC => Some("Idieresis"),
        0xED => Some("Igrave"),
        0xEE => Some("Oacute"),
        0xEF => Some("Ocircumflex"),
        0xF0 => None, // Apple-logo PUA glyph; no portable name ~keep
        0xF1 => Some("Ograve"),
        0xF2 => Some("Uacute"),
        0xF3 => Some("Ucircumflex"),
        0xF4 => Some("Ugrave"),
        0xF5 => Some("dotlessi"),
        0xF6 => Some("circumflex"),
        0xF7 => Some("tilde"),
        0xF8 => Some("macron"),
        0xF9 => Some("breve"),
        0xFA => Some("dotaccent"),
        0xFB => Some("ring"),
        0xFC => Some("cedilla"),
        0xFD => Some("hungarumlaut"),
        0xFE => Some("ogonek"),
        0xFF => Some("caron"),
        _ => None,
    }
}

/// Annex D Table D.1 (StandardEncoding, PostScript) byte → glyph name.
///
/// ASCII range 0x20-0x7E shares glyph names with WinAnsi except a handful
/// (0x27 quoteright, 0x60 quoteleft, etc.) — those overlap the existing
/// WinAnsi table's choice of `quoteright` for 0x27. The high-byte range
/// has its own PostScript repertoire (fraction at 0xA4, ligature `fi`/`fl`
/// at 0xAE/0xAF, etc.) which differs sharply from WinAnsi.
///
/// Bytes left unassigned by StandardEncoding return `None`.
pub(super) fn standard_encoding_byte_to_name(byte: u8) -> Option<&'static str> {
    use crate::fonts::font_dict::FontInfo;
    if (0x20..=0x7E).contains(&byte) {
        return FontInfo::gid_to_standard_glyph_name(byte as u16);
    }
    match byte {
        0xA1 => Some("exclamdown"),
        0xA2 => Some("cent"),
        0xA3 => Some("sterling"),
        0xA4 => Some("fraction"),
        0xA5 => Some("yen"),
        0xA6 => Some("florin"),
        0xA7 => Some("section"),
        0xA8 => Some("currency"),
        0xA9 => Some("quotesingle"),
        0xAA => Some("quotedblleft"),
        0xAB => Some("guillemotleft"),
        0xAC => Some("guilsinglleft"),
        0xAD => Some("guilsinglright"),
        0xAE => Some("fi"),
        0xAF => Some("fl"),
        0xB1 => Some("endash"),
        0xB2 => Some("dagger"),
        0xB3 => Some("daggerdbl"),
        0xB4 => Some("periodcentered"),
        0xB6 => Some("paragraph"),
        0xB7 => Some("bullet"),
        0xB8 => Some("quotesinglbase"),
        0xB9 => Some("quotedblbase"),
        0xBA => Some("quotedblright"),
        0xBB => Some("guillemotright"),
        0xBC => Some("ellipsis"),
        0xBD => Some("perthousand"),
        0xBF => Some("questiondown"),
        0xC1 => Some("grave"),
        0xC2 => Some("acute"),
        0xC3 => Some("circumflex"),
        0xC4 => Some("tilde"),
        0xC5 => Some("macron"),
        0xC6 => Some("breve"),
        0xC7 => Some("dotaccent"),
        0xC8 => Some("dieresis"),
        0xCA => Some("ring"),
        0xCB => Some("cedilla"),
        0xCD => Some("hungarumlaut"),
        0xCE => Some("ogonek"),
        0xCF => Some("caron"),
        0xE1 => Some("AE"),
        0xE3 => Some("ordfeminine"),
        0xE8 => Some("Lslash"),
        0xE9 => Some("Oslash"),
        0xEA => Some("OE"),
        0xEB => Some("ordmasculine"),
        0xF1 => Some("ae"),
        0xF5 => Some("dotlessi"),
        0xF8 => Some("lslash"),
        0xF9 => Some("oslash"),
        0xFA => Some("oe"),
        0xFB => Some("germandbls"),
        _ => None,
    }
}
