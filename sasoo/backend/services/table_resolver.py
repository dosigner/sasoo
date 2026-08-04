"""
Table resolver for resolver_v1.
"""

from __future__ import annotations

import asyncio
import base64
import csv
import json
import logging
import os
import re
import unicodedata
from io import StringIO
from pathlib import Path
from typing import Any

from api.analysis_helpers import _clean_llm_json
from services.llm.interactions_client import call_interaction
from services.document_manifest import (
    _caption_label_key,
    parse_table_label,
    strip_caption_decoration,
    table_int_to_roman,
)
from services.model_registry import resolve as resolve_model

logger = logging.getLogger(__name__)


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
    # 계약 6: 캡션 라벨 규칙만 넓히고 여기를 놔두면 캡션은 인정하면서 번호를 못 읽어
    # "Table {index}"라는 가짜 이름이 붙는다. NFKC는 "Table\xa0I" 표기 때문에 필요하다.
    normalized = unicodedata.normalize("NFKC", strip_caption_decoration(caption_text))
    label = parse_table_label(normalized)
    if label:
        notation, number, suffix, _ = label
        # 표기법은 원문을 따른다 — IEEE 논문에서 "Table VIII"이 "Table 8"로 바뀌면
        # 사용자가 본문에서 그 표를 찾을 수 없다.
        base = f"Table {table_int_to_roman(number)}" if notation == "roman" else f"Table {number}{suffix.upper()}"
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
    # 표의 격자 복원은 본질적으로 VLM에 의존한다 — `caption_fallback_crop` 후보는 text_grid가
    # 비어 있고, 그 상태로 돌아가면 최종 필터(_has_meaningful_grid)에서 100% 탈락한다.
    # 키가 없거나 호출이 실패했을 때 그 사실이 어디에도 남지 않아, 표가 통째로 사라져도
    # 원인을 알 수 없었다. 429·JSON 파싱 실패·타임아웃이 전부 같은 결과(빈 grid)로 보인다.
    if not os.environ.get("GEMINI_API_KEY"):
        if not _has_meaningful_grid(_normalize_grid(candidate.get("text_grid"))):
            logger.warning(
                "table resolver: GEMINI_API_KEY가 없어 격자 복원을 건너뛴다 — "
                "이 후보는 격자가 비어 있어 표로 산출되지 못한다 (page=%s, id=%s)",
                candidate.get("page_number"), candidate.get("id"),
            )
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
        image_bytes = (paper_dir / page["raster_path"]).resolve().read_bytes()
        _choice = resolve_model("table_resolver", "gemini")
        result = await call_interaction(
            [
                {"type": "image", "data": base64.b64encode(image_bytes).decode("ascii"), "mime_type": "image/png"},
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
            lane="pipeline",
            model=_choice.model,
            thinking_level=_choice.effort,
            store=False,
        )
        payload = json.loads(_clean_llm_json(result["text"]))
        return (_normalize_grid(payload.get("rows")), result["model"], float(payload.get("confidence") or 0.0))
    except Exception as exc:
        # 예외를 삼키는 것 자체는 유지한다(한 표의 실패가 문서 전체를 깨면 안 된다).
        # 다만 조용히 빈 grid로 둔갑시키지는 않는다 — 실패 원인이 로그에 남아야 한다.
        logger.warning(
            "table resolver: 격자 복원 실패 (page=%s, id=%s): %s: %s",
            candidate.get("page_number"), candidate.get("id"), type(exc).__name__, exc,
        )
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
    emitted_labels: set[str] = set()
    dropped_without_caption = 0
    dropped_duplicate_label = 0
    resolved: list[dict[str, Any]] = []
    low_confidence_pages: set[int] = set()
    fallback_index = 1
    suspect_pages = {
        int(page)
        for page in (manifest.get("audit", {}) or {}).get("suspect_pages", [])
        if isinstance(page, int)
    }

    ordered_candidates = sorted(
        [
            item
            for item in manifest.get("table_candidates", [])
            if not page_numbers or item.get("page_number") in page_numbers
        ],
        key=lambda item: (item.get("page_number", 9999), (item.get("bbox") or [0, 0, 0, 0])[1], (item.get("bbox") or [0, 0, 0, 0])[0]),
    )

    # ── 1단계(순수 계산): 후보별로 grid·신뢰도·VLM 수리 필요 여부를 먼저 확정한다.
    # 이 판정에는 LLM이 필요 없다 — 그래서 수리 호출만 따로 떼어 병렬로 돌릴 수 있다.
    prepared: list[dict[str, Any]] = []
    for candidate in ordered_candidates:
        page_number = candidate.get("page_number")
        grid, preprocessing_notes = _preprocess_grid(_normalize_grid(candidate.get("text_grid")))
        parse_method = candidate.get("source_kind") or "hybrid"
        confidence = 0.6 if _has_meaningful_grid(grid) else 0.38

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
            bool(candidate.get("plausible_ruled_bbox"))
            or bool(candidate.get("best_caption_id"))
            or (isinstance(page_number, int) and page_number in suspect_pages)
        )
        prepared.append(
            {
                "candidate": candidate,
                "page_number": page_number,
                "grid": grid,
                "preprocessing_notes": preprocessing_notes,
                "parse_method": parse_method,
                "confidence": confidence,
                "unresolved_reasons": unresolved_reasons,
                "needs_vlm_repair": needs_vlm_repair,
                "skip": not _has_meaningful_grid(grid) and not needs_vlm_repair,
            }
        )

    # ── 2단계(병렬): VLM 수리. 후보끼리 독립이라 동시에 돌린다. 예전에는 이 호출이
    # 메인 루프 안에서 순차로 await돼, 수리가 필요한 표 수만큼 지연이 그대로 쌓였다.
    repair_targets = [item for item in prepared if item["needs_vlm_repair"] and not item["skip"]]
    if repair_targets:
        repair_results = await asyncio.gather(
            *[_repair_with_vlm(item["candidate"], manifest, paper_dir) for item in repair_targets]
        )
        for item, result in zip(repair_targets, repair_results):
            item["repair_result"] = result

    # ── 3단계(순차): 표 번호 부여와 파일 쓰기. 원래 순서를 지켜야 번호·파일명이 이전과 같다.
    for item in prepared:
        candidate = item["candidate"]
        page_number = item["page_number"]
        grid = item["grid"]
        preprocessing_notes = item["preprocessing_notes"]
        parse_method = item["parse_method"]
        confidence = item["confidence"]
        unresolved_reasons = item["unresolved_reasons"]
        needs_vlm_repair = item["needs_vlm_repair"]
        classifier_model = "heuristic"
        repair_attempted = False
        repair_reason: str | None = None
        repair_confidence: float | None = None

        if item["skip"]:
            if isinstance(page_number, int):
                low_confidence_pages.add(page_number)
            continue

        if needs_vlm_repair:
            repair_attempted = True
            repair_reason = " | ".join(dict.fromkeys(preprocessing_notes + unresolved_reasons)) or None
            repaired_grid, model_used, repair_confidence_value = item["repair_result"]
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

        # ── 캡션 필수 게이트 (그림 계약 7의 대칭 규칙).
        # 캡션이 없으면 `Table {fallback_index}`라는 가짜 번호가 붙어 그대로 산출물이 됐다.
        # 실측: 산출된 표 38개 중 28개가 무캡션이었고, 크롭을 눈으로 보니 정체는 대부분
        # **그래프의 범례 박스**였다(2014_Saliency p7의 PR 곡선 범례 9개, 2013 p8 등).
        # 범례는 격자 구조를 가져 pdfplumber가 표로 인식하지만 캡션이 붙지 않는다.
        if not caption_text:
            dropped_without_caption += 1
            if isinstance(page_number, int):
                low_confidence_pages.add(page_number)
            continue

        # ── 라벨 단위 중복제거.
        # 같은 표에 후보가 둘 붙으면 "Table 1"과 "Table 1 [2]"가 함께 나온다. 원인은 두 가지고
        # 둘 다 실측된다: (a) 한 캡션에 후보가 여럿 연결(2022_SciRep 3건), (b) 같은 라벨의
        # 캡션 자체가 중복(2025_TurboQuant p20의 "Table 1"이 2개). 라벨 기준으로 걸러야
        # 두 경우가 함께 잡힌다.
        label_key = _caption_label_key(caption_text)
        if label_key:
            if label_key in emitted_labels:
                dropped_duplicate_label += 1
                continue
            emitted_labels.add(label_key)

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

    if ordered_candidates and not resolved:
        # 캡션 연결이 하나도 없어 전멸한 경우. figure_resolver의 같은 경고와 동형이다.
        logger.warning(
            "table resolver: 후보 %d개가 있었지만 캡션에 연결된 것이 없어 표 0개 "
            "(파서가 캡션을 못 잡았거나 후보가 전부 오탐) — paper_dir=%s",
            len(ordered_candidates), paper_dir,
        )
    if dropped_without_caption or dropped_duplicate_label:
        logger.info(
            "table resolver: 캡션 없는 후보 %d개, 라벨 중복 %d개를 버렸다 (표 %d개 산출)",
            dropped_without_caption, dropped_duplicate_label, len(resolved),
        )

    return {
        "tables": resolved,
        "low_confidence_pages": sorted(low_confidence_pages),
    }
