"""표 라벨 파싱 — 로마 숫자를 포함한 확장 라벨 규칙 (측정 전용).

`services.document_manifest.TABLE_LABEL_PATTERN`은 digit-only라 IEEE 계열의
`Table I`~`Table VIII`을 통째로 못 본다. 정답 기준을 그 정규식으로 세우면
2017_COMST의 정답이 0이 되므로, 측정 하네스는 확장 규칙을 쓴다.

로마 숫자는 **대문자만** 인정하고 형태를 검증한다. `[IVXLC]{1,6}`를 대소문자
무시로 쓰면 "Table ill-conditioned ..."의 "ill"이 로마 숫자로 매칭된다.
"""

from __future__ import annotations

import re
import unicodedata

# "Table" / "TABLE" / "Tbl." 뒤에 오는 라벨 토큰을 통째로 잡고 파이썬에서 검증한다.
# 정규식 하나로 아라비아·로마를 모두 안전하게 가르려 하면 빈 매칭·오탐이 생긴다.
TABLE_LABEL_EXT_PATTERN = re.compile(r"^\s*(?:table|tbl\.?)\s*([A-Za-z0-9]{1,7})\b", re.IGNORECASE)

# 표 번호로 실제로 쓰이는 범위(I~XXXIX)만 인정한다. 엄격한 형태 검증이라
# "ILL", "VV" 같은 것은 떨어진다.
_ROMAN_PATTERN = re.compile(r"^(?:X{0,3})(?:IX|IV|V?I{0,3})$")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}

_ARABIC_PATTERN = re.compile(r"^(\d{1,2})([A-Za-z]?)$")


def roman_to_int(token: str) -> int:
    total = 0
    previous = 0
    for char in reversed(token):
        value = _ROMAN_VALUES[char]
        total += -value if value < previous else value
        previous = max(previous, value)
    return total


def parse_table_label_token(token: str) -> tuple[str, int, str] | None:
    """라벨 토큰을 (표기법, 번호, 접미사)로 파싱한다. 표 라벨이 아니면 None.

    >>> parse_table_label_token("VIII")
    ('roman', 8, '')
    >>> parse_table_label_token("2a")
    ('arabic', 2, 'a')
    >>> parse_table_label_token("ill")
    """
    arabic = _ARABIC_PATTERN.match(token)
    if arabic:
        return ("arabic", int(arabic.group(1)), arabic.group(2).lower())
    if token and token == token.upper() and _ROMAN_PATTERN.match(token):
        return ("roman", roman_to_int(token), "")
    return None


def match_table_label(text: str) -> tuple[str, int, str, int] | None:
    """문두에서 표 라벨을 찾아 (표기법, 번호, 접미사, 매치 끝 오프셋)을 돌려준다.

    입력은 NFKC 정규화·장식 제거를 **끝낸** 텍스트여야 한다.
    """
    match = TABLE_LABEL_EXT_PATTERN.match(text)
    if not match:
        return None
    parsed = parse_table_label_token(match.group(1))
    if parsed is None:
        return None
    notation, number, suffix = parsed
    return (notation, number, suffix, match.end())


def canonical_label(notation: str, number: int, suffix: str = "") -> str:
    """gold 파일에 적는 표기. 로마는 원문 표기를 유지한다(`Table I`)."""
    if notation == "roman":
        return f"Table {int_to_roman(number)}"
    return f"Table {number}{suffix.upper()}"


def int_to_roman(value: int) -> str:
    numerals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = []
    for amount, numeral in numerals:
        while value >= amount:
            out.append(numeral)
            value -= amount
    return "".join(out)


def normalize(text: str | None) -> str:
    """캡션 장식 제거 + NFKC. 제품 코드와 같은 순서를 지킨다."""
    from services.document_manifest import strip_caption_decoration

    return unicodedata.normalize("NFKC", strip_caption_decoration(text or ""))
