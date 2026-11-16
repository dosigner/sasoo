use std::{
    collections::HashSet,
    path::{Component, PathBuf},
};

use serde::{Deserialize, Serialize};

use crate::{
    error::{Result, SasooError},
    types::Hash256,
};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EngineIdentity {
    pub name: String,
    pub version: String,
    pub revision: Option<String>,
    pub resource_manifest_sha256: Option<Hash256>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PageBox {
    Media,
    Crop,
    // PDF.js uses the crop/media intersection and falls back to MediaBox.
    EffectiveCrop,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum CoordinateSpace {
    PdfUserSpace,
    // Physical points use the same unrotated origin as raw PDF user coordinates.
    PhysicalPoints,
    UnrotatedTopLeft {
        reference: PageBox,
    },
    DisplayTopLeft {
        reference: PageBox,
    },
    DisplayPixels {
        reference: PageBox,
        width: f64,
        height: f64,
    },
    DisplayNormalized {
        reference: PageBox,
    },
    EngineNative {
        name: String,
    },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EngineBox {
    pub coords: [f64; 4],
    pub space: CoordinateSpace,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PdfUserBox {
    pub coords: [f64; 4],
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct AffineTransform {
    pub a: f64,
    pub b: f64,
    pub c: f64,
    pub d: f64,
    pub e: f64,
    pub f: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PageGeometry {
    pub media_box: [f64; 4],
    pub crop_box: [f64; 4],
    pub rotation_deg: u16,
    pub user_unit: f64,
    pub engine_to_pdf_user_space: Option<AffineTransform>,
}

impl PageGeometry {
    pub fn validate(&self) -> Result<()> {
        for rectangle in [self.media_box, self.crop_box] {
            if !rectangle.iter().all(|value| value.is_finite())
                || rectangle[2] <= rectangle[0]
                || rectangle[3] <= rectangle[1]
                || !(rectangle[2] - rectangle[0]).is_finite()
                || !(rectangle[3] - rectangle[1]).is_finite()
            {
                return Err(invalid("Page boxes must be finite and have positive area"));
            }
        }
        if !matches!(self.rotation_deg, 0 | 90 | 180 | 270) {
            return Err(invalid("Page rotation must be 0, 90, 180, or 270 degrees"));
        }
        if !self.user_unit.is_finite() || self.user_unit <= 0.0 {
            return Err(invalid("PDF UserUnit must be finite and positive"));
        }
        Ok(())
    }

    pub fn reference_box(&self, reference: PageBox) -> [f64; 4] {
        match reference {
            PageBox::Media => self.media_box,
            PageBox::Crop => self.crop_box,
            PageBox::EffectiveCrop => {
                let [ml, mb, mr, mt] = self.media_box;
                let [cl, cb, cr, ct] = self.crop_box;
                let intersection = [ml.max(cl), mb.max(cb), mr.min(cr), mt.min(ct)];
                if intersection[2] > intersection[0] && intersection[3] > intersection[1] {
                    intersection
                } else {
                    self.media_box
                }
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Page {
    pub page_index0: u32,
    pub page_number1: u32,
    pub media_box: [f64; 4],
    pub crop_box: [f64; 4],
    pub rotation_deg: u16,
    pub user_unit: f64,
    pub source_space: CoordinateSpace,
    #[serde(default)]
    pub engine_to_pdf_user_space: Option<AffineTransform>,
}

impl Page {
    pub fn geometry(&self) -> PageGeometry {
        PageGeometry {
            media_box: self.media_box,
            crop_box: self.crop_box,
            rotation_deg: self.rotation_deg,
            user_unit: self.user_unit,
            engine_to_pdf_user_space: self.engine_to_pdf_user_space,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EngineConfidence {
    pub value: f64,
    pub metric: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Provenance {
    pub source_kind: String,
    pub source_native_id: Option<String>,
    pub engine_revision: Option<String>,
    pub ocr: Option<bool>,
    pub confidence: Option<EngineConfidence>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TableCell {
    pub row: u32,
    pub column: u32,
    pub rowspan: u32,
    pub colspan: u32,
    pub text: String,
    pub source_bbox: Option<EngineBox>,
    pub bbox: Option<PdfUserBox>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum BlockContent {
    Text {
        text: String,
    },
    Heading {
        text: String,
        level: Option<u8>,
    },
    Equation {
        text: String,
        latex: Option<String>,
    },
    Table {
        cells: Vec<TableCell>,
        caption: Option<String>,
    },
    Figure {
        asset_id: Option<String>,
        caption: Option<String>,
    },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Block {
    pub native_id: String,
    pub page_index0: u32,
    pub reading_order: Option<u32>,
    pub source_bbox: Option<EngineBox>,
    pub bbox: Option<PdfUserBox>,
    pub content: BlockContent,
    pub provenance: Provenance,
}

impl Block {
    pub fn has_verified_bbox(&self, page: &PageGeometry) -> bool {
        self.bbox.is_some()
            && self.source_bbox.is_some()
            && validate_evidence_boxes(self.source_bbox.as_ref(), self.bbox, page).is_ok()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AssetRef {
    pub id: String,
    pub relative_path: PathBuf,
    pub sha256: Option<Hash256>,
    pub mime_type: Option<String>,
    pub source_native_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExtractionWarning {
    pub code: String,
    pub message: String,
    pub page_index0: Option<u32>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentArtifact {
    pub source_sha256: Hash256,
    pub engine: EngineIdentity,
    #[serde(default)]
    pub extraction_options_sha256: Option<Hash256>,
    pub pages: Vec<Page>,
    pub blocks: Vec<Block>,
    pub assets: Vec<AssetRef>,
    pub warnings: Vec<ExtractionWarning>,
}

impl DocumentArtifact {
    pub fn validate(&self) -> Result<()> {
        if self.engine.name.trim().is_empty() || self.engine.version.trim().is_empty() {
            return Err(invalid(
                "The extraction engine needs an explicit name and version",
            ));
        }
        if self.pages.is_empty() {
            return Err(invalid("An extracted document needs page geometry"));
        }
        for (index, page) in self.pages.iter().enumerate() {
            if usize::try_from(page.page_index0).ok() != Some(index)
                || page.page_number1
                    != page
                        .page_index0
                        .checked_add(1)
                        .ok_or_else(|| invalid("Page number overflow"))?
            {
                return Err(invalid(
                    "Page indices must be contiguous from zero and page numbers from one",
                ));
            }
            page.geometry().validate()?;
            validate_source_space(&page.source_space)?;
        }
        let mut ids = HashSet::new();
        let mut asset_ids = HashSet::new();
        for asset in &self.assets {
            if asset.id.is_empty()
                || !asset_ids.insert(&asset.id)
                || asset.relative_path.as_os_str().is_empty()
                || asset
                    .relative_path
                    .components()
                    .any(|part| !matches!(part, Component::Normal(_)))
                || asset
                    .relative_path
                    .to_string_lossy()
                    .contains(['\\', ':', '\0'])
            {
                return Err(invalid(
                    "Asset IDs must be unique and asset paths must stay relative",
                ));
            }
        }
        for block in &self.blocks {
            if block.native_id.is_empty() || !ids.insert((block.page_index0, &block.native_id)) {
                return Err(invalid(
                    "Native block IDs must be nonempty and unique on a page",
                ));
            }
            let page = self
                .pages
                .get(block.page_index0 as usize)
                .ok_or_else(|| invalid("Block references an unknown page"))?;
            validate_evidence_boxes(block.source_bbox.as_ref(), block.bbox, &page.geometry())?;
            if let Some(confidence) = &block.provenance.confidence {
                if !confidence.value.is_finite() || confidence.metric.is_empty() {
                    return Err(invalid(
                        "Engine confidence needs a finite value and its own metric name",
                    ));
                }
            }
            match &block.content {
                BlockContent::Table { cells, .. } => {
                    for cell in cells {
                        if cell.rowspan == 0
                            || cell.colspan == 0
                            || cell.row.checked_add(cell.rowspan).is_none()
                            || cell.column.checked_add(cell.colspan).is_none()
                        {
                            return Err(invalid("Table cell spans must be positive"));
                        }
                        validate_evidence_boxes(
                            cell.source_bbox.as_ref(),
                            cell.bbox,
                            &page.geometry(),
                        )?;
                    }
                }
                BlockContent::Figure {
                    asset_id: Some(id), ..
                } if !asset_ids.contains(id) => {
                    return Err(invalid("Figure references an unknown asset ID"));
                }
                _ => {}
            }
        }
        if self.warnings.iter().any(|warning| {
            warning
                .page_index0
                .is_some_and(|index| index as usize >= self.pages.len())
        }) {
            return Err(invalid("Extraction warning references an unknown page"));
        }
        Ok(())
    }
}

fn validate_evidence_boxes(
    source: Option<&EngineBox>,
    bbox: Option<PdfUserBox>,
    page: &PageGeometry,
) -> Result<()> {
    if let Some(source) = source {
        validate_source_space(&source.space)?;
        if !source.coords.iter().all(|value| value.is_finite()) {
            return Err(invalid("Source bbox coordinates must be finite"));
        }
    }
    if let Some(bbox) = bbox {
        let converted = super::coordinates::to_pdf_user_space(
            EngineBox {
                coords: bbox.coords,
                space: CoordinateSpace::PdfUserSpace,
            },
            page,
        )?;
        if converted.is_none()
            || bbox.coords[2] <= bbox.coords[0]
            || bbox.coords[3] <= bbox.coords[1]
        {
            return Err(invalid(
                "Verified bbox coordinates must be ordered with positive area",
            ));
        }
        let source = source.ok_or_else(|| invalid("Verified bbox needs its source coordinates"))?;
        let mapped = super::coordinates::to_pdf_user_space(source.clone(), page)?
            .ok_or_else(|| invalid("Source coordinates have no verified PDF transform"))?;
        for (actual, expected) in mapped.coords.into_iter().zip(bbox.coords) {
            // Allow only floating-point roundoff at the coordinate's own scale.
            let tolerance = 16.0 * f64::EPSILON * actual.abs().max(expected.abs()).max(1.0);
            if (actual - expected).abs() > tolerance {
                return Err(invalid(
                    "Verified bbox differs from the declared source coordinate transform",
                ));
            }
        }
    }
    Ok(())
}

fn validate_source_space(space: &CoordinateSpace) -> Result<()> {
    match space {
        CoordinateSpace::DisplayPixels { width, height, .. }
            if !width.is_finite() || !height.is_finite() || *width <= 0.0 || *height <= 0.0 =>
        {
            return Err(invalid(
                "Raster width and height must be finite and positive",
            ));
        }
        CoordinateSpace::EngineNative { name } if name.trim().is_empty() => {
            return Err(invalid(
                "Native coordinate space needs its engine's frame name",
            ));
        }
        _ => {}
    }
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PdfInput {
    pub path: PathBuf,
    pub source_sha256: Hash256,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PdfOptions {
    pub engine: EngineIdentity,
    pub profile: String,
    pub options_hash: Hash256,
}

fn invalid(message: &str) -> SasooError {
    SasooError::InvalidInput(message.into())
}
