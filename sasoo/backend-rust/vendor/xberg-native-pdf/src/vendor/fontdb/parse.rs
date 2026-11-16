// Derived from fontdb 0.24.0 (https://github.com/RazrFalcon/fontdb),
// Copyright (c) 2020 Yevhenii Reizner, MIT licensed. Modified: the inlined
// ttf_parser-based parser (`parse_face_info`/`parse_names`/`parse_os2`/
// `parse_post`) was replaced with skrifa/read-fonts, and the English-family
// selection now keys off skrifa's BCP-47 language tags rather than
// ttf_parser's `Language` enum. ~keep

//! Per-face metadata extraction, using skrifa/read-fonts in place of
//! upstream fontdb's inlined `ttf_parser` copy.

use skrifa::raw::TableProvider;
use skrifa::string::StringId;
use skrifa::{FontRef, MetadataProvider};

use super::{FaceInfo, Source, Stretch, Style, Weight};

/// A list of possible font loading errors.
///
/// Mirrors upstream fontdb's `LoadError`, minus the IO variant (this crate's
/// callers surface IO failures separately, see `system_fonts::load_fonts_from_file`).
#[derive(Debug)]
pub(super) enum LoadError {
    /// skrifa could not parse the face at the given index (malformed font).
    Malformed,
    /// A valid font without a usable *Typographic Family* or *Family* name.
    Unnamed,
}

impl core::fmt::Display for LoadError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            LoadError::Malformed => write!(f, "malformed font"),
            LoadError::Unnamed => write!(f, "font doesn't have a family name"),
        }
    }
}

/// Extracts a [`FaceInfo`] for one face of a font file/blob.
///
/// `font` must already be resolved to the specific face (via
/// `FontRef::from_index`/`FontRef::fonts`) — this only reads tables off it,
/// it does not resolve collection indices itself.
pub(super) fn parse_face_info(font: &FontRef, source: Source, index: u32) -> Result<FaceInfo, LoadError> {
    let families = parse_families(font).ok_or(LoadError::Unnamed)?;

    let attrs = font.attributes();
    let mut style = convert_style(attrs.style);
    // skrifa's `Attributes::new` upgrades OS/2 fsSelection Oblique to
    // `Style::Oblique` (with the post-table angle) but, unlike upstream
    // fontdb, never promotes a plain `Normal` to `Italic` purely from the
    // post table's italic angle. Replicate fontdb's behaviour for the fonts
    // that only set `post.italicAngle` and leave the OS/2 italic bit unset. ~keep
    if style == Style::Normal
        && let Ok(post) = font.post()
        && post.italic_angle().to_f64() != 0.0
    {
        style = Style::Italic;
    }

    let weight = Weight(attrs.weight.value().round() as u16);
    let stretch = convert_stretch(attrs.stretch);

    Ok(FaceInfo {
        source,
        index,
        families,
        style,
        weight,
        stretch,
    })
}

/// Collects `(name, BCP-47 language tag)` pairs, preferring the
/// *Typographic Family* (name ID 16) and falling back to *Family* (ID 1),
/// with any English-tagged entry moved to the front.
///
/// This is not bit-for-bit identical to upstream fontdb's algorithm, which
/// keys off `ttf_parser::Language::English_UnitedStates` derived from raw
/// Mac/Windows name-table language IDs. skrifa's `LocalizedString::language`
/// derives BCP-47 tags from the same underlying IDs (borrowing Skia's
/// mapping table), so `starts_with("en")` is semantically equivalent for the
/// case that matters — English-US name records, which is what real fonts
/// carry — but is not a byte-for-byte port. ~keep
fn parse_families(font: &FontRef) -> Option<Vec<(String, Option<String>)>> {
    let mut families = collect_localized(font, StringId::TYPOGRAPHIC_FAMILY_NAME);
    if families.is_empty() {
        families = collect_localized(font, StringId::FAMILY_NAME);
    }
    if families.is_empty() {
        return None;
    }

    if let Some(index) = families
        .iter()
        .position(|(_, lang)| lang.as_deref().is_some_and(|l| l.starts_with("en")))
        && index != 0
    {
        families.swap(0, index);
    }

    Some(families)
}

fn collect_localized(font: &FontRef, id: StringId) -> Vec<(String, Option<String>)> {
    font.localized_strings(id)
        .map(|s| (s.to_string(), s.language().map(str::to_string)))
        .collect()
}

fn convert_style(style: skrifa::attribute::Style) -> Style {
    match style {
        skrifa::attribute::Style::Normal => Style::Normal,
        skrifa::attribute::Style::Italic => Style::Italic,
        skrifa::attribute::Style::Oblique(_) => Style::Oblique,
    }
}

/// Maps skrifa's continuous `Stretch` ratio back onto fontdb's 9-step scale.
///
/// skrifa derives `Attributes.stretch` from the OS/2 `usWidthClass` via
/// `Stretch::from_width_class`, which only ever produces one of the nine
/// named constants below (or the `NORMAL` default when there is no OS/2
/// table) — so exact `PartialEq` comparison against those constants is
/// safe and not an approximation. ~keep
fn convert_stretch(stretch: skrifa::attribute::Stretch) -> Stretch {
    use skrifa::attribute::Stretch as SkrifaStretch;
    match stretch {
        s if s == SkrifaStretch::ULTRA_CONDENSED => Stretch::UltraCondensed,
        s if s == SkrifaStretch::EXTRA_CONDENSED => Stretch::ExtraCondensed,
        s if s == SkrifaStretch::CONDENSED => Stretch::Condensed,
        s if s == SkrifaStretch::SEMI_CONDENSED => Stretch::SemiCondensed,
        s if s == SkrifaStretch::SEMI_EXPANDED => Stretch::SemiExpanded,
        s if s == SkrifaStretch::EXPANDED => Stretch::Expanded,
        s if s == SkrifaStretch::EXTRA_EXPANDED => Stretch::ExtraExpanded,
        s if s == SkrifaStretch::ULTRA_EXPANDED => Stretch::UltraExpanded,
        _ => Stretch::Normal,
    }
}
