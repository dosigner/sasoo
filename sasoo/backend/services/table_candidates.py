"""
Table candidate generation for resolver_v1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber
from PIL import Image


def _bbox_area(bbox: list[float] | None) -> float:
    if not bbox:
        return 0.0
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _bbox_iou(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    union = _bbox_area(a) + _bbox_area(b) - inter
    return inter / union if union else 0.0


def _bbox_dims(bbox: list[float] | None) -> tuple[float, float]:
    if not bbox:
        return (0.0, 0.0)
    return (max(0.0, bbox[2] - bbox[0]), max(0.0, bbox[3] - bbox[1]))


def _page_size_tuple(page: dict[str, Any]) -> tuple[float, float]:
    size = page.get("page_size") or {}
    return float(size.get("width") or 0.0), float(size.get("height") or 0.0)


def _normalize_grid(grid: list[list[Any]] | None) -> list[list[str]]:
    if not grid:
        return []
    width = max((len(row) for row in grid if row), default=0)
    normalized: list[list[str]] = []
    for row in grid:
        values = ["" if value is None else str(value).strip() for value in row]
        if width and len(values) < width:
            values.extend([""] * (width - len(values)))
        if any(value for value in values):
            normalized.append(values)
    return normalized


def _has_irregular_rows(grid: list[list[Any]] | None) -> bool:
    if not grid:
        return False
    widths = {len(row) for row in grid if row}
    return len(widths) > 1


def _grid_non_empty_cells(grid: list[list[str]]) -> int:
    return sum(1 for row in grid for cell in row if cell.strip())


def _is_meaningful_grid(grid: list[list[str]]) -> bool:
    if not grid:
        return False
    width = max((len(row) for row in grid if row), default=0)
    non_empty = _grid_non_empty_cells(grid)
    return len(grid) >= 2 and width >= 2 and non_empty >= 4


def _is_plausible_table_bbox(bbox: list[float] | None, page: dict[str, Any]) -> bool:
    if not bbox:
        return False
    page_width, page_height = _page_size_tuple(page)
    width, height = _bbox_dims(bbox)
    if width < 72 or height < 56:
        return False
    if not page_width or not page_height:
        return False
    area_ratio = _bbox_area(bbox) / (page_width * page_height)
    return area_ratio >= 0.02 and width / page_width >= 0.2 and height / page_height >= 0.08


def _caption_candidates(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [caption for caption in page.get("caption_blocks", []) if caption.get("kind") == "table"]


def _horizontal_overlap_ratio(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    if overlap <= 0:
        return 0.0
    base = max(1.0, min(a[2] - a[0], b[2] - b[0]))
    return overlap / base


def _best_caption_for_bbox(page: dict[str, Any], bbox: list[float] | None) -> tuple[str | None, list[str]]:
    captions = _caption_candidates(page)
    if not captions or not bbox:
        return (None, [])
    page_width, page_height = _page_size_tuple(page)
    ranked = sorted(
        [
            caption
            for caption in captions
            if (
                _horizontal_overlap_ratio(caption.get("bbox"), bbox) >= 0.3
                or abs((((caption.get("bbox") or [0, 0, 0, 0])[0] + (caption.get("bbox") or [0, 0, 0, 0])[2]) / 2) - ((bbox[0] + bbox[2]) / 2)) <= page_width * 0.18
            )
            and abs((((caption.get("bbox") or [0, 0, 0, 0])[1] + (caption.get("bbox") or [0, 0, 0, 0])[3]) / 2) - ((bbox[1] + bbox[3]) / 2)) <= page_height * 0.32
        ],
        key=lambda caption: (
            -_horizontal_overlap_ratio(caption.get("bbox"), bbox),
            abs(((caption.get("bbox") or [0, 0, 0, 0])[1] + (caption.get("bbox") or [0, 0, 0, 0])[3]) / 2 - ((bbox[1] + bbox[3]) / 2)),
            abs((caption.get("order") or 0)),
        ),
    )
    if not ranked:
        return (None, [])
    return (ranked[0]["id"], [caption["id"] for caption in ranked[:3]])


def _pdfplumber_candidates(pdf_path: Path, page_numbers: set[int] | None = None) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            if page_numbers and page_index not in page_numbers:
                continue
            page_height = float(page.height)
            entries: list[dict[str, Any]] = []
            for idx, table in enumerate(page.find_tables()):
                try:
                    raw_grid = table.extract()
                    grid = _normalize_grid(raw_grid)
                except Exception:
                    raw_grid = []
                    grid = []
                x0, top, x1, bottom = [float(value) for value in table.bbox]
                bbox = [x0, page_height - bottom, x1, page_height - top]
                entries.append(
                    {
                        "id": f"pdfplumber:p{page_index}:n{idx}",
                        "bbox": bbox,
                        "text_grid": grid,
                        "source_kind": "pdfplumber",
                        "had_irregular_rows": _has_irregular_rows(raw_grid),
                    }
                )
            result[page_index] = entries
    return result


def _raster_ruled_table_candidates(page: dict[str, Any], paper_dir: Path, *, aggressive: bool) -> list[dict[str, Any]]:
    raster_path = page.get("raster_path")
    if not raster_path:
        return []
    image_path = (paper_dir / raster_path).resolve()
    if not image_path.exists():
        return []

    with Image.open(image_path) as image:
        grayscale = image.convert("L")
        width, height = grayscale.size
        pixels = grayscale.load()
        horizontal = []
        vertical = []
        for y in range(height):
            dark = sum(1 for x in range(width) if pixels[x, y] < 80)
            horizontal.append(dark / max(width, 1))
        for x in range(width):
            dark = sum(1 for y in range(height) if pixels[x, y] < 80)
            vertical.append(dark / max(height, 1))

    line_rows = [index for index, value in enumerate(horizontal) if value >= (0.32 if aggressive else 0.42)]
    line_cols = [index for index, value in enumerate(vertical) if value >= (0.2 if aggressive else 0.3)]
    if len(line_rows) < 3 or len(line_cols) < 2:
        return []

    x0_px = min(line_cols)
    x1_px = max(line_cols)
    y0_px = min(line_rows)
    y1_px = max(line_rows)
    page_width, page_height = _page_size_tuple(page)
    if not page_width or not page_height:
        return []
    bbox = [
        x0_px / width * page_width,
        page_height - (y1_px / height * page_height),
        x1_px / width * page_width,
        page_height - (y0_px / height * page_height),
    ]
    return [
        {
            "bbox": bbox,
            "source_kind": "raster_ruled_table",
            "text_grid": [],
        }
    ]


def build_table_candidates(
    manifest: dict[str, Any],
    *,
    pdf_path: Path,
    paper_dir: Path,
    page_numbers: set[int] | None = None,
    aggressive: bool = False,
) -> list[dict[str, Any]]:
    pdfplumber_by_page = _pdfplumber_candidates(pdf_path, page_numbers=page_numbers)
    candidates: list[dict[str, Any]] = []

    for page in manifest.get("pages", []):
        page_number = page.get("page_number")
        if not isinstance(page_number, int):
            continue
        if page_numbers and page_number not in page_numbers:
            continue

        base_candidates: list[dict[str, Any]] = []
        for node in page.get("odl_table_nodes", []):
            raw_rows = node.get("rows")
            grid = _normalize_grid(raw_rows)
            bbox = node.get("bbox")
            if not _is_meaningful_grid(grid) and not _is_plausible_table_bbox(bbox, page):
                continue
            base_candidates.append(
                {
                    "bbox": bbox,
                    "source_kind": "odl",
                    "text_grid": grid,
                    "source_block_ids": [node.get("id")] if node.get("id") else [],
                    "had_irregular_rows": _has_irregular_rows(raw_rows),
                }
            )
        for candidate in pdfplumber_by_page.get(page_number, []):
            if _is_meaningful_grid(candidate.get("text_grid") or []) or _is_plausible_table_bbox(candidate.get("bbox"), page):
                base_candidates.append(candidate)
        for candidate in _raster_ruled_table_candidates(page, paper_dir, aggressive=aggressive):
            if _is_plausible_table_bbox(candidate.get("bbox"), page):
                base_candidates.append(candidate)

        merged: list[dict[str, Any]] = []
        for candidate in base_candidates:
            bbox = candidate.get("bbox")
            matched = None
            for existing in merged:
                if _bbox_iou(existing.get("bbox"), bbox) >= 0.75:
                    matched = existing
                    break
            if matched is None:
                merged.append(candidate)
                continue

            existing_grid = matched.get("text_grid") or []
            new_grid = candidate.get("text_grid") or []
            if _is_meaningful_grid(new_grid) and not _is_meaningful_grid(existing_grid):
                matched["text_grid"] = new_grid
            elif len(new_grid) > len(existing_grid):
                matched["text_grid"] = new_grid
            matched["source_kind"] = "hybrid"
            matched["source_block_ids"] = sorted({*(matched.get("source_block_ids") or []), *(candidate.get("source_block_ids") or [])})
            matched["had_irregular_rows"] = bool(matched.get("had_irregular_rows")) or bool(candidate.get("had_irregular_rows"))

        for index, candidate in enumerate(sorted(merged, key=lambda item: ((item.get("bbox") or [0, 0, 0, 0])[1], (item.get("bbox") or [0, 0, 0, 0])[0]))):
            grid = _normalize_grid(candidate.get("text_grid"))
            if not _is_meaningful_grid(grid) and not _is_plausible_table_bbox(candidate.get("bbox"), page):
                continue
            best_caption_id, caption_options = _best_caption_for_bbox(page, candidate.get("bbox"))
            candidates.append(
                {
                    "id": f"tblcand:p{page_number}:n{index}",
                    "page_number": page_number,
                    "bbox": candidate.get("bbox"),
                    "source_kind": candidate.get("source_kind") or "hybrid",
                    "source_parsers": [candidate.get("source_kind") or "hybrid"],
                    "text_grid": grid,
                    "linked_caption_ids": caption_options,
                    "best_caption_id": best_caption_id,
                    "source_block_ids": candidate.get("source_block_ids") or [],
                    "has_meaningful_grid": _is_meaningful_grid(grid),
                    "plausible_ruled_bbox": _is_plausible_table_bbox(candidate.get("bbox"), page),
                    "had_irregular_rows": bool(candidate.get("had_irregular_rows")),
                }
            )
    return candidates
