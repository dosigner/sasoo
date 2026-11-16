//! Image content element types.
//!
//! This module provides the `ImageContent` type for representing
//! images in PDFs.

use crate::geometry::Rect;

/// Image content that can be extracted from or written to a PDF.
///
/// This represents an embedded image with its positioning information.
#[derive(Debug, Clone)]
pub struct ImageContent {
    /// Bounding box where the image is placed
    pub bbox: Rect,
    /// Image format
    pub format: ImageFormat,
    /// Image bytes. When constructed via `from_bytes()` or `new()` this holds the
    /// encoded file bytes (PNG/JPEG). When extracted from an existing PDF the bytes
    /// are the raw decoded pixel data as stored in the XObject stream.
    pub data: Vec<u8>,
    /// Image width in pixels
    pub width: u32,
    /// Image height in pixels
    pub height: u32,
    /// Bits per component (typically 8)
    pub bits_per_component: u8,
    /// Color space
    pub color_space: ColorSpace,
    /// Reading order index
    pub reading_order: Option<usize>,
    /// Alternative text for accessibility
    pub alt_text: Option<String>,

    /// Horizontal DPI (dots per inch) calculated from pixel width and bbox
    pub horizontal_dpi: Option<f32>,
    /// Vertical DPI (dots per inch) calculated from pixel height and bbox
    pub vertical_dpi: Option<f32>,

    /// Optional alpha / transparency channel for PNG-style soft masks.
    /// Already compressed (FlateDecode) by the image decoder. Carried
    /// through to the PDF as an `/SMask` XObject so transparent PNGs
    /// render with their alpha preserved. `None` for opaque images
    /// and for formats that don't carry transparency (JPEG, CMYK).
    pub soft_mask: Option<Vec<u8>>,
    /// Optional 2D affine transform in PDF row order `[a b c d e f]`.
    /// When set, the image is wrapped in `q ... cm ... Q` on emission
    /// so graphics-state stays scoped. Populated by
    /// `FluentPageBuilder::{rotated, scaled, translated, with_transform}`
    /// closures. #393 Bundle A-2 follow-up.
    pub matrix: Option<[f32; 6]>,
    /// When `true` the image is purely decorative and must be marked as an
    /// `/Artifact` in the content stream so assistive technology ignores it.
    /// PDF/UA-1 §7.1 (F-3). Mutually exclusive with `alt_text`.
    pub is_artifact: bool,
}

impl ImageContent {
    /// Create a new image content element.
    pub fn new(bbox: Rect, format: ImageFormat, data: Vec<u8>, width: u32, height: u32) -> Self {
        let mut image = Self {
            bbox,
            format,
            data,
            width,
            height,
            bits_per_component: 8,
            color_space: ColorSpace::RGB,
            reading_order: None,
            alt_text: None,
            horizontal_dpi: None,
            vertical_dpi: None,
            soft_mask: None,
            matrix: None,
            is_artifact: false,
        };
        image.calculate_dpi();
        image
    }

    /// Mark this image as a decorative artifact (PDF/UA-1 §7.1). The image
    /// will be wrapped in `/Artifact BDC`/`EMC` so assistive technology
    /// skips it. Clears any `alt_text` that was previously set.
    pub fn as_artifact(mut self) -> Self {
        self.is_artifact = true;
        self.alt_text = None;
        self
    }

    /// Attach a pre-compressed soft-mask (alpha) channel. The bytes are
    /// emitted verbatim as a separate XObject stream linked via
    /// `/SMask` so PDF viewers composite the alpha at paint time.
    pub fn with_soft_mask(mut self, mask: Vec<u8>) -> Self {
        self.soft_mask = Some(mask);
        self
    }

    /// Set the reading order.
    pub fn with_reading_order(mut self, order: usize) -> Self {
        self.reading_order = Some(order);
        self
    }

    /// Set alternative text for accessibility.
    pub fn with_alt_text(mut self, text: impl Into<String>) -> Self {
        self.alt_text = Some(text.into());
        self
    }

    /// Get the aspect ratio (width / height).
    pub fn aspect_ratio(&self) -> f32 {
        if self.height == 0 {
            1.0
        } else {
            self.width as f32 / self.height as f32
        }
    }

    /// Check if this is a grayscale image.
    pub fn is_grayscale(&self) -> bool {
        matches!(self.color_space, ColorSpace::Gray)
    }

    /// Calculate and set the DPI values based on pixel dimensions and bounding box.
    ///
    /// DPI = pixels / inches, where inches = points / 72 (1 inch = 72 points)
    pub fn calculate_dpi(&mut self) {
        // Convert bbox dimensions from points to inches (72 points = 1 inch) ~keep
        let width_inches = self.bbox.width / 72.0;
        let height_inches = self.bbox.height / 72.0;

        if width_inches > 0.0 && self.width > 0 {
            self.horizontal_dpi = Some(self.width as f32 / width_inches);
        }

        if height_inches > 0.0 && self.height > 0 {
            self.vertical_dpi = Some(self.height as f32 / height_inches);
        }
    }

    /// Get the resolution as (horizontal_dpi, vertical_dpi).
    ///
    /// Returns None if DPI hasn't been calculated or bbox is invalid.
    pub fn resolution(&self) -> Option<(f32, f32)> {
        match (self.horizontal_dpi, self.vertical_dpi) {
            (Some(h), Some(v)) => Some((h, v)),
            _ => None,
        }
    }

    /// Get the horizontal DPI.
    pub fn get_horizontal_dpi(&self) -> Option<f32> {
        self.horizontal_dpi
    }

    /// Get the vertical DPI.
    pub fn get_vertical_dpi(&self) -> Option<f32> {
        self.vertical_dpi
    }

    /// Check if this image is high resolution (>= 300 DPI in both dimensions).
    ///
    /// 300 DPI is considered the standard for print-quality images.
    pub fn is_high_resolution(&self) -> bool {
        match self.resolution() {
            Some((h, v)) => h >= 300.0 && v >= 300.0,
            None => false,
        }
    }

    /// Check if this image is low resolution (< 150 DPI in either dimension).
    ///
    /// 150 DPI is often considered the minimum for reasonable quality.
    pub fn is_low_resolution(&self) -> bool {
        match self.resolution() {
            Some((h, v)) => h < 150.0 || v < 150.0,
            None => false,
        }
    }

    /// Check if this image is medium resolution (>= 150 DPI but < 300 DPI).
    pub fn is_medium_resolution(&self) -> bool {
        match self.resolution() {
            Some((h, v)) => {
                let min_dpi = h.min(v);
                (150.0..300.0).contains(&min_dpi)
            }
            None => false,
        }
    }

    /// Create an `ImageContent` from raw image bytes, auto-detecting JPEG/PNG by magic number.
    ///
    /// Pixel dimensions, color space, and soft mask are parsed from the image header
    /// automatically — no need to supply `width` or `height`. `bbox` controls the
    /// on-page display rectangle in PDF points (72 pt = 1 inch).
    ///
    /// Returns an error if the bytes do not start with a recognised image magic number.
    pub fn from_bytes(bbox: Rect, data: Vec<u8>) -> Result<Self, crate::error::Error> {
        let parsed = parse_image_header(&data)?;
        let mut image = Self {
            bbox,
            format: parsed.format,
            data,
            width: parsed.width,
            height: parsed.height,
            bits_per_component: parsed.bits_per_component,
            color_space: parsed.color_space,
            reading_order: None,
            alt_text: None,
            horizontal_dpi: None,
            vertical_dpi: None,
            soft_mask: parsed.soft_mask,
            matrix: None,
            is_artifact: false,
        };
        image.calculate_dpi();
        Ok(image)
    }
}

impl Default for ImageContent {
    fn default() -> Self {
        Self {
            bbox: Rect::new(0.0, 0.0, 0.0, 0.0),
            format: ImageFormat::Unknown,
            data: Vec::new(),
            width: 0,
            height: 0,
            bits_per_component: 8,
            color_space: ColorSpace::RGB,
            reading_order: None,
            alt_text: None,
            horizontal_dpi: None,
            vertical_dpi: None,
            soft_mask: None,
            matrix: None,
            is_artifact: false,
        }
    }
}

/// Supported image formats.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ImageFormat {
    /// JPEG format
    Jpeg,
    /// PNG format
    Png,
    /// JPEG 2000 format (JPX)
    Jpeg2000,
    /// JBIG2 format (typically for scanned documents)
    Jbig2,
    /// Raw uncompressed image data
    Raw,
    /// Unknown or unsupported format
    Unknown,
}

impl ImageFormat {
    /// Get the MIME type for this format.
    pub fn mime_type(&self) -> &'static str {
        match self {
            ImageFormat::Jpeg => "image/jpeg",
            ImageFormat::Png => "image/png",
            ImageFormat::Jpeg2000 => "image/jp2",
            ImageFormat::Jbig2 => "image/jbig2",
            ImageFormat::Raw => "application/octet-stream",
            ImageFormat::Unknown => "application/octet-stream",
        }
    }

    /// Get the typical file extension for this format.
    pub fn extension(&self) -> &'static str {
        match self {
            ImageFormat::Jpeg => "jpg",
            ImageFormat::Png => "png",
            ImageFormat::Jpeg2000 => "jp2",
            ImageFormat::Jbig2 => "jbig2",
            ImageFormat::Raw => "raw",
            ImageFormat::Unknown => "bin",
        }
    }
}

/// Color space for images.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[allow(clippy::upper_case_acronyms)]
pub enum ColorSpace {
    /// Grayscale (1 component)
    Gray,
    /// RGB color (3 components)
    #[default]
    RGB,
    /// CMYK color (4 components)
    CMYK,
    /// Indexed color (palette-based)
    Indexed,
    /// Lab color space
    Lab,
}

impl ColorSpace {
    /// Get the number of components for this color space.
    pub fn components(&self) -> u8 {
        match self {
            ColorSpace::Gray => 1,
            ColorSpace::RGB => 3,
            ColorSpace::CMYK => 4,
            ColorSpace::Indexed => 1,
            ColorSpace::Lab => 3,
        }
    }
}

/// Parsed image header fields extracted by [`parse_image_header`].
struct ParsedImageHeader {
    width: u32,
    height: u32,
    bits_per_component: u8,
    color_space: ColorSpace,
    format: ImageFormat,
    soft_mask: Option<Vec<u8>>,
}

/// Parse a JPEG or PNG image header, auto-detecting the format by magic number.
///
/// This extracts pixel dimensions, colour space, and (for PNG) an alpha
/// channel encoded as a PDF-ready soft mask. The original encoded bytes are
/// left untouched by the caller; this function only inspects them.
///
/// Returns an error if the bytes do not start with a recognised image magic
/// number.
fn parse_image_header(data: &[u8]) -> Result<ParsedImageHeader, crate::error::Error> {
    if data.len() >= 2 && data[0] == 0xFF && data[1] == 0xD8 {
        let (width, height, color_space) = parse_jpeg_dimensions(data).map_err(crate::error::Error::Image)?;
        return Ok(ParsedImageHeader {
            width,
            height,
            bits_per_component: 8,
            color_space,
            format: ImageFormat::Jpeg,
            soft_mask: None,
        });
    }

    if data.len() >= 8 && &data[0..8] == b"\x89PNG\r\n\x1a\n" {
        return parse_png_header(data);
    }

    Err(crate::error::Error::Image("Unsupported image format".to_string()))
}

/// Parse a JPEG SOF marker to extract width, height, and colour space
/// without decoding the compressed image data.
fn parse_jpeg_dimensions(data: &[u8]) -> Result<(u32, u32, ColorSpace), String> {
    if data.len() < 2 || data[0] != 0xFF || data[1] != 0xD8 {
        return Err("Not a valid JPEG".to_string());
    }

    let mut pos = 2;
    while pos < data.len() - 1 {
        if data[pos] != 0xFF {
            pos += 1;
            continue;
        }

        let marker = data[pos + 1];
        pos += 2;

        if marker == 0xFF || marker == 0x00 {
            continue;
        }

        // SOF markers (Start of Frame) ~keep
        if matches!(
            marker,
            0xC0 | 0xC1 | 0xC2 | 0xC3 | 0xC5 | 0xC6 | 0xC7 | 0xC9 | 0xCA | 0xCB | 0xCD | 0xCE | 0xCF
        ) {
            if pos + 7 > data.len() {
                return Err("Truncated JPEG header".to_string());
            }

            let _precision = data[pos + 2];
            let height = u16::from_be_bytes([data[pos + 3], data[pos + 4]]) as u32;
            let width = u16::from_be_bytes([data[pos + 5], data[pos + 6]]) as u32;
            let components = data[pos + 7];

            let color_space = match components {
                1 => ColorSpace::Gray,
                3 => ColorSpace::RGB,
                4 => ColorSpace::CMYK,
                _ => ColorSpace::RGB,
            };

            return Ok((width, height, color_space));
        }

        if pos + 2 > data.len() {
            break;
        }
        let length = u16::from_be_bytes([data[pos], data[pos + 1]]) as usize;
        pos += length;
    }

    Err("Could not find JPEG dimensions".to_string())
}

/// Decode a PNG to extract width, height, colour space, and (if present) an
/// alpha channel encoded as a PDF-ready soft mask.
///
/// Unlike the JPEG path this must fully decode the pixel data: PNG's alpha
/// channel is interleaved with colour samples, so there is no header field
/// to read the way JPEG's SOF marker gives dimensions directly.
fn parse_png_header(data: &[u8]) -> Result<ParsedImageHeader, crate::error::Error> {
    use image::GenericImageView;

    let img = image::load_from_memory_with_format(data, image::ImageFormat::Png)
        .map_err(|e| crate::error::Error::Image(e.to_string()))?;
    let (width, height) = img.dimensions();

    let (color_space, alpha): (ColorSpace, Option<Vec<u8>>) = match img.color() {
        image::ColorType::L8 | image::ColorType::L16 => (ColorSpace::Gray, None),
        image::ColorType::La8 | image::ColorType::La16 => {
            let luma_alpha = img.to_luma_alpha8();
            let alpha_channel = luma_alpha.pixels().map(|pixel| pixel.0[1]).collect();
            (ColorSpace::Gray, Some(alpha_channel))
        }
        image::ColorType::Rgb8 | image::ColorType::Rgb16 => (ColorSpace::RGB, None),
        image::ColorType::Rgba8 | image::ColorType::Rgba16 => {
            let rgba = img.to_rgba8();
            let alpha_channel = rgba.pixels().map(|pixel| pixel.0[3]).collect();
            (ColorSpace::RGB, Some(alpha_channel))
        }
        _ => (ColorSpace::RGB, None),
    };

    // Alpha is 1 component (gray) per pixel. ~keep
    let soft_mask = alpha.map(|a| compress_soft_mask(&a, width)).transpose()?;

    Ok(ParsedImageHeader {
        width,
        height,
        bits_per_component: 8,
        color_space,
        format: ImageFormat::Png,
        soft_mask,
    })
}

/// Compress a single-component (grayscale) alpha channel using Flate with a
/// PNG None-filter byte (0x00) prepended to each scanline.
///
/// The PDF spec requires that when `FlateDecode` is used with
/// `DecodeParms/Predictor=15` (PNG adaptive predictor), the decompressed
/// byte stream must begin each row with a filter-type byte followed by the
/// (possibly filtered) row samples. Filter type 0 = None means the samples
/// are stored verbatim. Flate still compresses the whole stream, including
/// the filter bytes, so LZ compression quality is unaffected.
fn compress_soft_mask(pixels: &[u8], width: u32) -> Result<Vec<u8>, crate::error::Error> {
    use std::io::Write;

    use flate2::Compression;
    use flate2::write::ZlibEncoder;

    let row_bytes = width as usize;

    if row_bytes == 0 || pixels.is_empty() {
        let encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        return encoder.finish().map_err(|e| crate::error::Error::Image(e.to_string()));
    }

    // Pre-allocate: 1 filter byte per row + all pixel bytes. ~keep
    let num_rows = pixels.len().div_ceil(row_bytes);
    let mut filtered = Vec::with_capacity(pixels.len() + num_rows);
    for row in pixels.chunks(row_bytes) {
        filtered.push(0u8);
        filtered.extend_from_slice(row);
    }

    let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
    encoder
        .write_all(&filtered)
        .map_err(|e| crate::error::Error::Image(e.to_string()))?;
    encoder.finish().map_err(|e| crate::error::Error::Image(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_image_content_creation() {
        let image = ImageContent::new(
            Rect::new(0.0, 0.0, 100.0, 100.0),
            ImageFormat::Jpeg,
            vec![0u8; 1000],
            800,
            600,
        );

        assert_eq!(image.width, 800);
        assert_eq!(image.height, 600);
        assert_eq!(image.format, ImageFormat::Jpeg);
    }

    #[test]
    fn test_aspect_ratio() {
        let image = ImageContent::new(Rect::new(0.0, 0.0, 100.0, 100.0), ImageFormat::Png, vec![], 1920, 1080);

        let ratio = image.aspect_ratio();
        assert!((ratio - (1920.0 / 1080.0)).abs() < 0.001);
    }

    #[test]
    fn test_color_space_components() {
        assert_eq!(ColorSpace::Gray.components(), 1);
        assert_eq!(ColorSpace::RGB.components(), 3);
        assert_eq!(ColorSpace::CMYK.components(), 4);
    }

    #[test]
    fn test_image_format_extension() {
        assert_eq!(ImageFormat::Jpeg.extension(), "jpg");
        assert_eq!(ImageFormat::Png.extension(), "png");
        assert_eq!(ImageFormat::Jpeg2000.extension(), "jp2");
    }

    #[test]
    fn test_dpi_calculation_high_res() {
        // 600 pixels in 2 inches (144 points) = 300 DPI ~keep
        let image = ImageContent::new(Rect::new(0.0, 0.0, 144.0, 144.0), ImageFormat::Jpeg, vec![], 600, 600);

        let (h, v) = image.resolution().unwrap();
        assert!((h - 300.0).abs() < 1.0);
        assert!((v - 300.0).abs() < 1.0);
        assert!(image.is_high_resolution());
        assert!(!image.is_low_resolution());
    }

    #[test]
    fn test_dpi_calculation_low_res() {
        // 100 pixels in 1 inch (72 points) = ~100 DPI ~keep
        let image = ImageContent::new(Rect::new(0.0, 0.0, 72.0, 72.0), ImageFormat::Png, vec![], 100, 100);

        let (h, v) = image.resolution().unwrap();
        assert!((h - 100.0).abs() < 1.0);
        assert!((v - 100.0).abs() < 1.0);
        assert!(!image.is_high_resolution());
        assert!(image.is_low_resolution());
    }

    #[test]
    fn test_dpi_calculation_medium_res() {
        // 200 pixels in 1 inch = 200 DPI (medium) ~keep
        let image = ImageContent::new(Rect::new(0.0, 0.0, 72.0, 72.0), ImageFormat::Png, vec![], 200, 200);

        let (h, v) = image.resolution().unwrap();
        assert!((h - 200.0).abs() < 1.0);
        assert!((v - 200.0).abs() < 1.0);
        assert!(image.is_medium_resolution());
    }

    #[test]
    fn test_dpi_asymmetric() {
        // Different DPI in horizontal and vertical
        // 300 pixels in 1 inch (horizontal) = 300 DPI
        // 100 pixels in 1 inch (vertical) = 100 DPI ~keep
        let image = ImageContent::new(Rect::new(0.0, 0.0, 72.0, 72.0), ImageFormat::Png, vec![], 300, 100);

        let (h, v) = image.resolution().unwrap();
        assert!((h - 300.0).abs() < 1.0);
        assert!((v - 100.0).abs() < 1.0);

        // Low resolution because vertical is < 150 ~keep
        assert!(image.is_low_resolution());
        // Not high resolution because both need to be >= 300 ~keep
        assert!(!image.is_high_resolution());
    }

    #[test]
    fn test_dpi_zero_dimensions() {
        // Zero bbox should result in no DPI ~keep
        let image = ImageContent::default();
        assert!(image.resolution().is_none());
    }

    #[test]
    fn test_dpi_getters() {
        let image = ImageContent::new(Rect::new(0.0, 0.0, 72.0, 72.0), ImageFormat::Png, vec![], 300, 300);

        assert!(image.get_horizontal_dpi().is_some());
        assert!(image.get_vertical_dpi().is_some());
        assert!((image.get_horizontal_dpi().unwrap() - 300.0).abs() < 1.0);
    }

    fn encode_png(image: image::DynamicImage) -> Vec<u8> {
        let mut bytes = Vec::new();
        image
            .write_to(&mut std::io::Cursor::new(&mut bytes), image::ImageFormat::Png)
            .expect("encode test PNG");
        bytes
    }

    fn encode_jpeg(image: image::DynamicImage) -> Vec<u8> {
        let mut bytes = Vec::new();
        image
            .write_to(&mut std::io::Cursor::new(&mut bytes), image::ImageFormat::Jpeg)
            .expect("encode test JPEG");
        bytes
    }

    #[test]
    fn from_bytes_should_parse_rgb_png_header_without_soft_mask() {
        let rgb = image::RgbImage::from_pixel(4, 3, image::Rgb([10, 20, 30]));
        let png_bytes = encode_png(image::DynamicImage::ImageRgb8(rgb));

        let image = ImageContent::from_bytes(Rect::new(0.0, 0.0, 72.0, 72.0), png_bytes.clone())
            .expect("from_bytes should parse a valid PNG header");

        assert_eq!(image.width, 4);
        assert_eq!(image.height, 3);
        assert_eq!(image.format, ImageFormat::Png);
        assert_eq!(image.color_space, ColorSpace::RGB);
        assert_eq!(image.bits_per_component, 8);
        assert!(image.soft_mask.is_none());
        // The original encoded bytes are preserved verbatim, not re-encoded. ~keep
        assert_eq!(image.data, png_bytes);
    }

    #[test]
    fn from_bytes_should_extract_soft_mask_from_rgba_png() {
        let rgba = image::RgbaImage::from_pixel(2, 2, image::Rgba([1, 2, 3, 128]));
        let png_bytes = encode_png(image::DynamicImage::ImageRgba8(rgba));

        let image = ImageContent::from_bytes(Rect::new(0.0, 0.0, 72.0, 72.0), png_bytes)
            .expect("from_bytes should parse an RGBA PNG header");

        assert_eq!(image.width, 2);
        assert_eq!(image.height, 2);
        assert_eq!(image.color_space, ColorSpace::RGB);
        assert!(image.soft_mask.is_some(), "RGBA PNG must produce a soft mask");
    }

    #[test]
    fn from_bytes_should_parse_grayscale_png_header() {
        let gray = image::GrayImage::from_pixel(5, 6, image::Luma([42]));
        let png_bytes = encode_png(image::DynamicImage::ImageLuma8(gray));

        let image = ImageContent::from_bytes(Rect::new(0.0, 0.0, 72.0, 72.0), png_bytes)
            .expect("from_bytes should parse a grayscale PNG header");

        assert_eq!(image.width, 5);
        assert_eq!(image.height, 6);
        assert_eq!(image.color_space, ColorSpace::Gray);
        assert!(image.soft_mask.is_none());
    }

    #[test]
    fn from_bytes_should_parse_jpeg_header_via_sof_marker() {
        let rgb = image::RgbImage::from_pixel(16, 8, image::Rgb([200, 100, 50]));
        let jpeg_bytes = encode_jpeg(image::DynamicImage::ImageRgb8(rgb));

        let image = ImageContent::from_bytes(Rect::new(0.0, 0.0, 72.0, 72.0), jpeg_bytes.clone())
            .expect("from_bytes should parse a valid JPEG SOF marker");

        assert_eq!(image.width, 16);
        assert_eq!(image.height, 8);
        assert_eq!(image.format, ImageFormat::Jpeg);
        assert_eq!(image.color_space, ColorSpace::RGB);
        assert_eq!(image.bits_per_component, 8);
        assert!(image.soft_mask.is_none());
        assert_eq!(image.data, jpeg_bytes);
    }

    #[test]
    fn from_bytes_should_reject_unrecognised_magic_number() {
        let result = ImageContent::from_bytes(Rect::new(0.0, 0.0, 72.0, 72.0), vec![0u8; 16]);
        assert!(result.is_err(), "non-image bytes must not parse as an image header");
    }
}
