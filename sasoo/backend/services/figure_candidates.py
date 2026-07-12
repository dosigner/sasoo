"""
Figure candidate generation for resolver_v1.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import fitz

AXIS_TEXT_PATTERN = re.compile(
    r"(?:^|[\s(])(?:x|y|z)(?:[\s)\-=:]|$)|[%/]|±|\b(?:nm|um|μm|mm|cm|hz|khz|mhz|ghz|db|ev|mev|ma|mv|ms|s)\b",
    re.IGNORECASE,
)


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
    intersection = (x1 - x0) * (y1 - y0)
    union = _bbox_area(a) + _bbox_area(b) - intersection
    return intersection / union if union else 0.0


def _bbox_union(boxes: list[list[float]]) -> list[float]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _center(box: list[float] | None) -> tuple[float, float]:
    if not box:
        return (0.0, 0.0)
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _distance(a: list[float] | None, b: list[float] | None) -> float:
    ax, ay = _center(a)
    bx, by = _center(b)
    return math.hypot(ax - bx, ay - by)


def _page_size_tuple(page: dict[str, Any]) -> tuple[float, float]:
    size = page.get("page_size") or {}
    return float(size.get("width") or 0.0), float(size.get("height") or 0.0)


def _page_ratio_metrics(bbox: list[float] | None, page: dict[str, Any]) -> tuple[float, float, float]:
    if not bbox:
        return (0.0, 0.0, 0.0)
    page_width, page_height = _page_size_tuple(page)
    width = max(0.0, bbox[2] - bbox[0])
    height = max(0.0, bbox[3] - bbox[1])
    width_ratio = width / page_width if page_width else 0.0
    height_ratio = height / page_height if page_height else 0.0
    area_ratio = _bbox_area(bbox) / (page_width * page_height) if page_width and page_height else 0.0
    return (width_ratio, height_ratio, area_ratio)


def _bbox_dims(bbox: list[float] | None) -> tuple[float, float]:
    if not bbox:
        return (0.0, 0.0)
    return (max(0.0, bbox[2] - bbox[0]), max(0.0, bbox[3] - bbox[1]))


def _is_strip_like(bbox: list[float] | None, page: dict[str, Any]) -> bool:
    width_ratio, height_ratio, _ = _page_ratio_metrics(bbox, page)
    return (width_ratio >= 0.6 and height_ratio <= 0.11) or (height_ratio >= 0.6 and width_ratio <= 0.11)


def _is_tiny_visual(bbox: list[float] | None, page: dict[str, Any]) -> bool:
    width_ratio, height_ratio, area_ratio = _page_ratio_metrics(bbox, page)
    width, height = _bbox_dims(bbox)
    return (
        area_ratio < 0.012
        or width < 42
        or height < 42
        or (width_ratio < 0.12 and height_ratio < 0.12)
        or min(width_ratio, height_ratio) < 0.055
    )


def _is_full_page_composite(bbox: list[float] | None, page: dict[str, Any]) -> bool:
    width_ratio, height_ratio, area_ratio = _page_ratio_metrics(bbox, page)
    return width_ratio >= 0.72 and height_ratio >= 0.68 and area_ratio >= 0.48


def _extract_pymupdf_image_blocks(pdf_path: Path) -> dict[int, list[dict[str, Any]]]:
    doc = fitz.open(str(pdf_path))
    try:
        result: dict[int, list[dict[str, Any]]] = {}
        for page_index, page in enumerate(doc, start=1):
            page_height = float(page.rect.height)
            blocks = page.get_text("dict").get("blocks", [])
            entries: list[dict[str, Any]] = []
            for index, block in enumerate(blocks):
                if block.get("type") != 1:
                    continue
                bbox = block.get("bbox")
                if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    continue
                x0, y0, x1, y1 = [float(value) for value in bbox]
                entries.append(
                    {
                        "id": f"pymupdf:p{page_index}:n{index}",
                        "bbox": [x0, page_height - y1, x1, page_height - y0],
                        "source_kind": "pymupdf_image",
                    }
                )
            result[page_index] = entries
        return result
    finally:
        doc.close()


def _caption_candidates_for_page(
    page: dict[str, Any],
    *,
    caption_kind: str,
) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, int], dict[str, Any]] = {}
    for caption in page.get("caption_blocks", []):
        if caption.get("kind") != caption_kind:
            continue
        text = re.sub(r"\s+", " ", str(caption.get("text") or "")).strip().lower()
        key = (text, int(caption.get("page_number") or 0))
        existing = deduped.get(key)
        if existing is None or _bbox_area(caption.get("bbox")) > _bbox_area(existing.get("bbox")):
            deduped[key] = caption
    return list(deduped.values())


def _best_linked_caption(candidate_bbox: list[float], captions: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    if not captions:
        return (None, [])
    scored = sorted(
        captions,
        key=lambda caption: (
            0 if caption.get("linked_content_id") is not None else 1,
            _distance(candidate_bbox, caption.get("bbox")),
            abs((caption.get("order") or 0)),
        ),
    )
    return (scored[0]["id"], [caption["id"] for caption in scored[:3]])


def _fallback_bbox_from_caption(page: dict[str, Any], caption: dict[str, Any], *, aggressive: bool) -> list[float] | None:
    bbox = caption.get("bbox")
    if not bbox:
        return None
    page_width, page_height = _page_size_tuple(page)
    if not page_width or not page_height:
        return None
    caption_mid_y = (bbox[1] + bbox[3]) / 2
    if caption_mid_y > page_height * 0.6:
        top = page_height * (0.04 if aggressive else 0.08)
        bottom = max(top + page_height * 0.22, bbox[1] - page_height * 0.03)
    else:
        top = min(page_height * 0.96, bbox[3] + page_height * 0.03)
        bottom = page_height * (0.98 if aggressive else 0.9)
    if bottom <= top:
        return None
    side_margin = page_width * (0.03 if aggressive else 0.08)
    return [side_margin, top, page_width - side_margin, bottom]


def _horizontal_overlap_ratio(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    if overlap <= 0:
        return 0.0
    base = max(1.0, min(a[2] - a[0], b[2] - b[0]))
    return overlap / base


def _looks_chart_like_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized or len(normalized) > 90:
        return False
    if normalized.lower().startswith(("figure ", "fig.", "fig ")):
        return False
    if AXIS_TEXT_PATTERN.search(normalized):
        return True
    token_count = len(normalized.split())
    digit_count = sum(char.isdigit() for char in normalized)
    return digit_count >= 2 and token_count <= 8


def _caption_band_candidates(
    page: dict[str, Any],
    caption: dict[str, Any],
    visual_blocks: list[dict[str, Any]],
    *,
    aggressive: bool,
) -> list[dict[str, Any]]:
    caption_bbox = caption.get("bbox")
    if not caption_bbox:
        return []

    page_width, page_height = _page_size_tuple(page)
    if not page_width or not page_height:
        return []

    x_margin = page_width * (0.08 if aggressive else 0.04)
    min_x = max(0.0, caption_bbox[0] - x_margin)
    max_x = min(page_width, caption_bbox[2] + x_margin)
    vertical_min = caption_bbox[3] - page_height * 0.015
    vertical_max = min(page_height * 0.98, caption_bbox[3] + page_height * (0.72 if aggressive else 0.52))

    image_matches = [
        block
        for block in visual_blocks
        if block.get("bbox")
        and block["bbox"][1] >= vertical_min
        and block["bbox"][3] <= vertical_max
        and (_horizontal_overlap_ratio(block["bbox"], [min_x, caption_bbox[1], max_x, caption_bbox[3]]) >= 0.28 or abs(_center(block["bbox"])[0] - ((caption_bbox[0] + caption_bbox[2]) / 2)) <= page_width * 0.18)
        and not _is_tiny_visual(block["bbox"], page)
    ]
    # 코드리뷰 F4(부분 미수정, 영향 경미): gemini slim 스키마에선 page['text_blocks']에 본문이
    # 없어(heading/caption만) 이 chart-like 텍스트 매칭이 항상 비게 되고, 아래 caption_band_union_text
    # 확장(축 라벨을 포함하도록 크롭 bbox를 넓히는 변형)만 사라진다. 기본 image 후보(caption_band_union)
    # 는 image_blocks에서 그대로 나오므로 figure 후보 자체는 유실되지 않는다(파일럿에서 후보 수 정상).
    # 완전 해소하려면 gemini 본문을 per-page text_blocks로 채워야 하는데, 이는 매니페스트 비대화 +
    # 다수 하류 소비자 변경을 수반해 비용 대비 이득이 불명확하다 — 의도적으로 보류(보고서에 기재).
    text_matches = [
        block
        for block in page.get("text_blocks", [])
        if block.get("bbox")
        and block["bbox"][1] >= vertical_min
        and block["bbox"][3] <= vertical_max
        and _horizontal_overlap_ratio(block["bbox"], [min_x, caption_bbox[1], max_x, caption_bbox[3]]) >= 0.2
        and _looks_chart_like_text(str(block.get("text") or ""))
    ]

    image_groups = _merge_adjacent_images(page, image_matches) if len(image_matches) > 1 else []
    if not image_groups:
        image_groups = [[block] for block in sorted(image_matches, key=lambda entry: (_distance(entry["bbox"], caption_bbox), -_bbox_area(entry["bbox"])))]

    band_candidates: list[dict[str, Any]] = []
    for group in image_groups[:2]:
        group_boxes = [block["bbox"] for block in group if block.get("bbox")]
        if not group_boxes:
            continue
        base_bbox = _bbox_union(group_boxes)
        related_text = [
            block["bbox"]
            for block in text_matches
            if block.get("bbox") and _horizontal_overlap_ratio(block["bbox"], base_bbox) >= 0.2
        ]
        band_candidates.append(
            {
                "bbox": base_bbox,
                "source_kind": "caption_band_union",
                "source_block_ids": [block.get("id") for block in group if block.get("id")],
                "weak_image_evidence": len(group) == 1,
                "ambiguity_reasons": ["competing_candidate_crops"] if len(image_groups) > 1 else [],
            }
        )
        if related_text:
            expanded_bbox = _bbox_union(group_boxes + related_text)
            if _bbox_area(expanded_bbox) > _bbox_area(base_bbox) * 1.08:
                band_candidates.append(
                    {
                        "bbox": expanded_bbox,
                        "source_kind": "caption_band_union_text",
                        "source_block_ids": [block.get("id") for block in group if block.get("id")],
                        "weak_image_evidence": False,
                        "ambiguity_reasons": ["competing_candidate_crops"] if len(image_groups) > 1 else [],
                    }
                )

    if not band_candidates and text_matches:
        text_bbox = _bbox_union([block["bbox"] for block in text_matches if block.get("bbox")])
        band_candidates.append(
            {
                "bbox": text_bbox,
                "source_kind": "caption_chart_text",
                "source_block_ids": [block.get("id") for block in text_matches if block.get("id")],
                "weak_image_evidence": True,
                "ambiguity_reasons": ["weak_image_evidence"],
            }
        )

    return band_candidates[:3]


def _candidate_signature(page_number: int, bbox: list[float] | None) -> tuple[int, int, int, int, int] | None:
    if not bbox:
        return None
    return (
        page_number,
        round(bbox[0]),
        round(bbox[1]),
        round(bbox[2]),
        round(bbox[3]),
    )


def _append_candidate(
    out: list[dict[str, Any]],
    seen: set[tuple[int, int, int, int, int]],
    *,
    page: dict[str, Any],
    bbox: list[float] | None,
    source_kind: str,
    source_parsers: list[str],
    linked_caption_ids: list[str] | None = None,
    best_caption_id: str | None = None,
    source_block_ids: list[str] | None = None,
    aggressive: bool = False,
    weak_image_evidence: bool = False,
    ambiguity_reasons: list[str] | None = None,
) -> None:
    signature = _candidate_signature(page["page_number"], bbox)
    if bbox is None or signature is None:
        return
    if _is_strip_like(bbox, page) and not aggressive:
        return
    if _is_tiny_visual(bbox, page) and source_kind not in {"caption_band_union", "caption_band_union_text", "caption_chart_text"}:
        return
    if signature in seen:
        return
    seen.add(signature)
    out.append(
        {
            "page_number": page["page_number"],
            "bbox": bbox,
            "source_kind": source_kind,
            "source_parsers": source_parsers,
            "linked_caption_ids": linked_caption_ids or [],
            "best_caption_id": best_caption_id,
            "source_block_ids": source_block_ids or [],
            "is_composite_hint": _is_full_page_composite(bbox, page),
            "weak_image_evidence": weak_image_evidence,
            "ambiguity_reasons": ambiguity_reasons or [],
            "needs_vlm_rerank": weak_image_evidence or bool(ambiguity_reasons),
        }
    )


def _merge_adjacent_images(page: dict[str, Any], visual_blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    page_width, page_height = _page_size_tuple(page)
    groups: list[list[dict[str, Any]]] = []
    max_gap = max(page_width, page_height) * 0.08
    for block in sorted(visual_blocks, key=lambda entry: (entry["bbox"][1], entry["bbox"][0])):
        placed = False
        for group in groups:
            union_bbox = _bbox_union([item["bbox"] for item in group])
            if _distance(block["bbox"], union_bbox) <= max_gap:
                group.append(block)
                placed = True
                break
        if not placed:
            groups.append([block])
    return [group for group in groups if len(group) > 1]


def _prune_caption_duplicates(candidates: list[dict[str, Any]], page: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        caption_id = candidate.get("best_caption_id") or (candidate.get("linked_caption_ids") or [candidate.get("id")])[0]
        grouped.setdefault((candidate["page_number"], str(caption_id)), []).append(candidate)

    pruned: list[dict[str, Any]] = []
    for _, group in grouped.items():
        ordered = sorted(group, key=lambda item: (_bbox_area(item.get("bbox")), 1 if item.get("weak_image_evidence") else 0), reverse=True)
        kept: list[dict[str, Any]] = []
        for candidate in ordered:
            if any(_bbox_iou(candidate.get("bbox"), existing.get("bbox")) >= 0.8 for existing in kept):
                continue
            if kept and _is_tiny_visual(candidate.get("bbox"), page) and not _is_tiny_visual(kept[0].get("bbox"), page):
                continue
            kept.append(candidate)
            if len(kept) >= 3:
                break
        pruned.extend(kept)
    return pruned


def build_figure_candidates(
    manifest: dict[str, Any],
    *,
    pdf_path: Path,
    page_numbers: set[int] | None = None,
    aggressive: bool = False,
) -> list[dict[str, Any]]:
    pymupdf_blocks = _extract_pymupdf_image_blocks(pdf_path)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int, int]] = set()

    for page in manifest.get("pages", []):
        page_number = page.get("page_number")
        if not isinstance(page_number, int):
            continue
        if page_numbers and page_number not in page_numbers:
            continue

        figure_captions = _caption_candidates_for_page(page, caption_kind="figure")
        visual_blocks = list(page.get("image_blocks", [])) + pymupdf_blocks.get(page_number, [])

        linked_by_source_id = {
            block.get("source_id"): block
            for block in page.get("image_blocks", [])
            if block.get("source_id") is not None
        }

        for caption in figure_captions:
            linked = linked_by_source_id.get(caption.get("linked_content_id"))
            if linked:
                best_caption_id, caption_options = _best_linked_caption(linked.get("bbox"), figure_captions)
                _append_candidate(
                    candidates,
                    seen,
                    page=page,
                    bbox=linked.get("bbox"),
                    source_kind="odl_linked_visual",
                    source_parsers=["odl"],
                    linked_caption_ids=caption_options,
                    best_caption_id=best_caption_id or caption.get("id"),
                    source_block_ids=[linked.get("id")] if linked.get("id") else [],
                    aggressive=aggressive,
                )

            for band_candidate in _caption_band_candidates(page, caption, visual_blocks, aggressive=aggressive):
                _append_candidate(
                    candidates,
                    seen,
                    page=page,
                    bbox=band_candidate.get("bbox"),
                    source_kind=str(band_candidate.get("source_kind") or "caption_band_union"),
                    source_parsers=["odl", "pymupdf", "heuristic"],
                    linked_caption_ids=[caption["id"]],
                    best_caption_id=caption["id"],
                    source_block_ids=band_candidate.get("source_block_ids") or [],
                    aggressive=True,
                    weak_image_evidence=bool(band_candidate.get("weak_image_evidence")),
                    ambiguity_reasons=list(band_candidate.get("ambiguity_reasons") or []),
                )

        for block in visual_blocks:
            best_caption_id, caption_options = _best_linked_caption(block.get("bbox"), figure_captions)
            source_kind = block.get("source_kind") or "odl_image"
            _append_candidate(
                candidates,
                seen,
                page=page,
                bbox=block.get("bbox"),
                source_kind=source_kind,
                source_parsers=["pymupdf"] if source_kind == "pymupdf_image" else ["odl"],
                linked_caption_ids=caption_options,
                best_caption_id=best_caption_id,
                source_block_ids=[block.get("id")] if block.get("id") else [],
                aggressive=aggressive,
                weak_image_evidence=_is_tiny_visual(block.get("bbox"), page),
            )

        for group in _merge_adjacent_images(page, [block for block in visual_blocks if block.get("bbox")]):
            bbox = _bbox_union([block["bbox"] for block in group if block.get("bbox")])
            best_caption_id, caption_options = _best_linked_caption(bbox, figure_captions)
            _append_candidate(
                candidates,
                seen,
                page=page,
                bbox=bbox,
                source_kind="merged_image",
                source_parsers=sorted({*(["odl"] if any("odl" in (block.get("source_kind") or "") for block in group) else []), *(["pymupdf"] if any(block.get("source_kind") == "pymupdf_image" for block in group) else [])}),
                linked_caption_ids=caption_options,
                best_caption_id=best_caption_id,
                source_block_ids=[block.get("id") for block in group if block.get("id")],
                aggressive=aggressive,
                ambiguity_reasons=["competing_candidate_crops"] if len(group) > 2 else [],
            )

        full_page_blocks = [block for block in visual_blocks if _is_full_page_composite(block.get("bbox"), page)]
        for block in full_page_blocks:
            best_caption_id, caption_options = _best_linked_caption(block.get("bbox"), figure_captions)
            _append_candidate(
                candidates,
                seen,
                page=page,
                bbox=block.get("bbox"),
                source_kind="full_page_composite",
                source_parsers=["odl"] if block.get("source_kind") != "pymupdf_image" else ["pymupdf"],
                linked_caption_ids=caption_options,
                best_caption_id=best_caption_id,
                source_block_ids=[block.get("id")] if block.get("id") else [],
                aggressive=True,
            )

        for caption in figure_captions:
            if any(caption.get("id") in candidate.get("linked_caption_ids", []) for candidate in candidates if candidate.get("page_number") == page_number):
                continue
            fallback_bbox = _fallback_bbox_from_caption(page, caption, aggressive=aggressive)
            if fallback_bbox is None:
                continue
            _append_candidate(
                candidates,
                seen,
                page=page,
                bbox=fallback_bbox,
                source_kind="caption_fallback_crop",
                source_parsers=["odl", "heuristic"],
                linked_caption_ids=[caption["id"]],
                best_caption_id=caption["id"],
                source_block_ids=[],
                aggressive=True,
                weak_image_evidence=True,
                ambiguity_reasons=["weak_image_evidence"],
            )

            if aggressive:
                page_width, page_height = _page_size_tuple(page)
                extra_bbox = [page_width * 0.02, page_height * 0.02, page_width * 0.98, page_height * 0.98]
                _append_candidate(
                    candidates,
                    seen,
                    page=page,
                    bbox=extra_bbox,
                    source_kind="caption_fallback_crop",
                    source_parsers=["heuristic"],
                    linked_caption_ids=[caption["id"]],
                    best_caption_id=caption["id"],
                    aggressive=True,
                    weak_image_evidence=True,
                    ambiguity_reasons=["weak_image_evidence", "competing_candidate_crops"],
                )

    pages = sorted({candidate["page_number"] for candidate in candidates})
    numbered: list[dict[str, Any]] = []
    for page_number in pages:
        page = next((entry for entry in manifest.get("pages", []) if entry.get("page_number") == page_number), None)
        page_candidates_source = [candidate for candidate in candidates if candidate["page_number"] == page_number]
        page_candidates = _prune_caption_duplicates(page_candidates_source, page) if page else page_candidates_source
        page_candidates = sorted(
            page_candidates,
            key=lambda candidate: (candidate["bbox"][1], candidate["bbox"][0], -_bbox_area(candidate["bbox"])),
        )
        for index, candidate in enumerate(page_candidates):
            numbered.append(
                {
                    **candidate,
                    "id": f"figcand:p{page_number}:n{index}",
                }
            )
    return numbered
