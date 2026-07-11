"""
Figure resolver for resolver_v1.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz
from PIL import Image

from api.analysis_helpers import _call_gemini, _clean_llm_json
from models.paper import Figure as ParsedFigure
from services.subfigure_detector import SubFigureDetector
from services.models import MODEL_RESOLVER

FIGURE_LABEL_PATTERN = re.compile(r"^\s*(?:Figure|Fig\.?)\s*(\d+[A-Za-z]?)\b", re.IGNORECASE)


def _bbox_area(bbox: list[float] | None) -> float:
    if not bbox:
        return 0.0
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


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


def _is_composite_candidate(candidate: dict[str, Any], page: dict[str, Any]) -> bool:
    source_kind = candidate.get("source_kind")
    if source_kind in {"full_page_composite", "merged_image"}:
        return True
    width_ratio, height_ratio, area_ratio = _page_ratio_metrics(candidate.get("bbox"), page)
    return width_ratio >= 0.7 and height_ratio >= 0.65 and area_ratio >= 0.45


def _odl_bbox_to_fitz_rect(page_height: float, bbox: list[float]) -> fitz.Rect:
    left, bottom, right, top = bbox
    return fitz.Rect(left, page_height - top, right, page_height - bottom)


def _crop_candidate(pdf_path: Path, page_number: int, bbox: list[float], output_path: Path) -> tuple[int, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_number - 1]
        clip = _odl_bbox_to_fitz_rect(page.rect.height, bbox)
        pix = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), clip=clip, alpha=False)
        pix.save(str(output_path))
        return (pix.width, pix.height)
    finally:
        doc.close()


def _quality_from_dims(width: int, height: int) -> str:
    if width < 200 or height < 200:
        return "low"
    if width < 400 or height < 400:
        return "medium"
    return "high"


def _normalized_figure_num(
    caption_text: str | None,
    page_number: int,
    fallback_index: int,
    seen: set[str],
) -> str:
    match = FIGURE_LABEL_PATTERN.match(caption_text or "")
    if match:
        base = f"Fig. {match.group(1).upper()}"
    else:
        base = f"p{page_number}_fig{fallback_index}"

    if base not in seen:
        seen.add(base)
        return base

    suffix = 2
    while f"{base} [{suffix}]" in seen:
        suffix += 1
    figure_num = f"{base} [{suffix}]"
    seen.add(figure_num)
    return figure_num


def _status_from_confidence(confidence: float) -> str:
    return "resolved" if confidence >= 0.85 else "uncertain"


def _score_candidate(
    candidate: dict[str, Any],
    page: dict[str, Any],
    captions_by_id: dict[str, dict[str, Any]],
) -> tuple[str, float, str | None, bool, str | None]:
    bbox = candidate.get("bbox")
    confidence = 0.2
    rejection_reason = None
    best_caption_id = candidate.get("best_caption_id")

    if candidate.get("source_kind") == "odl_linked_visual":
        confidence += 0.42
    elif candidate.get("source_kind") == "caption_band_union_text":
        confidence += 0.38
    elif candidate.get("source_kind") == "caption_band_union":
        confidence += 0.34
    elif candidate.get("source_kind") == "merged_image":
        confidence += 0.28
    elif candidate.get("source_kind") == "full_page_composite":
        confidence += 0.32
    elif candidate.get("source_kind") == "pymupdf_image":
        confidence += 0.22
    elif candidate.get("source_kind") == "caption_chart_text":
        confidence += 0.14
    elif candidate.get("source_kind") == "caption_fallback_crop":
        confidence += 0.12
    else:
        confidence += 0.18

    if candidate.get("linked_caption_ids"):
        confidence += 0.16
    if best_caption_id and captions_by_id.get(best_caption_id, {}).get("linked_content_id") is not None:
        confidence += 0.08

    width_ratio, height_ratio, area_ratio = _page_ratio_metrics(bbox, page)
    if 0.03 <= area_ratio <= 0.85:
        confidence += 0.12
    elif area_ratio < 0.01:
        confidence -= 0.28
        rejection_reason = "candidate_too_small"
    elif area_ratio > 0.9:
        confidence -= 0.1

    if _is_tiny_visual(bbox, page):
        confidence -= 0.32
        rejection_reason = rejection_reason or "candidate_too_small"
    if _is_strip_like(bbox, page):
        confidence -= 0.45
        rejection_reason = "strip_like_visual"
    if candidate.get("weak_image_evidence"):
        confidence -= 0.08

    if width_ratio >= 0.15 and height_ratio >= 0.12:
        confidence += 0.08

    is_composite = _is_composite_candidate(candidate, page)
    if is_composite:
        confidence += 0.05

    if confidence < 0.5 and rejection_reason is None:
        rejection_reason = "low_visual_signal"

    return ("figure" if confidence >= 0.5 else "reject", max(0.0, min(confidence, 0.99)), rejection_reason, is_composite, best_caption_id)


def _candidate_group_key(candidate: dict[str, Any]) -> tuple[int, str]:
    caption_id = candidate.get("best_caption_id") or next(iter(candidate.get("linked_caption_ids") or []), None)
    return int(candidate.get("page_number") or 0), str(caption_id or candidate.get("id") or candidate.get("bbox"))


def _group_candidates(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[_candidate_group_key(candidate)].append(candidate)
    return [
        sorted(group, key=lambda item: ((item.get("bbox") or [0, 0, 0, 0])[1], (item.get("bbox") or [0, 0, 0, 0])[0]))
        for _, group in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _needs_candidate_recheck(group: list[dict[str, Any]], page: dict[str, Any]) -> bool:
    if len(group) > 1:
        return True
    candidate = group[0]
    return bool(
        candidate.get("needs_vlm_rerank")
        or _is_strip_like(candidate.get("bbox"), page)
        or _is_tiny_visual(candidate.get("bbox"), page)
        or candidate.get("weak_image_evidence")
    )


async def _maybe_select_candidate(
    group: list[dict[str, Any]],
    page: dict[str, Any],
    captions_by_id: dict[str, dict[str, Any]],
    paper_dir: Path,
    resolver_version: str,
) -> tuple[dict[str, Any], float, str]:
    scored = sorted(
        group,
        key=lambda candidate: (
            _score_candidate(candidate, page, captions_by_id)[1],
            -_bbox_area(candidate.get("bbox")),
            0 if candidate.get("weak_image_evidence") else 1,
        ),
        reverse=True,
    )
    chosen = scored[0]

    if not _needs_candidate_recheck(group, page):
        return (chosen, 0.0, "heuristic")
    if len(scored) == 1 or not os.environ.get("GEMINI_API_KEY"):
        return (chosen, 0.0, "heuristic")

    raster_path = page.get("raster_path")
    if not raster_path:
        return (chosen, 0.0, "heuristic")

    caption_id = chosen.get("best_caption_id") or next(iter(chosen.get("linked_caption_ids") or []), None)
    caption = captions_by_id.get(str(caption_id), {})
    prompt = {
        "task": "Choose the best crop for the scientific figure caption. Prefer the crop that contains the full figure, not tiny fragments or decorative strips.",
        "resolver_version": resolver_version,
        "caption": {
            "id": caption.get("id"),
            "text": caption.get("text"),
            "bbox": caption.get("bbox"),
        },
        "candidate_crops": [
            {
                "id": candidate.get("id"),
                "bbox": candidate.get("bbox"),
                "source_kind": candidate.get("source_kind"),
                "weak_image_evidence": candidate.get("weak_image_evidence"),
            }
            for candidate in scored[:3]
        ],
        "response_format": {
            "selected_candidate_id": "one of the provided ids",
            "confidence": "0.0-1.0",
        },
    }

    try:
        result = await _call_gemini(
            json.dumps(prompt, ensure_ascii=False),
            model=MODEL_RESOLVER,
            thinking_level="minimal",
            image_paths=[str((paper_dir / raster_path).resolve())],
        )
        payload = json.loads(_clean_llm_json(result["text"]))
        selected = str(payload.get("selected_candidate_id") or "")
        confidence_delta = min(max(float(payload.get("confidence") or 0.0), 0.0), 0.16)
        matched = next((candidate for candidate in scored if str(candidate.get("id")) == selected), None)
        if matched is not None:
            return (matched, confidence_delta, result["model"])
    except Exception:
        pass

    return (chosen, 0.0, "heuristic")


async def _maybe_rerank_caption(
    candidate: dict[str, Any],
    page: dict[str, Any],
    captions_by_id: dict[str, dict[str, Any]],
    paper_dir: Path,
    resolver_version: str,
) -> tuple[str | None, float, str]:
    option_ids = candidate.get("linked_caption_ids", [])[:3]
    if (
        len(option_ids) <= 1
        or not os.environ.get("GEMINI_API_KEY")
        or not candidate.get("needs_vlm_rerank")
    ):
        return (candidate.get("best_caption_id"), 0.0, "heuristic")

    raster_path = page.get("raster_path")
    if not raster_path:
        return (candidate.get("best_caption_id"), 0.0, "heuristic")

    captions = [captions_by_id[caption_id] for caption_id in option_ids if caption_id in captions_by_id]
    if len(captions) <= 1:
        return (candidate.get("best_caption_id"), 0.0, "heuristic")

    prompt = {
        "task": "Select the best matching caption for an existing scientific figure crop. Do not invent a new caption.",
        "resolver_version": resolver_version,
        "candidate_bbox": candidate.get("bbox"),
        "caption_options": [
            {
                "id": caption["id"],
                "text": caption.get("text"),
                "bbox": caption.get("bbox"),
            }
            for caption in captions
        ],
        "response_format": {
            "selected_caption_id": "one of the provided ids",
            "confidence": "0.0-1.0",
        },
    }

    try:
        result = await _call_gemini(
            json.dumps(prompt, ensure_ascii=False),
            model=MODEL_RESOLVER,
            thinking_level="minimal",
            image_paths=[str((paper_dir / raster_path).resolve())],
        )
        payload = json.loads(_clean_llm_json(result["text"]))
        selected = payload.get("selected_caption_id")
        confidence_delta = float(payload.get("confidence") or 0.0)
        if selected in option_ids:
            return (selected, max(0.0, min(confidence_delta, 0.15)), result["model"])
    except Exception:
        pass

    return (candidate.get("best_caption_id"), 0.0, "heuristic")


async def _maybe_detect_subfigures(
    *,
    figure_num: str,
    figure_path: Path,
    paper_dir: Path,
    bbox: list[float],
    page_number: int,
    caption_text: str | None,
    confidence: float,
) -> list[dict[str, Any]]:
    if not os.environ.get("GEMINI_API_KEY"):
        return []

    detector = SubFigureDetector()
    parsed_figure = ParsedFigure(
        figure_id=figure_num,
        page_number=page_number,
        bbox=tuple(bbox),
        image_path=figure_path,
        caption=caption_text or "",
    )

    try:
        result = await detector.detect_subfigures(parsed_figure)
        if not result.has_subfigures or result.confidence < 0.5:
            return []
        extracted = await detector.extract_subfigures(parsed_figure, figure_path.parent, result)
    except Exception:
        return []

    children: list[dict[str, Any]] = []
    for child in extracted:
        child_path = Path(child.image_path)
        if not child_path.exists():
            continue
        with Image.open(child_path) as image:
            width, height = image.size
        children.append(
            {
                "figure_num": f"{figure_num}{(child.sub_label or '').upper()}",
                "caption": caption_text,
                "file_path": str(child_path.resolve().relative_to(paper_dir.resolve())),
                "page_number": child.page_number,
                "bbox": list(child.bbox),
                "quality": _quality_from_dims(width, height),
                "confidence": max(0.5, confidence - 0.05),
                "classifier_label": "figure",
                "classifier_model": "gemini-subfigure",
                "parent_figure_num": figure_num,
                "is_composite": False,
                "resolver_version": "resolver-v1",
                "extraction_status": _status_from_confidence(confidence - 0.05),
                "rejection_reason": None,
            }
        )
    return children


async def resolve_figure_candidates(
    manifest: dict[str, Any],
    *,
    paper_dir: Path,
    pdf_path: Path,
    resolver_version: str,
    page_numbers: set[int] | None = None,
) -> dict[str, Any]:
    pages_by_number = {
        page["page_number"]: page
        for page in manifest.get("pages", [])
        if isinstance(page.get("page_number"), int)
    }
    captions_by_id = {
        caption["id"]: caption
        for caption in manifest.get("captions", [])
        if isinstance(caption.get("id"), str)
    }

    figures_dir = paper_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    seen_figure_nums: set[str] = set()
    accepted: list[dict[str, Any]] = []
    low_confidence_pages: set[int] = set()
    fallback_index = 1

    candidates = [
        candidate
        for candidate in manifest.get("figure_candidates", [])
        if not page_numbers or candidate.get("page_number") in page_numbers
    ]
    candidate_groups = _group_candidates(candidates)

    for group in candidate_groups:
        candidate = group[0]
        page_number = candidate.get("page_number")
        page = pages_by_number.get(page_number)
        if page is None:
            continue

        selected_candidate, selection_delta, selection_model = await _maybe_select_candidate(
            group,
            page,
            captions_by_id,
            paper_dir,
            resolver_version,
        )
        bbox = selected_candidate.get("bbox")
        if not bbox:
            continue

        label, confidence, rejection_reason, is_composite, best_caption_id = _score_candidate(selected_candidate, page, captions_by_id)
        confidence = min(0.99, confidence + selection_delta)
        classifier_model = selection_model
        if 0.5 <= confidence < 0.85:
            best_caption_id, delta, classifier_model = await _maybe_rerank_caption(
                selected_candidate,
                page,
                captions_by_id,
                paper_dir,
                resolver_version,
            )
            confidence = min(0.99, confidence + delta)
        elif confidence < 0.5:
            low_confidence_pages.add(page_number)

        if label != "figure" or confidence < 0.5:
            continue

        caption = captions_by_id.get(best_caption_id or "", {})
        caption_text = caption.get("text")
        figure_num = _normalized_figure_num(caption_text, page_number, fallback_index, seen_figure_nums)
        fallback_index += 1
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", figure_num).strip("_") or f"p{page_number}_figure"
        output_path = figures_dir / f"{safe_name}.png"
        width, height = _crop_candidate(pdf_path, page_number, bbox, output_path)

        entry = {
            "figure_num": figure_num,
            "caption": caption_text,
            "file_path": str(output_path.resolve().relative_to(paper_dir.resolve())),
            "page_number": page_number,
            "bbox": bbox,
            "quality": _quality_from_dims(width, height),
            "extraction_engine": manifest.get("engine"),
            "confidence": confidence,
            "classifier_label": label,
            "classifier_model": classifier_model,
            "parent_figure_num": None,
            "is_composite": is_composite,
            "resolver_version": resolver_version,
            "extraction_status": _status_from_confidence(confidence),
            "rejection_reason": rejection_reason,
            "best_caption_id": best_caption_id,
        }
        accepted.append(entry)

        if is_composite:
            accepted.extend(
                await _maybe_detect_subfigures(
                    figure_num=figure_num,
                    figure_path=output_path,
                    paper_dir=paper_dir,
                    bbox=bbox,
                    page_number=page_number,
                    caption_text=caption_text,
                    confidence=confidence,
                )
            )

    return {
        "figures": accepted,
        "low_confidence_pages": sorted(low_confidence_pages),
    }
