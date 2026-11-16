//! Core annotation types and enums per PDF spec ISO 32000-1:2008, Section 12.5.
//!
//! This module provides shared types used by both annotation reading and writing.

/// Annotation subtype per PDF spec Table 169.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum AnnotationSubtype {
    /// Text annotation (sticky note) - Section 12.5.6.4
    Text,
    /// Link annotation - Section 12.5.6.5
    Link,
    /// Free text annotation - Section 12.5.6.6
    FreeText,
    /// Line annotation - Section 12.5.6.7
    Line,
    /// Square annotation - Section 12.5.6.8
    Square,
    /// Circle annotation - Section 12.5.6.8
    Circle,
    /// Polygon annotation - Section 12.5.6.9
    Polygon,
    /// Polyline annotation - Section 12.5.6.9
    PolyLine,
    /// Highlight annotation - Section 12.5.6.10
    Highlight,
    /// Underline annotation - Section 12.5.6.10
    Underline,
    /// Squiggly underline annotation - Section 12.5.6.10
    Squiggly,
    /// Strikeout annotation - Section 12.5.6.10
    StrikeOut,
    /// Rubber stamp annotation - Section 12.5.6.12
    Stamp,
    /// Caret annotation - Section 12.5.6.11
    Caret,
    /// Ink annotation - Section 12.5.6.13
    Ink,
    /// Popup annotation - Section 12.5.6.14
    Popup,
    /// File attachment annotation - Section 12.5.6.15
    FileAttachment,
    /// Sound annotation - Section 12.5.6.16
    Sound,
    /// Movie annotation - Section 12.5.6.17
    Movie,
    /// Widget annotation (form field) - Section 12.5.6.19
    Widget,
    /// Screen annotation - Section 12.5.6.18
    Screen,
    /// Printer's mark annotation - Section 12.5.6.20
    PrinterMark,
    /// Trap network annotation - Section 12.5.6.21
    TrapNet,
    /// Watermark annotation - Section 12.5.6.22
    Watermark,
    /// 3D annotation - Section 12.5.6.24
    ThreeD,
    /// Redaction annotation - Section 12.5.6.23
    Redact,
    /// RichMedia annotation - Adobe Extension Level 3
    RichMedia,
    /// Unknown annotation type
    Unknown,
}

impl AnnotationSubtype {
    /// Get the PDF name for this annotation subtype.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::Text => "Text",
            Self::Link => "Link",
            Self::FreeText => "FreeText",
            Self::Line => "Line",
            Self::Square => "Square",
            Self::Circle => "Circle",
            Self::Polygon => "Polygon",
            Self::PolyLine => "PolyLine",
            Self::Highlight => "Highlight",
            Self::Underline => "Underline",
            Self::Squiggly => "Squiggly",
            Self::StrikeOut => "StrikeOut",
            Self::Stamp => "Stamp",
            Self::Caret => "Caret",
            Self::Ink => "Ink",
            Self::Popup => "Popup",
            Self::FileAttachment => "FileAttachment",
            Self::Sound => "Sound",
            Self::Movie => "Movie",
            Self::Widget => "Widget",
            Self::Screen => "Screen",
            Self::PrinterMark => "PrinterMark",
            Self::TrapNet => "TrapNet",
            Self::Watermark => "Watermark",
            Self::ThreeD => "3D",
            Self::Redact => "Redact",
            Self::RichMedia => "RichMedia",
            Self::Unknown => "Unknown",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "Text" => Self::Text,
            "Link" => Self::Link,
            "FreeText" => Self::FreeText,
            "Line" => Self::Line,
            "Square" => Self::Square,
            "Circle" => Self::Circle,
            "Polygon" => Self::Polygon,
            "PolyLine" => Self::PolyLine,
            "Highlight" => Self::Highlight,
            "Underline" => Self::Underline,
            "Squiggly" => Self::Squiggly,
            "StrikeOut" => Self::StrikeOut,
            "Stamp" => Self::Stamp,
            "Caret" => Self::Caret,
            "Ink" => Self::Ink,
            "Popup" => Self::Popup,
            "FileAttachment" => Self::FileAttachment,
            "Sound" => Self::Sound,
            "Movie" => Self::Movie,
            "Widget" => Self::Widget,
            "Screen" => Self::Screen,
            "PrinterMark" => Self::PrinterMark,
            "TrapNet" => Self::TrapNet,
            "Watermark" => Self::Watermark,
            "3D" => Self::ThreeD,
            "Redact" => Self::Redact,
            "RichMedia" => Self::RichMedia,
            _ => Self::Unknown,
        }
    }

    /// Check if this is a markup annotation (has popup, replies, etc.)
    pub fn is_markup(&self) -> bool {
        matches!(
            self,
            Self::Text
                | Self::FreeText
                | Self::Line
                | Self::Square
                | Self::Circle
                | Self::Polygon
                | Self::PolyLine
                | Self::Highlight
                | Self::Underline
                | Self::Squiggly
                | Self::StrikeOut
                | Self::Stamp
                | Self::Caret
                | Self::Ink
                | Self::FileAttachment
                | Self::Sound
                | Self::Redact
        )
    }

    /// Check if this is a text markup annotation.
    pub fn is_text_markup(&self) -> bool {
        matches!(
            self,
            Self::Highlight | Self::Underline | Self::Squiggly | Self::StrikeOut
        )
    }
}

/// Annotation flags per PDF spec Table 165.
///
/// These flags control how the annotation behaves when displayed or printed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct AnnotationFlags(u32);

impl AnnotationFlags {
    /// Invisible flag (bit 1) - If set, do not display if no AP.
    pub const INVISIBLE: u32 = 1 << 0;
    /// Hidden flag (bit 2) - If set, do not display or print.
    pub const HIDDEN: u32 = 1 << 1;
    /// Print flag (bit 3) - If set, print annotation when printing.
    pub const PRINT: u32 = 1 << 2;
    /// NoZoom flag (bit 4) - If set, do not scale with page zoom.
    pub const NO_ZOOM: u32 = 1 << 3;
    /// NoRotate flag (bit 5) - If set, do not rotate with page.
    pub const NO_ROTATE: u32 = 1 << 4;
    /// NoView flag (bit 6) - If set, do not display on screen.
    pub const NO_VIEW: u32 = 1 << 5;
    /// ReadOnly flag (bit 7) - If set, do not allow interaction.
    pub const READ_ONLY: u32 = 1 << 6;
    /// Locked flag (bit 8) - If set, do not allow deletion/modification.
    pub const LOCKED: u32 = 1 << 7;
    /// ToggleNoView flag (bit 9) - Invert NoView on mouse events.
    pub const TOGGLE_NO_VIEW: u32 = 1 << 8;
    /// LockedContents flag (bit 10) - If set, do not allow content modification.
    pub const LOCKED_CONTENTS: u32 = 1 << 9;

    /// Create new flags from raw value.
    pub fn new(value: u32) -> Self {
        Self(value)
    }

    /// Create empty flags.
    pub fn empty() -> Self {
        Self(0)
    }

    /// Create default flags for printing (PRINT flag set).
    pub fn printable() -> Self {
        Self(Self::PRINT)
    }

    /// Get raw value.
    pub fn bits(&self) -> u32 {
        self.0
    }

    /// Check if a flag is set.
    pub fn contains(&self, flag: u32) -> bool {
        (self.0 & flag) != 0
    }

    /// Set a flag.
    pub fn set(&mut self, flag: u32) {
        self.0 |= flag;
    }

    /// Clear a flag.
    pub fn clear(&mut self, flag: u32) {
        self.0 &= !flag;
    }

    /// Check if invisible.
    pub fn is_invisible(&self) -> bool {
        self.contains(Self::INVISIBLE)
    }

    /// Check if hidden.
    pub fn is_hidden(&self) -> bool {
        self.contains(Self::HIDDEN)
    }

    /// Check if printable.
    pub fn is_printable(&self) -> bool {
        self.contains(Self::PRINT)
    }

    /// Check if no zoom.
    pub fn is_no_zoom(&self) -> bool {
        self.contains(Self::NO_ZOOM)
    }

    /// Check if no rotate.
    pub fn is_no_rotate(&self) -> bool {
        self.contains(Self::NO_ROTATE)
    }

    /// Check if read only.
    pub fn is_read_only(&self) -> bool {
        self.contains(Self::READ_ONLY)
    }

    /// Check if locked.
    pub fn is_locked(&self) -> bool {
        self.contains(Self::LOCKED)
    }
}

/// Border style type per PDF spec Table 166.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum BorderStyleType {
    /// Solid border (S)
    #[default]
    Solid,
    /// Dashed border (D)
    Dashed,
    /// Beveled border (B)
    Beveled,
    /// Inset border (I)
    Inset,
    /// Underline border (U)
    Underline,
}

impl BorderStyleType {
    /// Get PDF name for this border style.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::Solid => "S",
            Self::Dashed => "D",
            Self::Beveled => "B",
            Self::Inset => "I",
            Self::Underline => "U",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "S" => Self::Solid,
            "D" => Self::Dashed,
            "B" => Self::Beveled,
            "I" => Self::Inset,
            "U" => Self::Underline,
            _ => Self::Solid,
        }
    }
}

/// Border style dictionary per PDF spec Table 166.
#[derive(Debug, Clone, Default)]
pub struct AnnotationBorderStyle {
    /// Border width in points.
    pub width: f32,
    /// Border style type.
    pub style: BorderStyleType,
    /// Dash pattern for dashed borders [dash, gap, dash, gap, ...].
    pub dash_pattern: Option<Vec<f32>>,
}

impl AnnotationBorderStyle {
    /// Create a solid border with given width.
    pub fn solid(width: f32) -> Self {
        Self {
            width,
            style: BorderStyleType::Solid,
            dash_pattern: None,
        }
    }

    /// Create a dashed border.
    pub fn dashed(width: f32, dash: f32, gap: f32) -> Self {
        Self {
            width,
            style: BorderStyleType::Dashed,
            dash_pattern: Some(vec![dash, gap]),
        }
    }

    /// Create no visible border.
    pub fn none() -> Self {
        Self {
            width: 0.0,
            style: BorderStyleType::Solid,
            dash_pattern: None,
        }
    }
}

/// Border effect style per PDF spec Table 167.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum BorderEffectStyle {
    /// No effect (S)
    #[default]
    None,
    /// Cloudy border (C)
    Cloudy,
}

impl BorderEffectStyle {
    /// Get PDF name.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::None => "S",
            Self::Cloudy => "C",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "C" => Self::Cloudy,
            _ => Self::None,
        }
    }
}

/// Border effect dictionary per PDF spec Table 167.
#[derive(Debug, Clone, Default)]
pub struct BorderEffect {
    /// Effect style.
    pub style: BorderEffectStyle,
    /// Effect intensity (for cloudy effect, 0-2 recommended).
    pub intensity: f32,
}

/// Line ending style per PDF spec Table 176.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum LineEndingStyle {
    /// No line ending
    #[default]
    None,
    /// Square filled with interior color
    Square,
    /// Circle filled with interior color
    Circle,
    /// Diamond filled with interior color
    Diamond,
    /// Open arrow (two lines forming acute angle)
    OpenArrow,
    /// Closed arrow (filled triangle)
    ClosedArrow,
    /// Butt (perpendicular line at endpoint)
    Butt,
    /// Reverse open arrow
    ROpenArrow,
    /// Reverse closed arrow
    RClosedArrow,
    /// Slash (30 degrees from perpendicular)
    Slash,
}

impl LineEndingStyle {
    /// Get PDF name.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::None => "None",
            Self::Square => "Square",
            Self::Circle => "Circle",
            Self::Diamond => "Diamond",
            Self::OpenArrow => "OpenArrow",
            Self::ClosedArrow => "ClosedArrow",
            Self::Butt => "Butt",
            Self::ROpenArrow => "ROpenArrow",
            Self::RClosedArrow => "RClosedArrow",
            Self::Slash => "Slash",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "None" => Self::None,
            "Square" => Self::Square,
            "Circle" => Self::Circle,
            "Diamond" => Self::Diamond,
            "OpenArrow" => Self::OpenArrow,
            "ClosedArrow" => Self::ClosedArrow,
            "Butt" => Self::Butt,
            "ROpenArrow" => Self::ROpenArrow,
            "RClosedArrow" => Self::RClosedArrow,
            "Slash" => Self::Slash,
            _ => Self::None,
        }
    }
}

/// Annotation color representation.
///
/// Colors are specified as values in the range 0.0 to 1.0.
#[derive(Debug, Clone, PartialEq, Default)]
pub enum AnnotationColor {
    /// No color (transparent)
    #[default]
    None,
    /// Grayscale (1 component)
    Gray(f32),
    /// RGB color (3 components)
    Rgb(f32, f32, f32),
    /// CMYK color (4 components)
    Cmyk(f32, f32, f32, f32),
}

impl AnnotationColor {
    /// Create yellow color (common for highlights).
    pub fn yellow() -> Self {
        Self::Rgb(1.0, 1.0, 0.0)
    }

    /// Create red color.
    pub fn red() -> Self {
        Self::Rgb(1.0, 0.0, 0.0)
    }

    /// Create green color.
    pub fn green() -> Self {
        Self::Rgb(0.0, 1.0, 0.0)
    }

    /// Create blue color.
    pub fn blue() -> Self {
        Self::Rgb(0.0, 0.0, 1.0)
    }

    /// Create black color.
    pub fn black() -> Self {
        Self::Gray(0.0)
    }

    /// Create white color.
    pub fn white() -> Self {
        Self::Gray(1.0)
    }

    /// Convert to PDF array representation.
    pub fn to_array(&self) -> Option<Vec<f32>> {
        match self {
            Self::None => None,
            Self::Gray(g) => Some(vec![*g]),
            Self::Rgb(r, g, b) => Some(vec![*r, *g, *b]),
            Self::Cmyk(c, m, y, k) => Some(vec![*c, *m, *y, *k]),
        }
    }

    /// Parse from PDF array.
    pub fn from_array(arr: &[f32]) -> Self {
        match arr.len() {
            0 => Self::None,
            1 => Self::Gray(arr[0]),
            3 => Self::Rgb(arr[0], arr[1], arr[2]),
            4 => Self::Cmyk(arr[0], arr[1], arr[2], arr[3]),
            _ => Self::None,
        }
    }
}

/// Text annotation icon types per PDF spec Section 12.5.6.4.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum TextAnnotationIcon {
    /// Comment icon
    Comment,
    /// Key icon
    Key,
    /// Note icon (default)
    #[default]
    Note,
    /// Help icon
    Help,
    /// New paragraph icon
    NewParagraph,
    /// Paragraph icon
    Paragraph,
    /// Insert icon
    Insert,
}

impl TextAnnotationIcon {
    /// Get PDF name.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::Comment => "Comment",
            Self::Key => "Key",
            Self::Note => "Note",
            Self::Help => "Help",
            Self::NewParagraph => "NewParagraph",
            Self::Paragraph => "Paragraph",
            Self::Insert => "Insert",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "Comment" => Self::Comment,
            "Key" => Self::Key,
            "Note" => Self::Note,
            "Help" => Self::Help,
            "NewParagraph" => Self::NewParagraph,
            "Paragraph" => Self::Paragraph,
            "Insert" => Self::Insert,
            _ => Self::Note,
        }
    }
}

/// Text markup annotation type.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TextMarkupType {
    /// Highlight annotation
    Highlight,
    /// Underline annotation
    Underline,
    /// Squiggly underline annotation
    Squiggly,
    /// Strikeout annotation
    StrikeOut,
}

impl TextMarkupType {
    /// Get the annotation subtype.
    pub fn subtype(&self) -> AnnotationSubtype {
        match self {
            Self::Highlight => AnnotationSubtype::Highlight,
            Self::Underline => AnnotationSubtype::Underline,
            Self::Squiggly => AnnotationSubtype::Squiggly,
            Self::StrikeOut => AnnotationSubtype::StrikeOut,
        }
    }

    /// Get default color for this markup type.
    pub fn default_color(&self) -> AnnotationColor {
        match self {
            Self::Highlight => AnnotationColor::yellow(),
            Self::Underline => AnnotationColor::green(),
            Self::Squiggly => AnnotationColor::Rgb(1.0, 0.5, 0.0),
            Self::StrikeOut => AnnotationColor::red(),
        }
    }
}

/// Standard stamp types per PDF spec Section 12.5.6.12.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub enum StampType {
    /// Approved stamp
    Approved,
    /// Experimental stamp
    Experimental,
    /// Not approved stamp
    NotApproved,
    /// As-is stamp
    AsIs,
    /// Expired stamp
    Expired,
    /// Not for public release stamp
    NotForPublicRelease,
    /// Confidential stamp
    Confidential,
    /// Final stamp
    Final,
    /// Sold stamp
    Sold,
    /// Departmental stamp
    Departmental,
    /// For comment stamp
    ForComment,
    /// Top secret stamp
    TopSecret,
    /// Draft stamp
    #[default]
    Draft,
    /// For public release stamp
    ForPublicRelease,
    /// Custom stamp name
    Custom(String),
}

impl StampType {
    /// Get PDF name.
    pub fn pdf_name(&self) -> String {
        match self {
            Self::Approved => "Approved".to_string(),
            Self::Experimental => "Experimental".to_string(),
            Self::NotApproved => "NotApproved".to_string(),
            Self::AsIs => "AsIs".to_string(),
            Self::Expired => "Expired".to_string(),
            Self::NotForPublicRelease => "NotForPublicRelease".to_string(),
            Self::Confidential => "Confidential".to_string(),
            Self::Final => "Final".to_string(),
            Self::Sold => "Sold".to_string(),
            Self::Departmental => "Departmental".to_string(),
            Self::ForComment => "ForComment".to_string(),
            Self::TopSecret => "TopSecret".to_string(),
            Self::Draft => "Draft".to_string(),
            Self::ForPublicRelease => "ForPublicRelease".to_string(),
            Self::Custom(name) => name.clone(),
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "Approved" => Self::Approved,
            "Experimental" => Self::Experimental,
            "NotApproved" => Self::NotApproved,
            "AsIs" => Self::AsIs,
            "Expired" => Self::Expired,
            "NotForPublicRelease" => Self::NotForPublicRelease,
            "Confidential" => Self::Confidential,
            "Final" => Self::Final,
            "Sold" => Self::Sold,
            "Departmental" => Self::Departmental,
            "ForComment" => Self::ForComment,
            "TopSecret" => Self::TopSecret,
            "Draft" => Self::Draft,
            "ForPublicRelease" => Self::ForPublicRelease,
            other => Self::Custom(other.to_string()),
        }
    }
}

/// FreeText annotation intent per PDF spec Section 12.5.6.6.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum FreeTextIntent {
    /// Plain free text (text box comment)
    #[default]
    FreeText,
    /// Callout with line pointing to content
    FreeTextCallout,
    /// Typewriter-style text
    FreeTextTypeWriter,
}

impl FreeTextIntent {
    /// Get PDF name.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::FreeText => "FreeText",
            Self::FreeTextCallout => "FreeTextCallout",
            Self::FreeTextTypeWriter => "FreeTextTypeWriter",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "FreeTextCallout" => Self::FreeTextCallout,
            "FreeTextTypeWriter" => Self::FreeTextTypeWriter,
            _ => Self::FreeText,
        }
    }
}

/// Text alignment (quadding) per PDF spec.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum TextAlignment {
    /// Left-justified (0)
    #[default]
    Left,
    /// Centered (1)
    Center,
    /// Right-justified (2)
    Right,
}

impl TextAlignment {
    /// Get PDF integer value.
    pub fn to_pdf_int(&self) -> i32 {
        match self {
            Self::Left => 0,
            Self::Center => 1,
            Self::Right => 2,
        }
    }

    /// Parse from PDF integer.
    pub fn from_pdf_int(value: i32) -> Self {
        match value {
            1 => Self::Center,
            2 => Self::Right,
            _ => Self::Left,
        }
    }
}

/// Caret annotation symbol per PDF spec Section 12.5.6.11.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum CaretSymbol {
    /// No symbol
    #[default]
    None,
    /// Paragraph symbol (pilcrow)
    Paragraph,
}

impl CaretSymbol {
    /// Get PDF name.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::None => "None",
            Self::Paragraph => "P",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "P" => Self::Paragraph,
            _ => Self::None,
        }
    }
}

/// File attachment annotation icon per PDF spec Section 12.5.6.15.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum FileAttachmentIcon {
    /// Graph/push pin icon
    GraphPushPin,
    /// Paperclip tag icon (default)
    #[default]
    PaperclipTag,
    /// Push pin icon
    PushPin,
}

impl FileAttachmentIcon {
    /// Get PDF name.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::GraphPushPin => "GraphPushPin",
            Self::PaperclipTag => "PaperclipTag",
            Self::PushPin => "PushPin",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "GraphPushPin" => Self::GraphPushPin,
            "PushPin" => Self::PushPin,
            _ => Self::PaperclipTag,
        }
    }
}

/// Reply type for annotation replies per PDF spec Table 170.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ReplyType {
    /// Reply annotation
    #[default]
    Reply,
    /// Group annotation
    Group,
}

impl ReplyType {
    /// Get PDF name.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::Reply => "R",
            Self::Group => "Group",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "Group" => Self::Group,
            _ => Self::Reply,
        }
    }
}

/// Highlight mode for link annotations per PDF spec Table 173.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum HighlightMode {
    /// No highlighting (N)
    None,
    /// Invert the contents (I) - default
    #[default]
    Invert,
    /// Invert the border (O)
    Outline,
    /// Push effect (P)
    Push,
}

impl HighlightMode {
    /// Get PDF name.
    pub fn pdf_name(&self) -> &'static str {
        match self {
            Self::None => "N",
            Self::Invert => "I",
            Self::Outline => "O",
            Self::Push => "P",
        }
    }

    /// Parse from PDF name.
    pub fn from_pdf_name(name: &str) -> Self {
        match name {
            "N" => Self::None,
            "O" => Self::Outline,
            "P" => Self::Push,
            _ => Self::Invert,
        }
    }
}

/// Widget field type for form fields.
#[derive(Debug, Clone, PartialEq, Default)]
pub enum WidgetFieldType {
    /// Text input field
    #[default]
    Text,
    /// Checkbox
    Checkbox {
        /// Whether the checkbox is checked
        checked: bool,
    },
    /// Radio button
    Radio {
        /// Selected option value
        selected: Option<String>,
    },
    /// Push button
    Button,
    /// Choice field (dropdown or list)
    Choice {
        /// Available options
        options: Vec<String>,
        /// Selected option(s)
        selected: Option<String>,
    },
    /// Signature field
    Signature,
    /// Unknown field type
    Unknown,
}

/// A quad point specification (8 numbers defining a quadrilateral).
///
/// Points are specified as [x1, y1, x2, y2, x3, y3, x4, y4] in counterclockwise order.
/// The bottom edge is from (x1, y1) to (x2, y2).
pub type QuadPoint = [f64; 8];

/// Helper functions for quad points.
pub mod quad_points {
    use super::QuadPoint;
    use crate::geometry::Rect;

    /// Create a quad point from a rectangle.
    pub fn from_rect(rect: &Rect) -> QuadPoint {
        let x1 = rect.x as f64;
        let y1 = rect.y as f64;
        let x2 = (rect.x + rect.width) as f64;
        let y2 = rect.y as f64;
        let x3 = (rect.x + rect.width) as f64;
        let y3 = (rect.y + rect.height) as f64;
        let x4 = rect.x as f64;
        let y4 = (rect.y + rect.height) as f64;

        [x1, y1, x2, y2, x3, y3, x4, y4]
    }

    /// Get the bounding rectangle of a quad point.
    pub fn bounding_rect(quad: &QuadPoint) -> Rect {
        let min_x = quad[0].min(quad[2]).min(quad[4]).min(quad[6]) as f32;
        let max_x = quad[0].max(quad[2]).max(quad[4]).max(quad[6]) as f32;
        let min_y = quad[1].min(quad[3]).min(quad[5]).min(quad[7]) as f32;
        let max_y = quad[1].max(quad[3]).max(quad[5]).max(quad[7]) as f32;

        Rect::new(min_x, min_y, max_x - min_x, max_y - min_y)
    }

    /// Parse quad points from a flat array of numbers.
    pub fn parse(arr: &[f64]) -> Vec<QuadPoint> {
        arr.as_chunks::<8>()
            .0
            .iter()
            .map(|chunk| {
                [
                    chunk[0], chunk[1], chunk[2], chunk[3], chunk[4], chunk[5], chunk[6], chunk[7],
                ]
            })
            .collect()
    }

    /// Flatten quad points to a single array.
    pub fn flatten(quads: &[QuadPoint]) -> Vec<f64> {
        quads.iter().flat_map(|q| q.iter().copied()).collect()
    }
}

#[cfg(test)]
mod tests;
