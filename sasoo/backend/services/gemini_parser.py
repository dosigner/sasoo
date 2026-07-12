"""
Gemini Vision 기반 대체 PDF 파서 엔진.

ODL(Java) 파서와 동일한 계약으로 ``(root_json, markdown_text, actual_engine)``
3-tuple을 반환한다. PyMuPDF로 페이지를 래스터화해 비전 모델에 넘기고, 페이지마다
"페이지 전체 마크다운 + 정규화(0-1000) box_2d 요소 목록"을 받아 ODL 호환 트리로
조립한다. 조립된 트리는 build_document_manifest / figure_candidates가 그대로 소비한다.

좌표계 (odl_parser._odl_bbox_to_fitz_rect / figure_candidates._extract_pymupdf_image_blocks
에서 확인): ODL 트리 bbox = [x_left, y_bottom, x_right, y_top], 단위는 PDF 포인트,
원점은 페이지 좌하단, y는 위로 증가(y_bottom < y_top).

Gemini box_2d 규약: [ymin, xmin, ymax, xmax], 0-1000 정규화, 좌상단 원점(y 아래로 증가).
환산은 pymupdf 블록과 동일한 방식([x0, H - y1, x1, H - y0])을 정규화 좌표로 옮긴 것.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from services.llm.interactions_client import call_interaction
from services.models import MODEL_VISUAL
from services.pricing import calc_cost

logger = logging.getLogger(__name__)

GEMINI_ENGINE_NAME = "gemini"
RENDER_DPI = 180                # 페이지 래스터화 해상도
PAGE_CONCURRENCY = 4            # 동시에 진행하는 페이지 수(interactions pipeline lane 세마포어와 조합)
_PAGE_RETRIES = 1              # 페이지 호출 실패 시 추가 재시도 횟수(총 2회 시도)
_THINKING_LEVEL = "low"        # 구조 충실도를 위해 약간의 추론. thinking 토큰은 출력 단가로 과금됨.

# 기본 system_instruction은 모든 value를 한국어로 강제한다(interactions_client). 파서는
# 원문을 그대로 옮겨야 하므로 전용 지시로 덮어써 번역/요약을 막는다.
_PARSER_SYSTEM_INSTRUCTION = (
    "You are a precise PDF document parser. Transcribe the page content verbatim in the "
    "document's original language. Never translate, summarize, paraphrase, or add commentary. "
    "Output only valid JSON that matches the requested schema."
)

# box_2d는 [ymin, xmin, ymax, xmax] 0-1000 정규화 — Gemini 공식 규약.
_PAGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string"},
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["image", "table", "caption", "heading", "paragraph", "formula"],
                    },
                    "box_2d": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "text": {"type": "string"},
                },
                "required": ["type", "box_2d", "text"],
            },
        },
    },
    "required": ["markdown", "elements"],
}

_PAGE_PROMPT = (
    "Parse this single scientific-paper page image into structured JSON.\n"
    "\n"
    "Return two fields:\n"
    "1. \"markdown\": the ENTIRE page transcribed as Markdown, in reading order.\n"
    "   - Tables as GitHub-flavored Markdown tables.\n"
    "   - Math/equations as LaTeX: inline $...$ and display $$...$$.\n"
    "   - At each figure's location put a single line: ![Figure N](placeholder)\n"
    "   - Preserve the original language verbatim; do not translate.\n"
    "2. \"elements\": a list of visual/text blocks on the page. For each block give:\n"
    "   - \"type\": one of image | table | caption | heading | paragraph | formula\n"
    "   - \"box_2d\": [ymin, xmin, ymax, xmax] normalized to 0-1000, origin at the\n"
    "     TOP-LEFT of the page (y grows downward). Use the tightest box that encloses the block.\n"
    "   - \"text\": for caption/heading/paragraph -> the verbatim text; for formula -> its LaTeX;\n"
    "     for table -> the table rendered as Markdown (may be empty); for image -> empty string \"\".\n"
    "\n"
    "Rules:\n"
    "- Every figure/chart/photo/diagram region MUST appear as an \"image\" element with a box_2d.\n"
    "- Figure and table captions (e.g. \"Figure 3: ...\", \"Table 2: ...\") MUST be separate\n"
    "  \"caption\" elements whose text starts with the exact caption label.\n"
    "- Output JSON only."
)


class GeminiParserError(RuntimeError):
    """Gemini 파서 엔진 실패. odl_parser 디스패처가 OdlParserError로 변환해 폴백을 유도한다."""


# Gemini element type -> ODL 트리 type 매핑.
# formula는 ODL의 TEXTUAL_TYPES에 없어 매니페스트에서 탈락하므로 paragraph로 보존한다.
_GEMINI_TO_ODL_TYPE: dict[str, str] = {
    "image": "image",
    "table": "table",
    "caption": "caption",
    "heading": "heading",
    "paragraph": "paragraph",
    "formula": "paragraph",
}
_IMAGE_TYPES = {"image", "picture"}


def _box2d_to_odl_bbox(
    box_2d: Any,
    page_width: float,
    page_height: float,
) -> list[float] | None:
    """Gemini box_2d([ymin,xmin,ymax,xmax], 0-1000)를 ODL 트리 bbox로 환산.

    반환: [x_left, y_bottom, x_right, y_top] (PDF 포인트, 좌하단 원점, y_bottom < y_top).
    pymupdf 경로의 [x0, H - y1, x1, H - y0]와 동일한 변환을 정규화 좌표에 적용한 것.
    """
    if not isinstance(box_2d, (list, tuple)) or len(box_2d) != 4:
        return None
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box_2d)
    except (TypeError, ValueError):
        return None

    def _clamp(value: float) -> float:
        return max(0.0, min(1000.0, value))

    xmin, xmax = sorted((_clamp(xmin), _clamp(xmax)))
    ymin, ymax = sorted((_clamp(ymin), _clamp(ymax)))

    x_left = xmin / 1000.0 * page_width
    x_right = xmax / 1000.0 * page_width
    # top-left 원점의 세로 좌표를 좌하단 원점으로 뒤집는다.
    y_top = (1.0 - ymin / 1000.0) * page_height
    y_bottom = (1.0 - ymax / 1000.0) * page_height
    return [x_left, y_bottom, x_right, y_top]


def _parse_json(text: str) -> dict[str, Any]:
    """모델 응답에서 JSON 객체를 파싱. ```json 펜스가 있으면 벗겨낸다."""
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("parsed JSON is not an object")
    return data


def _assemble_page_nodes(
    data: dict[str, Any],
    page_number: int,
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    """페이지 응답을 ODL 트리 노드 리스트로 변환(id는 상위에서 순서대로 부여)."""
    nodes: list[dict[str, Any]] = []
    elements = data.get("elements")
    if not isinstance(elements, list):
        return nodes

    for element in elements:
        if not isinstance(element, dict):
            continue
        etype = str(element.get("type", "")).strip().lower()
        odl_type = _GEMINI_TO_ODL_TYPE.get(etype)
        if odl_type is None:
            continue
        bbox = _box2d_to_odl_bbox(element.get("box_2d"), page_width, page_height)
        if odl_type in _IMAGE_TYPES and bbox is None:
            # bbox 없는 이미지는 크롭 불가 — 노이즈이므로 버린다.
            continue
        text = str(element.get("text", "") or "")

        node: dict[str, Any] = {"type": odl_type, "page number": page_number}
        if bbox is not None:
            node["bbox"] = bbox
        if odl_type not in _IMAGE_TYPES:
            node["content"] = text
        nodes.append(node)
    return nodes


async def _render_page_png(pdf_path: Path, page_index: int, dpi: int) -> tuple[str, float, float]:
    """페이지를 PNG로 렌더해 (base64, width_pt, height_pt) 반환. 페이지마다 독립 doc를
    열어 fitz 스레드 안전성을 보장한다(블로킹이라 기본 실행기 스레드에서 수행)."""

    def _work() -> tuple[str, float, float]:
        doc = fitz.open(str(pdf_path))
        try:
            page = doc[page_index]
            width = float(page.rect.width)
            height = float(page.rect.height)
            matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png_b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
            return png_b64, width, height
        finally:
            doc.close()

    return await asyncio.get_running_loop().run_in_executor(None, _work)


async def _call_page(png_b64: str, model: str) -> dict[str, Any]:
    """한 페이지에 대한 비전 호출. 파싱된 JSON dict + usage를 담아 반환."""
    result = await call_interaction(
        [
            {"type": "image", "data": png_b64, "mime_type": "image/png"},
            {"type": "text", "text": _PAGE_PROMPT},
        ],
        lane="pipeline",
        model=model,
        system_instruction=_PARSER_SYSTEM_INSTRUCTION,
        thinking_level=_THINKING_LEVEL,
        store=False,
        response_schema=_PAGE_RESPONSE_SCHEMA,
    )
    data = _parse_json(result.get("text", ""))
    tokens_in = int(result.get("tokens_in", 0) or 0)
    tokens_out = int(result.get("tokens_out", 0) or 0)
    tokens_thought = int(result.get("tokens_thought", 0) or 0)
    used_model = result.get("model", model)
    data["_usage"] = {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_thought": tokens_thought,
        "cost_usd": calc_cost(used_model, tokens_in, tokens_out),
        "model": used_model,
    }
    return data


async def _process_page(
    pdf_path: Path,
    page_index: int,
    page_sem: asyncio.Semaphore,
    model: str,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """페이지 하나를 렌더 -> 호출 -> 조립. 실패 시 _PAGE_RETRIES회 재시도 후 예외."""
    async with page_sem:
        png_b64, width, height = await _render_page_png(pdf_path, page_index, RENDER_DPI)
        last_err: Exception | None = None
        for attempt in range(_PAGE_RETRIES + 1):
            try:
                data = await _call_page(png_b64, model)
                nodes = _assemble_page_nodes(data, page_index + 1, width, height)
                page_markdown = str(data.get("markdown", "") or "")
                usage = data.get("_usage", {})
                return nodes, page_markdown, usage
            except Exception as exc:  # noqa: BLE001 - 재시도 후 재던짐
                last_err = exc
                logger.warning(
                    "Gemini parser page %d attempt %d failed: %s",
                    page_index + 1,
                    attempt + 1,
                    exc,
                )
        raise GeminiParserError(f"page {page_index + 1} failed after retry: {last_err}")


def _open_metadata(pdf_path: Path) -> tuple[int, str | None, str | None]:
    doc = fitz.open(str(pdf_path))
    try:
        meta = doc.metadata or {}
        return len(doc), meta.get("title") or None, meta.get("author") or None
    finally:
        doc.close()


async def run_convert_gemini(
    pdf_path: Path,
    output_dir: Path,
    figures_dir: Path,
    *,
    usage_out: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Gemini 비전 엔진으로 PDF를 파싱해 ODL 호환 (root_json, markdown_text, "gemini") 반환.

    output_dir / figures_dir는 ODL 계약과의 시그니처 정합을 위해 받되, 이 엔진은 산출물을
    디스크에 직접 쓰지 않는다(트리와 마크다운을 메모리로 반환하고 하류가 저장한다).

    usage_out이 주어지면 토큰/비용 집계를 채운다(파일럿 스크립트 소비용). 반환 트리 계약은
    3-tuple 그대로 두고, 사용량은 이 out-param 별도 채널로만 노출한다.
    """
    pdf_path = Path(pdf_path)
    loop = asyncio.get_running_loop()
    page_count, meta_title, meta_author = await loop.run_in_executor(
        None, _open_metadata, pdf_path
    )
    if page_count <= 0:
        raise GeminiParserError(f"PDF has no pages: {pdf_path}")

    page_sem = asyncio.Semaphore(PAGE_CONCURRENCY)
    tasks = [
        _process_page(pdf_path, page_index, page_sem, MODEL_VISUAL)
        for page_index in range(page_count)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = [item for item in results if isinstance(item, BaseException)]
    if errors:
        raise GeminiParserError(
            f"{len(errors)}/{page_count} page(s) failed; first error: {errors[0]}"
        )

    kids: list[dict[str, Any]] = []
    page_markdowns: list[str] = []
    totals = {"tokens_in": 0, "tokens_out": 0, "tokens_thought": 0, "cost_usd": 0.0}
    element_id = 0
    for page_index in range(page_count):
        nodes, page_markdown, usage = results[page_index]  # type: ignore[misc]
        for node in nodes:
            node["id"] = element_id
            element_id += 1
            kids.append(node)
        page_markdowns.append(page_markdown)
        totals["tokens_in"] += int(usage.get("tokens_in", 0) or 0)
        totals["tokens_out"] += int(usage.get("tokens_out", 0) or 0)
        totals["tokens_thought"] += int(usage.get("tokens_thought", 0) or 0)
        totals["cost_usd"] += float(usage.get("cost_usd", 0.0) or 0.0)

    root: dict[str, Any] = {
        "title": meta_title,
        "author": meta_author,
        "number of pages": page_count,
        "kids": kids,
    }
    markdown_text = "\n\n".join(md for md in page_markdowns if md).strip()

    if usage_out is not None:
        usage_out.update(
            {
                "engine": GEMINI_ENGINE_NAME,
                "model": MODEL_VISUAL,
                "pages": page_count,
                "tokens_in": totals["tokens_in"],
                "tokens_out": totals["tokens_out"],
                "tokens_thought": totals["tokens_thought"],
                "cost_usd": round(totals["cost_usd"], 8),
            }
        )

    return root, markdown_text, GEMINI_ENGINE_NAME
