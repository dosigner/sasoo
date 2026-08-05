"""
Sasoo - LLM client helpers.
Shared utilities for calling Gemini APIs.
"""

import json
import zlib
from typing import Optional


# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------

from services.llm.interactions_client import _SYSTEM_INSTRUCTION_KO  # noqa: F401 - 단일 소스 재노출


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _clean_llm_json(text: str) -> str:
    """
    Strip markdown code fences from LLM JSON responses.
    LLMs often return ```json ... ``` wrapped responses.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove opening fence (```json or ```)
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        # Remove closing fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


# ---------------------------------------------------------------------------
# Degenerate repetition detection
# ---------------------------------------------------------------------------

# 반복 루프에 빠진 출력은 소수 단어의 순열이 수백 번 되풀이되므로
# 단어 다양성이 극단적으로 낮다. 자연어(한국어·영어)는 50단어 창에서
# 고유 비율이 통상 0.4 이상이라 0.15는 안전한 여유를 가진다.
_DEGEN_WINDOW = 50
_DEGEN_UNIQUE_RATIO = 0.15
_DEGEN_MIN_CHARS = 300
_DEGEN_ZLIB_MIN_BYTES = 500
_DEGEN_ZLIB_RATIO = 0.05


def _is_degenerate_string(text: str) -> bool:
    """문자열이 LLM 반복 루프(degenerate repetition) 출력인지 판정한다."""
    if len(text) < _DEGEN_MIN_CHARS:
        return False
    raw = text.encode("utf-8")
    # 공백 없이 이어지는 반복까지 잡는 언어 무관 검사 — 루프 출력은 극단적으로 잘 압축된다
    if len(raw) >= _DEGEN_ZLIB_MIN_BYTES:
        if len(zlib.compress(raw, 6)) / len(raw) < _DEGEN_ZLIB_RATIO:
            return True
    words = text.split()
    if len(words) < _DEGEN_WINDOW:
        return False
    # 정상 서술 뒤에 루프가 붙는 경우가 있어 슬라이딩 창으로 국소 구간을 본다
    step = _DEGEN_WINDOW // 2
    for i in range(0, len(words) - _DEGEN_WINDOW + 1, step):
        window = words[i:i + _DEGEN_WINDOW]
        if len(set(window)) / len(window) < _DEGEN_UNIQUE_RATIO:
            return True
    return False


def _has_degenerate_repetition(data) -> bool:
    """파싱된 JSON 값 전체를 훑어 반복 루프에 오염된 문자열 필드를 찾는다."""
    if isinstance(data, str):
        return _is_degenerate_string(data)
    if isinstance(data, dict):
        return any(_has_degenerate_repetition(v) for v in data.values())
    if isinstance(data, list):
        return any(_has_degenerate_repetition(v) for v in data)
    return False


def _stage_result_defect(text: str) -> Optional[str]:
    """스테이지 결과 텍스트의 재시도 사유를 찾는다. 정상이면 None.

    JSON 파싱 실패뿐 아니라, 파싱은 되지만 필드 값 안에서 반복 루프가
    발생한 경우(스키마 강제 출력을 통과하는 오염)도 잡는다."""
    try:
        parsed = json.loads(_clean_llm_json(text or ""))
    except (json.JSONDecodeError, TypeError):
        return "JSON parse failed"
    if _has_degenerate_repetition(parsed):
        return "degenerate repetition detected"
    return None


def _is_error_result(text: str) -> bool:
    """Check if an LLM result text indicates an error."""
    if not text or not text.strip():
        return True
    try:
        data = json.loads(text)
        return "_parse_error" in data or "error" in data
    except (json.JSONDecodeError, TypeError):
        return False
