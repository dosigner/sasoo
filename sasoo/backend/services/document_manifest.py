"""
Resolver v1 document-manifest builder.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
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


_JOURNAL_NATURE_HEADER_PATTERN = re.compile(r"et al\.\s+(.+?)\s+\(\d{4}\)\s+\d+")
_JOURNAL_ALLCAPS_HEADER_PATTERN = re.compile(r"(?:^|\n)\s*([A-Z][A-Z ]{6,80}?),?\s*VOL\.\s*\d+")
_JOURNAL_NAMED_PATTERN = re.compile(
    r"(?:Published in|Journal of|Proceedings of)\s+(.+?)(?:,\s*(?:Vol|No)\.|[.\n])",
    re.IGNORECASE,
)


def resolve_paper_journal(text: str) -> str | None:
    """첫 페이지 텍스트에서 저널/컨퍼런스 러닝 헤더를 찾아 저널명을 추출한다.

    표지·소속기관 문구 안에서 "Nature", "Optics", "IEEE" 같은 단어 하나만 보고
    맞장구치던 옛 키워드-매칭 방식은 소속기관 문구("Institute for Quantum
    Optics...")나 URL("www.nature.com/scientificreports"), 논문 제목 자체를
    저널명으로 오인했다. 이 함수는 실제 학술지 러닝 헤더 구조(Nature 계열
    "et al. <저널명> (연도) 권:쪽", IEEE/JLT 계열 "<저널명>, VOL. n", OSA/Optica
    계열 "Vol. n, No. n / 날짜 / 저널명")에만 매칭해 오탐을 없앤다. 어떤 구조에도
    맞지 않으면 단정하지 않고 None을 반환한다(불확실하면 비워두는 게 틀린 값을
    보여주는 것보다 낫다).
    """
    candidates: list[str] = []

    m = _JOURNAL_NATURE_HEADER_PATTERN.search(text)
    if m:
        candidates.append(m.group(1))

    m = _JOURNAL_ALLCAPS_HEADER_PATTERN.search(text)
    if m:
        candidates.append(m.group(1))

    for line in text.splitlines():
        if "Vol." in line and "No." in line and "/" in line:
            segments = [s.strip() for s in line.split("/")]
            if len(segments) >= 2:
                tail = segments[-1]
                if re.search(r"[^\W\d_]", tail) and len(tail) < 60:
                    candidates.append(tail)
            break

    m = _JOURNAL_NAMED_PATTERN.search(text)
    if m:
        candidates.append(m.group(1))

    for candidate in candidates:
        cleaned = re.sub(r"\s{2,}", " ", candidate).strip(" ,.;")
        if len(cleaned) < 3:
            continue
        if not re.search(r"[^\W\d_]", cleaned):
            continue
        if AFFILIATION_PATTERN.search(cleaned):
            continue
        return cleaned[:100]
    return None


def _clean_author_text(text: str) -> str:
    cleaned = EMAIL_PATTERN.sub("", text)
    cleaned = re.sub(r"[\*\d†‡§¶]+", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip(" ,;")
    # "[]", "()" 같은 문자 없는 플레이스홀더는 저자명이 아니다.
    return cleaned if re.search(r"[^\W\d_]", cleaned) else ""


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

    journal = resolve_paper_journal(full_text[:2000])

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


# 캡션 앞에 붙는 마크다운 서식·장식 문자. gemini 파서는 캡션을 마크다운 그대로 내보내므로
# "**Fig. 1. ...**"처럼 볼드로 시작하는 경우가 흔하다.
_CAPTION_LEADING_NOISE = re.compile(r"^[\s*_#>`~\-–—•]+")


def strip_caption_decoration(text: str | None) -> str:
    """캡션 앞의 마크다운 서식·장식 문자를 벗긴다.

    라벨 패턴(FIGURE_LABEL_PATTERN 등)은 전부 문두 매칭이라, 앞에 "**"가 하나만 붙어도
    캡션 판정·그림 번호 부여가 동시에 실패한다. 캡션을 라벨로 해석하는 모든 지점이
    이 함수를 거치게 해서 한 곳에서만 규칙을 관리한다.
    """
    return _CAPTION_LEADING_NOISE.sub("", text or "")


# "Fig. 2(e) shows ..." 처럼 라벨 뒤에 붙는 서브피겨 지시자. 본문/캡션 판정에서는 건너뛴다.
_CAPTION_SUBLABEL_PATTERN = re.compile(r"^\s*\([0-9a-z]{1,3}\)", re.IGNORECASE)

# 라벨과 캡션 본문을 잇는 구분자.
_CAPTION_LABEL_SEPARATORS = ".:,;)]|–—-"


def _label_is_followed_by_caption_body(rest: str) -> bool:
    """라벨 뒤에 오는 텍스트가 캡션 본문인지, 그냥 이어지는 본문 문장인지 판정한다.

    "Fig. N"으로 시작하기만 하면 캡션으로 인정하면 본문 첫 문장이 캡션 블록이 되고,
    같은 번호의 그림 후보가 하나 더 생겨 "Fig. 9"와 "Fig. 9 [2]"가 함께 나온다.
    실측 초과분(2013_IEEETIP +1, 2022_SciRep +1, 2022_ApplOpt +3)이 전부 이 케이스였다.

    가르는 신호는 라벨 바로 뒤 한 글자다.
      캡션 : "Fig. 1. Given a ..."  "Figure 1: Error ..."  "Fig. 2 Subharmonic Phase ..."
      본문 : "Fig. 1 illustrates ..."  "Figure 9 shows ..."  "Fig. 2(e) shows ..."
    구분자나 대문자/숫자로 이어지면 캡션, 소문자 단어(= 서술 동사)로 이어지면 본문 문장이다.
    구분자를 무조건 요구하면 안 된다 — "Fig. 2 Subharmonic ..."처럼 구분자 없는 캡션이
    실제로 있고(TurPy_OpticTurb), 그런 논문의 그림이 통째로 사라진다.
    """
    sublabel = _CAPTION_SUBLABEL_PATTERN.match(rest)
    if sublabel:
        rest = rest[sublabel.end() :]
    stripped = rest.strip()
    if not stripped:
        # 라벨만 있는 줄. 캡션 본문이 다음 블록으로 넘어간 형태이므로 캡션으로 본다.
        return True
    if stripped[0] in _CAPTION_LABEL_SEPARATORS:
        return True
    return not stripped[0].islower()


def _caption_kind(text: str) -> str | None:
    # 라벨 패턴은 문두 매칭이라, 앞에 "**"가 하나만 붙어도 캡션으로 인식되지 않는다.
    # 그러면 그 문서는 figure 캡션이 0개가 되고, 캡션에 기대는 하류 로직(후보-캡션 연결,
    # 캡션 폴백, 캡션 없는 후보 억제)이 통째로 무력화된다 — 실측: 캡션 6개가 전부
    # "unknown"으로 떨어져 그림이 원문 8개 대비 17개까지 부풀었다.
    #
    # NFKC 정규화는 "Figure\xa01."처럼 non-breaking space가 낀 표기(2022_SciRep) 때문에
    # 필요하다. 라벨 뒤 구분자 판정이 공백 종류에 흔들리면 안 된다.
    normalized = unicodedata.normalize("NFKC", strip_caption_decoration(text))
    figure_match = FIGURE_LABEL_PATTERN.match(normalized)
    if figure_match:
        return "figure" if _label_is_followed_by_caption_body(normalized[figure_match.end() :]) else None
    table_match = TABLE_LABEL_PATTERN.match(normalized)
    if table_match:
        return "table" if _label_is_followed_by_caption_body(normalized[table_match.end() :]) else None
    return None


def _caption_label_key(text: str) -> str | None:
    """캡션 텍스트에서 중복 판정용 라벨 키를 뽑는다("**Fig. 3. ...**" -> "figure:3")."""
    normalized = unicodedata.normalize("NFKC", strip_caption_decoration(text))
    figure_match = FIGURE_LABEL_PATTERN.match(normalized)
    if figure_match:
        return f"figure:{figure_match.group(1).lower()}"
    table_match = TABLE_LABEL_PATTERN.match(normalized)
    if table_match:
        return f"table:{table_match.group(1).lower()}"
    return None


def recover_missing_caption_blocks(
    *,
    pdf_path: Path,
    pages: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """파서가 빠뜨린 캡션을 PDF 텍스트에서 되살려 페이지에 채워 넣고, 추가분을 반환한다.

    실측(2026_SR_AgileMultiskill): gemini가 p6·p9에서 caption/image 요소를 하나도 내지
    않아 Fig. 3과 Fig. 5가 통째로 사라졌다. 두 캡션 모두 같은 응답의 markdown에는 온전히
    들어 있었으니 프롬프트가 아니라 elements 방출이 확률적으로 누락된 것이고, 프롬프트를
    더 강하게 써도 재발을 막을 보장이 없다. 캡션 없는 후보는 버리는 규칙(2026-07-29 결정)
    때문에 캡션 하나가 빠지면 그 그림이 곧바로 소실된다.

    캡션 텍스트 자체는 PDF 안에 결정적으로 존재하므로 PyMuPDF 텍스트 블록에서 되살린다.
    이미 파서가 같은 라벨을 잡은 페이지는 건드리지 않는다 — 중복 캡션은 같은 그림의 후보를
    하나 더 만들어 "Fig. 1"과 "Fig. 1 [2]"가 함께 나오게 한다.
    """
    recovered: list[dict[str, Any]] = []
    doc = fitz.open(str(pdf_path))
    try:
        for page_number, page_entry in pages.items():
            page_index = page_number - 1
            if page_index < 0 or page_index >= len(doc):
                continue
            caption_blocks = page_entry.get("caption_blocks")
            if caption_blocks is None:
                continue
            # 라벨 점유는 "진짜 캡션으로 인정된" 블록만 한다. 본문 언급("Fig. 9 shows ...")이
            # 캡션 블록으로 남아 있는 페이지에서 진짜 캡션 복원이 막히면 안 된다.
            seen_labels = {
                key
                for key in (
                    _caption_label_key(text)
                    for text in (str(block.get("text") or "") for block in caption_blocks)
                    if _caption_kind(text) is not None
                )
                if key
            }
            page = doc[page_index]
            page_height = float(page.rect.height)
            max_order = max(
                (int(block.get("order") or 0) for block in caption_blocks),
                default=0,
            )
            # get_text("blocks")는 dict 모드와 달리 span 트리를 만들지 않는다. 여기서 필요한
            # 건 블록 단위 (bbox, 텍스트)뿐이라 문서 파싱 비용이 한 자릿수 ms로 떨어진다.
            for index, block in enumerate(page.get_text("blocks")):
                if len(block) < 7 or block[6] != 0:  # block_type 0 == 텍스트
                    continue
                # 블록 텍스트는 줄바꿈을 품고 있다. 캡션은 한 줄로 다뤄지므로 공백을 정규화한다.
                text = re.sub(r"\s+", " ", str(block[4] or "")).strip()
                if not text:
                    continue
                kind = _caption_kind(text)
                if kind is None:
                    continue
                label_key = _caption_label_key(text)
                if label_key is None or label_key in seen_labels:
                    continue
                x0, y0, x1, y1 = (float(value) for value in block[:4])
                seen_labels.add(label_key)
                max_order += 1
                caption_block = {
                    # 파서가 낸 캡션(cap:pN:nM)과 구분되게 r 접두를 쓴다.
                    "id": f"cap:p{page_number}:r{index}",
                    "page_number": page_number,
                    # 매니페스트 bbox 규약은 좌하단 원점 — PyMuPDF의 좌상단 y를 뒤집는다.
                    "bbox": [x0, page_height - y1, x1, page_height - y0],
                    "text": text,
                    "kind": kind,
                    "linked_content_id": None,
                    "source_id": None,
                    "order": max_order,
                    "recovered_from": "pymupdf_text",
                }
                caption_blocks.append(caption_block)
                recovered.append(caption_block)
    finally:
        doc.close()
    return recovered


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

        # 코드리뷰 F4(주의): gemini slim 스키마의 트리에는 본문 paragraph가 없어(heading/caption만)
        # per-page text_blocks가 본문을 담지 못한다. 본문 계약은 full_text(=markdown, 위 gemini 분기)로
        # 보전되고, {stem}.json 텍스트 루트는 odl_parser._manifest_to_text_root가 full_text를 페이지별로
        # 복원해 채운다. text_blocks 기반의 caption-band 텍스트 확장(figure_candidates)만 slim에서 비활성.
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

    # 파서가 캡션 요소를 통째로 빠뜨린 페이지를 PDF 텍스트로 메운다. 캡션 없는 후보는
    # 버리는 규칙 때문에, 캡션 하나가 빠지면 그 그림이 그대로 소실된다.
    captions.extend(recover_missing_caption_blocks(pdf_path=pdf_path, pages=pages))

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
        # gemini 파서가 일부 페이지를 못 읽고 PyMuPDF 텍스트로 메운 경우 그 페이지 번호들.
        # 해당 페이지엔 caption/image 요소가 없으므로 하류가 aggressive 후보 재생성으로 덮는다.
        "parser_failed_pages": [
            page for page in (root.get("parser_failed_pages") or []) if isinstance(page, int)
        ],
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
