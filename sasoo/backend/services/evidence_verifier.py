"""evidence_verifier — Recipe 파라미터 근거의 결정론적 검증기.

원칙(docs/superpowers/specs/2026-08-06-evidence-anchoring-design.md):
- LLM 후보를 다른 LLM 전사본으로 확인하지 않는다. 대조 원본은 PDF 텍스트층뿐이다.
- 유사도·편집거리·임베딩을 검증에 쓰지 않는다. 실측상 숫자 한 자리를 바꾼 위조 인용이
  임계 0.6에서 81.1%, 0.8에서도 52.0% 통과한다. 정규화 완전일치만 0.0%다.
- partial_match는 탐색 보조일 뿐 검증이 아니다.
- 상태는 직교 3필드(quote/page/value)로 저장하고 표시 상태 1개를 결정론 규칙으로 파생한다.
"""

from __future__ import annotations

import re
import unicodedata

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

    # 0~4단계: 문자 단위 치환. 각 출력 문자는 자기가 유래한 원문 인덱스를 들고 다닌다.
    pairs: list[tuple[str, int]] = []
    for index, char in enumerate(text):
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

_NUMBER_LITERAL = re.compile(r"\d+(?:\.\d+)?")


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
    needles = numbers or [normalized_value]
    for needle in needles:
        if needle not in normalized_quote:
            return ("value_missing", f"missing:{needle[:24]}")
    return ("value_in_quote", None)
