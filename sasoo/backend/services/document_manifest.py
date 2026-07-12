"""
Resolver v1 document-manifest builder.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import fitz

FIGURE_LABEL_PATTERN = re.compile(r"^\s*(?:Figure|Fig\.?)\s*(\d+[A-Za-z]?)\b", re.IGNORECASE)
TABLE_LABEL_PATTERN = re.compile(r"^\s*(?:Table|Tbl\.?)\s*(\d+[A-Za-z]?)\b", re.IGNORECASE)
DOI_PATTERN = re.compile(r"10\.\d{4,}/[^\s]+")
YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
PAGE_MARKER_PATTERN = re.compile(r"^\s*---\s*Page\s+\d+\s*---\s*$", re.IGNORECASE)
ARXIV_BANNER_PATTERN = re.compile(r"\barxiv:\s*\S+", re.IGNORECASE)
DATE_LINE_PATTERN = re.compile(
    r"^\s*(?:\d{1,2}\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s,.-]+\d{4}\s*$|^\s*\d{4}-\d{2}-\d{2}\s*$",
    re.IGNORECASE,
)
CATEGORY_TAG_PATTERN = re.compile(r"^\s*(?:[A-Za-z-]+\.){1,}[A-Za-z-]+\s*$")
PAGE_NUMBER_PATTERN = re.compile(r"^\s*\d+\s*$")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
ABSTRACT_HEADING_PATTERN = re.compile(r"^\s*abstract\b", re.IGNORECASE)
REFERENCE_HEADING_PATTERN = re.compile(r"^\s*(?:references|bibliography)\b", re.IGNORECASE)
DOI_PREFIX_PATTERN = re.compile(r"\bdoi\s*[:/]\s*", re.IGNORECASE)
AFFILIATION_PATTERN = re.compile(
    r"\b(?:university|institute|department|school|laboratory|college|centre|center|faculty)\b",
    re.IGNORECASE,
)
JOURNAL_PATTERNS = [
    r"(?:Published in|Journal of|Proceedings of)\s+(.+?)[\.\n]",
    r"(?:Nature|Science|ACS|IEEE|Optics|Applied|Physical Review)\s*\w*",
]
IMAGE_ELEMENT_TYPES = {"image", "picture"}
TEXTUAL_TYPES = {"caption", "paragraph", "list item", "text block", "heading"}
PAGE_RASTER_DIRNAME = ".page_rasters"


@dataclass(slots=True)
class FlatElement:
    order: int
    element: dict[str, Any]


def _pdf_hash(pdf_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(pdf_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def get_pdf_signature(pdf_path: Path) -> dict[str, int]:
    stat = pdf_path.stat()
    return {
        "pdf_mtime_ns": stat.st_mtime_ns,
        "pdf_size": stat.st_size,
    }


def _maybe_text(text: Any) -> str:
    return text.strip() if isinstance(text, str) else ""


def _maybe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _element_page(element: dict[str, Any], default: int = 1) -> int:
    return _maybe_int(element.get("page")) or _maybe_int(element.get("page number")) or default


def _element_bbox(element: dict[str, Any]) -> list[float] | None:
    bbox = element.get("bbox")
    if bbox is None:
        bbox = element.get("bounding box")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        return [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None


def _element_id(element: dict[str, Any]) -> int | None:
    return _maybe_int(element.get("id"))


def _linked_content_id(element: dict[str, Any]) -> int | None:
    return _maybe_int(element.get("linked_content_id")) or _maybe_int(element.get("linked content id"))


def _flatten_elements(elements: Iterable[dict[str, Any]], counter: list[int], out: list[FlatElement]) -> None:
    for element in elements:
        if not isinstance(element, dict):
            continue
        out.append(FlatElement(order=counter[0], element=element))
        counter[0] += 1

        kids = element.get("kids")
        if isinstance(kids, list):
            _flatten_elements(kids, counter, out)

        list_items = element.get("list items")
        if isinstance(list_items, list):
            _flatten_elements(list_items, counter, out)

        rows = element.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                cells = row.get("cells")
                if isinstance(cells, list):
                    _flatten_elements(cells, counter, out)


def _extract_table_text(table: dict[str, Any]) -> str:
    rows = table.get("rows", [])
    rendered_rows: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rendered_cells: list[str] = []
        for cell in row.get("cells", []):
            if not isinstance(cell, dict):
                continue
            rendered_cells.append(_extract_plain_text_from_element(cell))
        if rendered_cells:
            rendered_rows.append("\t".join(cell for cell in rendered_cells if cell))
    return "\n".join(rendered_rows).strip()


def _extract_plain_text_from_element(element: dict[str, Any]) -> str:
    parts: list[str] = []
    content = _maybe_text(element.get("content"))
    if content:
        parts.append(content)

    if element.get("type") == "table":
        table_text = _extract_table_text(element)
        if table_text:
            parts.append(table_text)

    for key in ("kids", "list items"):
        children = element.get(key, [])
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            child_text = _extract_plain_text_from_element(child)
            if child_text:
                parts.append(child_text)

    return "\n".join(part for part in parts if part).strip()


def _flatten_text_for_metadata(element: dict[str, Any]) -> str:
    return _normalize_text(_extract_plain_text_from_element(element))


def _looks_like_author_line(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized or len(normalized) > 180:
        return False
    if EMAIL_PATTERN.search(normalized):
        return True
    if AFFILIATION_PATTERN.search(normalized):
        return True
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]+", normalized)
    if len(tokens) < 2:
        return False
    separators = normalized.count(",") + normalized.lower().count(" and ")
    capitalized = sum(1 for token in tokens if token[0].isupper())
    return separators >= 1 and capitalized >= max(2, len(tokens) // 2)


def _is_title_noise(text: str) -> bool:
    normalized = _normalize_text(text)
    lowered = normalized.lower()
    if not normalized:
        return True
    if PAGE_MARKER_PATTERN.match(normalized):
        return True
    if ARXIV_BANNER_PATTERN.search(normalized):
        return True
    if DATE_LINE_PATTERN.match(normalized):
        return True
    if CATEGORY_TAG_PATTERN.match(normalized):
        return True
    if PAGE_NUMBER_PATTERN.match(normalized):
        return True
    if EMAIL_PATTERN.search(normalized):
        return True
    if lowered.startswith("submitted on ") or lowered.startswith("version "):
        return True
    if _looks_like_author_line(normalized):
        return True
    return False


def _metadata_blocks(flat_elements: list[FlatElement]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for flat in flat_elements:
        element = flat.element
        text = _flatten_text_for_metadata(element)
        if not text:
            continue
        blocks.append(
            {
                "page_number": _element_page(element, 1),
                "bbox": _element_bbox(element),
                "text": text,
                "type": _maybe_text(element.get("type")).lower() or "text",
                "order": flat.order,
            }
        )
    return blocks


def _title_score(block: dict[str, Any], *, page_width: float, page_height: float) -> float:
    text = block["text"]
    bbox = block.get("bbox")
    block_type = block.get("type") or "text"
    score = 0.0

    if block_type == "heading":
        score += 5.0
    elif block_type in {"paragraph", "text block"}:
        score += 1.4
    elif block_type == "caption":
        score -= 3.0

    if 18 <= len(text) <= 220:
        score += 2.2
    elif len(text) < 10 or len(text) > 260:
        score -= 2.5

    if bbox and page_width and page_height:
        width = max(0.0, bbox[2] - bbox[0])
        width_ratio = width / page_width if page_width else 0.0
        top_ratio = bbox[3] / page_height if page_height else 0.0
        score += min(width_ratio, 0.95) * 3.2
        score += max(0.0, min(top_ratio, 0.9)) * 4.2
        if bbox[1] <= page_height * 0.08:
            score -= 1.4
    score += max(0.0, 1.6 - (block.get("order", 999) * 0.08))
    if re.search(r"[A-Za-z]{4,}", text):
        score += 0.6
    if text.isupper():
        score -= 0.8
    if DOI_PATTERN.search(text):
        score -= 2.0
    return score


def _choose_title_block(root_title: str, blocks: list[dict[str, Any]], page_sizes: dict[int, tuple[float, float]]) -> dict[str, Any] | None:
    normalized_root = _normalize_text(root_title)
    if normalized_root and not _is_title_noise(normalized_root):
        return {
            "page_number": 1,
            "bbox": None,
            "text": normalized_root,
            "type": "root_title",
            "order": -1,
        }

    page_width, page_height = page_sizes.get(1, (0.0, 0.0))
    first_page_blocks = [block for block in blocks if block["page_number"] == 1 and not _is_title_noise(block["text"])]
    if not first_page_blocks:
        return None

    ranked = sorted(
        first_page_blocks,
        key=lambda block: (
            _title_score(block, page_width=page_width, page_height=page_height),
            -block.get("order", 999),
        ),
        reverse=True,
    )
    return ranked[0]


def _clean_author_text(text: str) -> str:
    cleaned = EMAIL_PATTERN.sub("", text)
    cleaned = re.sub(r"[\*\d†‡§¶]+", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" ,;")


def _extract_authors_from_blocks(root_author: str, title_block: dict[str, Any] | None, blocks: list[dict[str, Any]], page_sizes: dict[int, tuple[float, float]]) -> str | None:
    normalized_root = _clean_author_text(_normalize_text(root_author))
    if normalized_root:
        return normalized_root
    if title_block is None:
        return None

    page_width, page_height = page_sizes.get(1, (0.0, 0.0))
    title_bbox = title_block.get("bbox")
    title_bottom = title_bbox[1] if title_bbox else page_height * 0.64
    title_left = title_bbox[0] if title_bbox else 0.0
    title_right = title_bbox[2] if title_bbox else page_width

    author_lines: list[str] = []
    for block in sorted(
        [block for block in blocks if block["page_number"] == 1 and block.get("order", 999) > title_block.get("order", -1)],
        key=lambda block: block.get("order", 999),
    ):
        text = block["text"]
        if ABSTRACT_HEADING_PATTERN.match(text) or REFERENCE_HEADING_PATTERN.match(text):
            break
        if len(text) > 220:
            break
        bbox = block.get("bbox")
        if bbox:
            if bbox[1] < title_bottom - page_height * 0.18:
                break
            horizontal_overlap = min(title_right, bbox[2]) - max(title_left, bbox[0])
            title_width = max(1.0, title_right - title_left)
            if horizontal_overlap / title_width < 0.35 and abs(((bbox[0] + bbox[2]) / 2) - ((title_left + title_right) / 2)) > page_width * 0.18:
                continue
        cleaned = _clean_author_text(text)
        if not cleaned or AFFILIATION_PATTERN.search(cleaned):
            continue
        if len(cleaned.split()) > 24:
            break
        author_lines.append(cleaned)
        if len(author_lines) >= 2:
            break

    if not author_lines:
        return None

    combined = _normalize_text(" ".join(author_lines))
    combined = re.sub(r"\s*,\s*,+", ", ", combined)
    return combined or None


def _extract_front_matter_doi(blocks: list[dict[str, Any]], title_block: dict[str, Any] | None) -> str | None:
    candidates: list[tuple[float, str]] = []
    title_order = title_block.get("order", 0) if title_block else 0
    for block in blocks:
        page_number = block["page_number"]
        if page_number > 2:
            continue
        text = block["text"]
        if REFERENCE_HEADING_PATTERN.match(text):
            break
        if len(text) > 600:
            continue
        for match in DOI_PATTERN.finditer(text):
            doi = match.group(0).rstrip(".,;)")
            score = 0.0
            score += 4.0 if page_number == 1 else 2.5
            score += 2.5 if DOI_PREFIX_PATTERN.search(text) else 0.0
            score += max(0.0, 2.0 - abs(block.get("order", title_order) - title_order) * 0.1)
            if ABSTRACT_HEADING_PATTERN.match(text) or "abstract" in text.lower():
                score += 1.4
            if "reference" in text.lower() or "doi.org/" in text.lower() and DOI_PREFIX_PATTERN.search(text) is None:
                score -= 2.0
            candidates.append((score, doi))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_doi = candidates[0]
    return best_doi if best_score >= 2.5 else None


def _build_plain_text(flat_elements: list[FlatElement]) -> str:
    pages: dict[int, list[str]] = {}
    last_page = 1
    for flat in flat_elements:
        page = _element_page(flat.element, last_page)
        last_page = page
        text = _extract_plain_text_from_element(flat.element)
        if not text:
            continue
        pages.setdefault(page, []).append(text)

    parts: list[str] = []
    for page in sorted(pages):
        parts.append(f"--- Page {page} ---")
        parts.append("\n".join(pages[page]))
    return "\n\n".join(parts).strip()


def _extract_metadata(
    root: dict[str, Any],
    flat_elements: list[FlatElement],
    full_text: str,
    pdf_path: Path,
    page_sizes: dict[int, tuple[float, float]],
) -> dict[str, Any]:
    blocks = _metadata_blocks(flat_elements)
    title_block = _choose_title_block(_maybe_text(root.get("title")), blocks, page_sizes)
    title = title_block["text"] if title_block else ""
    author = _extract_authors_from_blocks(_maybe_text(root.get("author")), title_block, blocks, page_sizes)
    creation_date = _maybe_text(root.get("creation_date")) or _maybe_text(root.get("creation date"))

    if not title:
        for line in full_text.splitlines():
            cleaned = _normalize_text(line)
            if len(cleaned) > 10 and not _is_title_noise(cleaned):
                title = cleaned
                break
    if not title:
        title = pdf_path.stem

    year = None
    if creation_date:
        creation_match = YEAR_PATTERN.search(creation_date)
        if creation_match:
            year = int(creation_match.group(1))
    if year is None:
        matches = [int(match) for match in YEAR_PATTERN.findall(full_text[:3000])]
        valid = [item for item in matches if 1900 <= item <= 2100]
        if valid:
            year = max(valid)

    doi = _extract_front_matter_doi(blocks, title_block)

    journal = None
    for pattern in JOURNAL_PATTERNS:
        match = re.search(pattern, full_text[:2000], re.IGNORECASE)
        if match:
            journal = match.group(0).strip()[:100]
            break

    return {
        "title": title[:200],
        "authors": author,
        "year": year,
        "journal": journal,
        "doi": doi,
        "page_count": _maybe_int(root.get("num_pages")) or _maybe_int(root.get("number of pages")) or 0,
    }


def _extract_page_sizes(pdf_path: Path) -> dict[int, tuple[float, float]]:
    doc = fitz.open(str(pdf_path))
    try:
        return {
            page_index + 1: (doc[page_index].rect.width, doc[page_index].rect.height)
            for page_index in range(len(doc))
        }
    finally:
        doc.close()


def _relative_to_paper(paper_dir: Path, path: Path) -> str:
    return str(path.resolve().relative_to(paper_dir.resolve()))


def _ensure_page_rasters(pdf_path: Path, paper_dir: Path, page_count: int) -> dict[int, str]:
    raster_dir = paper_dir / PAGE_RASTER_DIRNAME
    raster_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    try:
        result: dict[int, str] = {}
        for page_number in range(1, page_count + 1):
            target = raster_dir / f"page_{page_number}.png"
            if not target.exists():
                page = doc[page_number - 1]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
                pix.save(str(target))
            result[page_number] = _relative_to_paper(paper_dir, target)
        return result
    finally:
        doc.close()


def _caption_kind(text: str) -> str | None:
    if FIGURE_LABEL_PATTERN.match(text):
        return "figure"
    if TABLE_LABEL_PATTERN.match(text):
        return "table"
    return None


def _table_rows_from_element(element: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in element.get("rows", []):
        if not isinstance(row, dict):
            continue
        cells: list[str] = []
        for cell in row.get("cells", []):
            if not isinstance(cell, dict):
                continue
            cells.append(_extract_plain_text_from_element(cell))
        if cells:
            rows.append(cells)
    return rows


def build_document_manifest(
    *,
    pdf_path: Path,
    paper_dir: Path,
    root: dict[str, Any],
    markdown_text: str,
    actual_engine: str,
    requested_mode: str,
    extraction_pipeline_version: str,
    parser_version: str,
    resolver_version: str,
    generate_page_rasters: bool = True,
) -> dict[str, Any]:
    flat_elements: list[FlatElement] = []
    _flatten_elements(root.get("kids", []), [0], flat_elements)

    if actual_engine == "gemini":
        # gemini(gemini_parser.GEMINI_ENGINE_NAME) 엔진은 markdown_text가 완전한 본문
        # (reading order / GFM 테이블 / LaTeX 수식 / "--- Page N ---" 마커)을 담는다.
        # slim 스키마에선 트리에 본문 paragraph가 없으므로 markdown을 full_text 원천으로
        # 삼아 본문 유실을 막는다(트리 조립본보다 품질 우위). ODL 경로는 아래 기존 로직 불변.
        full_text = markdown_text or _build_plain_text(flat_elements)
    else:
        full_text = _build_plain_text(flat_elements) or markdown_text
    page_sizes = _extract_page_sizes(pdf_path)
    metadata = _extract_metadata(root, flat_elements, full_text, pdf_path, page_sizes)
    page_count = metadata.get("page_count") or len(page_sizes)
    raster_paths = _ensure_page_rasters(pdf_path, paper_dir, page_count) if generate_page_rasters else {}

    pages: dict[int, dict[str, Any]] = {}
    for page_number in range(1, page_count + 1):
        width, height = page_sizes.get(page_number, (0.0, 0.0))
        pages[page_number] = {
            "page_number": page_number,
            "page_size": {"width": width, "height": height},
            "raster_path": raster_paths.get(page_number),
            "source_parsers": [actual_engine],
            "text_blocks": [],
            "image_blocks": [],
            "caption_blocks": [],
            "odl_table_nodes": [],
        }

    caption_counts: dict[int, int] = {}
    text_counts: dict[int, int] = {}
    image_counts: dict[int, int] = {}
    table_counts: dict[int, int] = {}
    captions: list[dict[str, Any]] = []

    for flat in flat_elements:
        element = flat.element
        page_number = _element_page(element, 1)
        page_entry = pages.setdefault(
            page_number,
            {
                "page_number": page_number,
                "page_size": {"width": 0.0, "height": 0.0},
                "raster_path": raster_paths.get(page_number),
                "source_parsers": [actual_engine],
                "text_blocks": [],
                "image_blocks": [],
                "caption_blocks": [],
                "odl_table_nodes": [],
            },
        )

        element_type = _maybe_text(element.get("type")).lower()
        bbox = _element_bbox(element)
        text = _extract_plain_text_from_element(element)
        linked_content = _linked_content_id(element)
        source_id = _element_id(element)

        if element_type in IMAGE_ELEMENT_TYPES:
            idx = image_counts.get(page_number, 0)
            image_counts[page_number] = idx + 1
            page_entry["image_blocks"].append(
                {
                    "id": f"img:p{page_number}:n{idx}",
                    "page_number": page_number,
                    "bbox": bbox,
                    "source": _maybe_text(element.get("source")) or None,
                    "source_id": source_id,
                    "order": flat.order,
                }
            )
            continue

        caption_kind = _caption_kind(text)
        if element_type == "caption" or caption_kind:
            idx = caption_counts.get(page_number, 0)
            caption_counts[page_number] = idx + 1
            caption_id = f"cap:p{page_number}:n{idx}"
            caption_block = {
                "id": caption_id,
                "page_number": page_number,
                "bbox": bbox,
                "text": text,
                "kind": caption_kind or "unknown",
                "linked_content_id": linked_content,
                "source_id": source_id,
                "order": flat.order,
            }
            page_entry["caption_blocks"].append(caption_block)
            captions.append(caption_block)
            continue

        if element_type == "table":
            idx = table_counts.get(page_number, 0)
            table_counts[page_number] = idx + 1
            page_entry["odl_table_nodes"].append(
                {
                    "id": f"odltbl:p{page_number}:n{idx}",
                    "page_number": page_number,
                    "bbox": bbox,
                    "text": _extract_table_text(element),
                    "rows": _table_rows_from_element(element),
                    "source_id": source_id,
                    "order": flat.order,
                }
            )
            continue

        if element_type in TEXTUAL_TYPES and text:
            idx = text_counts.get(page_number, 0)
            text_counts[page_number] = idx + 1
            page_entry["text_blocks"].append(
                {
                    "id": f"txt:p{page_number}:n{idx}",
                    "page_number": page_number,
                    "bbox": bbox,
                    "text": text,
                    "type": element_type or "text",
                    "source_id": source_id,
                    "order": flat.order,
                }
            )

    pdf_signature = get_pdf_signature(pdf_path)
    return {
        "parser_version": parser_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_mode": requested_mode,
        "extraction_pipeline_version": extraction_pipeline_version,
        "resolver_version": resolver_version,
        "engine": actual_engine,
        "pdf_hash": _pdf_hash(pdf_path),
        "pdf_mtime_ns": pdf_signature["pdf_mtime_ns"],
        "pdf_size": pdf_signature["pdf_size"],
        "pdf_file": pdf_path.name,
        "markdown_file": f"{pdf_path.stem}.md",
        "json_file": f"{pdf_path.stem}.json",
        "metadata": metadata,
        "full_text": full_text,
        "pages": [pages[page_number] for page_number in sorted(pages)],
        "captions": captions,
        "figure_candidates": [],
        "table_candidates": [],
        "figures": [],
        "tables": [],
        "visual_artifacts_ready": False,
        "audit": {
            "triggered": False,
            "reason": None,
            "suspect_pages": [],
        },
    }


def write_manifest(paper_dir: Path, manifest: dict[str, Any], filename: str) -> None:
    (paper_dir / filename).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
