use crate::error::{Result, SasooError};

use super::types::{CoordinateSpace, EngineBox, PageBox, PageGeometry, PdfUserBox};

/// Return unrotated raw PDF user coordinates for the existing PDF.js overlay.
pub fn to_pdf_user_space(bbox: EngineBox, page: &PageGeometry) -> Result<Option<PdfUserBox>> {
    page.validate()?;
    if !bbox.coords.iter().all(|value| value.is_finite()) {
        return Err(invalid("BBox coordinates must be finite"));
    }
    let [x0, y0, x1, y1] = bbox.coords;
    if x0 == x1 || y0 == y1 {
        return Ok(None);
    }
    let mut points = Vec::with_capacity(4);
    for (x, y) in [(x0, y0), (x1, y0), (x0, y1), (x1, y1)] {
        let point = match &bbox.space {
            CoordinateSpace::PdfUserSpace => (x, y),
            CoordinateSpace::PhysicalPoints => (x / page.user_unit, y / page.user_unit),
            CoordinateSpace::UnrotatedTopLeft { reference } => {
                let [left, _, _, top] = page.reference_box(*reference);
                (left + x, top - y)
            }
            CoordinateSpace::DisplayTopLeft { reference } => from_display(x, y, page, *reference),
            CoordinateSpace::DisplayNormalized { reference } => {
                let (width, height) = display_size(page, *reference);
                from_display(x * width, y * height, page, *reference)
            }
            CoordinateSpace::DisplayPixels {
                reference,
                width,
                height,
            } => {
                if !width.is_finite() || !height.is_finite() || *width <= 0.0 || *height <= 0.0 {
                    return Err(invalid(
                        "Raster width and height must be finite and positive",
                    ));
                }
                let (display_width, display_height) = display_size(page, *reference);
                from_display(
                    x * display_width / width,
                    y * display_height / height,
                    page,
                    *reference,
                )
            }
            CoordinateSpace::EngineNative { name } => {
                if name.trim().is_empty() {
                    return Err(invalid(
                        "Native coordinate space needs its engine's frame name",
                    ));
                }
                let Some(matrix) = page.engine_to_pdf_user_space else {
                    return Ok(None);
                };
                let determinant = matrix.a * matrix.d - matrix.b * matrix.c;
                if ![matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f]
                    .iter()
                    .all(|value| value.is_finite())
                    || !determinant.is_finite()
                    || determinant == 0.0
                {
                    return Err(invalid(
                        "Engine coordinate transform must be finite and invertible",
                    ));
                }
                (
                    matrix.a * x + matrix.c * y + matrix.e,
                    matrix.b * x + matrix.d * y + matrix.f,
                )
            }
        };
        if !point.0.is_finite() || !point.1.is_finite() {
            return Err(invalid("Coordinate transform produced a nonfinite value"));
        }
        points.push(point);
    }
    let coords = [
        points.iter().map(|p| p.0).fold(f64::INFINITY, f64::min),
        points.iter().map(|p| p.1).fold(f64::INFINITY, f64::min),
        points.iter().map(|p| p.0).fold(f64::NEG_INFINITY, f64::max),
        points.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max),
    ];
    if coords[2] <= coords[0] || coords[3] <= coords[1] {
        return Err(invalid(
            "Coordinate transform lost the bbox's positive area",
        ));
    }
    Ok(Some(PdfUserBox { coords }))
}

/// Keep physical points separate from the raw coordinates sent to PDF.js.
pub fn to_physical_points(bbox: PdfUserBox, page: &PageGeometry) -> Result<[f64; 4]> {
    page.validate()?;
    if bbox.coords[2] <= bbox.coords[0] || bbox.coords[3] <= bbox.coords[1] {
        return Err(invalid(
            "Physical conversion requires an ordered bbox with positive area",
        ));
    }
    let points = bbox.coords.map(|value| value * page.user_unit);
    if !points.iter().all(|value| value.is_finite()) {
        return Err(invalid(
            "Physical point conversion produced a nonfinite value",
        ));
    }
    Ok(points)
}

fn display_size(page: &PageGeometry, reference: PageBox) -> (f64, f64) {
    let [left, bottom, right, top] = page.reference_box(reference);
    if matches!(page.rotation_deg, 90 | 270) {
        (top - bottom, right - left)
    } else {
        (right - left, top - bottom)
    }
}

fn from_display(x: f64, y: f64, page: &PageGeometry, reference: PageBox) -> (f64, f64) {
    let [left, bottom, right, top] = page.reference_box(reference);
    match page.rotation_deg {
        0 => (left + x, top - y),
        90 => (left + y, bottom + x),
        180 => (right - x, bottom + y),
        270 => (right - y, top - x),
        _ => unreachable!("page geometry is checked before coordinate conversion"),
    }
}

fn invalid(message: &str) -> SasooError {
    SasooError::InvalidInput(message.into())
}
