"""
Figure resolver for resolver_v1.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz
from PIL import Image

from api.analysis_helpers import _clean_llm_json
from models.paper import Figure as ParsedFigure
from services.llm.interactions_client import call_interaction
from services.document_manifest import strip_caption_decoration
from services.model_registry import resolve as resolve_model
from services.subfigure_detector import SubFigureDetector

logger = logging.getLogger(__name__)

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


def _crop_candidate(
    pdf_path: Path,
    page_number: int,
    bbox: list[float],
    output_path: Path,
    *,
    doc: "fitz.Document | None" = None,
) -> tuple[int, int]:
    """후보 bbox를 크롭해 PNG로 저장하고 (width, height)를 반환한다.

    doc을 주면 그걸 재사용한다 — 예전에는 후보마다 fitz.open/close를 반복해 그림 수만큼
    PDF 전체를 다시 파싱했다(21그림 = 21회 재파싱). fitz.Document는 스레드 안전이 아니므로
    호출부가 단일 스레드에서 순차로 쓸 때만 공유해야 한다.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    owned = doc is None
    document = fitz.open(str(pdf_path)) if owned else doc
    try:
        page = document[page_number - 1]
        clip = _odl_bbox_to_fitz_rect(page.rect.height, bbox)
        pix = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), clip=clip, alpha=False)
        pix.save(str(output_path))
        return (pix.width, pix.height)
    finally:
        if owned:
            document.close()


class _RasterCache:
    """페이지 래스터 PNG의 base64를 페이지당 1회만 읽어 재사용한다.

    예전에는 VLM 호출마다 (paper_dir / raster_path).read_bytes()를 다시 돌려, 같은 페이지에
    그림이 3개면 같은 450KB PNG를 3번 읽고 3번 base64로 인코딩했다(실측 페이지당 358~457KB).

    get()은 await가 없는 동기 함수다 — 같은 이벤트 루프의 코루틴들이 중간에 끼어들 수 없어
    별도 락 없이도 캐시 갱신이 안전하다.
    """

    def __init__(self, paper_dir: Path) -> None:
        self._paper_dir = paper_dir
        self._cache: dict[int, str | None] = {}

    def get(self, page: dict[str, Any]) -> str | None:
        page_number = page.get("page_number")
        if page_number in self._cache:
            return self._cache[page_number]
        raster_path = page.get("raster_path")
        encoded: str | None = None
        if raster_path:
            try:
                data = (self._paper_dir / raster_path).resolve().read_bytes()
                encoded = base64.b64encode(data).decode("ascii")
            except OSError:
                encoded = None
        self._cache[page_number] = encoded
        return encoded


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
    match = FIGURE_LABEL_PATTERN.match(strip_caption_decoration(caption_text))
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


def _survives_acceptance(
    candidate: dict[str, Any],
    page: dict[str, Any],
    captions_by_id: dict[str, dict[str, Any]],
    confidence_delta: float,
) -> bool:
    """이 후보가 `resolve_figure_candidates`의 수용 조건을 통과하는지 미리 본다.

    조건은 2단계 루프의 것과 같아야 한다 — label이 figure이고, confidence가 0.5 이상이며,
    캡션이 연결돼 있어야 한다(계약 7).
    """
    label, confidence, _, _, best_caption_id = _score_candidate(candidate, page, captions_by_id)
    return label == "figure" and min(0.99, confidence + confidence_delta) >= 0.5 and bool(best_caption_id)


async def _maybe_select_candidate(
    group: list[dict[str, Any]],
    page: dict[str, Any],
    captions_by_id: dict[str, dict[str, Any]],
    rasters: _RasterCache,
    resolver_version: str,
    *,
    provider: str = "gemini",
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

    image_b64 = rasters.get(page)
    if not image_b64:
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
        _choice = resolve_model("figure_resolver", provider)
        result = await call_interaction(
            [
                {"type": "image", "data": image_b64, "mime_type": "image/png"},
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
            lane="pipeline",
            model=_choice.model,
            thinking_level=_choice.effort,
            store=False,
        )
        payload = json.loads(_clean_llm_json(result["text"]))
        selected = str(payload.get("selected_candidate_id") or "")
        confidence_delta = min(max(float(payload.get("confidence") or 0.0), 0.0), 0.16)
        matched = next((candidate for candidate in scored if str(candidate.get("id")) == selected), None)
        if matched is not None and _survives_acceptance(matched, page, captions_by_id, confidence_delta):
            return (matched, confidence_delta, result["model"])
        # VLM이 고른 크롭이 수용 게이트를 통과하지 못하면 휴리스틱 선택을 유지한다.
        # 이 단계의 역할은 "여럿 중 최선 고르기"이지 수용 여부를 뒤집는 것이 아닌데,
        # 고른 결과가 그대로 게이트로 넘어가 그림이 통째로 사라졌다.
        # 실측(2022_SciRep p9): 휴리스틱은 figcand:p9:n1(figure, 0.60)을 고르는데 VLM이
        # figcand:p9:n0(reject, 0.43, low_visual_signal)을 골라 Fig. 9가 매번 없어졌다.
        # 2025_TurboQuant에서는 같은 경로로 실행마다 다른 그림이 1~3개씩 사라졌다.
    except Exception:
        pass

    return (chosen, 0.0, "heuristic")


async def _maybe_rerank_caption(
    candidate: dict[str, Any],
    page: dict[str, Any],
    captions_by_id: dict[str, dict[str, Any]],
    rasters: _RasterCache,
    resolver_version: str,
    *,
    provider: str = "gemini",
) -> tuple[str | None, float, str]:
    option_ids = candidate.get("linked_caption_ids", [])[:3]
    if (
        len(option_ids) <= 1
        or not os.environ.get("GEMINI_API_KEY")
        or not candidate.get("needs_vlm_rerank")
    ):
        return (candidate.get("best_caption_id"), 0.0, "heuristic")

    image_b64 = rasters.get(page)
    if not image_b64:
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
        _choice = resolve_model("figure_resolver", provider)
        result = await call_interaction(
            [
                {"type": "image", "data": image_b64, "mime_type": "image/png"},
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
            lane="pipeline",
            model=_choice.model,
            thinking_level=_choice.effort,
            store=False,
        )
        payload = json.loads(_clean_llm_json(result["text"]))
        selected = payload.get("selected_caption_id")
        confidence_delta = float(payload.get("confidence") or 0.0)
        if selected in option_ids:
            return (selected, max(0.0, min(confidence_delta, 0.15)), result["model"])
    except Exception:
        pass

    return (candidate.get("best_caption_id"), 0.0, "heuristic")


def _subfigure_num(figure_num: str, sub_label: str | None) -> str:
    """부모 그림 번호와 패널 라벨을 합쳐 서브피겨 이름을 만든다.

    패널 라벨은 알파벳뿐 아니라 숫자도 온다(`_normalize_sub_label`이 둘 다 인정한다).
    숫자를 그냥 이어붙이면 부모와 구분되지 않는다 — 실측(2013_IEEETIP): Fig. 12의
    패널 7개가 `Fig. 121`~`Fig. 127`이 되어, 존재하지 않는 121번 그림처럼 읽혔다.
    숫자일 때만 구분자를 넣는다. 알파벳은 기존 표기(`Fig. 12A`)를 그대로 둔다.
    """
    label = (sub_label or "").upper()
    if not label:
        return figure_num
    return f"{figure_num}-{label}" if label[0].isdigit() else f"{figure_num}{label}"


async def _maybe_detect_subfigures(
    *,
    figure_num: str,
    figure_path: Path,
    paper_dir: Path,
    bbox: list[float],
    page_number: int,
    caption_text: str | None,
    confidence: float,
    provider: str = "gemini",
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
        result = await detector.detect_subfigures(parsed_figure, provider=provider)
        if not result.has_subfigures or result.confidence < 0.5:
            return []
        extracted = await detector.extract_subfigures(
            parsed_figure, figure_path.parent, result, provider=provider,
        )
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
                "figure_num": _subfigure_num(figure_num, child.sub_label),
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
    provider: str = "gemini",
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
    rasters = _RasterCache(paper_dir)

    # 캡션에 연결되지 않은 후보(로고·아이콘·수식 이미지·장식 등)가 각각 그림으로 승격돼
    # 목록을 부풀리고 있었다. 이름도 "p9_fig7" 꼴이라 사용자 눈에 바로 노이즈로 보인다.
    # 캡션 없는 후보는 그림으로 인정하지 않는다.
    #
    # 한때 "문서에 캡션이 하나라도 있을 때만 적용"하는 안전장치를 뒀는데, 캡션 앞
    # 마크다운 서식을 벗기는 수정(strip_caption_decoration) 이후로는 전 논문이 캡션을
    # 충분히 잡아 그 분기가 한 번도 발동하지 않았다 — 결과가 12편 전부 동일해 제거했다.
    #
    # 남는 위험: 파서가 캡션을 하나도 못 잡는 문서가 오면 그림이 0개가 된다. 조용히 비면
    # 원인 파악이 어려우므로 아래에서 경고를 남긴다.

    candidates = [
        candidate
        for candidate in manifest.get("figure_candidates", [])
        if not page_numbers or candidate.get("page_number") in page_numbers
    ]
    candidate_groups = _group_candidates(candidates)

    # ── 1단계(병렬): 그룹별 VLM 판정. 후보 그룹끼리는 완전히 독립이라 동시에 돌려도 된다.
    # 예전에는 이 루프가 순차라 그림 N개면 VLM 호출이 일렬로 최대 2N번 나갔다.
    # 파일 쓰기·번호 부여는 여기서 하지 않는다 — 순서에 의존하므로 2단계로 미룬다.
    async def _decide(group: list[dict[str, Any]]) -> dict[str, Any] | None:
        page_number = group[0].get("page_number")
        page = pages_by_number.get(page_number)
        if page is None:
            return None

        selected_candidate, selection_delta, selection_model = await _maybe_select_candidate(
            group,
            page,
            captions_by_id,
            rasters,
            resolver_version,
            provider=provider,
        )
        bbox = selected_candidate.get("bbox")
        if not bbox:
            return None

        label, confidence, rejection_reason, is_composite, best_caption_id = _score_candidate(
            selected_candidate, page, captions_by_id
        )
        confidence = min(0.99, confidence + selection_delta)
        classifier_model = selection_model
        low_confidence = False
        if 0.5 <= confidence < 0.85:
            best_caption_id, delta, classifier_model = await _maybe_rerank_caption(
                selected_candidate,
                page,
                captions_by_id,
                rasters,
                resolver_version,
                provider=provider,
            )
            confidence = min(0.99, confidence + delta)
        elif confidence < 0.5:
            low_confidence = True

        return {
            "page_number": page_number,
            "bbox": bbox,
            "label": label,
            "confidence": confidence,
            "rejection_reason": rejection_reason,
            "is_composite": is_composite,
            "best_caption_id": best_caption_id,
            "classifier_model": classifier_model,
            "low_confidence": low_confidence,
        }

    decisions = await asyncio.gather(*[_decide(group) for group in candidate_groups])

    # ── 2단계(순차): 그림 번호 부여와 크롭 파일 쓰기. 반드시 후보 그룹 원래 순서를 지켜야
    # 번호(_normalized_figure_num의 seen 집합·fallback_index)와 파일명이 예전과 동일하게 나온다.
    # LLM 호출이 없어 순차여도 빠르다. PDF는 한 번만 열어 전 후보가 공유한다.
    pending_subfigures: list[tuple[int, dict[str, Any], Path]] = []
    crop_doc = fitz.open(str(pdf_path))
    try:
        for decision in decisions:
            if decision is None:
                continue
            page_number = decision["page_number"]
            if decision["low_confidence"]:
                low_confidence_pages.add(page_number)
            if decision["label"] != "figure" or decision["confidence"] < 0.5:
                continue
            # 크롭 파일을 쓰기 전에 걸러 디스크에 고아 PNG가 남지 않게 한다.
            if not decision["best_caption_id"]:
                continue

            confidence = decision["confidence"]
            bbox = decision["bbox"]
            caption = captions_by_id.get(decision["best_caption_id"] or "", {})
            caption_text = caption.get("text")
            figure_num = _normalized_figure_num(
                caption_text, page_number, fallback_index, seen_figure_nums
            )
            fallback_index += 1
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", figure_num).strip("_") or f"p{page_number}_figure"
            output_path = figures_dir / f"{safe_name}.png"
            width, height = _crop_candidate(
                pdf_path, page_number, bbox, output_path, doc=crop_doc
            )

            entry = {
                "figure_num": figure_num,
                "caption": caption_text,
                "file_path": str(output_path.resolve().relative_to(paper_dir.resolve())),
                "page_number": page_number,
                "bbox": bbox,
                "quality": _quality_from_dims(width, height),
                "extraction_engine": manifest.get("engine"),
                "confidence": confidence,
                "classifier_label": decision["label"],
                "classifier_model": decision["classifier_model"],
                "parent_figure_num": None,
                "is_composite": decision["is_composite"],
                "resolver_version": resolver_version,
                "extraction_status": _status_from_confidence(confidence),
                "rejection_reason": decision["rejection_reason"],
                "best_caption_id": decision["best_caption_id"],
            }
            accepted.append(entry)
            if decision["is_composite"]:
                pending_subfigures.append((len(accepted) - 1, entry, output_path))
    finally:
        crop_doc.close()

    # ── 3단계(병렬): composite 그림의 서브피겨 검출. 그림마다 VLM 호출이 1회씩 붙으므로
    # 여기가 순차면 composite 개수만큼 지연이 쌓인다. 부모 entry는 이미 확정돼 있어
    # 병렬로 돌려도 번호·파일명이 흔들리지 않는다.
    if pending_subfigures:
        children_lists = await asyncio.gather(
            *[
                _maybe_detect_subfigures(
                    figure_num=entry["figure_num"],
                    figure_path=path,
                    paper_dir=paper_dir,
                    bbox=entry["bbox"],
                    page_number=entry["page_number"],
                    caption_text=entry["caption"],
                    confidence=entry["confidence"],
                    provider=provider,
                )
                for _, entry, path in pending_subfigures
            ]
        )
        # 부모 바로 뒤에 자식이 오도록 뒤에서부터 삽입한다(앞 인덱스가 밀리지 않게).
        for (index, _, _), children in sorted(
            zip(pending_subfigures, children_lists), key=lambda item: item[0][0], reverse=True
        ):
            if children:
                accepted[index + 1 : index + 1] = children

    if candidate_groups and not accepted:
        # 캡션 연결이 하나도 없어 전멸한 경우. 파서가 캡션을 못 잡은 문서일 가능성이 크다.
        logger.warning(
            "figure resolver: 후보 %d그룹이 있었지만 캡션에 연결된 것이 없어 그림 0개 "
            "(파서가 캡션을 못 잡았을 수 있음) — paper_dir=%s",
            len(candidate_groups), paper_dir,
        )

    return {
        "figures": accepted,
        "low_confidence_pages": sorted(low_confidence_pages),
    }
