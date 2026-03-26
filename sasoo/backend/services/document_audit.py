"""
Document audit heuristics for resolver_v1 fallback.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

FIGURE_MENTION_PATTERN = re.compile(r"\b(?:Fig\.?|Figure)\b", re.IGNORECASE)
TABLE_MENTION_PATTERN = re.compile(r"\b(?:Table|Tbl\.?)\b", re.IGNORECASE)
PAGE_MARKER_PATTERN = re.compile(r"--- Page (\d+) ---")


def _page_text_map(full_text: str) -> dict[int, str]:
    matches = list(PAGE_MARKER_PATTERN.finditer(full_text))
    if not matches:
        return {}

    page_map: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(full_text)
        page_map[int(match.group(1))] = full_text[start:end]
    return page_map


def _bbox_area(bbox: list[float] | None) -> float:
    if not bbox:
        return 0.0
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _page_area(page: dict[str, Any]) -> float:
    size = page.get("page_size") or {}
    return float(size.get("width") or 0.0) * float(size.get("height") or 0.0)


def _is_tiny_candidate(candidate: dict[str, Any], page: dict[str, Any]) -> bool:
    page_area = _page_area(page)
    if not page_area:
        return False
    return _bbox_area(candidate.get("bbox")) / page_area < 0.012 or bool(candidate.get("weak_image_evidence"))


def _is_low_quality_figure(figure: dict[str, Any], page: dict[str, Any]) -> bool:
    try:
        confidence = float(figure.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    quality = str(figure.get("quality") or "").lower()
    return quality == "low" or confidence < 0.72 or _is_tiny_candidate(figure, page)


def _is_low_quality_table(table: dict[str, Any], page: dict[str, Any]) -> bool:
    try:
        confidence = float(table.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence < 0.72 or _bbox_area(table.get("bbox")) / max(_page_area(page), 1.0) < 0.02


def find_suspect_pages(
    *,
    full_text: str,
    pages: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    figure_candidates: list[dict[str, Any]],
    table_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    page_text = _page_text_map(full_text)
    figure_count_by_page = defaultdict(int)
    table_count_by_page = defaultdict(int)
    figure_candidate_count_by_page = defaultdict(int)
    table_candidate_count_by_page = defaultdict(int)
    tiny_figure_candidate_count_by_page = defaultdict(int)
    weak_table_candidate_count_by_page = defaultdict(int)
    low_quality_figure_count_by_page = defaultdict(int)
    low_quality_table_count_by_page = defaultdict(int)
    pages_by_number = {
        page.get("page_number"): page
        for page in pages
        if isinstance(page.get("page_number"), int)
    }

    for figure in figures:
        page_number = figure.get("page_number")
        if isinstance(page_number, int):
            figure_count_by_page[page_number] += 1
            page = pages_by_number.get(page_number, {})
            if _is_low_quality_figure(figure, page):
                low_quality_figure_count_by_page[page_number] += 1
    for table in tables:
        page_number = table.get("page_number")
        if isinstance(page_number, int):
            table_count_by_page[page_number] += 1
            page = pages_by_number.get(page_number, {})
            if _is_low_quality_table(table, page):
                low_quality_table_count_by_page[page_number] += 1
    for candidate in figure_candidates:
        page_number = candidate.get("page_number")
        if isinstance(page_number, int):
            figure_candidate_count_by_page[page_number] += 1
            page = pages_by_number.get(page_number, {})
            if _is_tiny_candidate(candidate, page):
                tiny_figure_candidate_count_by_page[page_number] += 1
    for candidate in table_candidates:
        page_number = candidate.get("page_number")
        if isinstance(page_number, int):
            table_candidate_count_by_page[page_number] += 1
            if not candidate.get("has_meaningful_grid") and not candidate.get("plausible_ruled_bbox"):
                weak_table_candidate_count_by_page[page_number] += 1

    suspect_pages: list[tuple[int, int]] = []
    mention_stats: dict[int, dict[str, int]] = {}
    for page in pages:
        page_number = page.get("page_number")
        if not isinstance(page_number, int):
            continue
        text = page_text.get(page_number, "")
        figure_mentions = len(FIGURE_MENTION_PATTERN.findall(text))
        table_mentions = len(TABLE_MENTION_PATTERN.findall(text))
        mention_stats[page_number] = {
            "figure_mentions": figure_mentions,
            "table_mentions": table_mentions,
        }
        score = 0
        if figure_mentions >= 2 and figure_count_by_page[page_number] == 0:
            score += figure_mentions
            if figure_candidate_count_by_page[page_number] == 0:
                score += 1
        elif figure_mentions >= 2 and tiny_figure_candidate_count_by_page[page_number] >= max(1, figure_candidate_count_by_page[page_number]):
            score += figure_mentions
        elif figure_count_by_page[page_number] and low_quality_figure_count_by_page[page_number] >= figure_count_by_page[page_number]:
            score += 2
        if table_mentions >= 2 and table_count_by_page[page_number] == 0:
            score += table_mentions
            if table_candidate_count_by_page[page_number] == 0:
                score += 1
        elif table_mentions >= 1 and weak_table_candidate_count_by_page[page_number] >= max(1, table_candidate_count_by_page[page_number]):
            score += table_mentions + 1
        elif table_count_by_page[page_number] and low_quality_table_count_by_page[page_number] >= table_count_by_page[page_number]:
            score += 2
        if score > 0:
            suspect_pages.append((page_number, score))

    suspect_pages.sort(key=lambda item: (-item[1], item[0]))
    reason = None
    if suspect_pages:
        if any(low_quality_figure_count_by_page[p] or low_quality_table_count_by_page[p] for p, _ in suspect_pages):
            reason = "low_quality_visual_results"
        elif any(tiny_figure_candidate_count_by_page[p] or weak_table_candidate_count_by_page[p] for p, _ in suspect_pages):
            reason = "weak_visual_candidates"
        else:
            reason = "mention_heavy_but_unresolved"
    return {
        "triggered": bool(suspect_pages),
        "reason": reason,
        "suspect_pages": [page_number for page_number, _ in suspect_pages[:5]],
        "mention_stats": mention_stats,
    }
