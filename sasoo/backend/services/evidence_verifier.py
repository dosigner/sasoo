"""evidence_verifier — Recipe 파라미터 근거의 결정론적 검증기.

원칙(docs/superpowers/specs/2026-08-06-evidence-anchoring-design.md):
- LLM 후보를 다른 LLM 전사본으로 확인하지 않는다. 대조 원본은 PDF 텍스트층뿐이다.
- 유사도·편집거리·임베딩을 검증에 쓰지 않는다. 실측상 숫자 한 자리를 바꾼 위조 인용이
  임계 0.6에서 81.1%, 0.8에서도 52.0% 통과한다. 정규화 완전일치만 0.0%다.
- partial_match는 탐색 보조일 뿐 검증이 아니다.
- 상태는 직교 3필드(quote/page/value)로 저장하고 표시 상태 1개를 결정론 규칙으로 파생한다.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import fitz

EVIDENCE_VERIFIER_VERSION = "ev1"
EVIDENCE_NORMALIZER_VERSION = "norm-v1"
EVIDENCE_CORPUS_PDF_TEXT = "pdf_text"

QUOTE_STATUSES = frozenset(
    {
        "verified_exact",
        "verified_normalized",
        "partial_match",
        "not_found",
        "no_quote",
        "no_text_layer",
        "ambiguous",
        "stale_source",
        "verifier_error",
    }
)
PAGE_STATUSES = frozenset({"match", "mismatch", "invalid_page", "no_page", "derived"})
VALUE_STATUSES = frozenset({"value_in_quote", "value_missing", "inferred", "not_applicable"})

# ---------------------------------------------------------------------------
# normalizer-v1
# ---------------------------------------------------------------------------
# 스펙의 규칙 순서: NFKC → 소문자 → 대시 통일 → 리거처 해제 → 줄바꿈 하이픈 결합 →
# 공백 축약 → 스마트 따옴표 통일.
# 스펙에 없지만 추가한 0단계: 제로폭/소프트하이픈 제거. 소프트하이픈(U+00AD)은 NFKC가
# 제거하지 않는데, 이걸 남기면 줄바꿈 하이픈 결합이 소프트하이픈 케이스를 놓친다.
# (표기 정규화일 뿐 수치 의미를 바꾸지 않으므로 스펙과 충돌하지 않는다.)

_STRIP_CHARS = frozenset("­​‌‍﻿")
_DASHES = frozenset("‐‑‒–—―−")
_SINGLE_QUOTES = frozenset("‘’‚‛′")
_DOUBLE_QUOTES = frozenset("“”„‟″")
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """정규화 문자열과 '정규화 문자 i → 원문 인덱스' 맵을 함께 반환한다.

    맵이 있어야 정규화 매치 구간을 원문 span으로 되돌릴 수 있고, 그 원문 span을
    PyMuPDF page.search_for에 그대로 넘겨 bbox를 얻을 수 있다.
    """
    text = str(text or "")

    # 0~4단계: 문자 단위가 아니라 "베이스 문자 + 뒤따르는 결합 문자(combining mark)"
    # 클러스터 단위로 치환한다. 코드포인트 단위 NFKC는 NFD로 분해된 결합 시퀀스
    # (예: "e" + U+0301)를 재합성하지 못해, 같은 실제 텍스트가 유니코드 표현 형태만
    # 달라도(NFC vs NFD) 정규화 결과가 갈리는 false negative를 낳는다(리뷰 지적).
    # 클러스터를 통째로 NFKC에 넣어야 결합 문자가 베이스와 재합성된다.
    n = len(text)
    clusters: list[tuple[str, int]] = []  # (클러스터 원문, 클러스터 시작 인덱스)
    i = 0
    while i < n:
        start = i
        i += 1
        while i < n and unicodedata.category(text[i])[0] == "M":
            i += 1
        clusters.append((text[start:i], start))

    pairs: list[tuple[str, int]] = []
    for cluster_text, index in clusters:
        if len(cluster_text) == 1:
            char = cluster_text
            if char in _STRIP_CHARS:
                continue
            if char in _DASHES:
                folded = "-"
            elif char in _SINGLE_QUOTES:
                folded = "'"
            elif char in _DOUBLE_QUOTES:
                folded = '"'
            elif char in _LIGATURES:
                folded = _LIGATURES[char]
            else:
                folded = unicodedata.normalize("NFKC", char).casefold()
        else:
            # 베이스+결합문자 클러스터: 특수 치환 대상이 아니므로 통째로 NFKC+casefold.
            folded = unicodedata.normalize("NFKC", cluster_text).casefold()
        for out_char in folded:
            pairs.append((out_char, index))

    # 5단계: 줄바꿈 하이픈 결합 — '-' + (공백) + '\n' + (공백)을 통째로 제거한다.
    joined: list[tuple[str, int]] = []
    total = len(pairs)
    cursor = 0
    while cursor < total:
        char, source = pairs[cursor]
        if char == "-":
            probe = cursor + 1
            while probe < total and pairs[probe][0] in " \t\r":
                probe += 1
            if probe < total and pairs[probe][0] == "\n":
                probe += 1
                while probe < total and pairs[probe][0].isspace():
                    probe += 1
                cursor = probe
                continue
        joined.append((char, source))
        cursor += 1

    # 6단계: 공백류 연속 → 스페이스 1개, 양끝 strip.
    collapsed: list[tuple[str, int]] = []
    previous_was_space = True  # 선행 공백 제거
    for char, source in joined:
        if char.isspace():
            if previous_was_space:
                continue
            collapsed.append((" ", source))
            previous_was_space = True
        else:
            collapsed.append((char, source))
            previous_was_space = False
    while collapsed and collapsed[-1][0] == " ":
        collapsed.pop()

    return "".join(char for char, _ in collapsed), [source for _, source in collapsed]


def normalize_text(text: str) -> str:
    return normalize_with_map(text)[0]


# ---------------------------------------------------------------------------
# 파라미터 ↔ 앵커 결속 키
# ---------------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^0-9a-z가-힣]+")


def slugify_target(name: str) -> str:
    folded = unicodedata.normalize("NFKC", str(name or "")).casefold()
    slug = _SLUG_STRIP.sub("-", folded).strip("-")
    return (slug or "unnamed")[:48]


def build_target_key(index: int, name: str) -> str:
    return f"p{int(index):03d}:{slugify_target(name)}"


# ---------------------------------------------------------------------------
# 표시 상태 파생
# ---------------------------------------------------------------------------

_DISPLAY_BY_QUOTE_STATUS = {
    "verifier_error": "UNVERIFIED_ERROR",
    "no_text_layer": "UNVERIFIED_NO_TEXT_LAYER",
    "stale_source": "UNVERIFIED_STALE_SOURCE",
    "no_quote": "UNVERIFIED_NO_QUOTE",
    "ambiguous": "UNVERIFIED_AMBIGUOUS",
    "not_found": "UNVERIFIED_NOT_FOUND",
    "partial_match": "UNVERIFIED_PARTIAL",
}


def derive_display_status(quote_status: str, page_status: str, value_status: str) -> str:
    """VERIFIED는 세 필드가 전부 통과할 때만 나온다 — 조용한 승격 금지의 마지막 방어선."""
    mapped = _DISPLAY_BY_QUOTE_STATUS.get(quote_status)
    if mapped is not None:
        return mapped
    if quote_status not in {"verified_exact", "verified_normalized"}:
        return "UNVERIFIED_ERROR"  # 알 수 없는 상태는 절대 승격하지 않는다
    if page_status not in {"match", "derived"}:
        return "UNVERIFIED_PAGE_MISMATCH"
    if value_status == "inferred":
        return "UNVERIFIED_INFERRED"
    if value_status != "value_in_quote":
        return "UNVERIFIED_VALUE_MISMATCH"
    return "VERIFIED"


# ---------------------------------------------------------------------------
# 값 가드
# ---------------------------------------------------------------------------

_NUMBER_LITERAL = re.compile(r"(?<!\d)-?\d+(?:\.\d+)?")


def _number_boundary_match(needle: str, haystack: str) -> bool:
    """숫자 needle이 haystack 안에서 더 긴 숫자의 부분문자열로 우연히 걸리지 않게 한다.

    "50"이 "1550"의 substring이라는 이유만으로 매치되면 안 된다(리뷰 지적 Critical #1).
    needle에 부호가 포함돼 있으면(예: "-40") 그 "-"까지 패턴에 들어가므로, quote 쪽에
    부호 없는 숫자만 있는 경우("40")는 이 경계 검사에서 자연히 걸러진다(리뷰 지적
    Critical #2 — 부호가 quote에 실제로 없으면 값이 다른 것이므로 불일치가 맞다).
    """
    pattern = rf"(?<![\d.]){re.escape(needle)}(?![\d.])"
    return re.search(pattern, haystack) is not None


def check_value_in_quote(
    value: str, source_tag: str | None, matched_quote: str | None
) -> tuple[str, str | None]:
    """파라미터 값이 확인된 인용 안에 실제로 들어 있는지 본다.

    인용이 원문에 존재한다는 사실만으로는 그 파라미터를 뒷받침하지 못한다. explicit
    파라미터는 값(숫자, 없으면 값 리터럴)이 인용 안에 있어야 VERIFIED가 될 수 있다.
    inferred는 구조적으로 VERIFIED 불가다 — 계산식 검증 기능이 생기기 전까지.
    """
    if str(source_tag or "").strip().casefold() == "inferred":
        return ("inferred", None)

    normalized_value = normalize_text(value)
    if not normalized_value:
        return ("not_applicable", "empty_value")
    if not matched_quote:
        return ("value_missing", "no_matched_quote")

    normalized_quote = normalize_text(matched_quote)
    numbers = _NUMBER_LITERAL.findall(normalized_value)
    if numbers:
        for needle in numbers:
            if not _number_boundary_match(needle, normalized_quote):
                return ("value_missing", f"missing:{needle[:24]}")
        return ("value_in_quote", None)

    if normalized_value not in normalized_quote:
        return ("value_missing", f"missing:{normalized_value[:24]}")
    return ("value_in_quote", None)


# ---------------------------------------------------------------------------
# PDF 텍스트층 인덱스
# ---------------------------------------------------------------------------
# 대조 원본은 PDF 텍스트층 하나뿐이다. 매니페스트 full_text는 Gemini 경로에서 다른 LLM의
# 전사본일 수 있어(순환 검증) 쓰지 않는다. 실측: 축자 인용을 full_text로 대조하면 70.7%만
# 확인되고(ODL 83.0% / Gemini 33.6%), PDF 텍스트층으로 대조하면 91.4%가 확인된다.


@dataclass(frozen=True, slots=True)
class PageText:
    page_number: int
    raw: str
    normalized: str
    source_map: tuple[int, ...]
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PdfTextIndex:
    pages: tuple[PageText, ...]
    page_count: int

    @property
    def has_text_layer(self) -> bool:
        return any(page.normalized for page in self.pages)


@dataclass(frozen=True, slots=True)
class QuoteMatch:
    quote_status: str
    page_status: str
    matched_page: int | None = None
    matched_quote: str | None = None
    match_method: str | None = None
    match_ratio: float | None = None
    failure_detail: str | None = None


def _index_from_doc(doc) -> PdfTextIndex:
    pages: list[PageText] = []
    for number in range(1, doc.page_count + 1):
        raw = doc[number - 1].get_text() or ""
        normalized, source_map = normalize_with_map(raw)
        pages.append(
            PageText(
                page_number=number,
                raw=raw,
                normalized=normalized,
                source_map=tuple(source_map),
                tokens=tuple(normalized.split(" ")) if normalized else (),
            )
        )
    return PdfTextIndex(pages=tuple(pages), page_count=doc.page_count)


def build_pdf_index(pdf_path) -> PdfTextIndex:
    with fitz.open(str(pdf_path)) as doc:
        return _index_from_doc(doc)


# ---------------------------------------------------------------------------
# 인용 검색
# ---------------------------------------------------------------------------

_MIN_PARTIAL_TOKENS = 8
_MIN_PARTIAL_RATIO = 0.6
_PARTIAL_PAGE_CANDIDATES = 3


def _claim_is_valid(claimed_page, page_count: int) -> bool:
    return isinstance(claimed_page, int) and not isinstance(claimed_page, bool) and 1 <= claimed_page <= page_count


def _unlocated_page_status(claimed_page, page_count: int) -> str:
    if claimed_page is None or _claim_is_valid(claimed_page, page_count):
        return "no_page"
    return "invalid_page"


def _located_page_status(claimed_page, found_page: int, page_count: int) -> str:
    if claimed_page is None:
        return "derived"
    if not _claim_is_valid(claimed_page, page_count):
        return "invalid_page"
    return "match" if claimed_page == found_page else "mismatch"


def _raw_span(page: PageText, start: int, end_exclusive: int) -> str:
    raw_start = page.source_map[start]
    raw_end = page.source_map[end_exclusive - 1] + 1
    return page.raw[raw_start:raw_end]


def _exact_on_page(page: PageText, raw_needle: str) -> str | None:
    return raw_needle if raw_needle and raw_needle in page.raw else None


def _normalized_on_page(page: PageText, normalized_needle: str) -> str | None:
    start = page.normalized.find(normalized_needle)
    if start < 0:
        return None
    return _raw_span(page, start, start + len(normalized_needle))


def _token_char_span(tokens: tuple[str, ...], start: int, size: int) -> tuple[int, int]:
    """정규화 문자열은 토큰을 스페이스 1개로 이은 것이므로 오프셋이 정확히 계산된다."""
    prefix = sum(len(token) + 1 for token in tokens[:start])
    length = sum(len(token) + 1 for token in tokens[start : start + size]) - 1
    return prefix, prefix + length


def _best_partial(index: PdfTextIndex, normalized_needle: str):
    """부분 일치는 '검증'이 아니라 탐색 보조다. 최장 공통 블록 기준으로만 계산한다."""
    quote_tokens = normalized_needle.split(" ")
    if len(quote_tokens) < _MIN_PARTIAL_TOKENS:
        return None
    quote_set = set(quote_tokens)
    ranked = sorted(
        (page for page in index.pages if page.tokens),
        key=lambda page: (-len(quote_set & set(page.tokens)), page.page_number),
    )[:_PARTIAL_PAGE_CANDIDATES]

    best = None
    for page in ranked:
        matcher = difflib.SequenceMatcher(None, quote_tokens, list(page.tokens), autojunk=False)
        block = matcher.find_longest_match(0, len(quote_tokens), 0, len(page.tokens))
        if block.size < _MIN_PARTIAL_TOKENS:
            continue
        ratio = block.size / len(quote_tokens)
        if ratio < _MIN_PARTIAL_RATIO:
            continue
        if best is None or ratio > best[2]:
            start, end = _token_char_span(page.tokens, block.b, block.size)
            best = (page, _raw_span(page, start, end), ratio)
    return best


def find_quote(index: PdfTextIndex, quote: str, claimed_page: int | None) -> QuoteMatch:
    """검색 순서(스펙): 주장 페이지 exact → 주장 페이지 normalized → 전문 exact → 전문 normalized → 부분.

    주장 페이지가 틀렸을 때 발견 페이지로 조용히 고쳐 VERIFIED를 주지 않는다 —
    page_status='mismatch'로 남기고 발견 페이지는 진단 필드로 보존한다.
    """
    raw_needle = str(quote or "").strip()
    normalized_needle = normalize_text(raw_needle)
    page_count = index.page_count

    if not normalized_needle:
        return QuoteMatch("no_quote", _unlocated_page_status(claimed_page, page_count))
    if not index.has_text_layer:
        return QuoteMatch(
            "no_text_layer",
            _unlocated_page_status(claimed_page, page_count),
            failure_detail="empty_text_layer",
        )

    if _claim_is_valid(claimed_page, page_count):
        page = index.pages[claimed_page - 1]
        hit = _exact_on_page(page, raw_needle)
        if hit is not None:
            return QuoteMatch("verified_exact", "match", page.page_number, hit, "exact", 1.0)
        hit = _normalized_on_page(page, normalized_needle)
        if hit is not None:
            return QuoteMatch("verified_normalized", "match", page.page_number, hit, "normalized", 1.0)

    for status, method, finder, needle in (
        ("verified_exact", "exact", _exact_on_page, raw_needle),
        ("verified_normalized", "normalized", _normalized_on_page, normalized_needle),
    ):
        hits = [(page, finder(page, needle)) for page in index.pages]
        hits = [(page, hit) for page, hit in hits if hit is not None]
        if len(hits) == 1:
            page, hit = hits[0]
            return QuoteMatch(
                status,
                _located_page_status(claimed_page, page.page_number, page_count),
                page.page_number,
                hit,
                method,
                1.0,
            )
        if len(hits) > 1:
            page, hit = hits[0]
            return QuoteMatch(
                "ambiguous",
                _unlocated_page_status(claimed_page, page_count),
                page.page_number,
                hit,
                method,
                1.0,
                failure_detail=f"multi_page:{len(hits)}",
            )

    partial = _best_partial(index, normalized_needle)
    if partial is not None:
        page, matched, ratio = partial
        return QuoteMatch(
            "partial_match",
            _unlocated_page_status(claimed_page, page_count),
            page.page_number,
            matched,
            "partial",
            round(ratio, 3),
        )

    return QuoteMatch("not_found", _unlocated_page_status(claimed_page, page_count))


# ---------------------------------------------------------------------------
# bbox
# ---------------------------------------------------------------------------


def locate_bbox(page, matched_quote: str | None) -> list[float] | None:
    """확인된 원문 span의 bbox를 PDF 포인트·좌하단 원점으로 반환한다.

    첫 매치 rect만 쓴다 — 다단 조판에서 union은 과대 박스가 되어 오히려 오해를 만든다
    (스펙 §알려진 위험 3). 실패하면 None이고, UI는 페이지 점프로 폴백한다.
    """
    needle = str(matched_quote or "").strip()
    if not needle:
        return None
    try:
        rects = page.search_for(needle)
        if not rects and len(needle) > 40:
            rects = page.search_for(needle[:40])
        if not rects:
            return None
        rect = rects[0]
        height = float(page.rect.height)
        bbox = [
            round(float(rect.x0), 2),
            round(height - float(rect.y1), 2),
            round(float(rect.x1), 2),
            round(height - float(rect.y0), 2),
        ]
    except Exception:
        return None
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return bbox


# ---------------------------------------------------------------------------
# Recipe 파라미터 순회 (프론트 파서와 규칙이 반드시 같아야 한다)
# ---------------------------------------------------------------------------
# 프론트는 parameters[] 중 object(null 제외)와 string만 화면 행으로 만든다. 백엔드가 다른
# 규칙으로 세면 target_index가 밀려 엉뚱한 파라미터에 근거가 붙는다 — 스펙 §5의 fail-closed
# 조건이 걸리기 전에 애초에 어긋나지 않게 규칙을 맞춘다.

_STRING_PARAM_PATTERN = re.compile(r"^(.+?):\s*(.+)$")


def _first_str(source: dict, *keys: str) -> str:
    """JS의 `a || b || c` 폴백을 그대로 옮긴다(0과 ""는 falsy로 취급)."""
    for key in keys:
        value = source.get(key)
        if value is None or value is False or value == "" or value == 0:
            continue
        return str(value)
    return ""


def _param_from_dict(item: dict) -> dict:
    return {
        "name": _first_str(item, "name", "Name", "parameter", "key"),
        "value": _first_str(item, "value", "Value", "val"),
        "unit": _first_str(item, "unit", "Unit", "units"),
        "notes": _first_str(item, "notes", "Notes", "note", "context"),
        "source_tag": _first_str(item, "source_tag"),
        "evidence_quote": _first_str(item, "evidence_quote"),
        "evidence_page": item.get("evidence_page"),
    }


def _param_from_string(item: str) -> dict:
    match = _STRING_PARAM_PATTERN.match(item)
    if match:
        name, value = match.group(1).strip(), match.group(2).strip()
    else:
        name, value = item, ""
    return {
        "name": name,
        "value": value,
        "unit": "",
        "notes": "",
        "source_tag": "",
        "evidence_quote": "",
        "evidence_page": None,
    }


def iter_recipe_parameters(recipe: dict) -> list[tuple[int, dict]]:
    raw = recipe.get("parameters") if isinstance(recipe, dict) else None
    if not isinstance(raw, list):
        return []
    parsed: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            parsed.append(_param_from_dict(item))
        elif isinstance(item, list):
            parsed.append(_param_from_dict({}))  # JS의 typeof [] === 'object'와 동형
        elif isinstance(item, str):
            parsed.append(_param_from_string(item))
    return list(enumerate(parsed))


def count_recipe_parameters(recipe: dict) -> int:
    return len(iter_recipe_parameters(recipe))


# ---------------------------------------------------------------------------
# 앵커 초안 생성
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceAnchorDraft:
    target_kind: str
    target_key: str
    target_index: int
    target_label: str
    source_tag: str | None
    claimed_quote: str
    claimed_page: int | None
    quote_status: str
    page_status: str
    value_status: str
    display_status: str
    match_method: str | None
    match_ratio: float | None
    matched_quote: str | None
    matched_page: int | None
    bbox_json: str | None
    corpus: str
    failure_detail: str | None
    verifier_version: str
    normalizer_version: str


def _coerce_page(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _draft(
    param_index: int,
    param: dict,
    *,
    quote_status: str,
    page_status: str,
    value_status: str,
    match_method: str | None = None,
    match_ratio: float | None = None,
    matched_quote: str | None = None,
    matched_page: int | None = None,
    bbox: list[float] | None = None,
    failure_detail: str | None = None,
) -> EvidenceAnchorDraft:
    name = param.get("name", "")
    return EvidenceAnchorDraft(
        target_kind="recipe_parameter",
        target_key=build_target_key(param_index, name),
        target_index=param_index,
        target_label=name,
        source_tag=param.get("source_tag") or None,
        claimed_quote=str(param.get("evidence_quote") or ""),
        claimed_page=_coerce_page(param.get("evidence_page")),
        quote_status=quote_status,
        page_status=page_status,
        value_status=value_status,
        display_status=derive_display_status(quote_status, page_status, value_status),
        match_method=match_method,
        match_ratio=match_ratio,
        matched_quote=matched_quote,
        matched_page=matched_page,
        bbox_json=json.dumps(bbox) if bbox else None,
        corpus=EVIDENCE_CORPUS_PDF_TEXT,
        failure_detail=failure_detail,
        verifier_version=EVIDENCE_VERIFIER_VERSION,
        normalizer_version=EVIDENCE_NORMALIZER_VERSION,
    )


def _unverifiable(param_index: int, param: dict, quote_status: str, detail: str) -> EvidenceAnchorDraft:
    value_status, _ = check_value_in_quote(param.get("value", ""), param.get("source_tag"), None)
    return _draft(
        param_index,
        param,
        quote_status=quote_status,
        page_status="no_page",
        value_status=value_status,
        failure_detail=detail,
    )


def _verify_parameter(doc, index: PdfTextIndex, param_index: int, param: dict) -> EvidenceAnchorDraft:
    try:
        match = find_quote(index, param.get("evidence_quote", ""), _coerce_page(param.get("evidence_page")))
        value_status, value_detail = check_value_in_quote(
            param.get("value", ""), param.get("source_tag"), match.matched_quote
        )
        bbox = None
        if match.matched_page is not None and match.matched_quote:
            bbox = locate_bbox(doc[match.matched_page - 1], match.matched_quote)
        return _draft(
            param_index,
            param,
            quote_status=match.quote_status,
            page_status=match.page_status,
            value_status=value_status,
            match_method=match.match_method,
            match_ratio=match.match_ratio,
            matched_quote=match.matched_quote,
            matched_page=match.matched_page,
            bbox=bbox,
            failure_detail=match.failure_detail or value_detail,
        )
    except Exception as exc:  # 파라미터 하나의 실패가 나머지를 죽이지 않는다
        return _unverifiable(param_index, param, "verifier_error", type(exc).__name__)


def verify_recipe_parameters(recipe: dict, pdf_path=None) -> list[EvidenceAnchorDraft]:
    """파라미터마다 앵커 초안을 정확히 1건씩 만든다. 실패도 앵커로 남긴다(침묵 금지)."""
    parameters = iter_recipe_parameters(recipe)
    if not parameters:
        return []

    path = Path(pdf_path) if pdf_path else None
    if path is None or not path.exists():
        return [_unverifiable(i, p, "no_text_layer", "pdf_missing") for i, p in parameters]

    try:
        with fitz.open(str(path)) as doc:
            index = _index_from_doc(doc)
            if not index.has_text_layer:
                return [_unverifiable(i, p, "no_text_layer", "empty_text_layer") for i, p in parameters]
            return [_verify_parameter(doc, index, i, p) for i, p in parameters]
    except Exception as exc:
        return [_unverifiable(i, p, "verifier_error", type(exc).__name__) for i, p in parameters]
