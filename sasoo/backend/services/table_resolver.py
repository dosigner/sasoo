"""
Table resolver for resolver_v1.
"""

from __future__ import annotations

import csv
import json
import os
import re
from io import StringIO
from pathlib import Path
from typing import Any

from api.analysis_helpers import _call_gemini, _clean_llm_json
from services.models import MODEL_RESOLVER

TABLE_LABEL_PATTERN = re.compile(r"^\s*(?:Table|Tbl\.?)\s*(\d+[A-Za-z]?)\b", re.IGNORECASE)


def _normalize_grid(grid: list[list[Any]] | None) -> list[list[str]]:
    if not grid:
        return []
    width = max((len(row) for row in grid if row), default=0)
    rows: list[list[str]] = []
    for row in grid:
        values = ["" if value is None else str(value).strip() for value in row]
        if width and len(values) < width:
            values.extend([""] * (width - len(values)))
        if any(value for value in values):
            rows.append(values)
    return rows


def _has_meaningful_grid(grid: list[list[str]]) -> bool:
    if not grid:
        return False
    width = max((len(row) for row in grid if row), default=0)
    non_empty = sum(1 for row in grid for cell in row if cell.strip())
    return len(grid) >= 2 and width >= 2 and non_empty >= 4


def _flatten_cell(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.replace("\n", " ")).strip()


def _combine_cells(*parts: str) -> str:
    values = [_flatten_cell(part) for part in parts if _flatten_cell(part)]
    if not values:
        return ""
    combined: list[str] = []
    for value in values:
        if value not in combined:
            combined.append(value)
    return " / ".join(combined)


def _has_sparse_header(grid: list[list[str]]) -> bool:
    if len(grid) < 2:
        return False
    header = grid[0]
    next_row = grid[1]
    empty_count = sum(1 for cell in header if not cell.strip())
    next_dense = sum(1 for cell in next_row if cell.strip()) >= max(2, len(next_row) - 1)
    return empty_count >= max(1, len(header) // 3) and next_dense


def _preprocess_grid(grid: list[list[str]]) -> tuple[list[list[str]], list[str]]:
    if not grid:
        return ([], [])

    processed = [[_flatten_cell(cell) for cell in row] for row in grid]
    notes: list[str] = []

    if processed != grid and any("\n" in cell for row in grid[:2] for cell in row):
        notes.append("multiline_header")

    if _has_sparse_header(processed):
        header = processed[0]
        next_row = processed[1]
        processed = [[_combine_cells(header[index], next_row[index]) for index in range(len(header))]] + processed[2:]
        notes.append("sparse_header")

    return (_normalize_grid(processed), notes)


def _repair_reasons(
    candidate: dict[str, Any],
    *,
    page_number: int | None,
    suspect_pages: set[int],
    grid: list[list[str]],
) -> list[str]:
    reasons: list[str] = []

    if candidate.get("had_irregular_rows"):
        reasons.append("irregular_row_widths")
    if any("\n" in cell for row in grid[:2] for cell in row):
        reasons.append("multiline_header")
    if _has_sparse_header(grid):
        reasons.append("sparse_header")
    if candidate.get("best_caption_id") and not _has_meaningful_grid(grid):
        reasons.append("caption_linked_but_grid_weak")
    if candidate.get("plausible_ruled_bbox") and not _has_meaningful_grid(grid):
        reasons.append("ruled_bbox_without_grid")
    if isinstance(page_number, int) and page_number in suspect_pages:
        reasons.append("page_audit_suspect")

    return list(dict.fromkeys(reasons))


def _table_num(caption_text: str | None, page_number: int, fallback_index: int, seen: set[str]) -> str:
    match = TABLE_LABEL_PATTERN.match(caption_text or "")
    if match:
        base = f"Table {match.group(1).upper()}"
    else:
        base = f"Table {fallback_index}"
    if base not in seen:
        seen.add(base)
        return base
    suffix = 2
    while f"{base} [{suffix}]" in seen:
        suffix += 1
    value = f"{base} [{suffix}]"
    seen.add(value)
    return value


def _grid_to_csv(grid: list[list[str]]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    for row in grid:
        writer.writerow(row)
    return output.getvalue()


def _grid_to_html(grid: list[list[str]]) -> str:
    if not grid:
        return "<table></table>\n"
    rows: list[str] = ["<table>"]
    header = grid[0]
    rows.append("  <thead>")
    rows.append("    <tr>" + "".join(f"<th>{cell}</th>" for cell in header) + "</tr>")
    rows.append("  </thead>")
    rows.append("  <tbody>")
    for row in grid[1:]:
        rows.append("    <tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    rows.append("  </tbody>")
    rows.append("</table>")
    return "\n".join(rows) + "\n"


def _grid_to_markdown(grid: list[list[str]]) -> str:
    if not grid:
        return ""
    header = grid[0]
    separator = ["---"] * len(header)
    body = grid[1:] or [[""] * len(header)]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


async def _repair_with_vlm(candidate: dict[str, Any], manifest: dict[str, Any], paper_dir: Path) -> tuple[list[list[str]], str, float]:
    if not os.environ.get("GEMINI_API_KEY"):
        return (_normalize_grid(candidate.get("text_grid")), "heuristic", 0.0)

    page = next(
        (page for page in manifest.get("pages", []) if page.get("page_number") == candidate.get("page_number")),
        None,
    )
    if page is None or not page.get("raster_path"):
        return (_normalize_grid(candidate.get("text_grid")), "heuristic", 0.0)

    prompt = {
        "task": "Repair a scientific table grid only when headers are merged, borderless, or multiline. Preserve rows and columns.",
        "bbox": candidate.get("bbox"),
        "existing_grid": candidate.get("text_grid"),
        "response_format": {"rows": [["cell"]], "confidence": "0.0-1.0"},
    }
    try:
        result = await _call_gemini(
            json.dumps(prompt, ensure_ascii=False),
            model=MODEL_RESOLVER,
            thinking_level="minimal",
            image_paths=[str((paper_dir / page["raster_path"]).resolve())],
        )
        payload = json.loads(_clean_llm_json(result["text"]))
        return (_normalize_grid(payload.get("rows")), result["model"], float(payload.get("confidence") or 0.0))
    except Exception:
        return (_normalize_grid(candidate.get("text_grid")), "heuristic", 0.0)


async def resolve_table_candidates(
    manifest: dict[str, Any],
    *,
    paper_dir: Path,
    resolver_version: str,
    page_numbers: set[int] | None = None,
) -> dict[str, Any]:
    captions_by_id = {
        caption["id"]: caption
        for caption in manifest.get("captions", [])
        if isinstance(caption.get("id"), str)
    }
    tables_dir = paper_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    seen_nums: set[str] = set()
    resolved: list[dict[str, Any]] = []
    low_confidence_pages: set[int] = set()
    fallback_index = 1
    suspect_pages = {
        int(page)
        for page in (manifest.get("audit", {}) or {}).get("suspect_pages", [])
        if isinstance(page, int)
    }

    for candidate in sorted(
        [
            item
            for item in manifest.get("table_candidates", [])
            if not page_numbers or item.get("page_number") in page_numbers
        ],
        key=lambda item: (item.get("page_number", 9999), (item.get("bbox") or [0, 0, 0, 0])[1], (item.get("bbox") or [0, 0, 0, 0])[0]),
    ):
        page_number = candidate.get("page_number")
        grid, preprocessing_notes = _preprocess_grid(_normalize_grid(candidate.get("text_grid")))
        parse_method = candidate.get("source_kind") or "hybrid"
        confidence = 0.6 if _has_meaningful_grid(grid) else 0.38
        classifier_model = "heuristic"
        plausible_ruled_bbox = bool(candidate.get("plausible_ruled_bbox"))
        repair_attempted = False
        repair_reason: str | None = None
        repair_confidence: float | None = None

        if parse_method == "hybrid":
            confidence += 0.18
        elif parse_method == "odl":
            confidence += 0.08
        elif parse_method == "pdfplumber":
            confidence += 0.15
        elif parse_method == "raster_ruled_table":
            confidence += 0.04

        unresolved_reasons = _repair_reasons(
            candidate,
            page_number=page_number,
            suspect_pages=suspect_pages,
            grid=grid,
        )

        needs_vlm_repair = bool(unresolved_reasons) and (
            plausible_ruled_bbox
            or bool(candidate.get("best_caption_id"))
            or (isinstance(page_number, int) and page_number in suspect_pages)
        )

        if not _has_meaningful_grid(grid) and not needs_vlm_repair:
            if isinstance(page_number, int):
                low_confidence_pages.add(page_number)
            continue

        if needs_vlm_repair:
            repair_attempted = True
            repair_reason = " | ".join(dict.fromkeys(preprocessing_notes + unresolved_reasons)) or None
            repaired_grid, model_used, repair_confidence_value = await _repair_with_vlm(candidate, manifest, paper_dir)
            repair_confidence = repair_confidence_value
            if _has_meaningful_grid(repaired_grid):
                grid = repaired_grid
                parse_method = "vlm_repaired"
                classifier_model = model_used
                confidence = max(confidence, 0.72 + min(repair_confidence_value, 0.18))

        unresolved_reasons = _repair_reasons(
            candidate,
            page_number=page_number,
            suspect_pages=suspect_pages,
            grid=grid,
        )

        if not _has_meaningful_grid(grid):
            if isinstance(page_number, int):
                low_confidence_pages.add(page_number)
            continue

        if not unresolved_reasons:
            if repair_attempted:
                confidence = max(confidence, 0.85 + min(repair_confidence or 0.0, 0.1))
            elif preprocessing_notes:
                confidence = max(confidence, 0.87)
            else:
                confidence = max(confidence, 0.88)

        caption = captions_by_id.get(candidate.get("best_caption_id") or "", {})
        caption_text = caption.get("text")
        table_num = _table_num(caption_text, page_number, fallback_index, seen_nums)
        fallback_index += 1

        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", table_num).strip("_") or f"table_{fallback_index}"
        csv_path = tables_dir / f"{safe_name}.csv"
        html_path = tables_dir / f"{safe_name}.html"
        md_path = tables_dir / f"{safe_name}.md"

        csv_text = _grid_to_csv(grid)
        html_text = _grid_to_html(grid)
        markdown_text = _grid_to_markdown(grid)
        csv_path.write_text(csv_text, encoding="utf-8")
        html_path.write_text(html_text, encoding="utf-8")
        md_path.write_text(markdown_text, encoding="utf-8")

        review_required = confidence < 0.85 or bool(unresolved_reasons)
        if review_required and isinstance(page_number, int):
            low_confidence_pages.add(page_number)

        resolved.append(
            {
                "table_num": table_num,
                "page_number": page_number,
                "bbox": candidate.get("bbox"),
                "caption": caption_text,
                "csv_path": str(csv_path.resolve().relative_to(paper_dir.resolve())),
                "html_path": str(html_path.resolve().relative_to(paper_dir.resolve())),
                "markdown_text": markdown_text,
                "confidence": min(confidence, 0.99),
                "parse_method": parse_method if parse_method in {"odl", "pdfplumber", "hybrid", "vlm_repaired"} else "hybrid",
                "classifier_model": classifier_model,
                "resolver_version": resolver_version,
                "extraction_status": "resolved" if not review_required else "uncertain",
                "repair_attempted": repair_attempted,
                "repair_reason": repair_reason,
                "repair_confidence": repair_confidence,
                "review_required": review_required,
            }
        )

    return {
        "tables": resolved,
        "low_confidence_pages": sorted(low_confidence_pages),
    }
