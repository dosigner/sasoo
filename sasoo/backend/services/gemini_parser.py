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
import os
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from services.llm.interactions_client import call_interaction
from services.models import MODEL_VISUAL
from services.pricing import calc_cost

logger = logging.getLogger(__name__)

GEMINI_ENGINE_NAME = "gemini"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("invalid %s=%r; falling back to %d", name, raw, default)
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip()


# --- 비용 튜닝 레버(모두 env 오버라이드 가능; 기본값 = 튜닝 후 권장값) ---
# 베이스라인 재현:
#   SASOO_GEMINI_PARSER_DPI=180 SASOO_GEMINI_PARSER_THINKING=low \
#   SASOO_GEMINI_PARSER_MEDIA_RESOLUTION= SASOO_GEMINI_PARSER_ELEMENTS=full
RENDER_DPI = _env_int("SASOO_GEMINI_PARSER_DPI", 150)  # 페이지 래스터화 해상도(하향: 150)
PAGE_CONCURRENCY = _env_int("SASOO_GEMINI_PARSER_PAGE_CONCURRENCY", 4)
_PAGE_RETRIES = 1              # 페이지 호출 실패 시 추가 재시도 횟수(총 2회 시도)
# thinking 토큰은 출력 단가로 과금됨. ThinkingLevel 허용값 minimal<low<medium<high 중 최저치.
_THINKING_LEVEL = _env_str("SASOO_GEMINI_PARSER_THINKING", "minimal")
# 이미지 파트별 media_resolution(low/medium/high/ultra_high). 빈 문자열이면 미지정(SDK 기본).
# 저해상일수록 이미지 입력 토큰이 줄지만 작은 수식/캡션 OCR이 깨질 수 있다 — DPI와 함께 조절.
_MEDIA_RESOLUTION = _env_str("SASOO_GEMINI_PARSER_MEDIA_RESOLUTION", "low")
# elements 스키마 모드: "slim"(기본, 시각요소+heading만) | "full"(베이스라인, paragraph/formula 포함).
# slim은 markdown과 중복되는 paragraph/formula 본문 출력을 없애 출력 토큰을 줄인다.
_ELEMENTS_SLIM = _env_str("SASOO_GEMINI_PARSER_ELEMENTS", "slim").lower() != "full"

# 기본 system_instruction은 모든 value를 한국어로 강제한다(interactions_client). 파서는
# 원문을 그대로 옮겨야 하므로 전용 지시로 덮어써 번역/요약을 막는다.
_PARSER_SYSTEM_INSTRUCTION_SLIM = (
    "You are a precise PDF parser. Transcribe verbatim in the original language; "
    "never translate or summarize. Output only valid JSON matching the schema."
)
_PARSER_SYSTEM_INSTRUCTION_FULL = (
    "You are a precise PDF document parser. Transcribe the page content verbatim in the "
    "document's original language. Never translate, summarize, paraphrase, or add commentary. "
    "Output only valid JSON that matches the requested schema."
)
_PARSER_SYSTEM_INSTRUCTION = (
    _PARSER_SYSTEM_INSTRUCTION_SLIM if _ELEMENTS_SLIM else _PARSER_SYSTEM_INSTRUCTION_FULL
)

_ELEMENT_TYPES_SLIM = ["image", "table", "caption", "heading"]
_ELEMENT_TYPES_FULL = ["image", "table", "caption", "heading", "paragraph", "formula"]


def _build_page_schema(element_types: list[str]) -> dict[str, Any]:
    # box_2d는 [ymin, xmin, ymax, xmax] 0-1000 정규화 — Gemini 공식 규약.
    return {
        "type": "object",
        "properties": {
            "markdown": {"type": "string"},
            "elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": list(element_types)},
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


_PAGE_RESPONSE_SCHEMA: dict[str, Any] = _build_page_schema(
    _ELEMENT_TYPES_SLIM if _ELEMENTS_SLIM else _ELEMENT_TYPES_FULL
)

# slim: 본문은 markdown이 전담(중복 제거). elements는 시각요소+heading만.
_PAGE_PROMPT_SLIM = (
    "Parse this scientific-paper page image into JSON with two fields.\n"
    "\n"
    "\"markdown\": the ENTIRE page as Markdown in reading order. Tables as GitHub-flavored "
    "Markdown; math as LaTeX ($...$ inline, $$...$$ display); at each figure put one line "
    "![Figure N](placeholder). Transcribe verbatim in the original language; never translate.\n"
    "\n"
    "\"elements\": visual blocks only — figures, tables, captions, headings. For each give "
    "\"type\" (image|table|caption|heading), \"box_2d\" [ymin,xmin,ymax,xmax] normalized 0-1000 "
    "with TOP-LEFT origin (tightest enclosing box), and \"text\" (caption/heading verbatim text; "
    "table as Markdown; image empty \"\").\n"
    "\n"
    "Rules: every figure/chart/photo/diagram is an \"image\" element with box_2d. Each figure or "
    "table caption (\"Figure 3: ...\", \"Table 2: ...\") is a separate \"caption\" element starting "
    "with its label. Do NOT emit paragraph or formula elements — body text lives only in markdown. "
    "Output JSON only."
)
_PAGE_PROMPT_FULL = (
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
_PAGE_PROMPT = _PAGE_PROMPT_SLIM if _ELEMENTS_SLIM else _PAGE_PROMPT_FULL


class GeminiParserError(RuntimeError):
    """Gemini 파서 엔진 실패. odl_parser 디스패처가 OdlParserError로 변환해 폴백을 유도한다."""


# Gemini element type -> ODL 트리 type 매핑.
# slim 모드에선 paragraph/formula를 방출하지 않으므로(본문은 markdown 전담) 매핑에서 뺀다.
# full 모드는 baseline 재현용 — formula는 ODL TEXTUAL_TYPES에 없어 매니페스트에서
# 탈락하므로 paragraph로 보존한다.
_GEMINI_TO_ODL_TYPE_FULL: dict[str, str] = {
    "image": "image",
    "table": "table",
    "caption": "caption",
    "heading": "heading",
    "paragraph": "paragraph",
    "formula": "paragraph",
}
_GEMINI_TO_ODL_TYPE_SLIM: dict[str, str] = {
    "image": "image",
    "table": "table",
    "caption": "caption",
    "heading": "heading",
}
_GEMINI_TO_ODL_TYPE = _GEMINI_TO_ODL_TYPE_SLIM if _ELEMENTS_SLIM else _GEMINI_TO_ODL_TYPE_FULL
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


async def _render_page_png(
    doc: "fitz.Document", page_index: int, dpi: int
) -> tuple[str, float, float]:
    """페이지를 PNG로 렌더해 (base64, width_pt, height_pt) 반환.

    F6: 페이지마다 fitz.open(전체 재파싱)하는 대신, 상위에서 오픈해 풀로 관리하는 doc를
    재사용한다. fitz.Document는 스레드/태스크 안전하지 않으므로 호출부(_process_page)가
    doc 풀에서 배타적으로 체크아웃한 doc만 넘긴다 — 동시에 두 태스크가 같은 doc를 만지지
    않는다. 렌더는 블로킹이라 기본 실행기 스레드에서 수행한다."""

    def _work() -> tuple[str, float, float]:
        page = doc[page_index]
        width = float(page.rect.width)
        height = float(page.rect.height)
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        png_b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
        return png_b64, width, height

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
        thinking_level=_THINKING_LEVEL or None,
        store=False,
        response_schema=_PAGE_RESPONSE_SCHEMA,
        media_resolution=_MEDIA_RESOLUTION or None,
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
    doc_pool: "asyncio.Queue[fitz.Document]",
    page_index: int,
    page_sem: asyncio.Semaphore,
    model: str,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """페이지 하나를 렌더 -> 호출 -> 조립. 실패 시 _PAGE_RETRIES회 재시도 후 예외.

    렌더는 doc_pool에서 doc를 배타적으로 체크아웃해 수행하고, 렌더가 끝나면 즉시 반납한다
    (긴 LLM 호출 동안 doc를 점유하지 않아 소수의 doc로 전 페이지를 커버한다 — F6)."""
    async with page_sem:
        doc = await doc_pool.get()
        try:
            png_b64, width, height = await _render_page_png(doc, page_index, RENDER_DPI)
        finally:
            doc_pool.put_nowait(doc)
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
    # F1: fitz.open이 손상/암호화 PDF를 거부하면 raw fitz/RuntimeError가 새어나가
    # ensure_visual_artifacts의 폴백(except OdlParserError)을 우회한다. 엔진 계약대로
    # GeminiParserError로 감싸 폴백이 ODL 실패와 동일하게 동작하게 한다(원인 체이닝 유지).
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:  # noqa: BLE001 - 폴백 유도용으로 엔진 계약 예외로 변환
        raise GeminiParserError(f"failed to open PDF: {exc}") from exc
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
    # F6: 페이지마다 fitz.open하는 대신 doc를 PAGE_CONCURRENCY개(≤페이지 수)만 열어 풀로
    # 재사용한다. 각 doc는 _process_page가 렌더 동안만 배타 체크아웃하므로 동시 접근이 없다.
    pool_size = max(1, min(PAGE_CONCURRENCY, page_count))
    docs: list["fitz.Document"] = await loop.run_in_executor(
        None, lambda: [fitz.open(str(pdf_path)) for _ in range(pool_size)]
    )
    doc_pool: "asyncio.Queue[fitz.Document]" = asyncio.Queue()
    for _doc in docs:
        doc_pool.put_nowait(_doc)

    try:
        # F5: 시스템성 오류(bad key/쿼터 소진 등) fail-fast. 페이지 1을 먼저 단독 시도하고,
        # 실패하면 나머지 페이지를 팬아웃하지 않고 즉시 중단한다(28p 논문에서 N×2회 헛호출을
        # 페이지 1의 2회로 축소). 페이지 1이 성공해야만 나머지를 병렬 fan-out한다.
        first = await _process_page(doc_pool, 0, page_sem, MODEL_VISUAL)  # 실패 시 GeminiParserError 전파
        results: list[Any] = [first]
        if page_count > 1:
            rest = await asyncio.gather(
                *[
                    _process_page(doc_pool, page_index, page_sem, MODEL_VISUAL)
                    for page_index in range(1, page_count)
                ],
                return_exceptions=True,
            )
            results.extend(rest)
    finally:
        await loop.run_in_executor(None, lambda: [d.close() for d in docs])

    # F2: 성공 페이지는 이미 API에 과금됐다. 부분 실패로 문서를 중단(raise)하더라도 그 시점까지의
    # 실제 지출이 원장에 남도록, totals를 raise 이전에 계산해 usage_out에 반영한다.
    kids: list[dict[str, Any]] = []
    page_markdowns: list[str] = []
    totals = {"tokens_in": 0, "tokens_out": 0, "tokens_thought": 0, "cost_usd": 0.0}
    element_id = 0
    success_pages = 0
    errors: list[BaseException] = []
    for page_index in range(page_count):
        item = results[page_index]
        if isinstance(item, BaseException):
            errors.append(item)
            continue
        nodes, page_markdown, usage = item
        success_pages += 1
        for node in nodes:
            node["id"] = element_id
            element_id += 1
            kids.append(node)
        page_markdowns.append(page_markdown)
        totals["tokens_in"] += int(usage.get("tokens_in", 0) or 0)
        totals["tokens_out"] += int(usage.get("tokens_out", 0) or 0)
        totals["tokens_thought"] += int(usage.get("tokens_thought", 0) or 0)
        totals["cost_usd"] += float(usage.get("cost_usd", 0.0) or 0.0)

    if usage_out is not None:
        # 성공/부분실패 공통으로 실제 지출을 반영한다. pages는 실제 성공(=과금)한 페이지 수.
        usage_out.update(
            {
                "engine": GEMINI_ENGINE_NAME,
                "model": MODEL_VISUAL,
                "pages": success_pages,
                "tokens_in": totals["tokens_in"],
                "tokens_out": totals["tokens_out"],
                "tokens_thought": totals["tokens_thought"],
                "cost_usd": round(totals["cost_usd"], 8),
                "partial": bool(errors),
            }
        )

    if errors:
        raise GeminiParserError(
            f"{len(errors)}/{page_count} page(s) failed; first error: {errors[0]}"
        )

    root: dict[str, Any] = {
        "title": meta_title,
        "author": meta_author,
        "number of pages": page_count,
        "kids": kids,
    }
    # 페이지 경계에 "--- Page N ---" 마커를 넣는다(ODL _build_plain_text full_text 포맷과 정합).
    # slim 모드에서 이 markdown이 manifest full_text로 채택되면(document_manifest의 gemini 분기)
    # document_audit._page_text_map의 페이지별 텍스트 분리가 그대로 동작한다.
    markdown_parts: list[str] = []
    for page_index, md in enumerate(page_markdowns):
        if not md:
            continue
        markdown_parts.append(f"--- Page {page_index + 1} ---\n\n{md}")
    markdown_text = "\n\n".join(markdown_parts).strip()

    # usage_out은 위(raise 이전)에서 이미 성공 페이지 기준으로 채워졌다(F2). 여기서 다시
    # 쓰지 않는다 — 성공 경로에선 success_pages == page_count라 값이 동일하다.
    return root, markdown_text, GEMINI_ENGINE_NAME
